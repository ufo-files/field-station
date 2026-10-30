#!/usr/bin/env python3
"""Pi-controlled, one-shot unlisted YouTube Live trial on the remote M1."""
from datetime import datetime,timezone
import json
from pathlib import Path
import shlex
import signal
import subprocess
import threading
import time
from urllib.parse import urlencode
from experiments import load
from m1_encode import ssh_args
from youtube_api import YouTubeAPI,YouTubeError,private_save

ROOT=Path(__file__).resolve().parent
STATE=ROOT/'private/m1/live-state.json'
STATUS=ROOT/'run/youtube-live.json'
CHANNEL='UCQA8_F18kJhUA1hE0MpyHug'


def post(api,resource,body=None,**params):
    return api.raw('POST','https://www.googleapis.com/youtube/v3/'+resource+'?'+urlencode(params),
        json.dumps(body).encode() if body is not None else b'',{'Content-Type':'application/json'},auth=True)[2]


def prepare(api,state):
    api.channel(CHANNEL)
    api.list('liveBroadcasts',part='id',mine='true',maxResults=1)
    if not state.get('stream_id'):
        stream=post(api,'liveStreams',dict(snippet=dict(title='Field station M1 test'),
            cdn=dict(frameRate='30fps',resolution='720p',ingestionType='rtmp'),contentDetails=dict(isReusable=True)),part='id,snippet,cdn,contentDetails')
        info=stream['cdn']['ingestionInfo'];address=info.get('rtmpsIngestionAddress')
        if not address:raise ValueError('YouTube did not provide an encrypted ingestion endpoint')
        state.update(stream_id=stream['id'],publish_url=address.rstrip('/')+'/'+info['streamName']);private_save(STATE,state)
    if not state.get('broadcast_id'):
        broadcast=post(api,'liveBroadcasts',dict(snippet=dict(title='UFO Files Project — station live test',
            description='Unlisted 10-minute camera test. Pi capture and M1 remote encoding. Silent audio.',
            scheduledStartTime=datetime.now(timezone.utc).isoformat()),
            status=dict(privacyStatus='unlisted',selfDeclaredMadeForKids=False),
            contentDetails=dict(enableAutoStart=True,enableAutoStop=False,enableDvr=True,monitorStream=dict(enableMonitorStream=False))),part='id,snippet,status,contentDetails')
        state.update(broadcast_id=broadcast['id']);private_save(STATE,state)
    post(api,'liveBroadcasts/bind',id=state['broadcast_id'],streamId=state['stream_id'],part='id,contentDetails')
    return state


def main():
    stop=threading.Event();proc=None
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
    api=YouTubeAPI(ROOT/'private/youtube');state=load(STATE,{})
    if state.get('finished'):
        private_save(STATUS,dict(phase='test_completed',watch_url=state.get('watch_url')));return
    try:
        while not stop.is_set():
            try:
                config=load(ROOT/'private/m1/config.json',{})
                if not config.get('enabled'):raise ValueError('M1 worker disabled')
                state=prepare(api,state);watch='https://www.youtube.com/watch?v='+state['broadcast_id']
                state['watch_url']=watch
                state.setdefault('test_deadline_epoch',time.time()+600)
                private_save(STATE,state)
                remaining=max(0,int(state['test_deadline_epoch']-time.time()))
                if not remaining:
                    result=api.list('liveBroadcasts',part='status',id=state['broadcast_id'])
                    phase=next(iter(result.get('items',[])),{}).get('status',{}).get('lifeCycleStatus')
                    if phase in ('live','testing'):
                        post(api,'liveBroadcasts/transition',id=state['broadcast_id'],broadcastStatus='complete',part='id,status')
                    state.update(finished=True);private_save(STATE,state)
                    private_save(STATUS,dict(phase='test_completed',watch_url=watch));return
                command='/usr/bin/caffeinate -is /usr/bin/python3 '+shlex.quote(str(Path(config['worker']).with_name('m1_live.py')))
                with (ROOT/'private/m1/live-encoder.log').open('w') as log:
                    proc=subprocess.Popen(ssh_args(config)+[command],stdin=subprocess.PIPE,stdout=log,stderr=log,text=True)
                    proc.stdin.write(json.dumps(dict(publish_url=state['publish_url'],source='http://100.117.92.45:8090/preview.mjpeg?fps=30',duration_seconds=remaining))+'\n');proc.stdin.close()
                    began=time.monotonic()
                    while proc.poll() is None and not stop.wait(15):
                        result=api.list('liveBroadcasts',part='status',id=state['broadcast_id'])
                        phase=next(iter(result.get('items',[])),{}).get('status',{}).get('lifeCycleStatus','starting')
                        private_save(STATUS,dict(phase=phase,watch_url=watch,resolution='720p',output_fps=30,encoder_worker='m1'))
                        if time.monotonic()-began>900:raise OSError('Live trial exceeded its time limit')
                    if stop.is_set():break
                    if proc.returncode:raise OSError('M1 live encoder disconnected')
                post(api,'liveBroadcasts/transition',id=state['broadcast_id'],broadcastStatus='complete',part='id,status')
                state.update(finished=True);private_save(STATE,state)
                private_save(STATUS,dict(phase='test_completed',watch_url=watch));return
            except (OSError,ValueError,KeyError) as error:
                if proc and proc.poll() is None:proc.terminate();proc.wait(timeout=10)
                phase='waiting_youtube_activation' if isinstance(error,YouTubeError) and error.reason in ('liveStreamingNotEnabled','livePermissionBlocked') else 'waiting_retry'
                private_save(STATUS,dict(phase=phase,error=str(error),retry_policy='manual_only'))
                return
    finally:
        if proc and proc.poll() is None:proc.terminate();proc.wait(timeout=10)

if __name__=='__main__':main()

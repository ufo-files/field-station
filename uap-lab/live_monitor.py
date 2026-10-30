"""Saved-model live tagging, confirmed station events, and native postprocessing."""
import json,os,threading,time,urllib.request,urllib.error
import cv2
import numpy as np
import lab
from live_matcher import LiveMatcher

class Confirmation:
    """Confirm each spatial track separately; another object's confidence cannot substitute."""
    def __init__(self):self.tracks=[];self.count=0;self.confirmed=[];self.sequence=0
    def update(self,matches,now):
        candidates=[m for m in matches if m['label']=='anomalous'];remaining=list(self.tracks);tracks=[];self.confirmed=[]
        for match in candidates:
            x,y,w,h=match['box'];cx,cy=x+w/2,y+h/2
            options=[t for t in remaining if now-t['time']<3 and abs(cx-t['cx'])+abs(cy-t['cy'])<=max(80,3*max(w,h))]
            prior=min(options,key=lambda t:abs(cx-t['cx'])+abs(cy-t['cy'])) if options else None
            if prior:remaining.remove(prior)
            else:self.sequence+=1
            track=dict(cx=cx,cy=cy,time=now,count=prior['count']+1 if prior else 1,id=prior['id'] if prior else self.sequence)
            tracks.append(track)
            if track['count']>=3:self.confirmed.append(dict(match,target_id=track['id']))
        self.tracks=tracks;self.count=max((t['count'] for t in tracks),default=0)
        return bool(self.confirmed)

class LiveMonitor:
    def __init__(self,preview_path=None,start_workers=True):
        self.preview_path=lab.Path(preview_path or str(lab.Path(os.environ.get('XDG_RUNTIME_DIR',f'/run/user/{os.getuid()}'))/'field-station/preview.jpg'));self.stop_event=threading.Event()
        self.folder=lab.DATA/'live';self.folder.mkdir(exist_ok=True)
        self.config=lab.read(self.folder/'config.json',dict(enabled=True,threshold=.97))
        self.state=dict(enabled=self.config['enabled'],phase='starting',objects=[],motion_objects=[],events=lab.read(self.folder/'events.json',[]))
        self.image=None;self.token=None;self.model_id=None;self.templates=None;self.gate=Confirmation();self.frame_stamp=None;self.next_capture_attempt=0;self.station_url='http://127.0.0.1:8090';self.lock=threading.RLock()
        if start_workers:
            from native_capture import NativeCapture
            if os.environ.get("UAP_NATIVE_EXTERNAL")!="1":
                self.native_capture=NativeCapture(self);self.native_capture.start()
            threading.Thread(target=self.preview_work,daemon=True).start()
            threading.Thread(target=self.work,daemon=True).start()
            threading.Thread(target=self.postprocess,daemon=True).start()
    def configure(self,body):
        enabled=body.get('enabled')
        if not isinstance(enabled,bool):raise ValueError('Enabled must be true or false')
        with self.lock:
            self.config['enabled']=enabled;lab.save(self.folder/'config.json',self.config);self.state['enabled']=enabled
            if not enabled:self.gate=Confirmation();self.state['objects']=[];self.state.pop('recording',None)
        return self.state
    def station(self,path,body=None,retry=True):
        if body is not None and not self.token:self.token=self.station('/api/session')['csrf']
        request=urllib.request.Request(self.station_url+path,data=None if body is None else json.dumps(body).encode(),headers={} if body is None else {'Content-Type':'application/json','X-Station-Token':self.token})
        try:
            with urllib.request.urlopen(request,timeout=15) as response:return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code==403:
                self.token=None
                if body is not None and retry:return self.station(path,body,retry=False)
            raise ValueError(exc.read().decode(errors='replace')[:500])
    def preview_work(self):
        """Fresh preview runs independently of model inference."""
        path=self.preview_path
        while not self.stop_event.is_set():
            try:
                analyzed=None
                if os.environ.get('UAP_NATIVE_EXTERNAL')=='1':
                    try:
                        from recognition.recognition_preview import unpack
                        metadata,jpeg=unpack((lab.DATA/'recognition/preview.bin').read_bytes())
                        if 0<=time.time()-metadata['source_received_epoch']<3:analyzed=(metadata,jpeg)
                    except (OSError,ValueError,KeyError):pass
                if analyzed:
                    metadata,jpeg=analyzed;stamp=metadata['source_received_epoch'];w=metadata['width'];h=metadata['height'];raw_jpeg=jpeg
                    self.state.update(preview_mode='analyzed',display_tags=metadata['tags'],display_sequence=metadata['sequence'],display_generation=metadata['generation'],display_model=metadata['model'])
                else:
                    with path.open('rb') as stream:raw=stream.read();stamp=os.fstat(stream.fileno()).st_mtime
                    if time.time()-stamp>3:raise ValueError('Camera preview is not fresh')
                    image=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
                    if image is None:raise ValueError('Camera frame could not be decoded')
                    h,w=image.shape[:2]
                    if w>1280:image=cv2.resize(image,(1280,round(h*1280/w)),interpolation=cv2.INTER_AREA);h,w=image.shape[:2]
                    ok,jpeg=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,80])
                    if not ok:raise ValueError('Camera preview encoding failed')
                    raw_jpeg=jpeg.tobytes();self.state.update(preview_mode='camera_unannotated',display_tags=[])
                if os.environ.get('UAP_NATIVE_EXTERNAL')=='1':
                    self.state['native_analysis']=lab.read(self.folder/'native-analysis.json',{})
                    q=lab.read(lab.DATA/'qualification/current.json',{})
                    self.state['qualification']={key:q.get(key) for key in ['state','clean_seconds','required_seconds','current_faults','failing_samples','scientific_ready']}
                with self.lock:self.image=raw_jpeg;self.state.update(frame_epoch=stamp,preview_error=None,width=w,height=h,motion_objects=[])
            except Exception as exc:
                with self.lock:self.state.update(preview_error=str(exc),motion_objects=[])
            self.stop_event.wait(.2)
    def session_status(self):
        result=self.station('/api/session');result.pop('csrf',None)
        result['recent_manual']=lab.read(self.folder/'manual-sessions.json',[])[-20:]
        return result
    def manual_start(self,body):
        active=self.session_status().get('active')
        if active and active.get('capture_origin')=='provisional_motion':
            result=self.station('/api/provisional/manual',dict(session_id=active['id']))
        elif active:raise ValueError('A session is already recording')
        else:result=self.station('/api/start',dict(title='Manual live session',condition='silence',minutes=120,notes='Started manually from the observation-model Live view.'))
        record=dict(session_id=result['id'],created=time.time(),kind='manual')
        records=lab.read(self.folder/'manual-sessions.json',[]);records.append(record);lab.save(self.folder/'manual-sessions.json',records)
        return dict(session_id=result['id'],state='recording')
    def manual_stop(self,body):
        active=self.session_status().get('active')
        if not active:raise ValueError('No session is recording')
        if body.get('session_id')!=active['id']:raise ValueError('Session changed. Refresh the live status before stopping.')
        result=self.station('/api/stop',dict(expected_session_id=active['id']));self.gate=Confirmation();self.next_capture_attempt=max(self.next_capture_attempt,time.monotonic()+3);return dict(session_id=active['id'],state='stopped')
    def work(self):
        preview=self.preview_path
        while True:
            started=time.monotonic()
            try:
                model=lab.read(lab.DATA/'active-model.json')
                if os.environ.get('CAPTURE_DURABLE_SPOOL')=='1':
                    self.model_id=model['id'] if model else None
                    with self.lock:self.state.update(phase='capture_first',model_id=self.model_id,objects=[],performance=dict(method='every-native-frame motion, local appearance and temporal suggestions'),error=None)
                    self.stop_event.wait(1);continue
                if model and model['id']!=self.model_id:
                    self.templates=lab.model_templates(model);self.matcher=LiveMatcher(self.templates);self.model_id=model['id'];self.gate=Confirmation()
                if time.time()-preview.stat().st_mtime>3:raise ValueError('Camera preview is not fresh')
                with preview.open('rb') as stream:
                    raw=stream.read();frame_stat=os.fstat(stream.fileno())
                stamp=frame_stat.st_mtime_ns
                if stamp==self.frame_stamp:time.sleep(.2);continue
                self.frame_stamp=stamp;image=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
                if image is None:raise ValueError('Camera frame could not be decoded')
                h,w=image.shape[:2];objects=[]
                if self.config['enabled'] and model:
                    self.state.update(phase='analyzing',analysis_started_epoch=time.time(),model_id=model['id'])
                    objects,performance=self.matcher.predict(image,self.config['threshold'],model['classes']);objects=[m for m in objects if m['label']!='cloud'];self.state['performance']=performance
                    confirmed=self.gate.update(objects,time.monotonic())
                    tracks=iter(self.gate.tracks)
                    objects=[dict(m,target_id=t['id'],confirmed=t['count']>=3) if m['label']=='anomalous' and (t:=next(tracks,None)) else m for m in objects]
                    if confirmed and self.config['enabled'] and time.monotonic()>=self.next_capture_attempt:
                        self.next_capture_attempt=time.monotonic()+2
                        try:
                            snapshot=lab.Path(os.environ.get('XDG_RUNTIME_DIR',f'/run/user/{os.getuid()}'))/'uap-lab-detection.jpg';temp=snapshot.with_suffix('.tmp');temp.write_bytes(raw);temp.replace(snapshot)
                            result=self.station('/api/lab/detection',dict(model_id=model['id'],frame_epoch=frame_stat.st_mtime,frame_sha256=lab.hashlib.sha256(raw).hexdigest(),width=w,height=h,objects=self.gate.confirmed[:20]))
                            self.state.pop('capture_error',None)
                            if result.get('session_id'):
                                with self.lock:
                                    entry=next((e for e in self.state['events'] if e['event_id']==result['event_id']),None)
                                    if entry is None:self.state['events'].append(dict(**result,created=time.time(),postprocessing='waiting'));lab.save(self.folder/'events.json',self.state['events'])
                                    elif entry.get('target_count')!=result.get('target_count'):
                                        entry.update(target_count=result.get('target_count'),target_ids=result.get('target_ids',[]));lab.save(self.folder/'events.json',self.state['events'])
                                self.state['recording']=result
                        except Exception as exc:self.state['capture_error']=str(exc)
                    if not any(m['label']=='anomalous' for m in objects):self.state.pop('recording',None)
                else:self.gate=Confirmation()
                with self.lock:
                    self.state.update(enabled=self.config['enabled'],phase='tagging' if self.config['enabled'] and model else 'waiting_for_model' if not model else 'paused',model_id=self.model_id,objects=objects,inference_epoch=frame_stat.st_mtime,inference_completed_epoch=time.time(),inference_seconds=round(time.monotonic()-started,3),width=w,height=h,error=None,confirmation_frames=self.gate.count)
            except Exception as exc:
                with self.lock:self.state.update(phase='error',error=str(exc))
            time.sleep(max(.1,1-(time.monotonic()-started)))
    def postprocess(self):
        observed={}
        while True:
            try:
                with self.lock:events=list(self.state['events'])
                for event in events:
                    if event.get('run_id') or event.get('postprocessing')=='complete':continue
                    sourcefolder=lab.STATION/'sessions'/event['session_id'];manifest=lab.read(sourcefolder/'manifest.json',{})
                    if manifest.get('state') in ('recording',None):continue
                    buffer_state=lab.read(sourcefolder/'buffer-state.json',{})
                    if manifest.get('buffered_capture') and buffer_state.get('state')!='assembled':continue
                    source=sourcefolder/'video.mkv'
                    if not source.is_file():continue
                    sig=(source.stat().st_size,source.stat().st_mtime_ns);prior=observed.get(event['event_id'])
                    if prior is None or prior[0]!=sig:observed[event['event_id']]=(sig,time.monotonic());continue
                    if time.monotonic()-prior[1]<10:continue
                    model=lab.read(lab.DATA/'models'/event['model_id']/'model.json')
                    if not model:continue
                    vid=lab.hashlib.sha256(('live:'+event['session_id']).encode()).hexdigest()[:32];folder=lab.video_path(vid);folder.mkdir(exist_ok=True)
                    if not (folder/'source').exists():os.link(source,folder/'source')
                    if not (folder/'video.json').exists():
                        meta=lab.probe(source);meta.update(id=vid,name='Live event '+event['session_id'],created=event['created'],mime='video/x-matroska',provenance=dict(collection='live-event',session_id=event['session_id'],model_id=event['model_id']));lab.save(folder/'video.json',meta)
                        lab.save(folder/'review.json',dict(completed=True,automated_event=True))
                    try:rid=lab.start_run(vid,.97,['anomalous'],model=model)
                    except ValueError:continue
                    runfolder=lab.DATA/'runs'/rid
                    for name in ('rf.jsonl','manifest.json'):
                        if (sourcefolder/name).is_file():lab.shutil.copyfile(sourcefolder/name,runfolder/('source-'+name))
                    with self.lock:event.update(run_id=rid,postprocessing='started');lab.save(self.folder/'events.json',self.state['events'])
            except Exception as exc:print('Live postprocessing:',str(exc),flush=True)
            time.sleep(5)

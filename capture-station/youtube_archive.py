"""Per-clip public uploads; confirm server processing before video-only cleanup."""
import hashlib
import json
import re
import threading
import time
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlencode
from experiments import load,save,file_info
from youtube_api import YouTubeAPI,YouTubeError,private_save

CHANNEL_ID='UCQA8_F18kJhUA1hE0MpyHug'
SID=re.compile(r'[0-9TZ]+-[a-f0-9]{6}')
VIDEO_ID=re.compile(r'[A-Za-z0-9_-]{11}')


class YouTubeArchive:
    def __init__(self,station,root,data,storage,api=None,start=True):
        self.station,self.root,self.data,self.storage=station,Path(root),Path(data),storage
        self.private=self.root/'private'/'youtube'
        self.catalog=self.root/'catalog'/'sessions';self.catalog.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.jobs=self.private/'jobs';self.jobs.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.api=api or YouTubeAPI(self.private)
        self.job_cache={p.stem:load(p,{}) for p in self.jobs.glob('*.json')}
        self.config_path=self.private/'settings.json'
        self.config=dict(enabled=True,privacy='public',cleanup='videos',daily_upload_limit=100,retention_seconds=0,
                         channel_id=CHANNEL_ID,channel_handle='@ufofilesproject')
        self.config.update(load(self.config_path,{}))
        self.preparation_counts={}
        self.phase='waiting_credentials';self.error=None;self.current=None;self.next_discovery=0
        self.wake=threading.Event()
        self.worker=threading.Thread(target=self.work,daemon=True)
        if start:self.worker.start()

    def session_folder(self,sid):
        if not SID.fullmatch(sid):raise ValueError('Invalid session ID')
        folder=self.data/sid
        if folder.is_symlink() or not folder.resolve().is_relative_to(self.data.resolve()):
            raise ValueError('Unsafe session path')
        return folder

    def import_credentials(self,body=None):
        candidates=[self.root.parent/'youtube.oauth.json',self.data.parent/'Uploads'/'youtube.oauth.json']
        source=next((p for p in candidates if p.is_file() and not p.is_symlink()),None)
        if source is None:
            downloaded=[p for p in (self.data.parent/'Uploads').glob('client_secret_*.apps.googleusercontent.com.json') if p.is_file() and not p.is_symlink()]
            if len(downloaded)==1:source=downloaded[0]
        if source is None:raise ValueError('Save the downloaded OAuth client JSON as youtube.oauth.json in the T7 Uploads folder.')
        value=json.loads(source.read_text())
        self.configure_client(value)
        source.unlink() # Move the OAuth secret out of the SMB share after protected storage is durable.
        return dict(configured=True)

    def status(self):
        jobs=list(self.job_cache.values())
        states={}
        for job in jobs:states[job.get('state','queued')]=states.get(job.get('state','queued'),0)+1
        current=next((j for j in jobs if j.get('id')==self.current),{})
        return dict(**self.config,phase=self.phase,error=self.error,auth=self.api.auth_status(),counts=states,preparation_counts=self.preparation_counts,
            current=dict(id=current.get('id'),state=current.get('state'),uploaded_bytes=current.get('offset',0),
                total_bytes=current.get('source',{}).get('bytes',0),url=current.get('url')),
            connected_channel=load(self.private/'channel.json'))

    def configure(self,body):
        cfg=self.config.copy()
        if 'privacy' in body:
            if body['privacy'] not in ('public','unlisted','private'):raise ValueError('Unknown upload visibility')
            cfg['privacy']=body['privacy']
        if 'enabled' in body:cfg['enabled']=bool(body['enabled'])
        if 'daily_upload_limit' in body:
            value=int(body['daily_upload_limit'])
            if value!=float(body['daily_upload_limit']) or not 1<=value<=10000:raise ValueError('Daily upload limit must be 1–10000')
            cfg['daily_upload_limit']=value
        # Retention is deliberately fixed to the user's authorization: videos only.
        self.config=cfg;private_save(self.config_path,cfg);self.wake.set();return self.status()

    def configure_client(self,body):
        self.api.set_client(body)
        (self.private/'channel.json').unlink(missing_ok=True)
        return dict(configured=True)

    def connect(self,body=None):
        result=self.api.start_auth();self.wake.set();return result

    def retry(self,body):
        sid=str(body.get('id',''))
        if not SID.fullmatch(sid):raise ValueError('Invalid session ID')
        path=self.jobs/(sid+'.json');job=load(path)
        if not job:raise ValueError('Upload job not found')
        if job['state']=='needs_review':
            raise ValueError('Upload completion is uncertain. Local files are retained; do not restart blindly and create a duplicate.')
        if job['state']=='cleaned':return dict(state='cleaned')
        job.update(next_attempt=0,error=None)
        if job['state']=='failed':job['state']='verifying' if job.get('video_id') else 'uploading' if job.get('upload_url') else 'queued'
        self.persist(job);self.wake.set();return dict(state=job['state'])

    def persist(self,job):
        private_save(self.jobs/(job['id']+'.json'),job)
        self.job_cache[job['id']]=dict(job)

    def receipt(self,job,state=None):
        return dict(state=state or job['state'],video_id=job.get('video_id'),url=job.get('url'),
            channel_id=job['channel_id'],privacy=job['privacy'],uploaded_at=job.get('uploaded_at'),
            verified_at=job.get('verified_at'),uploaded_file=job['source'],cleanup='videos_only',
            cleaned_files=job.get('cleaned_files',[]),cleanup_plan=job.get('cleanup_plan',[]),error=job.get('error'))

    def publish(self,job,state=None):
        with self.station.lock:
            path=self.session_folder(job['id'])/'manifest.json'
            manifest=load(path) if self.storage()['available'] else None
            manifest=manifest or load(self.catalog/(job['id']+'.json')) or job.get('manifest',{})
            if not manifest:raise ValueError('No session metadata available')
            manifest['youtube']=self.receipt(job,state)
            if job['state']=='cleaned':
                for entry in job.get('cleanup_plan',[]):manifest.setdefault('files',{}).pop(entry['file'],None)
                if not manifest.get('internet_archive',{}).get('verified_at'):manifest['video_playback']=dict(state='youtube',url=job['url'],frame_count=job['source'].get('frame_count'))
            # The SD catalog is durably committed before touching SSD video files.
            save(self.catalog/(job['id']+'.json'),manifest)
            if self.storage()['available'] and path.exists():save(path,manifest)

    def discover(self):
        if not self.storage()['available']:return
        preparation={}
        for path in sorted(self.data.glob('*/manifest.json')):
            m=load(path,{})
            if m.get('state')=='recording':
                preparation['recording']=preparation.get('recording',0)+1
            if m.get('state') not in ('completed','interrupted') or not SID.fullmatch(m.get('id','')):continue
            existing=load(self.jobs/(m['id']+'.json'))
            if existing:
                if existing.get('state')=='cleaned' and m.get('youtube',{}).get('state')!='cleaned':self.publish(existing)
                continue
            folder=self.session_folder(m['id'])
            source=folder/'video.mp4'
            if source.is_symlink():continue
            if m.get('video_playback',{}).get('state')!='completed' or not source.is_file():
                stage='preparation_failed' if any(m.get(k,{}).get('state')=='failed' for k in ('buffer_assembly','frames','video_playback')) else 'preparing_video'
                preparation[stage]=preparation.get(stage,0)+1
                if (path.parent/'video.mkv').is_file():self.station.experiments.queue_playback(m['id'])
                continue
            cached=m.get('files',{}).get('video.mp4',{})
            stats={k:cached[k] for k in ('bytes','sha256')} if cached.get('bytes')==source.stat().st_size and cached.get('sha256') else self.media_hash(source)
            if not stats['bytes']:continue
            playback=m['video_playback']
            job=dict(id=m['id'],state='queued',created_at=time.time(),channel_id=self.config['channel_id'],
                privacy=self.config['privacy'],offset=0,sent_any=False,next_attempt=0,attempts=0,
                source=dict(file='video.mp4',**stats,frame_count=playback.get('frame_count'),
                    fps=playback.get('avg_frame_rate'),width=playback.get('width',1920),height=playback.get('height',1080)),
                manifest=m,cleaned_files=[])
            self.persist(job);self.publish(job)

        self.preparation_counts=preparation

    def media_hash(self,path):
        return getattr(self.station.experiments,'hash_file',file_info)(path)

    def channel(self):
        channel=self.api.channel(self.config['channel_id'])
        private_save(self.private/'channel.json',channel);return channel

    def daily_available(self):
        day=datetime.now(timezone.utc).strftime('%Y-%m-%d')
        counter=load(self.private/'daily.json',{})
        return day,counter.get('count',0) if counter.get('day')==day else 0

    def start_upload(self,job):
        self.channel() # Check the currently authorized identity before every upload.
        day,count=self.daily_available()
        if count>=self.config['daily_upload_limit']:
            job['next_attempt']=time.time()+900;job['error']='Daily upload budget reached; queued for retry';self.persist(job);return
        path=self.session_folder(job['id'])/'video.mp4'
        if not path.is_file():raise OSError('Local MP4 unavailable; original recording has not been deleted by the uploader')
        if self.media_hash(path)!={k:job['source'][k] for k in ('bytes','sha256')}:
            raise ValueError('MP4 changed after the upload was queued; local files retained')
        metadata=dict(snippet=dict(title=(('Pipeline validation · ' if job['manifest'].get('validation') else 'Field Station · ')+job['id'])[:100],
            description='Camera and RF experiment recording. Session '+job['id']+'; UTC timestamps. '+
                'Capture origin: '+job['manifest'].get('capture_origin','manual')+'.',categoryId='28'),
            status=dict(privacyStatus=job['privacy'],selfDeclaredMadeForKids=False))
        # Charge the local budget before initiating, even if the response is lost.
        private_save(self.private/'daily.json',dict(day=day,count=count+1))
        location=self.api.initiate(metadata,job['source']['bytes'])
        job.update(upload_url=location,state='uploading',offset=0,next_attempt=0)
        self.persist(job);self.publish(job)

    def received(self,job,body):
        video_id=str(body.get('id',''))
        if not VIDEO_ID.fullmatch(video_id):raise ValueError('YouTube returned an invalid video ID')
        channel=body.get('snippet',{}).get('channelId')
        if channel and channel!=job['channel_id']:raise ValueError('YouTube returned a different channel; local files retained')
        job.update(video_id=video_id,url='https://www.youtube.com/watch?'+urlencode(dict(v=video_id)),
            state='verifying',offset=job['source']['bytes'],uploaded_at=time.time(),next_attempt=0,checks=0)
        self.persist(job);self.publish(job)

    def send(self,job):
        size=job['source']['bytes']
        try:status,headers,body=self.api.progress(job['upload_url'],size)
        except YouTubeError as error:
            if error.status==404:
                job.update(state='needs_review' if job.get('sent_any') else 'queued',
                    error='Resumable session expired; completion is uncertain. Local files retained.' if job.get('sent_any') else 'Expired empty session; retrying')
                if not job.get('sent_any'):job.pop('upload_url',None)
                self.persist(job);self.publish(job);return
            raise
        if status in (200,201):self.received(job,body);return
        offset=self.api.offset(headers)
        if not 0<=offset<size:raise ValueError('Invalid resumable upload offset')
        path=self.session_folder(job['id'])/'video.mp4'
        if path.stat().st_size!=size:raise ValueError('Local upload size changed')
        with path.open('rb') as stream:stream.seek(offset);data=stream.read(4*1024**2)
        if not data:raise OSError('Upload source unexpectedly empty')
        job.update(sent_any=True,offset=offset);self.persist(job)
        status,headers,body=self.api.chunk(job['upload_url'],offset,size,data)
        if status in (200,201):self.received(job,body);return
        job['offset']=self.api.offset(headers);job['error']=None;self.persist(job)

    def remote_verified(self,job):
        result=self.api.list('videos',part='snippet,status,processingDetails,fileDetails,contentDetails,suggestions',id=job['video_id'])
        items=result.get('items',[])
        if len(items)!=1 or items[0].get('id')!=job['video_id']:raise ValueError('Uploaded video is missing on YouTube; local files retained')
        video=items[0]
        if video.get('snippet',{}).get('channelId')!=job['channel_id']:raise ValueError('Remote channel mismatch; local files retained')
        status=video.get('status',{});processing=video.get('processingDetails',{}).get('processingStatus')
        if processing=='terminated':raise ValueError('YouTube processing verification is unavailable; local files retained')
        if processing=='failed' or status.get('uploadStatus') in ('failed','rejected','deleted'):
            raise ValueError('YouTube processing failed or was rejected; local files retained')
        if processing!='succeeded' or status.get('uploadStatus')!='processed':return False
        if status.get('privacyStatus')!=job['privacy']:raise ValueError('YouTube visibility does not match the requested setting; local files retained')
        details=video.get('fileDetails',{})
        if not details.get('fileSize') or not details.get('videoStreams'):return False
        if str(details.get('fileSize'))!=str(job['source']['bytes']):raise ValueError('YouTube file-size confirmation is missing or mismatched; local files retained')
        stream=details['videoStreams'][0]
        if (stream.get('widthPixels'),stream.get('heightPixels'))!=(job['source']['width'],job['source']['height']):
            raise ValueError('YouTube source dimensions mismatch; local files retained')
        expected_aspect=job['source']['width']/job['source']['height']
        if stream.get('aspectRatio') is not None and abs(float(stream['aspectRatio'])-expected_aspect)>.01:
            raise ValueError('YouTube display aspect ratio mismatch; local files retained')
        fps=job['source'].get('fps')
        if fps:
            from fractions import Fraction
            if not stream.get('frameRateFps'):return False
            if abs(float(stream['frameRateFps'])-float(Fraction(fps)))>.1:raise ValueError('YouTube source frame rate mismatch; local files retained')
        if video.get('suggestions',{}).get('processingErrors'):raise ValueError('YouTube reports playback processing errors')
        job['verification']=dict(uploadStatus='processed',processingStatus='succeeded',fileSize=details['fileSize'],privacyStatus=status['privacyStatus'])
        return True

    def verify(self,job):
        if not self.remote_verified(job):
            checks=job.get('checks',0)+1;job.update(checks=checks,next_attempt=time.time()+min(1800,30*2**min(checks,6)))
            self.persist(job);return
        job.update(state='verified',verified_at=time.time(),error=None,next_attempt=0)
        self.persist(job);self.publish(job)
        self.cleanup(job)

    def busy(self,sid):
        exp=self.station.experiments
        return bool((self.station.active and self.station.active['id']==sid) or any(getattr(exp,k,None)==sid for k in ('processing','assembly_processing','playback_processing','large_processing','large_assembly_processing','large_playback_processing')) or
            any(sid in getattr(exp,k,set()) for k in ('pending','assembly_pending','playback_priorities')))

    def frames_present(self,folder,manifest):
        index_path=folder/'frames/index.json'
        if (folder/'frames').is_symlink() or not index_path.is_file() or index_path.is_symlink():return False
        index=load(index_path,{})
        frames=index.get('frames',[])
        if len(frames)!=manifest.get('frames',{}).get('count') or not frames:return False
        expected=manifest.get('files',{}).get('frames/index.json',{}).get('sha256')
        if expected and file_info(index_path)['sha256']!=expected:return False
        for frame in frames:
            name=frame.get('file','')
            if not re.fullmatch(r'(?:export-[a-f0-9]{10}/)?(?:frame-[0-9]{9}|second-[0-9]{6})\.jpg',name):return False
            path=folder/'frames'/name
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to((folder/'frames').resolve()):return False
            if frame.get('bytes') is not None and path.stat().st_size!=frame['bytes']:return False
        return True

    def cleanup(self,job):
        if not self.config['enabled'] or not self.storage()['available']:return
        sid=job['id'];folder=self.session_folder(sid)
        with self.station.lock:
            m=load(folder/'manifest.json',{})
            if m.get('frames',{}).get('state')!='completed' or not self.frames_present(folder,m):
                job['state']='waiting_frames';job['next_attempt']=time.time()+30;self.persist(job);self.publish(job);return
            experiments=self.station.experiments
            if self.busy(sid):
                job['next_attempt']=time.time()+15;self.persist(job);return
        archive=getattr(self.station,'internet_archive',None)
        if archive and not archive.verified(sid,job['source'].get('sha256')):
            job.update(state='waiting_archive',next_attempt=time.time()+60)
            self.persist(job);self.publish(job);return
        retain_until=job.get('verified_at',0)+self.config.get('retention_seconds',0)
        if time.time()<retain_until:
            job.update(state='retaining',next_attempt=retain_until)
            self.persist(job);self.publish(job);return
        if not self.remote_verified(job):return
        # Persist the durable receipt and explicit cleanup journal before first unlink.
        job['state']='deleting';self.persist(job);self.publish(job)
        with self.station.lock:
            if self.busy(sid):return
            if not self.config['enabled'] or not self.storage()['available']:return
            m=load(folder/'manifest.json',{})
            if m.get('frames',{}).get('state')!='completed' or not self.frames_present(folder,m):return
            names=['video.mkv','video.mp4','video-assembling.mkv','video-playback-tmp.mp4']
            segments=folder/'buffer-segments'
            if segments.is_symlink():raise ValueError('Unsafe segment folder; cleanup stopped')
            if segments.is_dir():
                names += ['buffer-segments/'+p.name for p in segments.iterdir() if re.fullmatch(r'segment-[0-9]{9}\.(mkv|tmp)',p.name)]
            # Validate every path before deleting any. Never touch frames, RF, images or manifests.
            for name in names:
                file=folder/name
                if file.is_symlink() or (file.exists() and (not file.is_file() or not file.resolve().is_relative_to(folder.resolve()))):
                    raise ValueError('Unsafe cleanup path; local files retained')
            if not job.get('cleanup_plan'):
                job['cleanup_plan']=[dict(file=name,bytes=(folder/name).stat().st_size,**{k:v for k,v in m.get('files',{}).get(name,{}).items() if k!='bytes'}) for name in names if (folder/name).is_file()]
                self.persist(job);self.publish(job)
            for name in names:
                file=folder/name
                if file.exists():
                    entry=dict(file=name,bytes=file.stat().st_size)
                    if name in m.get('files',{}):entry.update(m['files'][name])
                    file.unlink();job['cleaned_files'].append(entry);self.persist(job)
                m.setdefault('files',{}).pop(name,None)
            if not m.get('internet_archive',{}).get('verified_at'):m['video_playback']=dict(state='youtube',url=job['url'],frame_count=job['source'].get('frame_count'))
            job.update(state='cleaned',cleaned_at=time.time(),next_attempt=0)
            self.persist(job);m['youtube']=self.receipt(job)
            save(self.catalog/(sid+'.json'),m);save(folder/'manifest.json',m)

    def tick(self):
        if self.api.poll_auth():self.channel()
        if not self.config['enabled']:self.phase='disabled';return
        if not self.api.configured():self.phase='waiting_credentials';return
        if not self.api.connected():self.phase='waiting_authorization';return
        if not load(self.private/'channel.json'):self.channel()
        if time.time()>=self.next_discovery:
            self.discover();self.next_discovery=time.time()+30
        jobs=list(self.job_cache.values())
        candidates=[j for j in jobs if j.get('state') not in ('cleaned','failed','needs_review','skipped_archive_primary') and j.get('next_attempt',0)<=time.time()]
        if not candidates:self.phase='preparing_video' if self.preparation_counts.get('preparing_video') else 'preparation_failed' if self.preparation_counts.get('preparation_failed') else 'idle';self.current=None;return
        # Round-robin to avoid a slow upload starving verification/cleanup of another clip.
        candidates.sort(key=lambda j:j.get('last_step',0))
        job=candidates[0];self.current=job['id'];self.phase=job['state']
        try:
            if job['state']=='queued':self.start_upload(job)
            elif job['state']=='uploading':self.send(job)
            elif job['state']=='verifying':self.verify(job)
            elif job['state'] in ('verified','waiting_frames','deleting','retaining','waiting_archive'):self.cleanup(job)
            job['last_step']=time.time();self.persist(job);self.error=None
        except (OSError,ValueError) as error:
            job['attempts']=job.get('attempts',0)+1
            job.update(error=str(error),next_attempt=time.time()+min(3600,15*2**min(job['attempts'],8)),last_step=time.time())
            if isinstance(error,ValueError):job['state']='failed'
            self.persist(job);self.publish(job);self.error=str(error)

    def work(self):
        while not self.station.exiting.is_set():
            try:self.tick()
            except Exception as error:self.error=str(error);self.phase='error';self.station.exiting.wait(10)
            self.wake.wait(.5);self.wake.clear()

    def shutdown(self):
        self.wake.set()
        if self.worker.is_alive():self.worker.join(timeout=50)

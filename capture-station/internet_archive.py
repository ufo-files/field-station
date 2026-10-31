"""Public Internet Archive uploads with durable multipart state and verified cleanup."""
import base64
from archive_policy import eligible
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote,urlsplit,urlencode,urljoin
import requests
from experiments import load,save,utc
from youtube_api import private_save

SID=re.compile(r'[0-9TZ]+-[a-f0-9]{6}')
MOTION=re.compile(r'motion-[a-f0-9]{16}-(before|after|boxed)\.jpg')
PART_SIZE=16*1024**2


def hashes(path):
    md5=hashlib.md5();sha=hashlib.sha256();size=0
    with path.open('rb') as stream:
        for data in iter(lambda:stream.read(4*1024**2),b''):
            size+=len(data);md5.update(data);sha.update(data)
    return dict(bytes=size,md5=md5.hexdigest(),sha256=sha.hexdigest())


class ArchiveError(OSError):
    def __init__(self,status,message):
        self.status=status;super().__init__(message)


class ArchiveAPI:
    def __init__(self,private):self.private=Path(private);self.session=requests.Session()
    def configured(self):
        value=load(self.private/'credentials.json',{})
        return bool(value.get('access_key') and value.get('secret_key'))
    def configure(self,body):
        access=str(body.get('access_key','')).strip();secret=str(body.get('secret_key','')).strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{8,128}',access) or not 8<=len(secret)<=256 or any(ord(c)<33 or ord(c)>126 for c in secret):
            raise ValueError('Enter the Internet Archive S3 access key and secret key from archive.org/account/s3.php.')
        private_save(self.private/'credentials.json',dict(access_key=access,secret_key=secret))
    def raw(self,method,url,data=None,headers=None,auth=False):
        headers=dict(headers or {})
        if auth:
            value=load(self.private/'credentials.json',{})
            if not value:raise ValueError('Internet Archive API keys are required')
            headers['Authorization']='LOW '+value['access_key']+':'+value['secret_key']
        position=data.tell() if hasattr(data,'tell') else None
        for _ in range(5):
            parsed=urlsplit(url)
            if parsed.scheme!='https' or not parsed.hostname or not (parsed.hostname=='archive.org' or parsed.hostname.endswith('.archive.org')) or parsed.username or parsed.password:
                raise ValueError('Unexpected Internet Archive server')
            if position is not None:data.seek(position)
            try:r=self.session.request(method,url,data=data,headers=headers,allow_redirects=False,timeout=(15,90))
            except requests.RequestException:raise ArchiveError(0,'Internet Archive connection interrupted; local files retained') from None
            if r.status_code in (301,302,303,307,308):
                location=r.headers.get('Location');r.close()
                if not location:raise ArchiveError(502,'Internet Archive returned an empty redirect')
                url=urljoin(url,location);continue
            if r.status_code>=400:
                status=r.status_code;r.close()
                message='Internet Archive is busy; upload queued for retry' if status in (429,503) else 'Internet Archive rejected the API keys or item permissions' if status in (401,403) else f'Internet Archive request failed ({status}); local files retained'
                raise ArchiveError(status,message)
            return r
        raise ArchiveError(502,'Too many Internet Archive redirects; local files retained')
    def metadata(self,identifier):
        try:
            with self.raw('GET','https://archive.org/metadata/'+quote(identifier)) as r:return r.json()
        except ArchiveError as error:
            if error.status==404:return {}
            raise
    def url(self,identifier,name):return 'https://s3.us.archive.org/'+quote(identifier)+'/'+quote(name,safe='/')
    def item_headers(self,job,derive=False):
        return {'x-archive-auto-make-bucket':'1','x-archive-meta-collection':'opensource_movies',
            'x-archive-meta-mediatype':'movies','x-archive-meta-title':'Field Station '+job['id'],
            'x-archive-meta-creator':'UFO Files Project','x-archive-meta-subject':'sky observation;camera;RF measurements',
            'x-archive-meta-description':'Human-reviewed camera and RF observation. Session '+job['id']+'. Includes raw video.mp4 and video-annotated.mp4 with human-reviewed boxes on explicitly labeled frames. An anomalous label means unidentified by the reviewer, not an established explanation.',
            'x-archive-queue-derive':'1' if derive else '0','x-archive-keep-old-version':'1'}
    def small(self,job,entry,path):
        headers=self.item_headers(job)
        headers.update({'Content-Length':str(entry['bytes']),'Content-MD5':base64.b64encode(bytes.fromhex(entry['md5'])).decode(),'Content-Type':'image/jpeg' if entry['name'].endswith('.jpg') else 'application/json' if entry['name'].endswith('.json') else 'application/octet-stream'})
        if not entry['bytes']:
            with self.raw('PUT',self.url(job['identifier'],entry['name']),b'',headers,auth=True):pass
        else:
            with path.open('rb') as body:
                with self.raw('PUT',self.url(job['identifier'],entry['name']),body,headers,auth=True):pass
    def initiate(self,job,entry):
        with self.raw('POST',self.url(job['identifier'],entry['name'])+'?uploads',b'',self.item_headers(job,derive=True),auth=True) as r:
            root=ET.fromstring(r.content)
        upload_id=next((e.text for e in root.iter() if e.tag.split('}')[-1]=='UploadId'),None)
        if not upload_id:raise ArchiveError(502,'Internet Archive did not return a multipart upload ID')
        return upload_id
    def part(self,job,entry,upload_id,number,data):
        query=urlencode(dict(partNumber=number,uploadId=upload_id))
        headers={'Content-Length':str(len(data)),'Content-MD5':base64.b64encode(hashlib.md5(data).digest()).decode()}
        with self.raw('PUT',self.url(job['identifier'],entry['name'])+'?'+query,data,headers,auth=True) as r:etag=r.headers.get('ETag')
        if not etag:raise ArchiveError(502,'Internet Archive did not confirm the uploaded part')
        return etag
    def complete(self,job,entry,upload_id,parts):
        root=ET.Element('CompleteMultipartUpload')
        for part in parts:
            item=ET.SubElement(root,'Part');ET.SubElement(item,'PartNumber').text=str(part['number']);ET.SubElement(item,'ETag').text=part['etag']
        with self.raw('POST',self.url(job['identifier'],entry['name'])+'?'+urlencode(dict(uploadId=upload_id)),ET.tostring(root),{'Content-Type':'application/xml','x-archive-queue-derive':'1'},auth=True) as r:
            if r.content:
                response=ET.fromstring(r.content)
                if response.tag.split('}')[-1]=='Error':raise ArchiveError(503,'Internet Archive has not committed the upload; queued for verification')
    def downloadable(self,job,entry):
        with self.raw('HEAD','https://archive.org/download/'+quote(job['identifier'])+'/'+quote(entry['name'],safe='/')) as r:
            return r.status_code==200 and r.headers.get('Content-Length')==str(entry['bytes'])


class InternetArchive:
    def __init__(self,station,root,data,storage,api=None,start=True):
        self.station,self.root,self.data,self.storage=station,Path(root),Path(data),storage
        self.private=self.root/'private/internet-archive';self.private.mkdir(parents=True,exist_ok=True,mode=0o700);self.private.chmod(0o700)
        self.jobs=self.private/'jobs';self.jobs.mkdir(exist_ok=True,mode=0o700)
        self.catalog=self.root/'catalog/sessions';self.catalog.mkdir(parents=True,exist_ok=True)
        self.api=api or ArchiveAPI(self.private)
        self.settings_path=self.private/'settings.json';self.config=dict(enabled=True,retention_seconds=3600,identifier_prefix='ufo-files-station-'+secrets.token_hex(3))
        self.config.update(load(self.settings_path,{}))
        if not self.settings_path.exists():private_save(self.settings_path,self.config)
        self.job_cache={p.stem:load(p,{}) for p in self.jobs.glob('*.json')}
        self.phase='waiting_credentials';self.error=None;self.current=None;self.next_discovery=0;self.cooldown_until=0
        self.wake=threading.Event();self.worker=threading.Thread(target=self.work,daemon=True)
        if start:self.worker.start()
    def status(self):
        counts={}
        for j in self.job_cache.values():counts[j['state']]=counts.get(j['state'],0)+1
        j=self.job_cache.get(self.current,{})
        return dict(enabled=self.config['enabled'],scope='web_confirmed_anomalies_only',configured=self.api.configured(),phase=self.phase,error=self.error,counts=counts,
            current=dict(id=j.get('id'),uploaded_bytes=j.get('uploaded_bytes',0),total_bytes=j.get('total_bytes',0),url=j.get('url')),
            retention_seconds=self.config['retention_seconds'],cleanup_enabled=self.config.get('cleanup_enabled',True))
    def configure(self,body):
        if 'enabled' in body:self.config['enabled']=bool(body['enabled']);private_save(self.settings_path,self.config)
        if body.get('access_key') or body.get('secret_key'):self.api.configure(body)
        self.error=None;self.cooldown_until=0;self.wake.set();return self.status()
    def folder(self,sid):
        if not SID.fullmatch(sid):raise ValueError('Invalid session ID')
        folder=self.data/sid
        if folder.is_symlink() or not folder.resolve().is_relative_to(self.data.resolve()):raise ValueError('Unsafe session folder')
        return folder
    def persist(self,job):
        private_save(self.jobs/(job['id']+'.json'),job);self.job_cache[job['id']]=dict(job)
    def receipt(self,job):
        return {k:job.get(k) for k in ('state','identifier','url','video_url','verified_at','cleaned_at','files','error')}
    def verified(self,sid,sha256=None):
        job=self.job_cache.get(sid,{})
        video=next((e for e in job.get('files',[]) if e['name']=='video.mp4'),{})
        return bool(job.get('verified_at') and job.get('state') in ('retaining','cleaned') and (not sha256 or video.get('sha256')==sha256))
    def publish(self,job):
        with self.station.lock:
            path=self.folder(job['id'])/'manifest.json';m=load(path,{}) or load(self.catalog/(job['id']+'.json'),{})
            if not m:return
            m['internet_archive']=self.receipt(job)
            if job['state']=='cleaned':
                for entry in job.get('cleaned_files',[]):m.setdefault('files',{}).pop(entry['file'],None)
                m['video_playback']=dict(state='internet_archive',url=job['video_url'],frame_count=job.get('frame_count'))
            save(self.catalog/(job['id']+'.json'),m)
            if self.storage()['available'] and path.exists():save(path,m)
    def complete_session_plan(self,job,manifest):
        """Archive the finalized session record, excluding raw/scratch video."""
        decision=load(self.folder(job['id'])/'archive-decision.json',{})
        if job.get('plan_version')==4 and job.get('review_revision')==decision.get('review_revision'):return False
        folder=self.folder(job['id']);old_files=list(job['files']);old_length=len(old_files);known={e['name'] for e in job['files']}
        changed=[]
        for i,entry in enumerate(job['files']):
            if entry['name'] in ('archive-decision.json','review-annotations.json','video-annotated.mp4'):
                updated=dict(name=entry['name'],**hashes(folder/entry['name']))
                if updated!=entry:job['files'][i]=updated;changed.append(i)
        for path in sorted(folder.iterdir()):
            if path.name=='manifest.json' or path.name in known or path.suffix.lower() not in ('.json','.jsonl','.log','.txt','.jpg','.jpeg','.png','.wav'):continue
            if path.is_symlink():raise ValueError('Unsafe session evidence link')
            if not path.is_file():continue
            job['files'].append(dict(name=path.name,**hashes(path)))
        # Native evidence added by the M1 pipeline lives below the session root.
        # Only explicit evidence directories are eligible; never recurse into
        # private/configuration folders or follow symlinks.
        known={e['name'] for e in job['files']}
        evidence=[folder/'video-annotated.mp4']
        if (folder/'video.mkv').is_file():evidence.append(folder/'video.mkv')
        for directory,patterns in (
            ('buffer-segments',('frame-times-*.jsonl',)),
            ('model-frames',('*.jpg','*.png','*.jsonl')),
            ('frames',('frame-*.jpg','index.json')),
        ):
            parent=folder/directory
            if parent.is_symlink():raise ValueError('Unsafe archive evidence directory')
            if directory=='frames' and manifest.get('frames',{}).get('mode')!='selected':continue
            for pattern in patterns:evidence.extend(parent.glob(pattern))
        for path in sorted(set(evidence)):
            name=path.relative_to(folder).as_posix()
            if name in known:continue
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(folder.resolve()):raise ValueError('Unsafe archive evidence path')
            job['files'].append(dict(name=name,**hashes(path)));known.add(name)
        # Freeze the session manifest so upload receipts cannot change it mid-transfer.
        if 'manifest.json' not in known:
            snapshot=self.private/(job['id']+'-manifest.json')
            private_save(snapshot,dict(manifest,archive_location=dict(identifier=job['identifier'],url=job['url'])))
            job['files'].append(dict(name='manifest.json',private_source=snapshot.name,**hashes(snapshot)))
        inventory=self.private/(job['id']+'-archive-index.json')
        private_save(inventory,dict(schema=1,session_id=job['id'],created_at=utc(),
            excluded=['Temporary video and capture segments','Full per-frame JPEG export directories when mode is not selected','Private configuration and credentials'],
            files=[{k:e[k] for k in ('name','bytes','md5','sha256')} for e in job['files'] if e['name']!='archive-index.json']))
        inventory_entry=dict(name='archive-index.json',private_source=inventory.name,**hashes(inventory))
        first_new=old_length
        if 'archive-index.json' in known:
            first_new=next(i for i,e in enumerate(job['files']) if e['name']=='archive-index.json')
            job['files'][first_new]=inventory_entry
        else:job['files'].append(inventory_entry)
        job['plan_version']=4;job['review_revision']=decision.get('review_revision');job['total_bytes']=sum(e['bytes'] for e in job['files'])
        if changed or len(job['files'])>old_length:
            first_new=min([first_new,*changed,job.get('file_index',0)])
        if (changed or len(job['files'])>old_length) and job['state'] in ('uploading','completing','verifying','retaining','cleaned','failed'):
            job.update(state='uploading',file_index=first_new,parts=[],next_attempt=0,error=None,uploaded_bytes=sum(e['bytes'] for e in old_files[:first_new]))
            job.pop('upload_id',None);job.pop('verified_at',None)
        return bool(changed or len(job['files'])>old_length)

    def extend_existing_plans(self):
        if not self.storage()['available']:return
        for job in list(self.job_cache.values()):
            if not self.archive_eligible(job['id']):continue
            manifest=load(self.folder(job['id'])/'manifest.json',{})
            if manifest and self.complete_session_plan(job,manifest):self.persist(job);self.publish(job)

    def archive_eligible(self,sid):
        folder=self.folder(sid)
        return eligible(load(folder/'manifest.json',{}) or load(self.catalog/(sid+'.json'),{}),load(folder/'archive-decision.json',{})) and all((folder/name).is_file() and not (folder/name).is_symlink() for name in ('video.mp4','video-annotated.mp4'))

    def reconcile_policy(self):
        for job in list(self.job_cache.values()):
            if job['state']=='cleaned':continue
            allowed=self.archive_eligible(job['id'])
            if not allowed and job['state']!='held_for_review':
                job.update(policy_previous_state=job['state'],state='held_for_review',policy_hold_epoch=time.time(),policy_reason='Only completed anomalous web reviews with raw and annotated video are uploaded. Local evidence retained.')
                self.persist(job);self.publish(job)
            elif allowed and job['state']=='held_for_review':
                job.update(state=job.pop('policy_previous_state','queued'),next_attempt=0,plan_version=2)
                job.pop('policy_reason',None)
                self.complete_session_plan(job,load(self.folder(job['id'])/'manifest.json',{}))
                self.persist(job);self.publish(job)

    def discover(self,only=None):
        if not self.storage()['available']:return
        for path in sorted(self.data.glob('*/manifest.json')):
            m=load(path,{});sid=m.get('id','')
            if only is not None and sid not in only:continue
            if not SID.fullmatch(sid) or sid in self.job_cache or m.get('state') not in ('completed','interrupted'):continue
            folder=self.folder(sid);video=folder/'video.mp4'
            if not self.archive_eligible(sid):continue
            if m.get('video_playback',{}).get('state')!='completed' or not video.is_file():continue
            if self.station.youtube.busy(sid):continue
            names=['rf.jsonl','motion-events.json','rf-trigger-events.json','frames/index.json']
            names += [p.name for p in folder.iterdir() if MOTION.fullmatch(p.name)]
            index=load(folder/'frames/index.json',{})
            for entry in index.get('frames',[])[:3]:
                if not re.fullmatch(r'frame-[0-9]{9}\.jpg',entry.get('file','')):raise ValueError('Selected still path is invalid')
                names.append('frames/'+entry['file'])
            files=[]
            for name in names:
                source=folder/name
                if not source.exists():continue
                if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(folder.resolve()):raise ValueError('Unsafe archive evidence path')
                if source.stat().st_size==0:continue
                files.append(dict(name=name,**hashes(source)))
            identifier=self.config['identifier_prefix']+'-'+sid.lower()
            job=dict(id=sid,state='queued',identifier=identifier,url='https://archive.org/details/'+identifier,
                video_url='https://archive.org/download/'+identifier+'/video.mp4',files=files,
                file_index=0,parts=[],uploaded_bytes=0,attempts=0,next_attempt=0,last_step=0,frame_count=m['video_playback'].get('frame_count'))
            snapshot=self.private/(sid+'-session.json');private_save(snapshot,dict(session=m,archive_url=job['url'],schema=1))
            job['files'].append(dict(name='session.json',private_source=snapshot.name,**hashes(snapshot)))
            if video.is_symlink():raise ValueError('Unsafe upload video')
            job['files'].append(dict(name='video.mp4',**hashes(video)))
            self.complete_session_plan(job,m)
            job['total_bytes']=sum(e['bytes'] for e in job['files']);self.persist(job);self.publish(job)
    def source(self,job,entry):
        path=self.private/entry['private_source'] if entry.get('private_source') else self.folder(job['id'])/entry['name']
        if path.is_symlink() or not path.is_file():raise ValueError('Archive source unavailable; local files retained')
        if path.stat().st_size!=entry['bytes']:raise ValueError('Archive source changed; local files retained')
        return path
    def matches(self,job,metadata):
        if metadata.get('is_dark') or not metadata.get('metadata'):return False
        remote={e.get('name'):e for e in metadata.get('files',[])}
        return all(str(remote.get(e['name'],{}).get('size'))==str(e['bytes']) and remote.get(e['name'],{}).get('md5','').lower()==e['md5'] for e in job['files'])
    def current_review(self,job):
        if not self.archive_eligible(job['id']):return False
        decision=load(self.folder(job['id'])/'archive-decision.json',{})
        if job.get('review_revision')!=decision.get('review_revision'):
            self.next_discovery=0;return False
        return True
    def send(self,job):
        if not self.current_review(job):return
        index=job['file_index']
        if index>=len(job['files']):job.update(state='verifying',next_attempt=0);return
        entry=job['files'][index];source=self.source(job,entry)
        # Hashes are checked again before the first bytes of each file leave disk.
        multipart=entry['name'] in ('video.mp4','video.mkv','video-annotated.mp4') or entry['bytes']>=16*1024**2
        if (not multipart or not job.get('upload_id')) and hashes(source)!={k:entry[k] for k in ('bytes','md5','sha256')}:
            raise ValueError('Archive source checksum changed; upload stopped')
        if not multipart:
            self.api.small(job,entry,source);job['uploaded_bytes']+=entry['bytes'];job['file_index']+=1;job['state']='uploading';return
        if not job.get('upload_id'):
            job['upload_id']=self.api.initiate(job,entry);job['parts']=[];job['state']='uploading';return
        offset=sum(p['bytes'] for p in job['parts'])
        if offset<entry['bytes']:
            with source.open('rb') as stream:stream.seek(offset);data=stream.read(PART_SIZE)
            number=len(job['parts'])+1;etag=self.api.part(job,entry,job['upload_id'],number,data)
            job['parts'].append(dict(number=number,etag=etag,bytes=len(data)));job['uploaded_bytes']+=len(data);return
        # Persist the uncertain-completion state before requesting commit.
        job['state']='completing';self.persist(job)
        self.complete(job)
    def complete(self,job):
        if not self.current_review(job):return
        entry=job['files'][job['file_index']]
        try:self.api.complete(job,entry,job['upload_id'],job['parts'])
        except ArchiveError as error:
            if error.status!=404:raise
            # A lost completion response can remove UploadId before metadata appears.
        next_index=job['file_index']+1
        job.pop('upload_id',None);job['parts']=[]
        job.update(state='uploading' if next_index<len(job['files']) else 'verifying',file_index=next_index,next_attempt=0 if next_index<len(job['files']) else time.time()+30)

    def verify(self,job):
        if not self.current_review(job):return False
        metadata=self.api.metadata(job['identifier'])
        if not self.matches(job,metadata):job['next_attempt']=time.time()+60;return False
        video=next(e for e in job['files'] if e['name']=='video.mp4')
        annotated=next((e for e in job['files'] if e['name']=='video-annotated.mp4'),None)
        if not annotated or not all(self.api.downloadable(job,e) for e in (video,annotated)):job['next_attempt']=time.time()+60;return False
        job.update(state='retaining',verified_at=time.time(),error=None,next_attempt=time.time()+self.config['retention_seconds'])
        return True
    def cleanup(self,job):
        if not self.storage()['available'] or not self.config['enabled'] or not self.archive_eligible(job['id']):return
        if not self.config.get('cleanup_enabled',True):
            job['next_attempt']=time.time()+3600;return
        if time.time()<job['verified_at']+self.config['retention_seconds']:
            job['next_attempt']=job['verified_at']+self.config['retention_seconds'];return
        sid=job['id'];folder=self.folder(sid);yt=self.station.youtube
        if yt.busy(sid) or yt.current==sid:job['next_attempt']=time.time()+30;return
        if not self.matches(job,self.api.metadata(job['identifier'])):raise ValueError('Archive copy no longer matches; local video retained')
        video=next(e for e in job['files'] if e['name']=='video.mp4')
        annotated=next((e for e in job['files'] if e['name']=='video-annotated.mp4'),None)
        if not annotated or not all(self.api.downloadable(job,e) for e in (video,annotated)):raise ValueError('Archive videos are not downloadable; local video retained')
        with self.station.lock:
            if yt.busy(sid) or yt.current==sid:return
            m=load(folder/'manifest.json',{})
            local_video=folder/'video.mp4'
            if local_video.exists() and hashes(local_video)!={k:video[k] for k in ('bytes','md5','sha256')}:raise ValueError('Local MP4 changed after archive verification; retained')
            if m.get('frames',{}).get('state')!='completed' or not yt.frames_present(folder,m):job['next_attempt']=time.time()+60;return
            names=['video.mkv','video.mp4','video-assembling.mkv','video-playback-tmp.mp4']
            segments=folder/'buffer-segments'
            if segments.is_symlink():raise ValueError('Unsafe segment folder')
            if segments.is_dir():names += ['buffer-segments/'+p.name for p in segments.iterdir() if re.fullmatch(r'segment-[0-9]{9}\.(mkv|tmp)',p.name)]
            for name in names:
                path=folder/name
                if path.is_symlink() or (path.exists() and (not path.is_file() or not path.resolve().is_relative_to(folder.resolve()))):raise ValueError('Unsafe archive cleanup path')
            job.setdefault('cleanup_plan',[dict(file=name,bytes=(folder/name).stat().st_size) for name in names if (folder/name).is_file()])
            job.setdefault('cleaned_files',[]);self.persist(job)
            # A YouTube mirror that has not uploaded can be skipped after the primary archive succeeds.
            mirror=yt.job_cache.get(sid)
            if mirror and not mirror.get('video_id') and mirror.get('state') not in ('cleaned','skipped_archive_primary'):
                mirror.update(state='skipped_archive_primary',error=None,next_attempt=0);yt.persist(mirror);yt.publish(mirror)
            for name in names:
                path=folder/name
                if path.exists():
                    job['cleaned_files'].append(dict(file=name,bytes=path.stat().st_size));self.persist(job);path.unlink()
            job.update(state='cleaned',cleaned_at=time.time(),next_attempt=0);self.persist(job);self.publish(job)
    def tick(self):
        if not self.config['enabled']:self.phase='disabled';return
        if not self.api.configured():self.phase='waiting_credentials';return
        if time.time()<self.cooldown_until:self.phase='waiting_retry';return
        if time.time()>=self.next_discovery:self.reconcile_policy();self.extend_existing_plans();self.discover();self.next_discovery=time.time()+30
        candidates=[j for j in self.job_cache.values() if j['state'] not in ('cleaned','failed','held_for_review') and j.get('next_attempt',0)<=time.time()]
        if not candidates:self.phase='idle';self.current=None;return
        candidates.sort(key=lambda j:(0 if j['state'] in ('verifying','retaining') else 1,max(0,j.get('total_bytes',0)-j.get('uploaded_bytes',0)),j.get('last_step',0)));job=candidates[0];self.current=job['id'];self.phase=job['state']
        try:
            if job['state'] in ('queued','uploading'):self.send(job)
            elif job['state']=='completing':self.complete(job)
            elif job['state']=='verifying':self.verify(job)
            elif job['state']=='retaining':self.cleanup(job)
            self.error=None;job['error']=None
        except (OSError,ValueError,ET.ParseError) as error:
            job['attempts']+=1;job['error']=str(error);self.error=str(error)
            job['next_attempt']=time.time()+min(3600,30*2**min(job['attempts'],7))
            if isinstance(error,ValueError):job['state']='failed'
            if isinstance(error,ArchiveError) and error.status in (401,403,429,503):self.cooldown_until=time.time()+300
        job['last_step']=time.time();self.persist(job);self.publish(job)
    def work(self):
        try:os.setpriority(os.PRIO_PROCESS,threading.get_native_id(),10)
        except OSError:pass
        while not self.station.exiting.is_set():
            try:self.tick()
            except Exception as error:self.error=str(error);self.phase='error'
            self.wake.wait(1);self.wake.clear()
    def shutdown(self):
        self.wake.set()
        if self.worker.is_alive():self.worker.join(timeout=5)

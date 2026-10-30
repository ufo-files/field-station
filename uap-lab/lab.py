"""Independent, local video annotation and appearance-model evaluation lab."""
import hashlib, json, os, re, secrets, shutil, subprocess, threading, time, uuid
from pathlib import Path
from collections import OrderedDict
from concurrent.futures import Future
from evidence_copy import copy_evidence
import cv2
import numpy as np
cv2.setNumThreads(1)

ROOT=Path(__file__).resolve().parent
DATA=Path(os.environ.get('UAP_LAB_DATA','/home/hackrf/t7/uap-lab'))
STATION=Path(os.environ.get('CAPTURE_STATION_ROOT',str(ROOT.parent/'capture-station')))
FFMPEG=os.environ.get('FFMPEG',str(STATION/'vendor/root/usr/bin/ffmpeg'))
FFPROBE=os.environ.get('FFPROBE',str(STATION/'vendor/root/usr/bin/ffprobe'))
ENV=dict(os.environ,LD_LIBRARY_PATH=str(STATION/'vendor/root/usr/lib/aarch64-linux-gnu')+':'+str(STATION/'vendor/root/usr/lib/aarch64-linux-gnu/lapack'),OPENBLAS_NUM_THREADS='1')
LABELS=['anomalous','bird','airplane','tree','cloud','insect','other_animal','balloon','drone','unknown']
LOCK=threading.Lock()
RESERVE=int(os.environ.get('UAP_LAB_RESERVE_BYTES',100*1024**3))
for directory in ('videos','models','runs'): (DATA/directory).mkdir(parents=True,exist_ok=True)

def save(path,value):
    temp=path.with_suffix('.tmp-'+uuid.uuid4().hex)
    temp.write_text(json.dumps(value,indent=2));temp.replace(path)

def read(path,default=None):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return default

def checked_id(value):
    if not re.fullmatch('[a-f0-9]{32}',str(value)):raise ValueError('Invalid ID')
    return value

def video_path(vid):return DATA/'videos'/checked_id(vid)

def run_command(args,**kwargs):
    p=subprocess.run(args,env=ENV,stdout=subprocess.PIPE,stderr=subprocess.PIPE,**kwargs)
    if p.returncode:raise ValueError(p.stderr.decode(errors='replace')[-3000:])
    return p.stdout

def probe(path):
    value=json.loads(run_command([FFPROBE,'-v','error','-show_streams','-show_format','-of','json',str(path)],timeout=60))
    streams=[v for v in value['streams'] if v['codec_type']=='video' and not v.get('disposition',{}).get('attached_pic')]
    if not streams:raise ValueError('No video stream found')
    v=streams[0]
    return dict(width=v['width'],height=v['height'],fps=v.get('avg_frame_rate','0/0'),duration=float(v.get('duration') or value['format'].get('duration') or 0),codec=v['codec_name'],rotation=next((s.get('rotation',0) for s in v.get('side_data_list',[]) if 'rotation' in s),0))

_FRAME_LOCK=threading.Lock()
_FRAME_CACHE=OrderedDict()
_FRAME_PENDING={}
_FRAME_BYTES=0
_DECODERS=threading.BoundedSemaphore(2)
_TIMELINE_LOCKS={}
_REVIEW_LOCKS={}

def _per_video_lock(registry,folder):
    with _FRAME_LOCK:return registry.setdefault(str(folder),threading.Lock())

def frame_at(folder,seconds):
    """Bounded PNG cache and one decode per source/time, including concurrent requests."""
    global _FRAME_BYTES
    folder=Path(folder);stat=(folder/'source').stat();key=(str(folder.resolve()),stat.st_size,stat.st_mtime_ns,float(seconds))
    with _FRAME_LOCK:
        raw=_FRAME_CACHE.get(key);future=_FRAME_PENDING.get(key);owner=raw is None and future is None
        if raw is not None:_FRAME_CACHE.move_to_end(key)
        elif owner:future=Future();_FRAME_PENDING[key]=future
    if raw is None:
        if owner:
            try:
                with _DECODERS:
                    raw=run_command([FFMPEG,'-v','error','-threads','1','-ss',str(seconds),'-i',str(folder/'source'),'-frames:v','1','-f','image2pipe','-vcodec','png','-threads','1','-'],timeout=120)
                with _FRAME_LOCK:
                    _FRAME_CACHE[key]=raw;_FRAME_BYTES+=len(raw)
                    while len(_FRAME_CACHE)>64 or _FRAME_BYTES>96*1024**2:
                        _,old=_FRAME_CACHE.popitem(last=False);_FRAME_BYTES-=len(old)
                    _FRAME_PENDING.pop(key,None);future.set_result(raw)
            except BaseException as exc:
                with _FRAME_LOCK:_FRAME_PENDING.pop(key,None);future.set_exception(exc)
                raise
        else:raw=future.result(timeout=180)
    im=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
    if im is None:raise ValueError('No frame at this position')
    return im,raw

def timeline(folder):
    folder=Path(folder)
    with _per_video_lock(_TIMELINE_LOCKS,folder):
        cached=read(folder/'timeline.json')
        if cached is None:
            # Packet PTS provide display timestamps without decoding the entire video.
            raw=json.loads(run_command([FFPROBE,'-v','error','-select_streams','v:0','-show_packets','-show_entries','packet=pts_time,flags','-of','json',str(folder/'source')],timeout=120))
            times=sorted({float(v['pts_time']) for v in raw['packets'] if 'pts_time' in v and 'D' not in v.get('flags','')})
            cached=[v-times[0] for v in times] if times else []
            save(folder/'timeline.json',cached)
        return cached

def complete_review(vid,targets,no_target=False,legacy=None):
    folder=video_path(vid)
    with _per_video_lock(_REVIEW_LOCKS,folder):
        meta=read(folder/'video.json')
        if not meta:raise ValueError('Video not found')
        prior=read(folder/'review.json',{})
        if prior.get('completed'):
            from review_archive import record_decision
            record_decision(folder,meta,prior)
            return prior
        if not isinstance(targets,list) or len(targets)>200:raise ValueError('Select at most 200 targets per video')
        if no_target and (targets or read(folder/'annotations.json',[])):raise ValueError('Remove target selections before marking no target')
        progress=dict(state='saving',completed=0,total=len(targets)+(1 if legacy else 0),updated=time.time())
        save(folder/'review-progress.json',progress)
        try:
            for i,region in enumerate(targets):
                annotate(vid,region['time'],region['bounds'],region.get('label','anomalous'),region['id'],region.get('track_id'))
                progress.update(completed=i+1,updated=time.time());save(folder/'review-progress.json',progress)
            if legacy:annotate(vid,legacy['time'],legacy['bounds'],legacy.get('label','anomalous'))
            if not read(folder/'annotations.json',[]) and not no_target:raise ValueError('Select the target first')
            review=dict(completed=True,reviewed_at=time.time(),no_target=bool(no_target));save(folder/'review.json',review)
            if meta.get('sha256'):
                with LOCK:
                    hashes=read(DATA/'reviewed-videos.json',{});hashes[meta['sha256']]=review;save(DATA/'reviewed-videos.json',hashes)
            from review_archive import record_decision
            record_decision(folder,meta,review)
            progress.update(state='complete',completed=progress['total']);save(folder/'review-progress.json',progress)
            return review
        except Exception as exc:
            progress.update(state='failed',error=str(exc));save(folder/'review-progress.json',progress);raise

def prepare_preview(folder):
    """Browser compatibility copy only; annotations and exports use the source."""
    try:
        space_check()
        run_command([FFMPEG,'-v','error','-threads','1','-i',str(folder/'source'),'-map','0:v:0','-an','-vf',"scale=w='min(1280,iw)':h='min(1280,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",'-fps_mode','vfr','-c:v','libx264','-threads','1','-preset','fast','-crf','22','-pix_fmt','yuv420p','-movflags','+faststart','-y',str(folder/'preview.mp4')],timeout=7200)
        with LOCK:
            meta=read(folder/'video.json');meta['preview_state']='ready';save(folder/'video.json',meta)
    except Exception as exc:
        with LOCK:
            meta=read(folder/'video.json');meta.update(preview_state='failed',preview_error=str(exc));save(folder/'video.json',meta)

def annotate(vid,seconds,bounds,label,annotation_id=None,track_id=None):
    folder=video_path(vid);meta=read(folder/'video.json')
    if not meta:raise ValueError('Video not found')
    aid=checked_id(annotation_id) if annotation_id else uuid.uuid4().hex
    track_id=checked_id(track_id) if track_id else None
    existing=read(folder/'annotations.json',[])
    if any(a['id']==aid for a in existing):return existing
    if label not in LABELS:raise ValueError('Unknown label')
    seconds=float(seconds)
    if not np.isfinite(seconds) or seconds<0 or seconds>=meta['duration']:raise ValueError('Invalid video time')
    from bisect import bisect_left
    times=timeline(folder) if track_id else []
    frame_index=min(bisect_left(times,seconds-1e-6),len(times)-1) if times else None
    if frame_index is not None:seconds=times[frame_index]
    if track_id:
        siblings=[a for a in existing if a.get('track_id')==track_id]
        if any(a['label']!=label for a in siblings):raise ValueError('One object track must have one label')
        if any(a.get('frame_index')==frame_index for a in siblings):raise ValueError('This object already has a selection on this frame')
    image,_=frame_at(folder,seconds);h,w=image.shape[:2]
    x,y,bw,bh=[float(bounds[k]) for k in ('x','y','w','h')]
    if not all(np.isfinite(v) for v in (x,y,bw,bh)) or x<0 or y<0 or bw<=0 or bh<=0 or x+bw>1.00001 or y+bh>1.00001:raise ValueError('Draw a target inside the image')
    l,t=max(0,int(x*w)),max(0,int(y*h));r,b=min(w,int(np.ceil((x+bw)*w))),min(h,int(np.ceil((y+bh)*h)))
    if r-l<3 or b-t<3:raise ValueError('Select a target at least 3 native pixels wide and high')
    crop=image[t:b,l:r]
    from temporal_model import shape_descriptor
    cv2.imwrite(str(folder/(aid+'.png')),crop)
    with LOCK:
        annotations=read(folder/'annotations.json',[])
        if any(a['id']==aid for a in annotations):return annotations
        annotations.append(dict(id=aid,time=seconds,label=label,bounds=dict(x=x,y=y,w=bw,h=bh),pixels=dict(width=r-l,height=b-t),image=aid+'.png',schema_version=2,track_id=track_id,frame_index=frame_index,shape_descriptor=shape_descriptor(crop)))
        save(folder/'annotations.json',annotations)
    return annotations

def train():
    mid=uuid.uuid4().hex;folder=DATA/'models'/mid;folder.mkdir()
    examples=[];temporal_records=[];omitted_hashes=read(DATA/'omitted-videos.json',{})
    for v in sorted((DATA/'videos').iterdir()):
        if not v.is_dir():continue
        meta=read(v/'video.json',{})
        if read(v/'training-excluded.json',{}).get('excluded') or meta.get('sha256') in omitted_hashes:continue
        for a in read(v/'annotations.json',[]):
            name=f'{v.name}-{a["id"]}.png';shutil.copyfile(v/a['image'],folder/name)
            examples.append(dict(video_id=v.name,annotation=a['id'],label=a['label'],image=name,annotation_data=a))
            if a.get('track_id'):
                source_sha=meta.get('sha256')
                if not source_sha:
                    digest=hashlib.sha256()
                    with (v/'source').open('rb') as stream:
                        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
                    source_sha=digest.hexdigest()
                recording_group=source_sha
                session=meta.get('provenance',{}).get('session_id')
                if session and re.fullmatch(r'[0-9TZ]+-[a-f0-9]{6}',session):
                    generation=read(STATION/'sessions'/session/'manifest.json',{}).get('spool_generation')
                    if generation and re.fullmatch(r'run-[a-f0-9]+',generation):recording_group='capture:'+generation
                temporal_records.append(dict(a,source_sha256=source_sha,recording_group=recording_group))
    from email_training import reviewed_examples
    for reviewed in reviewed_examples(DATA):
        name='email-'+reviewed['id']+'.png';shutil.copyfile(reviewed['image'],folder/name)
        examples.append(dict(video_id=None,annotation=reviewed['id'],label=reviewed['label'],image=name,annotation_data=dict(id=reviewed['id'],label=reviewed['label'],pixels=dict(width=reviewed['native_width'],height=reviewed['native_height']),source='explicit_email_review')))
    if not examples:raise ValueError('Select and save at least one target before training')
    model=dict(id=mid,created=time.time(),kind='multiscale normalized appearance matching',examples=examples,classes=sorted({e['label'] for e in examples}),notes='Learns saved target appearances. Testing on the same video measures re-identification, not generalization to new footage.')
    from temporal_model import fit
    model.update(schema_version=2,temporal=fit(temporal_records))
    save(folder/'temporal-annotations.json',temporal_records)
    save(folder/'model.json',model);save(DATA/'active-model.json',model)
    queue_model_publication(model)
    return model

def model_templates(model):
    result=[]
    for e in model['examples']:
        im=cv2.imread(str(DATA/'models'/model['id']/e['image']),cv2.IMREAD_GRAYSCALE)
        if im is None:raise ValueError('Missing model example')
        # Uniform selections do not provide enough structure for reliable matching.
        if im.std()<2:continue
        result.append((e['label'],im))
    if not result:raise ValueError('Targets lack visual detail. Include the object boundary and a little surrounding background.')
    return result

def detect(image,templates,threshold,labels,verify_detail=True):
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY);h,w=gray.shape;matches=[]
    # Native pixels are used for both the saved examples and full-frame inference.
    for label,template in templates:
        th,tw=template.shape
        for scale in (.65,.8,1.,1.25,1.6):
            sw,sh=round(tw*scale),round(th*scale)
            if min(sw,sh)<3 or sw>w or sh>h:continue
            target=cv2.resize(template,(sw,sh),interpolation=cv2.INTER_AREA if scale<1 else cv2.INTER_CUBIC)
            if target.std()<2:continue
            scores=cv2.matchTemplate(gray,target,cv2.TM_CCOEFF_NORMED)
            # Raw NCC can be almost perfect for two unrelated smooth gradients.
            # Verify fine spatial structure independently before calling it an object.
            target_detail=None
            if verify_detail and label!='cloud':
                target_float=target.astype(np.float32)
                # A linear sky gradient has no localized subject; blur boundaries
                # and 8-bit quantization must not manufacture apparent detail.
                xx=np.arange(sw,dtype=np.float32)-(sw-1)/2
                yy=np.arange(sh,dtype=np.float32)-(sh-1)/2
                ax=float(np.sum(target_float*xx[None,:]))/max(1,float(sh*np.sum(xx*xx)))
                ay=float(np.sum(target_float*yy[:,None]))/max(1,float(sw*np.sum(yy*yy)))
                structure=target_float-target_float.mean()-ax*xx[None,:]-ay*yy[:,None]
                if structure.std()<.5:continue
                target_detail=target_float-cv2.GaussianBlur(target_float,(0,0),1.2)
                if target_detail.std()<.2:continue
            # Nonmaximum suppression allows multiple objects from a learned class.
            for _ in range(8):
                _,score,_,location=cv2.minMaxLoc(scores)
                if score<threshold:break
                x,y=location
                detail_score=None
                if target_detail is not None:
                    patch=gray[y:y+sh,x:x+sw].astype(np.float32)
                    detail=patch-cv2.GaussianBlur(patch,(0,0),1.2)
                    if detail.std()>=.2:detail_score=float(cv2.matchTemplate(detail,target_detail,cv2.TM_CCOEFF_NORMED)[0,0])
                if target_detail is None or (detail_score is not None and np.isfinite(detail_score) and detail_score>=.55):
                    match=dict(label=label,score=float(score),box=[x,y,sw,sh])
                    if detail_score is not None:match['detail_score']=detail_score
                    matches.append(match)
                scores[max(0,y-sh//2):min(scores.shape[0],y+sh//2+1),max(0,x-sw//2):min(scores.shape[1],x+sw//2+1)]=-1
    result=[]
    for m in sorted(matches,key=lambda v:-v['score']):
        x,y,bw,bh=m['box']
        def overlap(n):
            xx,yy,ww,hh=n['box'];inter=max(0,min(x+bw,xx+ww)-max(x,xx))*max(0,min(y+bh,yy+hh)-max(y,yy))
            return inter/max(1,min(bw*bh,ww*hh))
        if not any(overlap(n)>.35 for n in result):result.append(m)
    # Reviewed known objects compete with anomalous examples, so stronger known
    # matches can suppress a weaker target match at the same location.
    return [m for m in result if m['label'] in labels]

def groups(indices):
    result=[]
    for i in indices:
        if not result or i>result[-1][-1]+1:result.append([i])
        else:result[-1].append(i)
    return result

def space_check(extra=0):
    if shutil.disk_usage(DATA).free<RESERVE+extra:raise ValueError('Not enough storage: preserving 100 GiB for camera recordings. Remove old lab runs or use a smaller video.')

def concat_video(files,times,dest,count,last_duration=None):
    final_duration=last_duration or (times[-1]-times[-2] if len(times)>1 else 1/30)
    listing=dest.with_suffix('.concat')
    lines=[]
    for i,p in enumerate(files):
        delta=(times[i+1]-times[i]) if i+1<len(times) else final_duration
        lines.extend([f"file '{p.resolve()}'",'option framerate 1000000',f'duration {max(.000001,delta):.9f}'])
    lines.extend([f"file '{files[-1].resolve()}'",'option framerate 1000000'])
    listing.write_text('\n'.join(lines)+'\n')
    run_command([FFMPEG,'-v','error','-threads','1','-safe','0','-f','concat','-i',str(listing),'-frames:v',str(count),'-fps_mode','vfr','-enc_time_base','1:90000','-c:v','libx264','-threads','1','-preset','fast','-bf','0','-crf','18','-vf','pad=ceil(iw/2)*2:ceil(ih/2)*2','-pix_fmt','yuv420p','-bsf:v',f'setts=duration={max(1,round(final_duration*90000))}:time_base=1/90000','-movflags','+faststart','-y',str(dest)],timeout=7200)
    listing.unlink()

def evaluate(rid,vid,model,threshold,labels,resume=False):
    if os.environ.get('UAP_LAB_WORKER_CONFIG'):
        from remote_evaluation import evaluate as remote_evaluate
        return remote_evaluate(rid,vid,model,threshold,labels)
    folder=DATA/'runs'/rid;previous=read(folder/'run.json',{});status=dict(id=rid,video_id=vid,model_id=model['id'],state='extracting',progress=0,created=previous.get('created',time.time()),threshold=threshold,labels=labels,detached=previous.get('detached',False),inference_revision=2)
    def update(**v):status.update(v);save(folder/'run.json',status)
    batch_matcher=None
    try:
        source=video_path(vid)/'source';templates=model_templates(model);frames=folder/'frames';frames.mkdir(exist_ok=True);space_check()
        cached=read(folder/'timestamps.json',{}) if resume else {}
        files=sorted(frames.glob('*.png'))
        if cached and len(files)==cached.get('frame_count') and len(files)==len(cached.get('times',[])):
            times=cached['times'];durations=cached.get('durations') or [None]*len(times);timing=[dict(pkt_duration_time=value) for value in durations]
            update(message='Reusing extracted native frames; evaluating with cloud-detail rejection.')
        else:
            update(message='Extracting every source frame as lossless PNG; preserving source timestamps.')
            # Frame timestamps are kept separately so variable-rate sources do not become fixed-rate videos.
            raw=json.loads(run_command([FFPROBE,'-v','error','-select_streams','v:0','-show_frames','-show_entries','frame=best_effort_timestamp_time,pkt_duration_time','-of','json',str(source)],timeout=7200))
            timing=raw['frames'];times=[float(v['best_effort_timestamp_time']) for v in timing]
            if not times or any(b<=a for a,b in zip(times,times[1:])):raise ValueError('Video timestamps are missing or non-increasing; cannot preserve native timing safely')
            meta=read(video_path(vid)/'video.json');space_check(len(times)*meta['width']*meta['height']*3)
            log=folder/'extraction.log'
            with log.open('wb') as out:
                proc=subprocess.Popen([FFMPEG,'-v','error','-threads','1','-i',str(source),'-map','0:v:0','-fps_mode','passthrough','-c:v','png','-threads','1',str(frames/'%09d.png')],env=ENV,stdout=out,stderr=out)
                try:
                    while proc.poll() is None:
                        space_check();time.sleep(1)
                    if proc.returncode:raise ValueError(log.read_text()[-3000:])
                except BaseException:
                    proc.terminate();proc.wait();raise
            files=sorted(frames.glob('*.png'))
            if len(files)!=len(times):raise ValueError(f'Decoded {len(files)} frames but found {len(times)} timestamps')
            save(folder/'timestamps.json',dict(times=times,durations=[v.get('pkt_duration_time') for v in timing],source_fps=meta['fps'],frame_count=len(files),first_frame_index=0))
        batch_matcher=None
        if os.environ.get('UAP_LAB_SEARCH')=='coarse':
            from batch_matcher import BatchMatcher
            batch_matcher=BatchMatcher(templates)
        detections={};update(state='detecting',frame_count=len(files),message='Searching every native frame with the frozen appearance model.')
        with (folder/'detections.jsonl').open('w') as output:
            for i,path in enumerate(files):
                space_check();update(progress=round(i/len(files),4),processed_frames=i)
                image=cv2.imread(str(path))
                matches=batch_matcher.predict(image,threshold,labels) if batch_matcher else detect(image,templates,threshold,labels)
                if matches:detections[i]=matches
                output.write(json.dumps(dict(frame=i,time=times[i],objects=matches))+'\n')
        segments=[];update(state='exporting',progress=1,message='Saving detected frames, boundary frames, full-size clips, and cropped target clips.')
        for number,group in enumerate(groups(sorted(detections)),1):
            space_check();first,last=max(0,group[0]-1),min(len(files)-1,group[-1]+1)
            event=folder/f'event-{number:04d}';event.mkdir();selected=event/'frames';selected.mkdir()
            for i in range(first,last+1):os.link(files[i],selected/files[i].name)
            seq=files[first:last+1];ts=times[first:last+1]
            concat_video(seq,ts,event/'full-size.mp4',len(seq),float(timing[last].get('pkt_duration_time') or 0) or None)
            # Each detected target gets its own centered crop video; contextual frames use nearest detection.
            tracks=[]
            for i in group:
                for match in detections[i]:
                    x,y,w,h=match['box'];cx,cy=x+w/2,y+h/2
                    candidates=[tr for tr in tracks if tr['label']==match['label'] and tr['last']>=i-1 and i not in tr['boxes'] and abs(cx-tr['cx'])+abs(cy-tr['cy'])<max(80,4*max(w,h))]
                    track=min(candidates,key=lambda tr:abs(cx-tr['cx'])+abs(cy-tr['cy'])) if candidates else None
                    if track is None:track=dict(label=match['label'],last=i,cx=cx,cy=cy,boxes={});tracks.append(track)
                    track.update(last=i,cx=cx,cy=cy);track['boxes'][i]=match['box']
            crops=[]
            for n,track in enumerate(tracks,1):
                cropdir=event/f'crop-{n:03d}';cropdir.mkdir()
                boxes=track['boxes'];a,b=max(0,min(boxes)-1),min(len(files)-1,max(boxes)+1)
                side=max(32,int(max(max(v[2:]) for v in boxes.values())*1.6));side+=side%2
                for i in range(a,b+1):
                    box=boxes[min(boxes,key=lambda k:abs(k-i))];image=cv2.imread(str(files[i]));h,w=image.shape[:2];x,y,bw,bh=box
                    # Padding preserves a fixed crop size even when the target reaches an image edge.
                    cx,cy=round(x+bw/2),round(y+bh/2);pad=side
                    image=cv2.copyMakeBorder(image,pad,pad,pad,pad,cv2.BORDER_REPLICATE)
                    patch=image[cy+pad-side//2:cy+pad+side//2,cx+pad-side//2:cx+pad+side//2]
                    # Native-sized crop; no invented detail or unnecessary upscaling.
                    cv2.imwrite(str(cropdir/files[i].name),patch)
                dest=event/f'target-{n:03d}.mp4';concat_video(sorted(cropdir.glob('*.png')),times[a:b+1],dest,b-a+1,float(timing[b].get('pkt_duration_time') or 0) or None);shutil.rmtree(cropdir)
                crops.append(dict(target_id=n,label=track['label'],file=str(dest.relative_to(folder)),first_frame=a,last_frame=b))
            segment=dict(first_detected=group[0],last_detected=group[-1],first_saved=first,last_saved=last,start_seconds=times[first],end_seconds=times[last],full_size=str((event/'full-size.mp4').relative_to(folder)),crops=crops,frames=str(selected.relative_to(folder)))
            save(event/'event.json',segment);segments.append(segment);update(segments=segments)
        update(state='complete',segments=segments,detected_frames=len(detections),completed=time.time(),message='Complete. Same-video results demonstrate re-identification; use another video to assess generalization.')
    except Exception as exc:update(state='failed',error=str(exc),message='Run failed; partial files retained for inspection.')
    finally:
        if batch_matcher:batch_matcher.close()

JOB_LOCK=threading.Lock()
def start_run(vid,threshold,labels,model=None):
    checked_id(vid)
    if not read(video_path(vid)/'video.json'):raise ValueError('Video not found')
    threshold=float(threshold)
    if not .5<=threshold<=.9999:raise ValueError('Threshold must be between 0.5 and 0.9999')
    if not labels or set(labels)-set(LABELS):raise ValueError('Choose valid target labels')
    model=model or read(DATA/'active-model.json')
    if not model:raise ValueError('Train a model first')
    if not set(labels)&set(model['classes']):raise ValueError('The model has no examples for the selected labels')
    if any(r.get('detached') and r.get('state') not in ('complete','failed') for r in (read(p,{}) for p in (DATA/'runs').glob('*/run.json'))):raise ValueError('A video test is already running in the background')
    if not JOB_LOCK.acquire(False):raise ValueError('A test is already running')
    rid=uuid.uuid4().hex;folder=DATA/'runs'/rid;folder.mkdir()
    save(folder/'model.json',model);save(folder/'run.json',dict(id=rid,video_id=vid,model_id=model['id'],state='queued',created=time.time(),threshold=threshold,labels=labels,detached=bool(os.environ.get('UAP_LAB_WORKER_CONFIG'))))
    if os.environ.get('UAP_LAB_WORKER_CONFIG'):
        with (folder/'dispatcher.log').open('ab') as log:
            subprocess.Popen([__import__('sys').executable,str(ROOT/'dispatch_job.py'),rid],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
        JOB_LOCK.release();return rid
    def work():
        try:evaluate(rid,vid,model,threshold,labels)
        finally:JOB_LOCK.release()
    threading.Thread(target=work,daemon=True).start();return rid

TRAINING_FOLDER=Path(os.environ.get('UAP_LAB_TRAINING_FOLDER','/home/hackrf/t7/training-data'))
_INTAKE_LOCK=threading.Lock()

def library_videos():
    """Resolve review/omission history by content, including older per-video records."""
    videos=[];recovered_reviews={};recovered_omissions={}
    for folder in (DATA/'videos').iterdir():
        video=read(folder/'video.json')
        if not video:continue
        video['annotations']=read(folder/'annotations.json',[]);video['review']=read(folder/'review.json',{})
        exclusion=read(folder/'training-excluded.json',{});video['training_excluded']=bool(exclusion.get('excluded'))
        sha=video.get('sha256')
        if sha and video['review'].get('completed'):recovered_reviews[sha]=max((recovered_reviews.get(sha,{}),video['review']),key=lambda r:r.get('reviewed_at',0))
        if sha and exclusion.get('excluded'):recovered_omissions[sha]=exclusion
        videos.append(video)
    with LOCK:
        hashes=read(DATA/'reviewed-videos.json',{});omitted=read(DATA/'omitted-videos.json',{});before_reviews=dict(hashes);before_omitted=dict(omitted)
        for sha,review in recovered_reviews.items():
            if sha not in hashes or review.get('reviewed_at',0)>hashes[sha].get('reviewed_at',0):hashes[sha]=review
        for sha,exclusion in recovered_omissions.items():omitted.setdefault(sha,exclusion)
        if hashes!=before_reviews:save(DATA/'reviewed-videos.json',hashes)
        if omitted!=before_omitted:save(DATA/'omitted-videos.json',omitted)
    for video in videos:
        sha=video.get('sha256')
        if sha in hashes:video['review']=hashes[sha]
        if sha in omitted:video['training_excluded']=True
    return videos

def find_video_by_sha(sha):
    for folder in sorted((DATA/'videos').iterdir()):
        meta=read(folder/'video.json',{})
        if meta.get('sha256')==sha:return meta
    return None

def import_training_file(path):
    """Register arbitrary stable videos once by bytes, independent of filenames."""
    import mimetypes
    path=Path(path).resolve();stat=path.stat();sig=[stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns];key=str(path)
    with _INTAKE_LOCK:
        index=read(DATA/'intake-index.json',{});known=index.get(key,{})
        if known.get('signature')==sig:
            meta=read(video_path(known['video_id'])/'video.json')
            if meta and (video_path(meta['id'])/'source').is_file():return meta,False
        digest=hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
        after=path.stat()
        if [after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns]!=sig:raise ValueError('Video is still changing; waiting for the copy to finish')
        sha=digest.hexdigest();existing=find_video_by_sha(sha);vid=existing['id'] if existing else sha[:32];folder=video_path(vid)
        if existing and (folder/'source').is_file():
            index[key]=dict(signature=sig,sha256=sha,video_id=vid);save(DATA/'intake-index.json',index);return existing,False
        meta=probe(path)
        if meta['duration']<=0:raise ValueError('Video duration unavailable')
        folder.mkdir(exist_ok=True);space_check(stat.st_size)
        temporary=folder/('source.part-'+uuid.uuid4().hex)
        try:
            copy_evidence(path,temporary)
            after=path.stat()
            if [after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns]!=sig:raise ValueError('Video changed during import; waiting for the copy to finish')
            temporary.replace(folder/'source')
        finally:
            temporary.unlink(missing_ok=True)
        if existing:meta=existing
        else:
            meta.update(id=vid,name=path.name,created=time.time(),bytes=stat.st_size,sha256=sha,mime=mimetypes.guess_type(path.name)[0] or 'video/mp4',provenance=dict(collection='training-data',local_file=key))
            if not (path.suffix.lower() in ('.mp4','.m4v','.mov') and meta['codec']=='h264'):meta['preview_state']='preparing'
            save(folder/'video.json',meta)
        index[key]=dict(signature=sig,sha256=sha,video_id=vid);save(DATA/'intake-index.json',index)
        return meta,not bool(existing)

def watch_training_folder():
    TRAINING_FOLDER.mkdir(parents=True,exist_ok=True);observed={};registered=set()
    library_videos() # Repair legacy review registries before any duplicate is imported.
    while True:
        try:
            for path in TRAINING_FOLDER.rglob('*'):
                if not path.is_file() or path.is_symlink() or path.suffix.lower() not in ('.mp4','.mov','.mkv','.webm','.avi','.m4v','.mts'):continue
                key=str(path.resolve());stat=path.stat();sig=(stat.st_ino,stat.st_size,stat.st_mtime_ns)
                if (key,sig) in registered:continue
                before=observed.get(key)
                if before is None or before[0]!=sig:observed[key]=(sig,time.monotonic());continue
                if time.monotonic()-before[1]<10:continue
                try:
                    meta,created=import_training_file(path);registered.add((key,sig))
                    if created and meta.get('preview_state')=='preparing':prepare_preview(video_path(meta['id']))
                except Exception as exc:print('Training folder import:',path,str(exc),flush=True)
        except Exception as exc:print('Training folder scan:',str(exc),flush=True)
        time.sleep(5)


def queue_model_publication(model):
    publication=DATA/'publication';config=read(publication/'config.json',{})
    if not config.get('enabled'):return
    outbox=publication/'outbox';outbox.mkdir(parents=True,exist_ok=True)
    request=outbox/(checked_id(model['id'])+'.json')
    if not request.exists():save(request,dict(model_id=model['id'],created=model.get('created',time.time()),state='queued',attempts=0))

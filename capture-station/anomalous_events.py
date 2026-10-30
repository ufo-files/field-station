"""Independent evidence copies for observer-flagged anomalous events."""
import json
from pathlib import Path
import re
from experiments import load,save
from boxed_frames import copy_boxed


def sync_anomalous(data):
    data=Path(data);root=data/'anomalous'
    if root.is_symlink():raise ValueError('Anomalous folder must not be a symlink')
    root.mkdir(exist_ok=True);count=0
    for source in sorted(data.glob('*/motion-events.json')):
        if not re.fullmatch(r'[0-9TZ]+-[a-f0-9]{6}',source.parent.name):continue
        for event in load(source,[]):
            review=event.get('human_review',{})
            model_event=event.get('classification',{}).get('source')=='uap-lab' and any(r.get('object',{}).get('label')=='anomalous' for r in event.get('classification',{}).get('regions',[]))
            if not any(r.get('object')=='anomalous' for r in review.get('regions',[])) and not (model_event and not review):continue
            eid=event.get('id','')
            if not re.fullmatch(r'[a-f0-9]{16}',eid):continue
            sid=source.parent.name;target=root/(sid+'--'+eid)
            if target.is_symlink():raise ValueError('Anomalous event folder must not be a symlink')
            target.mkdir(exist_ok=True)
            for original in source.parent.glob(f'motion-{eid}-*'):
                if original.suffix.lower() in ('.jpg','.jpeg','.png') and original.is_file():copy_boxed(original,target/original.name)
            manifest=load(source.parent/'manifest.json',{})
            summary=dict(session_id=sid,event_id=eid,human_review=review,flag_source='human' if review else 'uap-lab-model',event=event,
                source_video=dict(session_directory='../..'+'/'+sid,local_url=f'/sessions/{sid}/video.mp4',
                                  archive_url=manifest.get('internet_archive',{}).get('video_url'),
                                  event_time=event.get('detected_at'),note='Original session and video remain in their original location.'))
            existing=load(target/'event.json',{})
            if existing!=summary:save(target/'event.json',summary)
            count+=1
    return count

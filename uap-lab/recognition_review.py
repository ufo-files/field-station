"""Read-only suggestions aligned by exact encoded packet identity, never guessed time."""
import bisect,hashlib,json,sqlite3
from contextlib import closing
from pathlib import Path

def packets(path):
 import lab,re
 from fractions import Fraction
 # Remuxing can add non-picture headers. Hash unchanged coded slices in a common
 # Annex B representation; never rewrite the original evidence.
 raw=lab.run_command([lab.FFMPEG,'-v','error','-threads','1','-copyts','-i',str(path),'-map','0:v:0','-an','-c:v','copy','-bsf:v','h264_mp4toannexb,filter_units=pass_types=1-5','-f','framehash','-hash','sha256','pipe:1'],timeout=120)
 if isinstance(raw,bytes):raw=raw.decode()
 timebase=None;result=[]
 for line in raw.splitlines():
  if line.startswith('#tb 0:'):timebase=Fraction(line.split(':',1)[1].strip())
  if not line or line.startswith('#'):continue
  fields=[v.strip() for v in line.split(',')]
  if len(fields)!=6 or timebase is None:raise ValueError('Invalid encoded-slice hash output')
  result.append(dict(pts_time=float(int(fields[2])*timebase),data_hash=fields[5]))
 return result

def align(movie,source):
 """Require a unique contiguous match; identical repeated pictures are not collapsed."""
 candidates=[];hashes=[p['hash'] for p in source];target=[p['data_hash'] for p in movie]
 if not target:raise ValueError('Video contains no packets')
 for start in range(len(source)-len(movie)+1):
  if hashes[start]==target[0] and hashes[start:start+len(movie)]==target:candidates.append(start)
 if len(candidates)!=1:raise ValueError('Original packet alignment is missing or ambiguous')
 start=candidates[0];selected=source[start:start+len(movie)]
 if any(b['sequence']!=a['sequence']+1 for a,b in zip(selected,selected[1:])):raise ValueError('Original source sequence has a gap')
 return [dict(sequence=s['sequence'],pts_seconds=s['pts_seconds'],time=float(m['pts_time'])) for m,s in zip(movie,selected)]

def mapping(folder,meta):
 import lab
 cache=lab.read(folder/'recognition-frame-map.json',{})
 if cache.get('source_sha256')==meta['sha256']:return cache
 sid=meta.get('provenance',{}).get('session_id')
 import re
 if not sid or not re.fullmatch(r'[0-9TZ]+-[a-f0-9]{6}',sid):raise ValueError('Suggestions are available for new station recordings; this clip has no native capture mapping')
 session=lab.STATION/'sessions'/sid;manifest=lab.read(session/'manifest.json',{});buffer=lab.read(session/'buffer-state.json',{});generation=manifest.get('spool_generation')
 if not generation and buffer.get('segments'):
  import os
  first=buffer['segments'][0];candidates=[]
  if re.fullmatch(r'segment-\d+\.mkv',first.get('file','')):
   for run in Path(os.environ['CAPTURE_BUFFER_ROOT']).glob('run-*'):
    if lab.read(run/(first['file']+'.json'),{}).get('sha256')==first.get('sha256') and first.get('sha256'):candidates.append(run.name)
  if len(candidates)==1:generation=candidates[0]
 if not generation or not re.fullmatch(r'run-[a-f0-9]+',generation):raise ValueError('Original capture generation unavailable')
 import os
 from native_frames import timing_rows
 root=Path(os.environ['CAPTURE_BUFFER_ROOT'])/generation;source=[]
 for segment in buffer.get('segments',[]):
  name=segment['file']
  if not re.fullmatch(r'segment-\d+\.mkv',name):raise ValueError('Invalid segment path')
  path=root/name
  if not path.is_file():raise ValueError('Original segments are unavailable for verified suggestion alignment')
  times=timing_rows(root,segment['start'],segment['end']);values=[r['pts_seconds'] for r in times]
  for packet in packets(path):
   pts=segment['start']+float(packet['pts_time']);near=bisect.bisect_left(values,pts);options=[i for i in (near-1,near) if 0<=i<len(times)];choice=min(options,key=lambda i:abs(values[i]-pts)) if options else None
   if choice is None or abs(values[choice]-pts)>.003:raise ValueError('Original packet timestamp is unmatched')
   source.append(dict(sequence=times[choice]['sequence'],pts_seconds=times[choice]['pts_seconds'],hash=packet['data_hash']))
 result=dict(source_sha256=meta['sha256'],generation=generation,frames=align(packets(folder/'source'),source),method='unique_contiguous_encoded_slice_SHA256')
 lab.save(folder/'recognition-frame-map.json',result);return result

def proposals(vid,after=-1,limit=100):
 import lab
 folder=lab.video_path(vid);meta=lab.read(folder/'video.json')
 if not meta:raise ValueError('Video not found')
 if lab.read(folder/'training-excluded.json',{}).get('excluded') or meta['sha256'] in lab.read(lab.DATA/'omitted-videos.json',{}) or lab.read(lab.DATA/'reviewed-videos.json',{}).get(meta['sha256'],{}).get('completed') or lab.read(folder/'review.json',{}).get('completed'):return dict(items=[],message='This video has already been reviewed or excluded.')
 db=lab.DATA/'recognition/results.sqlite'
 if not db.exists():return dict(items=[],message='Local recognition is starting.')
 origin=mapping(folder,meta);frames=origin['frames'];by_sequence={r['sequence']:r for r in frames};items=[];analyzed=0;ordinal=0;limit=min(100,max(1,int(limit)))
 with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=5)) as connection:
  rows=connection.execute('SELECT sequence,observations FROM frames WHERE generation=? AND sequence>=? AND sequence<=? ORDER BY sequence',(origin['generation'],frames[0]['sequence'],frames[-1]['sequence']))
  for sequence,encoded in rows:
   if sequence not in by_sequence:continue
   analyzed+=1;frame=by_sequence[sequence]
   for observation in json.loads(encoded):
    index=ordinal;ordinal+=1
    if index<=after or len(items)>=limit:continue
    x,y,w,h=observation['box'];track=hashlib.sha256(observation['proposed_track_id'].encode()).hexdigest()[:32]
    items.append(dict(index=index,id=hashlib.sha256(f'{meta["sha256"]}:{track}:{sequence}'.encode()).hexdigest()[:32],track_id=track,time=frame['time'],sequence=sequence,bounds=dict(x=x/meta['width'],y=y/meta['height'],w=w/meta['width'],h=h/meta['height']),suggested_label=observation['suggested_label'],scores=observation['scores'],ambiguous_link=observation['ambiguous_link'],direction_change_degrees=observation['direction_change_degrees'],human_confirmed=False))
 return dict(items=items,total_suggestions=ordinal,analyzed_frames=analyzed,native_frames=len(frames),next_after=items[-1]['index'] if items and items[-1]['index']<ordinal-1 else None,message='Suggestions are unconfirmed. Review each box and label before saving.' if items else 'No suggestions yet for this clip. Recognition coverage may start after this recording.')

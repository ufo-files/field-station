"""User-managed Archive subjects, independent of video encoding and labels."""
BASE=['sky observation','camera','RF measurements']
RESERVED={s.casefold() for s in [*BASE,'ce5-tones']}
def normalize(tags):
 if not isinstance(tags,list) or len(tags)>30:raise ValueError('Use up to 30 tags.')
 result=[];seen=set()
 for value in tags:
  if not isinstance(value,str):raise ValueError('Tags must be text.')
  tag=' '.join(value.split())
  if not tag:continue
  if len(tag)>64 or any(c in value for c in '\r\n;') or any(ord(c)<32 for c in value):raise ValueError('Use short tags without line breaks or semicolons.')
  key=tag.casefold()
  if key in RESERVED:raise ValueError('Automatic tags are managed by the station.')
  if key not in seen:result.append(tag);seen.add(key)
 return result

def subjects(job):return [*BASE,*(['ce5-tones'] if job.get('ce5_playback') else []),*normalize(job.get('custom_tags',[]))]

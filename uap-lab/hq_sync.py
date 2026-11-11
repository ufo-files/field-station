"""Frame-only HQ replication; compare review revisions under the canonical write lock."""
import hashlib,json,re,time
from pathlib import Path

def revision(record):
 if not record or not record.get('human_confirmed') or record.get('deleted'):return 'unreviewed'
 values=[record.get('sample_id',record.get('event_id')),record.get('label'),record.get('reviewed_epoch',0)]
 return hashlib.sha256(json.dumps(values,separators=(',',':')).encode()).hexdigest()

def identity(key):
 if re.fullmatch('[a-f0-9]{32}',key or ''):return key,key
 parts=(key or '').split(':')
 if len(parts)==3 and parts[0]=='review' and all(re.fullmatch('[a-f0-9]{32}',v) for v in parts[1:]):return parts[1],parts[2]
 raise ValueError('Invalid review object')

def snapshot(data):
 from detection_library import listing,refresh
 data=Path(data);cached,indexing,error=refresh(data);rows=listing(data,export=True)
 for row in rows:
  _,sample=identity(row['id']);row['review_revision']=revision(dict(sample_id=sample,label=row['label'],reviewed_epoch=row.get('created',0),human_confirmed=row['human_reviewed']))
 return dict(schema=1,generated_epoch=time.time(),complete=cached is not None and cached[0]!=0,items=rows)

def apply_reviews(data,body):
 from detection_library import _SAVE_LOCK,label
 from email_training import review_batch
 from label_queue import read
 from retired_data import save
 data=Path(data);items=body.get('items');results=[]
 if not isinstance(items,list) or not 1<=len(items)<=50:raise ValueError('Choose 1–50 reviews')
 with _SAVE_LOCK,review_batch(data):
  for item in items:
   key=item.get('id','');request=item.get('request_id','');category=item.get('label')
   if not re.fullmatch('[a-f0-9]{32}',request) or category not in ('anomalous','not_anomalous'):raise ValueError('Invalid review request')
   event,sample=identity(key);receipt=data/'hq-sync/receipts'/(request+'.json');old=read(receipt,{})
   if old:
    if old['id']!=key or old['label']!=category:raise ValueError('Request ID already used')
    results.append(old);continue
   record=read(data/'email-reviews/examples'/sample/'review.json',{})
   current=revision(record)
   own=record.get('message_id') in ('quick-label:'+request,'object-label:'+request)
   if current!=item.get('base_revision') and not own:
    if not (record.get('human_confirmed') and record.get('label')==category and not record.get('deleted')):
     results.append(dict(id=key,request_id=request,state='conflict',error='This object changed at the field station. Review the current decision.',current_label=record.get('label'),current_revision=current));continue
   try:
    result=label(data,dict(id=key,label=category,request_id=request))
    record=read(data/'email-reviews/examples'/sample/'review.json',{})
    answer=dict(id=key,label=category,request_id=request,state='synced',review_revision=revision(record),reviewer=str(item.get('reviewer','HQ reviewer'))[:100],synced_epoch=time.time())
    receipt.parent.mkdir(parents=True,exist_ok=True);save(receipt,answer);results.append(answer)
   except (OSError,ValueError,KeyError) as exc:
    results.append(dict(id=key,request_id=request,state='attention',error=str(exc)[:500]))
 return dict(results=results)

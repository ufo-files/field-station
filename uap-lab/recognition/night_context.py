"""Conservative, model-qualified nighttime context confirmation; retains all observations."""
import math
from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

@lru_cache(maxsize=8)
def boundaries(day):
 from astral import Observer
 from astral.sun import sun
 value=sun(Observer(37.7749,-122.4194),date=day,tzinfo=ZoneInfo('America/Los_Angeles'))
 return value['sunrise'].timestamp(),value['sunset'].timestamp()

def enabled(policy,epoch):
 rule=policy.get('night_context_confirmation',{})
 if not rule.get('enabled') or rule.get('version')!=policy.get('version') or policy.get('input_color_space')!='RGB':return False
 if not isinstance(epoch,(int,float)) or not math.isfinite(epoch) or epoch<=0:return False
 local=datetime.fromtimestamp(epoch,ZoneInfo('America/Los_Angeles'));rise,setting=boundaries(local.date())
 return not rise<=epoch<setting

def predict(worker,images,contexts,policy,request_id):
 results=worker.predict(images,request_id)
 if not contexts:return results
 if len(contexts)!=len(images) or len(results)!=len(images):raise ValueError('Night context crop mapping mismatch')
 rule=policy['night_context_confirmation'];floor=rule['minimum_context_score']
 if not 0<floor<=.001:raise ValueError('Night context cutoff exceeds conservative limit')
 selected=[i for i,r in enumerate(results) if not r.get('error') and r['scores']['anomalous']>=policy['thresholds']['anomalous']]
 if not selected:return results
 checks=worker.predict([contexts[i] for i in selected],str(request_id)+':context')
 if len(checks)!=len(selected):raise ValueError('Missing night context predictions')
 for i,check in zip(selected,checks):
  if check.get('error'):raise ValueError('Night context inference failed')
  score=check['scores']['anomalous']
  if not math.isfinite(score) or not 0<=score<=1:raise ValueError('Invalid night context score')
  results[i]['night_context']=dict(score=score,minimum_score=floor,suppressed=score<floor,geometry='review-context-v1')
 return results

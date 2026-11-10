"""Eligibility for opt-in daytime machine-negative retention."""
import math
from datetime import datetime
from observation_metrics import TZ,daylight

def is_daytime(stamp):
 if isinstance(stamp,bool) or not isinstance(stamp,(int,float)) or not math.isfinite(stamp) or stamp<=0:return False
 rise,setting=daylight(datetime.fromtimestamp(stamp,TZ).date())
 return rise<=stamp<setting

def eligible(event,now,policy):
 if policy.get('enabled') is not True or not is_daytime(now):return False
 if event.get('classification')!='not_anomalous':return False
 if event.get('kind')=='manual_recording' or event.get('manual_session_id') or event.get('capture_origin')=='manual' or event.get('starred'):return False
 captured=event.get('detected_epoch')
 if not is_daytime(captured):return False
 age=policy.get('after_seconds',10800)
 if isinstance(age,bool) or not isinstance(age,(int,float)) or not math.isfinite(age):return False
 return now-captured>=max(10800,age)

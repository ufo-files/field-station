"""Durable manual training cycles: stable first, then a frozen leaderboard order."""
import json,math,sys,time
from pathlib import Path
NAMES={'human':'Human-curated (stable)','experimental':'Human-curated (experimental)','hybrid':'Hybrid','machine':'Machine-only'}
MEASURES={'accuracy','false_positive_rate','recall'}

def read(path,default=None):
 try:return json.loads(Path(path).read_text())
 except FileNotFoundError:return default

def save(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value));tmp.replace(path)

def ranked_order(history,measure):
 if measure not in MEASURES:measure='false_positive_rate'
 latest=(history.get('points') or [{}])[-1];scores=latest.get('lanes',{})
 def key(lane):
  value=scores.get(lane,{}).get(measure)
  if not isinstance(value,(int,float)) or not math.isfinite(value):return (1,0)
  return (0,value if measure=='false_positive_rate' else -value)
 return ['human',*sorted(['experimental','hybrid','machine'],key=key)]

def pending(controller,request_id):
 state=read(controller.root/'cascades'/(request_id+'.json'),{})
 return bool(state) and state.get('phase') not in ('complete','complete_with_errors')

def run_manual(controller,request):
 cfg=controller.c['cascade'];path=controller.root/'cascades'/(request['id']+'.json');state=read(path)
 sys.path.insert(0,cfg['runtime'])
 from cascade_training import freeze_inputs,train_lane,compare,retry_publications
 def persist():
  state['updated_epoch']=time.time();save(path,state);save(controller.root/'cascade-status.json',state)
 def progress(phase,reason):
  try:controller.rpc('manual_training.py','progress','--json',json.dumps(dict(phase=phase,reason=reason)),timeout=10)
  except Exception:pass
 if state is None:
  measure=request.get('ranking_measure','false_positive_rate');history=read(Path(cfg['comparison_root'])/'history.json',{})
  state=dict(id=request['id'],phase='preparing',ranking_measure=measure,order=ranked_order(history,measure),ranking_sample_id=(history.get('points') or [{}])[-1].get('sample_id'),steps={},created_epoch=time.time())
  persist()
 if state['phase'] in ('complete','complete_with_errors'):return state
 if not state.get('inputs'):
  state['inputs']=freeze_inputs(cfg,request['id']);persist()
 if state['steps'].get('human',{}).get('state') not in ('complete','failed'):
  state.update(phase='training',current_lane='human');state['steps']['human']={'state':'running'};persist()
  try:
   # Resume after a process restart without training/deploying stable twice.
   deployed=controller.state.get('manual_request_id')==request['id'] and controller.state.get('phase')=='deployed'
   if not deployed:controller.tick()
   if controller.state.get('manual_activation_pending'):
    state['phase']='activation_pending';persist();return state
   if controller.state.get('phase')!='deployed':raise RuntimeError(controller.state.get('reason') or 'Stable training did not complete')
   state['steps']['human']=dict(state='complete',version=controller.state['active_version'],folder=controller.state['run_directory'])
  except Exception as exc:
   state['steps']['human']=dict(state='failed',error=str(exc))
  persist()
 if not state.get('stable_source'):
  from worker import model_folder
  state['stable_source']=str(model_folder(controller.root,controller.state['active_version']));persist()
 for index,lane in enumerate(state['order'][1:],2):
  if state['steps'].get(lane,{}).get('state') in ('complete','failed'):continue
  state.update(phase='training',current_lane=lane);state['steps'][lane]={'state':'running'};persist()
  progress('cascade_training',f'Training {index}/4: {NAMES[lane]}.')
  try:state['steps'][lane]=dict(state='complete',**train_lane(cfg,state,lane))
  except Exception as exc:state['steps'][lane]=dict(state='failed',error=str(exc))
  persist()
 state.update(phase='publishing',current_lane=None);persist()
 publication_errors=retry_publications(cfg,state)
 if publication_errors:
  state.update(phase='publication_retry_pending',publication_errors=publication_errors);persist();progress('cascade_evaluating','Training finished; model publication will retry automatically.');return state
 state.update(phase='evaluating',current_lane=None);persist();progress('cascade_evaluating','Comparing all available models on the same fresh 500 images.')
 try:
  state['comparison']=compare(cfg,state)
 except Exception as exc:
  state.update(phase='evaluation_retry_pending',error=str(exc));persist();progress('cascade_evaluating','Training finished; shared evaluation will retry automatically.');return state
 failed=[NAMES[lane] for lane,result in state['steps'].items() if result['state']=='failed']
 state.update(phase='complete_with_errors' if failed else 'complete',finished_epoch=time.time(),error=None,reason=('Training cycle finished; needs attention: '+', '.join(failed)) if failed else 'All four models trained and compared. Human-curated (stable) is live.');persist()
 return state

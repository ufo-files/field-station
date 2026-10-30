"""An evaluated deployment may change the model without resetting capture coverage."""
import hashlib,json
from pathlib import Path

def transition(state,policy,config):
 if state['model']==policy['version']:return state
 approval=config.get('model_transition',{})
 if approval.get('from_version')!=state['model'] or approval.get('to_version')!=policy['version']:raise ValueError('Model change lacks an evaluated transition')
 path=Path(approval['evaluation_path'])
 if path.is_symlink():raise ValueError('Unsafe evaluation report')
 raw=path.read_bytes();report=json.loads(raw)
 if hashlib.sha256(raw).hexdigest()!=approval.get('evaluation_sha256') or report.get('passed') is not True or report.get('baseline_version')!=state['model'] or report.get('candidate_version')!=policy['version']:raise ValueError('Model evaluation does not authorize this transition')
 return dict(state,model=policy['version'],model_history=[*state.get('model_history',[]),dict(from_version=state['model'],to_version=policy['version'],generation=state['generation'],after_sequence=state.get('last_sequence'),evaluation_sha256=approval['evaluation_sha256'])])

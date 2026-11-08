"""Retain every proposal; infer appearance only where existing policy permits a label."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from classification_taxonomy import canonical_label,LABELS
from binary_decision import decide

def eligible(observation,policy):
    return max(observation['box'][2:])>=policy['minimum_native_size']

def apply_results(observations,indices,results,policy):
    if len(indices)!=len(results):raise ValueError('Missing classification results')
    binary=set(policy.get('classes',policy.get('thresholds',{})))=={'anomalous','not_anomalous'}
    selected=set(indices)
    if len(selected)!=len(indices) or any(i<0 or i>=len(observations) for i in indices):
        raise ValueError('Invalid classification result mapping')
    for i,observation in enumerate(observations):
        if i not in selected:
            if eligible(observation,policy):raise ValueError('Eligible proposal lacks inference')
            observation.update(scores={},suggested_label='not_anomalous' if binary else 'unknown',model=policy['version'],decision_rule='anomalous-at-threshold-otherwise-not-anomalous' if binary else 'legacy-thresholds',classification_status='below_model_minimum_size')
    for i,result in zip(indices,results):
        if 'error' in result:raise ValueError('Object classification failed; source retained for retry')
        scores=result['scores'];label=max(scores,key=scores.get)
        decision=decide(scores,policy['thresholds'].get('anomalous',1.1)) if binary else canonical_label(label) if canonical_label(label) in LABELS and scores[label]>=policy['thresholds'].get(label,1.1) else 'unknown'
        observations[i].update(scores=scores,original_label=label,suggested_label=decision,model=policy['version'],decision_rule='anomalous-at-threshold-otherwise-not-anomalous' if binary else 'legacy-thresholds',classification_status='inferred')

"""Retain every proposal; infer appearance only where existing policy permits a label."""
def eligible(observation,policy):
    return max(observation['box'][2:])>=policy['minimum_native_size']

def apply_results(observations,indices,results,policy):
    if len(indices)!=len(results):raise ValueError('Missing classification results')
    selected=set(indices)
    if len(selected)!=len(indices) or any(i<0 or i>=len(observations) for i in indices):
        raise ValueError('Invalid classification result mapping')
    for i,observation in enumerate(observations):
        if i not in selected:
            if eligible(observation,policy):raise ValueError('Eligible proposal lacks inference')
            observation.update(scores={},suggested_label='unknown',model=policy['version'],classification_status='below_model_minimum_size')
    for i,result in zip(indices,results):
        if 'error' in result:raise ValueError('Object classification failed; source retained for retry')
        scores=result['scores'];label=max(scores,key=scores.get)
        observations[i].update(scores=scores,suggested_label=label if scores[label]>=policy['thresholds'].get(label,1.1) else 'unknown',model=policy['version'],classification_status='inferred')

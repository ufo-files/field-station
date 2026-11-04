"""Two-category model decision; inference failures are never negative predictions."""
import math

def decide(scores,threshold,eligible=True):
 if not {'anomalous','not_anomalous'}<=set(scores):raise ValueError('Missing binary model scores')
 if not math.isfinite(threshold) or any(not math.isfinite(v) or not 0<=v<=1 for v in scores.values()):raise ValueError('Invalid binary model scores')
 return 'anomalous' if eligible and scores['anomalous']>=threshold else 'not_anomalous'

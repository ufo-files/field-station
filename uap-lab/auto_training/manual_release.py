"""Authorize a requested model without relabeling validation regressions as passes."""
import math

def authorize(report,request_id):
 candidate=report['candidate'];baseline=report['baseline']
 error=candidate.get('export_max_absolute_error')
 if not request_id or error is None or not math.isfinite(error) or error>.025:
  raise ValueError('Manual model failed Core ML export validation')
 if not candidate.get('total') or candidate['total']!=baseline['total']:
  raise ValueError('Manual model lacks comparable evaluation')
 return dict(report,manual_deployment=dict(request_id=request_id,runtime_validated=True,policy='manual-train-publish-activate',note='Manually requested deployment; validation scores and regressions remain unchanged'))

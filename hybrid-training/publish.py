"""Publish shadow artifacts as prereleases; never replace the live/latest release."""
import json,shutil,tarfile,tempfile,time
from pathlib import Path

def publish(root,folder,repository='ufo-files/anomaly-vision-model'):
 from model_publication import GitHub,sha,save
 dataset=json.loads((folder/'dataset.json').read_text());lane=dataset.get('training_lane','hybrid');policy=json.loads((folder/'candidate-policy.json').read_text());version=policy['version'];receipt=root/'publications'/(version+'.json')
 if receipt.exists():return json.loads(receipt.read_text())
 artifact=root/'artifacts'/version;artifact.mkdir(parents=True,exist_ok=True)
 if not (artifact/'model.tar.gz').exists():
  with tempfile.TemporaryDirectory(dir=artifact) as temporary:
   payload=Path(temporary);shutil.copytree(folder/'candidate.mlpackage',payload/'candidate.mlpackage');shutil.copyfile(folder/'candidate-weights.pt',payload/'candidate-weights.pt')
   keys=('version','classes','thresholds','minimum_native_size','input_color_space','decision_rule','preprocessing','night_context_confirmation')
   save(payload/'candidate-policy.json',{k:policy[k] for k in keys if k in policy})
   dataset=json.loads((folder/'dataset.json').read_text());save(payload/'model-card.json',dict(version=version,role=lane+'-shadow-only',live=False,human_training_counts=dataset.get('human_training_counts',{}),pseudo_labels=dataset.get('pseudo_labels',0),human_baseline_version=dataset.get('human_baseline_version'),qualification='Experimental; prospective human-reviewed comparison required before live use. Training images are not included.'))
   with tarfile.open(artifact/'model.tar.gz','w:gz') as tar:
    for p in payload.iterdir():tar.add(p,arcname=p.name)
  (artifact/'SHA256SUMS').write_text(sha(artifact/'model.tar.gz')+'  model.tar.gz\n')
 tag=lane+'-'+version;github=GitHub(repository);release=github.find(tag)
 if release is None:
  notes=artifact/'notes.md';notes.write_text('Experimental '+lane+' model. '+('Training examples are exclusively machine-labeled; the initial teacher was human-curated. ' if lane=='machine_only' else 'Trained on human-reviewed frames plus conservative machine labels. ')+'Shadow use only; does not replace the live human-curated model. No training images are included.\n')
  github.run(['release','create',tag,'--repo',repository,'--draft','--prerelease','--latest=false','--title',lane.replace('_',' ').title()+' shadow model '+version[:12],'--notes-file',str(notes)]);release=github.find(tag)
  if release is None:raise ValueError('Shadow draft not visible yet; retrying')
 names={r['name'] for r in release.get('assets',[])}
 for name in ('model.tar.gz','SHA256SUMS'):
  if name not in names:github.upload(tag,artifact/name)
 with tempfile.TemporaryDirectory(dir=root) as temporary:
  for name in ('model.tar.gz','SHA256SUMS'):
   github.download(tag,name,temporary)
   if sha(Path(temporary)/name)!=sha(artifact/name):raise ValueError('Shadow release checksum mismatch')
 github.run(['release','edit',tag,'--repo',repository,'--draft=false','--prerelease','--latest=false']);release=github.find(tag)
 if release.get('draft') or not release.get('prerelease'):raise ValueError('Shadow prerelease state not verified')
 result=dict(state='published',version=version,url=release['html_url'],verified_epoch=time.time(),sha256=sha(artifact/'model.tar.gz'));save(receipt,result);return result

"""Durable, verified GitHub Releases for successfully deployed native models."""
import sys
import argparse,fcntl,gzip,hashlib,json,os,re,shutil,subprocess,tarfile,tempfile,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'recognition'))
from model_transition import deployment_approved
VERSION=re.compile(r'[a-f0-9]{64}')

def read(path,default=None):
 try:return json.loads(Path(path).read_text())
 except FileNotFoundError:return default

def save(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.tmp')
 with tmp.open('w') as f:json.dump(value,f,indent=2);f.flush();os.fsync(f.fileno())
 tmp.replace(path)

def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()

def enqueue(config,folder,release):
 publication=config.get('model_publication',{})
 if not publication.get('enabled'):return
 folder=Path(folder);policy=read(folder/'candidate-policy.json');report=read(folder/'promotion-evaluation.json');version=release['version']
 if not VERSION.fullmatch(version) or policy['version']!=version or report['candidate_version']!=version or not deployment_approved(report):raise ValueError('Only evaluated deployed models may be published')
 if release.get('previous_version')!=report['baseline_version'] or not release.get('deployed_epoch'):raise ValueError('Missing deployment provenance')
 root=Path(config['root'])/'model-publication';job=root/'outbox'/(version+'.json')
 if job.exists():return read(job)
 value=dict(version=version,folder=str(folder.resolve()),repository=publication['repository'],release=release,state='queued',created_epoch=time.time(),attempts=0,next_attempt=0)
 save(job,value);return value

def summary(report):
 return {k:report[k] for k in ('total','unknown','per_class','thresholds','classes','export_max_absolute_error') if k in report}

def bundle(root,job):
 target=root/'artifacts'/job['version']
 if target.exists():
  manifest=read(target/'assets.json')
  if not manifest or any(sha(target/name)!=digest for name,digest in manifest.items()):raise ValueError('Immutable publication bundle changed')
  return target,manifest
 source=Path(job['folder']);policy=read(source/'candidate-policy.json');report=read(source/'promotion-evaluation.json')
 if policy['version']!=job['version'] or report['candidate_version']!=job['version'] or not deployment_approved(report):raise ValueError('Model identity or evaluation changed before packaging')
 target.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(dir=target.parent) as temporary:
  work=Path(temporary);payload=work/'payload';payload.mkdir();package=source/'candidate.mlpackage'
  if package.is_symlink() or not package.is_dir():raise ValueError('Missing or unsafe Core ML package')
  for p in package.rglob('*'):
   if p.is_symlink():raise ValueError('Symlink inside Core ML package')
  shutil.copytree(package,payload/'candidate.mlpackage')
  weights=source/'candidate-weights.pt'
  if weights.is_symlink() or not weights.is_file():raise ValueError('Missing or unsafe model weights')
  shutil.copyfile(weights,payload/weights.name)
  # Explicit metadata allowlist: no credentials, filesystem paths, or training images.
  keys=('schema_version','version','classes','thresholds','minimum_native_size','preprocessing','role','automatic_promotion','focused_cloud_correction','cloud_corrections','class_corrections','binary_corrections','legacy_classes','legacy_thresholds','base_head_classes','parent_version','score_semantics','deferred_classes')
  save(payload/'candidate-policy.json',{k:policy[k] for k in keys if k in policy})
  save(payload/'evaluation.json',dict(passed=report['passed'],manual_deployment=report.get('manual_deployment'),reasons=report.get('reasons',[]),baseline_version=report['baseline_version'],candidate_version=job['version'],baseline=summary(report['baseline']),candidate=summary(report['candidate']),limitations=report.get('limitations',[]),runtime=report.get('runtime')))
  save(payload/'model-card.json',dict(format='Core ML native crop classifier',version=job['version'],previous_version=report['baseline_version'],deployed_epoch=job['release']['deployed_epoch'],classes=policy['classes'],contents=['candidate.mlpackage','candidate-weights.pt','candidate-policy.json','evaluation.json'],validation=('Manual deployment; validation did not meet automatic promotion rules. ' if report.get('manual_deployment') and not report['passed'] else 'Passed release evaluation. ')+'Passed deployment health checks. Historical regression results are not prospective field accuracy.',training_images_included=False))
  files=sorted(p for p in payload.rglob('*') if p.is_file());(payload/'SHA256SUMS').write_text(''.join(sha(p)+'  '+p.relative_to(payload).as_posix()+'\n' for p in files))
  artifact=work/'model.tar.gz'
  with artifact.open('wb') as raw,gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as compressed,tarfile.open(fileobj=compressed,mode='w') as archive:
   for p in sorted(payload.rglob('*')):
    info=archive.gettarinfo(str(p),p.relative_to(payload).as_posix());info.uid=info.gid=0;info.uname=info.gname='';info.mtime=0
    if p.is_file():
     with p.open('rb') as stream:archive.addfile(info,stream)
    else:archive.addfile(info)
  output=work/'output';output.mkdir();artifact.rename(output/'model.tar.gz');shutil.copyfile(payload/'model-card.json',output/'model-card.json');(output/'SHA256SUMS').write_text(sha(output/'model.tar.gz')+'  model.tar.gz\n'+sha(output/'model-card.json')+'  model-card.json\n')
  manifest={p.name:sha(p) for p in output.iterdir()};save(output/'assets.json',manifest);output.rename(target)
 return target,manifest

class GitHub:
 def __init__(self,repository):
  if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository):raise ValueError('Invalid model repository')
  self.repo=repository
 def run(self,args):
  r=subprocess.run(['gh',*args],capture_output=True,text=True,timeout=600,env=dict(os.environ,GH_PROMPT_DISABLED='1'))
  if r.returncode:raise RuntimeError(re.sub(r'(ghp_|github_pat_)[A-Za-z0-9_]+','[redacted]',r.stderr[-1500:]))
  return r.stdout
 def find(self,tag):
  try:return json.loads(self.run(['api',f'repos/{self.repo}/releases/tags/{tag}']))
  except RuntimeError as exc:
   if 'HTTP 404' not in str(exc):raise
   # GitHub's tag endpoint excludes drafts until their tag is published.
   pages=json.loads(self.run(['api','--paginate','--slurp',f'repos/{self.repo}/releases?per_page=100']))
   return next((r for page in pages for r in page if r['tag_name']==tag),None)
 def create(self,tag,notes):
  self.run(['release','create',tag,'--repo',self.repo,'--draft','--title','Native recognition model '+tag.removeprefix('model-')[:12],'--notes-file',str(notes)])
 def upload(self,tag,path):self.run(['release','upload',tag,str(path),'--repo',self.repo])
 def download(self,tag,name,directory):self.run(['release','download',tag,'--repo',self.repo,'--pattern',name,'--dir',str(directory)])
 def publish(self,tag):self.run(['release','edit',tag,'--repo',self.repo,'--draft=false'])

def publish(root,job,github):
 folder,assets=bundle(root,job);tag='model-'+job['version'];release=github.find(tag)
 if release is None:
  notes=folder/'release-notes.txt';notes.write_text('Successfully deployed native recognition model.\n\nDownload model.tar.gz for the Core ML package, model weights, policy, evaluation summary, and internal file checksums. Verify the archive using SHA256SUMS. Training images and station credentials are not included.\n\nModel version: '+job['version']+'\n')
  github.create(tag,notes);release=github.find(tag)
  if release is None:raise ValueError('Created draft is not yet visible; retrying lookup')
 names={a['name'] for a in release.get('assets',[])}
 for name in assets:
  if name not in names:github.upload(tag,folder/name)
 # Verify actual GitHub downloads, including assets left by an interrupted attempt.
 with tempfile.TemporaryDirectory(dir=root) as temporary:
  for name,digest in assets.items():
   github.download(tag,name,temporary)
   if sha(Path(temporary)/name)!=digest:raise ValueError('GitHub asset checksum mismatch: '+name)
 if release.get('draft'):github.publish(tag)
 final=github.find(tag)
 if final.get('draft'):raise ValueError('Release remains a draft')
 job.update(state='published',published_epoch=time.time(),url=final['html_url'],assets=assets,error=None,next_attempt=0)
 save(root/'receipts'/(job['version']+'.json'),job)
 return job

def tick(config,github_factory=GitHub):
 if not config.get('model_publication',{}).get('enabled'):return
 root=Path(config['root'])/'model-publication';root.mkdir(parents=True,exist_ok=True)
 with (root/'worker.lock').open('a') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:return
  jobs=sorted((root/'outbox').glob('*.json'),key=lambda p:read(p)['created_epoch'])
  for path in jobs:
   job=read(path)
   if job['state']=='published' or job.get('next_attempt',0)>time.time():continue
   try:job=publish(root,job,github_factory(job['repository']))
   except Exception as exc:
    attempts=job.get('attempts',0)+1;job.update(state='retrying',attempts=attempts,error=str(exc),next_attempt=time.time()+min(3600,30*2**min(attempts-1,7)))
   save(path,job);save(root/'status.json',dict(version=job['version'],state=job['state'],error=job.get('error'),url=job.get('url'),updated_epoch=time.time(),next_attempt=job.get('next_attempt')))
   return job

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--config',required=True);a=p.parse_args();result=tick(read(a.config));print(json.dumps(result))

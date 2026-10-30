"""Publish saved model snapshots to GitHub outside the request/recording threads."""
import hashlib,json,os,re,shutil,subprocess,threading,time,uuid
from pathlib import Path
import lab
import export_public_model

class ModelPublisher:
    def __init__(self,start_worker=True):
        self.root=lab.DATA/'publication';self.root.mkdir(exist_ok=True);self.checkout=self.root/'checkout';self.stop_event=threading.Event()
        if start_worker:threading.Thread(target=self.work,daemon=True).start()
    def status(self):
        config=lab.read(self.root/'config.json',{});state=lab.read(self.root/'status.json',dict(phase='idle'))
        state['enabled']=bool(config.get('enabled'));state['repository']=config.get('repository');state['pending']=sum(lab.read(p,{}).get('state')!='published' for p in (self.root/'outbox').glob('*.json'))
        return state
    def command(self,args,timeout=180):
        result=subprocess.run(args,cwd=self.checkout if self.checkout.exists() else self.root,env=dict(os.environ,GIT_TERMINAL_PROMPT='0',OPENBLAS_NUM_THREADS='1'),capture_output=True,text=True,timeout=timeout)
        if result.returncode:
            message=result.stderr[-1500:] or result.stdout[-1500:]
            message=re.sub(r'(?:ghp_|github_pat_|hf_)[A-Za-z0-9_]+','[redacted]',message)
            raise RuntimeError(message.strip())
        return result.stdout.strip()
    def prepare(self,repository):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository):raise ValueError('Invalid publication repository')
        if not (self.checkout/'.git/HEAD').is_file():
            if self.checkout.exists():self.checkout.rename(self.root/('incomplete-checkout-'+str(time.time_ns())))
            for old in self.root.glob('.clone-*'):
                if old.is_dir():shutil.rmtree(old)
            staging=self.root/('.clone-'+uuid.uuid4().hex)
            try:
                self.command(['git','clone','--depth','1','https://github.com/'+repository+'.git',str(staging)])
                staging.replace(self.checkout)
            except Exception:
                if staging.exists():shutil.rmtree(staging)
                raise
        self.command(['git','config','user.name',repository.split('/')[0]])
        self.command(['git','config','user.email',repository.split('/')[0]+'@users.noreply.github.com'])
    def publish(self,request,path,config):
        model_id=lab.checked_id(request['model_id']);repo=config['repository'];tag='model-'+model_id;url='https://github.com/'+repo+'/tree/'+tag
        def update(phase,**details):lab.save(self.root/'status.json',dict(phase=phase,model_id=model_id,updated=time.time(),**details))
        if os.environ.get('UAP_LAB_WORKER_CONFIG'):
            from remote_evaluation import publish_model
            update('uploading')
            publish_model(model_id)
            request.update(state='published',published_at=time.time(),url=url);lab.save(path,request)
            update('published',url=url,worker='mac-mini');return
        update('preparing');self.prepare(repo)
        if not request.get('commit'):
            self.command(['git','pull','--ff-only','origin','main'])
            # The exporter reads only the exact saved model's native templates.
            export_public_model.DATA=lab.DATA
            export_public_model.build_saved(model_id,self.checkout)
            self.command([__import__('sys').executable,'-m','unittest','-q','test_inference'],timeout=120)
            (self.checkout/'verification.json').write_text(json.dumps(dict(source_model_id=model_id,software_tests='Portable inference tests passed before upload',python=__import__('platform').python_version(),opencv=lab.cv2.__version__,numpy=lab.np.__version__,independent_accuracy_evaluation=None),indent=2)+'\n')
            files=[p for p in self.checkout.rglob('*') if p.is_file() and '.git' not in p.relative_to(self.checkout).parts and '__pycache__' not in p.parts and p.name!='SHA256SUMS']
            for p in files:
                if p.suffix in ('.json','.md','.py'):
                    text=p.read_text()
                    if any(marker in text for marker in ('/home/hackrf','BEGIN OPENSSH PRIVATE KEY','github_pat_','192.168.8.208','100.117.92.45')):raise ValueError('Local-only data found in public artifact: '+p.name)
            (self.checkout/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(self.checkout).as_posix()+'\n' for p in sorted(files)))
            self.command(['git','add','.'])
            changed=self.command(['git','diff','--cached','--name-only'])
            if changed:self.command(['git','commit','-m','Publish saved observation model '+model_id])
            request['commit']=self.command(['git','rev-parse','HEAD']);lab.save(path,request)
        update('uploading');self.command(['git','push','origin',request['commit']+':refs/heads/main'])
        existing=self.command(['git','tag','--list',tag])
        if not existing:self.command(['git','tag',tag,request['commit']])
        self.command(['git','push','origin','refs/tags/'+tag])
        request.update(state='published',published_at=time.time(),url=url);lab.save(path,request)
        receipts=self.root/'receipts';receipts.mkdir(exist_ok=True);lab.save(receipts/(model_id+'.json'),request)
        update('published',url=url,commit=request['commit'])
    def tick(self):
        config=lab.read(self.root/'config.json',{})
        if not config.get('enabled'):return
        active=lab.read(lab.DATA/'active-model.json')
        if active:lab.queue_model_publication(active)
        jobs=[(p,lab.read(p,{})) for p in (self.root/'outbox').glob('*.json')];jobs.sort(key=lambda item:item[1].get('created',0))
        for path,request in jobs:
            if request.get('state')=='published':continue
            if request.get('retry_at',0)>time.time():return
            try:self.publish(request,path,config)
            except Exception as exc:
                attempts=request.get('attempts',0)+1;request.update(state='failed',attempts=attempts,error=str(exc),retry_at=time.time()+min(1800,60*2**min(attempts-1,5)));lab.save(path,request)
                lab.save(self.root/'status.json',dict(phase='failed',model_id=request.get('model_id'),error=str(exc),updated=time.time(),retry_at=request['retry_at']))
            return
    def work(self):
        while not self.stop_event.is_set():
            try:self.tick()
            except Exception as exc:lab.save(self.root/'status.json',dict(phase='failed',error=str(exc),updated=time.time()))
            self.stop_event.wait(2)

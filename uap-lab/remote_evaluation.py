"""Transfer a frozen input once, poll durable progress, and retrieve event artifacts."""
import hashlib,json,os,shlex,subprocess,tarfile,time
from pathlib import Path
import lab

def evaluate(rid,vid,model,threshold,labels):
    config=lab.read(Path(os.environ['UAP_LAB_WORKER_CONFIG']));folder=lab.DATA/'runs'/rid
    ssh=['/usr/bin/ssh','-T','-o','BatchMode=yes','-o','ConnectTimeout=10','-o','ServerAliveInterval=15','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+config['known_hosts'],'-i',config['identity'],config['username']+'@'+config['host']]
    run=dict(id=rid,video_id=vid,model_id=model['id'],threshold=threshold,labels=labels,created=lab.read(folder/'run.json',{}).get('created',time.time()),state='uploading',progress=0,detached=True,worker='mac-mini')
    def update(**values):run.update(values);lab.save(folder/'run.json',run)
    def rpc(request,timeout=30):
        p=subprocess.run(ssh,input=(json.dumps(request)+'\n').encode(),capture_output=True,timeout=timeout)
        if p.returncode:raise ValueError(p.stderr.decode(errors='replace')[-1500:])
        return json.loads(p.stdout)
    try:
        while True:
            try:rpc(dict(action='ping'));break
            except (OSError,subprocess.TimeoutExpired,ValueError) as exc:
                update(state='waiting_worker',message='Waiting for the Mac mini; field capture remains available.',connection_error=str(exc));time.sleep(5)
        existing=rpc(dict(action='status',id=rid))
        if existing.get('state')=='missing':
            update(state='uploading',message='Sending frozen video and model to the Mac mini.')
            source=lab.video_path(vid)/'source';digest=hashlib.sha256()
            with source.open('rb') as stream:
                for data in iter(lambda:stream.read(1024**2),b''):digest.update(data)
            with (folder/'worker-ssh.log').open('ab') as log:
                p=subprocess.Popen(ssh,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log)
                p.stdin.write((json.dumps(dict(action='submit',id=rid,run=run,bytes=source.stat().st_size,source_sha256=digest.hexdigest()))+'\n').encode())
                try:
                    with tarfile.open(fileobj=p.stdin,mode='w|gz',dereference=True) as out:
                        out.add(source,arcname=f'videos/{vid}/source')
                        out.add(lab.video_path(vid)/'video.json',arcname=f'videos/{vid}/video.json')
                        for item in (lab.DATA/'models'/model['id']).rglob('*'):
                            if item.is_file():out.add(item,arcname='models/'+model['id']+'/'+str(item.relative_to(lab.DATA/'models'/model['id'])))
                    p.stdin.close();reply=p.stdout.read();code=p.wait()
                    if code:raise ValueError('Mac mini rejected the input; see worker-ssh.log')
                    if not json.loads(reply).get('accepted'):raise ValueError('Worker did not accept the job')
                except BaseException:
                    p.terminate();p.wait();raise
        while True:
            try:status=rpc(dict(action='status',id=rid));run.update(status);lab.save(folder/'run.json',run)
            except (OSError,subprocess.TimeoutExpired,ValueError) as exc:
                update(message='Waiting for the Mac mini to reconnect; its job continues.',connection_error=str(exc));time.sleep(5);continue
            if status['state']=='failed':return
            if status['state']=='complete':break
            time.sleep(2)
        update(state='receiving',message='Downloading videos and target frames; native source frames remain on the Mac mini.')
        with (folder/'worker-ssh.log').open('ab') as log:
            p=subprocess.Popen(ssh,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log)
            p.stdin.write((json.dumps(dict(action='results',id=rid))+'\n').encode());p.stdin.close()
            with tarfile.open(fileobj=p.stdout,mode='r|gz') as inp:
                for member in inp:
                    rel=Path(member.name)
                    if rel.is_absolute() or '..' in rel.parts or not (member.isfile() or member.isdir()):raise ValueError('Invalid result path')
                    dest=folder/rel
                    if member.isdir():dest.mkdir(parents=True,exist_ok=True);continue
                    if member.name=='run.json':continue
                    dest.parent.mkdir(parents=True,exist_ok=True)
                    with inp.extractfile(member) as src,dest.open('wb') as dst:lab.shutil.copyfileobj(src,dst)
            if p.wait():raise ValueError('Result transfer interrupted')
        update(state='complete',message='Complete. Processed on the Mac mini; event videos and frames are available locally.')
    except Exception as exc:update(state='waiting_retry',error=str(exc),retry_after_epoch=time.time()+30,message='Transfer interrupted; original input and partial results retained for retry.')

def publish_model(model_id):
    config=lab.read(Path(os.environ['UAP_LAB_WORKER_CONFIG']));model=lab.read(lab.DATA/'models'/model_id/'model.json')
    ssh=['/usr/bin/ssh','-T','-o','BatchMode=yes','-o','ConnectTimeout=10','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+config['known_hosts'],'-i',config['identity'],config['username']+'@'+config['host']]
    vids=sorted({e['video_id'] for e in model['examples'] if e.get('video_id')})
    p=subprocess.Popen(ssh,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        p.stdin.write((json.dumps(dict(action='publish',id=model_id,video_ids=vids,bytes=0))+'\n').encode())
        with tarfile.open(fileobj=p.stdin,mode='w|gz',dereference=True) as out:
            for source in (lab.DATA/'models'/model_id).rglob('*'):
                if source.is_file():out.add(source,arcname='models/'+model_id+'/'+str(source.relative_to(lab.DATA/'models'/model_id)))
            for vid in vids:
                for name in ['video.json','annotations.json']:
                    source=lab.DATA/'videos'/vid/name
                    if source.is_file():out.add(source,arcname=f'videos/{vid}/{name}')
        p.stdin.close();reply=p.stdout.read();error=p.stderr.read();code=p.wait()
        if code or not json.loads(reply).get('accepted'):raise ValueError('Mac mini model transfer failed: '+error.decode(errors='replace')[-500:])
    except BaseException:
        p.terminate();p.wait();raise
    while True:
        p=subprocess.run(ssh,input=(json.dumps(dict(action='publication_status',id=model_id))+'\n').encode(),capture_output=True,timeout=30)
        if p.returncode:raise ValueError('Mac mini publication status unavailable')
        status=json.loads(p.stdout)
        if status['state']=='published':return status
        if status['state']=='failed':raise ValueError(status.get('error','Mac mini publication failed'))
        time.sleep(5)

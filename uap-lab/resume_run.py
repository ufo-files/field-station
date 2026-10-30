"""Run a saved video test independently of web/live-view restarts."""
import sys,shutil,time
import lab
rid=lab.checked_id(sys.argv[1]);folder=lab.DATA/'runs'/rid;run=lab.read(folder/'run.json')
if not run:raise SystemExit('Saved run not found')
if run.get('state')=='complete':raise SystemExit(0)
model=lab.read(folder/'model.json')
if not model:raise SystemExit('Frozen model snapshot not found')
run.update(detached=True,state='queued');lab.save(folder/'run.json',run)
old=folder/'detections.jsonl'
if old.exists() and old.stat().st_size:old.replace(folder/('detections-before-cloudfix-'+str(time.time_ns())+'.jsonl'))
previous=[p for p in folder.glob('event-*') if p.is_dir()]
if previous:
    archive=folder/('exports-before-restart-'+str(time.time_ns()));archive.mkdir()
    for p in previous:p.rename(archive/p.name)
lab.evaluate(rid,run['video_id'],model,run.get('threshold',.97),run.get('labels',['anomalous']),resume=True)
if lab.read(folder/'run.json',{}).get('state')!='complete':raise SystemExit(1)

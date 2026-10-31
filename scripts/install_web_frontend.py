"""Install the persistent local front end on the existing macOS station."""
import argparse,json,os,plistlib,shutil,socket,subprocess,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--app',type=Path,required=True);args=p.parse_args();app=args.app.resolve()
domain='gui/'+str(os.getuid());agents=Path.home()/'Library/LaunchAgents';label='com.ufo-files.field.web';lab=domain+'/com.ufo-files.field.lab'
def run(*cmd):return subprocess.run(cmd,check=True,capture_output=True)
def active(job):return subprocess.run(['launchctl','print',job],capture_output=True).returncode==0
def port_open(port):
 try:
  with socket.create_connection(('127.0.0.1',port),timeout=1):return True
 except OSError:return False
if active(domain+'/'+label):raise SystemExit('Web front end is already installed')
if port_open(8092):raise SystemExit('Port 8092 is already occupied; configuration unchanged')
envpath=app/'environment.json';previous=envpath.read_bytes();env=json.loads(previous)
backup=app/'maintenance/web-frontend'/str(int(time.time()));backup.mkdir(parents=True);(backup/'environment.json').write_bytes(previous)
(app/'run').mkdir(exist_ok=True)
plist=agents/(label+'.plist')
config=dict(Label=label,ProgramArguments=[str(app/'venv/bin/python'),str(app/'uap-lab/web_frontend.py')],RunAtLoad=True,KeepAlive=True,ThrottleInterval=3,WorkingDirectory=str(app/'uap-lab'),StandardOutPath=str(app/'logs/web.log'),StandardErrorPath=str(app/'logs/web.err'))
was_running=active(lab)
try:
 env['UAP_LAB_PORT']='8092';temp=envpath.with_suffix('.web-tmp');temp.write_text(json.dumps(env,indent=2));temp.replace(envpath)
 if was_running:run('launchctl','bootout',lab)
 for _ in range(100):
  if not port_open(8091):break
  time.sleep(.1)
 else:raise RuntimeError('Original web port did not close')
 plist.write_bytes(plistlib.dumps(config));run('launchctl','bootstrap',domain,str(plist))
 for _ in range(100):
  if port_open(8091):break
  time.sleep(.1)
 else:raise RuntimeError('Persistent web front end did not start')
 if was_running:run('launchctl','bootstrap',domain,str(agents/'com.ufo-files.field.lab.plist'))
 print('Persistent web front end listening on 8091; lab uses 8092. Configuration backup:',backup)
except BaseException:
 if active(domain+'/'+label):subprocess.run(['launchctl','bootout',domain+'/'+label],capture_output=True)
 envpath.write_bytes(previous)
 if was_running and not active(lab):subprocess.run(['launchctl','bootstrap',domain,str(agents/'com.ufo-files.field.lab.plist')],capture_output=True)
 raise

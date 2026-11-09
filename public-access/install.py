import os,pathlib,plistlib,subprocess,time
home=pathlib.Path.home();code=pathlib.Path(__file__).parent
agents=home/'Library/LaunchAgents';domain=f'gui/{os.getuid()}';logs=home/'Library/Logs/field-station'
# Retire the rejected exporter completely, including automatic login startup.
label='app.ufo-files.field.public-export'
subprocess.run(['launchctl','bootout',domain+'/'+label],capture_output=True)
old=agents/(label+'.plist')
if old.exists():
 backup=home/'Library/Application Support/ufo-field-onion/retired';backup.mkdir(parents=True,exist_ok=True);old.replace(backup/old.name)
label='app.ufo-files.field.public-web';path=agents/(label+'.plist')
args=[str(home/'ufo-field/venv/bin/python'),str(code/'readonly.py')]
path.write_bytes(plistlib.dumps(dict(Label=label,ProgramArguments=args,RunAtLoad=True,KeepAlive=True,ThrottleInterval=30,WorkingDirectory=str(home),EnvironmentVariables=dict(PYTHONUNBUFFERED='1'),StandardOutPath=str(logs/'public-web.log'),StandardErrorPath=str(logs/'public-web.error.log'))))
subprocess.run(['launchctl','bootout',domain+'/'+label],capture_output=True)
for name in ('public-web','public-tor'):
 label='app.ufo-files.field.'+name
 loaded=subprocess.run(['launchctl','print',domain+'/'+label],capture_output=True).returncode==0
 if loaded:continue
 for attempt in range(8):
  result=subprocess.run(['launchctl','bootstrap',domain,str(agents/(label+'.plist'))],capture_output=True)
  if not result.returncode:break
  time.sleep(1)
 else:raise RuntimeError('Could not start '+label)
 print('Started',label)

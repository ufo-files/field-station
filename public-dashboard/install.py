#!/usr/bin/env python3
"""Install the independent public observer and Tor launch agents on UFO Field."""
import os, pathlib, plistlib, subprocess, time
root=pathlib.Path('/Volumes/UFO-Field')
UUID='E4920328-C7F6-4DD1-AAAB-CCE821F8CF78'
info=plistlib.loads(subprocess.check_output(['/usr/sbin/diskutil','info','-plist',str(root)]))
assert info.get('VolumeUUID','').upper()==UUID, 'Expected field SSD is missing'
code=root/'station-runtime/public-dashboard'
assert (code/'dashboard.py').is_file()
home=pathlib.Path.home(); support=home/'Library/Application Support/ufo-field-onion'
support.mkdir(parents=True,exist_ok=True);support.chmod(0o700)
logs=home/'Library/Logs/field-station';logs.mkdir(parents=True,exist_ok=True)
torrc=support/'torrc'
previous_torrc=torrc.read_text() if torrc.exists() else None
torrc.write_text(f'''DataDirectory "{support}/tor-data"
SocksPort 127.0.0.1:19050
ControlPort 0
ClientOnly 1
HiddenServiceDir "{support}/onion"
HiddenServiceVersion 3
HiddenServicePort 80 127.0.0.1:8093
HiddenServiceMaxStreams 12
HiddenServiceMaxStreamsCloseCircuit 1
UseBridges 1
ClientTransportPlugin snowflake exec /opt/homebrew/bin/snowflake-client
Bridge snowflake 192.0.2.3:80 2B280B23E1107BB62ABFC40DDCC8824814F80A72 fingerprint=2B280B23E1107BB62ABFC40DDCC8824814F80A72 url=https://1098762253.rsc.cdn77.org front=www.phpmyadmin.net,cdn.zk.mk ice=stun:stun.antisip.com:3478,stun:stun.epygi.com:3478,stun:stun.uls.co.za:3478,stun:stun.voipgate.com:3478,stun:stun.mixvoip.com:3478,stun:stun.nextcloud.com:3478,stun:stun.bethesda.net:3478,stun:stun.nextcloud.com:443 utls-imitate=hellorandomizedalpn
Log notice stdout
''')
torrc.chmod(0o600)
subprocess.run(['/opt/homebrew/bin/tor','--verify-config','-f',str(torrc)],check=True)
python=str(home/'ufo-field/venv/bin/python')
common=['--root',str(root),'--output',str(root/'public-dashboard'),'--volume-uuid',UUID]
services={
 'public-export':[python,str(code/'dashboard.py'),'export',*common],
 'public-web':[python,str(code/'dashboard.py'),'serve',*common],
 'public-tor':['/opt/homebrew/bin/tor','-f',str(torrc)]}
domain=f'gui/{os.getuid()}'
for name,command in services.items():
 label='app.ufo-files.field.'+name
 plist=home/'Library/LaunchAgents'/f'{label}.plist'
 data=dict(Label=label,ProgramArguments=command,RunAtLoad=True,KeepAlive=True,ThrottleInterval=30,WorkingDirectory=str(home),EnvironmentVariables=dict(PYTHONUNBUFFERED='1',PATH='/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin'),StandardOutPath=str(logs/(name+'.log')),StandardErrorPath=str(logs/(name+'.error.log')))
 plist.write_bytes(plistlib.dumps(data))
 loaded=subprocess.run(['launchctl','print',domain+'/'+label],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0
 if loaded and name=='public-tor' and previous_torrc==torrc.read_text():
  print('Already configured',label);continue
 if loaded:
  subprocess.run(['launchctl','kickstart','-k',domain+'/'+label],check=True)
 else:
  for attempt in range(5):
   result=subprocess.run(['launchctl','bootstrap',domain,str(plist)],capture_output=True)
   if result.returncode==0:break
   time.sleep(2)
  else:raise RuntimeError('Could not start '+label)

 print('Started',label)
print('Onion hostname will appear at',support/'onion/hostname')

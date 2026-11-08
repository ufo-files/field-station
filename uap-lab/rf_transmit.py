"""Supervised, one-shot HackRF TX with independent watchdog and RX restoration."""
import atexit,fcntl,hashlib,hmac,json,math,os,re,secrets,shutil,signal,subprocess,sys,threading,time
from pathlib import Path
from rf_waveform import plan,write_iq,FREQUENCY,RATE,OFFSET,MAX_SECONDS

RADIOS={'0000000000000000930c64dc29427ec3':'rf','0000000000000000930c64dc29283bc3':'rf-wide'}
CLASSES=('technician','general','extra')
DEFAULTS=dict(callsign='',license_class='technician',tx_serial=next(iter(RADIOS)),measured_dbm=None,hardware_notes='',hardware_verified=False,authorization_confirmed=False,shielding_verified=False)
LIMITS=dict(frequency_hz=FREQUENCY,encoding='International Morse / CW, 20 WPM',max_seconds=30,cooldown_seconds=60,gain_db=0,rf_amplifier=False,bias_tee=False,max_conducted_dbm=0)

def read(path,default=None):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return default

def atomic(path,value):
    temp=path.with_name(path.name+'.'+secrets.token_hex(6)+'.tmp')
    try:
        with temp.open('x') as out:
            os.chmod(temp,0o600);json.dump(value,out,allow_nan=False);out.flush();os.fsync(out.fileno())
        temp.replace(path)
    finally:temp.unlink(missing_ok=True)

def password_hash(password,salt):
    return hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),200000).hex()

def verify_password(config,password):
    if not isinstance(password,str) or len(password)>256:return False
    return hmac.compare_digest(config.get('password_hash',''),password_hash(password,config['salt']))

def validate_config(value):
    if not isinstance(value,dict):raise ValueError('Expected operator settings.')
    allowed=set(DEFAULTS)|{'password','current_password'}
    if set(value)-allowed:raise ValueError('Unknown operator setting. Frequency and hardware gain are preset.')
    result={k:value.get(k,v) for k,v in DEFAULTS.items()}
    call=result['callsign']
    if not isinstance(call,str):raise ValueError('Enter the station callsign.')
    call=call.strip().upper()
    if not re.fullmatch(r'(?:[KNW][A-Z]?|A[A-L])[0-9][A-Z]{1,3}',call):raise ValueError('Enter a US station callsign, without portable suffix or SSID.')
    result['callsign']=call
    if result['license_class'] not in CLASSES:raise ValueError('Select the operator’s license class.')
    if result['tx_serial'] not in RADIOS:raise ValueError('Choose one of the station’s two radios.')
    power=result['measured_dbm']
    if isinstance(power,bool) or not isinstance(power,(float,int)) or not math.isfinite(power) or not -100<=power<=0:raise ValueError('Enter measured conducted output power, at or below 0 dBm, for this preset.')
    notes=result['hardware_notes']
    if not isinstance(notes,str) or not 10<=len(notes.strip())<=2000:raise ValueError('Describe the antenna/load, filtering, attenuation, and power measurement (10–2,000 characters).')
    for key in ('hardware_verified','authorization_confirmed','shielding_verified'):
        if not isinstance(result[key],bool):raise ValueError('Invalid setup confirmation.')
    if not result['hardware_verified'] or not result['authorization_confirmed']:raise ValueError('Operator authorization and RF-chain verification are required.')
    result.update(frequency_hz=FREQUENCY,limits=LIMITS,updated_epoch=time.time(),operator_acknowledgment_version='rf-2026-11-08')
    return result

class Controller:
    def __init__(self,root,project=None):
        self.root=Path(root);self.project=Path(project or Path(__file__).resolve().parent.parent)
        self.lock=threading.RLock();self.lease=None;self.worker=None;self.last_stop=None
    def directory(self):
        resolved=self.root.resolve()
        if len(resolved.parts)<3 or resolved.parts[1]!='Volumes' or not Path(*resolved.parts[:3]).is_mount():raise ValueError('Verified external storage is unavailable.')
        path=self.root/'rf-transmit';path.mkdir(exist_ok=True);return path
    def config(self):return read(self.directory()/'operator.json',{})
    def current(self):return read(self.directory()/'state.json',{})
    def _valid_lease(self,token=None):
        return self.lease is not None and time.monotonic()<self.lease['expires'] and time.monotonic()-self.lease['heartbeat']<6 and (token is None or hmac.compare_digest(str(token),self.lease['token']))
    def status(self):
        with self.lock:
            cfg=self.config();state=self.current();active=self.worker is not None and self.worker.poll() is None
            try:
                with (self.directory()/'hardware.lock').open('a') as guard:
                    try:fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    except BlockingIOError:active=True
            except OSError:pass
            if self.lease and self.lease['used'] and not active:self._disarm()
            armed=self._valid_lease()
            if self.lease and not armed:self._disarm()
            last=read(self.directory()/'last-attempt.json',{}).get('epoch',0)
            return dict(configured=bool(cfg),setup={k:cfg.get(k,v) for k,v in DEFAULTS.items()},limits=LIMITS,radios=[dict(serial=k,role=v) for k,v in RADIOS.items()],armed=armed,busy=active,state=state,cooldown_seconds=max(0,math.ceil(last+60-time.time())),transmit_enabled=armed and not active,reason='Armed for one transmission' if armed else 'Disarmed' if cfg else 'Complete Operator setup below')
    def save(self,value):
        with self.lock:
            if self.status()['busy']:raise ValueError('Stop the active transmission before changing setup.')
            old=self.config()
            if old and not verify_password(old,value.get('current_password')):raise ValueError('Enter the current operator passphrase to change setup.')
            cfg=validate_config(value)
            password=value.get('password')
            if old and not password:cfg.update(salt=old['salt'],password_hash=old['password_hash'])
            else:
                if not isinstance(password,str) or not 12<=len(password)<=256:raise ValueError('Set an operator passphrase of 12–256 characters.')
                salt=secrets.token_hex(16);cfg.update(salt=salt,password_hash=password_hash(password,salt))
            self._disarm();atomic(self.directory()/'operator.json',cfg)
            with (self.directory()/'events.jsonl').open('a') as audit:audit.write(json.dumps(dict(event='operator-setup',callsign=cfg['callsign'],license_class=cfg['license_class'],tx_serial=cfg['tx_serial'],acknowledgment=cfg['operator_acknowledgment_version'],epoch=time.time()))+'\n')
            return self.status()
    def _disarm(self):
        self.lease=None
        atomic(self.directory()/'lease.json',dict(armed=False,updated_epoch=time.time()))
    def disarm(self):
        with self.lock:self._disarm();return self.status()
    def arm(self,value):
        with self.lock:
            status=self.status();cfg=self.config()
            if not cfg:raise ValueError('Complete Operator setup first.')
            if status['busy']:raise ValueError('Wait for the current transmission to finish.')
            if status['cooldown_seconds']:raise ValueError('Wait for the transmit cooldown.')
            if value.get('operator_present') is not True or value.get('channel_clear') is not True:raise ValueError('The designated control operator must supervise this session.')
            if not verify_password(cfg,value.get('password')):raise ValueError('Operator passphrase is incorrect.')
            profile=value.get('profile')
            if profile=='shielded':
                if not cfg.get('shielding_verified'):raise ValueError('Verify and save the shielded test arrangement first.')
            elif profile!='ham-'+cfg['license_class']:raise ValueError('Select the saved operator’s ham profile. Simulation and experimental grants cannot arm this transmitter.')
            token=secrets.token_urlsafe(32)
            self.lease=dict(token=token,profile=profile,expires=time.monotonic()+60,heartbeat=time.monotonic(),used=False)
            atomic(self.directory()/'lease.json',dict(armed=True,token=token,updated_epoch=time.time()))
            return dict(self.status(),arm_token=token)
    def heartbeat(self,value):
        with self.lock:
            if not self._valid_lease(value.get('arm_token')):raise ValueError('Transmit session expired. Disarm and arm again.')
            self.lease['heartbeat']=time.monotonic()
            atomic(self.directory()/'lease.json',dict(armed=True,token=self.lease['token'],updated_epoch=time.time()))
            return dict(armed=True)
    def preview(self,value):
        cfg=self.config();call=cfg.get('callsign','N0CALL')
        p=plan(value.get('message'),call)
        return {k:v for k,v in p.items() if k!='spans'}|dict(transmitted=False,identification_placeholder=not bool(cfg))
    def send(self,value):
        with self.lock:
            if not self._valid_lease(value.get('arm_token')) or self.lease['used']:raise ValueError('Arm a supervised session before transmitting. Each arm permits one burst.')
            if self.status()['busy']:raise ValueError('A transmission is already active.')
            if set(value)-{'message','arm_token'}:raise ValueError('Hardware settings cannot be overridden by a transmit request.')
            cfg=self.config();p=plan(value.get('message'),cfg['callsign'])
            if shutil.disk_usage(self.directory()).free<p['bytes']+1024*1024:raise ValueError('Insufficient external storage for the temporary waveform.')
            self.lease['used']=True
            job=secrets.token_hex(12);path=self.directory()/(job+'.json')
            public_cfg={k:v for k,v in cfg.items() if k not in ('salt','password_hash')}
            atomic(path,dict(id=job,message=value['message'],config=public_cfg,profile=self.lease['profile'],token=self.lease['token'],requested_epoch=time.time()))
            atomic(self.directory()/'last-attempt.json',dict(epoch=time.time()))
            atomic(self.directory()/'state.json',dict(id=job,phase='preparing',message='Preparing transmission',requested_epoch=time.time()))
            with (self.directory()/(job+'.log')).open('ab') as log:
                self.worker=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--worker',str(path),str(self.project)],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
            return dict(accepted=True,id=job,seconds=p['seconds'])

_controller=None
_controller_lock=threading.Lock()
def controller(root):
    global _controller
    with _controller_lock:
        if _controller is None:
            _controller=Controller(root);_controller.disarm();atexit.register(_controller.disarm)
        return _controller

def transfer_command(config,iq,p):
    # No repeat flag, no amp, no bias tee, minimum TX gain; finite sample count.
    return ['/opt/homebrew/bin/hackrf_transfer','-d',config['tx_serial'],'-t',str(iq),'-f',str(FREQUENCY-OFFSET),'-s',str(RATE),'-b','1750000','-x','0','-a','0','-p','0','-n',str(p['samples'])]

def run_worker(job_path,project):
    folder=job_path.parent;job=read(job_path);cfg=job['config'];iq=folder/(job['id']+'.cs8');proc=None;detached=False;stopping=False
    role=RADIOS[cfg['tx_serial']];label='app.ufo-files.field.'+role;domain='gui/'+str(os.getuid());agent=Path.home()/'Library/LaunchAgents'/(label+'.plist')
    state=dict(id=job['id'],phase='preparing',frequency_hz=FREQUENCY,serial=cfg['tx_serial'],profile=job['profile'],callsign=cfg['callsign'],requested_epoch=job['requested_epoch'],transmitted=False)
    def update(**changes):state.update(changes);atomic(folder/'state.json',state)
    def interrupted():
        lease=read(folder/'lease.json',{})
        return stopping or not lease.get('armed') or lease.get('token')!=job['token'] or time.time()-lease.get('updated_epoch',0)>6 or time.time()-job['requested_epoch']>60
    def stop(*args):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    with (folder/'hardware.lock').open('a') as guard:
        try:fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:update(phase='failed',error='RF hardware is already in use');return
        try:
            p=plan(job['message'],cfg['callsign']);update(seconds=p['seconds'],encoded_text=p['text'],declared_measured_dbm=cfg['measured_dbm'])
            write_iq(iq,p,interrupted)
            if interrupted():raise ValueError('Disarmed before transmission.')
            # Refuse arbitrary/stale service mappings; preserve the other RX process.
            services=read(project/'services.json',{});args=services.get(role,[])
            if '--serial' not in args or args[args.index('--serial')+1]!=cfg['tx_serial']:raise ValueError('Receiver device assignment changed; operator setup must be reviewed.')
            subprocess.run(['launchctl','print',domain+'/'+label],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5)
            # Mark before bootout: even a timed-out removal must attempt restoration.
            detached=True
            subprocess.run(['launchctl','bootout',domain+'/'+label],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)
            if interrupted():raise ValueError('Disarmed while releasing receiver.')
            update(phase='transmitting',message='Transmitting; reception is not yet verified',started_epoch=time.time(),rf_attempted=True)
            proc=subprocess.Popen(transfer_command(cfg,iq,p),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            deadline=time.monotonic()+p['seconds']+3
            while proc.poll() is None:
                if interrupted() or time.monotonic()>deadline:
                    proc.terminate()
                    try:proc.wait(timeout=1)
                    except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=1)
                    raise ValueError('Transmission stopped by disarm, lost operator connection, or timeout.')
                time.sleep(.1)
            stderr=proc.stderr.read(16384).decode(errors='replace')
            if proc.returncode:raise ValueError('HackRF transfer failed: '+stderr[-800:])
            update(phase='completed',transmitted=True,message='Transmit process completed; reception not verified',finished_epoch=time.time())
        except Exception as error:update(phase='failed',error=str(error),finished_epoch=time.time())
        finally:
            if proc and proc.poll() is None:proc.kill();proc.wait(timeout=2)
            iq.unlink(missing_ok=True)
            if detached:
                try:
                    check=subprocess.run(['launchctl','print',domain+'/'+label],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5)
                    if check.returncode:subprocess.run(['launchctl','bootstrap',domain,str(agent)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
                    update(receiver_restored=True)
                except Exception as error:update(receiver_restored=False,restore_error=str(error))
            atomic(folder/'lease.json',dict(armed=False,updated_epoch=time.time()))
            with (folder/'events.jsonl').open('a') as log:log.write(json.dumps(state)+'\n')
            job_path.unlink(missing_ok=True)
            # Transfer stderr is captured in state on error; do not retain per-run logs.
            (folder/(job['id']+'.log')).unlink(missing_ok=True)

if __name__=='__main__':
    if len(sys.argv)!=4 or sys.argv[1]!='--worker':raise SystemExit('Use the supervised Field Station API.')
    run_worker(Path(sys.argv[2]),Path(sys.argv[3]))

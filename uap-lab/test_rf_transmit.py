import json,subprocess,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch,Mock
import numpy as np
import rf_transmit as tx
from rf_waveform import plan,write_iq,RATE,OFFSET,AMPLITUDE,MORSE

class LocalController(tx.Controller):
    def directory(self):self.root.mkdir(exist_ok=True);return self.root

class RFTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.c=LocalController(self.root)
        self.config=dict(callsign='W6ABC',license_class='general',tx_serial=next(iter(tx.RADIOS)),measured_dbm=-10,hardware_notes='Test fixture: dummy load, filter, power measured.',hardware_verified=True,authorization_confirmed=True,shielding_verified=False,password='test-only-passphrase')
    def tearDown(self):self.temp.cleanup()
    def arm(self):return self.c.arm(dict(profile='ham-general',password='test-only-passphrase',operator_present=True,channel_clear=True))
    def test_setup_redacts_password_and_requires_current_password(self):
        s=self.c.save(self.config);self.assertTrue(s['configured']);self.assertNotIn('password_hash',json.dumps(s));self.assertNotIn('test-only-passphrase',json.dumps(s));self.assertFalse(s['armed'])
        with self.assertRaises(ValueError):self.c.save(self.config)
        self.c.save(dict(self.config,current_password='test-only-passphrase'))
    def test_arm_requires_operator_and_matching_license(self):
        self.c.save(self.config)
        for change in ({'operator_present':False},{'channel_clear':False},{'password':'wrong'},{'profile':'ham-extra'},{'profile':'simulation'},{'profile':'shielded'},{'profile':'experimental'}):
            with self.assertRaises(ValueError):self.c.arm(dict(profile='ham-general',password='test-only-passphrase',operator_present=True,channel_clear=True)|change)
        s=self.arm();self.assertTrue(s['armed']);self.c.disarm();self.assertFalse(self.c.status()['armed'])
    def test_watchdog_expiry(self):
        self.c.save(self.config);s=self.arm();self.c.lease['heartbeat']-=7
        with self.assertRaises(ValueError):self.c.send(dict(message='TEST',arm_token=s['arm_token']))
        self.assertFalse(self.c.status()['armed']);self.assertFalse(tx.read(self.root/'lease.json')['armed'])
    def test_reject_arbitrary_hardware_parameters_and_power(self):
        for delta in ({'frequency_hz':1600000000},{'gain_db':47},{'measured_dbm':float('nan')},{'measured_dbm':1},{'hardware_verified':False},{'tx_serial':'other'}):
            with self.assertRaises(ValueError):self.c.save(self.config|delta)
    def test_one_shot_and_fixed_command(self):
        self.c.save(self.config);s=self.arm()
        fake=Mock();fake.poll.return_value=None
        with patch.object(tx.subprocess,'Popen',return_value=fake) as popen:
            r=self.c.send(dict(message='TEST',arm_token=s['arm_token']));self.assertTrue(r['accepted']);self.assertEqual(popen.call_count,1)
            with self.assertRaises(ValueError):self.c.send(dict(message='TEST',arm_token=s['arm_token']))
        job=tx.read(self.root/(r['id']+'.json'));self.assertNotIn('password_hash',job['config'])
        cmd=tx.transfer_command(self.config,self.root/'test.cs8',plan('TEST','W6ABC'))
        self.assertEqual(cmd[cmd.index('-x')+1],'0');self.assertEqual(cmd[cmd.index('-a')+1],'0');self.assertEqual(cmd[cmd.index('-p')+1],'0');self.assertNotIn('-R',cmd);self.assertIn('-n',cmd)
    def test_cw_duration_id_and_rejection(self):
        self.assertEqual(MORSE['S'],'...');self.assertEqual(MORSE['O'],'---');self.assertEqual(MORSE['X'],'-..-')
        p=plan('sos','W6ABC');self.assertEqual(p['text'],'SOS DE W6ABC');self.assertLess(p['seconds'],30)
        for message in ('🌙','', 'Z'*64):
            with self.assertRaises(ValueError):plan(message,'W6ABC')
    def test_generated_iq_frequency_envelope_and_size(self):
        path=self.root/'wave.cs8';p=dict(spans=[(True,160000)])
        self.assertEqual(write_iq(path,p),160000)
        raw=np.fromfile(path,dtype=np.int8).reshape(-1,2);self.assertEqual(path.stat().st_size,320000)
        self.assertTrue(np.all(raw[0]==0));self.assertTrue(np.all(raw[-1]==0));self.assertLessEqual(np.abs(raw).max(),AMPLITUDE)
        z=raw[60000:100000,0].astype(float)+1j*raw[60000:100000,1]
        freq=np.fft.fftfreq(len(z),1/RATE)[np.argmax(abs(np.fft.fft(z)))];self.assertAlmostEqual(freq,OFFSET)
    def test_worker_restores_receiver_after_transfer_failure(self):
        job=self.root/'job.json';cfg=tx.validate_config(self.config);project=self.root/'project';project.mkdir()
        (project/'services.json').write_text(json.dumps({'rf':['logger','--serial',cfg['tx_serial']]}))
        tx.atomic(job,dict(id='job',message='TEST',config=cfg,profile='ham-general',token='lease',requested_epoch=time.time()))
        tx.atomic(self.root/'lease.json',dict(armed=True,token='lease',updated_epoch=time.time()))
        fake=Mock();fake.poll.return_value=1;fake.returncode=1;fake.stderr.read.return_value=b'test device failure'
        def command(args,**kwargs):
            # First print verifies loaded service; second print sees booted-out service.
            if args[1]=='print':command.prints+=1;return subprocess.CompletedProcess(args,0 if command.prints==1 else 1)
            return subprocess.CompletedProcess(args,0)
        command.prints=0
        with patch.object(tx,'write_iq',side_effect=lambda path,*args:path.write_bytes(b'00')),patch.object(tx.subprocess,'run',side_effect=command) as run,patch.object(tx.subprocess,'Popen',return_value=fake):
            tx.run_worker(job,project)
        calls=[c.args[0][1] for c in run.call_args_list];self.assertIn('bootout',calls);self.assertIn('bootstrap',calls)
        s=tx.read(self.root/'state.json');self.assertEqual(s['phase'],'failed');self.assertTrue(s['receiver_restored']);self.assertFalse(s['transmitted']);self.assertFalse((self.root/'job.cs8').exists());self.assertFalse(tx.read(self.root/'lease.json')['armed'])

class WorkerWatchdogTests(unittest.TestCase):
    def test_lost_heartbeat_terminates_transfer_and_restores_rx(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);project=root/'project';project.mkdir();serial=next(iter(tx.RADIOS))
            (project/'services.json').write_text(json.dumps({'rf':['logger','--serial',serial]}))
            cfg=dict(callsign='W6ABC',tx_serial=serial,measured_dbm=-10)
            job=root/'job.json';tx.atomic(job,dict(id='job',message='TEST',config=cfg,profile='ham-general',token='t',requested_epoch=time.time()));tx.atomic(root/'lease.json',dict(armed=True,token='t',updated_epoch=time.time()))
            fake=Mock();fake.stopped=False
            def poll():
                if fake.stopped:return 0
                tx.atomic(root/'lease.json',dict(armed=False,updated_epoch=time.time()));return None
            def terminate():fake.stopped=True
            fake.poll.side_effect=poll;fake.terminate.side_effect=terminate
            calls=[]
            def run(args,**kwargs):
                calls.append(args[1]);return subprocess.CompletedProcess(args,1 if args[1]=='print' and calls.count('print')>1 else 0)
            with patch.object(tx,'write_iq',side_effect=lambda path,*args:path.write_bytes(b'00')),patch.object(tx.subprocess,'run',side_effect=run),patch.object(tx.subprocess,'Popen',return_value=fake):tx.run_worker(job,project)
            fake.terminate.assert_called_once();self.assertIn('bootstrap',calls);self.assertFalse(tx.read(root/'state.json')['transmitted']);self.assertFalse((root/'job.cs8').exists())

if __name__=='__main__':unittest.main()

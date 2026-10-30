"""Automatic paired trials, controlled stimulus playback, and 1 fps exports."""
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from collections import defaultdict


def utc():
    return datetime.now(timezone.utc).isoformat()


def load(path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def save(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        stream.write(json.dumps(value, indent=2))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    directory = os.open(path.parent, os.O_RDONLY | getattr(os,'O_DIRECTORY',0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def file_info(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return dict(bytes=path.stat().st_size, sha256=digest.hexdigest())


class StorageWait(OSError):
    pass


class Experiments:
    def __init__(self, station, root, data, run, ffmpeg, env, storage, readrate=0.5):
        self.station, self.root, self.data, self.run = station, root, data, run
        self.ffmpeg, self.env, self.storage = ffmpeg, env, storage
        self.readrate=readrate
        self.assets = data.parent / 'experiment-audio'
        self.config = run / 'automatic.json'
        previous = load(self.config, {})
        self.auto = dict(enabled=bool(previous.get('enabled', False)), phase='waiting_schedule' if previous.get('enabled') else 'disabled',
                         next_condition='silence', pair=previous.get('pair', 1), completed_sessions=previous.get('completed_sessions', 0),
                         run_id=previous.get('run_id'), repeat=previous.get('repeat', True), last_session=None, error=None,
                         output=previous.get('output', ''), volume=previous.get('volume', 0.25),
                         duration_minutes=previous.get('duration_minutes', 3), gap_minutes=previous.get('gap_minutes', 10),
                         interval_minutes=previous.get('interval_minutes', 60),
                         video_fps=previous.get('video_fps', 60), frame_export_mode=previous.get('frame_export_mode', 'selected'),
                         frame_fps=previous.get('frame_fps', 60) if 'frame_export_mode' in previous else 60,
                         ce5_enabled=previous.get('ce5_enabled', False),
                         next_cycle_epoch=max(time.time(), previous.get('next_cycle_epoch') or 0), next_session_epoch=None,
                         cycle_settings=None, settings_revision=previous.get('settings_revision', 0))
        self.audio = None
        self.audio_log = None
        self.jobs = queue.PriorityQueue()
        self.large_jobs=queue.PriorityQueue()
        self.large_assembly_jobs=queue.PriorityQueue()
        self.large_playback_jobs=queue.PriorityQueue()
        self.pending = set()
        self.processing = None
        self.processing_proc = None
        self.assembly_proc = None
        self.large_processing=None
        self.large_processing_proc=None
        self.large_assembly_processing=None
        self.large_assembly_proc=None
        self.large_playback_processing=None
        self.large_playback_proc=None
        self.playback_proc=None
        self.playback_jobs=queue.PriorityQueue()
        self.playback_priorities={}
        self.playback_processing=None
        self.playback_locks=defaultdict(threading.Lock)
        self.assembly_jobs=queue.PriorityQueue()
        self.assembly_pending=set()
        self.assembly_processing=None
        self.assembly_locks=defaultdict(threading.RLock)
        self.pause_requested = threading.Event()
        self.io_paused = threading.Event()
        self.worker = threading.Thread(target=self.work, daemon=True)
        self.assembly_worker=threading.Thread(target=self.assemble_work,daemon=True)
        self.playback_worker=threading.Thread(target=self.playback_work,daemon=True)
        self.large_worker=threading.Thread(target=lambda:self.work(large=True),daemon=True)
        self.large_assembly_worker=threading.Thread(target=lambda:self.assemble_work(large=True),daemon=True)
        self.large_playback_worker=threading.Thread(target=lambda:self.playback_work(large=True),daemon=True)
        self.next_recovery=0
        self.resume_pending()
        self.large_worker.start()
        self.large_assembly_worker.start()
        self.large_playback_worker.start()
        self.worker.start()
        self.assembly_worker.start()
        self.playback_worker.start()

    def launch_media(self,args,**kwargs):
        """Keep offline media work below live capture in CPU and I/O priority."""
        proc=subprocess.Popen(args,**kwargs)
        try:os.setpriority(os.PRIO_PROCESS,proc.pid,10)
        except OSError:pass
        ionice=shutil.which('ionice')
        if ionice:
            try:subprocess.run([ionice,'-c','2','-n','7','-p',str(proc.pid)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3)
            except (OSError,subprocess.TimeoutExpired):pass
        return proc

    def storage_reserve(self):
        return float(load(self.run/'storage-policy.json',{}).get('reserve_gib',3))*1024**3

    def prepare_selected_stills(self,folder,source,info):
        frames=folder/'frames';frames.mkdir(exist_ok=True)
        if frames.is_symlink():raise ValueError('Unsafe frames directory')
        duration=float(info.get('format',{}).get('duration') or 0)
        offsets=sorted({0.0,max(0,duration/2),max(0,duration-1)})
        entries=[]
        for offset in offsets:
            self.io_gate()
            if self.station.exiting.is_set():raise OSError('Selected stills paused by shutdown')
            if self.storage()['free']<self.storage_reserve():raise StorageWait('Storage reserve reached')
            name=f'frame-{len(entries):09d}.jpg';target=frames/name;temporary=frames/(name+'.tmp')
            args=[self.ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-y','-ss',str(offset),'-i',str(source),'-map','0:v:0','-frames:v','1']
            args += ['-c:v','copy'] if info['streams'][0]['codec_name']=='mjpeg' else ['-c:v','mjpeg','-q:v','2','-threads','1']
            result=subprocess.run(args+['-f','image2',str(temporary)],env=self.env,capture_output=True,timeout=60)
            if result.returncode or not temporary.is_file() or not temporary.stat().st_size:raise OSError('Could not extract selected still: '+result.stderr.decode(errors='replace')[-500:])
            temporary.replace(target)
            entries.append(dict(file=name,video_time_seconds=offset,**file_info(target)))
        index=dict(mode='selected',timing='Representative stills near start, middle and end; original JPEG packets where available.',frames=entries)
        save(frames/'index.json',index)
        with self.station.lock:
            manifest=load(folder/'manifest.json',{})
            manifest['frame_integrity']=dict(every_recorded_frame=False,selected_original_stills=True)
            save(folder/'manifest.json',manifest)
        self.update_frames(folder.name,dict(state='completed',mode='selected',count=len(entries),completed_at=utc()),frames/'index.json')
        return index

    def resume_pending(self):
        # Reconcile durable state repeatedly, including failures after startup.
        self.next_recovery=time.monotonic()+300
        if not self.storage()['available']:
            return
        for path in self.data.glob('*/manifest.json'):
            m=load(path,{})
            if m.get('state') not in ('completed','interrupted'):
                continue
            if m.get('youtube',{}).get('state')=='cleaned':
                continue
            sid=m.get('id','')
            if not re.fullmatch(r'[0-9TZ]+-[a-f0-9]{6}',sid):
                continue
            folder=path.parent
            archive=folder/'video.mkv'
            buffered=load(folder/'buffer-state.json',{})
            if not archive.is_file() and not buffered.get('segments'):
                continue
            if archive.is_file() and m.get('video_playback',{}).get('state')!='completed':
                self.queue_playback(sid)
            if m.get('frames',{}).get('state')!='completed':
                if m.get('frames',{}).get('state')=='waiting_storage':
                    required=(archive.stat().st_size*.15 if archive.exists() and m.get('frame_export_mode')=='selected' else archive.stat().st_size*1.15 if archive.exists() else sum(v['bytes'] for v in buffered.get('segments',[]))*(1.05 if m.get('frame_export_mode')=='selected' else 2.2))+self.storage_reserve()
                    if self.storage()['free']<required:
                        continue
                self.queue_frames(sid)

    def wait_for_recovery(self, message):
        self.auto.update(phase='waiting_resources', error=message, last_session=None,
                         next_condition='silence', next_session_epoch=None, cycle_settings=None)
        save(self.config, self.auto)

    def outputs(self):
        try:
            result = subprocess.run(['aplay', '-L'], capture_output=True, text=True, timeout=5)
            devices = []
            for line in result.stdout.splitlines():
                if line.startswith('plughw:CARD='):
                    devices.append(dict(id=line.strip(), name=line.split('CARD=', 1)[1].replace(',DEV=', ' / device ')))
            return devices
        except (OSError, subprocess.TimeoutExpired):
            return []

    def tone(self):
        metadata = load(self.assets / 'ce5.json', {})
        return dict(ready=(self.assets / 'ce5.wav').is_file() and bool(metadata), **metadata)

    def library(self):
        root = self.data.parent / 'Uploads'
        if not root.is_dir():
            return []
        tracks = []
        extensions = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.aiff'}
        for path in sorted(root.rglob('*')):
            if path.suffix.lower() not in extensions or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
                continue
            relative = str(path.relative_to(root))
            tracks.append(dict(path=relative, name=relative, bytes=path.stat().st_size))
        # The supplied guide identifies CD3 as the field-work audio.
        return sorted(tracks, key=lambda item: ('WGT-CD3/' not in item['path'], item['path']))

    def select(self, body):
        with self.station.lock:
            relative = str(body.get('path', ''))
            if relative not in {track['path'] for track in self.library()}:
                raise ValueError('Choose an audio file listed in the SSD library.')
            if self.auto['enabled'] or self.station.active:
                raise ValueError('Stop capture before changing the CE5 stimulus.')
            if not self.storage()['available']:
                raise ValueError('Mount the T7 before selecting audio.')
            source = self.data.parent / 'Uploads' / relative
            self.assets.mkdir(exist_ok=True)
            temporary = self.assets / ('import-'+secrets.token_hex(6)+'.tmp')
            try:
                shutil.copyfile(source, temporary)
                metadata = self.upload(temporary, relative)
                metadata.pop('ready', None)
                metadata['library_path'] = relative
                save(self.assets/'ce5.json', metadata)
                return self.tone()
            finally:
                temporary.unlink(missing_ok=True)

    def status(self):
        return dict(exports_paused=(self.run/'exports-paused').exists(),automatic=self.auto.copy(), tone=self.tone(), outputs=self.outputs(),
                    processing=self.processing, large_processing=self.large_processing, large_assembly_processing=self.large_assembly_processing, large_playback_processing=self.large_playback_processing, queued=len(self.pending),assembly_processing=self.assembly_processing,assembly_queued=len(self.assembly_pending),playback_processing=self.playback_processing,playback_queued=len(self.playback_priorities),
                    camera_speaker='Unavailable: camera HDMI is output-only. Use a Pi-connected speaker.')

    def require_rf(self):
        frame = load(Path(os.environ.get('RF_LIVE_PATH','/home/hackrf/signal-spool/live.json')), {})
        if abs(time.time()-frame.get('timestamp', 0)) > 5:
            raise ValueError('Fresh RF measurements are required for automatic experiments.')

    def pause_exports(self):
        self.pause_requested.set()
        for proc in (self.processing_proc,self.assembly_proc,self.playback_proc,self.large_processing_proc,self.large_assembly_proc,self.large_playback_proc):
            if proc and proc.poll() is None:
                try:
                    proc.send_signal(signal.SIGSTOP)
                except ProcessLookupError:
                    pass
        if not self.processing or self.io_paused.wait(2):
            return True
        self.resume_exports()
        return False

    def resume_exports(self):
        self.pause_requested.clear()
        if (self.run/'exports-paused').exists():return
        for proc in (self.processing_proc,self.assembly_proc,self.playback_proc,self.large_processing_proc,self.large_assembly_proc,self.large_playback_proc):
            if proc and proc.poll() is None:
                try:proc.send_signal(signal.SIGCONT)
                except ProcessLookupError:pass

    def io_gate(self, proc=None):
        if not self.pause_requested.is_set() and not (self.run/'exports-paused').exists():
            return
        if proc and proc.poll() is None:
            try:
                proc.send_signal(signal.SIGSTOP)
            except ProcessLookupError:
                pass
        self.io_paused.set()
        while (self.pause_requested.is_set() or (self.run/'exports-paused').exists()) and not self.station.exiting.is_set():
            self.station.exiting.wait(0.1)
        self.io_paused.clear()
        if proc and proc.poll() is None:
            try:
                proc.send_signal(signal.SIGCONT)
            except ProcessLookupError:
                pass

    def hash_file(self, path):
        digest = hashlib.sha256()
        hash_start=time.monotonic();hashed=0
        with path.open('rb') as stream:
            while True:
                if self.station.exiting.is_set():raise OSError('File verification paused for station shutdown')
                self.io_gate()
                block = stream.read(1024*1024)
                if not block:
                    break
                digest.update(block)
                hashed+=len(block)
                if self.readrate:self.station.exiting.wait(max(0,hashed/(32*1024**2)-(time.monotonic()-hash_start)))
        return dict(bytes=path.stat().st_size,sha256=digest.hexdigest())

    def playback_args(self, output, volume, source=None, seconds=60):
        args = [self.ffmpeg, '-hide_banner', '-loglevel', 'warning', '-nostdin']
        if source:
            args += ['-re', '-stream_loop', '-1', '-i', str(source)]
        else:
            args += ['-re', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000']
        return args + ['-t', str(seconds), '-vn', '-af', 'volume='+str(volume), '-ac', '2',
                       '-ar', '48000', '-c:a', 'pcm_s16le', '-f', 'alsa', output]

    def validate_output(self, output):
        if output not in {o['id'] for o in self.outputs()}:
            raise ValueError('Select a connected Pi audio playback device.')
        args = [self.ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-f', 'lavfi',
                '-i', 'anullsrc=r=48000:cl=stereo', '-t', '0.1', '-f', 'alsa', output]
        try:
            result = subprocess.run(args, env=self.env, capture_output=True, timeout=8)
        except subprocess.TimeoutExpired:
            raise ValueError('Audio output did not respond. Connect a USB speaker or HDMI audio display.')
        if result.returncode:
            raise ValueError('Audio device cannot play: '+result.stderr.decode(errors='replace')[-500:])

    def upload(self, source, name):
        with self.station.lock:
            if self.auto['enabled'] or self.station.active:
                raise ValueError('Stop capture before changing the CE5 stimulus.')
            if not self.storage()['available']:
                raise ValueError('Mount the T7 before uploading audio.')
            self.assets.mkdir(exist_ok=True)
            destination = self.assets / ('source-' + secrets.token_hex(6) + '.audio')
            source.replace(destination)
            temporary = self.assets / 'ce5-new.wav'
            result = subprocess.run([self.ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
                '-i', str(destination), '-map', '0:a:0', '-t', str(self.auto['duration_minutes']*60), '-ac', '2', '-ar', '48000',
                '-c:a', 'pcm_s16le', str(temporary)], env=self.env, capture_output=True, timeout=120)
            if result.returncode or not temporary.exists() or temporary.stat().st_size < 1024:
                raise ValueError('No usable audio could be decoded from the uploaded file.')
            temporary.replace(self.assets / 'ce5.wav')
            metadata = dict(name=name[:200], uploaded_at=utc(), original_file=destination.name,
                            original=file_info(destination), prepared=file_info(self.assets/'ce5.wav'),
                            prepared_seconds=self.auto['duration_minutes']*60,
                            preparation=f'First {self.auto["duration_minutes"]*60} seconds, stereo 48 kHz PCM. Short files loop during playback.')
            save(self.assets / 'ce5.json', metadata)
            return self.tone()

    def prepare_tone(self, seconds):
        metadata = load(self.assets/'ce5.json', {})
        if metadata.get('prepared_seconds') == seconds and (self.assets/'ce5.wav').exists():
            return
        source = self.assets/metadata.get('original_file', '__missing__')
        temporary = self.assets/'ce5-new.wav'
        result = subprocess.run([self.ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
            '-i', str(source), '-map', '0:a:0', '-t', str(seconds), '-ac', '2', '-ar', '48000',
            '-c:a', 'pcm_s16le', str(temporary)], env=self.env, capture_output=True, timeout=120)
        if result.returncode or not temporary.exists() or temporary.stat().st_size < 1024:
            raise ValueError('Could not prepare the selected stimulus for this session duration.')
        temporary.replace(self.assets/'ce5.wav')
        metadata.update(prepared=file_info(self.assets/'ce5.wav'), prepared_seconds=seconds,
                        preparation=f'First {seconds} seconds, stereo 48 kHz PCM. Short files loop during playback.')
        save(self.assets/'ce5.json', metadata)

    def test_audio(self, body):
        with self.station.lock:
            if self.auto['enabled'] or self.station.active:
                raise ValueError('Stop capture before testing the speaker.')
            output = str(body.get('output', ''))
            self.validate_output(output)
            result = subprocess.run(self.playback_args(output, 0.05, seconds=2), env=self.env, capture_output=True, timeout=10)
            if result.returncode:
                raise ValueError('Speaker test failed: '+result.stderr.decode(errors='replace')[-400:])
            return dict(message='Two-second speaker test sent. Confirm you heard it before enabling automatic capture.')

    def settings(self, body):
        result = {}
        for name, low, high in (('duration_minutes', 1, 120), ('gap_minutes', 0, 1440), ('interval_minutes', 1, 1440), ('frame_fps', 1, 60)):
            raw = body.get(name, self.auto[name])
            try:
                value = int(raw)
                if float(raw) != value or not low <= value <= high:
                    raise ValueError()
            except (TypeError, ValueError, OverflowError):
                raise ValueError(f'{name.replace("_", " ")} must be a whole number from {low} to {high}.')
            result[name] = value
        rate = int(body.get('video_fps', self.auto['video_fps']))
        if rate not in (25, 30, 50, 60):
            raise ValueError('Video FPS must be 25, 30, 50, or 60.')
        mode = str(body.get('frame_export_mode', self.auto['frame_export_mode']))
        if mode not in ('all', 'sampled', 'selected'):
            raise ValueError('Choose every recorded frame or explicitly sampled frames.')
        result.update(video_fps=rate, frame_export_mode=mode)
        if mode == 'all':
            result['frame_fps'] = rate
        elif result['frame_fps'] > rate:
            raise ValueError('Sampled frame export FPS cannot exceed video capture FPS.')
        result['ce5_enabled'] = bool(body.get('ce5_enabled', self.auto['ce5_enabled']))
        result['repeat'] = bool(body.get('repeat', self.auto['repeat']))
        result['output'] = str(body.get('output', self.auto['output']))
        volume = float(body.get('volume', self.auto['volume']*100))/100
        if not 0.01 <= volume <= 1:
            raise ValueError('Volume must be between 1 and 100 percent.')
        result['volume'] = volume
        minimum = (2 if result['ce5_enabled'] else 1)*(result['duration_minutes']+result['gap_minutes'])
        if result['interval_minutes'] < minimum:
            raise ValueError(f'Run interval must be at least {minimum} minutes to fit recording durations and gaps.')
        if result['ce5_enabled']:
            if not self.tone()['ready']:
                raise ValueError('Upload your CE5 audio file before enabling paired capture.')
            self.validate_output(result['output'])
        return result

    def configure(self, body):
        with self.station.lock:
            values = self.settings(body)
            self.auto.update(values)
            self.auto['settings_revision'] += 1
            if self.auto.get('cycle_started_epoch'):
                self.auto['next_cycle_epoch'] = max(time.time(), self.auto['cycle_started_epoch']+values['interval_minutes']*60)
            save(self.config, self.auto)
            return self.auto.copy()

    def enable(self, body):
        with self.station.lock:
            if self.auto['enabled'] or self.station.active:
                raise ValueError('Stop the current session or automatic sequence first.')
            if not self.storage()['available'] or self.storage()['free'] < self.storage_reserve():
                raise ValueError('The recording SSD must be mounted with at least 3 GB free.')
            values = self.settings(body)
            self.require_rf()
            if not self.station.proc or self.station.proc.poll() is not None or self.station.preview_age() > 5:
                raise ValueError('Fresh camera frames are required.')
            self.auto.update(values)
            self.auto.update(enabled=True, phase='waiting_schedule', next_condition='silence', pair=1,
                completed_sessions=0, run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(3),
                last_session=None, error=None, next_cycle_epoch=time.time(), next_session_epoch=None,
                cycle_settings=None, cycle_started_epoch=None, settings_revision=self.auto['settings_revision']+1)
            save(self.config, self.auto)
            return self.auto.copy()

    def disable(self, body=None):
        with self.station.lock:
            self.auto.update(enabled=False, phase='disabled')
            save(self.config, self.auto)
            if self.station.active and self.station.active.get('automatic_run'):
                self.station.stop('Automatic capture disabled by observer')
            return self.auto.copy()

    def fail(self, message):
        self.auto.update(enabled=False, phase='error', error=message)
        save(self.config, self.auto)

    def tick(self):
        if time.monotonic()>=self.next_recovery:
            self.resume_pending()
        active = self.station.active
        if active and active.get('automatic_run'):
            try:
                self.require_rf()
            except ValueError as error:
                self.wait_for_recovery(str(error))
                active['trial_valid'] = False
                self.station.stop('Automatic sequence stopped: RF data stale')
                return
            if self.audio and self.audio.poll() is not None:
                code = self.audio.returncode
                expected_audio = active.get('playback',{}).get('requested_duration_seconds',active.get('duration_limit_seconds',60))
                if code != 0 or time.monotonic()-active['started_monotonic'] < expected_audio-2:
                    active['trial_valid'] = False
                    self.fail('CE5 playback ended early or failed. Check the speaker and playback log.')
                    self.station.stop('CE5 playback failed')
                    return
                active['playback'].update(state='completed',ended_at=utc(),ended_elapsed_seconds=time.monotonic()-active['started_monotonic'])
                self.audio = None
                self.audio_log.close()
        if not self.auto['enabled'] or self.station.active:
            return
        if not self.readrate and (self.processing or self.pending):
            self.auto['phase'] = 'extracting_frames'
            return
        if not self.storage()['available'] or self.storage()['free']<self.storage_reserve():
            self.auto['phase']='waiting_resources'
            self.auto['error']='Waiting for recording SSD and free space'
            return
        now = time.time()
        last_id = self.auto['last_session']
        if last_id:
            previous = load(self.data / last_id / 'manifest.json', {})
            frames = previous.get('frames', {})
            exporting=frames.get('state') in ('queued','processing','waiting_storage')
            if exporting and (not self.readrate or self.auto['next_condition']=='ce5'):
                self.auto['phase']='extracting_frames'
                return
            if (not exporting and frames.get('state')!='completed') or previous.get('state')!='completed' or previous.get('trial_valid') is False:
                self.wait_for_recovery('Previous trial interrupted or export failed; resuming with a fresh baseline.')
                return
            if self.auto['next_condition'] == 'ce5':
                if now < (self.auto.get('next_session_epoch') or 0):
                    self.auto['phase'] = 'waiting_gap'
                    return
            else:
                if not self.auto['repeat']:
                    self.auto.update(enabled=False, phase='completed')
                    save(self.config, self.auto)
                    return
                if now < self.auto['next_cycle_epoch']:
                    self.auto['phase'] = 'waiting_schedule'
                    return
        elif now < self.auto['next_cycle_epoch']:
            self.auto['phase'] = 'waiting_schedule'
            return
        try:
            self.require_rf()
            if self.station.preview_age() > 3:
                return
            condition = self.auto['next_condition']
            if condition == 'silence':
                self.auto['cycle_settings'] = {k: self.auto[k] for k in ('duration_minutes', 'gap_minutes', 'interval_minutes', 'frame_fps', 'video_fps', 'frame_export_mode', 'ce5_enabled', 'output', 'volume')}
                self.auto['cycle_started_epoch'] = now
                interval = self.auto['interval_minutes']*60
                due = self.auto['next_cycle_epoch']
                if due <= now:
                    due += (int((now-due)//interval)+1)*interval
                self.auto['next_cycle_epoch'] = due
            cycle = self.auto['cycle_settings'] or self.auto
            self.station.start(dict(title=f'Automatic pair {self.auto["pair"]} · {"Silence" if condition=="silence" else "CE5 tones"}',
                condition=condition, minutes=cycle['duration_minutes'],
                notes=f'Automatic scheduled trial. Frame export: {cycle["frame_fps"]} fps. CE5 stage enabled: {cycle["ce5_enabled"]}.'), automatic=True)
        except (ValueError, OSError) as error:
            self.auto.update(phase='waiting_resources',error=str(error))

    def session_started(self, manifest):
        cycle = self.auto['cycle_settings'] or self.auto
        manifest.update(automatic_run=self.auto['run_id'], pair=self.auto['pair'], trial_valid=True,
                        experiment_settings=dict(cycle), frame_fps=cycle['frame_fps'], video_fps=cycle['video_fps'], frame_export_mode=cycle['frame_export_mode'])
        self.auto['phase'] = 'recording_' + manifest['condition']
        self.auto['error'] = None
        if manifest['condition'] == 'ce5':
            self.prepare_tone(manifest['duration_limit_seconds'])
            target = self.data / manifest['id'] / 'stimulus.wav'
            shutil.copyfile(self.assets / 'ce5.wav', target)
            tone = self.tone()
            manifest['playback'] = dict(state='playing', file='stimulus.wav', source_name=tone['name'],
                stimulus=file_info(target), output=cycle['output'], volume=cycle['volume'],
                requested_duration_seconds=manifest['duration_limit_seconds'],
                requested_start_at=utc(), requested_start_elapsed_seconds=time.monotonic()-manifest['started_monotonic'],
                timing='Software playback request; acoustic onset and loudness are not measured.')
            self.audio_log = (self.data / manifest['id'] / 'playback.log').open('w')
            self.audio = subprocess.Popen(self.playback_args(cycle['output'], cycle['volume'], target, seconds=manifest['duration_limit_seconds']),
                env=self.env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=self.audio_log)
        else:
            manifest['playback'] = dict(state='silent', description='No station-controlled audio played during this trial.')
        save(self.config, self.auto)

    def before_finalize(self, manifest, reason):
        if self.audio:
            code = self.audio.poll()
            if code is None:
                self.audio.send_signal(signal.SIGINT)
                try:
                    self.audio.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.audio.kill()
                    self.audio.wait()
            playback = manifest.get('playback', {})
            playback.update(state='completed' if reason=='Automatic stop: duration reached' and code in (None, 0) else 'stopped',
                            stopped_at=utc(), process_exit_status=self.audio.returncode)
            if manifest.get('trial_valid') is False:
                playback['state'] = 'failed'
            self.audio = None
            self.audio_log.close()
        if manifest.get('automatic_run'):
            if reason != 'Automatic stop: duration reached':
                manifest['trial_valid'] = False
                if reason == 'Station shutting down':
                    self.auto['phase'] = 'waiting_schedule'
                elif reason in ('Manual stop', 'Automatic capture disabled by observer'):
                    self.auto.update(enabled=False, phase='disabled')
                else:
                    self.wait_for_recovery(reason)
            self.auto['last_session'] = manifest['id']
            if manifest.get('trial_valid') and manifest['state']=='completed':
                self.auto['completed_sessions'] += 1
                cycle = self.auto['cycle_settings'] or self.auto
                if manifest['condition']=='silence' and cycle['ce5_enabled']:
                    self.auto['next_condition'] = 'ce5'
                    self.auto['next_session_epoch'] = manifest.get('stopped_epoch', time.time())+cycle['gap_minutes']*60
                else:
                    self.auto['next_condition'] = 'silence'
                    self.auto['next_session_epoch'] = None
                    self.auto['pair'] += 1
                    self.auto['next_cycle_epoch'] = max(self.auto['next_cycle_epoch'], manifest.get('stopped_epoch', time.time())+cycle['gap_minutes']*60)
                self.auto['phase'] = 'extracting_frames'
            save(self.config, self.auto)
        fps = manifest.get('frame_fps', self.auto['frame_fps'])
        mode = manifest.get('frame_export_mode', self.auto['frame_export_mode'])
        manifest['frames'] = dict(state='queued' if manifest['state']=='completed' else 'skipped', fps=fps, mode=mode, count=0)

    def queue_frames(self, sid):
        if not re.fullmatch(r'[0-9TZ]+-[a-f0-9]{6}', sid):
            raise ValueError('Invalid session ID')
        with self.station.lock:
            folder=self.data/sid
            if (folder/'buffer-state.json').exists() and not (folder/'video.mkv').exists() and sid not in self.assembly_pending:
                self.assembly_pending.add(sid)
                size=sum(v.get('bytes',0) for v in load(folder/'buffer-state.json',{}).get('segments',[]))
                (self.large_assembly_jobs if size>2*1024**3 else self.assembly_jobs).put((size,time.monotonic_ns(),sid))
            if (folder/'video.mkv').is_file():self.queue_playback(sid)
            if sid in self.pending:
                return
            self.pending.add(sid)
            size=(folder/'video.mkv').stat().st_size if (folder/'video.mkv').exists() else sum(v.get('bytes',0) for v in load(folder/'buffer-state.json',{}).get('segments',[]))
            (self.large_jobs if size>2*1024**3 else self.jobs).put((size,time.monotonic_ns(),sid))

    def retry(self, body):
        sid = str(body.get('id', ''))
        if not re.fullmatch(r'[0-9TZ]+-[a-f0-9]{6}', sid):
            raise ValueError('Invalid session ID')
        with self.station.lock:
            m = load(self.data / sid / 'manifest.json', {})
            if m.get('state') != 'completed':
                raise ValueError('A completed recording is required.')
            if m.get('frames', {}).get('state') == 'completed' and not body.get('force'):
                return m['frames']
            mode = 'all' if body.get('all_frames') else self.auto['frame_export_mode']
            m['frame_export_mode'] = mode
            m['frame_fps'] = m.get('video_fps', 30) if mode=='all' else self.auto['frame_fps']
            m['frames'] = dict(state='queued', fps=m['frame_fps'], mode=mode, count=0)
            save(self.data / sid / 'manifest.json', m)
            self.queue_frames(sid)
            return m['frames']

    def update_frames(self, sid, value, index=None):
        with self.station.lock:
            path = self.data / sid / 'manifest.json'
            manifest = load(path)
            if manifest:
                manifest['frames'] = value
                if index:
                    manifest.setdefault('files', {})['frames/index.json'] = file_info(index)
                save(path, manifest)

    def probe(self, source, count=False):
        executable = str(Path(self.ffmpeg).with_name('ffprobe'))
        p = subprocess.run([executable, '-v', 'error', *(['-count_packets'] if count else []), '-show_entries',
             'stream=codec_name,width,height,sample_aspect_ratio,display_aspect_ratio,avg_frame_rate,nb_frames,nb_read_packets:format=duration', '-of', 'json', str(source)],
             env=self.env, capture_output=True, text=True, timeout=30)
        if p.returncode:
            raise OSError('Cannot inspect recorded video')
        return json.loads(p.stdout)

    def assemble_buffer(self,folder,background=False,large=False):
        with self.assembly_locks[str(folder)]:
            return self._assemble_buffer(folder,background,large)

    def _assemble_buffer(self, folder, background=False,large=False):
        if (folder/'video.mkv').exists():return
        state=load(folder/'buffer-state.json',{})
        segments=state.get('segments',[])
        if not segments:raise OSError('No buffered video segments are recoverable')
        required=sum(v['bytes'] for v in segments)*(1.05 if load(folder/'manifest.json',{}).get('frame_export_mode')=='selected' else 2.2)+self.storage_reserve()
        if self.storage()['free']<required:raise StorageWait('Waiting for enough SSD space to assemble and export every frame')
        playlist=folder/'buffer-concat.txt'
        lines=['ffconcat version 1.0']
        for seg in segments:
            name=seg['file']
            if not re.fullmatch(r'segment-[0-9]{9}\.mkv',name):raise ValueError('Invalid buffered segment name')
            if not (folder/'buffer-segments'/name).is_file():raise OSError('Buffered segment is missing')
            lines += [f"file 'buffer-segments/{name}'", f"duration {seg['end']-seg['start']:.9f}"]
        playlist.write_text('\n'.join(lines)+'\n')
        start=max(state['requested_start_epoch'],segments[0]['start_epoch'])
        end=min(state.get('requested_end_epoch') or segments[-1]['end_epoch'],segments[-1]['end_epoch'])
        if end<=start:raise OSError('Buffered clip has no video interval')
        offset=start-segments[0]['start_epoch']
        destination=folder/'video-assembling.mkv'
        assembly_rate=float(os.environ.get('CAPTURE_ASSEMBLY_READRATE','2' if os.environ.get('CAPTURE_DURABLE_SPOOL')=='1' else str(self.readrate)))
        if assembly_rate and not .25<=assembly_rate<=4:raise ValueError('Assembly read rate must be between 0.25 and 4')
        args=[self.ffmpeg,'-progress',str(folder/'assembly-progress.txt'),'-hide_banner','-loglevel','warning','-nostdin','-y','-f','concat','-safe','0',
              *(['-readrate',str(assembly_rate)] if assembly_rate else []),'-i',str(playlist),'-ss',f'{offset:.9f}','-t',f'{end-start:.9f}',
              '-map','0:v:0','-c:v','copy','-fps_mode','passthrough','-avoid_negative_ts','make_zero',str(destination)]
        proc=None
        try:
            with (folder/'assembly.log').open('w') as log:
                proc=self.launch_media(args,env=self.env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=log)
                setattr(self,('large_assembly_proc' if large else 'assembly_proc') if background else ('large_processing_proc' if large else 'processing_proc'),proc)
                while proc.poll() is None:
                    self.io_gate(proc)
                    if self.station.exiting.wait(.1):raise OSError('Assembly paused by station shutdown')
                    if not self.storage()['available'] or self.storage()['free']<self.storage_reserve():
                        raise StorageWait('Waiting for SSD space during assembly')
                if proc.returncode:raise OSError('Video assembly failed; see assembly.log')
            info=self.probe(destination)
            progress=dict(line.split('=',1) for line in (folder/'assembly-progress.txt').read_text().splitlines() if '=' in line)
            count=int(progress.get('frame',0))
            if count<1:raise OSError('No frames in assembled clip')
            with destination.open('rb') as stream:os.fsync(stream.fileno())
            destination.replace(folder/'video.mkv')
            state.update(state='assembled',archive_frames=count,clip_start_epoch=start,clip_end_epoch=end,
                         trim_start_seconds=offset,clip_seconds=end-start)
            save(folder/'buffer-state.json',state)
            with self.station.lock:
                manifest=load(folder/'manifest.json',{})
                manifest['capture_stats']=dict(frame=count)
                manifest['buffer_assembly']=dict(state='completed',frames=count,seconds=end-start,
                    trim_start_seconds=offset,packet_copy=True,
                    timing='Original segment packet timestamps; host UTC mapping estimated from first segment write time. HDMI latency uncalibrated.')
                save(folder/'manifest.json',manifest)
        finally:
            if proc and proc.poll() is None:
                try:proc.send_signal(signal.SIGCONT)
                except ProcessLookupError:pass
                proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
            setattr(self,('large_assembly_proc' if large else 'assembly_proc') if background else ('large_processing_proc' if large else 'processing_proc'),None)

    def cleanup_buffer_segments(self,folder):
        with self.assembly_locks[str(folder)]:
            self._cleanup_buffer_segments(folder)

    def _cleanup_buffer_segments(self,folder):
        state=load(folder/'buffer-state.json',{})
        if state.get('state')!='assembled' or state.get('temporary_segments_removed'):return
        for seg in state.get('segments',[]):
            name=seg['file']
            if re.fullmatch(r'segment-[0-9]{9}\.mkv',name):
                (folder/'buffer-segments'/name).unlink(missing_ok=True)
        state['temporary_segments_removed']=True
        save(folder/'buffer-state.json',state)
        with self.station.lock:
            manifest=load(folder/'manifest.json',{})
            manifest.setdefault('files',{})['buffer-state.json']=file_info(folder/'buffer-state.json')
            save(folder/'manifest.json',manifest)

    def assemble_work(self,large=False):
        jobs=self.large_assembly_jobs if large else self.assembly_jobs
        while not self.station.exiting.is_set():
            try:size,sequence,sid=jobs.get(timeout=.5)
            except queue.Empty:continue
            folder=self.data/sid
            guard=self.assembly_locks[str(folder)]
            if not guard.acquire(blocking=False):
                jobs.put((size,time.monotonic_ns(),sid));jobs.task_done()
                self.station.exiting.wait(.1);continue
            setattr(self,'large_assembly_processing' if large else 'assembly_processing',sid)
            try:
                self.io_gate()
                self.assemble_buffer(folder,background=True,large=large)
                info=dict(bytes=(folder/'video.mkv').stat().st_size,integrity='queued')
                with self.station.lock:
                    m=load(folder/'manifest.json',{})
                    m.setdefault('files',{})['video.mkv']=info
                    save(folder/'manifest.json',m)
                # These are scratch copies; the fsynced lossless archive is now committed.
                self.cleanup_buffer_segments(folder)
                self.queue_playback(sid)
                self.queue_frames(sid)
            except (OSError,ValueError,KeyError,subprocess.TimeoutExpired) as error:
                if isinstance(error,StorageWait):
                    self.update_frames(sid,dict(state='waiting_storage',error=str(error),count=0))
                else:
                    with self.station.lock:
                        m=load(folder/'manifest.json',{})
                        if m:
                            m['buffer_assembly']=dict(state='queued' if self.station.exiting.is_set() else 'failed',error=str(error))
                            save(folder/'manifest.json',m)
            finally:
                guard.release()
                self.assembly_pending.discard(sid)
                setattr(self,'large_assembly_processing' if large else 'assembly_processing',None)
                jobs.task_done()

    def queue_playback(self,sid,priority=10):
        if not re.fullmatch(r'[0-9TZ]+-[a-f0-9]{6}',sid):raise ValueError('Invalid session ID')
        with self.station.lock:
            folder=self.data/sid
            m=load(folder/'manifest.json',{})
            if m.get('video_playback',{}).get('state')=='completed' and (folder/'video.mp4').is_file():return
            if not (folder/'video.mkv').is_file():return
            playback=m.get('video_playback',{})
            if playback.get('next_attempt',0)>time.time():return
            if playback.get('attempts',0) or playback.get('state')=='failed':priority+=100
            old=self.playback_priorities.get(sid)
            if old is not None and old<=priority:return
            self.playback_priorities[sid]=priority
            size=(folder/'video.mkv').stat().st_size
            (self.large_playback_jobs if size>2*1024**3 else self.playback_jobs).put((priority,size,time.monotonic_ns(),sid))

    def prepare_playback(self,folder,background=False,large=False):
        with self.playback_locks[str(folder)]:
            m=load(folder/'manifest.json',{})
            target=folder/'video.mp4'
            if m.get('video_playback',{}).get('state')=='completed' and target.is_file():return
            source=folder/'video.mkv'
            if not source.exists():return # Legacy MP4 already is the source.
            if self.storage()['free']<self.storage_reserve()+max(32*1024**2,int(source.stat().st_size*.15)):
                raise StorageWait('Waiting for space to create playback MP4')
            info=self.probe(source);stream=info['streams'][0]
            expected=m.get('capture_stats',{}).get('frame') or int(stream.get('nb_frames') or 0)
            temporary=folder/'video-playback-tmp.mp4'
            args=[self.ffmpeg,'-progress',str(folder/'playback-progress.txt'),'-hide_banner','-loglevel','warning','-nostdin','-y','-threads','1','-i',str(source),
                '-map','0:v:0','-vf','setsar=1','-c:v','libx264','-preset','ultrafast','-crf','18','-threads','1',
                '-pix_fmt','yuv420p','-profile:v','high','-level:v','4.2','-fps_mode','passthrough',
                '-movflags','+faststart',str(temporary)]
            remux=stream['codec_name']=='h264'
            if remux:args=[self.ffmpeg,'-progress',str(folder/'playback-progress.txt'),'-hide_banner','-loglevel','warning','-nostdin','-y','-i',str(source),'-map','0:v:0','-c:v','copy','-bsf:v','h264_metadata=sample_aspect_ratio=1/1','-aspect','16:9','-fps_mode','passthrough','-movflags','+faststart',str(temporary)]
            remote=not remux and load(self.root/'private/m1/config.json',{}).get('enabled',False)
            encoder_worker='m1' if remote else 'macbook' if sys.platform=='darwin' else 'pi'
            if remote:
                args=[sys.executable,str(self.root/'m1_encode.py'),str(source),str(temporary)]
            proc=None
            try:
                with self.station.lock:
                    current=load(folder/'manifest.json',{})
                    current['video_playback']=dict(state='processing',file='video.mp4',encoder_worker=encoder_worker,attempts=current.get('video_playback',{}).get('attempts',0))
                    save(folder/'manifest.json',current)
                with (folder/'playback-encode.log').open('w') as log:
                    proc=self.launch_media(args,env=self.env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=log)
                    setattr(self,('large_playback_proc' if large else 'playback_proc') if background else ('large_processing_proc' if large else 'processing_proc'),proc)
                    while proc.poll() is None:
                        self.io_gate(proc)
                        if self.station.exiting.wait(.2):raise OSError('Playback creation paused by shutdown')
                        if not self.storage()['available'] or self.storage()['free']<self.storage_reserve():
                            raise StorageWait('Waiting for SSD space during playback creation')
                    if proc.returncode:raise OSError('MP4 encoding failed; see playback-encode.log')
                output=self.probe(temporary);out=output['streams'][0]
                count=int(out.get('nb_frames') or 0)
                if not count:count=int(self.probe(temporary,count=True)['streams'][0].get('nb_read_packets',0))
                if expected and count!=expected:raise OSError(f'Playback frame mismatch: {count} vs {expected}')
                if out['codec_name']!='h264':raise OSError('Playback is not H.264')
                if out.get('sample_aspect_ratio')!='1:1':raise OSError('Playback pixels are not square')
                if (out['width'],out['height'])!=(stream['width'],stream['height']):raise OSError('Playback dimensions changed')
                with temporary.open('rb') as file:os.fsync(file.fileno())
                temporary.replace(target)
                metadata=self.hash_file(target)
                with self.station.lock:
                    current=load(folder/'manifest.json',{})
                    current.setdefault('files',{})['video.mp4']=metadata
                    current['video_playback']=dict(state='completed',file='video.mp4',frame_count=count,
                        avg_frame_rate=out['avg_frame_rate'],codec='h264',width=out['width'],height=out['height'],sample_aspect_ratio=out['sample_aspect_ratio'],display_aspect_ratio=out['display_aspect_ratio'],faststart=True,encoder_worker=encoder_worker,quality='Unmodified H.264 archive remux' if remux else 'libx264 ultrafast CRF18')
                    save(folder/'manifest.json',current)
            finally:
                if proc and proc.poll() is None:
                    try:proc.send_signal(signal.SIGCONT)
                    except ProcessLookupError:pass
                    proc.terminate()
                    try:proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:proc.kill();proc.wait()
                setattr(self,('large_playback_proc' if large else 'playback_proc') if background else ('large_processing_proc' if large else 'processing_proc'),None)

    def playback_work(self,large=False):
        jobs=self.large_playback_jobs if large else self.playback_jobs
        while not self.station.exiting.is_set():
            try:priority,size,sequence,sid=jobs.get(timeout=.5)
            except queue.Empty:continue
            if self.playback_priorities.get(sid)!=priority:
                jobs.task_done();continue
            setattr(self,'large_playback_processing' if large else 'playback_processing',sid)
            try:
                self.io_gate()
                self.prepare_playback(self.data/sid,background=True,large=large)
            except (OSError,ValueError,KeyError,subprocess.TimeoutExpired) as error:
                with self.station.lock:
                    path=self.data/sid/'manifest.json';m=load(path,{})
                    if m:
                        attempts=m.get('video_playback',{}).get('attempts',0)+1
                        m['video_playback']=dict(state='queued' if self.station.exiting.is_set() else 'waiting_storage' if isinstance(error,StorageWait) else 'failed',file='video.mp4',error=str(error),attempts=attempts,next_attempt=0 if self.station.exiting.is_set() else time.time()+min(28800,3600*2**min(attempts-1,3)))
                        save(path,m)
            finally:
                self.playback_priorities.pop(sid,None)
                setattr(self,'large_playback_processing' if large else 'playback_processing',None)
                jobs.task_done()

    def work(self,large=False):
        from fractions import Fraction
        jobs=self.large_jobs if large else self.jobs
        while not self.station.exiting.is_set():
            try:
                priority,sequence,sid = jobs.get(timeout=1)
            except queue.Empty:
                continue
            folder = self.data / sid
            with self.station.lock:
                deferred=(folder/'buffer-state.json').exists() and not (folder/'video.mkv').exists()
                if deferred:self.pending.discard(sid)
            if deferred:
                jobs.task_done();self.station.exiting.wait(.1);continue
            setattr(self,'large_processing' if large else 'processing',sid)
            self.io_gate()
            proc = None
            original = load(folder/'manifest.json', {})
            requested = original.get('frames', {})
            mode = requested.get('mode', original.get('frame_export_mode', 'sampled'))
            fps = requested.get('fps', 1)
            state = dict(state='processing', fps=fps, mode=mode, count=0)
            try:
                if not self.storage()['available'] or self.storage()['free'] < self.storage_reserve():
                    raise OSError('SSD unavailable or low on space')
                self.update_frames(sid, state)
                if original.get('buffered_capture') or (folder/'buffer-state.json').exists():
                    self.assemble_buffer(folder,large=large)
                    original=load(folder/'manifest.json',{})
                source = folder/'video.mkv' if (folder/'video.mkv').exists() else folder/'video.mp4'
                info = self.probe(source)
                stream = info['streams'][0]
                if mode=='selected':
                    self.prepare_selected_stills(folder,source,info)
                    self.cleanup_buffer_segments(folder)
                    continue
                if source.suffix=='.mkv':self.prepare_playback(folder,large=large)
                native = stream['codec_name']=='mjpeg'
                if native and mode=='all' and self.storage()['free']<source.stat().st_size*1.15+3*1024**3:
                    raise StorageWait('Waiting for enough SSD space to export every recorded frame')
                if not native and not stream.get('nb_frames'):
                    info = self.probe(source,count=True)
                    stream = info['streams'][0]
                frames = folder/'frames'
                frames.mkdir(exist_ok=True)
                # A new versioned directory keeps prior exports intact during retries.
                export = frames/('export-'+secrets.token_hex(5))
                export.mkdir()
                hashes = export/'packets.sha256'
                tee = f'[f=image2:start_number=0]{export}/frame-%09d.jpg|[f=framehash:hash=sha256]{hashes}'
                args = [self.ffmpeg, '-hide_banner', '-loglevel', 'warning', '-nostdin', '-y', '-threads', '2', *(['-readrate',str(self.readrate)] if self.readrate else []), '-i', str(source)]
                args += ['-map', '0:v:0']
                if mode=='all' and native:
                    args += ['-c:v', 'copy']
                else:
                    if mode!='all':
                        args += ['-vf', 'fps='+str(fps)]
                    args += ['-c:v', 'mjpeg', '-q:v', '2', '-threads', '1']
                args += ['-fps_mode', 'passthrough', '-f', 'tee', tee]
                with (folder/'frames.log').open('w') as log:
                    proc = self.launch_media(args, env=self.env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log)
                    setattr(self,'large_processing_proc' if large else 'processing_proc',proc)
                    while proc.poll() is None:
                        self.io_gate(proc)
                        if self.station.exiting.wait(0.5):
                            raise OSError('Frame export paused by station shutdown')
                        if not self.storage()['available'] or self.storage()['free'] < self.storage_reserve():
                            raise OSError('SSD unavailable or low on space during export')
                    if proc.returncode:
                        raise OSError('Video/frame export failed; see frames.log')
                entries = []
                setattr(self,'large_processing_proc' if large else 'processing_proc',None)
                time_base = Fraction(1, fps)
                first_pts = None
                for line in hashes.read_text().splitlines():
                    self.io_gate()
                    if line.startswith('#tb 0:'):
                        time_base = Fraction(line.split(':',1)[1].strip())
                    if line.startswith('#') or not line.strip():
                        continue
                    row = [x.strip() for x in line.split(',')]
                    pts, size, digest = int(row[2]), int(row[4]), row[5]
                    if first_pts is None:
                        first_pts = pts
                    filename = f'frame-{len(entries):09d}.jpg'
                    file = export/filename
                    if file.stat().st_size != size:
                        raise OSError('Exported JPEG size differs from source packet')
                    entries.append(dict(file=export.name+'/'+filename, video_time_seconds=float((pts-first_pts)*time_base),
                                        pts=pts, bytes=size, sha256=digest))
                if not entries:
                    raise OSError('No frames could be extracted')
                playback = self.probe(folder/'video.mp4')
                if not playback['streams'][0].get('nb_frames'):
                    playback = self.probe(folder/'video.mp4',count=True)
                playback_count = int(playback['streams'][0].get('nb_frames') or playback['streams'][0].get('nb_read_packets',0))
                expected = original.get('capture_stats', {}).get('frame') or int(stream.get('nb_frames') or stream.get('nb_read_packets',0)) or None
                if mode=='all' and expected and len(entries)!=expected:
                    raise OSError(f'Frame count mismatch: archive reports {expected}, export has {len(entries)}')
                if mode=='all' and playback_count and len(entries)!=playback_count:
                    raise OSError(f'Playback count mismatch: {playback_count} video frames versus {len(entries)} JPEGs')
                index = dict(fps=fps, mode=mode, time_base=str(time_base), source=source.name,
                             source_codec=stream['codec_name'], packet_copy=mode=='all' and native,
                             timing='Original exported frame presentation timestamps; no frame interpolation.', frames=entries)
                save(frames/'index.json', index)
                # Hash large archives outside the station lock so live status and RF sampling stay responsive.
                archive_meta = self.hash_file(source)
                playback_meta = self.hash_file(folder/'video.mp4') if source.name!='video.mp4' else archive_meta
                with self.station.lock:
                    manifest = load(folder/'manifest.json', {})
                    manifest.setdefault('files', {})[source.name] = archive_meta
                    manifest['files']['video.mp4'] = playback_meta
                    manifest.setdefault('video_playback',{}).update(state='completed', file='video.mp4', frame_count=playback_count,
                                                      avg_frame_rate=playback['streams'][0]['avg_frame_rate'])
                    manifest['frame_integrity'] = dict(source_frames=expected, exported_frames=len(entries),
                                                      playback_frames=playback_count, packet_copy=index['packet_copy'],
                                                      every_recorded_frame=(mode=='all'))
                    save(folder/'manifest.json', manifest)
                self.update_frames(sid, dict(state='completed', fps=fps, mode=mode, count=len(entries), completed_at=utc()), frames/'index.json')
                self.cleanup_buffer_segments(folder)
            except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
                if proc and proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                try:
                    self.update_frames(sid, dict(state='waiting_storage' if isinstance(error,StorageWait) else 'queued' if self.station.exiting.is_set() or not self.storage()['available'] else 'failed', fps=fps, mode=mode, count=0, error=str(error)))
                except OSError:
                    pass
            finally:
                self.pending.discard(sid)
                setattr(self,'large_processing' if large else 'processing',None)
                setattr(self,'large_processing_proc' if large else 'processing_proc',None)
                self.io_paused.clear()
                jobs.task_done()

    def shutdown(self):
        if self.audio:
            self.audio.terminate()
            try:
                self.audio.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.audio.kill()
        self.playback_worker.join(timeout=8)
        self.assembly_worker.join(timeout=8)
        self.worker.join(timeout=8)
        self.large_worker.join(timeout=8)
        self.large_assembly_worker.join(timeout=8)
        self.large_playback_worker.join(timeout=8)

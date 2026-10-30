#!/usr/bin/env python3
"""Pi experiment station. Standard library only; FFmpeg owns the camera."""
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, unquote, parse_qs
from experiments import Experiments, save
from rf_trigger import RFTrigger
from motion_trigger import MotionTrigger
from object_analysis import ObjectAnalysis
from boxed_review import BoxedReview
from review_video import ReviewVideo
from training_control import TrainingControl
from lab_capture import LabCapture
from rolling_buffer import RollingBuffer
from youtube_archive import YouTubeArchive
from stills_archive import StillsArchive
from internet_archive import InternetArchive

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('CAPTURE_DATA', str(ROOT / 'sessions')))
VOLUME = os.environ.get('CAPTURE_VOLUME')
VOLUME_ID = os.environ.get('CAPTURE_VOLUME_ID', '')
RUN = ROOT / 'run'
PREVIEW = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')) / 'field-station' / 'preview.jpg'
LIVE = Path(os.environ.get('RF_LIVE_PATH','/home/hackrf/signal-spool/live.json'))
DEVICE = os.environ.get('CAPTURE_DEVICE', '/dev/v4l/by-id/usb-Elgato_Cam_Link_4K_A29YB624333H9X-video-index0')
FFMPEG = os.environ.get('FFMPEG', str(ROOT / 'vendor/root/usr/bin/ffmpeg'))
ENV = dict(os.environ, LD_LIBRARY_PATH=str(ROOT / 'vendor/root/usr/lib/aarch64-linux-gnu') + ':' + str(ROOT / 'vendor/root/usr/lib/aarch64-linux-gnu/lapack'))
TOKEN = secrets.token_urlsafe(32)

def utc():
    return datetime.now(timezone.utc).isoformat()

def read_json(path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default

def write_json(path, value):
    save(path, value)

def command(args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=5)
        return p.stdout.strip() or p.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return str(e)

def storage_status():
    try:
        if VOLUME:
            volume = Path(VOLUME)
            if not volume.is_mount() or (VOLUME_ID and (volume / '.field-station-volume').read_text().strip() != VOLUME_ID):
                raise OSError('Samsung T7 is not mounted at the configured path')
            if not DATA.resolve().is_relative_to(volume.resolve()):
                raise OSError('Capture directory is outside the configured drive')
        disk = shutil.disk_usage(DATA)
        return dict(available=True, free=disk.free, total=disk.total, path=str(DATA), volume=VOLUME, error=None)
    except OSError as e:
        return dict(available=False, free=0, total=0, path=str(DATA), volume=VOLUME, error=str(e))

class Station:
    def __init__(self):
        if not VOLUME:
            DATA.mkdir(exist_ok=True)
        RUN.mkdir(exist_ok=True)
        PREVIEW.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.active = None
        self.proc = None
        self.log = None
        self.last_rf = None
        self.services = {}
        self.upload_journal = ''
        self.exiting = threading.Event()
        self.camera_error = None
        self.next_retry = 0
        self.storage_was_available = storage_status()['available']
        self.rf_history=deque(maxlen=90)
        self.rf_history_stamp=None
        pre=read_json(RUN/'motion-trigger.json',{}).get('pre_roll_seconds',10)
        self.buffer=RollingBuffer(RUN,self.exiting,keep_seconds=pre+8)
        self.recover_sessions()
        self.experiments = Experiments(self, ROOT, DATA, RUN, FFMPEG, ENV, storage_status)
        self.rf_trigger = RFTrigger(self, RUN)
        self.motion_trigger = MotionTrigger(self, RUN, PREVIEW)
        self.classifier = ObjectAnalysis(self,ROOT)
        self.boxed_review = BoxedReview(self,DATA)
        self.review_video = ReviewVideo(self,ROOT,ENV)
        self.model_training = TrainingControl(ROOT,DATA)
        self.youtube=YouTubeArchive(self,ROOT,DATA,storage_status,start=False)
        self.internet_archive=InternetArchive(self,ROOT,DATA,storage_status,start=False)
        self.stills=StillsArchive(self,ROOT,DATA)
        self.youtube.worker.start()
        self.internet_archive.worker.start()

    @staticmethod
    def data_path(sid):
        return DATA/sid

    def recover_sessions(self):
        if not storage_status()['available']:
            return
        for path in DATA.glob('*/manifest.json'):
            m = read_json(path, {})
            interrupted = m.get('state') in ('recording', 'finalizing')
            partial = m.get('state')=='interrupted' and m.get('frames',{}).get('state') in (None,'skipped')
            if interrupted or partial:
                m.update(state='interrupted', trial_valid=False,
                         stopped_at=m.get('stopped_at') or utc(),
                         stop_reason=m.get('stop_reason') or 'Station restarted; partial recording retained')
                archive = path.parent/'video.mkv'
                buffered=read_json(path.parent/'buffer-state.json',{})
                if (archive.is_file() and archive.stat().st_size) or buffered.get('segments'):
                    m['frames']=dict(state='queued',fps=m.get('frame_fps',m.get('video_fps',60)),
                                     mode=m.get('frame_export_mode','all'),count=0)
                    m['video_playback']=dict(state='queued',file='video.mp4')
                    m['recovery']=dict(state='partial_archive_queued',detected_at=utc(),
                        note='Recover available frames; recording remains an interrupted trial.')
                    # A power loss may leave fewer packets than the last progress update.
                    m.pop('capture_stats',None)
                write_json(path, m)

    def spawn_camera(self, record=None):
        if not storage_status()['available'] or storage_status()['free']<self.experiments.storage_reserve():raise ValueError('Capture paused: recording volume unavailable or storage reserve reached; unprocessed evidence retained')
        self.camera_error = None
        self.log = (RUN / 'camera.log').open('w')
        rate = self.active['video_fps'] if record else self.experiments.auto['video_fps']
        self.camera_rate=rate
        from camera_backend import camera_input
        measured=bool(os.environ.get('CAPTURE_FFMPEG'))
        args = [os.environ.get('CAPTURE_FFMPEG',FFMPEG), '-hide_banner', '-loglevel', 'info' if measured else 'warning', '-nostats', '-y'] + camera_input(DEVICE, rate)
        buffer_path=self.buffer.new_run()
        from camera_backend import camera_encoder
        codec = camera_encoder(rate)
        if measured:
            if '-vf' in codec:
                i=codec.index('-vf')+1;codec[i]='showinfo=checksum=0,'+codec[i]
            else:codec=['-vf','showinfo=checksum=0']+codec
        args += ['-map','0:v:0'] + codec + ['-fps_mode','passthrough',
                 '-f','segment','-segment_time','1','-reset_timestamps','1',
                 '-segment_list',str(buffer_path/'segments.csv'),'-segment_list_type','csv',
                 '-segment_list_size','0' if self.buffer.durable else '128','-segment_list_flags','+live',
                 str(buffer_path/'segment-%09d.mkv')]
        # Copy JPEG packets into RAM for preview: no real-time decoding/re-encoding.
        preview_codec = ['-vf','fps=5','-c:v','mjpeg','-q:v','3','-threads','1'] if os.environ.get('CAPTURE_BACKEND')=='avfoundation' else ['-c:v','copy']
        args += ['-map', '0:v:0'] + preview_codec + ['-fps_mode', 'passthrough',
                 '-f', 'image2', '-update', '1', '-atomic_writing', '1', str(PREVIEW)]
        try:
            self.proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE if measured else self.log, env=ENV)
            if measured:
                from capture_health import CaptureHealth,drain_camera_log
                self.capture_health=CaptureHealth(buffer_path)
                self.camera_log_thread=threading.Thread(target=drain_camera_log,args=(self.proc.stderr,self.log,self.capture_health),daemon=True)
                self.camera_log_thread.start()
        except OSError as e:
            self.camera_error = str(e)
            self.log.close()
            self.proc = None

    def stop_camera(self):
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGINT)
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        if getattr(self,'camera_log_thread',None):self.camera_log_thread.join(timeout=3)
        if self.buffer.durable and self.buffer.path:
            self.buffer.ingest();write_json(self.buffer.path/'closed.json',dict(closed_epoch=time.time()))
        if self.log:
            self.log.close()
        code = self.proc.returncode if self.proc else None
        self.proc = None
        return code

    def start(self, body, automatic=False, trigger_event=None, motion_event=None, validation=False):
        with self.lock:
            if not automatic and not trigger_event and not motion_event and not validation and self.experiments.auto['enabled']:
                raise ValueError('Disable automatic capture before starting a manual session.')
            if self.active:
                raise ValueError('A session is already recording.')
            if not self.experiments.readrate and (self.experiments.processing or self.experiments.pending) and not trigger_event and not motion_event and not validation and not automatic:
                raise ValueError('Frame export is using the SSD. Wait for it to finish before recording.')
            storage = storage_status()
            if not storage['available']:
                raise ValueError('Recording drive unavailable. Mount the Samsung T7 before starting a session.')
            if storage['free'] < self.experiments.storage_reserve():
                raise ValueError('Storage reserve reached; waiting for verified uploads to free space.')
            self.experiments.require_rf()
            if not self.proc or self.proc.poll() is not None or self.preview_age() > 5:
                raise ValueError('Camera is not delivering fresh frames. Check power and HDMI.')
            title = str(body.get('title', '')).strip()[:120] or 'Untitled observation'
            condition = body.get('condition', 'silence')
            if condition not in ('silence', 'ce5', 'control', 'other'):
                raise ValueError('Unknown experiment condition.')
            try:
                duration = int(body.get('minutes', self.experiments.auto['duration_minutes']))
            except (ValueError, TypeError):
                raise ValueError('Duration must be a whole number of minutes.')
            if not 1 <= duration <= 120:
                raise ValueError('Duration must be between 1 and 120 minutes.')
            capture_settings = (self.experiments.auto.get('cycle_settings') or self.experiments.auto) if automatic else self.experiments.auto
            if getattr(self,'camera_rate',capture_settings['video_fps'])!=capture_settings['video_fps']:
                self.stop_camera()
                self.spawn_camera()
                raise ValueError('Camera frame rate is changing; wait for the buffer to warm up.')
            if not self.buffer.status()['ready']:
                raise ValueError('Camera buffer is warming up; retry shortly.')
            sid = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + secrets.token_hex(3)
            folder = DATA / sid
            folder.mkdir()
            m = dict(id=sid, title=title, condition=condition, notes=str(body.get('notes', ''))[:5000],
                     state='recording', started_at=utc(), started_epoch=time.time(), started_monotonic=time.monotonic(),
                     duration_limit_seconds=duration * 60, rf_records=0, markers=[], frame_fps=capture_settings['frame_fps'],
                     video_fps=capture_settings['video_fps'], frame_export_mode=capture_settings['frame_export_mode'],
                     video=f'1920x1080 / {capture_settings["video_fps"]} fps requested / {os.environ.get("CAPTURE_ENCODER", "original MJPEG stream")} / no audio',
                     video_archive='video.mkv', video_playback=dict(state='queued', file='video.mp4'),
                     rf_source=os.environ.get('RF_SOURCE','OpenWebRX FFT live snapshots, approximately 1 second; no raw IQ'),
                     timing='Host UTC and monotonic timestamps. HDMI latency is uncalibrated; not frame-synchronized.',
                     playback=dict(state='silent', description='Manual condition label; no station-controlled playback.'),
                     upload='Local only; video uploads are not configured')
            if validation:
                seconds=int(body.get('seconds',12))
                if not 5<=seconds<=30:raise ValueError('Validation capture must be 5–30 seconds')
                m.update(validation=True,duration_limit_seconds=seconds)
            m['buffered_capture']=True
            if motion_event:
                cfg=self.motion_trigger.config
                onset=motion_event.get('motion_started_epoch',motion_event['detected_epoch'])
                m.update(capture_mode='motion_window',pre_roll_seconds=cfg['pre_roll_seconds'],
                         post_roll_seconds=cfg['post_roll_seconds'],motion_onset_epoch=onset)
                requested_start=onset-cfg['pre_roll_seconds']
            else:
                requested_start=m['started_epoch']
            buffered=self.buffer.begin(folder,requested_start)
            actual=buffered['actual_start_epoch']
            m.update(started_epoch=actual,started_at=datetime.fromtimestamp(actual,timezone.utc).isoformat(),
                     started_monotonic=time.monotonic()-(time.time()-actual),
                     pre_roll_complete=buffered['prebuffer_complete'])
            if motion_event:
                m['duration_limit_seconds']=7200
                m['pre_roll_actual_seconds']=max(0,onset-actual)
            self.active = m
            m['capture_origin'] = 'rf_trigger' if trigger_event else 'motion_trigger' if motion_event else 'validation' if validation else 'scheduled' if automatic else 'manual'
            if trigger_event:
                m['trial_valid'] = True
                trigger_event.update(action='started_recording',session_id=sid)
                m['rf_trigger_events'] = [RFTrigger.summary(trigger_event)]
                m['playback']['description']='RF-triggered observation; no station-controlled audio stimulus requested.'
                save_events = folder/'rf-trigger-events.json'
                write_json(save_events,[trigger_event])
            self.last_rf = None
            if self.rf_history:
                with (folder/'rf.jsonl').open('a') as stream:
                    for frame in self.rf_history:
                        stamp=frame['timestamp']
                        if stamp>=actual:
                            stream.write(json.dumps(dict(captured_at=datetime.fromtimestamp(stamp,timezone.utc).isoformat(),
                                elapsed_seconds=stamp-actual,spectrum=frame))+'\n')
                            m['rf_records']+=1
                            self.last_rf=stamp
            write_json(folder / 'manifest.json', m)
            self.experiments.resume_exports()
            if automatic:
                try:
                    self.experiments.session_started(m)
                except (OSError, ValueError) as error:
                    m['trial_valid'] = False
                    self.stop('CE5 playback could not start')
                    raise ValueError(str(error))
                write_json(folder / 'manifest.json', m)
            return m.copy()

    def stop_requested(self,body):
        with self.lock:
            expected=body.get('expected_session_id')
            if expected and (not self.active or self.active['id']!=expected):raise ValueError('Session changed; refresh before stopping')
            return self.stop()

    def stop(self, reason='Manual stop'):
        with self.lock:
            if not self.active:
                raise ValueError('No session is recording.')
            m = self.active
            folder = DATA / m['id']
            m['state'] = 'finalizing'
            write_json(folder / 'manifest.json', m)
            buffered_capture=m.get('buffered_capture')
            if buffered_capture:
                requested_end=m.get('motion_end_epoch') or min(time.time(),m['started_epoch']+m['duration_limit_seconds'])
                buffer_state=self.buffer.finish(requested_end)
                code=0 if buffer_state['segments'] else 1
                if not buffer_state['tail_complete']:
                    m['trial_valid']=False
                m['buffer_tail_complete']=buffer_state['tail_complete']
                m['clip_end_epoch']=requested_end
            else:
                code = self.stop_camera()
            m.update(stopped_at=utc(), stopped_epoch=time.time(), elapsed_seconds=round(time.monotonic()-m['started_monotonic'], 3), stop_reason=reason)
            video = folder / 'video.mkv'
            progress = {}
            try:
                for line in (folder/'capture-progress.txt').read_text().splitlines():
                    if '=' in line:
                        k, v = line.split('=', 1)
                        progress[k] = v
            except OSError:
                pass
            m['capture_stats'] = {k: int(progress[k]) for k in ('frame', 'dup_frames', 'drop_frames') if progress.get(k, '').isdigit()}
            m['state'] = 'completed' if code in (0, 255) and (buffered_capture or (video.exists() and video.stat().st_size > 1024)) else 'failed'
            self.experiments.before_finalize(m, reason)
            shutil.copyfile(RUN / 'camera.log', folder / 'capture.log')
            m['files'] = {}
            for name in ('rf.jsonl', 'capture.log', 'capture-progress.txt', 'stimulus.wav', 'playback.log','rf-trigger-events.json','motion-events.json','buffer-state.json',*[f.name for f in folder.glob('motion-*.jpg')],*[f.name for f in folder.glob('motion-*.png')]):
                p = folder / name
                if p.exists():
                    digest = hashlib.sha256()
                    with p.open('rb') as f:
                        for chunk in iter(lambda: f.read(1024*1024), b''):
                            digest.update(chunk)
                    m['files'][name] = dict(bytes=p.stat().st_size, sha256=digest.hexdigest())
            if video.exists():
                m['files']['video.mkv'] = dict(bytes=video.stat().st_size, sha256=None, integrity='queued')
            write_json(folder / 'manifest.json', m)
            self.active = None
            self.experiments.resume_exports()
            if m.get('capture_origin') in ('rf_trigger','motion_trigger'):
                until=m['stopped_epoch']+self.experiments.auto['gap_minutes']*60
                self.experiments.auto['next_cycle_epoch']=max(self.experiments.auto['next_cycle_epoch'],until)
                if self.experiments.auto.get('next_session_epoch'):
                    self.experiments.auto['next_session_epoch']=max(self.experiments.auto['next_session_epoch'],until)
                write_json(self.experiments.config,self.experiments.auto)
            if m['state']=='completed':
                self.experiments.queue_frames(m['id'])
            if m.get('capture_mode')!='motion_window' and reason=='Automatic stop: duration reached':
                self.motion_trigger.handoff(m)
            if not buffered_capture and not self.exiting.is_set():
                self.spawn_camera()
            return m.copy()

    def mark(self, body):
        with self.lock:
            if not self.active:
                raise ValueError('Start a session before adding markers.')
            marker = dict(timestamp=utc(), elapsed_seconds=round(time.monotonic()-self.active['started_monotonic'], 3),
                          note=str(body.get('note', '')).strip()[:1000] or 'Observer event')
            self.active['markers'].append(marker)
            write_json(DATA / self.active['id'] / 'manifest.json', self.active)
            return marker

    def preview_age(self):
        try:
            return max(0, time.time() - PREVIEW.stat().st_mtime)
        except OSError:
            return 999999

    def monitor(self):
        next_services = 0
        next_export_recovery = 0
        while not self.exiting.wait(0.25):
            try:
                with self.lock:
                    available = storage_status()['available']
                    if available and not self.storage_was_available:
                        self.recover_sessions()
                        self.experiments.resume_pending()
                    if available and time.monotonic()>next_export_recovery:
                        self.experiments.resume_pending()
                        next_export_recovery=time.monotonic()+30
                    self.storage_was_available = available
                    if self.active and not available:
                        self.stop_camera()
                        self.buffer.abandon()
                        m = self.active
                        m.update(state='interrupted', stopped_at=utc(), stop_reason='Recording drive disconnected or unavailable')
                        self.experiments.before_finalize(m, m['stop_reason'])
                        write_json(RUN / ('interrupted-' + m['id'] + '.json'), m)
                        self.active = None
                        self.experiments.resume_exports()
                        self.spawn_camera()
                    if self.proc and available and storage_status()['free']<self.experiments.storage_reserve():
                        if self.active:self.stop('Storage reserve reached; evidence retained')
                        self.stop_camera();self.camera_error='Capture paused: storage reserve reached; evidence retained';self.next_retry=time.monotonic()+10
                    if self.proc and self.proc.poll() is not None:
                        self.camera_error = (RUN / 'camera.log').read_text()[-1500:]
                        if self.active:
                            self.stop('Camera process exited')
                        else:
                            self.stop_camera()
                        self.next_retry = time.monotonic() + 10
                    if not self.proc and time.monotonic() > self.next_retry:
                        self.spawn_camera()
                        self.next_retry = time.monotonic()+10
                    frame = read_json(LIVE, {})
                    stamp=frame.get('timestamp')
                    if stamp and stamp!=self.rf_history_stamp and abs(time.time()-stamp)<5:
                        self.rf_history.append(frame)
                        self.rf_history_stamp=stamp
                    if self.active:
                        m = self.active
                        frame = read_json(LIVE, {})
                        stamp = frame.get('timestamp')
                        if stamp and stamp != self.last_rf and abs(time.time()-stamp) < 5:
                            record = dict(captured_at=utc(), elapsed_seconds=time.monotonic()-m['started_monotonic'], spectrum=frame)
                            with (DATA / m['id'] / 'rf.jsonl').open('a') as f:
                                f.write(json.dumps(record)+'\n')
                            self.last_rf = stamp
                            m['rf_records'] += 1
                            write_json(DATA / m['id'] / 'manifest.json', m)
                        if storage_status()['free'] < self.experiments.storage_reserve():
                            self.stop('Automatic stop: storage reserve reached')
                        elif m.get('capture_mode')=='motion_window':
                            end=self.motion_trigger.recording_end(m)
                            m['motion_last_seen_epoch']=max(m['motion_onset_epoch'],self.motion_trigger.last_motion_epoch or 0)
                            m['motion_end_epoch']=end
                            m['motion_tail_remaining_seconds']=max(0,end-time.time())
                            m['duration_limit_seconds']=min(7200,end-m['started_epoch'])
                            if time.time()>=end:
                                self.stop('Motion ended: post-roll complete')
                            elif time.time()-m['started_epoch'] >= (60 if m.get('provisional') else 7200):
                                self.stop('Motion capture safety limit reached')
                        elif time.monotonic()-m['started_monotonic'] >= m['duration_limit_seconds']:
                            self.stop('Automatic stop: duration reached')
                    self.rf_trigger.tick(read_json(LIVE,{}))
                    self.motion_trigger.tick()
                    self.experiments.tick()
                if time.monotonic() > next_services:
                    self.services = {name: self.service(name) for name in (
                        'hackrf-signal-logger.service', 'hackrf-signal-publish.timer', 'hackrf-signal-publish.service', 'openwebrx.service', 'field-station-recovery.timer')}
                    self.services['clock'] = command(['timedatectl', 'show', '-p', 'NTPSynchronized', '--value'])
                    self.services['autostart_linger'] = command(['loginctl', 'show-user', str(os.getuid()), '-p', 'Linger', '--value'])
                    self.upload_journal = command(['journalctl', '-u', 'hackrf-signal-publish.service', '-n', '12', '--no-pager', '-o', 'short-iso'])
                    next_services = time.monotonic()+10
            except OSError as error:
                # A USB disconnect may happen between the mount check and a write.
                with self.lock:
                    self.stop_camera()
                    self.buffer.abandon()
                    if self.active:
                        m = self.active
                        m.update(state='interrupted', stopped_at=utc(), stop_reason='Storage I/O failure: ' + str(error))
                        self.experiments.before_finalize(m, m['stop_reason'])
                        write_json(RUN / ('interrupted-' + m['id'] + '.json'), m)
                        self.active = None
                        self.experiments.resume_exports()
                    self.storage_was_available = False
                    self.next_retry = time.monotonic() + 2

    @staticmethod
    def service(name):
        out = command(['systemctl', 'show', name, '--no-pager', '-p', 'ActiveState', '-p', 'SubState', '-p', 'Result',
                       '-p', 'NextElapseUSecRealtime', '-p', 'ExecMainStatus', '-p', 'ExecMainExitTimestamp'])
        return dict(line.split('=', 1) for line in out.splitlines() if '=' in line)

    def status(self):
        with self.lock:
            sessions = [m for p in sorted(DATA.glob('*/manifest.json'), reverse=True) if (m := read_json(p))]
            known={m['id'] for m in sessions}
            sessions += [m for p in self.youtube.catalog.glob('*.json') if (m:=read_json(p)) and m.get('id') not in known]
            sessions.sort(key=lambda m:m.get('started_epoch',0),reverse=True)
            live = read_json(LIVE, {})
            age = time.time()-live.get('timestamp', 0)
            return dict(now=utc(), csrf=TOKEN, active=self.active, sessions=sessions, services=self.services,
                        camera=dict(capture_fps=self.capture_health.snapshot()['measured_fps'] if getattr(self,'capture_health',None) else None, requested_fps=getattr(self,'camera_rate',self.experiments.auto['video_fps']), measurements=self.capture_health.snapshot() if getattr(self,'capture_health',None) else {}, connected=(self.preview_age()<5 if os.environ.get('CAPTURE_BACKEND')=='avfoundation' else Path(DEVICE).exists()), fresh=self.preview_age()<5, age_seconds=self.preview_age(),
                                    error=self.camera_error, device=DEVICE),
                        rf=dict(fresh=age<5, age_seconds=max(0, age), frame=live),
                        storage=storage_status(),
                        experiments=self.experiments.status(),
                        object_analysis=self.classifier.status(), rf_trigger=self.rf_trigger.status(), motion_trigger=self.motion_trigger.status(), rolling_buffer=self.buffer.status(),
                        youtube_live=read_json(RUN/'youtube-live.json',{}),upload_journal=self.upload_journal,youtube=self.youtube.status(),stills=self.stills.status(),internet_archive=self.internet_archive.status())

STATION = None

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        if not self.path.startswith(('/api/status', '/preview.jpg', '/preview.mjpeg')):
            super().log_message(fmt, *args)

    def send(self, code, data, kind='application/json'):
        if not isinstance(data, bytes):
            data = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.end_headers()
        self.wfile.write(data)

    def live_preview(self):
        rate=parse_qs(urlsplit(self.path).query).get('fps',['30'])[0]
        if rate not in ('2','15','30','60'):
            return self.send(400,{'error':'Preview FPS must be 2, 15, 30 or 60'})
        if STATION.preview_age()>5:
            return self.send(503,{'error':'No fresh camera frame'})
        interval=1/int(rate)
        self.close_connection=True
        self.connection.settimeout(5)
        self.send_response(200)
        self.send_header('Content-Type','multipart/x-mixed-replace; boundary=camera-frame')
        self.send_header('Cache-Control','no-store, no-cache, must-revalidate')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Accel-Buffering','no')
        self.send_header('Connection','close')
        self.end_headers()
        previous=None
        try:
            while not STATION.exiting.is_set():
                started=time.monotonic()
                # Open the atomically replaced file once so metadata and bytes
                # describe the same complete JPEG. Slow clients skip old frames.
                with PREVIEW.open('rb') as source:
                    stamp=os.fstat(source.fileno()).st_mtime_ns
                    if time.time()-stamp/1e9>5:
                        return
                    if stamp!=previous:
                        frame=source.read()
                    else:
                        frame=None
                if frame:
                    header=f'--camera-frame\r\nContent-Type: image/jpeg\r\nContent-Length: {len(frame)}\r\n\r\n'.encode()
                    self.wfile.write(header)
                    self.wfile.write(frame)
                    self.wfile.write(b'\r\n')
                    self.wfile.flush()
                    previous=stamp
                STATION.exiting.wait(max(0,interval-(time.monotonic()-started)))
        except OSError:
            return # Disconnected viewer, camera restart, or slow connection.

    def do_GET(self):
        try:
            path = unquote(urlsplit(self.path).path)
            if path == '/api/model-training/status':
                return self.send(200,dict(**STATION.model_training.status(),csrf=TOKEN))
            if path == '/api/session':
                with STATION.lock:
                    active=STATION.active
                    return self.send(200,dict(csrf=TOKEN,active=None if not active else {k:active.get(k) for k in ('id','state','started_epoch','capture_origin','rf_records','duration_limit_seconds')},triggers=dict(motion=STATION.motion_trigger.config['enabled'],rf=STATION.rf_trigger.config['enabled'],scheduled=STATION.experiments.auto['enabled'])))
            if path == '/api/status':
                return self.send(200, STATION.status())
            if path.startswith('/api/boxed-review/'):
                query=parse_qs(urlsplit(self.path).query)
                key=query.get('key',[''])[0]
                if path=='/api/boxed-review/list':return self.send(200,dict(**STATION.boxed_review.listing(query),csrf=TOKEN))
                if path=='/api/boxed-review/video-status':return self.send(200,STATION.boxed_review.video_info(key))
                if path=='/api/boxed-review/detail':return self.send(200,dict(**STATION.boxed_review.detail(key),csrf=TOKEN))
                if path=='/api/boxed-review/crop':
                    native=query.get('native')==['1']
                    return self.send(200,STATION.boxed_review.crop_image(key,int(query.get('target',['0'])[0]),native).read_bytes(),'image/png' if native else 'image/jpeg')
                if path=='/api/boxed-review/image':return self.send(200,STATION.boxed_review.image(key,query.get('original')==['1']).read_bytes(),'image/jpeg')
                if path=='/api/boxed-review/export':return self.send(200,STATION.boxed_review.export_training(),'application/zip')
                return self.send(404,{'error':'Not found'})
            if path == '/api/motion-overlay':
                return self.send(200, STATION.motion_trigger.overlay())
            if path == '/api/tone/library':
                return self.send(200, STATION.experiments.library())
            if path == '/preview.mjpeg':
                return self.live_preview()
            if path == '/preview.jpg':
                if STATION.preview_age() > 5:
                    return self.send(503, {'error': 'No fresh camera frame'})
                return self.send(200, PREVIEW.read_bytes(), 'image/jpeg')
            if path.startswith('/sessions/'):
                parts = path.strip('/').split('/')
                valid_id = len(parts)>=3 and re.fullmatch(r'[0-9TZ]+-[a-f0-9]{6}', parts[1])
                normal = len(parts)==3 and (bool(re.fullmatch(r"(?:motion-[0-9a-f]{16}-(before|after|boxed)\.jpg|review-[0-9a-f]{16}\.mp4)",parts[2])) or parts[2] in ('manifest.json', 'video.mp4', 'video.mkv', 'capture-progress.txt', 'rf.jsonl', 'capture.log', 'stimulus.wav', 'playback.log', 'frames.log','rf-trigger-events.json','motion-events.json','buffer-state.json','assembly.log'))
                frame = len(parts)==4 and parts[2]=='frames' and (parts[3]=='index.json' or re.fullmatch(r'(?:second-[0-9]{6}|frame-[0-9]{9})\.jpg', parts[3]))
                frame = frame or (len(parts)==5 and parts[2]=='frames' and re.fullmatch(r'export-[a-f0-9]{10}', parts[3]) and re.fullmatch(r'frame-[0-9]{9}\.jpg', parts[4]))
                if not valid_id or not (normal or frame):
                    return self.send(404, {'error': 'Not found'})
                file = DATA.joinpath(*parts[1:])
                if parts[2]=='manifest.json' and not file.exists():
                    file=STATION.youtube.catalog/(parts[1]+'.json')
            else:
                file = ROOT / 'static' / {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css', '/boxed-review': 'boxed-review.html', '/boxed-review.js': 'boxed-review.js', '/boxed-review.css': 'boxed-review.css'}.get(path, '__missing__')
            if not file.is_file():
                return self.send(404, {'error': 'Not found'})
            size = file.stat().st_size
            start, end = 0, size-1
            requested = self.headers.get('Range')
            if requested:
                match = re.fullmatch(r'bytes=(\d+)-(\d*)', requested)
                if not match:
                    return self.send(416, {'error': 'Unsupported range'})
                start = int(match[1])
                end = min(int(match[2]) if match[2] else end, end)
                if start > end:
                    return self.send(416, {'error': 'Invalid range'})
            self.send_response(206 if requested else 200)
            self.send_header('Content-Type', mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Length', str(end-start+1))
            self.send_header('X-Content-Type-Options', 'nosniff')
            if requested:
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.end_headers()
            with file.open('rb') as f:
                f.seek(start)
                remaining = end-start+1
                while remaining:
                    block = f.read(min(256*1024, remaining))
                    if not block:
                        break
                    self.wfile.write(block)
                    remaining -= len(block)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (ValueError,TypeError) as error:
            return self.send(400,{'error':str(error)})
        except OSError as error:
            return self.send(500,{'error':str(error)})

    def do_POST(self):
        if self.headers.get('X-Station-Token') != TOKEN:
            return self.send(403, {'error': 'Refresh the dashboard before controlling capture.'})
        origin = self.headers.get('Origin')
        if origin and urlsplit(origin).netloc != self.headers.get('Host'):
            return self.send(403, {'error': 'Cross-origin control is not allowed.'})
        try:
            length = int(self.headers.get('Content-Length', 0))
            if self.path == '/api/tone':
                if not 1 <= length <= 100*1024**2:
                    return self.send(413, {'error': 'Audio upload must be between 1 byte and 100 MB.'})
                if not storage_status()['available']:
                    raise ValueError('Mount the T7 before uploading audio.')
                with STATION.lock:
                    if STATION.active or STATION.experiments.auto['enabled']:
                        raise ValueError('Stop capture before changing CE5 audio.')
                    STATION.experiments.assets.mkdir(exist_ok=True)
                    temporary = STATION.experiments.assets / ('upload-'+secrets.token_hex(6)+'.tmp')
                    try:
                        remaining = length
                        with temporary.open('wb') as out:
                            while remaining:
                                block = self.rfile.read(min(1024*1024, remaining))
                                if not block:
                                    raise ValueError('Upload was interrupted')
                                out.write(block)
                                remaining -= len(block)
                        result = STATION.experiments.upload(temporary, unquote(self.headers.get('X-Audio-Name', 'CE5 audio')))
                    finally:
                        temporary.unlink(missing_ok=True)
                return self.send(200, result)
            if not 0 <= length <= 16384:
                return self.send(413, {'error': 'Request too large'})
            body = json.loads(self.rfile.read(length) or b'{}')
            if not isinstance(body, dict):
                raise ValueError('Expected an object')
            if self.path == '/api/provisional/manual':
                from provisional_capture import ProvisionalCapture
                return self.send(200,ProvisionalCapture(STATION).manual(body))
            if self.path == '/api/provisional/detection':
                from provisional_capture import ProvisionalCapture
                return self.send(200,ProvisionalCapture(STATION).receive(body))
            action = {'/api/start': STATION.start, '/api/stop': STATION.stop_requested, '/api/mark': STATION.mark,
                      '/api/automatic/enable': STATION.experiments.enable, '/api/automatic/disable': STATION.experiments.disable,
                      '/api/automatic/configure': STATION.experiments.configure,
                      '/api/rf-trigger/configure': STATION.rf_trigger.configure,
                      '/api/motion-trigger/configure': STATION.motion_trigger.configure,
                      '/api/motion/annotate': STATION.motion_trigger.annotate_event,
                      '/api/motion/classify': STATION.classifier.request,
                      '/api/boxed-review/save': STATION.boxed_review.save_review,
                      '/api/boxed-review/video': STATION.review_video.request,
                      '/api/model-training/start': STATION.model_training.start,
                      '/api/model-training/configure': STATION.model_training.configure,
                      '/api/motion/target': STATION.motion_trigger.select_target,
                      '/api/lab/detection': STATION.lab_capture.receive,
                      '/api/archive/configure': STATION.internet_archive.configure,
                      '/api/youtube/configure': STATION.youtube.configure,
                      '/api/youtube/client': STATION.youtube.configure_client,
                      '/api/youtube/import': STATION.youtube.import_credentials,
                      '/api/youtube/connect': STATION.youtube.connect,
                      '/api/youtube/retry': STATION.youtube.retry,
                      '/api/capture/validation': lambda b: STATION.start(dict(title='Pipeline validation · '+utc(),condition='control',minutes=1,seconds=b.get('seconds',12),notes='Camera/RF upload pipeline validation; no sighting is asserted.'),validation=True),
                      '/api/playback/prepare': lambda b: STATION.experiments.queue_playback(str(b.get('id','')),priority=0) or {'state':'queued'},
                      '/api/frames/retry': STATION.experiments.retry, '/api/audio/test': STATION.experiments.test_audio}.get(self.path)
            if self.path == '/api/tone/select':
                action = STATION.experiments.select
            if not action:
                return self.send(404, {'error': 'Not found'})
            return self.send(200, action(body))
        except (ValueError, TypeError) as e:
            return self.send(400, {'error': str(e)})
        except OSError as e:
            return self.send(500, {'error': str(e)})
        except subprocess.TimeoutExpired:
            return self.send(400, {'error': 'Audio processing timed out. Check the file and selected speaker.'})

def main():
    global STATION
    STATION = Station()
    STATION.lab_capture = LabCapture(STATION, PREVIEW)
    STATION.spawn_camera()
    threading.Thread(target=STATION.monitor, daemon=True).start()
    server = ThreadingHTTPServer((os.environ.get('CAPTURE_BIND', '0.0.0.0'), int(os.environ.get('CAPTURE_PORT', '8090'))), Handler)
    def shutdown(*_):
        STATION.exiting.set()
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    print('Experiment station listening on port 8090', flush=True)
    try:
        server.serve_forever()
    finally:
        STATION.exiting.set()
        with STATION.lock:
            if STATION.active:
                STATION.stop('Station shutting down')
            STATION.stop_camera()
        STATION.internet_archive.shutdown()
        STATION.stills.shutdown()
        STATION.youtube.shutdown()
        STATION.experiments.shutdown()
        server.server_close()

if __name__ == '__main__':
    main()

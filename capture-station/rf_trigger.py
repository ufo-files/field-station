"""Fresh-snapshot, sustained RF trigger with hysteresis and persistent controls."""
import math
import statistics
from collections import deque
from pathlib import Path
import secrets
import time
from experiments import load, save, utc


class RFTrigger:
    def __init__(self, station, run):
        self.station = station
        self.path = run/'rf-trigger.json'
        self.config = dict(enabled=False, threshold_db=20.0, confirm_snapshots=2,
                           duration_minutes=3, cooldown_minutes=10, min_bandwidth_khz=100,
                           hysteresis_db=5.0, quiet_snapshots=3, temporal_threshold_db=10.0,
                           broadband_rise_db=10.0, baseline_samples=60, baseline_window=300, broadband_fraction=0.5,
                           max_delay_seconds=30)
        self.config.update(load(self.path, {}))
        self.last_stamp = None
        self.consecutive = 0
        self.quiet = 0
        self.latched = False
        self.last_fired = self.config.pop('last_fired_epoch', 0)
        self.phase = 'armed' if self.config['enabled'] else 'disabled'
        self.last_event = load(run/'rf-trigger-last-event.json')
        self.pending = load(run/'rf-trigger-pending.json')
        self.peak = None
        self.error = None
        self.history = deque(maxlen=self.config['baseline_window'])
        self.previous_candidate = None
        self.confirming_frames = []
        self.baseline_floor = None

    def status(self):
        return dict(**self.config, phase=self.phase, consecutive=self.consecutive,
                    last_event=self.summary(self.last_event), pending=self.summary(self.pending), latest_peak_db=self.peak,
                    cooldown_until_epoch=self.last_fired+self.config['cooldown_minutes']*60,
                    error=self.error, baseline_samples_collected=len(self.history),
                    baseline_ready=len(self.history)>=self.config['baseline_samples'],baseline_floor_db=self.baseline_floor, monitored_range_hz=[1590000000,1610000000])

    @staticmethod
    def summary(event):
        if not event:
            return None
        result={k:event[k] for k in ('id','detected_at','detected_epoch','action','session_id','reason') if k in event}
        result['detection']={k:v for k,v in event['detection'].items() if k!='baseline_bin_db'}
        return result

    def configure(self, body):
        with self.station.lock:
            values = self.config.copy()
            for key, low, high in (('threshold_db',1,100),('confirm_snapshots',1,30),
                    ('duration_minutes',1,120),('cooldown_minutes',0,1440),
                    ('min_bandwidth_khz',100,20000),('hysteresis_db',0,50),('quiet_snapshots',1,60),
                    ('temporal_threshold_db',1,100),('broadband_rise_db',1,100),
                    ('baseline_samples',10,600),('baseline_window',30,1800),('broadband_fraction',0.1,1),('max_delay_seconds',5,600)):
                raw = body.get(key, values[key])
                value = float(raw)
                if not math.isfinite(value) or not low<=value<=high:
                    raise ValueError(f'{key.replace("_"," ")} must be from {low} to {high}.')
                if key not in ('threshold_db','hysteresis_db','temporal_threshold_db','broadband_rise_db','broadband_fraction') and int(value)!=value:
                    raise ValueError(key.replace('_',' ')+' must be a whole number.')
                values[key] = value if key in ('threshold_db','hysteresis_db','temporal_threshold_db','broadband_rise_db','broadband_fraction') else int(value)
            if values['hysteresis_db']>=values['threshold_db']:
                raise ValueError('Rearm margin must be smaller than the detection threshold.')
            if values['baseline_window']<values['baseline_samples']:
                raise ValueError('Baseline window must contain at least the warm-up snapshot count.')
            if values['baseline_window']!=self.config['baseline_window']:
                self.history = deque(self.history,maxlen=values['baseline_window'])
            values['enabled'] = bool(body.get('enabled',values['enabled']))
            self.config = values
            save(self.path, dict(**values,last_fired_epoch=self.last_fired))
            self.consecutive = 0
            self.confirming_frames = []
            self.quiet = 0
            self.latched = False
            self.pending = None
            (self.path.parent/'rf-trigger-pending.json').unlink(missing_ok=True)
            self.error = None
            self.phase = 'armed' if values['enabled'] else 'disabled'
            return self.status()

    def candidate(self, frame, margin=0):
        powers = frame['maximum_db']
        baseline = [statistics.median(row[0][i] for row in self.history) for i in range(len(powers))]
        self.baseline_floor = statistics.median(row[1] for row in self.history)
        floor = frame['noise_floor_db']
        deltas = [value-reference for value,reference in zip(powers,baseline)]
        floor_rise = floor-self.baseline_floor
        fraction = sum(value>=self.config['broadband_rise_db']-margin for value in deltas)/len(deltas)
        context = dict(baseline_floor_db=self.baseline_floor, current_floor_db=floor,
                       floor_rise_db=floor_rise, baseline_bin_db=baseline,
                       baseline_snapshots=len(self.history), baseline_start_epoch=self.history[0][2],
                       baseline_end_epoch=self.history[-1][2])
        if floor_rise>=self.config['broadband_rise_db']-margin and fraction>=self.config['broadband_fraction']:
            return dict(kind='broadband_rise', low_hz=1590000000,high_hz=1610000000,
                        above_floor_db=max(powers)-floor,baseline_rise_db=floor_rise,
                        affected_fraction=fraction,**context)
        width = frame['bin_width_hz']
        groups = []
        group = []
        for i,value in enumerate(powers):
            if value-floor>=self.config['threshold_db']-margin and deltas[i]>=self.config['temporal_threshold_db']-margin:
                group.append(i)
            else:
                if group:groups.append(group)
                group=[]
        if group:groups.append(group)
        groups = [g for g in groups if len(g)*width>=self.config['min_bandwidth_khz']*1000]
        if not groups:
            return None
        group = max(groups,key=lambda g:max(powers[i]-floor for i in g))
        peak = max(group,key=lambda i:powers[i])
        return dict(kind='new_peak',low_hz=1590000000+group[0]*width,
                    high_hz=1590000000+(group[-1]+1)*width,
                    peak_hz=1590000000+peak*width+width/2,peak_db=powers[peak],
                    above_floor_db=powers[peak]-floor,baseline_rise_db=deltas[peak],**context)

    def dispatch(self, event):
        try:
            active = self.station.active
            if active:
                elapsed = time.monotonic()-active['started_monotonic']
                desired = min(7200, elapsed+self.config['duration_minutes']*60)
                active['duration_limit_seconds'] = max(active['duration_limit_seconds'], desired)
                if active.get('capture_mode')=='motion_window':
                    active['rf_required_until_epoch']=time.time()+self.config['duration_minutes']*60
                event.update(action='extended_existing_recording', session_id=active['id'],
                             video_until_elapsed_seconds=active['duration_limit_seconds'])
                event['active_condition']=active.get('condition')
                event['playback_state']=active.get('playback',{}).get('state')
                active.setdefault('rf_trigger_events',[]).append(self.summary(event))
                description = (f'RF trigger: broadband floor rose {event["detection"]["baseline_rise_db"]:.1f} dB'
                               if event['detection']['kind']=='broadband_rise' else
                               f'RF trigger: {event["detection"]["above_floor_db"]:.1f} dB above noise floor')
                active['markers'].append(dict(timestamp=event['detected_at'],elapsed_seconds=elapsed,
                    note=description))
                folder = self.station.data_path(active['id'])
                evidence=load(folder/'rf-trigger-events.json',[])
                evidence.append(event)
                save(folder/'rf-trigger-events.json',evidence)
                save(folder/'manifest.json', active)
            else:
                if not self.station.experiments.pause_exports():
                    raise ValueError('Waiting for frame export to pause safely')
                try:
                    session = self.station.start(dict(title='RF trigger · '+utc(), condition='silence',
                        minutes=self.config['duration_minutes'],notes='Triggered by confirmed RF detection. Original spectrum snapshot is retained.'), trigger_event=event)
                except (ValueError,OSError):
                    self.station.experiments.resume_exports()
                    raise
                event.update(action='started_recording',session_id=session['id'])
            self.last_event = event
            self.pending = None
            (self.path.parent/'rf-trigger-pending.json').unlink(missing_ok=True)
            self.error = None
            self.phase = 'recording'
        except (ValueError,OSError) as error:
            self.pending = event
            self.error = str(error)
            self.phase = 'waiting_for_capture'
            save(self.path.parent/'rf-trigger-pending.json',event)

    def tick(self, frame):
        if not self.config['enabled']:
            self.phase = 'disabled'
            return
        now = time.time()
        if self.pending:
            if now-self.pending['detected_epoch']>self.config['max_delay_seconds']:
                self.pending.update(action='missed_capture',reason=self.error or 'Capture could not start in time')
                self.last_event = self.pending
                save(self.path.parent/'rf-trigger-last-event.json',self.pending)
                self.pending = None
                (self.path.parent/'rf-trigger-pending.json').unlink(missing_ok=True)
                self.phase = 'missed_event'
                return
            self.dispatch(self.pending)
            if self.pending:
                return
        stamp = frame.get('timestamp',0)
        powers = frame.get('maximum_db',[])
        floor = frame.get('noise_floor_db')
        valid = (isinstance(stamp,(int,float)) and math.isfinite(stamp) and abs(now-stamp)<=5 and
                 frame.get('range_hz')==[1590000000,1610000000] and
                 isinstance(floor,(int,float)) and math.isfinite(floor) and
                 isinstance(powers,list) and len(powers)==200 and frame.get('bin_width_hz')==100000 and
                 all(isinstance(p,(int,float)) and math.isfinite(p) for p in powers))
        if not valid:
            self.consecutive = 0
            self.confirming_frames=[]
            self.previous_candidate = None
            self.phase = 'waiting_for_fresh_rf'
            return
        if stamp==self.last_stamp:
            return
        if self.last_stamp and (stamp-self.last_stamp>5 or stamp<self.last_stamp):
            self.history.clear()
            self.consecutive = 0
            self.confirming_frames=[]
            self.previous_candidate = None
        self.last_stamp = stamp
        self.peak = max(powers)-floor
        if len(self.history)<self.config['baseline_samples']:
            self.history.append((powers[:],floor,stamp))
            self.phase = 'learning_baseline'
            return
        candidate = self.candidate(frame)
        quiet = (self.candidate(frame,margin=self.config['hysteresis_db']) if self.latched else candidate) is None
        self.quiet = self.quiet+1 if quiet else 0
        if self.quiet>=self.config['quiet_snapshots']:
            self.latched = False
        if quiet:
            self.history.append((powers[:],floor,stamp))
        if self.latched or now<self.last_fired+self.config['cooldown_minutes']*60:
            self.consecutive = 0
            self.confirming_frames=[]
            self.previous_candidate = None
            self.phase = 'cooldown' if now<self.last_fired+self.config['cooldown_minutes']*60 else 'waiting_for_quiet'
            return
        if not candidate:
            self.consecutive = 0
            self.confirming_frames=[]
            self.previous_candidate = None
            self.phase = 'armed'
            return
        previous = self.previous_candidate
        if previous and (previous['kind']!=candidate['kind'] or
                max(previous['low_hz'],candidate['low_hz'])>=min(previous['high_hz'],candidate['high_hz'])):
            self.consecutive = 0
            self.confirming_frames=[]
        self.previous_candidate = candidate
        self.consecutive += 1
        self.confirming_frames.append(frame)
        self.phase = 'confirming_signal'
        if self.consecutive<self.config['confirm_snapshots']:
            return
        self.consecutive = 0
        self.latched = True
        self.last_fired = now
        save(self.path,dict(**self.config,last_fired_epoch=now))
        event = dict(id=secrets.token_hex(8),detected_at=utc(),detected_epoch=now,algorithm='per-bin-baseline-v1',
                     detection=candidate,spectrum=frame,confirmation_spectra=self.confirming_frames[:],settings=self.config.copy())
        self.confirming_frames=[]
        self.dispatch(event)

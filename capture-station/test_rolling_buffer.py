import hashlib
import json
import os
import csv
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from experiments import Experiments,save,load,StorageWait
from rolling_buffer import RollingBuffer
import server


class RollingBufferTests(TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.data=self.root/'sessions';self.data.mkdir();self.run=self.root/'run';self.run.mkdir()
        self.stop=threading.Event()
        self.ring=RollingBuffer(self.run,self.stop,keep_seconds=20,root=self.root/'ram')
        self.path=self.ring.new_run()
        self.station=SimpleNamespace(lock=threading.RLock(),active=None,exiting=self.stop)
        self.e=Experiments(self.station,self.root,self.data,self.run,server.FFMPEG,server.ENV,
            lambda:dict(available=True,free=10*1024**3),readrate=0)
    def tearDown(self):
        self.stop.set();self.e.shutdown();self.ring.worker.join(2);self.tmp.cleanup()
    def generate(self,seconds=12):
        subprocess.run([server.FFMPEG,'-hide_banner','-loglevel','error','-nostdin','-y',
            '-f','lavfi','-i','testsrc2=size=160x90:rate=60','-t',str(seconds),
            '-c:v','mjpeg','-q:v','2','-threads','1','-f','segment','-segment_time','1',
            '-reset_timestamps','1','-segment_list',str(self.path/'segments.csv'),
            '-segment_list_type','csv','-segment_list_size','128','-segment_list_flags','+live',
            str(self.path/'segment-%09d.mkv')],env=server.ENV,check=True)
        for name,start,end in csv.reader((self.path/"segments.csv").read_text().splitlines()):
            os.utime(self.path/Path(name).name,(1000+float(end),1000+float(end)))
        # Deterministic timeline for the fixture, independent of generation speed.
        with self.ring.lock:
            self.ring.segments=[];self.ring.anchor=1000
            self.ring.ingest()
    def test_buffer_trim_and_export_preserves_every_native_packet(self):
        self.generate()
        folder=self.data/'20261026T000000Z-abcdef';folder.mkdir()
        self.ring.begin(folder,1002.25);state=self.ring.finish(1007.75)
        self.assertTrue(state['tail_complete'])
        save(folder/'manifest.json',dict(id=folder.name,state='completed',buffered_capture=True,
            video_fps=60,frame_fps=60,frame_export_mode='all',frames=dict(state='queued',fps=60,mode='all')))
        self.e.queue_frames(folder.name)
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            m=load(folder/'manifest.json')
            if m['frames']['state'] in ('completed','failed','waiting_storage'):break
            time.sleep(.1)
        self.assertEqual(m['frames']['state'],'completed',m)
        self.assertEqual(m['frames']['count'],330,m)
        self.assertEqual(m['video_playback']['frame_count'],330)
        self.assertTrue(m['frame_integrity']['packet_copy'])
        index=load(folder/'frames/index.json')
        # Compare JPEG hashes to the corresponding original encoded packets.
        playlist=self.root/'all.txt';playlist.write_text('ffconcat version 1.0\n'+''.join("file '"+str(s)+"'\n" for s in sorted(self.path.glob('segment-*.mkv'))))
        out=subprocess.run([server.FFMPEG,'-v','error','-f','concat','-safe','0','-i',str(playlist),
            '-map','0:v:0','-c:v','copy','-f','framehash','-hash','sha256','-'],env=server.ENV,capture_output=True,text=True,check=True)
        original=[line.split(',')[-1].strip() for line in out.stdout.splitlines() if line and not line.startswith('#')]
        self.assertEqual([f['sha256'] for f in index['frames']],original[135:465])
        self.assertFalse(list((folder/'buffer-segments').glob('*.mkv')))
        self.assertTrue(load(folder/'buffer-state.json')['temporary_segments_removed'])
    def test_clock_sync_rebases_segments_before_recording(self):
        self.generate(3)
        with self.ring.lock:
            for segment in self.ring.segments:
                segment['start_epoch']-=600
                segment['end_epoch']-=600
            self.ring.anchor-=600
            self.ring.segments.pop()
            self.ring.ingest()
            self.assertAlmostEqual(self.ring.anchor,1000)
            folder=self.data/'clock-sync';folder.mkdir()
            self.ring.begin(folder,1000.5)
            state=self.ring.finish(1002.5)
        self.assertTrue(state['segments'])
        self.assertTrue(state['tail_complete'])

    def test_ring_deletes_only_expired_ram_segments(self):
        self.generate(12)
        self.ring.keep_seconds=4
        self.ring.ingest()
        self.assertLessEqual(self.ring.status()['available_seconds'],5.01)
        self.assertLessEqual(len(list(self.path.glob('segment-*.mkv'))),6)
    def test_warming_buffer_reports_partial_preroll(self):
        self.generate(2)
        folder=self.data/'clip';folder.mkdir()
        details=self.ring.begin(folder,990)
        self.assertFalse(details['prebuffer_complete'])
        self.assertEqual(details['actual_start_epoch'],1000)
        self.ring.finish(1001)
    def test_archive_export_waits_for_space_without_deleting_source(self):
        self.generate(2)
        folder=self.data/'clip';folder.mkdir();self.ring.begin(folder,1000);self.ring.finish(1002)
        self.e.storage=lambda:dict(available=True,free=1000)
        with self.assertRaises(StorageWait):self.e.assemble_buffer(folder)
        self.assertTrue(list((folder/'buffer-segments').glob('*.mkv')))

    def test_new_native_clip_assembles_while_older_frame_export_is_busy(self):
        self.generate(4)
        old=self.data/'20261026T000001Z-abcdef';old.mkdir()
        (old/'video.mkv').write_bytes((self.path/'segment-000000000.mkv').read_bytes())
        save(old/'manifest.json',dict(id=old.name,state='completed',frames=dict(state='queued',mode='all',fps=60)))
        blocked=threading.Event();release=threading.Event();original_probe=self.e.probe
        def probe(source,count=False):
            if source==old/'video.mkv':blocked.set();release.wait(10)
            return original_probe(source,count)
        self.e.probe=probe
        self.e.queue_frames(old.name)
        try:
            self.assertTrue(blocked.wait(3))
            folder=self.data/'20261026T000002Z-abcdef';folder.mkdir()
            self.ring.begin(folder,1001);self.ring.finish(1003)
            save(folder/'manifest.json',dict(id=folder.name,state='completed',buffered_capture=True,
                frames=dict(state='queued',mode='all',fps=60)))
            self.e.queue_frames(folder.name)
            deadline=time.monotonic()+6
            while time.monotonic()<deadline:
                m=load(folder/'manifest.json')
                if m.get('files',{}).get('video.mkv'):break
                time.sleep(.1)
            self.assertIn('video.mkv',m.get('files',{}),m)
            self.assertEqual(self.e.processing,old.name)
        finally:release.set()

    def test_playback_created_when_jpeg_export_is_waiting_for_space(self):
        self.generate(2)
        folder=self.data/'20261026T000003Z-abcdef';folder.mkdir()
        (folder/'video.mkv').write_bytes((self.path/'segment-000000000.mkv').read_bytes())
        save(folder/'manifest.json',dict(id=folder.name,state='completed',capture_stats=dict(frame=60),
            frames=dict(state='queued',mode='all',fps=60)))
        save(self.run/'storage-policy.json',dict(reserve_gib=2))
        self.e.storage=lambda:dict(available=True,free=int(2.5*1024**3))
        self.e.queue_frames(folder.name)
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            m=load(folder/'manifest.json')
            if m.get('video_playback',{}).get('state')=='completed' and m['frames']['state']=='waiting_storage':break
            time.sleep(.1)
        self.assertEqual(m['video_playback']['state'],'completed',m)
        self.assertEqual(m['video_playback']['frame_count'],60)
        self.assertEqual(m['frames']['state'],'waiting_storage')
        payload=(folder/'video.mp4').read_bytes()
        self.assertLess(payload.find(b'moov'),payload.find(b'mdat'))

    def test_rate_limited_export_keeps_60fps_while_another_capture_is_active(self):
        self.generate(2)
        folder=self.data/'20261026T000004Z-abcdef';folder.mkdir()
        (folder/'video.mkv').write_bytes((self.path/'segment-000000000.mkv').read_bytes())
        save(folder/'manifest.json',dict(id=folder.name,state='completed',capture_stats=dict(frame=60),frames=dict(state='queued',mode='all',fps=60)))
        self.station.active={'id':'different-session'};self.e.readrate=.5
        self.e.queue_frames(folder.name)
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            m=load(folder/'manifest.json')
            if m['frames']['state'] in ('completed','failed'):break
            time.sleep(.1)
        self.assertEqual(m['frames']['state'],'completed',m)
        self.assertEqual(m['frames']['count'],60)
        self.assertEqual(m['video_playback']['frame_count'],60)
        self.assertEqual(m['video_playback']['avg_frame_rate'],'60/1')

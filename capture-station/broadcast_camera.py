"""Bounded, reconnecting camera source that keeps the encoder alive during outages."""
import os
from http.client import HTTPException
import sys
import threading
import time
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'uap-lab'))
from no_signal import NoSignalDetector

MAX_JPEG = 8 * 1024 * 1024

def mjpeg_frames(response):
    """Read the station's length-delimited multipart frames without an unbounded buffer."""
    while True:
        length = None
        header_bytes = 0
        while True:
            line = response.readline(4097)
            if not line:
                return
            header_bytes += len(line)
            if header_bytes > 8192:
                raise ValueError('Oversized camera multipart header')
            if line.lower().startswith(b'content-length:'):
                length = int(line.split(b':', 1)[1])
            if not line.strip() and length is not None:
                break
        if not 0 < length <= MAX_JPEG:
            raise ValueError('Invalid camera frame size')
        jpeg = response.read(length)
        if len(jpeg) != length:
            return
        if jpeg.startswith(b'\xff\xd8') and jpeg.endswith(b'\xff\xd9'):
            yield jpeg

class CameraPipe:
    def __init__(self, source, standby_path, stale_seconds=3):
        self.source = source
        self.standby = Path(standby_path).read_bytes()
        self.stale_seconds = stale_seconds
        self.latest = None
        self.detector = NoSignalDetector()
        self.stop = threading.Event()
        self.reader, self.writer = os.pipe()

    def accept(self, jpeg, now=None):
        now = time.monotonic() if now is None else now
        previous = self.latest
        # Match the existing Cam Link slate detector, including a live HDMI feed
        # which continues sending frames after the camera itself loses signal.
        checked = previous[3] if previous else float('-inf')
        no_signal = previous[2] if previous else False
        if now - checked >= .5:
            no_signal = self.detector.matches(jpeg)
            checked = now
        self.latest = (jpeg, now, no_signal, checked)

    def current(self, now=None):
        now = time.monotonic() if now is None else now
        latest = self.latest
        standby = latest is None or latest[2] or now - latest[1] >= self.stale_seconds
        return (self.standby if standby else latest[0]), standby

    def start(self):
        self.receive_thread = threading.Thread(target=self.receive, daemon=True)
        self.write_thread = threading.Thread(target=self.write, daemon=True)
        self.receive_thread.start()
        self.write_thread.start()

    def receive(self):
        while not self.stop.is_set():
            try:
                with urlopen(self.source, timeout=2) as response:
                    for jpeg in mjpeg_frames(response):
                        if self.stop.is_set():
                            return
                        self.accept(jpeg)
            except (OSError, ValueError, HTTPException):
                pass
            self.stop.wait(.5)

    def write(self):
        try:
            with os.fdopen(self.writer, 'wb', buffering=0) as pipe:
                deadline = time.monotonic()
                while not self.stop.is_set():
                    raw = memoryview(self.current()[0])
                    while raw:
                        written = pipe.write(raw)
                        if not written:
                            return
                        raw = raw[written:]
                    deadline += 1 / 30
                    delay = deadline - time.monotonic()
                    if delay < 0:
                        deadline = time.monotonic()
                    else:
                        self.stop.wait(delay)
        except (BrokenPipeError, OSError):
            pass

    def close(self):
        self.stop.set()
        try:
            os.close(self.reader)
        except OSError:
            pass
        if hasattr(self, 'write_thread'):
            self.write_thread.join(timeout=2)

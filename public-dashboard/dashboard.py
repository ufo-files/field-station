#!/usr/bin/env python3
"""Public, read-only field observer. Never imports or proxies the control application."""
import argparse, datetime, hashlib, http.server, json, math, mimetypes, os, plistlib, re, socket, stat, subprocess, threading, time, urllib.request
from pathlib import Path
from urllib.parse import urlsplit

SESSION = re.compile(r'[0-9TZ]+-[a-f0-9]{6}')
ID = re.compile(r'[a-f0-9]{32}')
LABELS = {'anomalous', 'not_anomalous', 'bird', 'plane', 'insect', 'cloud', 'sky', 'unknown'}

def read(path, default=None):
    try:
        if path.stat().st_size > 16 * 1024 * 1024: return default
        return json.loads(path.read_text())
    except (OSError, ValueError): return default

def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None

def numbers(row, keys):
    return {k: number(row.get(k)) for k in keys}

def enum(value, allowed):
    return value if isinstance(value, str) and value in allowed else 'unknown'

def atomic(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_bytes(value)
    temp.replace(path)

def safe_file(path, root):
    """Reject symlinks at every component, including when a recording is replaced."""
    try:
        path = Path(os.path.abspath(path)); root = Path(os.path.abspath(root))
        relative = path.relative_to(root)
        current = root
        if current.is_symlink(): return False
        for part in relative.parts:
            current = current / part
            if current.is_symlink(): return False
        return path.is_file() and path.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError): return False

class Exporter:
    def __init__(self, root, output):
        self.root, self.output = root, output
        self.device = root.stat().st_dev
        self.media = {}; self.catalog = []; self.stills = []; self.last_catalog = 0

    def media_link(self, path):
        if not safe_file(path, self.root): return None
        key = hashlib.sha256(str(path.relative_to(self.root)).encode()).hexdigest()
        self.media[key] = str(path.relative_to(self.root))
        return '/media/' + key

    def catalog_update(self):
        self.media = {}; recordings = []; stills = []
        for folder in (self.root / 'sessions').glob('*'):
            if not SESSION.fullmatch(folder.name) or folder.is_symlink(): continue
            m = read(folder / 'manifest.json', {})
            if m.get('state') not in ('completed', 'stopped'): continue
            files = []
            for filename in ('video.mp4', 'video.mkv'):
                path = folder / filename; url = self.media_link(path)
                if url: files.append(dict(url=url, format=filename.split('.')[-1], bytes=path.stat().st_size))
            recordings.append(dict(id=folder.name, epoch=number(m.get('started_epoch')), duration=number(m.get('elapsed_seconds')), files=files, provisional=m.get('provisional') is True, removed=m.get('session_media_removed') is True))
            for path in (folder / 'frames').glob('*'):
                if path.suffix.lower() not in ('.jpg', '.jpeg', '.png'): continue
                url = self.media_link(path)
                if url: stills.append(dict(url=url, session=folder.name, label='unreviewed', epoch=number(m.get('started_epoch'))))
        for folder in (self.root / 'uap-lab/videos').glob('*'):
            if not ID.fullmatch(folder.name) or folder.is_symlink(): continue
            meta = read(folder / 'video.json', {})
            url = self.media_link(folder / 'preview.mp4')
            if url:
                recordings.append(dict(id=folder.name, epoch=number(meta.get('created')), duration=number(meta.get('duration')), files=[dict(url=url, format='mp4', bytes=(folder/'preview.mp4').stat().st_size)], provisional=True, removed=False))
            for a in read(folder / 'annotations.json', []):
                if not isinstance(a, dict) or not ID.fullmatch(str(a.get('id', ''))): continue
                # Only explicit image basenames; never publish arbitrary metadata paths.
                name = a.get('image', '')
                if not isinstance(name, str) or Path(name).name != name or Path(name).suffix.lower() not in ('.png', '.jpg', '.jpeg'): continue
                url = self.media_link(folder / name)
                if url: stills.append(dict(url=url, session=folder.name, label=enum(a.get('label'), LABELS), epoch=number(meta.get('created'))))
        self.catalog = sorted(recordings, key=lambda x: x['epoch'] or 0, reverse=True)
        self.stills = sorted(stills, key=lambda x: x['epoch'] or 0, reverse=True)
        atomic(self.output / 'media-map.json', json.dumps(self.media).encode())
        atomic(self.output / 'recordings.json', json.dumps(self.catalog).encode())
        atomic(self.output / 'stills.json', json.dumps(self.stills).encode())
        self.last_catalog = time.monotonic()

    def update(self):
        if self.root.stat().st_dev != self.device: raise SystemExit('Field volume changed')
        if time.monotonic() - self.last_catalog > 60: self.catalog_update()
        native = read(self.root / 'uap-lab/live/native-analysis.json', {})
        qual = read(self.root / 'uap-lab/qualification/current.json', {})
        now = time.time()
        status = dict(updated_epoch=now, analysis=numbers(native, ('analyzed_epoch', 'analyzed_frames', 'analyzed_fps', 'latency_seconds', 'backlog_frames', 'candidate_count', 'model_classified_frames', 'model_classified_proposals')), capture=numbers(native.get('capture', {}), ('last_frame_epoch', 'measured_fps', 'captured_frames', 'timestamp_gap_count', 'inferred_missing_frames', 'device_dropped_frames')), qualification=dict(scientific_ready=qual.get('scientific_ready') is True and now - (number(qual.get('updated_epoch')) or 0) < 120, updated_epoch=number(qual.get('updated_epoch')), unavailable=bool(qual.get('error')), clean_seconds=number(qual.get('clean_seconds')), required_seconds=number(qual.get('required_seconds')), faults=[v for v in qual.get('current_faults', []) if isinstance(v, str) and re.fullmatch('[a-z_]{1,80}', v)]), recordings=len(self.catalog), playable_recordings=sum(bool(r['files']) for r in self.catalog), stills=len(self.stills))
        status['analysis']['phase'] = enum(native.get('phase'), {'analyzing', 'starting', 'idle', 'error', 'journal_error', 'stopped'})
        # Only this fixed, side-effect-free preview endpoint is called by the exporter.
        # Public requests never reach it and cannot supply URLs or parameters.
        try:
            with urllib.request.urlopen('http://127.0.0.1:8092/api/live/status', timeout=3) as response:
                live = json.loads(response.read(1024 * 1024))
            frame_epoch = number(live.get('frame_epoch'))
            if frame_epoch is None or not 0 <= now - frame_epoch < 30: raise ValueError('stale preview')
            with urllib.request.urlopen('http://127.0.0.1:8092/api/live/frame', timeout=3) as response:
                jpeg = response.read(4 * 1024 * 1024 + 1)
            if len(jpeg) > 4 * 1024 * 1024 or not jpeg.startswith(b'\xff\xd8'): raise ValueError('preview')
            atomic(self.output / 'camera.jpg', jpeg)
            status['camera_epoch'] = frame_epoch
        except Exception:
            status['camera_epoch'] = None
            (self.output / 'camera.jpg').unlink(missing_ok=True)
        rf = read(self.root / 'signal-spool/live.json', {})
        status['rf'] = {}
        for role in ('narrow', 'wide'):
            row = rf.get('receivers', {}).get(role) or read(self.root / 'signal-spool' / role / 'live.json', {})
            if not row and role == 'narrow': row = rf
            row = dict(row)
            for field in ('average_db', 'maximum_db'):
                values = row.get(field)
                if isinstance(values, list):
                    values = [v for v in values if number(v) is not None]
                    row[field] = (sum(values)/len(values) if field == 'average_db' else max(values)) if values else None
            if number(row.get('timestamp')) is None:
                try: row['timestamp'] = datetime.datetime.fromisoformat(row.get('minute_utc', '').replace('Z', '+00:00')).timestamp()
                except ValueError: pass
            status['rf'][role] = numbers(row, ('timestamp', 'average_db', 'maximum_db'))
            band = row.get('range_hz', [])
            status['rf'][role]['range_hz'] = [number(v) for v in band[:2]] if isinstance(band, list) else []
        atomic(self.output / 'status.json', json.dumps(status, allow_nan=False).encode())

class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16
    def __init__(self, address, handler, root, output, static):
        self.root, self.output, self.static = root, output, static
        self.device = root.stat().st_dev
        self.slots = threading.BoundedSemaphore(12)
        super().__init__(address, handler)
    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            request.close(); return
        try: super().process_request(request, address)
        except Exception:
            self.slots.release(); raise
    def process_request_thread(self, request, address):
        try: super().process_request_thread(request, address)
        finally: self.slots.release()

class Handler(http.server.BaseHTTPRequestHandler):
    server_version = 'FieldObserver'
    sys_version = ''
    def setup(self):
        super().setup(); self.connection.settimeout(15)
    def log_message(self, *args): pass  # No visitor access log.
    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; media-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()
    def reject(self):
        self.close_connection = True
        self.send_error(405, 'Read only')
    do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_TRACE = do_CONNECT = reject
    def do_HEAD(self): self.do_GET(head=True)
    def do_GET(self, head=False):
        try:
            if self.server.root.stat().st_dev != self.server.device:
                self.send_error(503); return
            path = urlsplit(self.path).path
            mime = None
            if path in ('/', '/app.js', '/style.css'):
                target = self.server.static / {'/':'index.html', '/app.js':'app.js', '/style.css':'style.css'}[path]
                root = self.server.static
            elif path in ('/status.json', '/recordings.json', '/stills.json', '/camera.jpg'):
                target = self.server.output / path[1:]; root = self.server.output
            elif re.fullmatch('/media/[a-f0-9]{64}', path):
                mapping = read(self.server.output / 'media-map.json', {})
                relative = mapping.get(path.split('/')[-1])
                if not relative: self.send_error(404); return
                root = self.server.root; target = root / relative
            else: self.send_error(404); return
            if not safe_file(target, root): self.send_error(404); return
            # Open without following the final symlink; recheck parent containment.
            fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, 'rb') as stream:
                if not safe_file(target, root): self.send_error(404); return
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode): self.send_error(404); return
                size = info.st_size; start = 0; end = size - 1; partial = False
                if self.headers.get('Range'):
                    match = re.fullmatch(r'bytes=(\d{0,20})-(\d{0,20})', self.headers['Range'])
                    if not match or not any(match.groups()): self.send_error(416); return
                    if match[1]: start = int(match[1]); end = min(end, int(match[2])) if match[2] else end
                    else: start = max(0, size - int(match[2]))
                    if start > end or start >= size: self.send_error(416); return
                    partial = True
                self.send_response(206 if partial else 200)
                self.send_header('Content-Type', mimetypes.guess_type(target.name)[0] or 'application/octet-stream')
                self.send_header('Content-Length', str(max(0, end-start+1)))
                self.send_header('Accept-Ranges', 'bytes')
                if partial: self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                self.end_headers()
                if head: return
                stream.seek(start); remaining = end-start+1
                while remaining > 0:
                    block = stream.read(min(65536, remaining))
                    if not block: break
                    self.wfile.write(block); remaining -= len(block)
        except (OSError, ValueError, socket.timeout):
            self.close_connection = True

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('export', 'serve'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--volume-uuid', required=True)
    parser.add_argument('--port', type=int, default=8093)
    args = parser.parse_args()
    info = plistlib.loads(subprocess.check_output(['/usr/sbin/diskutil', 'info', '-plist', str(args.root)]))
    if info.get('VolumeUUID', '').upper() != args.volume_uuid.upper(): raise SystemExit('Expected field SSD is unavailable')
    args.output.mkdir(parents=True, exist_ok=True)
    if args.mode == 'serve':
        Server(('127.0.0.1', args.port), Handler, args.root, args.output, Path(__file__).parent / 'static').serve_forever()
    else:
        exporter = Exporter(args.root, args.output)
        while True:
            try: exporter.update()
            except Exception as exc: print('Export unavailable:', type(exc).__name__, flush=True)
            time.sleep(15)

if __name__ == '__main__': main()

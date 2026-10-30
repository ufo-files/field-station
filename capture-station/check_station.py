#!/usr/bin/env python3
"""Hardware smoke check. Records a short, clearly labelled validation session."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import time
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parent
BASE = 'http://127.0.0.1:8090'
DRIVER = 'http://127.0.0.1:9515'

def request(url, value=None, method=None, headers=None):
    data = None if value is None else json.dumps(value).encode()
    h = {'Content-Type': 'application/json', **(headers or {})}
    with urlopen(Request(url, data=data, method=method, headers=h), timeout=45) as r:
        raw = r.read()
        return json.loads(raw) if 'application/json' in r.headers.get('Content-Type', '') else raw

def main():
    status = request(BASE+'/api/status')
    assert status['active'] is None, 'Do not interrupt an existing session'
    assert status['rf']['fresh'], 'RF source must be fresh'
    assert status['camera']['fresh'], 'Camera frames must be fresh'
    for path, value, headers in [('/api/start', {}, {}), ('/api/start', {'minutes': 0}, {'X-Station-Token': status['csrf']})]:
        try:
            request(BASE+path, value, headers=headers)
            raise AssertionError('Invalid request accepted')
        except HTTPError as e:
            assert e.code == (403 if not headers else 400)
    created = request(DRIVER+'/session', {'capabilities': {'alwaysMatch': {'browserName': 'chrome',
        'goog:chromeOptions': {'args': ['--headless=new', '--no-sandbox', '--disable-dev-shm-usage', '--window-size=1440,1200']},
        'goog:loggingPrefs': {'browser': 'ALL'}}}})
    sid = created['value']['sessionId']
    wd = DRIVER+'/session/'+sid
    def js(code):
        return request(wd+'/execute/sync', {'script': code, 'args': []})['value']
    try:
        request(wd+'/url', {'url': BASE})
        time.sleep(3)
        assert js('return document.getElementById("connection").textContent') == '● STATION ONLINE'
        js('document.querySelector("input[name=title]").value="System validation — HDMI + RF"; document.querySelector("input[name=minutes]").value="1"; document.querySelector("textarea[name=notes]").value="Automated hardware smoke test. Cam Link may display NO SIGNAL; not an experimental observation."; document.querySelector("#start").click();')
        time.sleep(3)
        status = request(BASE+'/api/status')
        assert status['active'], 'Start button failed'
        active_id = status['active']['id']
        js('document.getElementById("markerNote").value="Validation event marker"; document.getElementById("mark").click();')
        time.sleep(7)
        assert request(BASE+'/api/status')['active']['rf_records'] >= 3
        shot = request(wd+'/screenshot')['value']
        (ROOT/'run/dashboard-desktop.png').write_bytes(base64.b64decode(shot))
        if '--one-minute' not in sys.argv:
            js('document.getElementById("stop").click();')
        for _ in range(90):
            time.sleep(1)
            status = request(BASE+'/api/status')
            if not status['active']:
                break
        assert not status['active'], 'Stop button failed'
        m = next(m for m in status['sessions'] if m['id'] == active_id)
        assert m['state'] == 'completed', m
        for _ in range(600):
            status = request(BASE+'/api/status')
            m = next(m for m in status['sessions'] if m['id'] == active_id)
            if m.get('frames', {}).get('state') == 'completed':
                break
            time.sleep(1)
        assert m['frames']['state']=='completed', m
        index = request(BASE+'/sessions/'+active_id+'/frames/index.json')
        assert len(index['frames'])==m['frames']['count']
        for frame in (index['frames'][0], index['frames'][len(index['frames'])//2], index['frames'][-1]):
            data = request(BASE+'/sessions/'+active_id+'/frames/'+frame['file'])
            assert hashlib.sha256(data).hexdigest()==frame['sha256']
        if '--one-minute' in sys.argv:
            assert 59 <= m['elapsed_seconds'] <= 63, m['elapsed_seconds']
            assert m['rf_records'] >= 50, m['rf_records']
            assert m['frames']['count']==m['capture_stats']['frame'], m['frames']
        assert len(m['markers']) == 1
        for name, meta in m['files'].items():
            assert hashlib.sha256((ROOT/'sessions'/active_id/name).read_bytes()).hexdigest() == meta['sha256']
        video = BASE+'/sessions/'+active_id+'/video.mp4'
        with urlopen(Request(video, headers={'Range': 'bytes=0-99'})) as r:
            assert r.status == 206 and len(r.read()) == 100
        request(wd+'/url', {'url': BASE})
        time.sleep(3)
        js('document.querySelector(".session-row button").click();')
        time.sleep(2)
        assert js('return document.getElementById("review").open')
        assert js('return document.getElementById("recordedTime").textContent').startswith('Nearest RF snapshot')
        assert js('return document.getElementById("player").readyState') >= 1
        js('document.getElementById("player").muted=true; document.getElementById("player").play();')
        time.sleep(2)
        assert js('return document.getElementById("player").currentTime') > 0.5, 'Video playback did not advance'
        (ROOT/'run/session-review.png').write_bytes(base64.b64decode(request(wd+'/screenshot')['value']))
        js('document.getElementById("closeReview").click()')
        request(wd+'/window/rect', {'width': 390, 'height': 844})
        time.sleep(1)
        assert js('return document.documentElement.scrollWidth<=window.innerWidth'), 'Mobile horizontal overflow'
        (ROOT/'run/dashboard-mobile.png').write_bytes(base64.b64decode(request(wd+'/screenshot')['value']))
        errors = request(wd+'/log', {'type': 'browser'})['value']
        severe = [e for e in errors if e['level']=='SEVERE' and 'favicon.ico' not in e['message']]
        assert not severe, severe
        env = dict(__import__('os').environ, LD_LIBRARY_PATH=str(ROOT/'vendor/root/usr/lib/aarch64-linux-gnu')+':'+str(ROOT/'vendor/root/usr/lib/aarch64-linux-gnu/lapack'))
        probe = json.loads(subprocess.check_output([str(ROOT/'vendor/root/usr/bin/ffprobe'), '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(ROOT/'sessions'/active_id/'video.mp4')], env=env))
        v = probe['streams'][0]
        assert v['codec_name']=='h264' and v['width']==1920 and v['height']==1080
        if '--one-minute' in sys.argv:
            assert abs(float(probe['format']['duration'])-60) < 0.15, probe['format']['duration']
            assert m['frames']['count'] == m['capture_stats']['frame'], m['frames']
        print(json.dumps({'session': active_id, 'state': m['state'], 'rf_snapshots': m['rf_records'], 'frames': m['frames']['count'], 'markers': len(m['markers']), 'video_seconds': probe['format']['duration'], 'resolution': [v['width'],v['height']], 'browser_errors': severe, 'checksums': 'verified', 'range_playback': 'passed', 'mobile_layout': 'passed'}, indent=2))
    finally:
        request(wd, method='DELETE')
        if request(BASE+'/api/status')['active']:
            fresh = request(BASE+'/api/status')
            request(BASE+'/api/stop', {}, headers={'X-Station-Token': fresh['csrf']})

if __name__ == '__main__':
    driver = None
    try:
        try:
            request(DRIVER+'/status')
        except OSError:
            driver = subprocess.Popen(['chromedriver', '--port=9515', '--allowed-ips=127.0.0.1'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1)
        main()
    finally:
        if driver:
            driver.terminate()
            driver.wait(timeout=10)

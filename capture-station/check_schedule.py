"""Browser acceptance check; enables the user-requested real hourly schedule."""
import base64
import json
from pathlib import Path
import subprocess
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent

def request(base, path, body=None, method=None):
    with urlopen(Request(base+path, data=None if body is None else json.dumps(body).encode(),
                         method=method, headers={'Content-Type':'application/json'}), timeout=30) as r:
        return json.load(r)

def main():
    driver = subprocess.Popen(['chromedriver','--port=9515','--allowed-ips=127.0.0.1'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    sid = None
    try:
        time.sleep(1)
        base = 'http://127.0.0.1:9515'
        def wd(path, body=None, method=None):
            return request(base, path, body, method)['value']
        sid = wd('/session', {'capabilities': {'alwaysMatch': {'browserName':'chrome',
            'goog:chromeOptions': {'args':['--headless=new','--no-sandbox','--disable-dev-shm-usage','--window-size=1440,1200']},
            'goog:loggingPrefs': {'browser':'ALL'}}}})['sessionId']
        prefix = '/session/'+sid
        def js(source):
            return wd(prefix+'/execute/sync', {'script':source, 'args':[]})
        def status():
            return request('http://127.0.0.1:8090', '/api/status')
        wd(prefix+'/url', {'url':'http://127.0.0.1:8090/'})
        time.sleep(3)
        assert js('return document.getElementById("autoDuration").value')=='3'
        assert js('return document.getElementById("autoGap").value')=='10'
        assert js('return document.getElementById("autoInterval").value')=='60'
        assert not js('return document.getElementById("ce5Enabled").checked')
        # Verify explicit sampled export, then restore full-frame 60 fps capture.
        js('document.getElementById("frameExportMode").value="sampled";const e=document.getElementById("autoFps");e.value="2";e.dispatchEvent(new Event("input"));document.getElementById("saveAutomaticSettings").click();')
        time.sleep(2)
        assert status()['experiments']['automatic']['frame_fps']==2
        js('document.getElementById("frameExportMode").value="all";const e=document.getElementById("videoFps");e.value="60";e.dispatchEvent(new Event("input"));document.getElementById("saveAutomaticSettings").click();')
        time.sleep(2)
        assert status()['experiments']['automatic']['frame_fps']==60
        js('document.getElementById("enableAutomatic").click()')
        for _ in range(15):
            time.sleep(1)
            s=status()
            if s['active']:
                break
        assert s['active'] and s['active']['automatic_run'], s['experiments']['automatic']
        assert s['active']['duration_limit_seconds']==180
        assert s['active']['condition']=='silence'
        assert s['active']['frame_fps']==60
        assert s['experiments']['automatic']['enabled']
        assert not s['experiments']['automatic']['ce5_enabled']
        (ROOT/'run/scheduled-capture-desktop.png').write_bytes(base64.b64decode(wd(prefix+'/screenshot')))
        wd(prefix+'/window/rect', {'width':390,'height':844})
        time.sleep(1)
        assert js('return document.documentElement.scrollWidth<=window.innerWidth')
        (ROOT/'run/scheduled-capture-mobile.png').write_bytes(base64.b64decode(wd(prefix+'/screenshot')))
        errors = [e for e in wd(prefix+'/log', {'type':'browser'}) if e['level']=='SEVERE' and 'favicon.ico' not in e['message']]
        assert not errors, errors
        result = dict(session_id=s['active']['id'], duration_seconds=180, frame_fps=60,
                      gap_minutes=10, interval_minutes=60, ce5_enabled=False, browser_errors=errors)
        (ROOT/'run/schedule-validation.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result,indent=2))
    finally:
        if sid:
            request('http://127.0.0.1:9515','/session/'+sid,method='DELETE')
        driver.terminate()
        driver.wait(timeout=10)

if __name__=='__main__':
    main()

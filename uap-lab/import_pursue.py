#!/usr/bin/env python3
"""One-shot resumable PURSUE import. Discovery index is not training supervision."""
import concurrent.futures,hashlib,html,json,os,re,shutil,subprocess,threading,time
from pathlib import Path
from urllib.parse import urlsplit
import lab
BASE=Path('/home/hackrf/t7/training-videos/PURSUE')
for name in ('videos','metadata','pages'): (BASE/name).mkdir(parents=True,exist_ok=True)
STATUS=BASE/'import-status.json';LOCK=threading.Lock();results={}

def curl(url,path,download=False):
    args=['curl','-fL','--silent','--show-error','--connect-timeout','20','--max-time','1800' if download else '90','--retry','2','--retry-delay','3']
    if download:args+=['--continue-at','-','--limit-rate','8M']
    p=subprocess.run(args+['--output',str(path),url],capture_output=True)
    if p.returncode:raise ValueError(p.stderr.decode(errors='replace')[-800:])

def fetch_json(url,path):
    if not path.is_file():curl(url,path)
    return json.loads(path.read_text())

def progress(state='running'):
    with LOCK:
        rows=list(results.values());lab.save(STATUS,dict(state=state,total=len(entries),completed=sum(v['state']=='complete' for v in rows),failed=sum(v['state']=='failed' for v in rows),bytes=sum(v.get('bytes',0) for v in rows),updated=time.time(),discovery_url='https://pursueufotracker.com/generated/api/files.json',discovery_generated_at=index.get('generated_at'),coverage_note='150 video entries in the discovery index through release 06; official war.gov manifest was inaccessible (HTTP 403). No claim of complete latest government catalog coverage.',items=sorted(rows,key=lambda v:v['id'])))

def detail(entry):
    slug=entry['id']
    if not re.fullmatch('[a-z0-9-]+',slug):raise ValueError('Unsafe record ID')
    raw=fetch_json('https://pursueufotracker.com/generated/api/files/'+slug+'.json',BASE/'metadata'/(slug+'-discovery.json'))
    return raw

def process(entry):
    slug=entry['id'];row=dict(id=slug,state='downloading',title=entry['title']);results[slug]=row
    try:
        lab.space_check()
        existing=lab.read(BASE/'metadata'/(slug+'.json'),{})
        dest=BASE/'videos'/(slug+'.mp4')
        if existing and dest.is_file() and dest.stat().st_size==existing.get('bytes') and lab.read(lab.video_path(existing['video_id'])/'video.json'):
            row.update(state='complete',bytes=existing['bytes'],path=str(dest),video_id=existing['video_id'],sha256=existing['sha256']);progress();return
        d=detail(entry);d.update(lab.read(BASE/'source-overrides.json',{}).get(slug,{}));page=d.get('dvids_page_url');url=d.get('video_url')
        if not page or urlsplit(page).hostname not in ('www.dvidshub.net','dvidshub.net'):raise ValueError('No official DVIDS source page in discovery record')
        pagefile=BASE/'pages'/(slug+'.html')
        if not pagefile.is_file():curl(page,pagefile)
        content=pagefile.read_text();sources=[html.unescape(v) for v in re.findall(r'<source\b[^>]*src=[\"\x27]([^\"\x27]+\.mp4[^\"\x27]*)',content,re.I)]
        sources=[v for v in sources if urlsplit(v).hostname=='d34w7g4gy10iej.cloudfront.net']
        if not sources:raise ValueError('Official page has no public MP4 source')
        # Higher-resolution renditions discovered by the index must belong to the
        # same official asset directory as the page's public playback source.
        parent=urlsplit(sources[0]).path.rsplit('/',1)[0]+'/'
        allowed=url and urlsplit(url).hostname=='d34w7g4gy10iej.cloudfront.net' and urlsplit(url).path.startswith(parent)
        candidates=list(dict.fromkeys(([url] if allowed else [])+sources))
        dest=BASE/'videos'/(slug+'.mp4');part=dest.with_suffix('.mp4.part');used=None
        existing=lab.read(BASE/'metadata'/(slug+'.json'),{})
        if dest.is_file():used=existing.get('download_url') or candidates[0]
        else:
            for candidate in candidates:
                try:curl(candidate,part,True);used=candidate;break
                except Exception:
                    # A partial rendition cannot be resumed against another URL.
                    part.unlink(missing_ok=True)
                    if candidate==candidates[-1]:raise
            part.replace(dest)
        meta=lab.probe(dest);digest=hashlib.sha256()
        with dest.open('rb') as f:
            for block in iter(lambda:f.read(1024*1024),b''):digest.update(block)
        sha=digest.hexdigest();vid=hashlib.sha256(('pursue:'+slug).encode()).hexdigest()[:32]
        provenance=dict(collection='PURSUE',record_id=slug,title=d['title'],agency=d.get('agency'),date_released=d.get('date_released'),date_event=d.get('date_event'),source_page=page,download_url=used,discovery_url='https://pursueufotracker.com/files/'+slug,sha256=sha,bytes=dest.stat().st_size,discovery_sha256=d.get('sha256'),discovery_checksum_matches=(sha==d.get('sha256')) if d.get('sha256') else None,source_correction=d.get('source_correction'),local_file=str(dest),imported=time.time(),video_id=vid)
        lab.save(BASE/'metadata'/(slug+'.json'),provenance)
        folder=lab.video_path(vid);folder.mkdir(exist_ok=True)
        if not (folder/'source').exists():os.link(dest,folder/'source')
        if not (folder/'video.json').exists():
            meta.update(id=vid,name=d['title']+'.mp4',created=time.time(),bytes=dest.stat().st_size,sha256=sha,mime='video/mp4',provenance=provenance)
            if meta['codec']!='h264':meta['preview_state']='preparing'
            lab.save(folder/'video.json',meta)
            if meta['codec']!='h264':lab.prepare_preview(folder)
        row.update(state='complete',bytes=dest.stat().st_size,path=str(dest),video_id=vid,sha256=sha)
        print('COMPLETE',slug,row['bytes'],flush=True)
    except Exception as exc:
        row.update(state='failed',error=str(exc));print('FAILED',slug,str(exc),flush=True)
    progress()

if __name__=='__main__':
    index=fetch_json('https://pursueufotracker.com/generated/api/files.json',BASE/'discovery-index.json')
    entries=[v for v in index['files'] if v.get('type')=='video']
    progress();print('Importing',len(entries),'videos to',BASE,flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(process,entries))
    progress('complete' if all(v['state']=='complete' for v in results.values()) else 'partial')

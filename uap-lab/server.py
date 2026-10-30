#!/usr/bin/env python3
import html, json, mimetypes, os, re, secrets, shutil, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit,parse_qs,unquote
import lab

TOKEN=secrets.token_urlsafe(32)
LIVE=None
PUBLISHER=None
class Handler(BaseHTTPRequestHandler):
    def json(self,value,status=200):
        data=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
    def file(self,path,mime=None):
        if not path.is_file():self.send_error(404);return
        size=path.stat().st_size;start,end=0,size-1;partial=False
        value=self.headers.get('Range')
        if value:
            m=re.fullmatch(r'bytes=(\d*)-(\d*)',value)
            if not m or not any(m.groups()):self.send_error(416);return
            if m[1]:start=int(m[1]);end=min(end,int(m[2])) if m[2] else end
            else:start=max(0,size-int(m[2]))
            if start>end or start>=size:
                self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.send_header('Content-Length','0');self.end_headers();return
            partial=True
        self.send_response(206 if partial else 200);self.send_header('Content-Type',mime or mimetypes.guess_type(path.name)[0] or 'application/octet-stream');self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(end-start+1));self.send_header('X-Content-Type-Options','nosniff')
        if partial:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.end_headers()
        with path.open('rb') as f:
            f.seek(start);remaining=end-start+1
            while remaining:
                data=f.read(min(1024*1024,remaining))
                if not data:break
                self.wfile.write(data);remaining-=len(data)
    def do_GET(self):
        try:
            url=urlsplit(self.path);q=parse_qs(url.query);p=url.path
            if p=='/api/email-review':
                from email_review import detail,prepare
                key=q['id'][0];info=detail(lab.DATA,key)
                if info['clip']['state']=='preparing':
                    def build():
                        try:prepare(lab.DATA,key)
                        except Exception:pass
                    threading.Thread(target=build,daemon=True).start()
                self.json(dict(info,token=TOKEN));return
            if p=='/api/email-review/video':
                from email_review import folder_for
                self.file(folder_for(lab.DATA,q['id'][0])/'review.mp4','video/mp4');return
            if p=='/api/labeled-frames/token':self.json(dict(token=TOKEN));return
            if p=='/api/labeled-frames':
                from labeled_frames import listing
                self.json(listing(q.get('label',[''])[0],q.get('search',[''])[0],q.get('offset',['0'])[0],q.get('limit',['48'])[0]));return
            if p=='/api/tracks':
                folder=lab.video_path(q['id'][0]);meta=lab.read(folder/'video.json')
                if not meta:raise ValueError('Video not found')
                self.json(dict(id=meta['id'],name=meta['name'],annotations=lab.read(folder/'annotations.json',[])));return
            if p=='/api/annotation':
                folder=lab.video_path(q['id'][0]);aid=lab.checked_id(q['annotation'][0]);annotation=next((a for a in lab.read(folder/'annotations.json',[]) if a['id']==aid),None)
                if not annotation:raise ValueError('Annotation not found')
                path=folder/annotation['image']
                if path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()) or path.suffix.lower() not in ('.png','.jpg','.jpeg'):raise ValueError('Invalid annotation image')
                self.file(path);return
            if p=='/api/recognition/status':
                self.json(lab.read(lab.DATA/'recognition/status.json',dict(phase='starting')));return
            if p=='/api/recognition/proposals':
                from recognition_review import proposals
                self.json(proposals(q['id'][0],int(q.get('after',['-1'])[0])));return
            if p=='/api/provisional':
                from provisional_queue import listing
                self.json(dict(jobs=listing()));return
            if p=='/api/live/rf':
                from rf_overlay import snapshot
                self.json(snapshot());return
            if p=='/api/live/artifact-status':
                sid=q.get('session',[''])[0]
                if not re.fullmatch(r'[0-9TZ]+-[a-f0-9]{6}',sid):raise ValueError('Invalid session')
                folder=lab.STATION/'sessions'/sid;manifest=lab.read(folder/'manifest.json',{});buffer=lab.read(folder/'buffer-state.json',{})
                self.json(dict(state=manifest.get('state','missing'),assembly=buffer.get('state'),playback=manifest.get('video_playback',{}).get('state'),available={name:(folder/name).is_file() for name in ('video.mkv','video.mp4','rf.jsonl')}));return
            if p=='/api/live/artifact':
                sid=q.get('session',[''])[0];name=q.get('name',[''])[0]
                if not re.fullmatch(r'[0-9TZ]+-[a-f0-9]{6}',sid):raise ValueError('Invalid session')
                if name not in ('video.mkv','video.mp4','rf.jsonl','manifest.json'):raise ValueError('Invalid artifact')
                self.file(lab.STATION/'sessions'/sid/name);return
            if p=='/api/model-publication/status':self.json(PUBLISHER.status() if PUBLISHER else dict(enabled=False,phase='disabled'));return
            if p=='/api/live/session':self.json(LIVE.session_status());return
            if p=='/api/live/status':
                self.json(LIVE.state if LIVE else dict(phase='starting'));return
            if p=='/api/live/frame':
                data=LIVE.image if LIVE else None
                if not data:self.send_error(503);return
                self.send_response(200);self.send_header('Content-Type','image/jpeg');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data);return
            if p=='/api/state':
                videos=lab.library_videos()
                runs=[lab.read(p/'run.json') for p in (lab.DATA/'runs').iterdir() if p.is_dir()]
                self.json(dict(token=TOKEN,publication=PUBLISHER.status() if PUBLISHER else dict(enabled=False),labels=lab.LABELS,videos=sorted(videos,key=lambda v:-v['created']),model=lab.read(lab.DATA/'active-model.json'),runs=sorted(filter(None,runs),key=lambda r:-r['created']),free_bytes=shutil.disk_usage(lab.DATA).free));return
            if p=='/api/video':
                folder=lab.video_path(q['id'][0]);meta=lab.read(folder/'video.json')
                if meta and meta.get('preview_state')=='ready':self.file(folder/'preview.mp4','video/mp4');return
                self.file(folder/'source',meta.get('mime','video/mp4') if meta else None);return
            if p=='/api/frame':
                folder=lab.video_path(q['id'][0]);seconds=float(q.get('time',['0'])[0]);meta=lab.read(folder/'video.json')
                if not meta or not 0<=seconds<meta['duration']:raise ValueError('Invalid video time')
                _,data=lab.frame_at(folder,seconds);self.send_response(200);self.send_header('Content-Type','image/png');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
            if p=='/api/timeline':self.json(lab.timeline(lab.video_path(q['id'][0])));return
            if p=='/api/review-progress':self.json(lab.read(lab.video_path(q['id'][0])/'review-progress.json',dict(state='waiting',completed=0,total=0)));return
            if p.startswith('/results/'):
                relative=unquote(p[len('/results/'):]);path=(lab.DATA/'runs'/relative).resolve()
                if not path.is_relative_to((lab.DATA/'runs').resolve()):raise ValueError('Invalid result path')
                if path.is_dir():
                    files=sorted(path.iterdir());base=p.rstrip('/')+'/'
                    from urllib.parse import quote
                    content=('<!doctype html><meta name="viewport" content="width=device-width"><title>Lab output files</title><style>body{background:#10191e;color:#e8eef0;font:17px system-ui;padding:24px}a{color:#92ded0}li{margin:12px}</style><h1>Output files</h1><ul>'+''.join('<li><a href="'+base+quote(v.name)+('/' if v.is_dir() else '')+'">'+html.escape(v.name)+('/' if v.is_dir() else '')+'</a></li>' for v in files)+'</ul>').encode()
                    self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content);return
                self.file(path);return
            names={'/email-review':'email-review.html','/email-review.js':'email-review.js','/labels':'labels.html','/labels.js':'labels.js','/':'index.html','/events':'events.html','/events.js':'events.js','/tracks':'tracks.html','/tracks.js':'tracks.js','/app.js':'app.js','/style.css':'style.css'}
            if p in names:self.file(lab.ROOT/'static'/names[p]);return
            self.send_error(404)
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception as e:self.json(dict(error=str(e)),400)
    def do_POST(self):
        folder=None
        try:
            origin=self.headers.get('Origin')
            if self.headers.get('X-Lab-Token')!=TOKEN or (origin and urlsplit(origin).netloc!=self.headers.get('Host')):self.json(dict(error='Reload this page to reconnect securely.'),403);return
            p=urlsplit(self.path);length=int(self.headers.get('Content-Length','0'))
            if p.path=='/api/upload':
                if length<=0 or length>30*1024**3:raise ValueError('Choose a video smaller than 30 GiB')
                lab.space_check(length);name=parse_qs(p.query).get('name',['video.mp4'])[0]
                suffix=lab.Path(name).suffix.lower()
                if suffix not in ('.mp4','.mov','.mkv','.webm','.avi','.m4v','.mts'):raise ValueError('Unsupported video extension')
                vid=uuid.uuid4().hex;folder=lab.video_path(vid);folder.mkdir();remaining=length;digest=lab.hashlib.sha256()
                self.connection.settimeout(180)
                with (folder/'upload.part').open('wb') as f:
                    while remaining:
                        lab.space_check();data=self.rfile.read(min(1024*1024,remaining))
                        if not data:raise ValueError('Upload interrupted')
                        f.write(data);digest.update(data);remaining-=len(data)
                existing=lab.find_video_by_sha(digest.hexdigest())
                if existing and (lab.video_path(existing['id'])/'source').is_file():
                    shutil.rmtree(folder);folder=None
                    canonical=next(v for v in lab.library_videos() if v['id']==existing['id'])
                    self.json(dict(**canonical,duplicate=True));return
                (folder/'upload.part').rename(folder/'source');meta=lab.probe(folder/'source')
                if meta['duration']<=0:raise ValueError('Video duration unavailable')
                meta.update(id=vid,name=lab.Path(name).name,created=time.time(),bytes=length,sha256=digest.hexdigest(),mime=mimetypes.guess_type(name)[0] or 'video/mp4')
                needs_preview=not (suffix in ('.mp4','.m4v','.mov') and meta['codec']=='h264')
                if needs_preview:meta['preview_state']='preparing'
                lab.save(folder/'video.json',meta)
                if needs_preview:threading.Thread(target=lab.prepare_preview,args=(folder,),daemon=True).start()
                folder=None;self.json(meta);return
            if length>1024*1024:raise ValueError('Request too large')
            value=json.loads(self.rfile.read(length) or '{}')
            if p.path=='/api/email-review/delete':
                from email_review import remove_review
                self.json(remove_review(lab.DATA,value));return
            if p.path=='/api/email-review/save':
                from email_review import save_review
                self.json(save_review(lab.DATA,value));return
            if p.path=='/api/live/start':self.json(LIVE.manual_start(value));return
            if p.path=='/api/live/stop':self.json(LIVE.manual_stop(value));return
            if p.path=='/api/live/configure':self.json(LIVE.configure(value));return
            if p.path=='/api/omit':
                target=lab.video_path(value['id']);meta=lab.read(target/'video.json')
                if not meta:raise ValueError('Video not found')
                excluded=dict(excluded=True,omitted_at=time.time());lab.save(target/'training-excluded.json',excluded)
                if meta.get('sha256'):
                    with lab.LOCK:
                        omitted=lab.read(lab.DATA/'omitted-videos.json',{});omitted[meta['sha256']]=excluded;lab.save(lab.DATA/'omitted-videos.json',omitted)
                self.json(excluded);return
            if p.path=='/api/tracks/link':
                from track_review import link
                result=link(value['id'],value['annotations'])
                if value.get('train'):
                    try:
                        with lab.LOCK:model=lab.train()
                        result.update(model_id=model['id'],temporal_windows=model.get('temporal',{}).get('windows',0))
                    except Exception as exc:result['training_error']=str(exc)
                self.json(result);return
            if p.path=='/api/review':
                review=lab.complete_review(value['id'],value.get('targets',[]),value.get('no_target',False),value if value.get('bounds') else None)
                self.json(dict(**review,annotations=lab.read(lab.video_path(value['id'])/'annotations.json',[])));return
            if p.path=='/api/annotate':self.json(dict(annotations=lab.annotate(value['id'],value['time'],value['bounds'],value['label'])));return
            if p.path=='/api/delete-annotation':
                from labeled_frames import remove
                self.json(remove(value['id'],value['annotation']));return
            if p.path=='/api/train':
                with lab.LOCK:model=lab.train()
                self.json(model);return
            if p.path=='/api/test':self.json(dict(id=lab.start_run(value['id'],value.get('threshold',.85),value.get('labels',['anomalous']))));return
            self.send_error(404)
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception as e:self.json(dict(error=str(e)),400)
        finally:
            if folder:shutil.rmtree(folder,ignore_errors=True)

if __name__=='__main__':
    from provisional_queue import watch as watch_provisional
    threading.Thread(target=watch_provisional,daemon=True).start()
    from station_intake import watch_station
    threading.Thread(target=watch_station,daemon=True).start()
    for p in (lab.DATA/'runs').glob('*/run.json'):
        r=lab.read(p,{})
        if not r.get('detached') and r.get('state') not in ('complete','failed'):r.update(state='failed',error='App restarted before this run finished. Start another test.');lab.save(p,r)
    threading.Thread(target=lab.watch_training_folder,daemon=True).start()
    from model_publisher import ModelPublisher
    PUBLISHER=ModelPublisher()
    if os.environ.get('UAP_LAB_LIVE','1')=='1':
        from live_monitor import LiveMonitor
        LIVE=LiveMonitor()
    port=int(os.environ.get('UAP_LAB_PORT','8091'));print(f'UAP training lab listening on {port}',flush=True)
    ThreadingHTTPServer(('0.0.0.0',port),Handler).serve_forever()

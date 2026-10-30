"""Camera-preview motion analysis, independent of archival video frame rate."""
import io
import math
import re
import secrets
import threading
import time
from collections import deque
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from motion_details import save_motion_details
from classification_labels import label_text,matching_region,effective_classification
from experiments import load, save, utc, file_info


FILTER_PRESETS = {
 'daytime': dict(pixel_threshold=18,min_area_percent=.002,max_area_percent=2.0,confirmation_seconds=.5,reference_seconds=.4,cloud_suppression=True),
 'nighttime': dict(pixel_threshold=12,min_area_percent=.0012,max_area_percent=2.0,confirmation_seconds=.4,reference_seconds=.8,cloud_suppression=True),
}

class SelectedTargetTracker:
    """Local normalized template matching; stop rather than follow a weak match."""
    def __init__(self, image, x, y):
        a=np.asarray(image,dtype=np.float32)
        self.x=max(8,min(a.shape[1]-8,int(x)));self.y=max(8,min(a.shape[0]-8,int(y)))
        self.template=a[self.y-8:self.y+8,self.x-8:self.x+8].copy()
        self.template-=self.template.mean()
        self.energy=float(np.sum(self.template**2))
        if np.std(self.template)<2:raise ValueError('No distinct detail at that point. Click directly on the target.')
        self.last_seen=time.time();self.confidence=1.;self.state='tracking'
    def update(self, image):
        a=np.asarray(image,dtype=np.float32);h,w=a.shape
        left=max(0,self.x-40);top=max(0,self.y-40)
        right=min(w,self.x+40);bottom=min(h,self.y+40)
        search=a[top:bottom,left:right]
        if min(search.shape)<16:self.state='lost';return
        windows=np.lib.stride_tricks.sliding_window_view(search,(16,16))
        sums=windows.sum(axis=(-2,-1));energy=(windows**2).sum(axis=(-2,-1))-sums**2/256
        dot=np.einsum('ijkl,kl->ij',windows,self.template,optimize=True)
        score=dot/np.sqrt(np.maximum(energy*self.energy,1e-6))
        iy,ix=np.unravel_index(np.argmax(score),score.shape);self.confidence=float(score[iy,ix])
        if self.confidence>=.65:
            self.x=left+int(ix)+8;self.y=top+int(iy)+8;self.last_seen=time.time();self.state='tracking'
        else:self.state='lost'
    def status(self):
        return dict(state=self.state,confidence=round(self.confidence,3),
                    left=self.x-12,top=self.y-12,right=self.x+12,bottom=self.y+12)


class SmallMotionTracker:
    """Require several nearby, direction-consistent changes; reject static flicker."""
    def __init__(self):self.tracks=[]
    def update(self, regions, now):
        candidates=[r for r in regions if 3<=r['pixels']<=100 and
                    r['right']-r['left']<=24 and r['bottom']-r['top']<=24]
        tracks=[];used=set();confirmed=[]
        for track in self.tracks:
            dt=now-track['time']
            if not 0<dt<=.7:continue
            options=[]
            for i,r in enumerate(candidates):
                if i in used:continue
                x=(r['left']+r['right'])/2;y=(r['top']+r['bottom'])/2
                dx=x-track['x'];dy=y-track['y'];distance=math.hypot(dx,dy)
                if not .5<=distance<=max(4,90*dt):continue
                vx,vy=track.get('velocity',(0,0))
                speed=math.hypot(vx,vy)
                if speed and (dx*vx+dy*vy)/(distance*speed)<.8:continue
                error=math.hypot(dx-vx*dt,dy-vy*dt) if speed else distance
                if speed and error>max(4,speed*dt*.7):continue
                options.append((error,i,x,y,dx/dt,dy/dt,r))
            if not options:continue
            _,i,x,y,vx,vy,r=min(options,key=lambda o:o[0]);used.add(i)
            updated=dict(x=x,y=y,time=now,start=track['start'],origin=track['origin'],
                         count=track['count']+1,velocity=(vx,vy))
            tracks.append(updated)
            if updated['count']>=4 and now-updated['start']>=.5 and math.hypot(x-updated['origin'][0],y-updated['origin'][1])>=6:
                confirmed.append(r)
        for i,r in enumerate(candidates):
            if i not in used:
                x=(r['left']+r['right'])/2;y=(r['top']+r['bottom'])/2
                tracks.append(dict(x=x,y=y,time=now,start=now,origin=(x,y),count=1))
        self.tracks=tracks[:40]
        return confirmed


def validate_polygon(points):
    if not isinstance(points,list) or not 3<=len(points)<=32:
        raise ValueError('Detection border needs 3 to 32 points.')
    result=[]
    for point in points:
        if not isinstance(point,(list,tuple)) or len(point)!=2:
            raise ValueError('Each border point needs x and y percentages.')
        try:x,y=map(float,point)
        except (TypeError,ValueError):raise ValueError('Border coordinates must be numbers.')
        if not all(math.isfinite(v) and 0<=v<=100 for v in (x,y)):
            raise ValueError('Border points must be inside the image (0–100%).')
        result.append([x,y])
    if len({tuple(point) for point in result})!=len(result):raise ValueError('Border points must be distinct.')
    def orient(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    def between(a,b,c):return min(a[0],b[0])-1e-9<=c[0]<=max(a[0],b[0])+1e-9 and min(a[1],b[1])-1e-9<=c[1]<=max(a[1],b[1])+1e-9
    n=len(result)
    for i,a in enumerate(result):
        b=result[(i+1)%n]
        for j in range(i+1,n):
            if j==i+1 or (i==0 and j==n-1):continue
            c,d=result[j],result[(j+1)%n]
            x1,x2,x3,x4=orient(a,b,c),orient(a,b,d),orient(c,d,a),orient(c,d,b)
            crossing=(x1*x2<0 and x3*x4<0) or any(abs(v)<1e-9 and between(u,w,t) for v,u,w,t in ((x1,a,b,c),(x2,a,b,d),(x3,c,d,a),(x4,c,d,b)))
            if crossing:raise ValueError('Detection border edges cannot cross or touch each other.')
    area=abs(sum(result[i][0]*result[(i+1)%n][1]-result[(i+1)%n][0]*result[i][1] for i in range(n)))/2
    if area<10:raise ValueError('Detection border must cover at least 0.1% of the image.')
    return result


def region_geometry(config,width,height):
    polygon=config.get('roi_polygon')
    if not polygon:
        x=int(width*config.get('roi_left',0)/100);y=int(height*config.get('roi_top',0)/100)
        right=int(width*config.get('roi_right',100)/100);bottom=int(height*config.get('roi_bottom',100)/100)
        return (x,y,right,bottom),np.ones((bottom-y,right-x),dtype=bool)
    vertices=[(round(px*(width-1)/100),round(py*(height-1)/100)) for px,py in polygon]
    x=min(p[0] for p in vertices);y=min(p[1] for p in vertices)
    right=max(p[0] for p in vertices)+1;bottom=max(p[1] for p in vertices)+1
    mask=Image.new('1',(right-x,bottom-y))
    ImageDraw.Draw(mask).polygon([(px-x,py-y) for px,py in vertices],fill=1)
    return (x,y,right,bottom),np.asarray(mask,dtype=bool)


def motion_array(image, suppress_clouds=False):
    values=np.asarray(image)
    if not suppress_clouds:return values
    # Remove broad, slowly varying brightness structure while retaining detail.
    blurred=np.asarray(image.filter(ImageFilter.GaussianBlur(4)))
    return np.clip(values.astype(np.int16)-blurred.astype(np.int16)+128,0,255).astype(np.uint8)


def motion_mask(before, after, threshold, region=None):
    delta = after.astype(np.int16)-before.astype(np.int16)
    # Remove a uniform exposure shift; require neighboring changed pixels.
    sample=delta[::8,::8]
    if region is not None:sample=sample[region[::8,::8]]
    delta -= int(np.median(sample)) if sample.size else 0
    changed = np.abs(delta)>=threshold
    if region is not None:changed &= region
    neighbors = np.zeros(changed.shape, dtype=np.uint8)
    for dy in (-1,0,1):
        for dx in (-1,0,1):
            neighbors[1:-1,1:-1] += changed[1+dy:changed.shape[0]-1+dy,1+dx:changed.shape[1]-1+dx]
    mask = changed & (neighbors>=3)
    return mask


def group_regions(regions, gap=12):
    """Join overlapping/nearby fragments, keeping distant objects separate."""
    groups=[dict(r) for r in regions]
    while True:
        joined=False
        for i,a in enumerate(groups):
            for j in range(i+1,len(groups)):
                b=groups[j]
                if (a['left']<=b['right']+gap and b['left']<=a['right']+gap
                        and a['top']<=b['bottom']+gap and b['top']<=a['bottom']+gap):
                    groups[i]=dict(left=min(a['left'],b['left']),top=min(a['top'],b['top']),
                        right=max(a['right'],b['right']),bottom=max(a['bottom'],b['bottom']),pixels=a['pixels']+b['pixels'])
                    groups.pop(j);joined=True;break
            if joined:break
        if not joined:return sorted(groups,key=lambda r:r['pixels'],reverse=True)


def compact_region(region):
    width=max(1,region['right']-region['left']);height=max(1,region['bottom']-region['top'])
    # Cloud edges can contain many pixels but occupy very little of their bounds.
    return region['pixels']>=24 and region['pixels']/(width*height)>=.14


def motion_score(before, after, threshold, region=None, compact=False):
    mask=motion_mask(before,after,threshold,region)
    denominator=np.count_nonzero(region) if region is not None else mask.size
    count=max((r['pixels'] for r in group_regions(changed_regions(mask)) if compact_region(r)),default=0) if compact else np.count_nonzero(mask)
    return float(count*100/denominator) if denominator else 0


def changed_regions(mask):
    """Eight-connected components via row runs; coordinates are exclusive at right/bottom."""
    parents=[];runs=[];previous=[]
    def find(i):
        while parents[i]!=i:
            parents[i]=parents[parents[i]];i=parents[i]
        return i
    for y,row in enumerate(mask):
        edges=np.flatnonzero(np.diff(np.pad(row.astype(np.int8),(1,1))))
        current=[];j=0
        for left,right in zip(edges[::2],edges[1::2]):
            left,right=int(left),int(right)
            index=len(parents);parents.append(index);runs.append((left,y,right,right-left))
            while j<len(previous) and previous[j][1]<left:j+=1
            k=j
            while k<len(previous) and previous[k][0]<=right:
                parents[find(index)]=find(previous[k][2]);k+=1
            current.append((left,right,index))
        previous=current
    groups={}
    for i,(left,y,right,count) in enumerate(runs):
        key=find(i)
        if key not in groups:groups[key]=dict(left=left,top=y,right=right,bottom=y+1,pixels=0)
        g=groups[key];g.update(left=min(g['left'],left),top=min(g['top'],y),
            right=max(g['right'],right),bottom=max(g['bottom'],y+1),pixels=g['pixels']+count)
    return sorted((g for g in groups.values() if g['pixels']>=3),key=lambda g:g['pixels'],reverse=True)[:20]


def annotate_motion(before,after,config,target,classification=None):
    """Illustrate changes on the frame with visible detail; preserve both originals."""
    originals=[Image.open(io.BytesIO(raw)).convert('RGB') for raw in (before,after)]
    if originals[0].size!=originals[1].size:raise ValueError('Motion evidence dimensions differ')
    width=int(config.get('analysis_width',640));height=round(width*originals[0].height/originals[0].width)
    (x,y,right,bottom),region=region_geometry(config,width,height)
    arrays=[]
    for raw in (before,after):
        im=Image.open(io.BytesIO(raw));im.draft('L',(width,height));im=im.convert('L')
        if im.size!=(width,height):im=im.resize((width,height))
        arrays.append(motion_array(im,config.get('cloud_suppression',False))[y:bottom,x:right])
    boxes=group_regions(changed_regions(motion_mask(*arrays,config['pixel_threshold'],region)),gap=max(3,round(width/160)))
    if config.get('cloud_suppression'):boxes=[b for b in boxes if compact_region(b)]
    sx,sy=originals[0].width/width,originals[0].height/height
    gray=[im.convert('L') for im in originals]
    mapped=[];strength=[0.0,0.0]
    for box in boxes:
        item=dict(left=max(0,int((box['left']+x)*sx)),top=max(0,int((box['top']+y)*sy)),
            right=min(originals[0].width,int(np.ceil((box['right']+x)*sx))),
            bottom=min(originals[0].height,int(np.ceil((box['bottom']+y)*sy))),changed_analysis_pixels=box['pixels'])
        rect=(max(0,item['left']-4),max(0,item['top']-4),min(originals[0].width,item['right']+4),min(originals[0].height,item['bottom']+4))
        contrast=[float(np.std(np.asarray(im.crop(rect)))) for im in gray]
        source='before' if contrast[0]>contrast[1]*1.2+2 else 'after' if contrast[1]>contrast[0]*1.2+2 else 'both'
        item['visible_in']=source
        for i,value in enumerate(contrast):strength[i]+=value*box['pixels']
        mapped.append(item)
    selected=0 if strength[0]>strength[1]*1.1+2 else 1
    source_frame=('before','after')[selected]
    clean_original=originals[selected].copy()
    original=originals[selected];draw=ImageDraw.Draw(original)
    visible=[item for item in mapped if item['visible_in'] in (source_frame,'both')]
    visible=[item for item in visible if (matching_region(item,(classification or {}).get('regions',[])) or {}).get('object',{}).get('label')!='cloud']
    for number,item in enumerate(visible,1):
        padding=max(24,round(max(item['right']-item['left'],item['bottom']-item['top'])*.3))
        rect=(max(0,item['left']-padding),max(0,item['top']-padding),min(original.width-1,item['right']+padding),min(original.height-1,item['bottom']+padding))
        item['review_bounds']=dict(zip(('left','top','right','bottom'),rect))
        draw.rectangle(rect,outline='#ffcf33',width=3)
        match=matching_region(item,(classification or {}).get('regions',[]))
        item['label']=label_text(match) if match else 'Motion | analyzing'
        title=f'T{number}: '+item['label']
        font=ImageFont.load_default(size=18)
        bounds=draw.textbbox((0,0),title,font=font)
        tx=min(rect[0],max(0,original.width-(bounds[2]-bounds[0])-8));ty=max(0,rect[1]-26)
        draw.rectangle((tx,ty,tx+bounds[2]-bounds[0]+6,ty+24),fill='#071013')
        draw.text((tx+3,ty+2),title,font=font,fill='#ffcf33')
    label='EARLIER COMPARISON FRAME' if selected==0 else 'LATER CONFIRMATION FRAME'
    draw.text((12,original.height-24),label+' - suggested labels; originals retained',fill='white',stroke_width=1,stroke_fill='black')
    temporary=target.with_suffix('.tmp')
    original.save(temporary,format='JPEG',quality=95);temporary.replace(target)
    details=save_motion_details(clean_original,visible,target,source_frame)
    return dict(boxes=visible,detail_images=details,changed_regions=mapped,source_frame=source_frame,annotation_version=3,
        frame_width=original.width,frame_height=original.height,
        meaning='Boxes are shown on the frame with stronger local detail. Both original frames are retained; this is not object classification.')


class MotionTrigger:
    def __init__(self, station, run, preview):
        self.station, self.preview = station, preview
        self.path = run/'motion-trigger.json'
        self.config = dict(filter_profile="custom",enabled=False, duration_minutes=3, cooldown_minutes=0,
            pre_roll_seconds=10,post_roll_seconds=10,analysis_fps=10, analysis_width=1920, pixel_threshold=25, min_area_percent=0.5,
            max_area_percent=40, confirmation_seconds=0.5, reference_seconds=0.5,cloud_suppression=False,
            roi_left=0, roi_top=0, roi_right=100, roi_bottom=100,roi_polygon=None)
        stored = load(self.path,{})
        self.last_motion_epoch=None
        self.motion_run_since=None
        self.latest_pair=None
        self.last_fired = stored.pop('last_fired_epoch',0)
        self.config.update(stored)
        self.phase, self.error = 'disabled', None
        self.manual_tracker=None
        self.manual_overlay=None
        self.small_tracker=SmallMotionTracker()
        self.live_overlay = dict(frame_epoch=0, boxes=[])
        self.score, self.actual_fps = 0, 0
        self.last_event = load(run/'motion-trigger-last-event.json')
        self.pending = None
        self.history = deque()
        self.candidate_since = None
        self.quiet_since = None
        self.latched = False
        self.generation = 0
        self.worker = threading.Thread(target=self.analyze,daemon=True)
        self.worker.start()

    def status(self):
        return dict(**self.config, phase=self.phase, error=self.error, changed_area_percent=self.score,
            actual_analysis_fps=round(self.actual_fps,1),
            last_event=self.last_event, cooldown_until_epoch=self.last_fired+self.config['cooldown_minutes']*60)

    def select_target(self, body):
        if body.get('stop'):
            self.manual_tracker=None;self.manual_overlay=None
            return dict(state='stopped')
        try:x,y=float(body['x']),float(body['y'])
        except (KeyError,TypeError,ValueError):raise ValueError('Select a point on the preview.')
        if not all(math.isfinite(v) and 0<=v<=1 for v in (x,y)):raise ValueError('Target must be inside the image.')
        if time.time()-self.preview.stat().st_mtime>2:raise ValueError('No fresh camera frame')
        raw=self.preview.read_bytes();im=Image.open(io.BytesIO(raw)).convert('L')
        tracker=SelectedTargetTracker(im,x*im.width,y*im.height)
        with self.station.lock:
            self.manual_tracker=tracker
            self.manual_overlay=dict(width=im.width,height=im.height,frame_epoch=time.time(),**tracker.status())
            event=dict(id=secrets.token_hex(8),detected_at=utc(),detected_epoch=time.time(),
                       motion_started_epoch=time.time(),changed_area_percent=0,settings=self.config.copy(),
                       algorithm='user-selected-template-v1',user_selected=True,selected_point=dict(x=x,y=y))
            self.pending=(event,raw,raw)
            self.last_motion_epoch=time.time()
        return self.manual_overlay

    def overlay(self):
        data=self.live_overlay
        manual=self.manual_overlay
        if manual and time.time()-manual['frame_epoch']<2:
            data=dict(data,manual_target=manual)

        if not self.config["enabled"] or time.time()-data["frame_epoch"]>1:
            return dict(frame_epoch=0,boxes=[],manual_target=manual if manual and time.time()-manual['frame_epoch']<2 else None)
        classifier=getattr(self.station,'classifier',None)
        return classifier.decorate_overlay(data) if classifier else data

    def configure(self, body):
        with self.station.lock:
            cfg = self.config.copy()
            requested=body.get('filter_profile')
            if requested is not None:
                if requested not in FILTER_PRESETS and requested!='custom':
                    raise ValueError('Unknown motion filter profile')
                if requested in FILTER_PRESETS:cfg.update(FILTER_PRESETS[requested])
                cfg['filter_profile']=requested
            if any(k in body for k in FILTER_PRESETS['daytime']):cfg['filter_profile']='custom'

            limits = dict(pre_roll_seconds=(0,30),post_roll_seconds=(1,60),duration_minutes=(1,120),cooldown_minutes=(0,1440),analysis_fps=(1,60),analysis_width=(640,1920),
                pixel_threshold=(5,255),min_area_percent=(0.0001,30),max_area_percent=(1,100),
                confirmation_seconds=(0.1,10),reference_seconds=(0.1,5),
                roi_left=(0,99),roi_top=(0,99),roi_right=(1,100),roi_bottom=(1,100))
            for k,(low,high) in limits.items():
                v=float(body.get(k,cfg[k]))
                if not math.isfinite(v) or not low<=v<=high:
                    raise ValueError(f'{k} must be between {low} and {high}.')
                if k in ('duration_minutes','analysis_fps','analysis_width','pixel_threshold'):
                    if v!=int(v): raise ValueError(k+' must be a whole number.')
                    v=int(v)
                cfg[k]=v
            if 'roi_polygon' in body:
                cfg['roi_polygon']=validate_polygon(body['roi_polygon']) if body['roi_polygon'] is not None else None
            elif any(k in body for k in ('roi_left','roi_top','roi_right','roi_bottom')):
                cfg['roi_polygon']=None
            if cfg['roi_polygon'] is None and (cfg['roi_right']-cfg['roi_left']<5 or cfg['roi_bottom']-cfg['roi_top']<5):
                raise ValueError('Motion region must be at least 5% wide and high.')
            if cfg['min_area_percent']>=cfg['max_area_percent']:
                raise ValueError('Maximum changed area must exceed minimum changed area.')
            cfg['enabled']=bool(body.get('enabled',cfg['enabled']))
            cfg['cloud_suppression']=bool(body.get('cloud_suppression',cfg['cloud_suppression']))
            self.config=cfg
            if hasattr(self.station,'buffer'):self.station.buffer.keep_seconds=cfg['pre_roll_seconds']+8
            self.live_overlay=dict(frame_epoch=0,boxes=[])
            self.generation+=1
            self.pending=None
            self.error=None
            save(self.path,dict(**cfg,last_fired_epoch=self.last_fired))
            return self.status()

    def analyze(self):
        stamp=None
        generation=-1
        measured=deque()
        region_key=None
        while not self.station.exiting.is_set():
            began=time.monotonic()
            cfg=self.config.copy()
            try:
                if generation!=self.generation:
                    self.history.clear()
                    self.small_tracker.tracks=[]
                    self.candidate_since=None
                    self.motion_run_since=None
                    self.latched=False
                    self.quiet_since=None
                    self.small_reference=None
                    generation=self.generation
                if not cfg['enabled'] and self.manual_tracker is None:
                    self.phase='disabled'
                    self.history.clear()
                else:
                    stat=self.preview.stat()
                    if time.time()-stat.st_mtime>2:
                        self.phase='waiting_for_camera'
                        self.history.clear()
                        self.candidate_since=None
                    elif stat.st_mtime_ns!=stamp:
                        stamp=stat.st_mtime_ns
                        raw=self.preview.read_bytes()
                        im=Image.open(io.BytesIO(raw))
                        width=cfg['analysis_width']
                        height=round(width*im.height/im.width)
                        im.draft('L',(width,height))
                        im=im.convert('L')
                        if im.size!=(width,height): im=im.resize((width,height))
                        tracker=self.manual_tracker
                        if tracker is not None:
                            native=Image.open(io.BytesIO(raw)).convert('L')
                            tracker.update(native)
                            if self.manual_tracker is tracker:
                                self.manual_overlay=dict(width=native.width,height=native.height,
                                    frame_epoch=stat.st_mtime,**tracker.status())
                                if tracker.state=='tracking':self.last_motion_epoch=time.time()
                                elif time.time()-tracker.last_seen>2:self.manual_tracker=None
                        if not cfg['enabled']:continue
                        a=motion_array(im,cfg.get('cloud_suppression',True))
                        h,w=a.shape
                        key=(w,h,tuple(tuple(p) for p in cfg.get('roi_polygon') or []),cfg['roi_left'],cfg['roi_top'],cfg['roi_right'],cfg['roi_bottom'])
                        if key!=region_key:
                            region_key=key
                            (rx,ry,rr,rb),region=region_geometry(cfg,w,h)
                            self.history.clear()
                            self.candidate_since=None
                            self.motion_run_since=None
                        a=a[ry:rb,rx:rr]
                        now=time.monotonic()
                        if self.history and now-self.history[-1][0]>1:
                            self.history.clear()
                            self.candidate_since=None
                        measured.append(now)
                        while measured and now-measured[0]>5: measured.popleft()
                        self.actual_fps=(len(measured)-1)/(now-measured[0]) if len(measured)>1 else 0
                        if not self.history or now-self.history[0][0]<cfg['reference_seconds']:
                            self.phase='warming_up'
                        else:
                            while len(self.history)>1 and now-self.history[1][0]>=cfg['reference_seconds']:
                                self.history.popleft()
                            reference=self.history[0]
                            mask=motion_mask(reference[1],a,cfg['pixel_threshold'],region)
                            boxes=group_regions(changed_regions(mask))
                            if cfg.get('cloud_suppression',True):
                                boxes=[b for b in boxes if compact_region(b)]
                                count=max((b['pixels'] for b in boxes),default=0)
                            else:count=np.count_nonzero(mask)
                            denominator=np.count_nonzero(region)
                            self.score=float(count*100/denominator) if denominator else 0
                            tracked=[]
                            if cfg.get('filter_profile')=='nighttime':
                                raw_array=np.asarray(im)[ry:rb,rx:rr]
                                if self.small_reference is not None:
                                    previous,previous_time=self.small_reference
                                    if previous.shape==raw_array.shape and now-previous_time<.7:
                                        tiny=changed_regions(motion_mask(previous,raw_array,cfg['pixel_threshold'],region))
                                        tracked=self.small_tracker.update(tiny,now)
                                self.small_reference=(raw_array.copy(),now)
                            hit=(cfg['min_area_percent']<=self.score<=cfg['max_area_percent'] or bool(tracked))
                            if tracked:boxes=tracked+boxes

                            if hit:
                                self.motion_run_since=self.motion_run_since or now
                                if now-self.motion_run_since>=cfg['confirmation_seconds']:
                                    self.last_motion_epoch=time.time()
                                    self.latest_pair=(reference[2],raw)
                            else:
                                self.motion_run_since=None
                            confirmed=bool(hit and self.motion_run_since is not None and
                                now-self.motion_run_since>=cfg['confirmation_seconds'])
                            self.live_overlay=dict(frame_epoch=stat.st_mtime,width=w,height=h,
                                boxes=[dict(left=b['left']+rx,top=b['top']+ry,right=b['right']+rx,bottom=b['bottom']+ry)
                                       for b in boxes[:20] if b in tracked or b['pixels']*100/denominator>=cfg['min_area_percent']]
                                      if confirmed and denominator else [])
                            if not hit:
                                self.candidate_since=None
                                self.quiet_since=self.quiet_since or now
                                if now-self.quiet_since>=1: self.latched=False
                            else: self.quiet_since=None
                            cooldown=time.time()<self.last_fired+cfg['cooldown_minutes']*60
                            self.phase='cooldown' if cooldown else 'waiting_for_quiet' if self.latched else 'armed'
                            if self.score>cfg['max_area_percent']:
                                self.phase='scene_change_rejected'
                            if hit and not cooldown and not self.latched and not self.pending:
                                self.candidate_since=self.candidate_since or now
                                self.phase='confirming_motion'
                                if now-self.candidate_since>=cfg['confirmation_seconds']:
                                    event=dict(id=secrets.token_hex(8),detected_at=utc(),detected_epoch=time.time(),
                                        motion_started_epoch=time.time()-(now-self.candidate_since),
                                        changed_area_percent=self.score, settings=cfg,algorithm='night-small-trajectory-v1' if tracked else 'grouped-compact-detail-v4' if cfg.get('cloud_suppression') else 'native-detail-exposure-compensated-v2')
                                    if tracked:
                                        event['small_motion_regions']=[dict(b,left=b['left']+rx,right=b['right']+rx,top=b['top']+ry,bottom=b['bottom']+ry) for b in tracked]
                                    self.pending=(event,reference[2],raw)
                                    self.latched=True
                                    self.candidate_since=None
                        self.history.append((now,a.copy(),raw))
                        self.error=None
            except (OSError,ValueError) as e:
                self.error=str(e)
                self.phase='waiting_for_camera'
                self.history.clear()
                self.candidate_since=None
            self.station.exiting.wait(max(0.001,1/cfg['analysis_fps']-(time.monotonic()-began)))

    def handoff(self, previous):
        if (not self.config['enabled'] or not self.latest_pair or not previous.get('motion_events') or
                not self.last_motion_epoch or time.time()-self.last_motion_epoch>=self.config['post_roll_seconds']):
            return
        before,after=self.latest_pair
        event=dict(id=secrets.token_hex(8),detected_at=utc(),detected_epoch=time.time(),
            motion_started_epoch=self.last_motion_epoch,trigger_frame_epoch=self.last_motion_epoch,
            changed_area_percent=self.score,settings=self.config.copy(),
            algorithm='native-detail-exposure-compensated-v2',continued_from_session=previous['id'])
        self.pending=(event,before,after)

    def recording_end(self, active):
        last=max(active['motion_onset_epoch'],self.last_motion_epoch or 0)
        return max(last+active['post_roll_seconds'],active.get('rf_required_until_epoch',0))

    def annotate_event(self, body):
        sid=str(body.get('session_id',''));eid=str(body.get('event_id',''))
        if not re.fullmatch(r'[0-9TZ]+-[a-f0-9]{6}',sid) or not re.fullmatch(r'[a-f0-9]{16}',eid):
            raise ValueError('Invalid motion event')
        with self.station.lock:
            folder=self.station.data_path(sid)
            manifest=load(folder/'manifest.json',{})
            events=load(folder/'motion-events.json',[])
            event=next((e for e in events if e['id']==eid),None)
            if not event:raise ValueError('Motion event not found')
            target=folder/f'motion-{eid}-boxed.jpg'
            if event.get('human_review'):
                from boxed_review import render_review
                raw=Image.open(self.station.boxed_review.image(sid+'--'+target.name,True))
                event['annotation']=render_review(raw,event['human_review'],target)
            else:
                event['annotation']=annotate_motion((folder/f'motion-{eid}-before.jpg').read_bytes(),
                    (folder/f'motion-{eid}-after.jpg').read_bytes(),event['settings'],target,classification=effective_classification(event))
            event['annotated_frame']=target.name
            for e in manifest.get('motion_events',[]):
                if e['id']==eid:e.update(event)
            manifest.setdefault('files',{})[target.name]=file_info(target)
            if self.station.active and self.station.active['id']==sid:
                self.station.active.update(motion_events=manifest['motion_events'])
            save(folder/'motion-events.json',events)
            save(folder/'manifest.json',manifest)
            return event

    def tick(self):
        if self.config['enabled'] and self.station.active is None and self.pending is None and self.latched:
            # A latch belongs to a recording, not the lifetime of the detector.
            self.latched=False
            self.candidate_since=None
            self.quiet_since=None
            self.phase='armed'
        pending=self.pending
        if not pending or (not self.config['enabled'] and not pending[0].get('user_selected')): return
        event,before,after=pending
        try:
            if time.time()-event['detected_epoch']>30:
                event.update(action='missed_capture',reason=self.error or 'Capture could not start within 30 seconds')
            else:
                if not self.station.active:
                    if not self.station.experiments.pause_exports():
                        raise ValueError('Waiting for frame export to pause')
                    try:
                        self.station.start(dict(title='Motion trigger · '+utc(),condition='silence',
                            minutes=self.config['duration_minutes']),motion_event=event)
                    except (ValueError,OSError):
                        self.station.experiments.resume_exports()
                        raise
                    event['action']='started_recording'
                else:
                    event['action']='annotated_existing_recording'
                active=self.station.active
                elapsed=time.monotonic()-active['started_monotonic']
                event['session_id']=active['id']
                folder=self.station.data_path(active['id'])
                for suffix,data in [('before',before),('after',after)]:
                    (folder/f'motion-{event["id"]}-{suffix}.jpg').write_bytes(data)
                boxed=folder/f'motion-{event["id"]}-boxed.jpg'
                event['annotation']=annotate_motion(before,after,event.get('settings',self.config),boxed)
                event['annotated_frame']=boxed.name
                event['evidence_files']=[f'motion-{event["id"]}-{suffix}.jpg' for suffix in ('before','after')]
                event['classification']=dict(state='queued',mode='label_only',version=0)
                events=load(folder/'motion-events.json',[])
                events.append(event)
                save(folder/'motion-events.json',events)
                active.setdefault('motion_events',[]).append(event.copy())
                active['markers'].append(dict(timestamp=event['detected_at'],elapsed_seconds=elapsed,
                    note=f'Motion confirmed: {event["changed_area_percent"]:.4f}% of analysis region changed'))
                save(folder/'manifest.json',active)
                classifier=getattr(self.station,'classifier',None)
                if classifier:
                    try:classifier.enqueue(active['id'],event['id'])
                    except ValueError as error:classifier.error=str(error)
            self.last_fired=time.time()
            save(self.path,dict(**self.config,last_fired_epoch=self.last_fired))
            self.last_event=event
            save(self.path.parent/'motion-trigger-last-event.json',event)
            self.pending=None
        except (OSError,ValueError) as e:
            self.error=str(e)
            self.phase='waiting_for_capture'

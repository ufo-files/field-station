"""Bounded coarse search with native-pixel confirmation for the saved template bank."""
import time
import cv2
import lab

class LiveMatcher:
    def __init__(self,templates,preview_width=512,budget=.6):
        self.templates=templates;self.preview_width=preview_width;self.budget=budget;self.cursor=0;self.pinned={};self.scaled=None;self.width=None;self.sweep_started=time.monotonic();self.sweep_seconds=None
    def predict(self,image,threshold,labels):
        h,w=image.shape[:2];scale=min(1,self.preview_width/w)
        if self.width!=w:
            self.width=w;self.scaled=[(f'{i}:{label}',cv2.resize(template,(max(1,round(template.shape[1]*scale)),max(1,round(template.shape[0]*scale))),interpolation=cv2.INTER_AREA)) for i,(label,template) in enumerate(self.templates)]
        small=cv2.resize(image,(round(w*scale),round(h*scale)),interpolation=cv2.INTER_AREA) if scale<1 else image
        now=time.monotonic();self.pinned=dict(sorted(((i,t) for i,t in self.pinned.items() if now-t<8),key=lambda item:-item[1])[:8]);indices=list(self.pinned);started=time.monotonic();results=[];visited=set();candidate_count=0
        while True:
            if not indices:
                for _ in range(min(8,len(self.templates))):
                    indices.append(self.cursor);self.cursor=(self.cursor+1)%len(self.templates)
                    if self.cursor==0:self.sweep_seconds=time.monotonic()-self.sweep_started;self.sweep_started=time.monotonic()
            batch=[i for i in indices if i not in visited];indices=[]
            if not batch:break
            visited.update(batch)
            coarse=lab.detect(small,[self.scaled[i] for i in batch],.78,[self.scaled[i][0] for i in batch],verify_detail=False)
            for proposal in coarse[:12]:
                i=int(proposal['label'].split(':',1)[0]);label,template=self.templates[i];x,y,bw,bh=[v/scale for v in proposal['box']];pad=max(12,int(max(bw,bh)*.25))
                left=max(0,int(x)-pad);top=max(0,int(y)-pad);right=min(w,int(x+bw)+pad);bottom=min(h,int(y+bh)+pad)
                if right<=left or bottom<=top:continue
                for match in lab.detect(image[top:bottom,left:right],[(label,template)],threshold,[label]):
                    match['box'][0]+=left;match['box'][1]+=top;match['template_index']=i;results.append(match);self.pinned[i]=now
                candidate_count+=1
            if time.monotonic()-started>=self.budget or len(visited)>=len(self.templates):break
        merged=[]
        for m in sorted(results,key=lambda v:-v['score']):
            x,y,bw,bh=m['box']
            def overlap(n):
                a,b,c,d=n['box'];area=max(0,min(x+bw,a+c)-max(x,a))*max(0,min(y+bh,b+d)-max(y,b));return area/max(1,min(bw*bh,c*d))
            if not any(overlap(n)>.35 for n in merged):merged.append(m)
        return [m for m in merged if m['label'] in labels],dict(templates_scanned=len(visited),template_count=len(self.templates),bank_sweep_seconds=self.sweep_seconds,search_seconds=round(time.monotonic()-started,3),native_candidates=candidate_count)

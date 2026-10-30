"""Search the complete bank on every frame with bounded parallel CPU work."""
from concurrent.futures import ThreadPoolExecutor
import os
import lab
from live_matcher import LiveMatcher

class BatchMatcher:
    def __init__(self,templates):
        workers=max(1,min(4,int(os.environ.get('UAP_LAB_MATCH_THREADS','2')),len(templates)))
        self.matchers=[LiveMatcher(templates[i::workers],preview_width=512,budget=float('inf')) for i in range(workers)]
        self.pool=ThreadPoolExecutor(max_workers=workers)
    def predict(self,image,threshold,labels):
        futures=[self.pool.submit(m.predict,image,threshold,lab.LABELS) for m in self.matchers]
        matches=[v for f in futures for v in f.result()[0]];result=[]
        for m in sorted(matches,key=lambda m:-m['score']):
            x,y,w,h=m['box']
            def overlaps(n):
                xx,yy,ww,hh=n['box'];area=max(0,min(x+w,xx+ww)-max(x,xx))*max(0,min(y+h,yy+hh)-max(y,yy))
                return area/max(1,min(w*h,ww*hh))>.35
            if not any(overlaps(n) for n in result):result.append(m)
        return [m for m in result if m['label'] in labels]
    def close(self):self.pool.shutdown(wait=True)

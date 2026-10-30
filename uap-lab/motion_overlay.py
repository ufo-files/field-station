"""Ephemeral motion visualization. No recording, persistence, or event API access."""
import cv2
import numpy as np

class MotionOverlay:
    def __init__(self):
        self.background=cv2.createBackgroundSubtractorMOG2(history=100,varThreshold=25,detectShadows=False)
        self.stamp=None;self.shape=None;self.frames=0;self.tracks=[];self.sequence=0;self.objects=[]
    def update(self,image,stamp):
        if self.stamp==stamp:return self.objects
        if self.stamp is not None and (stamp-self.stamp>2 or stamp<=self.stamp or image.shape!=self.shape):
            self.__init__()
        self.stamp=stamp;self.shape=image.shape;self.frames+=1
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim==3 else image
        mask=self.background.apply(cv2.GaussianBlur(gray,(3,3),0))
        h,w=gray.shape
        if self.frames<4 or np.count_nonzero(mask)>h*w*.25:
            self.objects=[];self.tracks=[];return []
        mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((2,2),np.uint8))
        mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
        _,_,stats,_=cv2.connectedComponentsWithStats(mask,8)
        candidates=[]
        for x,y,bw,bh,area in stats[1:]:
            if area<6 or area>h*w*.02 or min(bw,bh)<3:continue
            candidates.append((int(area),[int(x),int(y),int(bw),int(bh)]))
        remaining=list(self.tracks);tracks=[];objects=[]
        # A display limit only; it never changes recording or model decisions.
        for _,box in sorted(candidates,reverse=True)[:32]:
            x,y,bw,bh=box;cx=x+bw/2;cy=y+bh/2
            options=[t for t in remaining if abs(cx-t['cx'])+abs(cy-t['cy'])<max(60,3*max(bw,bh))]
            prior=min(options,key=lambda t:abs(cx-t['cx'])+abs(cy-t['cy'])) if options else None
            if prior:remaining.remove(prior);identity=prior['id']
            else:self.sequence+=1;identity=self.sequence
            tracks.append(dict(id=identity,cx=cx,cy=cy))
            objects.append(dict(box=box,motion_id=identity,label='motion',source='display_only'))
        self.tracks=tracks;self.objects=objects
        return objects

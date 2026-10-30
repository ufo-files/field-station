"""Native-resolution, every-frame candidate detector. Candidates are not anomalies."""
import cv2
import numpy as np

class NativeMotion:
    def __init__(self):
        self.background=None;self.last_pts=None
    def update(self,image,pts):
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim==3 else image
        reset=self.background is None or self.background.shape!=gray.shape or self.last_pts is None or not 0<pts-self.last_pts<.1
        self.last_pts=pts
        if reset:
            self.background=gray.astype(np.float32)
            return [],dict(warming=True,global_change=False)
        difference=cv2.absdiff(gray,cv2.convertScaleAbs(self.background))
        detail=cv2.absdiff(gray,cv2.GaussianBlur(gray,(5,5),1))
        # The background is updated for every real frame, never a sampled preview.
        cv2.accumulateWeighted(gray,self.background,.04)
        mask=cv2.bitwise_and(cv2.compare(difference,8,cv2.CMP_GE),cv2.compare(detail,5,cv2.CMP_GE))
        mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((2,2),np.uint8))
        mask=cv2.dilate(mask,np.ones((3,3),np.uint8))
        _,_,stats,_=cv2.connectedComponentsWithStats(mask,8)
        h,w=gray.shape;boxes=[]
        for x,y,bw,bh,area in stats[1:]:
            if area<6 or min(bw,bh)<3:continue
            # Diffuse regions are reported separately, not silently treated as negatives.
            if bw>w*.15 or bh>h*.15:continue
            boxes.append([int(x),int(y),int(bw),int(bh)])
        return boxes,dict(warming=False,global_change=bool(np.count_nonzero(difference>15)>w*h*.2),candidate_count=len(boxes))

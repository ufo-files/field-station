"""Recognize this station's Cam Link slate; darkness alone is never no signal."""
from pathlib import Path
import cv2
import numpy as np

class NoSignalDetector:
    def __init__(self):
        reference=cv2.imread(str(Path(__file__).with_name('elgato-no-signal-reference.jpg')),cv2.IMREAD_GRAYSCALE)
        self.reference=cv2.resize(reference,(320,180),interpolation=cv2.INTER_AREA) if reference is not None else None
    def matches(self,jpeg):
        if self.reference is None:return False
        frame=cv2.imdecode(np.frombuffer(jpeg,np.uint8),cv2.IMREAD_GRAYSCALE)
        if frame is None or abs(frame.shape[1]/frame.shape[0]-16/9)>.03:return False
        small=cv2.resize(frame,(320,180),interpolation=cv2.INTER_AREA)
        difference=cv2.absdiff(small,self.reference)
        # Require both the logo and NO SIGNAL lettering, not just a black field.
        for top,bottom in ((76,103),(110,119)):
            mask=self.reference[top:bottom]>100
            if not mask.any() or float(difference[top:bottom][mask].mean())>30:return False
        return float(difference.mean())<5

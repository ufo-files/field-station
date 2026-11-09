"""Anomalous-only broadcast annotations, following the camera page's display rules."""
import math
from PIL import Image, ImageDraw, ImageFont
from broadcast_rf import FONT

def number(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)

def visible_objects(state, now, standby=False):
    if standby or not isinstance(state,dict) or state.get('camera_no_signal'):
        return []
    groups=[]
    display=state.get('display_epoch');frame=state.get('frame_epoch')
    if number(display) and number(frame) and 0<=now-display<.5 and abs(frame-display)<.5:
        groups.append((state.get('display_tags',[]),1920,1080))
    epoch=state.get('inference_epoch')
    if number(epoch) and 0<=now-epoch<3:
        groups.append((state.get('objects',[]),state.get('width'),state.get('height')))
    result=[]
    for objects,width,height in groups:
        if not isinstance(objects,list) or not number(width) or not number(height) or width<=0 or height<=0:
            continue
        for obj in objects:
            if not isinstance(obj,dict) or obj.get('label')!='anomalous' or obj.get('source')=='display_only':
                continue
            box=obj.get('box')
            if not isinstance(box,(list,tuple)) or len(box)!=4 or not all(number(v) for v in box):
                continue
            x,y,w,h=box
            if w<=0 or h<=0 or x>=width or y>=height or x+w<=0 or y+h<=0:
                continue
            bounds=(max(0,x)/width,max(0,y)/height,min(width,x+w)/width,min(height,y+h)/height)
            result.append((bounds,obj))
    return result

class TagOverlay:
    def __init__(self):
        self.font=ImageFont.truetype(str(FONT),18)

    def draw(self,image,state,now,standby=False):
        draw=ImageDraw.Draw(image)
        for bounds,obj in visible_objects(state,now,standby):
            x,y,right,bottom=[round(value*(image.width if i%2==0 else image.height)) for i,value in enumerate(bounds)]
            right=min(image.width-1,right);bottom=min(image.height-1,bottom)
            color='#91ffda' if obj.get('confirmed') else '#ffcf33'
            if obj.get('confirmed'):
                draw.rectangle((x,y,right,bottom),outline=color,width=2)
            else:
                for start in range(x,right,12):
                    draw.line((start,y,min(start+8,right),y),fill=color,width=2)
                    draw.line((start,bottom,min(start+8,right),bottom),fill=color,width=2)
                for start in range(y,bottom,12):
                    draw.line((x,start,x,min(start+8,bottom)),fill=color,width=2)
                    draw.line((right,start,right,min(start+8,bottom)),fill=color,width=2)
            target=obj.get('target_id')
            text=(f'T{str(target)[:12]} · ' if target else '')+'Anomalous · Model'
            width=draw.textlength(text,font=self.font)+8
            tx=max(0,min(x,image.width-width));ty=max(0,y-28)
            draw.rectangle((tx,ty,tx+width,ty+27),fill=(7,16,19,220))
            draw.text((tx+4,ty+3),text,font=self.font,fill=color)
        return image

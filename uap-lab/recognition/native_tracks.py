"""Conservative trajectory proposals, explicitly distinct from human-confirmed tracks."""
import math
import numpy as np
class NativeTracks:
    def __init__(self,generation,max_gap=.15):
        self.generation=generation;self.max_gap=max_gap;self.tracks={};self.serial=0;self.last_sequence=None;self.last_pts=None
    def update(self,sequence,pts,boxes):
        if self.last_sequence is not None and (sequence<=self.last_sequence or pts<=self.last_pts):raise ValueError('Track input repeated or reversed')
        discontinuity=self.last_sequence is not None and sequence!=self.last_sequence+1
        if discontinuity:self.tracks={}
        self.last_sequence=sequence;self.last_pts=pts
        self.tracks={key:t for key,t in self.tracks.items() if pts-t['pts']<=self.max_gap}
        by_box={};by_track={}
        if boxes:
            b=np.asarray(boxes,dtype=np.float64)
            if np.any(b[:,2:]<=0):raise ValueError('Invalid object dimensions')
            if self.tracks:
                keys=list(self.tracks);values=[self.tracks[k] for k in keys]
                t=np.asarray([[v['cx'],v['cy'],v['vx'],v['vy'],v['pts'],max(v['box'][2:])] for v in values],dtype=np.float64)
                dt=pts-t[:,4];px=t[:,0]+t[:,2]*dt;py=t[:,1]+t[:,3]*dt
                # Same gates and ambiguity rules, evaluated in bounded NumPy tiles.
                for first in range(0,len(b),64):
                    bb=b[first:first+64];cx=bb[:,0]+bb[:,2]/2;cy=bb[:,1]+bb[:,3]/2
                    gate=np.maximum(24,3*np.maximum(np.maximum(bb[:,2],bb[:,3])[:,None],t[:,5]))+np.minimum(80,np.hypot(t[:,2],t[:,3])*dt)
                    distance=np.hypot(cx[:,None]-px,cy[:,None]-py)
                    rows,cols=np.nonzero(distance<=gate)
                    for row,col in zip(rows.tolist(),cols.tolist()):
                        i=first+row;key=keys[col];cost=float(distance[row,col]/gate[row,col])
                        by_box.setdefault(i,[]).append((cost,key));by_track.setdefault(key,[]).append((cost,i))
        assigned={};ambiguous=set()
        for i,options in by_box.items():
            options.sort();cost,key=options[0];reverse=sorted(by_track[key])
            # Ambiguous crossings create reviewable splits rather than false identity certainty.
            if (len(options)>1 and options[1][0]-cost<.15) or (len(reverse)>1 and reverse[1][0]-reverse[0][0]<.15):ambiguous.add(i);continue
            if reverse[0][1]==i:assigned[i]=key
        observations=[]
        for i,box in enumerate(boxes):
            x,y,w,h=box;cx,cy=x+w/2,y+h/2;key=assigned.get(i);old=self.tracks.get(key);direction_change=None;shape_change=None
            if old:
                dt=pts-old['pts'];vx=(cx-old['cx'])/dt;vy=(cy-old['cy'])/dt
                if math.hypot(vx,vy)>1 and math.hypot(old['vx'],old['vy'])>1:
                    dot=(vx*old['vx']+vy*old['vy'])/(math.hypot(vx,vy)*math.hypot(old['vx'],old['vy']));direction_change=math.degrees(math.acos(max(-1,min(1,dot))))
                shape_change=dict(area_ratio=w*h/(old['box'][2]*old['box'][3]),aspect_ratio_change=(w/h)/(old['box'][2]/old['box'][3]))
                observed=old['observed']+1;first=old['first'];gap_frames=sequence-old['sequence']-1
            else:
                self.serial+=1;key=f'{self.generation}:proposal-{self.serial:08d}';vx=vy=0;observed=1;first=sequence;gap_frames=0
            self.tracks[key]=dict(cx=cx,cy=cy,vx=vx,vy=vy,pts=pts,box=box,sequence=sequence,observed=observed,first=first,temporal_history=list(old.get('temporal_history',[])) if old else [])
            observations.append(dict(proposed_track_id=key,track_status='suggested',human_confirmed=False,sequence=sequence,pts_seconds=pts,box=box,center=[cx,cy],velocity_pixels_per_second=[vx,vy],direction_change_degrees=direction_change,box_shape_change=shape_change,observation_count=observed,first_sequence=first,missing_observations=gap_frames,ambiguous_link=i in ambiguous,source_discontinuity=discontinuity))
        return observations

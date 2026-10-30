"""Conservative trajectory proposals, explicitly distinct from human-confirmed tracks."""
import math
class NativeTracks:
    def __init__(self,generation,max_gap=.15):
        self.generation=generation;self.max_gap=max_gap;self.tracks={};self.serial=0;self.last_sequence=None;self.last_pts=None
    def update(self,sequence,pts,boxes):
        if self.last_sequence is not None and (sequence<=self.last_sequence or pts<=self.last_pts):raise ValueError('Track input repeated or reversed')
        discontinuity=self.last_sequence is not None and sequence!=self.last_sequence+1
        if discontinuity:self.tracks={}
        self.last_sequence=sequence;self.last_pts=pts
        self.tracks={key:t for key,t in self.tracks.items() if pts-t['pts']<=self.max_gap}
        costs={};by_box={};by_track={}
        for i,box in enumerate(boxes):
            x,y,w,h=box
            if w<=0 or h<=0:raise ValueError('Invalid object dimensions')
            cx,cy=x+w/2,y+h/2
            for key,t in self.tracks.items():
                dt=pts-t['pts'];px=t['cx']+t['vx']*dt;py=t['cy']+t['vy']*dt
                gate=max(24,3*max(w,h,t['box'][2],t['box'][3]))+min(80,math.hypot(t['vx'],t['vy'])*dt)
                distance=math.hypot(cx-px,cy-py)
                if distance<=gate:
                    cost=distance/gate;costs[i,key]=cost;by_box.setdefault(i,[]).append((cost,key));by_track.setdefault(key,[]).append((cost,i))
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

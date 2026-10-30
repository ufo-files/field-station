"""Scalar implementation of the same three-observation temporal feature schema."""
import math

def feature_window(points):
    if len(points)!=3:raise ValueError('A temporal window needs three observations')
    times=[p['time'] for p in points]
    boxes=[tuple(p['bounds'][k] for k in ('x','y','w','h')) for p in points]
    if not all(math.isfinite(v) for v in times) or not all(math.isfinite(v) for box in boxes for v in box) or any(min(box[2:])<=0 for box in boxes):raise ValueError('Invalid temporal observation')
    dt=[times[1]-times[0],times[2]-times[1]]
    if min(dt)<=0:raise ValueError('Track timestamps must increase')
    centers=[(x+w/2,y+h/2) for x,y,w,h in boxes]
    vx0=(centers[1][0]-centers[0][0])/dt[0];vy0=(centers[1][1]-centers[0][1])/dt[0]
    vx1=(centers[2][0]-centers[1][0])/dt[1];vy1=(centers[2][1]-centers[1][1])/dt[1]
    s0=math.hypot(vx0,vy0);s1=math.hypot(vx1,vy1);den=s0*s1
    cosine=(vx0*vx1+vy0*vy1)/den if den>1e-12 else 1.
    sine=(vx0*vy1-vy0*vx1)/den if den>1e-12 else 0.
    elapsed=(dt[0]+dt[1])/2
    area=[math.log(b[2]*b[3]) for b in boxes];aspect=[math.log(b[2]/b[3]) for b in boxes]
    shapes=[p.get('shape_descriptor',[0.]*64) for p in points]
    return [vx0,vy0,vx1,vy1,s0,s1,cosine,sine,(vx1-vx0)/elapsed,(vy1-vy0)/elapsed,
            area[1]-area[0],area[2]-area[1],aspect[1]-aspect[0],aspect[2]-aspect[1],*dt,
            math.dist(shapes[0],shapes[1]),math.dist(shapes[1],shapes[2])]

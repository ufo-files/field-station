"""The native-pixel context used for review crops and nighttime confirmation."""
def context_bounds(bounds,width,height):
 x,y,w,h=map(int,bounds)
 if w<=0 or h<=0 or x<0 or y<0 or x+w>width or y+h>height:raise ValueError('Invalid native object bounds')
 bw=min(width,max(64,w+24));bh=min(height,max(64,h+24))
 return [max(0,min(width-bw,round(x+w/2-bw/2))),max(0,min(height-bh,round(y+h/2-bh/2))),bw,bh]

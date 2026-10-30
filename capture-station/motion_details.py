"""Deterministic native crops and smoothly enlarged review images; no generated detail."""
import hashlib
import json
import tempfile
from pathlib import Path
from PIL import Image,ImageFilter


def atomic_image(image,path,format,**options):
    with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.motion-detail-',delete=False) as output:
        temporary=Path(output.name)
    try:image.save(temporary,format=format,**options);temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)


def crop_geometry(bounds,width,height,padding=None):
    b={k:float(bounds[k]) for k in ('left','top','right','bottom')}
    pad=padding if padding is not None else max(24,round(max(b['right']-b['left'],b['bottom']-b['top'])*.3))
    return dict(left=max(0,int(b['left']-pad)),top=max(0,int(b['top']-pad)),
                right=min(width,int(b['right']+pad)),bottom=min(height,int(b['bottom']+pad)))


def save_detail(image,bounds,folder,prefix,padding=None):
    crop_bounds=crop_geometry(bounds,*image.size,padding)
    l,t,r,b=[crop_bounds[k] for k in ('left','top','right','bottom')]
    if r<=l or b<=t:raise ValueError('Crop must be inside the frame')
    token=hashlib.sha256(json.dumps(crop_bounds,sort_keys=True).encode()).hexdigest()[:10]
    folder=Path(folder);native=folder/f'{prefix}-{token}-crop.png';detail=folder/f'{prefix}-{token}-detail.jpg'
    nw,nh=r-l,b-t;scale=max(1,1024/max(nw,nh));dw,dh=round(nw*scale),round(nh*scale)
    if not native.is_file() or not detail.is_file():
        crop=image.convert('RGB').crop((l,t,r,b))
        if not native.is_file():
            atomic_image(crop,native,'PNG')
        smooth=crop.resize((dw,dh),Image.Resampling.LANCZOS)
        if scale>1:smooth=smooth.filter(ImageFilter.GaussianBlur(.25))
        atomic_image(smooth,detail,'JPEG',quality=95,subsampling=0)
    return dict(bounds={k:bounds[k] for k in ('left','top','right','bottom')},crop_bounds=crop_bounds,
                native_file=native.name,detail_file=detail.name,native_width=nw,native_height=nh,
                display_width=dw,display_height=dh,upscaled=scale>1,processing='Lanczos resize; mild display smoothing only')


def save_motion_details(image,boxes,target,source,reviewed=False):
    eid=target.name[len('motion-'):-len('-boxed.jpg')]
    return [save_detail(image,b,target.parent,f'motion-{eid}-{source}',16 if reviewed else None) for b in boxes]

"""Composite the stacked UFO-FILES.APP NETWORK watermark."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from broadcast_rf import FONT

class Watermark:
    def __init__(self):
        path=Path(__file__).with_name('assets')/'field-station-mark.jpg'
        # Composite the supplied white-on-black mark as luminance coverage.
        # Retain its original pixels and trim only the shared preview's margins.
        mask=Image.open(path).convert('L')
        bounds=mask.point(lambda value:255 if value>40 else 0).getbbox()
        if not bounds:raise ValueError('Watermark logo is empty')
        left,top,right,bottom=bounds
        bounds=(max(0,left-3),max(0,top-3),min(mask.width,right+3),min(mask.height,bottom+3))
        self.mask=mask.crop(bounds).point(lambda value:max(0,value-8)*255//247).resize((48,48),Image.Resampling.LANCZOS)
        brand_font=Path('/System/Library/Fonts/SFNSRounded.ttf')
        self.font=ImageFont.truetype(str(brand_font if brand_font.is_file() else FONT),18)
        self.subtitle_font=ImageFont.truetype(str(brand_font if brand_font.is_file() else FONT),11)

    def draw(self,canvas,frame=None,standby=False):
        bright=False
        if frame is not None and not standby:
            crop=frame.resize((1280,720)).convert('L').crop((30,26,285,74)).resize((16,4))
            bright=sum(crop.getdata())/(16*4)>155
        ink=(155,201,140) if standby else (17,17,17) if bright else (255,255,255)
        shadow=(255,255,255) if bright else (0,0,0)
        edge=Image.new('RGBA',self.mask.size,(*shadow,0));edge.putalpha(self.mask.filter(ImageFilter.MaxFilter(3)).point(lambda a:round(a*.55)))
        logo=Image.new('RGBA',self.mask.size,(*ink,0));logo.putalpha(self.mask.point(lambda a:round(a*.88)))
        canvas.alpha_composite(edge,(30,26));canvas.alpha_composite(logo,(30,26))
        draw=ImageDraw.Draw(canvas)
        draw.text((90,33),'UFO-FILES.APP',font=self.font,anchor='lt',fill=(*ink,225),stroke_width=1,stroke_fill=(*shadow,130))
        draw.text((90,57),'NETWORK',font=self.subtitle_font,anchor='lt',fill=(*ink,200),stroke_width=1,stroke_fill=(*shadow,130))

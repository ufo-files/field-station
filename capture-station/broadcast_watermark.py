"""Use the original ufo-files.app SVG mark, rasterized once for video composition."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from broadcast_rf import FONT

class Watermark:
    def __init__(self):
        path=Path(__file__).with_name('assets')/'ufo-files-logo.png'
        self.mask=Image.open(path).convert('RGBA').resize((48,46),Image.Resampling.LANCZOS).getchannel('A')
        self.font=ImageFont.truetype(str(FONT),18)

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
        ImageDraw.Draw(canvas).text((90,39),'ufo-files.app',font=self.font,fill=(*ink,225),stroke_width=1,stroke_fill=(*shadow,130))

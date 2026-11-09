"""Bounded YouTube encoder with receive-only RF graphs; no browser/UI controls."""
import argparse,json,subprocess,sys
from pathlib import Path
from m1_live import live_args
from broadcast_camera import CameraPipe
from broadcast_rf import OverlayPipe,OUTPUT_WIDTH,OUTPUT_HEIGHT

def broadcast_args(config,overlay_fd,validate=False,camera_fd=None):
 args=live_args(config)
 if camera_fd is not None:
  start=args.index("-rw_timeout");end=args.index("-i")+2
  args[start:end]=["-thread_queue_size","8","-f","image2pipe","-vcodec","mjpeg","-framerate","30","-i",f"pipe:{camera_fd}"]
 index=args.index('-t')
 args[index:index]=['-thread_queue_size','8','-f','rawvideo','-pixel_format','rgba','-video_size',f'{OUTPUT_WIDTH}x{OUTPUT_HEIGHT}','-framerate','5','-i',f'pipe:{overlay_fd}']
 i=args.index('-vf');args[i:i+2]=['-filter_complex',f'[0:v]scale=1280:720,setsar=1[base];[base][2:v]overlay=0:0:eof_action=repeat[v]']
 args[args.index('0:v:0')]='[v]'
 if validate:args[-3:]=['-f','null','-']
 # Bound each input as well as output: an endless overlay input otherwise
 # keeps the filter graph alive after the output duration is reached.
 for index in reversed([i for i,value in enumerate(args) if value=='-i']):
  args[index:index]=['-probesize','32768','-analyzeduration','0','-t',str(config.get('duration_seconds',120))]
 if config.get('continuous'):
  for index in reversed([i for i,value in enumerate(args) if value=='-t']):del args[index:index+2]
 args[1:1]=['-progress','pipe:1','-nostats']
 return args

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',type=Path,required=True);parser.add_argument('--validate',action='store_true');parser.add_argument('--seconds',type=int,default=120);args=parser.parse_args()
 if not 1<=args.seconds<=3600:parser.error('Duration must be between 1 and 3600 seconds')
 config=json.loads(args.config.read_text());config['duration_seconds']=args.seconds;config['continuous']=False
 camera=CameraPipe(config['source'],config.get('standby_path',Path(__file__).with_name('assets')/'broadcast-standby.jpg'))
 overlay=OverlayPipe(config.get('rf_path','/Volumes/UFO-Field/signal-spool/live.json'),config.get('preview_url','http://127.0.0.1:8090/preview.jpg'),camera=camera)
 try:
  with subprocess.Popen(broadcast_args(config,overlay.reader,args.validate,camera.reader),pass_fds=(overlay.reader,camera.reader),stdin=subprocess.DEVNULL,stdout=None,stderr=subprocess.PIPE,text=True) as proc:
   camera.start();overlay.start()
   try:
    for line in proc.stderr:
     print(line.replace(config['publish_url'],'[YouTube ingest]').replace(config['publish_url'].rsplit('/',1)[-1],'[stream key]'),file=sys.stderr,end='',flush=True)
    return proc.wait()
   finally:
    if proc.poll() is None:proc.terminate();proc.wait(timeout=10)
 finally:camera.close();overlay.close()

if __name__=='__main__':raise SystemExit(main())

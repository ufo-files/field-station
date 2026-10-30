"""Explicit capture-device backends; recordings retain native dimensions and cadence."""
import os

def camera_input(device,rate,backend=None):
    backend=backend or os.environ.get('CAPTURE_BACKEND','v4l2')
    if backend=='v4l2':
        return ['-thread_queue_size','512','-f','v4l2','-input_format','mjpeg','-video_size','1920x1080','-framerate',str(rate),'-i',device]
    if backend=='avfoundation':
        return ['-thread_queue_size','512','-f','avfoundation','-drop_late_frames','0','-pixel_format','uyvy422','-video_size','1920x1080','-framerate',str(rate),'-i',device]
    raise ValueError('Unsupported camera backend: '+backend)


def camera_encoder(rate):
    if os.environ.get('CAPTURE_BACKEND')!='avfoundation':return ['-c:v','copy']
    if os.environ.get('CAPTURE_ENCODER')=='h264_videotoolbox':
        # All-intra hardware encoding keeps each buffered frame independently decodable.
        return ['-vf','setsar=1','-c:v','h264_videotoolbox','-b:v','60M','-g','1','-bf','0','-realtime','1','-allow_sw','0','-pix_fmt','nv12']
    return ['-c:v','mjpeg','-q:v','3','-threads','2','-pix_fmt','yuvj422p']

import os,hashlib,json,subprocess,sys,unittest
from pathlib import Path
from stream_decode import StreamDecoder
class DecodeParity(unittest.TestCase):
 @unittest.skipUnless(os.environ.get("FIELD_TEST_NATIVE_SEGMENTS"), "Set FIELD_TEST_NATIVE_SEGMENTS to native 1080p segments for VideoToolbox integration testing")
 def test_native_pixels_and_pts_match_direct_pyav(self):
  paths=[Path(p) for p in os.environ['FIELD_TEST_NATIVE_SEGMENTS'].split(os.pathsep)]
  script="""import av,hashlib,json,sys
out=[]
for p in sys.argv[1:]:
 with av.open(p) as c:
  for f in c.decode(video=0):out.append([p,float(f.pts*f.time_base),hashlib.sha256(f.to_ndarray(format='gray').tobytes()).hexdigest()])
print(json.dumps(out))
"""
  expected=json.loads(subprocess.check_output([sys.executable,'-c',script,*map(str,paths)],text=True))
  with StreamDecoder() as d:
   pid=d.process.pid;actual=[]
   for path in paths:
    actual.extend([h['path'],h['pts_seconds'],hashlib.sha256(im.tobytes()).hexdigest()] for im,h in d.frames(path));self.assertEqual(pid,d.process.pid)
  self.assertEqual(actual,expected);self.assertGreater(len(actual),175)
 def test_bad_source_is_error(self):
  with StreamDecoder() as d:
   with self.assertRaises(ValueError):list(d.frames('/tmp/ufo-no-such-native-segment.mkv'))

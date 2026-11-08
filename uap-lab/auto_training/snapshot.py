"""Export only explicitly reviewed crops; never infer labels from model output."""
import argparse,hashlib,io,json,os,shutil,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from email_training import reviewed_examples,LABELS,canonical_label

def read(p,default=None):
 try:return json.loads(p.read_text())
 except FileNotFoundError:return default

def collect(lab):
 lab=Path(lab);rows=[];images={};omitted=read(lab/'omitted-videos.json',{})
 def add(path,label,group,origin,original_label=None,prepared=None):
  original_label=original_label or label
  label=canonical_label(label)
  if label not in LABELS:return
  if prepared:
   digest=prepared['pixel_sha256'];width=prepared['native_width'];height=prepared['native_height'];png=prepared['normalized_png']
  else:
   if path.is_symlink() or not path.is_file():raise ValueError('Reviewed crop is missing or unsafe')
   with Image.open(path) as source:im=source.convert('RGB')
   width,height=im.size;digest=hashlib.sha256(f'{width}x{height}:RGB:'.encode()+im.tobytes()).hexdigest();out=io.BytesIO();im.save(out,format='PNG');png=out.getvalue()
  name='images/'+hashlib.sha256(origin.encode()).hexdigest()+'.png';images[name]=png
  rows.append(dict(origin=origin,label=label,original_label=original_label,group=group,pixel_sha256=digest,native_width=width,native_height=height,image=name))
  if prepared:rows[-1].update(input_color_space=prepared.get('input_color_space','legacy_grayscale'),color_provenance=prepared.get('color_provenance','original'))
  else:rows[-1].update(input_color_space='RGB',color_provenance='video_annotation')
 for r in reviewed_examples(lab,workers=4,prepared=True):add(r['image'],r['label'],r['group'],'email:'+r['id'],r['review'].get('original_label',r['label']),prepared=r)
 for folder in sorted((lab/'videos').iterdir()):
  meta=read(folder/'video.json',{});sha=meta.get('sha256')
  if not sha or sha in omitted or read(folder/'training-excluded.json',{}).get('excluded'):continue
  sid=meta.get('provenance',{}).get('session_id');session=read(lab.parent/'sessions'/str(sid)/'manifest.json',{})
  group='generation:'+session['spool_generation'] if session.get('spool_generation') else 'sha:'+sha
  for a in read(folder/'annotations.json',[]):
   path=folder/a['image']
   if not path.resolve().is_relative_to(folder.resolve()):raise ValueError('Unsafe annotation path')
   add(path,a['label'],group,'lab:'+folder.name+':'+a['id'])
 rows.sort(key=lambda r:r['origin']);fingerprint=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
 return dict(schema=1,fingerprint=fingerprint,samples=rows),images

def export(lab,out):
 manifest,images=collect(lab);target=Path(out)/manifest['fingerprint']
 if not target.exists():
  target.parent.mkdir(parents=True,exist_ok=True)
  with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
   temp=Path(tmp)/'snapshot';(temp/'images').mkdir(parents=True)
   for name,data in images.items():(temp/name).write_bytes(data)
   (temp/'reviews.json').write_text(json.dumps(manifest));temp.rename(target)
 return dict(fingerprint=manifest['fingerprint'],examples=len(manifest['samples']))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--lab',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();print(json.dumps(export(a.lab,a.out)))

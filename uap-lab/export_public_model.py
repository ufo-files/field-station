"""Prepare a portable public model from reviewed sources with documented sharing status."""
import ast,hashlib,json,shutil,sys
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit
import cv2

ROOT=Path(__file__).resolve().parent
DATA=Path('/home/hackrf/t7/uap-lab')
SOURCES=Path('/home/hackrf/t7/training-videos/PURSUE')
def read(p,default=None):
    try:return json.loads(p.read_text())
    except (OSError,ValueError):return default

def build(destination):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True);(destination/'templates').mkdir(exist_ok=True)
    omitted=read(DATA/'omitted-videos.json',{});examples=[];annotations=[];sources={};skipped=Counter();usable=0
    for folder in sorted((DATA/'videos').iterdir()):
        video=read(folder/'video.json',{});review=read(folder/'review.json',{})
        if not review.get('completed'):continue
        if read(folder/'training-excluded.json',{}).get('excluded') or video.get('sha256') in omitted:continue
        provenance=video.get('provenance',{});rows=read(folder/'annotations.json',[])
        if not rows:continue
        page=provenance.get('source_page','');record=provenance.get('record_id','')
        publication=video.get('publication',{})
        is_pursue=provenance.get('collection')=='PURSUE' and urlsplit(page).hostname=='www.dvidshub.net'
        if is_pursue:
            official_html=SOURCES/'pages'/(record+'.html')
            if not official_html.is_file() or 'PUBLIC DOMAIN' not in official_html.read_text().upper():skipped['source_rights_not_verified']+=len(rows);continue
            source_key=record
            sources[source_key]=dict(id=record,title=provenance.get('title'),official_url=page,source_sha256=video.get('sha256'),date_released=provenance.get('date_released'),rights_marking='PUBLIC DOMAIN on source DVIDS page',terms_url='https://www.dvidshub.net/about/copyright')
        elif publication.get('publish_model_crops') and publication.get('media_license') and publication.get('attribution'):
            # New inputs train locally by default. Public crop redistribution uses
            # recorded source attribution/terms, independent of the source collection.
            source_key='external-'+(video.get('sha256') or folder.name)[:20]
            sources[source_key]=dict(id=source_key,title=video['name'],official_url=publication.get('source_url'),source_sha256=video.get('sha256'),rights_marking=publication['media_license'],attribution=publication['attribution'],terms_url=publication.get('terms_url'))
        else:skipped['publication_provenance_pending']+=len(rows);continue
        for ann in rows:
            original=folder/ann['image']
            if original.parent!=folder or not original.is_file():raise ValueError('Invalid native exemplar reference')
            data=original.read_bytes();gray=cv2.imread(str(original),cv2.IMREAD_GRAYSCALE)
            if gray is None:raise ValueError('Invalid exemplar image')
            index=len(examples)+1;name=f'templates/example-{index:05d}.png';(destination/name).write_bytes(data)
            useful=bool(gray.std()>=2);usable+=useful
            examples.append(dict(image=name,label=ann['label'],sha256=hashlib.sha256(data).hexdigest()))
            annotations.append(dict(example=name,label=ann['label'],source=source_key,time_seconds=ann['time'],bounds_normalized=ann['bounds'],native_pixels=ann.get('pixels'),usable_for_matching=useful))
    return write_release(destination,examples,annotations,sources,usable,skipped)

def build_saved(model_id,destination):
    """Export the exact immutable saved model; never substitute later review edits."""
    if len(model_id)!=32 or any(c not in '0123456789abcdef' for c in model_id):raise ValueError('Invalid saved model ID')
    model_folder=DATA/'models'/model_id;model=read(model_folder/'model.json')
    if not model:raise ValueError('Saved model not found')
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True);(destination/'templates').mkdir(exist_ok=True)
    examples=[];annotations=[];sources={};usable=0
    for item in model['examples']:
        original=(model_folder/item['image']).resolve()
        if not original.is_relative_to(model_folder.resolve()):raise ValueError('Invalid saved exemplar path')
        data=original.read_bytes();sha=hashlib.sha256(data).hexdigest();name='templates/'+sha+'.png';target=destination/name
        if not target.is_file():target.write_bytes(data)
        gray=cv2.imread(str(original),cv2.IMREAD_GRAYSCALE)
        if gray is None:raise ValueError('Invalid saved exemplar')
        useful=bool(gray.std()>=2);usable+=useful;examples.append(dict(image=name,label=item['label'],sha256=sha))
        vid=item.get('video_id');video=read(DATA/'videos'/vid/'video.json',{}) if vid else {};provenance=video.get('provenance',{});publication=video.get('publication',{})
        source_key=video.get('sha256') or vid or 'unspecified'
        official=provenance.get('collection')=='PURSUE' and urlsplit(provenance.get('source_page','')).hostname=='www.dvidshub.net'
        sources[source_key]=dict(id=source_key,source_sha256=video.get('sha256'),title=provenance.get('title') if official else 'Contributor-supplied video '+source_key[:12],official_url=provenance.get('source_page') if official else publication.get('source_url'),rights_marking='See credited DVIDS source terms' if official else publication.get('media_license','Contributor-supplied media; source-media terms remain separate'),attribution=publication.get('attribution'),terms_url='https://www.dvidshub.net/about/copyright' if official else publication.get('terms_url'))
        ann=item.get('annotation_data') or (next((a for a in read(DATA/'videos'/vid/'annotations.json',[]) if a['id']==item.get('annotation')),{}) if vid else {})
        annotations.append(dict(example=name,label=item['label'],source=source_key,time_seconds=ann.get('time'),bounds_normalized=ann.get('bounds'),native_pixels=dict(width=int(gray.shape[1]),height=int(gray.shape[0])),usable_for_matching=useful,track_id=ann.get('track_id'),frame_index=ann.get('frame_index'),shape_descriptor=ann.get('shape_descriptor')))
    return write_release(destination,examples,annotations,sources,usable,Counter(),saved_model=model)

def write_release(destination,examples,annotations,sources,usable,skipped,saved_model=None):
    destination=Path(destination)
    if not examples:raise ValueError('No eligible completed publishable-source annotations')
    fingerprint=hashlib.sha256(json.dumps(dict(examples=examples,annotations=annotations),sort_keys=True).encode()).hexdigest()
    model=dict(schema_version=1,id=(saved_model or {}).get('id',fingerprint[:32]),release=('model-'+saved_model['id']) if saved_model else 'v0.1.0-preview',kind='multiscale normalized appearance matching',classes=sorted({e['label'] for e in examples}),examples=examples,dataset_sha256=fingerprint,license='Apache-2.0 for original code, annotations, and compilation; source media terms are separate',parameters=dict(scales=[.65,.8,1,1.25,1.6],overlap_suppression=.35,default_threshold=.97,native_detail_threshold=.55,native_detail_gaussian_sigma=1.2,inference_revision=2),created_utc=(datetime.fromtimestamp(saved_model['created'],timezone.utc).isoformat() if saved_model and saved_model.get('created') else datetime.now(timezone.utc).isoformat()))
    if saved_model and saved_model.get('temporal'):
        model.update(schema_version=2,temporal=saved_model['temporal'])
    for name,value in (('model.json',model),('annotations.json',annotations),('sources.json',list(sources.values()))): (destination/name).write_text(json.dumps(value,indent=2)+'\n')
    source=(ROOT/'lab.py').read_text();tree=ast.parse(source);detect=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='detect')
    engine=ast.get_source_segment(source,detect)
    header='''# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 ufo-files contributors
"""Portable inference for the UAP appearance model. No station services required."""
import argparse, hashlib, json, sys
from pathlib import Path
import cv2
import numpy as np
cv2.setNumThreads(1)

'''
    runner='''

class Matcher:
    def __init__(self, model_dir=None):
        self.root=Path(model_dir or Path(__file__).resolve().parent).resolve()
        self.model=json.loads((self.root/'model.json').read_text())
        self.templates=[]
        for example in self.model['examples']:
            path=(self.root/example['image']).resolve()
            if not path.is_relative_to(self.root):raise ValueError('Invalid template path')
            if hashlib.sha256(path.read_bytes()).hexdigest()!=example['sha256']:raise ValueError('Template checksum mismatch: '+example['image'])
            image=cv2.imread(str(path),cv2.IMREAD_GRAYSCALE)
            if image is None:raise ValueError('Invalid template: '+example['image'])
            if image.std()>=2:self.templates.append((example['label'],image))
        if not self.templates:raise ValueError('No usable templates')
    def predict(self, image, threshold=.97, labels=None):
        if not .5<=threshold<=1:raise ValueError('Threshold must be between 0.5 and 1')
        return detect(image,self.templates,threshold,labels or self.model['classes'])

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path);parser.add_argument('--model',type=Path,default=Path(__file__).resolve().parent)
    parser.add_argument('--threshold',type=float,default=.97);parser.add_argument('--labels',help='Comma-separated output labels')
    parser.add_argument('--output',type=Path,help='JSONL detections; defaults to stdout')
    args=parser.parse_args();matcher=Matcher(args.model);labels=args.labels.split(',') if args.labels else None
    out=args.output.open('w') if args.output else sys.stdout
    try:
        image=cv2.imread(str(args.input),cv2.IMREAD_COLOR) if args.input.suffix.lower() in ('.png','.jpg','.jpeg','.bmp','.tif','.tiff','.webp') else None
        if image is not None:
            print(json.dumps(dict(model_id=matcher.model['id'],frame=0,objects=matcher.predict(image,args.threshold,labels))),file=out)
        else:
            video=cv2.VideoCapture(str(args.input))
            if not video.isOpened():raise ValueError('Cannot open input video')
            frame=0
            try:
                while True:
                    ok,image=video.read()
                    if not ok:break
                    print(json.dumps(dict(model_id=matcher.model['id'],frame=frame,objects=matcher.predict(image,args.threshold,labels))),file=out)
                    frame+=1
            finally:video.release()
    finally:
        if out is not sys.stdout:out.close()
if __name__=='__main__':main()
'''
    (destination/'inference.py').write_text(header+engine+runner)
    (destination/'requirements.txt').write_text('numpy>=2,<3\nopencv-python-headless>=4.10,<6\n')
    (destination/'.gitignore').write_text('__pycache__/\n.venv/\n*.jsonl\n')
    labels=dict(Counter(e['label'] for e in examples))
    summary=dict(model_id=model['id'],examples=len(examples),usable_templates=usable,source_videos=len(sources),classes=labels,skipped=dict(skipped),dataset_sha256=fingerprint,created_utc=model['created_utc'])
    (destination/'release-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    (destination/'README.md').write_text(f'''# UAP Observation Model

An experimental, reusable appearance model built from manually labeled targets in credited source videos. This release includes **{len(examples)} labeled crops from {len(sources)} source videos**, source credits, annotations, and a portable Python/OpenCV runner.

## Use it

Requires Python 3.11+ and a CPU. Clone this repository or extract the release ZIP, then:

```bash
python -m venv .venv
# Linux/macOS; on Windows use .venv\\Scripts\\activate
source .venv/bin/activate
pip install -r requirements.txt
python inference.py your-image.jpg --output detections.jsonl
python inference.py your-video.mp4 --threshold 0.97 --output detections.jsonl
```

Or use it from Python:

```python
import cv2
from inference import Matcher
model = Matcher()
objects = model.predict(cv2.imread("your-image.jpg"))
```

Each detection has a label, correlation score, and `[x, y, width, height]` box in native image pixels. Video output contains one JSON line per decoded frame, indexed from zero. The lightweight runner emits detections; recording, RF capture, event trimming, and cropped video export belong to the station application and are not bundled here.

## What is saved

`model.json` selects labeled native PNG templates in `templates/`. Inference searches five scales using normalized correlation and suppresses overlapping matches. Known-class examples compete with target examples when present. See [MODEL_CARD.md](MODEL_CARD.md) for coverage and limitations.

This is a template-based appearance model. No neural network weights or gradient-trained detector are claimed. The label `anomalous` records a human review choice. The model predicts a resemblance to those selections; it does not determine an object's identity or cause.

## Release

- Version: `{model['release']}`
- Model ID: `{model['id']}`
- Snapshot: `{model['created_utc']}`
- Label counts: `{json.dumps(labels,sort_keys=True)}`
- Usable templates after low-detail filtering: {usable}
- Independent held-out accuracy: not measured for this release

More templates increase CPU inference time. Start with still images before long videos. Threshold scores are correlations, not calibrated probabilities. This preview does not establish transfer accuracy on other cameras or environments.

## Sources and license

Original code, annotations, and compilation: **Apache License 2.0**, in [LICENSE](LICENSE). Source image crops retain their source-media status and terms; they are not relicensed as original imagery. [sources.json](sources.json) lists the official DVIDS page and source-video checksum for every contributing video. Source rights markings and attribution are recorded for each source; source media retain those separate terms. See [NOTICE](NOTICE) and [DVIDS source terms](https://www.dvidshub.net/about/copyright).

The appearance of U.S. Department of War (DoW) visual information does not imply or constitute DoW endorsement.
''')
    (destination/'MODEL_CARD.md').write_text(f'''# Model card: UAP Observation Model

## Snapshot and method

Version `{model['release']}`, model ID `{model['id']}`. Prepared {model['created_utc']}. {len(examples)} manually labeled native crops, {usable} usable templates, {len(sources)} source videos. Labels: `{json.dumps(labels,sort_keys=True)}`.

The saved artifact is a bank of native grayscale appearance templates plus label metadata. OpenCV normalized cross-correlation searches scales 0.65, 0.8, 1.0, 1.25, and 1.6; overlap suppression uses 0.35 intersection-over-smaller-box area. Default matching threshold is 0.97. Uniform templates with standard deviation below 2 are skipped. Native positive matches also require agreement of background-subtracted fine structure: Gaussian sigma 1.2, correlation at least 0.55. This rejects smooth cloud gradients that can have a high raw correlation. Cloud examples may still compete as background negatives. At most eight candidate peaks per template and scale are considered. The runner preserves this station inference algorithm.

## Data and provenance

Only completed, non-omitted reviews of credited credited source videos were eligible. Sources are listed in `sources.json`; crop time positions, labels, and normalized source bounds are in `annotations.json`. Native exemplars are copied without smoothing or enlargement. No full source videos, RF logs, local network addresses, or credentials are included. Only saved model snapshots are exported; full source videos and station logs are excluded. Dataset fingerprint: `{fingerprint}`.

## Evaluation

Independent held-out precision, recall, false-positive rate, and camera-transfer accuracy have not been measured. Tests verify portable inference parity with the source algorithm and template integrity; these are software checks, not real-world performance benchmarks. Same-source re-identification is not evidence of generalization. Review targets may share the same physical object or recording, so crop count is not a count of independent encounters.

## Intended use and limitations

Exploratory re-identification and reproducible experiments on visually similar footage. Appearance is sensitive to viewpoint, object scale, background, sensor modality, contrast, compression, and occlusion. Correlation can match overlays, reticles, sensor artifacts, or conventional objects. Multiple objects can be returned; this runner does not establish persistent identity through crossings or occlusion. A single positive-only class provides no calibrated discrimination against birds, aircraft, or clouds. The model carries human labels and makes no determination about physical identity or origin.

## Reproducibility

Use `python -m unittest -v test_inference` after installing requirements. `SHA256SUMS` records release file hashes. Tested with the software versions in `verification.json`. A standalone CPU runner requires no station services, Mac worker, GPU, or private filesystem layout.

## Attribution

Apache 2.0 applies to the project's original code, annotations, and compilation. Source media retain their separate status and terms described by official source pages. See LICENSE, NOTICE, and sources.json. Third-party software is installed separately and retains its own licenses.
''')
    (destination/'NOTICE').write_text('UAP Observation Model\nCopyright 2026 ufo-files contributors\n\nOriginal code, annotations, and compilation are licensed under Apache License 2.0.\nSource image crops retain their source-media status and terms; they are not claimed as original imagery.\nSource credits and official URLs are listed in sources.json.\nDVIDS source terms: https://www.dvidshub.net/about/copyright\n\nThe appearance of U.S. Department of War (DoW) visual information does not imply or constitute DoW endorsement.\n\nOpenCV and NumPy are installed separately under their respective licenses.\n')
    print(json.dumps(summary,indent=2));return summary
if __name__=='__main__':build(sys.argv[1])

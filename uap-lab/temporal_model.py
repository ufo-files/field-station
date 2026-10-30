"""Timestamp-aware multi-object sequence features; never invent intermediate labels.

Each training window contains three explicit observations of the same object.
Legacy independent crops stay independent. Evaluation splits by source SHA.
"""
from collections import defaultdict
import math
import cv2
import numpy as np

FEATURES = ['vx_before', 'vy_before', 'vx_after', 'vy_after', 'speed_before',
            'speed_after', 'turn_cos', 'turn_sin', 'acceleration_x', 'acceleration_y',
            'log_area_change_before', 'log_area_change_after',
            'log_aspect_change_before', 'log_aspect_change_after', 'dt_before', 'dt_after',
            'native_shape_change_before', 'native_shape_change_after']

def shape_descriptor(image):
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim==3 else image
    small=cv2.resize(gray,(8,8),interpolation=cv2.INTER_AREA).astype(np.float64)
    small-=small.mean()
    norm=np.linalg.norm(small)
    return (small/max(norm,1e-12)).ravel().tolist()

def feature_window(points):
    if len(points) != 3:
        raise ValueError('A temporal window needs three observations')
    t = np.array([p['time'] for p in points], dtype=np.float64)
    boxes = np.array([[p['bounds'][k] for k in ('x', 'y', 'w', 'h')] for p in points], dtype=np.float64)
    if not np.isfinite(t).all() or not np.isfinite(boxes).all() or np.any(boxes[:, 2:] <= 0):
        raise ValueError('Invalid temporal observation')
    dt = np.diff(t)
    if np.any(dt <= 0):
        raise ValueError('Track timestamps must increase')
    centers = boxes[:, :2] + boxes[:, 2:] / 2
    velocity = np.diff(centers, axis=0) / dt[:, None]
    speeds = np.linalg.norm(velocity, axis=1)
    denominator = speeds[0] * speeds[1]
    cosine = float(velocity[0] @ velocity[1] / denominator) if denominator > 1e-12 else 1.0
    sine = float((velocity[0, 0]*velocity[1, 1] - velocity[0, 1]*velocity[1, 0])/denominator) if denominator > 1e-12 else 0.0
    acceleration = (velocity[1] - velocity[0]) / (dt.mean())
    area = np.prod(boxes[:, 2:], axis=1)
    aspect = boxes[:, 2] / boxes[:, 3]
    shapes=[np.asarray(p.get('shape_descriptor',[0.0]*64)) for p in points]
    changes=[float(np.linalg.norm(b-a)) for a,b in zip(shapes,shapes[1:])]
    return np.concatenate([velocity.ravel(), speeds, [cosine, sine], acceleration,
                           np.diff(np.log(area)), np.diff(np.log(aspect)), dt, changes]).tolist()

def windows(records):
    groups = defaultdict(list)
    for row in records:
        # No fabricated track linkage for old singleton annotations.
        if row.get('track_id'):
            groups[(row['source_sha256'], row['track_id'])].append(row)
    result = []
    for (source, track), points in groups.items():
        points.sort(key=lambda p: p['time'])
        if len({p['label'] for p in points}) != 1:
            raise ValueError('One persistent track must have one label')
        if len({p['time'] for p in points}) != len(points):
            raise ValueError('A track may have only one observation per native frame')
        for index in range(2, len(points)):
            chunk = points[index-2:index+1]
            result.append(dict(source_sha256=source, recording_group=chunk[-1].get('recording_group',source), track_id=track, label=chunk[-1]['label'],
                               frame_indices=[p.get('frame_index') for p in chunk],
                               features=feature_window(chunk)))
    return result

def fit(records):
    samples = windows(records)
    sources = sorted({s['source_sha256'] for s in samples})
    recordings=sorted({s['recording_group'] for s in samples})
    model = dict(schema_version=3, kind='timestamped three-observation nearest-neighbor trajectory classifier',
                 feature_names=FEATURES, windows=len(samples), source_count=len(sources), recording_group_count=len(recordings),
                 state='needs_temporal_annotations', evaluation=dict(state='needs_two_independent_recordings'))
    if not samples:
        return model
    vectors = np.asarray([s['features'] for s in samples], dtype=np.float64)
    scale = np.maximum(np.std(vectors, axis=0), 1e-6)
    # Held-out evaluation refits scaling using training sources only.
    if len(recordings) >= 2:
        correct = total = 0
        for source in recordings:
            train = [s for s in samples if s['recording_group'] != source]
            test = [s for s in samples if s['recording_group'] == source]
            bank = np.asarray([s['features'] for s in train])
            fold_scale = np.maximum(np.std(bank, axis=0), 1e-6)
            for sample in test:
                distances = np.mean(((bank-np.asarray(sample['features']))/fold_scale)**2, axis=1)
                correct += train[int(np.argmin(distances))]['label'] == sample['label']
                total += 1
        model['evaluation'] = dict(state='leave_one_source_out', correct=correct, total=total,
                                   accuracy=correct/total, grouping='capture_generation_when_available_otherwise_source_sha256')
    model.update(state='trained', scale=scale.tolist(), samples=samples,
                 limitations='Sparse labeled sequences learn trajectory, box geometry and normalized native-crop appearance changes. Similarity is not calibrated; held-out performance and sufficient temporal labels are required before automatic temporal triggering.')
    return model

def predict(model, points):
    if model.get('state') != 'trained':
        return None
    vector = np.asarray(feature_window(points))
    bank = np.asarray([s['features'] for s in model['samples']])
    distances = np.mean(((bank-vector)/np.asarray(model['scale']))**2, axis=1)
    index = int(np.argmin(distances))
    return dict(label=model['samples'][index]['label'], distance=float(distances[index]),
                # Similarity is not a calibrated probability and never independently triggers recording.
                similarity=math.exp(-min(float(distances[index]), 700)))

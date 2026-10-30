"""Shared label text and spatial matching for preview and saved evidence."""
def label_text(region):
    obj=region.get('object',{}).get('label','unknown')
    shape=region.get('shape',{}).get('label','unresolved').replace('_',' ')
    name=(obj.replace('_',' ').capitalize()+' (reviewed)') if region.get('object',{}).get('source')=='human' else 'Unknown' if obj=='unknown' else 'Likely '+obj.replace('_',' ')
    return name+' | '+('shape unresolved' if shape=='unresolved' else shape)


def matching_region(box, regions):
    best=None;best_score=0
    for region in regions:
        b=region.get('bounds',{})
        if not all(k in b for k in ('left','top','right','bottom')):continue
        intersection=max(0,min(box['right'],b['right'])-max(box['left'],b['left']))*max(0,min(box['bottom'],b['bottom'])-max(box['top'],b['top']))
        area=max(1,(box['right']-box['left'])*(box['bottom']-box['top']))
        other=max(1,(b['right']-b['left'])*(b['bottom']-b['top']))
        score=intersection/(area+other-intersection)
        if score>=.2 and score>best_score:best=region;best_score=score
    return best


def effective_classification(event):
    """Observer corrections override display labels, never erase model evidence."""
    review=event.get('human_review')
    if review:
        return dict(state='completed',regions=[dict(bounds=r['bounds'],source_frame=review['source_frame'],
                    object=dict(label=r['object'],source='human'),shape=dict(label=r['shape'])) for r in review['regions']],source='human')
    result=dict(event.get('classification') or {})
    source=event.get('annotation',{}).get('source_frame')
    result['regions']=[r for r in result.get('regions',[]) if not source or r.get('source_frame',source)==source]
    return result

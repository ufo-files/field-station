"""Calibration never uses held-out test rows; uncertain outputs remain unknown."""
def calibrate(rows,probabilities,classes):
    thresholds={};evidence={}
    for i,label in enumerate(classes):
        chosen=None
        for cutoff in [.8,.85,.9,.93,.95,.97,.99,.995,.999]:
            accepted=[r for r,p in zip(rows,probabilities) if max(range(len(p)),key=p.__getitem__)==i and p[i]>=cutoff]
            correct=[r for r in accepted if r['label']==label];groups={r['group'] for r in correct}
            if len(correct)>=5 and len(groups)>=2 and len(correct)==len(accepted):chosen=(cutoff,len(correct),len(groups));break
        thresholds[label]=chosen[0] if chosen else 1.1
        evidence[label]=dict(enabled=chosen is not None,correct=chosen[1] if chosen else 0,groups=chosen[2] if chosen else 0)
    return thresholds,evidence

def evaluate(rows,probabilities,classes,thresholds):
    predictions=[]
    for row,scores in zip(rows,probabilities):
        i=max(range(len(scores)),key=scores.__getitem__);label=classes[i];accepted=label if scores[i]>=thresholds.get(label,1.1) and max(row['native_width'],row['native_height'])>=8 else 'unknown'
        predictions.append(dict(origin=row['origin'],group=row['group'],truth=row['label'],raw_label=label,label=accepted,score=float(scores[i])))
    metrics={}
    for label in classes:
        tp=sum(v['truth']==label and v['label']==label for v in predictions);fp=sum(v['truth']!=label and v['label']==label for v in predictions);fn=sum(v['truth']==label and v['label']!=label for v in predictions)
        metrics[label]=dict(tp=tp,fp=fp,fn=fn,precision=tp/(tp+fp) if tp+fp else None,recall=tp/(tp+fn) if tp+fn else None)
    return dict(per_class=metrics,unknown=sum(v['label']=='unknown' for v in predictions),total=len(rows),cloud_false_suppression=sum(v['truth']!='cloud' and v['label']=='cloud' for v in predictions),predictions=predictions)

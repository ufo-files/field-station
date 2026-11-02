"""Two review categories; uncertain and retired evidence is never invented as negative."""
LABELS={'anomalous','not_anomalous'}
NORMAL_LABELS={'airplane','bird','insect','cloud','other_animal','balloon','star','satellite','shooting_star','vehicle','drone'}
def canonical_label(label):
    if label in NORMAL_LABELS:return 'not_anomalous'
    return 'landscape' if label=='mountain' else label

"""Independent classification and human-review filters."""
CLASSES=('all','anomalous','not_anomalous')
STATUSES=('all','needs_review','human_reviewed')
def validate(classification,review_status):
 if classification not in CLASSES or review_status not in STATUSES:raise ValueError('Invalid review filters')
def matches(row,classification,review_status):
 return (classification=='all' or row['label']==classification) and (review_status=='all' or bool(row['human_reviewed'])==(review_status=='human_reviewed'))
def select(rows,classification,review_status):
 validate(classification,review_status)
 counts={'classification':dict.fromkeys(CLASSES,0),'review_status':dict.fromkeys(STATUSES,0)};selected=[]
 for row in rows:
  for value in CLASSES:counts['classification'][value]+=matches(row,value,review_status)
  for value in STATUSES:counts['review_status'][value]+=matches(row,classification,value)
  if matches(row,classification,review_status):selected.append(row)
 return selected,counts

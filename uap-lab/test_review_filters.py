import unittest
from review_filters import select,CLASSES,STATUSES
class FilterTests(unittest.TestCase):
 def setUp(self):self.rows=[dict(id=str(i),label=label,human_reviewed=reviewed) for i,(label,reviewed) in enumerate((('anomalous',False),('not_anomalous',False),('anomalous',True),('not_anomalous',True)))]
 def test_all_nine_combinations(self):
  for classification in CLASSES:
   for status in STATUSES:
    with self.subTest(classification=classification,status=status):
     rows,counts=select(self.rows,classification,status)
     expected=[r for r in self.rows if (classification=='all' or r['label']==classification) and (status=='all' or r['human_reviewed']==(status=='human_reviewed'))]
     self.assertEqual(rows,expected)
 def test_contextual_counts(self):
  rows,counts=select(self.rows,'anomalous','needs_review')
  self.assertEqual(counts,{'classification':{'all':2,'anomalous':1,'not_anomalous':1},'review_status':{'all':2,'needs_review':1,'human_reviewed':1}})
 def test_bad_filters_rejected(self):
  for classification,status in [('unknown','all'),('all','unreviewed')]:
   with self.assertRaises(ValueError):select(self.rows,classification,status)

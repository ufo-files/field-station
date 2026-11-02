import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from classification_taxonomy import LABELS,canonical_label
from training_policy import evaluate,project_binary
class BinaryTaxonomyTests(unittest.TestCase):
 def test_retired_and_unreviewed_are_not_negative_training_labels(self):
  for label in ('unknown','house','tree','landscape','mountain','antenna','telephone_pole'):
   self.assertNotIn(canonical_label(label),LABELS)
  for label in ('bird','cloud','satellite','drone','not_anomalous'):
   self.assertEqual(canonical_label(label),'not_anomalous')
 def test_project_actual_decisions_not_sum_multiclass_counts(self):
  rows=[dict(origin=str(i),group='g',label=truth,native_width=20,native_height=20) for i,truth in enumerate(('bird','anomalous','cloud','unknown'))]
  report=evaluate(rows,[[0,1,0],[1,0,0],[0,.7,.3],[0,1,0]],['bird','cloud','anomalous'],dict(bird=.8,cloud=.8,anomalous=.8))
  binary=project_binary(report)
  self.assertEqual(binary['total'],3)
  self.assertEqual(binary['per_class']['not_anomalous'],dict(tp=1,fp=1,fn=1,precision=.5,recall=.5))
  self.assertEqual(binary['per_class']['anomalous']['fn'],1)
  self.assertEqual(binary['unknown'],1)
  self.assertEqual(report['predictions'][0]['label'],'cloud')
  self.assertEqual(binary['predictions'][0]['original_label'],'cloud')

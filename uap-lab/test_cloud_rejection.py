"""Regressions for smooth sky gradients being mistaken for distinct targets."""
import unittest
from pathlib import Path
import cv2,numpy as np
import lab

class CloudRejectionTests(unittest.TestCase):
    def test_smooth_gradient_is_not_an_object_even_with_perfect_raw_correlation(self):
        gradient=np.tile(np.linspace(20,180,32,dtype=np.uint8),(48,1));image=cv2.cvtColor(gradient,cv2.COLOR_GRAY2BGR)
        self.assertTrue(lab.detect(image,[('anomalous',gradient)],.97,['anomalous'],verify_detail=False))
        self.assertEqual(lab.detect(image,[('anomalous',gradient)],.97,['anomalous']),[])
    def test_detail_mismatch_rejects_background_agreement(self):
        t=np.tile(np.linspace(30,210,53,dtype=np.float32),(75,1));cv2.circle(t,(26,25),3,150,-1);cv2.circle(t,(27,50),3,190,-1);t=t.astype(np.uint8)
        background=np.tile(np.linspace(30,210,53,dtype=np.uint8),(75,1));image=cv2.cvtColor(background,cv2.COLOR_GRAY2BGR)
        self.assertTrue(lab.detect(image,[('anomalous',t)],.97,['anomalous'],verify_detail=False))
        self.assertEqual(lab.detect(image,[('anomalous',t)],.97,['anomalous']),[])
    def test_faint_compact_targets_and_multiple_objects_survive(self):
        t=np.full((32,32),100,np.uint8);cv2.circle(t,(15,16),5,150,-1);cv2.circle(t,(14,15),2,165,-1)
        faint=np.clip((t.astype(float)-100)*.25+105,0,255).astype(np.uint8);image=np.full((128,192,3),105,np.uint8)
        image[20:52,30:62]=cv2.cvtColor(faint,cv2.COLOR_GRAY2BGR);image[70:102,130:162]=cv2.cvtColor(faint,cv2.COLOR_GRAY2BGR)
        objects=lab.detect(image,[('anomalous',t)],.97,['anomalous']);self.assertEqual(sorted(m['box'] for m in objects),[[30,20,32,32],[130,70,32,32]])
        self.assertTrue(all(m['detail_score']>=.55 for m in objects))
    def test_observed_cloud_false_positive_is_rejected_and_actual_template_retained(self):
        folder=Path('/home/hackrf/migration/preserved/uap-lab/diagnostics/cloud-rejection');source=folder/'culprit-377.png';frame=folder/'cloud-0.png'
        if not source.exists() or not frame.exists():self.skipTest('Local cloud replay fixtures unavailable')
        t=cv2.imread(str(source),0);image=cv2.imread(str(frame))
        self.assertGreater(len(lab.detect(image,[('anomalous',t)],.97,['anomalous'],verify_detail=False)),0)
        self.assertEqual(lab.detect(image,[('anomalous',t)],.97,['anomalous']),[])
        patch=np.full((150,150,3),100,np.uint8);h,w=t.shape;patch[30:30+h,40:40+w]=cv2.cvtColor(t,cv2.COLOR_GRAY2BGR)
        actual=lab.detect(patch,[('anomalous',t)],.97,['anomalous']);self.assertTrue(any(m['box']==[40,30,w,h] for m in actual))
if __name__=='__main__':unittest.main()

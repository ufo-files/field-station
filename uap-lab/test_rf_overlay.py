import json,tempfile,unittest
from pathlib import Path
from rf_overlay import snapshot

class RFOverlayTests(unittest.TestCase):
    def test_both_receivers_are_separate_and_private_metadata_is_not_exposed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'live.json'
            data=dict(receivers={role:dict(timestamp=123,range_hz=bounds,average_db=[-80,None],maximum_db=[-70,None],device_serial='private-id') for role,bounds in [('narrow',[1590000000,1610000000]),('wide',[1000000,6000000000])]})
            path.write_text(json.dumps(data));result=snapshot(path)
            self.assertEqual(set(result['receivers']),{'narrow','wide'})
            self.assertEqual(result['receivers']['wide']['maximum_db'],[-70,None])
            self.assertNotIn('device_serial',json.dumps(result))
    def test_missing_or_invalid_data_is_unavailable_not_fake_live_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'missing.json';self.assertFalse(snapshot(path)['available'])
            path.write_text('{');self.assertEqual(snapshot(path)['receivers'],{})

if __name__=='__main__':unittest.main()

import unittest
from rf_experiment import prepare,status,PROFILES

class Experiments(unittest.TestCase):
    def test_exact_utf8(self):
        r=prepare({'message':'Hello 🌙'})
        self.assertEqual(bytes.fromhex(r['hex']),'Hello 🌙'.encode())
        self.assertEqual(r['bits'],len('Hello 🌙'.encode())*8)
        self.assertFalse(r['transmitted'])
    def test_every_profile_is_locked(self):
        self.assertFalse(status()['transmit_enabled'])
        for key,_,_ in PROFILES:
            self.assertFalse(prepare({'message':'test','profile':key})['transmitted'])
            with self.assertRaises(ValueError):prepare({'message':'test','profile':key,'action':'transmit'})
    def test_limits_cannot_be_overridden(self):
        for value in ({'message':'x','frequency_hz':1600000000},{'message':'x','enabled':True},{'message':'x','profile':'unlicensed'},{'message':'🌙'*65},{'message':' '},{'message':'bad\x00'},[]):
            with self.assertRaises(ValueError):prepare(value)
    def test_preset(self):
        for key in ('ham-technician','ham-general','ham-extra','shielded'):
            self.assertEqual(prepare({'message':'x','profile':key})['preset']['frequency_hz'],441500000)
        self.assertIsNone(prepare({'message':'x'})['preset']['frequency_hz'])
    def test_boundary(self):
        self.assertEqual(prepare({'message':'x'*256})['bytes'],256)
        with self.assertRaises(ValueError):prepare({'message':'x'*257})
if __name__=='__main__':unittest.main()

import json,unittest
from unittest.mock import patch,Mock
from system_temperature import Temperature

class TemperatureTests(unittest.TestCase):
 def test_numeric_temperature_and_invalid_sensor_values(self):
  monitor=Temperature()
  for raw in [70.12,None,0,float('nan'),True]:
   with patch('system_temperature.subprocess.run',return_value=Mock(stdout=json.dumps({'temp':{'cpu_temp_avg':raw}}))):
    if raw==70.12:self.assertEqual(monitor.read(),70.1)
    else:
     with self.assertRaises(ValueError):monitor.read()
 def test_requests_share_background_sample_and_expire_stale_values(self):
  monitor=Temperature()
  with patch('system_temperature.threading.Thread') as thread,patch('system_temperature.time.monotonic',return_value=100):
   for _ in range(10):self.assertFalse(monitor.snapshot()['available'])
   self.assertEqual(thread.call_count,1)
  monitor.value=70;monitor.measured=100;monitor.running=False;monitor.next_sample=200
  with patch('system_temperature.time.monotonic',return_value=120):self.assertEqual(monitor.snapshot()['celsius'],70)
  with patch('system_temperature.time.monotonic',return_value=146):self.assertIsNone(monitor.snapshot()['celsius'])

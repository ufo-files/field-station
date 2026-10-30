import unittest
from unittest.mock import patch
from mail_alerts import poll_replies_if_due
class ReplyScheduleTests(unittest.TestCase):
 def test_due_poll_runs_without_waiting_for_outgoing_batch(self):
  with patch('mail_alerts.time.monotonic',return_value=120),patch('reply_reviews.poll') as poll:
   self.assertEqual(poll_replies_if_due({'lab_data':'/tmp/lab'},50),120)
   poll.assert_called_once()
 def test_not_due_does_not_poll(self):
  with patch('mail_alerts.time.monotonic',return_value=120),patch('reply_reviews.poll') as poll:
   self.assertEqual(poll_replies_if_due({'lab_data':'/tmp/lab'},100),100)
   poll.assert_not_called()

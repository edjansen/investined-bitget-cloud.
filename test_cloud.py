import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import cloud_scan as cloud

class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.now=1800000000
        self.record=dict(symbol='BTC/USDT:USDT',side='LONG',pullback_timestamp=(self.now-600)*1000,
            candle_timestamp=(self.now-300)*1000,updated=self.now,phase='ENTRY CONFIRMED',
            quality_gate=True,plan={'risk_valid':True})
        self.state=dict(version=1,cutoff=self.now-1000,seen={},cursor=0)
    def test_same_pullback_later_trigger_is_duplicate(self):
        self.assertTrue(cloud.reserve(self.record,self.state,self.now))
        self.record['candle_timestamp']+=300000
        self.record['updated']+=300
        self.assertFalse(cloud.reserve(self.record,self.state,self.now+300))
    def test_reject_unconfirmed_stale_future_and_invalid(self):
        for updates in [dict(phase='PULLBACK ACTIVE'),dict(updated=self.now-16),
                        dict(updated=self.now+1),dict(candle_timestamp=(self.now-601)*1000),
                        dict(quality_gate=False),dict(plan={'risk_valid':False})]:
            record={**self.record,**updates}
            self.assertFalse(cloud.reserve(record,copy.deepcopy(self.state),self.now))
    def test_cold_cache_does_not_replay(self):
        with tempfile.TemporaryDirectory() as d, patch.object(cloud,'STATE',Path(d)/'state.json'):
            state=cloud.load_state(self.now)
            self.assertFalse(cloud.reserve(self.record,state,self.now))
    def test_restart_preserves_reservation(self):
        with tempfile.TemporaryDirectory() as d, patch.object(cloud,'STATE',Path(d)/'state.json'):
            cloud.reserve(self.record,self.state,self.now)
            cloud.save(cloud.STATE,self.state)
            self.assertFalse(cloud.reserve(self.record,cloud.load_state(self.now),self.now))
    def test_corrupt_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as d, patch.object(cloud,'STATE',Path(d)/'state.json'):
            cloud.STATE.write_text('{')
            with self.assertRaises(ValueError):cloud.load_state(self.now)
    def test_telegram_error_hides_token_and_does_not_retry(self):
        record={**self.record,'potential_pct':2,'rr1':1.5,'detected_utc':'test'}
        with patch.dict('os.environ',TELEGRAM_BOT_TOKEN='fake-secret',TELEGRAM_CHAT_ID='123'), patch.object(cloud,'urlopen',side_effect=OSError('fake-secret')) as request:
            with self.assertRaises(RuntimeError) as error: cloud.telegram(record)
            self.assertNotIn('fake-secret',str(error.exception));request.assert_called_once()

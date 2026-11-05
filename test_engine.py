import copy
import io
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch
from pullback_entry import evaluate
NOW = 1800000000

def fixture():
    row = dict(coin='BTC', symbol='BTC/USDT:USDT', exchange='BITGET', side='LONG', scan_utc=datetime.fromtimestamp(NOW, timezone.utc).isoformat())
    market = dict(id='BTCUSDT', symbol=row['symbol'], base='BTC', quote='USDT', settle='USDT', active=True, swap=True, linear=True, info=dict(isRwa='NO', symbolStatus='normal', baseCoin='BTC', quoteCoin='USDT', symbol='BTCUSDT'))
    raw = {}
    for tf, d in [('1d', 86400), ('4h', 14400), ('1h', 3600), ('15m', 900), ('5m', 300)]:
        raw[tf] = [[(NOW - d * (110 - i)) * 1000, 100, 101, 99, 100, 100] for i in range(110)]
    raw['4h'] = [[b[0], 100, 120, 90, 100, 100] for b in raw['4h']]
    raw['15m'][-3][1:5] = [100, 103, 100, 102]
    raw['15m'][-2][1:5] = [102, 102.2, 99.8, 100.2]
    raw['15m'][-1][1:5] = [100.2, 101.2, 100, 100.6]
    raw['5m'][-2][1:5] = [100.2, 100.8, 100, 100.4]
    raw['5m'][-1][1:5] = [100.4, 101.2, 100.2, 101]
    raw['5m'][-1][5] = 200  # Current engine derives RVOL from actual candles.
    frames = {'1d': {'loc': 0.3}, '4h': {'loc': 0.3, 'rsi': 45}, '1h': {'hh': True, 'hl': True}, '15m': {'rvol': 2}, '5m': {'rvol': 2, 'atr': 1}}
    ticker = dict(bid=100.99, ask=101.01, timestamp=NOW * 1000, quoteVolume=1000000)
    return (row, frames, raw, ticker, market)

class PullbackTests(unittest.TestCase):

    def setUp(self):
        self.args = list(fixture())

    def run_engine(self):
        return evaluate(*self.args, NOW)

    def test_valid_entry(self):
        r = self.run_engine()
        self.assertEqual(r['phase'], 'ENTRY CONFIRMED', r)
        self.assertAlmostEqual(r['rr1'], (105 - 101.01) / (101.01 - 99.55))
        self.assertEqual(r['passed'], r['total'])

    def test_breakout_without_pullback(self):
        for b in self.args[2]['15m']:
            b[1:5] = [100, 103, 100, 102]
        self.assertEqual(self.run_engine()['phase'], 'WAIT PULLBACK')

    def test_pullback_without_confirmation(self):
        self.args[2]['5m'][-1][4] = 100.5
        self.assertEqual(self.run_engine()['phase'], 'PULLBACK ACTIVE')

    def test_expired_signal(self):
        self.args[0]['scan_utc'] = datetime.fromtimestamp(NOW - 1501, timezone.utc).isoformat()
        self.assertEqual(self.run_engine()['phase'], 'EXPIRED')

    def test_wrong_location(self):
        self.args[1]['1d']['loc'] = 0.6
        self.assertEqual(self.run_engine()['phase'], 'INVALIDATED')

    def test_spread(self):
        self.args[3]['ask'] = 101.3
        self.assertIn('SPREAD', self.run_engine()['reason'])

    def test_missing_data(self):
        del self.args[2]['4h']
        r = self.run_engine()
        self.assertEqual(r['phase'], 'INVALIDATED')
        self.assertFalse(r['plan'])

    def test_unknown_identity(self):
        self.args[4]['base'] = 'OTHER'
        self.assertEqual(self.run_engine()['phase'], 'INVALIDATED')

    def test_suspicious(self):
        self.args[0]['suspicious'] = True
        self.assertEqual(self.run_engine()['phase'], 'INVALIDATED')

    def test_low_rr(self):
        for b in self.args[2]['4h']:
            b[2] = 113
        self.assertIn('RR', self.run_engine()['reason'])

    def test_distance(self):
        self.args[3].update(bid=102.1, ask=102.11)
        self.assertIn('ENTRYAFSTAND', self.run_engine()['reason'])

    def test_no_confirmation_before_pullback(self):
        self.args[2]['15m'][-2][1:5] = [101, 103, 100, 102]
        self.args[2]['15m'][-1][1:5] = [102, 102.2, 99.8, 100.2]
        self.assertEqual(self.run_engine()['phase'], 'PULLBACK ACTIVE')

    def test_short_symmetry(self):
        self.args[0]['side'] = 'SHORT'
        self.args[1]['1d']['loc'] = self.args[1]['4h']['loc'] = 0.7
        self.args[1]['1h'] = {'lh': True, 'll': True}
        for bars in self.args[2].values():
            for b in bars:
                b[1:5] = [200 - b[1], 200 - b[3], 200 - b[2], 200 - b[4]]
        self.args[3].update(bid=98.99, ask=99.01)
        self.assertEqual(self.run_engine()['phase'], 'ENTRY CONFIRMED')

    def test_validator_integration_no_nameerror(self):
        import investined_entry_alert as alert
        row, frames, raw, ticker, market = self.args
        from unittest.mock import Mock
        ex = Mock()
        ex.fetch_ticker.return_value = ticker
        ex.market.return_value = market
        ex.milliseconds.return_value = NOW * 1000
        with patch.object(alert, 'analyze', return_value=(frames, raw)):
            signal, reason = alert.validate_with_reason(row, ex)
        self.assertEqual(reason, 'ENTRY CONFIRMED')
        self.assertIsNotNone(signal)

    def test_stale_quote(self):
        self.args[3]['timestamp'] = (NOW - 16) * 1000
        self.assertEqual(self.run_engine()['phase'], 'EXPIRED')

    def test_expired_confirmation(self):
        for tf in ('5m', '15m'):
            for b in self.args[2][tf]:
                b[0] -= 1600000
        self.assertEqual(self.run_engine()['phase'], 'EXPIRED')

    def test_broken_pullback(self):
        self.args[2]['5m'][-2][3:5] = [99, 99.5]
        self.assertEqual(self.run_engine()['phase'], 'INVALIDATED')

    def test_missing_atr_has_no_rr(self):
        del self.args[1]['5m']['atr']
        r = self.run_engine()
        self.assertEqual(r['phase'], 'INVALIDATED')
        self.assertNotIn('rr1', r)

    def test_real_candle_analysis_public_only(self):
        import math
        import investined_entry_alert as alert
        from unittest.mock import Mock
        row, frames, raw, ticker, market = self.args
        raw['1d'] = copy.deepcopy(raw['4h'])
        for i, b in enumerate(raw['1d']):
            b[0] = (NOW - 86400 * (110 - i)) * 1000
        for i, b in enumerate(raw['1h']):
            close = 80 + i * 0.1 + math.sin(i * math.pi / 3)
            b[1:5] = [close, close + 0.5, close - 0.5, close]
        raw['15m'][-1][5] = raw['5m'][-1][5] = 200
        ex = Mock()
        ex.fetch_ohlcv.side_effect = lambda symbol, tf, limit: raw[tf]
        ex.parse_timeframe.side_effect = lambda tf: {'1d': 86400, '4h': 14400, '1h': 3600, '15m': 900, '5m': 300}[tf]
        ex.milliseconds.return_value = NOW * 1000
        ex.fetch_ticker.return_value = ticker
        ex.market.return_value = market
        signal, reason = alert.validate_with_reason(row, ex)
        self.assertIsNotNone(signal, reason)
        ex.fetch_positions.assert_not_called()
        ex.create_order.assert_not_called()
if __name__ == '__main__':
    unittest.main()

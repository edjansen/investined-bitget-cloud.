"""On-demand, public-data-only Bitget review using existing Investined engine."""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re

import ccxt
from investined_entry_alert import analyze
from pullback_entry import contract_valid

TFS = ('1d', '4h', '1h', '15m', '5m')
SUMMARY_KEYS = ('structure', 'hh', 'hl', 'lh', 'll', 'bos_up', 'bos_dn',
                'choch', 'sweep_low', 'sweep_high', 'loc', 'rsi',
                'atr', 'atr_pct', 'rvol', 'ema20', 'ema50')


def coins(value):
    if not value:
        value = ','.join(json.loads(Path('analysis_request.json').read_text())['coins'])
    unique = []
    for part in value.replace(';', ',').split(','):
        coin = part.strip().upper().removesuffix('/USDT:USDT')
        if coin.endswith('USDT') and len(coin) > 5:
            coin = coin[:-4]
        if not coin:
            continue
        if not re.fullmatch('[A-Z0-9]{2,20}', coin):
            raise ValueError('Invalid contract name')
        if coin not in unique:
            unique.append(coin)
    if not 1 <= len(unique) <= 20:
        raise ValueError('Expected 1-20 unique coins')
    return unique


def clean(v):
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, (tuple, list)):
        return [clean(x) for x in v]
    return v


def inspect(ex, coin):
    matches = [m for m in ex.markets.values()
               if str(m.get('base') or '').upper() == coin and
               m.get('quote') == 'USDT' and m.get('settle') == 'USDT' and
               m.get('swap') is True and m.get('linear') is True]
    result = {'coin': coin, 'status': 'UNAVAILABLE'}
    if len(matches) != 1:
        result['reason'] = 'No unique Bitget USDT futures contract'
        return result
    market = matches[0]
    symbol = market['symbol']
    result['symbol'] = symbol
    result['contract_id'] = market['id']
    if not contract_valid({'coin': coin, 'symbol': symbol}, market):
        result.update(status='REJECTED', reason='Contract identity or asset gate')
        return result
    try:
        analyzed = analyze(ex, symbol)
        if not analyzed:
            raise ValueError('Insufficient closed candles')
        frames, candles = analyzed
        ticker = ex.fetch_ticker(symbol)
        result['candles'] = candles
        result['timeframes'] = {
            tf: {**{k: frames[tf].get(k) for k in SUMMARY_KEYS},
                 'bars': len(candles[tf]),
                 'last_closed_ms': candles[tf][-1][0] + ex.parse_timeframe(tf)*1000}
            for tf in TFS}
        bid, ask = ticker.get('bid'), ticker.get('ask')
        result['market'] = {'bid': bid, 'ask': ask, 'last': ticker.get('last'),
                            'quote_volume_24h': ticker.get('quoteVolume'),
                            'quote_timestamp_ms': ticker.get('timestamp'),
                            'spread_pct': 200*(ask-bid)/(ask+bid)
                            if isinstance(bid, (float, int)) and
                            isinstance(ask, (float, int)) and 0 < bid <= ask else None}
        result['status'] = 'ANALYZED'
        for method, field, key in [('fetch_funding_rate', 'funding_rate', 'fundingRate'),
                                   ('fetch_open_interest', 'open_interest', 'openInterestAmount')]:
            try:
                result[field] = getattr(ex, method)(symbol).get(key)
            except (ccxt.BaseError, AttributeError, TypeError):
                result[field] = None
    except (ccxt.BaseError, ValueError, TypeError, KeyError, IndexError) as error:
        result.update(status='DATA_ERROR', reason=type(error).__name__)
    return clean(result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--coins', default=os.environ.get('ANALYZE_COINS', ''))
    requested = coins(parser.parse_args().coins)
    ex = ccxt.bitget({'enableRateLimit': True, 'timeout': 15000,
                      'options': {'defaultType': 'swap'}})
    ex.load_markets()
    results = [inspect(ex, coin) for coin in requested]
    stamp = datetime.now(timezone.utc).isoformat()
    report = dict(source='Bitget public API via CCXT', generated_utc=stamp,
                  requested=requested, results=results,
                  note='Read-only, no orders. A project-integrity guarantee is impossible.')
    Path('analysis_report.json').write_text(json.dumps(clean(report), indent=2, allow_nan=False))
    lines = ['# INVESTINED LABS — Bitget coin review', '',
             f'UTC: {stamp}. 1D/4H/1H/15m/5m closed OHLCV candles.', '',
             '| Coin | Contract | 1H structure | 4H location | 5m RVOL |',
             '| --- | --- | --- | --- | --- |']
    for r in results:
        if r['status'] != 'ANALYZED':
            lines.append(f"| {r['coin']} | {r['status']} | - | {r.get('reason', '-')} | - |")
        else:
            lines.append(f"| {r['coin']} | {r['symbol']} | {r['timeframes']['1h']['structure']} | "
                         f"{r['timeframes']['4h']['loc']:.2f} | {r['timeframes']['5m']['rvol']} |")
    lines += ['', 'Volledige candlesticks, indicatoren en redenen: analysis_report.json.',
              'Geen automatische orders; alleen gesloten candles worden beoordeeld.']
    Path('analysis_report.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines), flush=True)
    if not any(r['status'] == 'ANALYZED' for r in results):
        raise SystemExit('No usable market data; see diagnostic artifact')


if __name__ == '__main__':
    main()

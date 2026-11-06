"""Terminal screenshot batch review: separate futures, global radar, spot markets.
Public market data only; no account access or orders.
"""
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time
import ccxt

from investined_on_demand import inspect, clean, SUMMARY_KEYS, TFS
from investined_entry_alert import analyze
from pullback_entry import evaluate


def check_spot(ex, coin):
    result = {'coin': coin, 'market_kind': 'SPOT', 'status': 'UNAVAILABLE'}
    matching = [m for m in ex.markets.values()
                if m.get('base', '').upper() == coin
                and m.get('quote') == 'USDT'
                and m.get('spot') is True and m.get('swap') is not True
                and m.get('active') is True]
    if len(matching) != 1:
        result['reason'] = 'No unique active Bitget USDT spot instrument'
        return result
    m = matching[0]
    result.update(symbol=m['symbol'], contract_id=m.get('id'))
    try:
        data = analyze(ex, m['symbol'])
        if not data:
            raise ValueError('Insufficient closed candles')
        frames, bars = data
        ticker = ex.fetch_ticker(m['symbol'])
        bid, ask = ticker.get('bid'), ticker.get('ask')
        result['timeframes'] = {
            tf: {**{k: frames[tf].get(k) for k in SUMMARY_KEYS},
                 'bars': len(bars[tf]),
                 'last_closed_ms': bars[tf][-1][0] + ex.parse_timeframe(tf)*1000}
            for tf in TFS}
        result['candles'] = bars
        result['market'] = {
            'bid': bid, 'ask': ask, 'last': ticker.get('last'),
            'quote_volume_24h': ticker.get('quoteVolume'),
            'quote_timestamp_ms': ticker.get('timestamp'),
            'spread_pct': 200*(ask-bid)/(ask+bid)
              if isinstance(bid,(float,int)) and isinstance(ask,(float,int)) and 0 < bid <= ask
              else None}
        result.update(status='ANALYZED', instrument_type='BITGET_SPOT',
                      entry_status='SPOT_RESEARCH_ONLY')
    except (ccxt.BaseError, ValueError, TypeError, KeyError, IndexError) as error:
        result.update(status='DATA_ERROR', reason=type(error).__name__)
    return clean(result)


def check_future(ex, coin):
    result = inspect(ex, coin)
    result['market_kind'] = 'USDT_PERPETUAL'
    if result.get('status') == 'ANALYZED':
        if result.get('instrument_type') == 'CRYPTO_USDT_PERP':
            try:
                symbol = result['symbol']
                row = {'coin':coin, 'symbol':symbol, 'side':'LONG',
                       'exchange':'BITGET', 'scan_utc':datetime.now(timezone.utc).isoformat()}
                ticker = ex.fetch_ticker(symbol)
                now = time.time()
                longr = evaluate(row, result['timeframes'], result['candles'], ticker, ex.market(symbol), now)
                row['side'] = 'SHORT'
                shortr = evaluate(row, result['timeframes'], result['candles'], ticker, ex.market(symbol), now)
                result['entry_checks'] = [{
                    'side':r['side'], 'phase':r['phase'], 'reason':r['reason'],
                    'distance_pct':r.get('distance_pct'),
                    'plan':r.get('plan') if r.get('plan',{}).get('risk_valid') else None,
                    'rvol5':r.get('iv_rvol5'),
                    'spread_pct':r.get('spread_pct')}
                    for r in (longr, shortr)]
            except (ccxt.BaseError, ValueError, KeyError, IndexError, TypeError) as e:
                result['entry_checks'] = [{'phase':'CHECK_ERROR', 'reason':type(e).__name__}]
        else:
            result['entry_status'] = 'RWA_RESEARCH_ONLY'
    return clean(result)


def main():
    request = json.loads(Path('terminal_review_request.json').read_text())
    groups = request['groups']
    ex = ccxt.bitget({'enableRateLimit': True, 'timeout': 15000,
                      'options': {'defaultType':'swap'}})
    ex.load_markets()
    spot = ccxt.bitget({'enableRateLimit': True, 'timeout': 15000,
                        'options': {'defaultType':'spot'}})
    spot.load_markets()

    records = {}
    for group, tokens in groups.items():
        if group not in ('futures_pullbacks', 'global_radar', 'spot_entry_list'):
            raise ValueError('Invalid group')
        entries = []
        for coin in tokens:
            if not isinstance(coin,str) or len(coin)>25:
                raise ValueError('Invalid symbol')
            print(f'Checking {group} / {coin}', flush=True)
            if group == 'spot_entry_list':
                entries.append(check_spot(spot, coin.upper()))
            else:
                entries.append(check_future(ex, coin.upper()))
        records[group] = entries
    report = {'generated_utc':datetime.now(timezone.utc).isoformat(),
              'source':'Bitget public REST API via CCXT',
              'notes':['All candlestick OHLCV bars are closed.',
                       'Global Radar and Stock RWA technical reviews are not crypto entry confirmations.',
                       'Spot review uses genuine Bitget spot pairs, not futures substitutes.',
                       'Unverified/missing data cannot justify an entry.'],
              'groups':records}
    Path('terminal_review_report.json').write_text(json.dumps(clean(report),ensure_ascii=False,indent=2,allow_nan=False))
    lines=['# INVESTINED LABS terminal — full review',
           '', 'UTC: '+report['generated_utc'],'']
    for group, entries in records.items():
        lines += ['## '+group, '',
                  '| Coin | Type | 4H | 1H | 15m | 5m RVOL | 24h volume USD | Spread % | Entry phase |',
                  '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
        for r in entries:
            if r['status']!='ANALYZED':
                lines.append(f"| {r['coin']} | {r['status']} | - | - | - | - | - | - | {r.get('reason','-')} |")
                continue
            frames=r['timeframes']; mark=r['market']
            phases=', '.join(f"{x['side']} {x['phase']}" for x in r.get('entry_checks',[]))
            if not phases: phases=r.get('entry_status','TECHNICAL_RESEARCH_ONLY')
            v=mark.get('quote_volume_24h')
            sp=mark.get('spread_pct')
            lines.append(f"| {r['coin']} | {r['instrument_type']} | {frames['4h']['structure']} | "
                 f"{frames['1h']['structure']} | {frames['15m']['structure']} | "
                 f"{frames['5m']['rvol']:.2f} | {round(v,1) if v is not None else '-'} | "
                 f"{round(sp,4) if sp is not None else '-'} | {phases} |")
        lines.append('')
    Path('terminal_review_report.md').write_text('\n'.join(lines))
    print('\n'.join(lines),flush=True)
    if not any(x.get('status')=='ANALYZED' for xs in records.values() for x in xs):
        raise SystemExit('No verified market data')


if __name__ == '__main__':
    main()

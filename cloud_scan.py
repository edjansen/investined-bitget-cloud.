"""Public Bitget scanner. No accounts, orders or credentials for exchanges."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen
import ccxt
from investined_entry_alert import analyze, validate_with_reason
from pullback_entry import evaluate, contract_valid

STATE = Path('state/dedup.json')
OUTBOX = Path('outbox.json')

def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, allow_nan=False))
    temp.replace(path)

def load_state(now):
    if not STATE.exists():
        # A lost cache must not replay setups that could already have been sent.
        return {'version': 1, 'cutoff': now, 'seen': {}, 'cursor': 0}
    state = json.loads(STATE.read_text())
    if state['version'] != 1 or not isinstance(state['seen'], dict):
        raise ValueError('Invalid state')
    if not 0 <= state['cutoff'] <= now:
        raise ValueError('Invalid state timestamp')
    state['seen'] = {k:v for k,v in state['seen'].items() if 0 <= now-v < 172800}
    return state

def identity(record):
    # One notification per pullback, even if a later trigger candle confirms again.
    return hashlib.sha256(json.dumps([record['symbol'], record['side'],
        record['pullback_timestamp']], separators=(',', ':')).encode()).hexdigest()

def fresh(record, now):
    try:
        return (record['phase'] == 'ENTRY CONFIRMED'
            and record['quality_gate'] is True
            and record['plan']['risk_valid'] is True
            and 0 <= now-record['updated'] <= 15
            and 0 <= now-(record['candle_timestamp']/1000+300) <= 300)
    except (KeyError, TypeError, ValueError):
        return False

def reserve(record, state, now):
    if not fresh(record, now) or record['pullback_timestamp']/1000 <= state['cutoff']:
        return False
    key = identity(record)
    if key in state['seen']:
        return False
    state['seen'][key] = now
    return True

def client():
    return ccxt.bitget({'enableRateLimit': True, 'timeout': 15000,
                        'options': {'defaultType': 'swap'}})

def prepare(budget):
    now = time.time()
    state = load_state(now)
    ex = client()
    ex.load_markets()
    tickers = ex.fetch_tickers(params={'productType': 'USDT-FUTURES'})
    markets = sorted((m for m in ex.markets.values()
        if contract_valid({'coin':m.get('base'), 'symbol':m.get('symbol')}, m)
        and float(tickers.get(m['symbol'], {}).get('quoteVolume') or 0) >= 1000000),
        key=lambda m:m['symbol'])
    selected = os.environ.get('SCAN_SYMBOLS', '').split(',')
    if any(selected):
        markets = [m for m in markets if m['symbol'] in selected]
    if not markets:
        raise RuntimeError('No eligible markets')
    start = time.monotonic()
    outbox = []
    checked = failed = 0
    cursor = state['cursor'] % len(markets)
    while checked < len(markets) and time.monotonic()-start < budget:
        market = markets[(cursor+checked) % len(markets)]
        checked += 1
        try:
            data = analyze(ex, market['symbol'])
            if not data:
                failed += 1
                continue
            frames, raw = data
            ticker = ex.fetch_ticker(market['symbol'])
            stamp = time.time()
            for side in ('LONG', 'SHORT'):
                row = dict(coin=market['base'], symbol=market['symbol'], exchange='BITGET',
                    side=side, scan_utc=datetime.fromtimestamp(stamp, timezone.utc).isoformat())
                record = evaluate(row, frames, raw, ticker, market, stamp)
                if reserve(record, state, time.time()):
                    outbox.append({'row': row, 'key':identity(record)})
        except (ccxt.BaseError, KeyError, ValueError, TypeError):
            failed += 1
    state['cursor'] = (cursor+checked) % len(markets)
    save(STATE, state)
    save(OUTBOX, outbox)
    print(json.dumps({'eligible':len(markets), 'checked':checked, 'failed':failed,
                      'reserved':len(outbox), 'complete_coverage':checked==len(markets)}))
    if failed == checked:
        raise RuntimeError('All market checks failed')

def telegram(record):
    token = os.environ['TELEGRAM_BOT_TOKEN']
    chat = os.environ['TELEGRAM_CHAT_ID']
    text = (f"Investined — ENTRY CONFIRMED\nBitget {record['symbol']} {record['side']}\n"
        f"Potentieel naar 4H EQ: {record['potential_pct']:.2f}% | theoretische RR: {record['rr1']:.2f}\n"
        f"Gecontroleerd: {record['detected_utc']}\nPositie onbekend. Geen order geplaatst.")
    request = Request('https://api.telegram.org/b'+ 'ot'+token+'/sendMessage',
        data=json.dumps({'chat_id':chat, 'text':text, 'disable_notification':False,
                         'protect_content':True}).encode(),
        headers={'Content-Type':'application/json'}, method='POST')
    # Never retry an ambiguous delivery: Telegram has no idempotency key.
    try:
        with urlopen(request, timeout=15) as response:
            if not json.load(response).get('ok'):
                raise RuntimeError()
    except Exception:
        raise RuntimeError('Telegram delivery failed or uncertain; not retried') from None

def send():
    pending = json.loads(OUTBOX.read_text())
    if not pending:
        return
    state = load_state(time.time())
    ex = client()
    ex.load_markets()
    for item in pending:
        if item['key'] not in state['seen']:
            raise RuntimeError('Unreserved notification')
        record, _ = validate_with_reason(item['row'], ex)
        if record and identity(record)==item['key'] and fresh(record, time.time()):
            telegram(record)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['prepare', 'send'])
    parser.add_argument('--budget', type=int, default=150)
    args = parser.parse_args()
    try:
        prepare(args.budget) if args.mode=='prepare' else send()
    except Exception as exc:
        # Third-party exceptions may contain URLs or credentials. Log type only.
        print('Run failed:', type(exc).__name__)
        raise SystemExit(1)

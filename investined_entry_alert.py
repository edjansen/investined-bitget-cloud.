from investined_display_metrics import frame_metrics, location as display_location
import csv
import json
import math
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import ccxt
import investined_global_futures as base

ROOT = Path("runtime")
SOURCE = ROOT / "global_futures_opportunities_v3.csv"
STATE = ROOT / "investined_entry_alert_state.json"
HISTORY = ROOT / "investined_confirmed_entries.jsonl"

CHECK_SECONDS = 60
MAX_CANDIDATES = 25

def number(value):
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None

def load_state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {"alerts": {}}

def save_state(state):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE)

def recent_closed_candles(ex, symbol, timeframe):
    # Zelfstandige refresh: niet afhankelijk van verouderde cache.
    duration = ex.parse_timeframe(timeframe) * 1000
    now = ex.milliseconds()
    # Cache only until the next candle close; failed/stale fetches never extend it.
    cache = getattr(recent_closed_candles, 'cache', {})
    key = (id(ex), symbol, timeframe)
    cached = cache.get(key)
    if cached and cached[0] == now // duration:
        return cached[1]
    candles = ex.fetch_ohlcv(symbol, timeframe, limit=110)
    duration = ex.parse_timeframe(timeframe) * 1000
    now = ex.milliseconds()

    closed = [
        c for c in candles
        if len(c) >= 6
        and c[0] + duration <= now
    ]
    if closed and closed[-1][0] + duration == (now // duration) * duration:
        cache[key] = (now // duration, closed)
        recent_closed_candles.cache = cache
    return closed

def active_bos(candles,lookback):
    """Replay recent closes against pivots already confirmed at that time."""
    event=None
    for j in range(max(5,len(candles)-lookback),len(candles)):
        highs=[];lows=[]
        for i in range(2,j-1):
            if all(candles[i][2]>candles[k][2] for k in (i-2,i-1,i+1,i+2)):
                highs.append(candles[i][2])
            if all(candles[i][3]<candles[k][3] for k in (i-2,i-1,i+1,i+2)):
                lows.append(candles[i][3])
        prior=candles[j-1][4];close=candles[j][4]
        if event and (close<=event[1] if event[0]=="UP" else close>=event[1]):event=None
        if highs and prior<=highs[-1]<close:event=("UP",highs[-1])
        if lows and prior>=lows[-1]>close:event=("DOWN",lows[-1])
    return event

def analyze(ex, symbol):
    result = {}
    raw = {}

    for tf in ("1d", "4h", "1h", "15m", "5m"):
        candles = recent_closed_candles(ex, symbol, tf)
        analysis = base.analyze(candles)

        if analysis is None:
            return None

        if tf in ("1h","15m"):
            event=active_bos(candles,3 if tf=="1h" else 4)
            if event:
                analysis["bos_up"]=event[0]=="UP"
                analysis["bos_dn"]=event[0]=="DOWN"
        raw[tf] = candles
        result[tf] = analysis

    return result, raw



def candidate_range(closed, side, price):
    from equilibrium_target import equilibrium_target
    return equilibrium_target(closed,side,price)["remaining_pct"]

def validate(row, ex, diagnostics=None, near_records=None):
    from pullback_entry import evaluate
    data = analyze(ex, row.get("symbol"))
    frames, raw = data if data else ({}, {})
    record = evaluate(row, frames, raw, ex.fetch_ticker(row["symbol"]),
                      ex.market(row["symbol"]), ex.milliseconds()/1000)
    record.update(frame_metrics(raw, ex.milliseconds()))
    if near_records is not None:
        near_records.append(record)
    if diagnostics is not None:
        diagnostics.append(record["phase"] + ": " + record["reason"])
    return record if record["phase"] == "ENTRY CONFIRMED" else None

_original_validate = validate

def validate_with_reason(row, ex, near_records=None):
    reasons = []
    signal = _original_validate(row, ex, diagnostics=reasons, near_records=near_records)
    return signal, "ENTRY CONFIRMED" if signal else (reasons[-1] if reasons else "CONTROLE ONVOLLEDIG")

def validate(row, ex):
    signal, reason = validate_with_reason(row, ex)
    print(f"ENTRY CHECK | {row.get('coin', '?'):<12} {row.get('side', '?'):<5} {reason}", flush=True)
    return signal


def display(signal):
    print()
    print("\a", end="", flush=True)

    print("=" * 72)
    print("🔔 INVESTINED — ENTRY CONFIRMED")
    print("=" * 72)

    print(f"COIN       {signal['coin']}")
    print(f"EXCHANGE   {signal['exchange']}")
    print(f"CONTRACT   {signal['symbol']}")
    print(f"RICHTING   {signal['side']}")
    print(f"SETUP      {signal['setup']}")
    print("-" * 72)

    print(f"TRIGGER    {signal['entry_reference']:.8g}")
    print("DOELTYPE   4H EQUILIBRIUM")
    print(f"RR TP1     1:{signal['rr1']:.1f}")
    print(f"POTENTIEEL {signal.get('potential_pct', 0):.2f}%")

    print("-" * 72)
    print("TECHNISCHE BEVESTIGING")

    for check in signal["checks"]:
        print("✓", check)

    print(f"RVOL15     {signal['rvol15']:.2f}x")
    print(f"RVOL5      {signal['rvol5']:.2f}x")
    print(f"SPREAD     {signal['spread_pct']:.3f}%")

    print("=" * 72)
    print("ONDERZOEKSSIGNAAL — GEEN AUTOMATISCHE ORDER")
    print("Prijzen zijn referenties; uitvoering is niet gegarandeerd.")
    print("=" * 72, flush=True)

    # macOS ingebouwd geluid.
    try:
        subprocess.run(
            ["afplay", "/System/Library/Sounds/Glass.aiff"],
            check=False,
            timeout=5,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass

def load_candidates():
    if not SOURCE.exists():
        return []

    if time.time() - SOURCE.stat().st_mtime > 25 * 60:
        print(
            "Kandidaten ouder dan 25 minuten: geen entryalerts.",
            flush=True
        )
        return []

    with SOURCE.open(newline="") as f:
        rows = list(csv.DictReader(f))

    return [
        row for row in rows
        if row.get("side") in ("LONG", "SHORT")
        and row.get("exchange")
        and row.get("symbol")
    ][:MAX_CANDIDATES]

def check_once():
    rows = load_candidates()

    if not rows:
        print("Geen geschikte V3-kandidaten voor entrycontrole.", flush=True)
        return

    state = load_state()
    alerted = state.setdefault("alerts", {})

    clients = {}

    try:
        for row in rows:
            name = row["exchange"].lower()

            if name not in ("bitget", "bybit", "blofin", "mexc"):
                continue

            try:
                if name not in clients:
                    cls = getattr(ccxt, name)
                    clients[name] = cls({
                        "enableRateLimit": True,
                        "timeout": 15000,
                    })
                    clients[name].load_markets()

                ex = clients[name]
                symbol = row["symbol"]

                market = ex.market(symbol)

                if not (
                    market.get("swap") is True
                    and market.get("linear") is True
                    and market.get("settle") == "USDT"
                    and market.get("active") is not False
                ):
                    continue

                signal = validate(row, ex)

                if signal is None:
                    continue

                key = "|".join([
                    name,
                    symbol,
                    signal["side"],
                    signal["setup"],
                    str(signal["candle_timestamp"]),
                ])

                if key in alerted:
                    continue

                # Eerst vastleggen, dan geluid.
                alerted[key] = signal["detected_utc"]
                save_state(state)

                with HISTORY.open("a") as f:
                    f.write(json.dumps(signal) + "\n")

                display(signal)

            except Exception as error:
                print(
                    f"Controle mislukt voor {row.get('coin')}: "
                    f"{str(error)[:100]}",
                    flush=True
                )

    finally:
        for ex in clients.values():
            try:
                ex.close()
            except Exception:
                pass

def main():
    continuous = "--watch" in sys.argv

    print("=" * 72)
    print("INVESTINED — CONFIRMED ENTRY ALERT")
    print("Geluid uitsluitend bij een nieuw gevalideerd entrysignaal.")
    print("Geen orders.")
    print("=" * 72, flush=True)

    while True:
        check_once()

        if not continuous:
            break

        print(
            f"Entrycontrole voltooid. Volgende controle over "
            f"{CHECK_SECONDS} seconden.",
            flush=True
        )

        time.sleep(CHECK_SECONDS)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nEntry-alert gestopt.")

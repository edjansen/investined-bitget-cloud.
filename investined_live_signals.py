import csv
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

ROOT = Path("runtime")
ROOT.mkdir(exist_ok=True)

INPUTS = {
    "SPOT": ROOT / "discovery_spot_all.csv",
    "FUTURES": ROOT / "discovery_futures_all.csv",
}

VENUES = ["bitget", "bybit", "blofin", "mexc"]

STABLE = {
    "USDT", "USDC", "DAI", "FDUSD", "USDE",
    "USDD", "PYUSD", "EURC", "RLUSD", "FRAX"
}

OTHER = {
    "SPY", "QQQ", "IWM", "VOO", "GLD", "SLV",
    "NVIDIA", "NVDA", "AAPL", "TSLA", "MRVL",
    "MU", "SNDK", "SNDKSTOCK", "MUSTOCK",
    "NBISSTOCK", "OPENAI", "XAU", "XAG",
    "XAUT", "PAXG", "ZCHF"
}

TIMEFRAMES = {
    "1d": 86400000,
    "4h": 14400000,
    "15m": 900000,
}

LIMIT_PER_STRATEGY = 10


def num(value, default=None):
    try:
        n = float(value)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError):
        return default


def read(path):
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def classify(base):
    base = str(base or "").upper()
    if base in STABLE:
        return "STABLE"
    if (
        base in OTHER
        or base.endswith("STOCK")
        or base.startswith("GOLD(")
    ):
        return "OTHER_INSTRUMENT"
    return "CRYPTO_CANDIDATE"


def eligible(row, kind):
    coin = str(row.get("coin") or "").upper()
    volume = num(row.get("volume_24h"), 0)
    spread = num(row.get("spread_pct"))

    if classify(coin) != "CRYPTO_CANDIDATE":
        return False

    minimum = 250000 if kind == "SPOT" else 1000000

    return (
        volume >= minimum
        and spread is not None
        and 0 <= spread <= 0.5
        and row.get("quote") in ("USD", "USDT", "USDC")
    )



def select_candidates(rows, kind):
    import hashlib

    state_file = ROOT / "live_rotation_v2.json"

    try:
        state = json.loads(state_file.read_text())
    except (OSError, ValueError):
        state = {}

    bands = defaultdict(list)

    for row in rows:
        if eligible(row, kind):
            band = str(row.get("volume_band") or "")
            if band in (
                "LOWER_VOLUME",
                "MEDIUM_VOLUME",
                "HIGH_VOLUME"
            ):
                bands[band].append(row)

    quotas = {
        "LOWER_VOLUME": 4,
        "MEDIUM_VOLUME": 3,
        "HIGH_VOLUME": 3
    }

    selected = []
    seen = set()

    def identity(row):
        return (
            str(row.get("coin") or "").upper(),
            str(row.get("exchange") or ""),
            str(row.get("market_id") or "")
        )

    for band, quota in quotas.items():
        candidates = bands[band]

        candidates.sort(
            key=lambda row: hashlib.sha256(
                repr(identity(row)).encode()
            ).hexdigest()
        )

        if not candidates:
            continue

        key = kind + ":" + band
        offset = int(state.get(key, 0)) % len(candidates)

        rotated = candidates[offset:] + candidates[:offset]

        visited = 0
        taken = 0

        for row in rotated:
            visited += 1
            coin = identity(row)[0]

            if not coin or coin in seen:
                continue

            selected.append(row)
            seen.add(coin)
            taken += 1

            if taken >= quota:
                break

        state[key] = int(state.get(key, 0)) + visited

    # Vul lege plaatsen uit de overige volumeklassen.
    if len(selected) < LIMIT_PER_STRATEGY:
        remaining = []

        for band in quotas:
            remaining.extend(bands[band])

        remaining.sort(
            key=lambda row: hashlib.sha256(
                repr(identity(row)).encode()
            ).hexdigest()
        )

        key = kind + ":FILL"

        if remaining:
            offset = int(state.get(key, 0)) % len(remaining)
            rotated = remaining[offset:] + remaining[:offset]

            visited = 0

            for row in rotated:
                visited += 1
                coin = identity(row)[0]

                if not coin or coin in seen:
                    continue

                selected.append(row)
                seen.add(coin)

                if len(selected) >= LIMIT_PER_STRATEGY:
                    break

            state[key] = int(state.get(key, 0)) + visited

    state_file.write_text(json.dumps(state, indent=2))

    return selected[:LIMIT_PER_STRATEGY]


def ema(values, period):
    if len(values) < period:
        return None

    value = sum(values[:period]) / period
    alpha = 2 / (period + 1)

    for x in values[period:]:
        value = alpha * x + (1 - alpha) * value

    return value


def rsi(values, period=14):
    if len(values) < period + 1:
        return None

    moves = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]

    gains = [max(x, 0) for x in moves]
    losses = [max(-x, 0) for x in moves]

    gain = sum(gains[:period]) / period
    loss = sum(losses[:period]) / period

    for i in range(period, len(moves)):
        gain = (gain * (period - 1) + gains[i]) / period
        loss = (loss * (period - 1) + losses[i]) / period

    if loss == 0:
        return 100 if gain > 0 else 50

    return 100 - 100 / (1 + gain / loss)


def analyze(candles, timeframe):
    now = int(time.time() * 1000)
    duration = TIMEFRAMES[timeframe]

    # Alleen gesloten candles gebruiken.
    valid = []

    for row in candles:
        if len(row) < 6:
            continue

        ts, op, hi, lo, close, vol = row[:6]

        values = [num(x) for x in (ts, op, hi, lo, close, vol)]

        if any(x is None for x in values):
            continue

        ts, op, hi, lo, close, vol = values

        if (
            ts + duration > now
            or min(op, hi, lo, close) <= 0
            or vol < 0
            or hi < max(op, close, lo)
            or lo > min(op, close, hi)
        ):
            continue

        valid.append(values)

    valid.sort(key=lambda r: r[0])

    # Dubbele tijdstempels verwijderen.
    unique = {int(r[0]): r for r in valid}
    valid = [unique[t] for t in sorted(unique)]

    if len(valid) < 55:
        return None

    closes = [r[4] for r in valid]
    highs = [r[2] for r in valid]
    lows = [r[3] for r in valid]
    volumes = [r[5] for r in valid]

    baseline = sum(volumes[-21:-1]) / 20

    rv = (
        volumes[-1] / baseline
        if baseline > 0 else None
    )

    last = closes[-1]
    e20 = ema(closes, 20)
    e50 = ema(closes, 50)

    recent_high = max(highs[-40:])
    recent_low = min(lows[-40:])

    width = recent_high - recent_low

    location = (
        (last - recent_low) / width
        if width > 0 else None
    )

    true_ranges = []

    for i in range(1, len(valid)):
        hi = highs[i]
        lo = lows[i]
        prev = closes[i - 1]

        true_ranges.append(
            max(hi - lo, abs(hi - prev), abs(lo - prev))
        )

    atr = sum(true_ranges[-14:]) / 14

    return {
        "bars": len(valid),
        "price": last,
        "ema20": e20,
        "ema50": e50,
        "rsi": rsi(closes),
        "rvol": rv,
        "location": location,
        "range_high": recent_high,
        "range_low": recent_low,
        "atr_pct": 100 * atr / last,
        "trend": (
            "UP" if last > e20 > e50
            else "DOWN" if last < e20 < e50
            else "MIXED"
        ),
    }



def confirmed_structure(candles, timeframe):
    """Confirmed fractal pivots from closed candles only."""
    now_ms = int(time.time() * 1000)
    duration = TIMEFRAMES[timeframe]
    clean = {}

    for bar in candles:
        if len(bar) < 6:
            continue
        v = [num(x) for x in bar[:6]]
        if any(x is None for x in v):
            continue
        ts, op, hi, lo, cl, volume = v
        if ts + duration > now_ms:
            continue
        if min(op, hi, lo, cl) <= 0 or volume < 0:
            continue
        if hi < max(op, lo, cl) or lo > min(op, hi, cl):
            continue
        clean[int(ts)] = v

    data = [clean[t] for t in sorted(clean)]
    if len(data) < 25:
        return {"hl": "N/B", "lh": "N/B",
                "bos": "N/B", "choch": "N/B",
                "sweep": "N/B", "rvol": None}

    highs = [b[2] for b in data]
    lows = [b[3] for b in data]
    closes = [b[4] for b in data]
    volumes = [b[5] for b in data]

    ph, pl = [], []
    k = 2

    for i in range(k, len(data)-k):
        if highs[i] > max(highs[i-k:i]) and highs[i] > max(highs[i+1:i+k+1]):
            ph.append((i, highs[i]))
        if lows[i] < min(lows[i-k:i]) and lows[i] < min(lows[i+1:i+k+1]):
            pl.append((i, lows[i]))

    hl = "N/B"
    lh = "N/B"

    if len(pl) >= 2:
        hl = "YES" if pl[-1][1] > pl[-2][1] else "NO"

    if len(ph) >= 2:
        lh = "YES" if ph[-1][1] < ph[-2][1] else "NO"

    bos = "NONE"
    choch = "UNCONFIRMED"
    sweep = "NONE"

    last_close = closes[-1]
    previous_close = closes[-2]

    if ph and previous_close <= ph[-1][1] < last_close:
        bos = "BULLISH"
    elif pl and previous_close >= pl[-1][1] > last_close:
        bos = "BEARISH"

    # An unambiguous reversal requires previously confirmed
    # higher-high/higher-low or lower-high/lower-low sequence.
    if len(ph) >= 2 and len(pl) >= 2:
        uptrend = (
            ph[-1][1] > ph[-2][1]
            and pl[-1][1] > pl[-2][1]
        )
        downtrend = (
            ph[-1][1] < ph[-2][1]
            and pl[-1][1] < pl[-2][1]
        )
        if uptrend and bos == "BEARISH":
            choch = "BEARISH_CONFIRMED"
        elif downtrend and bos == "BULLISH":
            choch = "BULLISH_CONFIRMED"

    if pl and lows[-1] < pl[-1][1] and last_close > pl[-1][1]:
        sweep = "LOW_SWEEP"
    elif ph and highs[-1] > ph[-1][1] and last_close < ph[-1][1]:
        sweep = "HIGH_SWEEP"

    baseline = sum(volumes[-21:-1]) / 20
    rvol = volumes[-1] / baseline if baseline > 0 else None

    return {"hl": hl, "lh": lh, "bos": bos,
            "choch": choch, "sweep": sweep, "rvol": rvol}

def load_exchanges():
    try:
        import ccxt
    except ImportError:
        raise RuntimeError(
            "CCXT ontbreekt. Installeer met: "
            ".venv/bin/python -m pip install ccxt"
        )

    loaded = {}
    errors = {}

    for venue in VENUES:
        try:
            cls = getattr(ccxt, venue)

            ex = cls({
                "enableRateLimit": True,
                "timeout": 12000,
            })

            ex.load_markets()
            loaded[venue] = ex

            print(
                f"{venue.upper():<8} "
                f"{len(ex.markets):>5} marktvermeldingen"
            )

        except Exception as exc:
            errors[venue] = str(exc)
            print(
                f"{venue.upper():<8} UNKNOWN "
                f"{str(exc)[:85]}"
            )

    return loaded, errors



def live_market_stats(ex, market):
    """Public ticker for the exact analyzed CCXT market."""
    try:
        ticker = ex.fetch_ticker(market["symbol"])
    except Exception:
        return {
            "vol24": None,
            "spread_pct": None,
            "volume_quote": market.get("quote"),
            "ticker_status": "UNAVAILABLE"
        }

    def safe(value):
        try:
            value = float(value)
            return value if math.isfinite(value) else None
        except (ValueError, TypeError):
            return None

    bid = safe(ticker.get("bid"))
    ask = safe(ticker.get("ask"))
    last = safe(ticker.get("last"))
    quote_volume = safe(ticker.get("quoteVolume"))
    base_volume = safe(ticker.get("baseVolume"))

    spread = None

    if bid is not None and ask is not None:
        if bid > 0 and ask >= bid:
            midpoint = (ask + bid) / 2
            spread = 100 * (ask - bid) / midpoint

    # baseVolume * last is alleen veilig voor gewone spotparen.
    # Voor derivaten kan de contractgrootte verschillen.
    if (
        quote_volume is None
        and market.get("spot")
        and base_volume is not None
        and last is not None
    ):
        quote_volume = base_volume * last

    if quote_volume is not None and quote_volume <= 0:
        quote_volume = None

    return {
        "vol24": quote_volume,
        "spread_pct": spread,
        "volume_quote": market.get("quote"),
        "ticker_status": (
            "OK" if quote_volume is not None
            else "VOLUME_UNAVAILABLE"
        )
    }


def matching_market(ex, coin, kind):
    matches = []

    for m in ex.markets.values():
        if str(m.get("base") or "").upper() != coin:
            continue

        if str(m.get("quote") or "").upper() not in (
            "USDT", "USDC", "USD"
        ):
            continue

        if m.get("active") is False:
            continue

        if kind == "SPOT":
            if not m.get("spot"):
                continue
        else:
            if not m.get("swap") or not m.get("linear"):
                continue

        matches.append(m)

    matches.sort(
        key=lambda m: (
            str(m.get("quote")).upper() != "USDT",
            str(m.get("quote")).upper() != "USDC",
        )
    )

    return matches[0] if matches else None


def fmt(value, digits=2):
    return (
        f"{value:.{digits}f}"
        if value is not None
        else "n/b"
    )


def evaluate(kind, daily, fourh, fifteen):
    # Deze status is onderzoeksinformatie.
    # Geen CHoCH/BOS of concrete entry zonder bewijs.
    bullish_context = (
        daily["trend"] == "UP"
        and fourh["trend"] == "UP"
    )

    bearish_context = (
        daily["trend"] == "DOWN"
        and fourh["trend"] == "DOWN"
    )

    discount = (
        daily["location"] is not None
        and fourh["location"] is not None
        and daily["location"] <= 0.5
        and fourh["location"] <= 0.5
    )

    premium = (
        daily["location"] is not None
        and fourh["location"] is not None
        and daily["location"] >= 0.5
        and fourh["location"] >= 0.5
    )

    rv = fifteen["rvol"]
    active = rv is not None and rv >= 1.5

    if kind == "SPOT":
        if discount and fourh["rsi"] <= 45 and active:
            return "BULLISH_REVERSAL_WATCH", "UP_WATCH"

        if bullish_context and active:
            return "BULLISH_TREND_WATCH", "UP_WATCH"

        return "NO_CONFIRMED_SPOT_SETUP", "NEUTRAL"

    if discount and active:
        return "LONG_LOCATION_WATCH", "LONG_WATCH"

    if premium and active:
        return "SHORT_LOCATION_WATCH", "SHORT_WATCH"

    return "NO_CONFIRMED_FUTURES_SETUP", "NEUTRAL"


def main():
    print("\nINVESTINED — LIVE GLOBAL SIGNAL RESEARCH")
    print("=" * 76)

    selected = {}

    for kind, filename in INPUTS.items():
        selected[kind] = select_candidates(
            read(filename), kind
        )

    print(
        "Onderzoek:",
        len(selected["SPOT"]), "spot +",
        len(selected["FUTURES"]), "futures"
    )

    exchanges, exchange_errors = load_exchanges()

    results = []

    for kind in ("SPOT", "FUTURES"):
        print("\n" + kind)
        print("-" * 76)

        for row in selected[kind]:
            coin = str(row.get("coin") or "").upper()

            availability = {}
            possibilities = []

            for venue in VENUES:
                ex = exchanges.get(venue)

                if ex is None:
                    availability[venue] = "UNKNOWN"
                    continue

                market = matching_market(ex, coin, kind)

                availability[venue] = (
                    "SYMBOL_MATCH" if market
                    else "NOT_LISTED"
                )

                if market:
                    possibilities.append((venue, ex, market))

            result = {
                "strategy": kind,
                "coin": coin,
                "identity_status": row.get("identity_status"),
                "source_exchange": row.get("exchange"),
                "mexc": availability.get("mexc"),
                "bitget": availability.get("bitget"),
                "bybit": availability.get("bybit"),
                "blofin": availability.get("blofin"),
                "analysis_exchange": "",
                "symbol": "",
                "vol24_live": "",
                "spread_live": "",
                "volume_quote_live": "",
                "ticker_status": "UNASSESSED",
                "signal": "UNASSESSED",
                "direction": "UNKNOWN",
                "daily_location": "",
                "fourh_location": "",
                "fourh_rsi": "",
                "rvol15": "",
                "atr4h_pct": "",
                "range_low_4h": "",
                "range_high_4h": "",
                "status": "NO_MARKET_DATA"
            }

            for venue, ex, market in possibilities:
                symbol = market["symbol"]

                try:
                    frames = {}

                    for tf in TIMEFRAMES:
                        candles = ex.fetch_ohlcv(
                            symbol,
                            timeframe=tf,
                            limit=90
                        )

                        if tf == "4h":
                            candles_4h = candles

                        frames[tf] = analyze(candles, tf)

                        if frames[tf] is None:
                            raise ValueError(
                                f"Insufficient closed {tf} candles"
                            )

                    daily = frames["1d"]
                    fourh = frames["4h"]
                    fifteen = frames["15m"]


                    structure = confirmed_structure(
                        candles_4h, "4h"
                    )
                    signal, direction = evaluate(
                        kind, daily, fourh, fifteen
                    )

                    ticker_stats = live_market_stats(ex, market)

                    result.update({
                        "vol24_live": (
                            ticker_stats["vol24"]
                            if ticker_stats["vol24"] is not None else ""
                        ),
                        "spread_live": (
                            ticker_stats["spread_pct"]
                            if ticker_stats["spread_pct"] is not None else ""
                        ),
                        "volume_quote_live": (
                            ticker_stats["volume_quote"] or ""
                        ),
                        "ticker_status": ticker_stats["ticker_status"],
                        "hl": structure["hl"],
                        "lh": structure["lh"],
                        "bos": structure["bos"],
                        "choch": structure["choch"],
                        "sweep": structure["sweep"],
                        "rvol4h": fmt(structure["rvol"]),
                        "analysis_exchange": venue,
                        "symbol": symbol,
                        "signal": signal,
                        "direction": direction,
                        "daily_location": fmt(
                            daily["location"], 3
                        ),
                        "fourh_location": fmt(
                            fourh["location"], 3
                        ),
                        "fourh_rsi": fmt(fourh["rsi"]),
                        "rvol15": fmt(fifteen["rvol"]),
                        "atr4h_pct": fmt(fourh["atr_pct"]),
                        "range_low_4h": fourh["range_low"],
                        "range_high_4h": fourh["range_high"],
                        "status": "TECHNICAL_RESEARCH_READY"
                    })

                    break

                except Exception as exc:
                    result["status"] = (
                        "CANDLE_FETCH_FAILED: "
                        + str(exc)[:90]
                    )

            results.append(result)

            print(
                f"{coin:<13} "
                f"{result['direction']:<13} "
                f"RVOL {str(result['rvol15']):<7} "
                f"{result['signal']}"
            )

    output = ROOT / "investined_live_signals.csv"

    with output.open("w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=list(results[0])
        )
        writer.writeheader()
        writer.writerows(results)


    # Historie met uitbreidbaar CSV-schema.
    # Nieuwe indicatorvelden mogen oude scans niet blokkeren.
    import os
    import tempfile
    import shutil

    history_path = ROOT / "investined_scan_history.csv"
    scan_time = datetime.now(timezone.utc).isoformat()

    old_rows = []
    old_fields = []

    if history_path.exists():
        with history_path.open(newline="") as hf:
            reader = csv.DictReader(hf)
            old_fields = list(reader.fieldnames or [])
            old_rows = list(reader)

    if results:
        new_rows = [
            {"scan_time": scan_time, **row}
            for row in results
        ]

        fields = list(dict.fromkeys(
            ["scan_time"] + old_fields + list(new_rows[0])
        ))

        all_rows = old_rows + new_rows

        fd, temp_path = tempfile.mkstemp(
            prefix=".history_",
            suffix=".csv",
            dir=ROOT
        )

        try:
            with os.fdopen(fd, "w", newline="") as hf:
                writer = csv.DictWriter(
                    hf,
                    fieldnames=fields,
                    extrasaction="ignore"
                )
                writer.writeheader()
                writer.writerows(all_rows)

            os.replace(temp_path, history_path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

        print("Scanhistorie:", history_path)

    report = {
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "research_count": len(results),
        "technically_ready": sum(
            r["status"] == "TECHNICAL_RESEARCH_READY"
            for r in results
        ),
        "signals_to_watch": sum(
            r["direction"] != "NEUTRAL"
            and r["direction"] != "UNKNOWN"
            for r in results
        ),
        "exchange_errors": exchange_errors,
        "notes": [
            "Symbol matches do not prove token identity.",
            "Watch signals are not confirmed entries.",
            "Exchange listing does not prove account access.",
            "Ranges are historical, not forecasts.",
            "4h/1d location uses a rolling 40-candle range.",
            "15m RVOL uses prior 20 closed candles.",
        ]
    }

    (ROOT / "investined_live_signals_report.json").write_text(
        json.dumps(report, indent=2)
    )

    print("\n" + "=" * 76)
    print("KLAAR")
    print("Onderzocht:", report["research_count"])
    print("Technisch gereed:", report["technically_ready"])
    print("Signalen ter observatie:", report["signals_to_watch"])
    print("Resultaten:", output)
    print("Rapport: runtime/investined_live_signals_report.json")
    print("\nGeen orders geplaatst.")
    print("Geen wijzigingen aan LOCATION of NEAR ENTRY.")


if __name__ == "__main__":
    main()

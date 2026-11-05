import csv
import json
import math
import time
from pathlib import Path
from collections import defaultdict

import ccxt

ROOT = Path("runtime")
CACHE = ROOT / "global_futures_cache"
CACHE.mkdir(parents=True, exist_ok=True)

EXCHANGES = ['bitget', 'bybit', 'blofin', 'mexc', 'binanceusdm', 'okx', 'gate', 'bingx']
TIMEFRAMES = ["1d", "4h", "1h", "15m", "5m"]

# Maximum aantal unieke futurescontracten voor diepgaande analyse.
SCAN_LIMIT = 30

# Verlopen candlecache, in seconden.
TTL = {
    "1d": 3600,
    "4h": 1200,
    "1h": 600,
    "15m": 180,
    "5m": 60,
}

NON_CRYPTO = {
    "KORU", "SPY", "QQQ", "NVDA", "TSLA",
    "AAPL", "XAU", "XAG", "CL",
}

STABLE = {"USDT", "USDC", "DAI", "FDUSD", "USDE"}

def num(x, default=None):
    try:
        x = float(x)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default

def ema(values, period):
    if not values:
        return 0
    a = 2 / (period + 1)
    result = values[0]
    for x in values[1:]:
        result = x * a + result * (1 - a)
    return result

def rsi(values, period=14):
    if len(values) < period + 2:
        return None

    changes = [
        values[i] - values[i-1]
        for i in range(1, len(values))
    ]

    gains = [max(x, 0) for x in changes]
    losses = [max(-x, 0) for x in changes]

    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period

    for i in range(period, len(changes)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period

    if avg_l == 0:
        return 100 if avg_g else 50

    return 100 - 100 / (1 + avg_g / avg_l)

def analyze(candles):
    if len(candles) < 65:
        return None

    o = [float(x[1]) for x in candles]
    h = [float(x[2]) for x in candles]
    l = [float(x[3]) for x in candles]
    c = [float(x[4]) for x in candles]
    v = [float(x[5]) for x in candles]

    if any(x <= 0 for x in c):
        return None

    tr = [
        max(
            h[i] - l[i],
            abs(h[i] - c[i-1]),
            abs(l[i] - c[i-1])
        )
        for i in range(1, len(c))
    ]

    atr = sum(tr[-14:]) / 14
    base_vol = sum(v[-21:-1]) / 20
    rv = v[-1] / base_vol if base_vol > 0 else None

    high40 = max(h[-40:])
    low40 = min(l[-40:])
    loc = (
        (c[-1] - low40) / (high40 - low40)
        if high40 > low40 else .5
    )

    ph, pl = [], []

    # Pivot is pas bekend wanneer twee latere candles gesloten zijn.
    for i in range(2, len(c)-2):
        if h[i] > max(h[i-2:i]) and h[i] > max(h[i+1:i+3]):
            ph.append((i, h[i]))

        if l[i] < min(l[i-2:i]) and l[i] < min(l[i+1:i+3]):
            pl.append((i, l[i]))

    hl = (
        pl[-1][1] > pl[-2][1]
        if len(pl) >= 2 else None
    )
    lh = (
        ph[-1][1] < ph[-2][1]
        if len(ph) >= 2 else None
    )

    hh = ph[-1][1] > ph[-2][1] if len(ph) >= 2 else None
    ll = pl[-1][1] < pl[-2][1] if len(pl) >= 2 else None
    prior_up = hh is True and hl is True
    prior_down = lh is True and ll is True

    # Breaks zijn candle-close-gebaseerd.
    bos_up = bool(ph and c[-2] <= ph[-1][1] < c[-1])
    bos_dn = bool(pl and c[-2] >= pl[-1][1] > c[-1])

    choch = (
        "BEAR" if prior_up and bos_dn
        else "BULL" if prior_down and bos_up
        else "-"
    )

    structure = (
        "UP" if prior_up
        else "DOWN" if prior_down
        else "MIX"
    )

    sweep_low = (
        l[-1] < min(l[-21:-1])
        and c[-1] > min(l[-21:-1])
    )
    sweep_high = (
        h[-1] > max(h[-21:-1])
        and c[-1] < max(h[-21:-1])
    )

    return {
        "o": o, "h": h, "l": l, "c": c, "v": v,
        "atr": atr,
        "atr_pct": atr / c[-1] * 100,
        "rvol": rv,
        "rsi": rsi(c),
        "ema20": ema(c[-60:], 20),
        "ema50": ema(c[-90:], 50),
        "loc": loc,
        "hh": hh,
        "hl": hl,
        "lh": lh,
        "ll": ll,
        "choch": choch,
        "structure": structure,
        "bos_up": bos_up,
        "bos_dn": bos_dn,
        "sweep_low": sweep_low,
        "sweep_high": sweep_high,
        "ph": ph,
        "pl": pl,
    }

def candles_closed(ex, symbol, tf):
    safe = (
        ex.id + "_" +
        symbol.replace("/", "_").replace(":", "_") +
        "_" + tf
    )
    path = CACHE / (safe + ".json")
    now = time.time()

    if path.exists() and now - path.stat().st_mtime < TTL[tf]:
        try:
            rows = json.loads(path.read_text())
            if len(rows) >= 65:
                return rows
        except Exception:
            pass

    rows = ex.fetch_ohlcv(symbol, tf, limit=110)

    duration_ms = ex.parse_timeframe(tf) * 1000
    current_ms = ex.milliseconds()

    rows = [
        x for x in rows
        if len(x) >= 6
        and x[0] + duration_ms <= current_ms
    ]

    # Cache alleen een bruikbare, succesvolle response.
    if len(rows) >= 65:
        path.write_text(json.dumps(rows))

    return rows

def patterns(d1, h4, h1, m15, m5):
    """Returns research patterns, not trading instructions."""
    out = []

    dloc = d1["loc"]
    hloc = h4["loc"]
    rv15 = m15["rvol"] or 0
    rv4 = h4["rvol"] or 0

    c = m15["c"]
    h = m15["h"]
    l = m15["l"]

    price = c[-1]
    atr = m15["atr"]

    bullish = h1["ema20"] > h1["ema50"]
    bearish = h1["ema20"] < h1["ema50"]

    discount = dloc < .45 and hloc < .45
    premium = dloc > .55 and hloc > .55

    def add(name, side, phase, bonus):
        out.append((name, side, phase, bonus))

    # 1. Explosive breakout
    high20 = max(h[-21:-1])
    low20 = min(l[-21:-1])

    if rv15 >= 1.8 and price > high20:
        add("EXPLOSIVE BREAKOUT", "LONG", "DEVELOPING", 24)

    if rv15 >= 1.8 and price < low20:
        add("EXPLOSIVE BREAKDOWN", "SHORT", "DEVELOPING", 24)

    # 2. Bullish/bearish reversal
    if discount and h4["hl"] and h1["bos_up"]:
        add("BULLISH REVERSAL", "LONG", "DEVELOPING", 28)

    if premium and h4["lh"] and h1["bos_dn"]:
        add("BEARISH REVERSAL", "SHORT", "DEVELOPING", 28)

    # 3. Liquidity sweep
    if m15["sweep_low"] and discount:
        add("LIQUIDITY SWEEP", "LONG", "DEVELOPING", 22)

    if m15["sweep_high"] and premium:
        add("LIQUIDITY SWEEP", "SHORT", "DEVELOPING", 22)

    # 4. Bull/bear flag: impulsive 1H direction,
    # short counter-trend 15m pullback and resumption.
    recent_move = h1["c"][-6] - h1["c"][-16]
    pullback = c[-2] - c[-6]

    if (
        recent_move > 2 * h1["atr"]
        and pullback < 0
        and c[-1] > max(h[-5:-1])
        and bullish
    ):
        add("BULL FLAG", "LONG", "DEVELOPING", 20)

    if (
        recent_move < -2 * h1["atr"]
        and pullback > 0
        and c[-1] < min(l[-5:-1])
        and bearish
    ):
        add("BEAR FLAG", "SHORT", "DEVELOPING", 20)

    # 5. Double bottom/top with neckline confirmation.
    piv_l = [
        x for x in m15["pl"]
        if x[0] >= len(c) - 35
    ]
    piv_h = [
        x for x in m15["ph"]
        if x[0] >= len(c) - 35
    ]

    if len(piv_l) >= 2:
        a, b = piv_l[-2:]
        if (
            abs(a[1]-b[1]) <= 1.2 * atr
            and b[0] - a[0] >= 4
        ):
            neckline = max(h[a[0]:b[0]+1])
            if price > neckline:
                add("DOUBLE BOTTOM", "LONG", "DEVELOPING", 25)

    if len(piv_h) >= 2:
        a, b = piv_h[-2:]
        if (
            abs(a[1]-b[1]) <= 1.2 * atr
            and b[0] - a[0] >= 4
        ):
            neckline = min(l[a[0]:b[0]+1])
            if price < neckline:
                add("DOUBLE TOP", "SHORT", "DEVELOPING", 25)

    # 6. Range edge, without falsely calling it a confirmed entry.
    range_high = max(h[-40:])
    range_low = min(l[-40:])
    span = range_high - range_low

    if span > 0:
        position = (price - range_low) / span

        if position < .15 and m15["hl"]:
            add("RANGE REVERSAL", "LONG", "DEVELOPING", 15)

        if position > .85 and m15["lh"]:
            add("RANGE REVERSAL", "SHORT", "DEVELOPING", 15)

    # 7. Volatility squeeze developing
    recent_range = max(h[-10:]) - min(l[-10:])
    older_range = max(h[-30:-10]) - min(l[-30:-10])

    if older_range > 0 and recent_range < older_range * .45:
        if rv15 >= 1.4 and bullish:
            add("SQUEEZE", "LONG", "DEVELOPING", 19)
        elif rv15 >= 1.4 and bearish:
            add("SQUEEZE", "SHORT", "DEVELOPING", 19)

    # 8. Momentum continuation
    if bullish and rv15 >= 1.5 and m15["bos_up"]:
        add("MOMENTUM", "LONG", "DEVELOPING", 18)

    if bearish and rv15 >= 1.5 and m15["bos_dn"]:
        add("MOMENTUM", "SHORT", "DEVELOPING", 18)

    # 9. Pullback toward EMA20
    if bullish and abs(price - m15["ema20"]) < atr * .5:
        if m15["hl"]:
            add("PULLBACK / RETEST", "LONG", "DEVELOPING", 16)

    if bearish and abs(price - m15["ema20"]) < atr * .5:
        if m15["lh"]:
            add("PULLBACK / RETEST", "SHORT", "DEVELOPING", 16)

    # 10. Structural breakout on higher timeframe
    if h1["bos_up"] and rv15 >= 1.2:
        add("1H STRUCTURE BREAK", "LONG", "DEVELOPING", 21)

    if h1["bos_dn"] and rv15 >= 1.2:
        add("1H STRUCTURE BREAK", "SHORT", "DEVELOPING", 21)

    return out

def choose_markets():
    path = ROOT / "discovery_futures_all.csv"

    if not path.exists():
        raise SystemExit(
            "Ontbreekt: runtime/discovery_futures_all.csv"
        )

    with path.open(newline="") as f:
        source = list(csv.DictReader(f))

    # Discoverydata bepaalt de prioriteit, niet de uiteindelijke setup.
    by_coin = {}

    for row in source:
        coin = str(row.get("coin") or "").upper().strip()
        if not coin or coin in NON_CRYPTO | STABLE:
            continue

        if coin.endswith(("3L", "3S", "5L", "5S")):
            continue

        vol = num(row.get("volume_24h"), 0)
        spread = num(row.get("spread_pct"))

        if vol < 100000:
            continue

        if spread is not None and spread > .5:
            continue

        if coin not in by_coin or vol > by_coin[coin][0]:
            by_coin[coin] = (vol, row)

    selected = sorted(
        by_coin.items(),
        key=lambda item: item[1][0],
        reverse=True
    )

    # Spreid discovery over volumeklassen.
    bands = [[], [], []]

    for coin, (vol, row) in selected:
        if vol < 1_000_000:
            bands[0].append(coin)
        elif vol < 20_000_000:
            bands[1].append(coin)
        else:
            bands[2].append(coin)

    result = []
    seen = set()

    # Om-en-om uit alle klassen; geen louter large-cap ranking.
    while len(result) < SCAN_LIMIT and any(bands):
        for band in bands:
            if band:
                coin = band.pop(0)
                if coin not in seen:
                    result.append(coin)
                    seen.add(coin)

                if len(result) == SCAN_LIMIT:
                    break

    return result

def resolve_markets(exchange, coins):
    found = {}

    markets = exchange.load_markets()

    for market in markets.values():
        base = str(market.get("base") or "").upper()

        if base not in coins:
            continue

        if market.get("active") is False:
            continue

        if not market.get("swap"):
            continue

        if not market.get("linear"):
            continue

        if str(market.get("quote") or "").upper() != "USDT":
            continue

        # Vermijd contractsuffixen en derivaten die niet overeenkomen
        # met een gewone USDT perpetual.
        if market.get("settle") != "USDT":
            continue

        found.setdefault(base, []).append(market)

    return found

def fmt(value, digits=2):
    if value is None:
        return "-"
    return f"{value:.{digits}f}"

def main():
    candidates = choose_markets()

    print("=" * 116)
    print("INVESTINED — GLOBAL FUTURES OPPORTUNITY RADAR")
    print("=" * 116)
    print("Discovery kandidaten:", len(candidates))
    print("Exchanges:", ", ".join(EXCHANGES))
    print("Strategieën: breakout / reversal / sweep / flag / double / range / squeeze / momentum / retest")
    print()

    exchange_clients = {}
    market_maps = {}

    for name in EXCHANGES:
        try:
            cls = getattr(ccxt, name)
            ex = cls({"enableRateLimit": True, "timeout": 15000})
            market_maps[name] = resolve_markets(ex, candidates)
            exchange_clients[name] = ex
            print(f"{name.upper():<8} markets geladen")
        except Exception as e:
            print(f"{name.upper():<8} niet beschikbaar: {str(e)[:90]}")

    opportunities = []
    failures = 0
    analyzed = 0

    for coin in candidates:
        chosen = None

        for name in EXCHANGES:
            possible = market_maps.get(name, {}).get(coin, [])
            if len(possible) == 1:
                chosen = (name, exchange_clients[name], possible[0])
                break

        if not chosen:
            continue

        name, ex, market = chosen
        symbol = market["symbol"]

        try:
            frames = {}

            for tf in TIMEFRAMES:
                candles = candles_closed(ex, symbol, tf)
                result = analyze(candles)
                if result is None:
                    raise ValueError(f"Onvoldoende candles: {tf}")
                frames[tf] = result

            analyzed += 1

            d1, h4, h1, m15, m5 = [
                frames[tf] for tf in TIMEFRAMES
            ]

            signals = patterns(d1, h4, h1, m15, m5)

            if not signals:
                continue

            for setup, side, phase, bonus in signals:
                rv15 = m15["rvol"] or 0
                rv4 = h4["rvol"] or 0

                # Heuristische onderzoeksscore, geen winstkans.
                score = bonus

                score += min(20, rv15 * 4)
                score += min(12, rv4 * 4)

                if side == "LONG":
                    if h4["hl"]:
                        score += 10
                    if m15["sweep_low"]:
                        score += 5
                else:
                    if h4["lh"]:
                        score += 10
                    if m15["sweep_high"]:
                        score += 5

                # HTF-location bonus uitsluitend voor
                # reversal/location-achtige strategieën.
                location_setup = setup in {
                    "BULLISH REVERSAL",
                    "BEARISH REVERSAL",
                    "LIQUIDITY SWEEP",
                    "RANGE REVERSAL",
                }

                if location_setup:
                    if side == "LONG" and d1["loc"] < .45 and h4["loc"] < .45:
                        score += 15

                    if side == "SHORT" and d1["loc"] > .55 and h4["loc"] > .55:
                        score += 15

                opportunities.append({
                    "coin": coin,
                    "exchange": name.upper(),
                    "symbol": symbol,
                    "side": side,
                    "setup": setup,
                    "phase": phase,
                    "score": round(score),
                    "rvol15": rv15,
                    "rvol4h": rv4,
                    "d1loc": d1["loc"],
                    "h4loc": h4["loc"],
                    "rsi4h": h4["rsi"],
                    "atr4h": h4["atr_pct"],
                    "hl4h": h4["hl"],
                    "lh4h": h4["lh"],
                    "bos1h": "UP" if h1["bos_up"] else "DN" if h1["bos_dn"] else "-",
                    "sweep15": "LOW" if m15["sweep_low"] else "HIGH" if m15["sweep_high"] else "-",
                    "rvol5m": m5["rvol"],
                })

        except Exception:
            failures += 1

    # Beste onderzoekssetup per coin; niet tien keer dezelfde ticker.
    best = {}

    for row in opportunities:
        coin = row["coin"]
        if coin not in best or row["score"] > best[coin]["score"]:
            best[coin] = row

    ranked = sorted(
        best.values(),
        key=lambda x: x["score"],
        reverse=True
    )

    output = ROOT / "global_futures_opportunities.csv"

    fields = [
        "coin", "exchange", "symbol", "side", "setup",
        "phase", "score", "rvol15", "rvol4h",
        "d1loc", "h4loc", "rsi4h", "atr4h",
        "hl4h", "lh4h", "bos1h", "sweep15", "rvol5m",
    ]

    with output.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(ranked)

    width = 116

    print()
    print("=" * width)
    print("GLOBAL FUTURES — BESTE ONDERZOEKSKANDIDATEN")
    print("-" * width)

    print(
        f"{'#':>2} {'COIN':<12} {'EX':<7} {'SIDE':<6} "
        f"{'SETUP':<22} {'RV15':>6} {'RV4H':>6} "
        f"{'1D':>4} {'4H':>4} {'RSI':>5} "
        f"{'HL':>3} {'LH':>3} {'BOS':>4} "
        f"{'SWP':>4} {'SCR':>4}"
    )

    print("-" * width)

    def loc(v):
        if v < .45:
            return "DISC"
        if v > .55:
            return "PREM"
        return "EQ"

    for i, r in enumerate(ranked[:20], 1):
        print(
            f"{i:>2} "
            f"{r['coin']:<12.12} "
            f"{r['exchange']:<7} "
            f"{r['side']:<6} "
            f"{r['setup']:<22.22} "
            f"{fmt(r['rvol15']):>6} "
            f"{fmt(r['rvol4h']):>6} "
            f"{loc(r['d1loc']):>4} "
            f"{loc(r['h4loc']):>4} "
            f"{fmt(r['rsi4h'],1):>5} "
            f"{'Y' if r['hl4h'] else 'N' if r['hl4h'] is False else '-':>3} "
            f"{'Y' if r['lh4h'] else 'N' if r['lh4h'] is False else '-':>3} "
            f"{r['bos1h']:>4} "
            f"{r['sweep15']:>4} "
            f"{r['score']:>4}"
        )

    if not ranked:
        print("Geen patronen gevonden binnen de onderzochte kandidaten.")

    print("-" * width)
    print(
        f"Geanalyseerd: {analyzed}/{len(candidates)} | "
        f"Fouten/onvoldoende data: {failures} | "
        f"Onderzoekskandidaten: {len(ranked)}"
    )
    print("CSV:", output)
    print("SCR = heuristische onderzoeksrangschikking; geen kans op winst.")
    print("Patronen zijn voorlopige detecties, niet onafhankelijk bevestigde setups.")
    print("Geen orders. Bestaande LOCATION en NEAR ENTRY ongewijzigd.")
    print("=" * width)

if __name__ == "__main__":
    main()

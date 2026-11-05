"""Public-data-only pullback selection; discovery never confirms an entry."""
import math
from datetime import datetime, timezone
from equilibrium_target import equilibrium_target

VERSION = 'pullback-v1'
MAX_AGE = 1500


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def source_time(row):
    try:
        stamp = datetime.fromisoformat(str(row['scan_utc']).replace('Z', '+00:00'))
        return stamp.replace(tzinfo=stamp.tzinfo or timezone.utc).timestamp()
    except (KeyError, ValueError, TypeError):
        return None


def contract_valid(row, market):
    from investined_asset_quality import contract_ok
    from investined_live_signals import classify
    coin = str(row.get("coin") or "").upper()
    return (
        classify(coin) == "CRYPTO_CANDIDATE"
        and contract_ok(row, market, "futures")
    )


def evaluate(row, frames, raw, ticker, market, now):
    result = {**row, 'engine': VERSION, 'phase': 'INVALIDATED', 'updated': now,
              'missing': [], 'passed': 0, 'total': 5, 'plan': {},
              'potential_pct': None, 'rr1': None, 'range_pct': None,
              'structure_1h': 'N/B', 'location': 'N/B',
              'pullback_zone': 'N/B', 'distance_pct': None}
    def finish(phase, reason):
        if not result['plan'].get('risk_valid'):
            result['plan'] = {}
            for key in ('potential_pct', 'rr1', 'range_pct'):
                result.pop(key, None)
        result.update(phase=phase, reason=reason, missing=[reason] if phase != 'ENTRY CONFIRMED' else [])
        return result
    try:
        side = row['side']; sign = 1 if side == 'LONG' else -1
        if side not in ('LONG', 'SHORT') or not contract_valid(row, market):
            return finish('INVALIDATED', 'CONTRACTIDENTITEIT ONBEKEND/VERDACHT')
        stamp = source_time(row)
        if stamp is None:
            return finish('INVALIDATED', 'SIGNAALTIJD ONTBREEKT')
        if not 0 <= now - stamp <= MAX_AGE:
            return finish('EXPIRED', 'SIGNAAL OUDER DAN 25 MIN')
        for tf, duration in [('1d',86400),('4h',14400),('1h',3600),('15m',900),('5m',300)]:
            bars = raw[tf]
            if len(bars) < 40:
                return finish('INVALIDATED', 'ONVOLDOENDE ' + tf + ' DATA')
            if any(len(b) < 6 or any(number(v) is None for v in b[:6]) or b[3] <= 0 or b[2] < max(b[1],b[4],b[3]) or b[3] > min(b[1],b[4]) for b in bars):
                return finish('INVALIDATED', 'ONGELDIGE CANDLES')
            if any(bars[i+1][0]-bars[i][0] != duration*1000 for i in range(len(bars)-1)):
                return finish('INVALIDATED', 'CANDLEVOLGORDE')
            age = now - (bars[-1][0]/1000 + duration)
            if not 0 <= age <= (960 if tf == '15m' else 360 if tf == '5m' else duration):
                return finish('EXPIRED', 'VEROUDERDE/ONGESLOTEN ' + tf)
        d,h4,h1,m15,m5 = [frames[t] for t in ('1d','4h','1h','15m','5m')]
        # INVESTINED_INLINE_DISPLAY_V10 - bestaande meetgegevens.
        result['iv_volume24'] = number(ticker.get('quoteVolume'))
        result['iv_rvol4h'] = number(h4.get('rvol'))
        result['iv_rvol15'] = number(m15.get('rvol'))
        result['iv_rvol5'] = result.get('iv_rvol5')
        _bid = number(ticker.get('bid'))
        _ask = number(ticker.get('ask'))
        _ts = number(ticker.get('timestamp'))
        result['iv_spread_pct'] = (
            100 * (_ask-_bid) / ((_bid+_ask)/2)
            if _bid is not None and _ask is not None
            and 0 < _bid <= _ask
            and _ts is not None
            and 0 <= now-_ts/1000 <= 15
            else None
        )
        from investined_display_metrics import location
        result['location'] = location(d.get('loc')) + '/' + location(h4.get('loc'))
        result['structure_1h'] = ('HH+HL' if h1.get('hh') is True and h1.get('hl') is True
                                  else 'LH+LL' if h1.get('lh') is True and h1.get('ll') is True
                                  else 'GEEN TREND')
        if not (0 <= d['loc'] < .45 and 0 <= h4['loc'] < .45 if sign == 1 else .55 < d['loc'] <= 1 and .55 < h4['loc'] <= 1):
            return finish('INVALIDATED', '1D/4H LOCATIE')
        result['passed'] = 1
        if not (h1.get('hh') is True and h1.get('hl') is True if sign == 1 else h1.get('lh') is True and h1.get('ll') is True):
            return finish('INVALIDATED', '1H SWINGSTRUCTUUR')
        result['passed'] = 2

        # INVESTINED_ONE_TERMINAL_20261104
        _bid = number(ticker.get('bid'))
        _ask = number(ticker.get('ask'))
        _vol = number(ticker.get('quoteVolume'))
        _ts = number(ticker.get('timestamp'))

        if _ts is None or not 0 <= now - _ts / 1000 <= 15:
            return finish('EXPIRED', 'KOERSDATA VERLOPEN')

        if _bid is None or _ask is None or not 0 < _bid <= _ask:
            return finish('INVALIDATED', 'BID/ASK ONGELDIG')

        _spread = 200 * (_ask - _bid) / (_ask + _bid)

        if _vol is None or _vol < 1000000:
            return finish('INVALIDATED', 'VOL24 ONDER 1M USD')

        if _spread > 0.12 + 1e-9:
            return finish('INVALIDATED', 'SPREAD > 0.12%')

        result['volume24'] = _vol
        result['spread_pct'] = _spread

        result['trend_4h'] = (
            'HH+HL'
            if h4.get('hh') is True and h4.get('hl') is True
            else 'LH+LL'
            if h4.get('lh') is True and h4.get('ll') is True
            else 'ONBEKEND'
        )

        if (
            side == 'LONG' and result['trend_4h'] == 'LH+LL'
        ) or (
            side == 'SHORT' and result['trend_4h'] == 'HH+HL'
        ):
            return finish('INVALIDATED', '4H TRENDCONFLICT')

        _candles5 = raw['5m'][-21:]

        if len(_candles5) != 21:
            return finish('INVALIDATED', '5M HISTORIE ONTBREEKT')

        _volumes = [number(c[5]) for c in _candles5]

        if any(v is None or v < 0 for v in _volumes):
            return finish('INVALIDATED', '5M VOLUME ONGELDIG')

        _average = sum(_volumes[:-1]) / 20

        result['iv_rvol5'] = (
            _volumes[-1] / _average if _average > 0 else None
        )
        result['quality_gate'] = True
        # Replay EMA at each bar: never use a later EMA to manufacture a retest.
        bars = raw['15m']; ema = bars[0][4]; pullback = None
        for i, bar in enumerate(bars):
            previous_ema = ema
            ema += (bar[4]-ema)*2/21
            if i < 20: continue
            prev = bars[i-1]
            # Prior price on trend side, then actual countertrend movement touching EMA.
            touch = (prev[4] > previous_ema and bar[3] <= ema <= bar[2] and bar[3] < prev[3] and bar[4] < prev[4]) if sign == 1 else (prev[4] < previous_ema and bar[3] <= ema <= bar[2] and bar[2] > prev[2] and bar[4] > prev[4])
            if touch: pullback = bar
        result['pullback_zone'] = '15m EMA20 retest'
        live = number(ticker.get('ask' if sign == 1 else 'bid'))
        result['distance_pct'] = abs(live-ema)/ema*100 if live and ema > 0 else None
        # INVESTINED_APPROACHING_WATCH_V1
        def approaching(reason='WACHT NIEUWE 15M EMA20 RETEST'):
            bid = number(ticker.get('bid'))
            ask = number(ticker.get('ask'))
            ts = number(ticker.get('timestamp'))
            vol = number(ticker.get('quoteVolume'))
            if ts is None or not 0 <= now - ts/1000 <= 15:
                return finish('EXPIRED', 'KOERSDATA NIET VERS')
            if not bid or not ask or not 0 < bid <= ask:
                return finish('INVALIDATED', 'BID/ASK ONTBREEKT')
            if 100*(ask-bid)/((ask+bid)/2) > .12:
                return finish('INVALIDATED', 'SPREAD > 0.12%')
            if vol is None or vol < 1000000:
                return finish('INVALIDATED', 'VOL24 ONBEKEND OF < 1M USD')
            result['early_stage'] = 'APPROACHING'
            return finish('WAIT PULLBACK', reason)

        if pullback is None:
            return approaching()
        result['pullback_zone'] = '15m retest geraakt'
        pb_close = pullback[0]/1000 + 900
        if not 0 <= now-pb_close <= MAX_AGE:
            result['pullback_zone'] = 'wacht nieuwe 15m retest'
            return approaching('OUDE 15M RETEST; WACHT NIEUWE PULLBACK')
        result.update(pullback_timestamp=pullback[0], passed=3)
        after = [b for b in raw['5m'] if b[0]/1000 >= pb_close]
        if any(b[4] < pullback[3] if sign == 1 else b[4] > pullback[2] for b in after):
            return finish('INVALIDATED', 'PULLBACKSTRUCTUUR GEBROKEN')
        prev, last = raw['5m'][-2:]
        trigger = last[4] > last[1] and last[4] > prev[2] if sign == 1 else last[4] < last[1] and last[4] < prev[3]
        if last[0]/1000 < pb_close or not trigger:
            return finish('PULLBACK ACTIVE', 'WACHT LATER GESLOTEN 5M TRIGGER')
        result['passed'] = 4
        if (result.get('iv_rvol5') or 0) < 1.5:
            return finish('PULLBACK ACTIVE', 'WACHT VOLUME >= 1.5')
        result['passed'] = 5
        reference = last[4]; atr = number(m5.get('atr'))
        bid,ask = number(ticker.get('bid')),number(ticker.get('ask'))
        if not atr or atr <= 0 or not bid or not ask or not 0 < bid <= ask:
            return finish('INVALIDATED', 'ATR/BID/ASK ONTBREEKT')
        quote_ts = number(ticker.get('timestamp'))
        if quote_ts is None or not 0 <= now-quote_ts/1000 <= 15:
            return finish('EXPIRED', 'KOERSDATA NIET VERS')
        spread = 100*(ask-bid)/((ask+bid)/2)
        if spread > .12: return finish('INVALIDATED', 'SPREAD > 0.12%')
        entry = ask if sign == 1 else bid
        if abs(entry-reference) > min(reference*.015, atr):
            return finish('INVALIDATED', 'ENTRYAFSTAND > 1.50% OF 1 ATR')
        holds_confirmation = (entry > prev[2] and bid > pullback[3]) if sign == 1 else (entry < prev[3] and ask < pullback[2])
        if not holds_confirmation:
            return finish('INVALIDATED', 'LIVE KOERS HOUDT BEVESTIGING NIET VAST')
        stop = pullback[3]-.25*atr if sign == 1 else pullback[2]+.25*atr
        risk = sign*(entry-stop)
        goal = equilibrium_target(raw['4h'], side, entry)
        target = goal.get('target')
        if not goal.get('potential_pct') or not target or stop <= 0 or risk <= 0:
            return finish('INVALIDATED', 'SL/4H EQ DOEL ONTBREEKT OF ONGELDIG')
        rr = sign*(target-entry)/risk
        result['plan'] = dict(entry=entry, stop=stop, target1=target, rr1=rr, potential_pct=goal['potential_pct'], risk_valid=False)
        if not .5 <= risk/atr <= 8 or rr < 1.30:
            return finish('INVALIDATED', 'RISICO ONGELDIG OF RR < 1.30')
        result['plan']['risk_valid'] = True
        result.update(setup='15M PULLBACK + 5M CONFIRMATION', entry_reference=entry, stop=stop,
                      target1=target, target2=None, rr1=rr, rr2=None, potential_pct=goal['potential_pct'],
                      range_pct=goal['potential_pct'], atr5m=atr, candle_timestamp=last[0],
                      spread_pct=spread, rsi4h=h4.get('rsi'), volume24=ticker.get('quoteVolume'),
                      rvol15=m15.get('rvol'), rvol5=result.get('iv_rvol5'),
                      checks=['1D/4H locatie','1H swingstructuur','Gesloten 15m pullback','Latere gesloten 5m trigger','Volume'],
                      detected_utc=datetime.fromtimestamp(now, timezone.utc).isoformat())

        # INVESTINED_ENTRY_FINAL_GUARD_V13
        if result.get('quality_gate') is not True:
            return finish('INVALIDATED', 'KWALITEIT NIET BEVESTIGD')

        v5 = number(result.get('iv_rvol5'))
        vol = number(result.get('volume24'))
        spr = number(result.get('spread_pct'))
        rr = number(result.get('rr1'))

        if v5 is None or v5 < 1.5:
            return finish('PULLBACK ACTIVE', '5M RVOL ONDER 1.5')
        if vol is None or vol < 1000000:
            return finish('INVALIDATED', 'VOL24 ONDER 1M')
        if spr is None or spr > 0.12:
            return finish('INVALIDATED', 'SPREAD BOVEN 0.12%')
        if not result.get('plan', {}).get('risk_valid'):
            return finish('INVALIDATED', 'RISICOPLAN ONTBREEKT')
        if rr is None or rr < 1.30:
            return finish('INVALIDATED', 'RR ONDER 1.30')

        ts = number(result.get('candle_timestamp'))
        if ts is None or not 0 <= now-(ts/1000+300) <= 300:
            return finish('EXPIRED', '5M TRIGGER NIET MEER VERS')
        return finish('ENTRY CONFIRMED', 'GESLOTEN PULLBACK ENTRY BEVESTIGD')
    except (KeyError, IndexError, TypeError, ValueError):
        return finish('INVALIDATED', 'ONTBREKENDE/ONGELDIGE DATA')

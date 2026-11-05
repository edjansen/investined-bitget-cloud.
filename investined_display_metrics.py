"""Read-only dashboard metrics. Thresholds mark anomalies, never gate trading."""
import math
import shutil
from datetime import datetime
from zoneinfo import ZoneInfo

DURATIONS = {'5m': 300000, '15m': 900000, '1h': 3600000, '4h': 14400000}
POT_WARNING = 100.0
RR_WARNING = 20.0


def numeric(value):
    try:
        n = float(str(value).strip().rstrip('%'))
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def rvol(bars, tf, now_ms):
    """Last closed candle / preceding 20; reject gaps, stale and bad volume."""
    duration = DURATIONS[tf]
    try:
        closed = [c for c in bars if len(c) >= 6 and numeric(c[0]) is not None
                  and float(c[0]) + duration <= now_ms][-21:]
        if len(closed) != 21 or not 0 <= now_ms - (float(closed[-1][0]) + duration) < duration:
            return None
        if any(float(b[0])-float(a[0]) != duration for a,b in zip(closed,closed[1:])):
            return None
        volumes = [numeric(c[5]) for c in closed]
        if any(v is None or v < 0 for v in volumes):
            return None
        mean = sum(volumes[:-1])/20
        return volumes[-1]/mean if mean > 0 else None
    except (TypeError, ValueError, IndexError):
        return None


def frame_metrics(raw, now_ms):
    return {key:rvol(raw.get(tf, []),tf,now_ms) for tf,key in
            [('5m','display_rv5'),('15m','display_rv15'),('1h','display_rv1h'),('4h','display_rv4h')]}


def distance_pct(price, entry):
    price,entry = numeric(price),numeric(entry)
    return abs(price-entry)/entry*100 if price and entry and min(price,entry)>0 else None


def clock(stamp):
    try:
        return datetime.fromtimestamp(float(stamp),ZoneInfo('Europe/Amsterdam')).strftime('%H:%M')
    except (ValueError,TypeError,OverflowError,OSError):
        return '-'


def metric(value, kind):
    if value == 'N/B':
        return 'N/B'
    if value is None or str(value).strip() in ('','-','onbepaald','geen EQ-doel'):
        return '-'
    approximate = str(value).strip().startswith("~")
    clean_value = str(value).strip().lstrip("~") if approximate else value
    n = numeric(clean_value)
    if n is None or n < 0 or (kind == 'RR' and n == 0):
        return 'ONGELD'
    extreme = (kind == 'POT%' and n > POT_WARNING) or (kind == 'RR' and n > RR_WARNING)
    if extreme:
        return 'N/B'
    text = f'{n:.1f}' if kind.startswith('RV') or kind == 'RR' else f'{n:.2f}%'
    if approximate:
        text = "~" + text
    if len(text) > 8:
        text = f'{n:.1e}' + ('%' if kind.endswith('%') else '')
    return ('!' if extreme else '') + text


def render(title, headers, rows):
    columns=['COIN','SIDE','ENTRY','CONF','RSI4H','VOL24','RV5','RV15','RV1H','RV4H','POT%','RR','DIST%','LOC','CHECK']
    if title == 'Open Trades': columns.append('PNL$')
    widths=dict(zip(columns,[23,5,12,4,5,8,6,6,6,6,10,9,9,9,5]+([8] if title=='Open Trades' else [])))
    if title == 'Instaplijst': widths['ENTRY'] = 15
    aliases={'CONF':['CONF','BEVEST.'],'POT%':['POT%','POTENTIEEL%','TOT DOEL%','DOEL%'],'RR':['RR','RR EQ']}
    prepared=[]
    for values in rows:
        source=dict(zip((str(h).upper() for h in headers),values))
        row={key:next((source[a] for a in aliases.get(key,[key]) if a in source),'-') for key in columns}
        if title=='Open Trades':row['ENTRY']='OPEN'
        for pair,a,b in [('RV5/15','RV5','RV15'),('RV1H/4H','RV1H','RV4H')]:
            parts=str(source.get(pair,'-/-')).split('/')
            if len(parts)==2:
                for key,v in zip((a,b),parts):
                    if row[key] in (None,'-'):row[key]=v
        for key in ['RV5','RV15','RV1H','RV4H','POT%','RR','DIST%']:
            row[key]=metric(row[key],key)
        prepared.append(row)
    # Preserve every column on small terminals, in aligned panels with COIN repeated.
    limit=max(45,shutil.get_terminal_size((200,24)).columns-1)
    panels=[];panel=['COIN'];used=widths['COIN']
    for key in columns[1:]:
        if used+3+widths[key]>limit:
            panels.append(panel);panel=['COIN'];used=widths['COIN']
        panel.append(key);used+=3+widths[key]
    panels.append(panel)
    def line(row, panel):
        cells=[]
        for key in panel:
            value=str(row.get(key,'-') if row.get(key) is not None else '-').replace('\n',' ')
            size=widths[key]
            if len(value)>size:value=value[:size-1]+'~'
            cells.append(value.ljust(size) if key in ('COIN','SIDE','ENTRY','LOC') else value.rjust(size))
        return ' | '.join(cells)
    print('\n'+title)
    for panel in panels:
        heading=line({c:c for c in columns},panel)
        print(heading);print('-'*len(heading))
        for row in prepared:print(line(row,panel))
        if not prepared:print('Geen posities of kandidaten.')


def location(value):
    value=numeric(value)
    return '-' if value is None else 'DISC' if value<0.45 else 'PREM' if value>0.55 else 'MID'

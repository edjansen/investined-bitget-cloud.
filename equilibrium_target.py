"""One target rule: discount long / premium short to closed-candle 4H equilibrium."""
import math

def positive(value):
    try:
        value=float(value)
        return value if math.isfinite(value) and value>0 else None
    except (ValueError,TypeError):
        return None

def equilibrium_target(closed, side, price, entry=None, position_mode=False):
    result={"target":None,"remaining_pct":None,"potential_pct":None,"status":"TE WEINIG 4H DATA"}
    side=str(side).upper();price=positive(price)
    origin=positive(entry) if entry is not None else price
    if side not in ("LONG","SHORT") or price is None or origin is None:
        result["status"]="PRIJS/RICHTING ONGELDIG";return result
    if len(closed)<30:return result
    try:
        # Same 40 closed candles used by analyze()["loc"] and scanner DISC/PREM.
        window=closed[-40:]
        highs=[positive(bar[2]) for bar in window]
        lows=[positive(bar[3]) for bar in window]
        if any(v is None for v in highs+lows) or any(h<l for h,l in zip(highs,lows)):
            result["status"]="4H DATA ONGELDIG";return result
        high=max(highs);low=min(lows)
        if high<=low:
            result["status"]="4H RANGE ONGELDIG";return result
        eq=(high+low)/2
        result.update(low=low,high=high,target=eq)
        sign=1 if side=="LONG" else -1
        if position_mode:
            # A live position is not a new entry. Its historical fill need not
            # lie inside today's rolling range to show the remaining EQ path.
            if sign*(eq-price)<=0:
                result.update(remaining_pct=0.0,status="EQ LIGT ACHTER KOERS")
            else:
                result.update(remaining_pct=100*sign*(eq-price)/price,status="DOEL: 4H EQ")
            if sign*(eq-origin)>0:
                result["potential_pct"]=100*sign*(eq-origin)/origin
            return result
        if not low<=origin<=high:
            result["status"]="ENTRY BUITEN 4H RANGE";return result
        if sign*(eq-origin)<=0:
            result["status"]="ENTRY NIET IN DISCOUNT" if side=="LONG" else "ENTRY NIET IN PREMIUM"
            return result
        result["potential_pct"]=100*sign*(eq-origin)/origin
        if sign*(eq-price)<=0:
            result.update(remaining_pct=0.0,status="EQ BEREIKT");return result
        if not low<=price<=high:
            result["status"]="KOERS BUITEN 4H RANGE";return result
        result.update(remaining_pct=100*sign*(eq-price)/price,status="DOEL: 4H EQ")
        return result
    except (IndexError,TypeError):
        result["status"]="4H DATA ONGELDIG";return result

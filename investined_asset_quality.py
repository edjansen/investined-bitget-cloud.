
"""Gedeelde contract- en risicocontrole. Geen projectveiligheidsgarantie."""

BAD_TYPES = ("stock", "equity", "commodity", "forex",
             "index", "etf", "preipo", "pre-ipo")
NEGATIVE = {"UNKNOWN", "UNVERIFIED", "AMBIGUOUS",
            "SUSPICIOUS", "MISMATCH", "REJECTED"}
FLAGS = ("suspicious", "is_scam", "blacklisted",
         "is_blacklisted", "fraud_flag")

def risk_reason(row, market):
    info = market.get("info") or {}

    for obj in (row, market, info):
        if any(str(obj.get(k, "")).lower() in
               ("true", "1", "yes") for k in FLAGS):
            return "EXPLICIET RISICOSIGNAAL"

    status = str(row.get("identity_status") or "").strip().upper()
    if status in NEGATIVE:
        return "IDENTITEIT NIET GEVERIFIEERD"
    if status and status != "VERIFIED_MAPPING":
        return "IDENTITEITSSTATUS ONBEKEND"

    tags = " ".join(
        str(info.get(k, market.get(k, ""))).lower()
        for k in ("assetType", "underlyingType",
                  "category", "symbolType")
    )
    if any(t in tags for t in BAD_TYPES):
        return "GEEN GEWONE CRYPTO"

    if str(info.get("isRwa", "")).upper() == "YES":
        return "GETOKENISEERD INSTRUMENT"

    if str(info.get("symbolStatus", "")).lower() in (
        "restrictedapi", "offline", "suspend",
        "suspended", "delisted"
    ):
        return "CONTRACT NIET ACTIEF"

    return None

def contract_ok(row, market, kind):
    if risk_reason(row, market):
        return False

    coin = str(row.get("coin") or market.get("base") or "").upper()
    info = market.get("info") or {}

    if not coin or coin != str(market.get("base") or "").upper():
        return False
    if not market.get("symbol"):
        return False
    if row.get("symbol") and row["symbol"] != market["symbol"]:
        return False
    if market.get("quote") != "USDT":
        return False
    if market.get("active") is not True:
        return False
    if coin.endswith(("3L", "3S", "5L", "5S")):
        return False
    if info.get("baseCoin") and str(info["baseCoin"]).upper() != coin:
        return False
    if info.get("quoteCoin") and info["quoteCoin"] != "USDT":
        return False
    if info.get("symbol") and info["symbol"] != market.get("id"):
        return False

    if kind == "spot":
        return market.get("spot") is True and market.get("swap") is not True

    if kind == "futures":
        return bool(
            market.get("swap") is True
            and market.get("linear") is True
            and market.get("settle") == "USDT"
            and info.get("isRwa") == "NO"
            and info.get("symbolStatus") == "normal"
            and info.get("baseCoin") == coin
            and info.get("quoteCoin") == "USDT"
            and info.get("symbol") == market.get("id")
        )

    raise ValueError("Ongeldig contracttype")

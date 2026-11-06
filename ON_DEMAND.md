# INVESTINED LABS — vaste Bitget on-demand controle

## Doel
De bestaande Investined Labs scanner en Pullback Entry Engine blijven intact. Deze aparte onderzoeksroute haalt uitsluitend publieke Bitget USDT-perpetual marktgegevens op, zonder API-key, posities of orders.

## Start vanuit ChatGPT of terminal
- Geef 1–10 tickers als tekst door of gebruik de tickers die zichtbaar zijn in een screenshot; een screenshot wordt in de chat gelezen, niet door de workflow.
- De gekoppelde GitHub-actie schrijft de tickers naar `analysis_request.json`, telkens met een nieuw `requested_utc`. Een push naar `main` start `.github/workflows/on_demand.yml` automatisch.
- Handmatig kan dezelfde workflow via GitHub Actions > "Investined on-demand Bitget research" > Run workflow, met invoer als `BTC,ETH`, gestart worden.
- De analyse gebruikt `investined_on_demand.py` en reeds aanwezige `investined_entry_alert.analyze` / `pullback_entry.contract_valid`.

## Exacte analyse en outputs
- Exact CCXT Bitget USDT-perpetual contract; ontbreken, meerdere matches of afwijzing worden zichtbaar gerapporteerd.
- Per symbool gesloten 1D/4H/1H/15m/5m OHLCV-candles, plus HH/HL/LH/LL, BOS, CHoCH, 40-candle locatie, RSI, EMA20/50, ATR en RVOL.
- Actuele publieke ticker: bid, ask, bid/ask-spread, 24-uurs quotevolume en tijdstempel.
- Funding en open interest waar API en CCXT ze beschikbaar stellen; ontbrekende informatie blijft `null`, nooit een geschatte waarde.
- Outputs van iedere run: `analysis_report.json` (tijdgestempeld, met alle opgehaalde candles) en `analysis_report.md` (samenvatting), als GitHub Actions artifact met 7 dagen bewaartermijn.
- Geen automatische orders, API-key, accounttoegang, koop/verkoopbesluiten of winstkansclaims.

## Technische zekerheid
De eerste BTC-smoketest op 6 november 2026 is door GitHub Actions voltooid met conclusie `success`: https://github.com/edjansen/investined-bitget-cloud./actions/runs/42183259479.
De log toont BTC/USDT:USDT, 1H-structuur DOWN, 4H-locatie 0,12, 5m-RVOL 3,94 en een geüpload onderzoeksartifact. Dit is bewijs dat de publieke multi-timeframe dataroute werkt; niet dat de bestaande vijfminutenscanner of een volledig tradeplan end-to-end is gevalideerd.

## Grenzen / volgende stap
De GitHub-route is **on-demand**, geen permanente live-socket in ChatGPT. De bestaande vijfminutenscanner staat los van deze workflow.
Rechtstreekse automatische doorvoer vanuit een lokaal draaiende terminal, volledige orderboekslippage, projectonderzoek, nieuwscontrole, en privépositieanalyse zijn hier niet geïntegreerd.
De repository is openbaar: zet geen privéposities, wachtwoorden, API-sleutels of persoonlijke gegevens in `analysis_request.json`.

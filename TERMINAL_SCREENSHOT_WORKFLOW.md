# INVESTINED: screenshots van de terminal zelfstandig analyseren

Deze route is op 6 november 2026 live getest: https://github.com/edjansen/investined-bitget-cloud./actions/runs/42195485195 .

## Vaste werkwijze in ChatGPT

1. Lees **alle zichtbare, unieke tickers** in het screenshot. Houd de oorspronkelijke groepen apart: futures_pullbacks, global_radar en spot_entry_list.
2. Gebruik de gekoppelde GitHub-app om alleen **terminal_review_request.json** bij te werken met de afgelezen tickers en een nieuw requested_utc. Laat .github/workflows/terminal_review.yml automatisch starten. De lokale Mac-processen, bestaande scannerbestanden en crypto-entryvoorwaarden worden niet aangepast.
3. Controleer de GitHub-runstatus. Controleer de log en download het artifact bitget-terminal-review; bekijk terminal_review_report.json, niet alleen de terminalwaarden uit de foto.
4. Per contract geeft terminal_review.py 1D, 4H, 1H, 15m en 5m met gesloten OHLCV-candles, swingstructuur, RSI, EMA, ATR, RVOL, volume en bid-ask spread. Voor **crypto futures** wordt bovendien de bestaande pullback_entry.evaluate in LONG en SHORT uitgevoerd.
5. Spotcoins worden **alleen via echte Bitget-spotparen** gelezen; RWA/aandelenperpetuals zijn alleen technisch onderzoek en worden niet door de crypto-only instapengine goedgekeurd.
6. Maak een expliciete shortlist met 'beste kwaliteit' EN 'dichtst bij bevestigde entry'. Alleen de bestaande engine mag ENTRY CONFIRMED melden. Als er geen bevestigde setups zijn, zeg dat duidelijk. Geen fictieve targets, risk/reward of projectenveiligheid.
7. Wees precies over ontbrekende contracten, niet-verse data en de tijdstempel. Geen automatische orderplaatsing. Geen API-key of privésleutels in GitHub.

## Geldige eerste proef
33 symbolen uit de foto: 7 futures_pullbacks, 14 global_radar, 12 spot_entry_list. Van 33 konden 31 correct als Bitget-futures of spotmarkten worden geanalyseerd; CRWVSTOCK en STXX hadden geen eenduidige contractidentiteit onder de opgegeven naam. Er was geen ENTRY CONFIRMED in de futures-entries. Het outputartifact bevat de ruwe gesloten candles en berekende timeframes.

## Status en grenzen
Dit is een **op aanvraag gestarte GitHub Action**, geen permanente live-verbinding vanuit ChatGPT en geen realtime gestreamde koersfeed. De bestaande vijfminutenscanner staat los hiervan. Een geslaagde GitHub-run bewijst de openbare dataverbinding en rapportage, maar geen levenslange uptime of validiteit van een later instapniveau.

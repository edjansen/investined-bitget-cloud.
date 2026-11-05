# Investined: afzonderlijke cloudscanner

De bestaande Mac-map, processen, Open Trades-monitor, watchlist en accountinstellingen zijn niet aangepast. Start de cloudscanner nooit via het oude start.command of watchdogscript. Dit pakket werkt zelfstandig.

## Wat is behouden en wat verschilt?

De acht bestanden in SOURCE_HASHES.json zijn exact gekopieerd, met SHA-256-controle. De beslislogica in pullback_entry.evaluate en de candle-analyse van investined_entry_alert zijn ongewijzigd. Alleen ENTRY CONFIRMED met vers koersbeeld en gesloten candles kan een melding geven. Geen bijna-kansen of live-reclaimmeldingen. Geen order- of accountaanvragen; geen Bitget-API-key nodig.

De oorspronkelijke keten: start.command start global_radar.py; de Mac-watchdog bewaakt extra discoveryprocessen. investined_bitget.py toont Open Trades en gebruikt EntryMonitor → investined_entry_alert → pullback_entry voor entrycontrole. Die hele Mac-keten blijft bestaan.

Cloud-entrypoint: cloud_scan.py. De cloudvariant vervangt de cross-exchange discovery-aanvoer door openbare Bitget USDT-perpetuals met minimaal 1 miljoen quotevolume, beide richtingen. Alle technische voorwaarden worden vervolgens door dezelfde engine beoordeeld. Dit is dus dezelfde bevestigingslogica, maar niet exact dezelfde kandidatenlijst of rangschikking. Er worden geen oude runtimebestanden gebruikt of als nieuw gedateerd.

Posities zijn in de cloud ONBEKEND. Een signaal kan ook komen voor een contract waarin je al handelt. De bestaande positiecontrole blijft uitsluitend in de Mac-monitor. Je hebt dit verschil geaccepteerd; er gaan geen accountgegevens naar GitHub.

## Vijf minuten en gratis gebruik

De workflow vraagt op minuut 2, 7, 12, enzovoort een run aan. GitHub kan runs vertragen of laten vervallen. In openbare repositories kunnen schedules na 60 dagen zonder activiteit worden uitgeschakeld. Dit is geen gegarandeerde continue bewaking.

Elke run krijgt 150 seconden scanbudget plus de laatste lopende marktcontrole. Alle geschikte contracten worden op volgorde geroteerd. Bij veel markten wordt NIET ieder contract iedere vijf minuten gecontroleerd. De log toont eligible, checked, failed en complete_coverage. Optioneel beperkt repositoryvariabele SCAN_SYMBOLS de marktset, bijvoorbeeld BTC/USDT:USDT,ETH/USDT:USDT. Kies geen kleinere set zonder de veranderde dekking te accepteren.

De engine weigert triggers ouder dan vijf minuten en quotes ouder dan 15 seconden. Vertraagde runs halen oude bevestigingen niet alsnog in. Korte setups kunnen worden gemist. Voor betrouwbare volledige vijfminutendekking is een permanent draaiende host waarschijnlijk geschikter; hier is geen gratis hostcapaciteit of SLA gegarandeerd.

Standaard GitHub-hosted runners voor openbare repositories zijn gratis, onder de gebruiksvoorwaarden. Privérepositories hebben een beperkt maandtegoed; 288 runs/dag is circa 8.640 runs per 30 dagen, nog vóór de scanduur. Controleer het actuele accountbudget, opslag en kostenlimiet. Het pakket gebruikt geen betaalde runner.

## Installeren op GitHub

1. Maak onder jouw GitHub-account een lege openbare repository, bijvoorbeeld investined-bitget-cloud.
2. Upload uitsluitend de inhoud van dit pakket, inclusief .github/workflows/scanner.yml. Upload nooit de oorspronkelijke Mac-map. Bij een ZIP eerst uitpakken; GitHub voert een geüploade ZIP niet uit.
3. Maak via Telegram @BotFather een bot. Open die bot op je iPhone en stuur /start. Zet Telegrammeldingen aan in iOS.
4. Zet de bot-token uitsluitend in Settings → Secrets and variables → Actions → Secrets als TELEGRAM_BOT_TOKEN. Voeg daar ook TELEGRAM_CHAT_ID toe met jouw privéchat-ID. Deel de token niet in chat, broncode of screenshots. Gebruik de officiële getUpdates-methode lokaal om je chat-ID te vinden en controleer dat deze bij jouw chat hoort.
5. Voeg repositoryvariabele SCANNER_ENABLED met waarde true toe. Zonder deze variabele draait geen scan. De workflow moet op de default branch staan.
6. Start Actions → Bitget verified pullbacks → Run workflow. Controleer de log en dat alle marktaanvragen niet falen. Een geslaagde run zonder melding is normaal.
7. Verifieer een echte, verse ENTRY CONFIRMED-melding op de iPhone. Er wordt geen testbericht als entry verstuurd. Tot deze stap is end-to-end pushbezorging niet bewezen.

De gekoppelde GitHub-connector kon in deze sessie geen repository aanmaken of bestanden uploaden. Publicatie en het invoeren van Telegram-secrets zijn daarom nog niet uitgevoerd.

## Deduplicatie en beveiliging

Eén sleutel per contract, richting en 15m-pullback; een nieuwe 5m-trigger op dezelfde pullback geeft niet opnieuw een melding. Reserveringen worden vóór verzending in de Actions-cache opgeslagen en via een exacte cache-restore gecontroleerd. Daarna wordt de setup opnieuw met actuele marktdata gevalideerd. Alleen de verzendstap krijgt Telegram-secrets. De GitHub-token heeft contents: read; er zijn geen code-pushrechten en geen pull-requesttriggers.

De cache bevat alleen gehashte setup-ID's, tijdstippen en een rotatiecursor. In een openbare repository is cache-inhoud geen geheime opslag. Er zitten geen tokens, accountposities of chat-ID's in. runtime en outbox worden niet gecachet of als artifact geüpload.

Ontbreekt de cache, dan worden alleen pullbacks die NA de herstart zijn ontstaan toegelaten. Bestaande setups worden overgeslagen om herhaalpushes te beperken. Corrupte state stopt de run. Cache is geen transactionele database: verlies, herstel van oude cache of gewijzigde workflows beperken de garantie. Telegram biedt hier geen idempotency key. Daarom geen retry bij onzekere verzending; dat kan een melding kosten. Absolute exactly-once-bezorging wordt niet beloofd.

Geen Telegram-token aanwezig in dit pakket. settings.json, .env, runtime, backups, lokale handelsgegevens en virtuele omgevingen zijn niet overgenomen. Een patrooncontrole vond geen tokens of private keys in het pakket; dit is geen formele security-audit. Beperk schrijfrechten tot je repository: wie de workflow kan wijzigen, kan ook de ingestelde secrets misbruiken.

## Verificatie

Live openbare Bitget-proefscan: BTC/USDT:USDT en ETH/USDT:USDT gecontroleerd, 0 API-fouten, 0 gereserveerde meldingen. Geen Telegrambericht verstuurd. Uitvoering op GitHub en iPhonebezorging zijn nog niet getest.

25 lokale tests geslaagd met de bestaande ccxt 4.5.88-omgeving. Ze toetsen onder andere geldige/ongeldige long- en shortsetups, veroudering, echte candle-analyse met gesimuleerde openbare API-responsen, herstartdeduplicatie, cacheverlies, corrupte state en een Telegramfout zonder tokenlek of retry.

De oude testfixture zette 5m-RVOL op 2 in afgeleide velden, terwijl de huidige engine zelf RVOL uit candles berekent. Zes bestaande tests faalden daardoor. Alleen de gekopieerde testfixture kreeg daadwerkelijk dubbel laatste candlevolume; productieregels zijn niet gewijzigd. De desktopweergavetest is niet opgenomen in dit zelfstandige cloudpakket.

Bronnen:
- https://docs.github.com/en/actions/how-tos/troubleshoot-workflows
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
- https://docs.github.com/en/actions/concepts/billing-and-usage
- https://core.telegram.org/bots/api#sendmessage

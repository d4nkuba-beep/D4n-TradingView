# MNQ NY-Open Sweep + ORB – Strategie-Beschreibung (aktueller Stand)

Stand: 29.09.2026 · Script: `strategies/mnq_m5_sweep.pine` (Pine v6) · Branch `claude/trading-strategy-examples-cvuv5h`

Diese Datei beschreibt die **aktuell live eingesetzte Fassung** vollständig, als Grundlage für spätere
Weiterentwicklungen. Die Entstehung (Version 1–3, alle getesteten Varianten) steht in `README.md`.

---

## 1. Überblick

| | |
|---|---|
| Markt | Micro E-mini Nasdaq-100 (`CME_MINI:MNQ1!`), 2 $ pro Punkt, Tick 0,25 |
| Zeitrahmen | 5 Minuten, Handelszeiten **ETH** (Overnight-Kerzen werden für die Levels gebraucht) |
| Zeitzone der Regeln | New York (America/New_York); in MEZ/MESZ jeweils +6 h |
| Handelsfenster | Einstiege 09:30–11:00, alle Positionen flat um 11:30 |
| Setups | **A: Liquidity Sweep** (Umkehr nach Stop-Run) und **B: Opening Range Breakout (ORB5)** |
| Positionen | Immer nur eine offene Position; erstes Signal des Tages gewinnt; max. 2 Trades/Tag, Schluss nach 2 Verlusten |
| Größe | Einstellbar („Contracts per trade“, Standard 2) |
| Absicherung | TP1 bei 0,5R schließt 50 % → Rest-Stop auf Breakeven → TP2 bei 2R |

Idee dahinter (aus den Beispiel-Charts): Zur NY-Eröffnung holt der Markt die Liquidität über/unter
offensichtlichen Hochs und Tiefs ab (Stops, „Spring/Upthrust“ nach Wyckoff) und dreht dann. Gehandelt wird
nur in Richtung des kurzfristigen Trends (EMA-Filter), weil Gegen-Trend-Trades im Test klar verloren haben.

---

## 2. Liquiditäts-Levels

Vor bzw. während der Session werden Levels gesammelt. Jedes Level hat eine Seite (Hoch = mögliches Short-Setup,
Tief = mögliches Long-Setup).

| Level | Quelle | Wird aktiv |
|---|---|---|
| PDH / PDL | Hoch/Tief der Vortags-RTH (09:30–16:00) | 16:00 |
| Asia H / L | 20:00–00:00 | 00:00 |
| London H / L | 02:00–05:00 | 05:00 |
| ON H / L | Overnight 18:00–09:30 | 09:30 |
| Swing H / L | Bestätigtes M5-Swing-Hoch/-Tief ab 08:00, Stärke 2 Kerzen je Seite (links ≥/≤, rechts strikt) | 2 Kerzen nach dem Swing |

- Ein Level ist **verbraucht**, sobald eine Kerze mehr als 1 Tick darüber (Hoch) bzw. darunter (Tief) handelt – egal
  ob innerhalb oder außerhalb des Handelsfensters. Verbrauchte Levels werden nie wieder gehandelt.
- Um 16:00 werden alle Levels des Tages gelöscht (neuer Handelstag).

---

## 3. Setup A – Liquidity Sweep

1. **Sweep** (09:30–11:00, flach, kein Order offen, Tageslimits nicht erreicht): Die Kerze handelt durch ein
   unverbrauchtes Level. Werden mehrere Levels gleichzeitig gesweept, zählt das äußerste. Werden in einer Kerze
   Hoch- und Tief-Levels gesweept, gilt das Long-Setup.
2. **Bestätigung** in der Sweep-Kerze oder einer der 3 folgenden Kerzen: Schlusskurs
   - Short: **unter** dem Level **und** unter dem Tief der Sweep-Kerze
   - Long: **über** dem Level **und** über dem Hoch der Sweep-Kerze
   Während des Wartens wird das Sweep-Extrem (höchstes Hoch / tiefstes Tief) nachgeführt.
3. **Filter** (siehe Abschnitt 5) müssen auf der Bestätigungskerze erfüllt sein; sonst wird weiter gewartet,
   bis die 3 Kerzen abgelaufen sind.
4. **Einstieg**: Market zum Schlusskurs der Bestätigungskerze.
5. **Stop**: 2 Ticks hinter dem Sweep-Extrem. Mindestens 10 Punkte (sonst auf 10 erweitert).
   Ist der Stop größer als **5 × ATR(14)**, wird der Trade ausgelassen.

Optional (standardmäßig aus): FVG in der Bewegung verlangen, Limit-Einstieg im OTE-Retracement (0,5) mit 6 Kerzen
Gültigkeit, Sweep-Kerze muss selbst wieder zurück schließen, Struktur-Lookback statt Sweep-Kerze.

## 4. Setup B – Opening Range Breakout (ORB5)

1. **Range** = Hoch/Tief der ersten 5-Minuten-Kerze (09:30–09:35).
2. Die **erste** Kerze, die außerhalb der Range schließt (bis 11:00), entscheidet den Tag – egal ob daraus ein
   Trade wird. Danach kein weiterer ORB an diesem Tag.
3. Einstieg nur, wenn in dem Moment keine Position/Order offen ist und die Filter (Abschnitt 5) erfüllt sind.
4. **Einstieg**: Market zum Schlusskurs der Ausbruchskerze.
5. **Stop**: 2 Ticks hinter der **Mitte** der Range. Ist der Stop größer als **100 Punkte**, kein Trade.

## 5. Filter (für beide Setups)

| Filter | Standard | Wirkung |
|---|---|---|
| Richtung | Beide | Optional nur Long / nur Short |
| Trend | **EMA 20 > EMA 50 für Long, < für Short** (Chart-Zeitrahmen) | Alternativen: Preis vs. VWAP, Preis vs. H1-EMA50, aus |
| Mindest-ATR | 0 (aus) | Setup nur bei ATR ≥ Wert |
| Efficiency Ratio | 0 (aus), Länge 10 | Setup nur bei ER ≥ Wert (Seitwärts-Filter) |

## 6. Ausstieg & Risikomanagement

- **R** = Abstand Einstieg–Stop in Punkten.
- **TP1** = Einstieg ± 0,5 R → schließt `floor(Kontrakte × 50 %)`, mindestens 1 Kontrakt
  (1 → 1, 2 → 1, 3 → 1, 4 → 2, 5 → 2). Bei 1 Kontrakt ist TP1 der komplette Ausstieg.
- **Breakeven**: Sobald TP1 gefüllt ist, wird der Stop der Rest-Kontrakte auf den Einstiegspreis gesetzt
  (wirksam ab der nächsten Kerze). Erkennung über „neuer geschlossener Trade bei weiterhin offener Position“ –
  funktioniert auch, wenn TP1 schon in der ersten Kerze nach dem Einstieg kommt.
- **TP2** = Einstieg ± 2 R für die Rest-Kontrakte.
- **Zeitausstieg**: Alles wird um 11:30 geschlossen, offene Limit-Orders storniert.
- **Tageslimits**: max. 2 Trades, nach 2 Verlusttrades keine neuen Einstiege.
- Kosten im Backtest: 0,62 $ Kommission pro Kontrakt und Seite, 1 Tick Slippage.
- `margin_long/short = 0`: nötig, weil Pine v6 sonst 100 % Margin verlangt und alle Orders ablehnt.

## 7. Alle Einstellungen (Standardwerte)

| Gruppe | Einstellung | Standard |
|---|---|---|
| Session | First entry / Last entry / Flat at | 0930 / 1100 / 1130 |
| Session | Max trades per day / Stop after N losses | 2 / 2 |
| Liquidity levels | PDH/PDL, Overnight, Asia, London, Intraday swings | alle an |
| Liquidity levels | Swing strength | 2 |
| Setup & entry | Bars to confirm after sweep | 3 |
| Setup & entry | Structure lookback / Close back inside / Require FVG | 0 / aus / aus |
| Setup & entry | Entry / OTE retracement / Limit lifetime | Market / 0,5 / 6 |
| Filters | Direction / Trend / EMA fast / EMA slow | Both / EMA fast/slow / 20 / 50 |
| Filters | ATR length / Min ATR / ER length / Min ER | 14 / 0 / 10 / 0 |
| Opening range breakout | Trade ORB / Range minutes | an / 5 |
| Risk & protection | Contracts per trade | 2 |
| Risk & protection | Min stop / Max stop (ORB) / Sweep max stop in ATR | 10 / 100 / 5 |
| Risk & protection | TP1 R / TP2 R / TP1 size % / Breakeven | 0,5 / 2,0 / 50 / an |
| Display | Trade-Boxen, Levels mit Namen, M15-Zonen (nur Anzeige), Debug-Tabelle | an |

## 8. Anzeige im Chart

- **Trade-Boxen**: rot = Risiko (Einstieg–Stop), grün = Ziel (bis TP2, ohne Runner bis TP1), gestrichelt = TP1,
  Ergebnis in $ am Ausstieg.
- **Levels**: Linie ab der Entstehungskerze; durchgezogenes Ende = gebrochen, gepunktetes Ende = verfallen.
- **M15-Support/Resistance-Zonen** (nur Orientierung, nicht Teil der Regeln): Docht-Bereich eines bestätigten
  M15-Swings (3 Kerzen je Seite), endet bei einem M5-Schluss durch die Zone; max. 30 aktive Zonen.
- EMA-Linien bzw. VWAP je nach Filter, blauer Hintergrund = Einstiegsfenster, Debug-Tabelle oben rechts.
- **Alarme** (`alert()`): bei jedem Sweep und jedem Einstieg mit Stop, TP1 und TP2.

## 9. Ergebnisse

| Test | Zeitraum | Positionen | Trefferquote | PF | Netto (2 MNQ) | Max. DD |
|---|---|---|---|---|---|---|
| **TradingView** (MNQ1! 5m, bestätigt) | 04.08.–25.09.2026 | 28 | 78,6 % | 2,07 | +1.605 $ | 578 $ |
| Python (gleiche Regeln) | 04.08.–25.09.2026 | 27 | 81,5 % | 2,28 | +1.758 $ | 574 $ |
| Python | 17.07.–25.09.2026 | 32 | 81,2 % | 2,23 | +2.174 $ | 574 $ |

- 27 von 27 Python-Positionen stimmen mit TradingView auf < 10 $ überein; TradingView hat zusätzlich einen
  Swing-Long am 07.09. (−124 $).
- Durchschnitt TradingView: Gewinn-Trade +141 $, Verlust-Trade −251 $, größter Verlust −361 $;
  12 von 28 Trades enden nach TP1 mit ±0 auf dem Rest.
- Werte skalieren linear mit den Kontrakten (4 MNQ ≈ doppelter Gewinn und Drawdown).

**Grenzen der Aussagekraft**: nur ~8 Wochen Daten, ~30 Trades, und die Standardwerte wurden aus mehreren hundert
getesteten Varianten ausgewählt (Auswahleffekt). Das ist kein Nachweis einer dauerhaften Profitabilität.

## 10. Was getestet und verworfen wurde (Kurzfassung)

| Idee | Ergebnis |
|---|---|
| Sweep ohne Trendfilter (Version 1) | im Out-of-Sample ±0 |
| Enge „Scalp“-Stops (≤ 100 Punkte beim Sweep) | deutlich negativ; Median-Stop liegt bei ~90 Punkten |
| M15 statt M5 | zu wenige Trades (6 in 48 Tagen) |
| VWAP-Filter, H1-EMA-Filter | kein stabiler Mehrwert |
| EMA 9/21, 50/200, 9/50 | schlechter als 20/50 |
| ORB 15/30 Minuten | kein Vorteil |
| Mindest-ATR, ER-Filter, ATR-Länge | kein Effekt oder schlechter im späten Testteil |
| Max. 1 oder 3 Trades/Tag | 1 schlechter, 3 ohne Effekt |
| Nur Short | stark in diesem Zeitraum, aber nur 16 Trades → Wette auf die Marktphase |
| Späterer Ausstieg (12:30 / 15:45), TP2 3R | schlechter |

## 11. Dateien & Werkzeuge

| Datei | Zweck |
|---|---|
| `strategies/mnq_m5_sweep.pine` | Live-Strategie für TradingView |
| `backtest/sweep_backtest.py` | Setup A in Python (inkl. gemeinsamer Filter `gate()`, Fill-Logik `bar_events()`) |
| `backtest/orb_backtest.py` | Setup B in Python |
| `backtest/combined_backtest.py` | Beide Setups wie im Pine-Script (erstes Signal gewinnt) – Referenz für Vergleiche |
| `backtest/plot_trades.py` → `backtest/charts/` | Chart-Bilder aller Trade-Tage mit Levels, Zonen, Boxen |
| `backtest/data/` | MNQ 5m/15m/1h (Yahoo `MNQ=F`, gegen TradingView geprüft) |

```
python backtest/combined_backtest.py --trades
python backtest/plot_trades.py 2026-09-18
```

Abgleich mit TradingView: im Strategy Tester „Liste der Trades“ als CSV exportieren und Trade für Trade mit
`combined_backtest.py --trades` vergleichen (TradingView-Zeiten in MESZ = New York + 6 h).

## 12. Bekannte Punkte & Ideen für die Weiterentwicklung

**Bekannt**
- Pine: TP1 und Stop in derselben Kerze werden von TradingView nach dessen Kerzen-Pfad gefüllt, Python rechnet
  „Stop zuerst“ (konservativ) – kleine Abweichungen möglich.
- Montags nutzt Python keine Asia-Levels (Wochenend-Lücke), Pine schon – selten relevant.
- Maximal 500 Linien/Labels/Boxen im Chart; ältere Zeichnungen verschwinden bei langer Historie.

**Nächste Schritte (Reihenfolge)**
1. Deep Backtesting über 1–2 Jahre in TradingView; Ziel: 200+ Trades, PF > 1,3, stabil pro Quartal.
2. 4–6 Wochen Paper Trading mit Alarmen; Live-Fills gegen Backtest vergleichen.
3. Erst dann echtes Geld, zunächst mit 1–2 MNQ.

**Ideen (erst nach Schritt 1 testen, sonst Overfitting)**
- News-Filter (CPI, NFP, FOMC-Tage auslassen)
- Risiko-basierte Positionsgröße (fester $-Betrag pro Trade statt fester Kontraktzahl)
- M15-Zonen als Filter oder Ziel (z. B. TP2 an der nächsten gegenüberliegenden Zone)
- Tagesverlust-Limit in $ statt Anzahl Verluste
- Zweites Fenster (z. B. 13:30–15:00) als separat getestetes Setup

---

Keine Anlageberatung, keine Gewinngarantie. Futures-Handel kann zum Totalverlust führen.

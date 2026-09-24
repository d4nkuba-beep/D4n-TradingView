# MNQ NY-Open Sweep + ORB (M5)

Regelbasierte Umsetzung der Chart-Beispiele (NAS100 / MNQ rund um die New-York-Eröffnung)
als TradingView-Strategie plus lokaler Python-Backtest.

| Datei | Inhalt |
|---|---|
| `strategies/mnq_m5_sweep.pine` | Pine v6 `strategy()` für TradingView (MNQ1!, 5 Minuten) |
| `backtest/sweep_backtest.py` | Python-Nachbau der Sweep-Regeln, Bar für Bar, ohne Lookahead |
| `backtest/orb_backtest.py` | Opening-Range-Breakout-Modul |
| `backtest/combined_backtest.py` | Beide Setups zusammen, so wie das Pine-Script handelt |
| `backtest/plot_trades.py`, `backtest/charts/` | Chart-Vorschau aller Trade-Tage mit Levels, Zonen und Trade-Boxen |
| `backtest/data/mnq_{5m,15m,1h}.csv` | MNQ-Kerzen (Yahoo `MNQ=F`, stichprobenartig gegen TradingView `CME_MINI:MNQ1!` geprüft: identisch) |

## Die Regeln

Aus den Bildern abgeleitet: Liquidität über/unter einem Hoch/Tief wird zur NY-Eröffnung abgeholt,
der Preis dreht, Ziel ist die Gegenseite, Stop über/unter dem Docht, danach „BE ziehen“.

1. **Levels** (vor 09:30 New-York-Zeit): Hoch/Tief des Vortags (RTH), Overnight-Hoch/Tief (18:00–09:30),
   Asia (20:00–00:00), London (02:00–05:00). Ab 08:00 kommen bestätigte Swing-Hochs/-Tiefs dazu.
   Ein Level ist verbraucht, sobald der Preis durchläuft.
2. **Sweep**: zwischen 09:30 und 11:00 läuft eine Kerze über/unter ein unberührtes Level.
3. **Bestätigung**: innerhalb von 3 Kerzen schließt eine Kerze wieder hinter dem Level **und**
   hinter dem Tief (Short) bzw. Hoch (Long) der Sweep-Kerze.
4. **Einstieg**: Market zum Schlusskurs der Bestätigungskerze (optional: Limit im OTE-Retracement).
5. **Stop**: 2 Ticks hinter dem Sweep-Docht (min. 10, max. 150 Punkte, sonst kein Trade).
6. **Absicherung**: TP1 bei 1R schließt 50 %, Rest-Stop auf Breakeven; TP2 bei 2R.
   Alles glatt um 11:30. Max. 2 Trades pro Tag, Schluss nach 2 Verlusten.

Kosten im Test: 0,62 $ Kommission pro Kontrakt und Seite plus 1 Tick Slippage. 2 Kontrakte MNQ (2 $/Punkt).

## Version 2: Trendfilter + ORB-Modul

Getestete Ergänzungen (je mit identischen Kosten und Fill-Regeln):

| Filter / Idee | Ergebnis |
|---|---|
| VWAP (mit Trend) | kein Mehrwert im späten Testteil |
| VWAP (Rückkehr zum VWAP) | schlechter |
| EMA50 auf H1 (mit Trend) | leicht besser, späte Hälfte ~0 |
| **EMA20 > EMA50 auf M5 (mit Trend)** | **besser in beiden Hälften, bei beiden Setups** |
| Gegen den EMA-Trend (Kontrollgruppe) | Verlust, bestätigt den Filter |
| Opening Range Breakout 15/30 Min. | kein Vorteil |
| **ORB 5 Min. (erste Kerze), Stop Mitte der Range, EMA-Filter** | **PF 1,85, 3 von 4 Zeitabschnitten positiv** |

Neue Standardregeln (Pine und Python):

7. **Richtungsfilter**: Long nur bei EMA20 > EMA50 (M5), Short nur darunter.
8. **Sweep-Stop-Grenze**: max. 5 × ATR(14) statt fester 150 Punkte.
9. **ORB-Modul**: Range = 09:30–09:35-Kerze. Erste Schlusskerze außerhalb entscheidet den Tag.
   Einstieg nur mit Trendfilter, Stop 2 Ticks hinter der Range-Mitte, gleiche Ausstiege (TP1 1R 50 % + BE, TP2 2R, 11:30 flat).
10. Sweep und ORB zusammen: erstes Signal gewinnt, immer nur eine Position, max. 2 Trades pro Tag.

```
python backtest/combined_backtest.py --trades   # so wie das Pine-Script handelt
python backtest/sweep_backtest.py --tf 5m        # nur Sweep
python backtest/orb_backtest.py [--grid]         # nur ORB
```

**Kombiniert (M5, 2 MNQ, 17.07.–24.09.2026)**

| Satz | Trades | Trefferquote | PF | Ø R | Netto | Max. DD |
|---|---|---|---|---|---|---|
| In-Sample | 20 | 70,0 % | 2,39 | +0,36 | +2.962 $ | 996 $ |
| Out-of-Sample | 15 | 60,0 % | 1,21 | +0,17 | +335 $ | 591 $ |
| Gesamt | 35 | 65,7 % | 1,88 | +0,28 | +3.297 $ | 996 $ |

Netto je Viertel des Zeitraums: +1.260 / +1.482 / −484 / +849 $. Bootstrap P(Ø R > 0) = 0,94.

**Einordnung**

- Besser als Version 1, und der EMA-Filter wirkt plausibel: Gegen-den-Trend-Trades verlieren.
- **Trotzdem kein Beweis**: 35 Trades in 48 Tagen, und die Regeln wurden nach ca. 300 getesteten Varianten
  ausgewählt. Das Ergebnis ist deshalb vermutlich zu optimistisch (Auswahleffekt). Der späte Testteil ist nur leicht positiv.
- Der entscheidende nächste Schritt ist der **TradingView Strategy Tester mit Deep Backtesting über mehrere Jahre**
  (M5-Historie von MNQ1!), danach Demokonto. Erst wenn es dort über 200+ Trades hält, ist es eine Strategie.

## Version 1: Ergebnisse ohne Filter

Version 1 (nur Sweep, ohne Trendfilter, max. 150 Punkte Stop).
Die ersten 60 % der Tage dienten der Entwicklung (In-Sample), die letzten 40 % wurden erst am Ende getestet (Out-of-Sample).

| Satz | Trades | Trefferquote | Profit-Faktor | Ø R | Netto | Max. Drawdown |
|---|---|---|---|---|---|---|
| In-Sample | 13 | 53,8 % | 1,39 | +0,17 | +745 $ | 575 $ |
| Out-of-Sample | 12 | 58,3 % | 0,98 | −0,08 | −35 $ | 908 $ |
| Gesamt | 25 | 56,0 % | 1,20 | +0,05 | +709 $ | 908 $ |

Reproduzieren: `python backtest/sweep_backtest.py --tf 5m --trend none --risk-atr 0`.
M15 hatte nur 6 Trades in 48 Tagen und war statistisch wertlos. Das Ergebnis hing an einzelnen Trades
(mit max. 100 Punkten Stop: −2.221 $). Echte Scalps mit engem Stop funktionieren auf MNQ zur NY-Eröffnung nicht:
Die Stops liegen im Median bei ~90 Punkten (~180 $ pro Kontrakt).

**Nicht mit echtem Geld handeln**, bevor die Strategie über mehrere Jahre im Strategy Tester und danach mehrere
Wochen auf einem Demokonto positiv war. Keine Anlageberatung, keine Gewinngarantie.

## Darstellung im Chart

Das Pine-Script zeichnet auch rückwirkend für jeden Tag:

- **Trade-Boxen** wie das Long/Short-Positions-Werkzeug: Rot = Risiko (Einstieg bis Stop), Grün = Ziel
  (Einstieg bis TP2), gestrichelt = TP1. Am Ausstieg steht das Ergebnis in $.
- **Liquiditäts-Levels** (PDH/PDL, Overnight, Asia, London, M5-Swing-Hochs/-Tiefs) mit Namen. Sie beginnen an der
  Kerze, an der sie entstanden sind, und enden an der Kerze, die sie durchbricht (durchgezogenes Ende).
  Ein Level, das bis Tagesende hält, endet gepunktet. Ein gebrochenes Level wird danach nicht mehr gezeigt und nicht mehr gehandelt.
- **M15-Support/Resistance-Zonen**: Docht-Bereich eines bestätigten M15-Swings (3 Kerzen je Seite).
  Die Zone gilt, bis eine M5-Kerze darüber (Resistance) bzw. darunter (Support) schließt, dann endet sie dort.
  Nur zur Orientierung, die Einstiege nutzen die Zonen nicht.
- EMA 20/50 bzw. VWAP je nach gewähltem Filter.

Vorschau ohne TradingView: `python backtest/plot_trades.py` erzeugt für jeden Trade-Tag ein Bild in
`backtest/charts/` nach denselben Regeln.

## Wyckoff-Zonen (Begriff aus den Beispielbildern)

Wyckoff beschreibt, wie große Marktteilnehmer in Seitwärtsphasen Positionen aufbauen (Akkumulation) oder
abbauen (Distribution). Die Schlüsselstelle ist der **Spring** (bzw. **Upthrust** oben): Der Preis sticht kurz
unter das Tief der Range, holt die Stops ab und kehrt sofort in die Range zurück. Das ist dasselbe Muster wie der
Liquidity Sweep dieser Strategie. Eine „Wyckoff-Zone“ im Chart ist meist der Bereich um dieses Range-Tief/-Hoch,
in dem auf den Spring und die Rückkehr gewartet wird.

## In TradingView laden

1. Chart `CME_MINI:MNQ1!`, Zeitrahmen **5 Minuten**, Handelszeiten „Electronic Trading Hours“ (Overnight-Kerzen werden gebraucht).
2. Pine Editor → Inhalt von `strategies/mnq_m5_sweep.pine` einfügen → „Zum Chart hinzufügen“.
3. Strategy Tester öffnen. Kommission und Slippage sind im Script voreingestellt. Unter Eigenschaften
   ggf. „Deep Backtesting“ für längere Historie aktivieren.
4. Alarme: „Alarm erstellen“ → Bedingung: diese Strategie → „alert() function calls only“.
   Das Script meldet jeden Sweep und jeden Einstieg mit Stop, TP1 und TP2.

Alle Regeln sind über die Einstellungen änderbar (Zeiten, Levels, Bestätigung, FVG-Pflicht, OTE-Einstieg,
Stop-Grenzen, TP-Größen, Breakeven, Trendfilter, ORB an/aus). Das Pine-Script ist nicht lokal kompiliert. Falls TradingView einen
Fehler meldet, bitte die Meldung schicken. TradingViews Broker-Emulator füllt Orders innerhalb einer Kerze
etwas anders als der konservative Python-Test (dort gilt: Stop und Ziel in derselben Kerze = Stop), daher
weichen die Zahlen leicht ab.

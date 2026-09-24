# MNQ NY-Open Liquidity Sweep (M5)

Regelbasierte Umsetzung der Chart-Beispiele (NAS100 / MNQ rund um die New-York-Eröffnung)
als TradingView-Strategie plus lokaler Python-Backtest.

| Datei | Inhalt |
|---|---|
| `strategies/mnq_m5_sweep.pine` | Pine v6 `strategy()` für TradingView (MNQ1!, 5 Minuten) |
| `backtest/sweep_backtest.py` | Python-Nachbau derselben Regeln, Bar für Bar, ohne Lookahead |
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

## Ergebnisse (ehrlich)

Daten: 17.07.–24.09.2026, 48 Handelstage (mehr als 60 Tage 5-Minuten-Historie gibt es kostenlos nicht).
Die ersten 60 % der Tage dienten der Entwicklung (In-Sample), die letzten 40 % wurden erst am Ende getestet (Out-of-Sample).

```
python backtest/sweep_backtest.py --tf 5m            # Standardwerte
python backtest/sweep_backtest.py --tf 5m --trades   # plus Trade-Liste
python backtest/sweep_backtest.py --tf 15m
python backtest/sweep_backtest.py --tf 5m --grid     # 96 Varianten
```

**M5, Standardwerte**

| Satz | Trades | Trefferquote | Profit-Faktor | Ø R | Netto | Max. Drawdown |
|---|---|---|---|---|---|---|
| In-Sample | 13 | 53,8 % | 1,39 | +0,17 | +745 $ | 575 $ |
| Out-of-Sample | 12 | 58,3 % | 0,98 | −0,08 | −35 $ | 908 $ |
| Gesamt | 25 | 56,0 % | 1,20 | +0,05 | +709 $ | 908 $ |

**M15**: nur 6 Trades in 48 Tagen (−53 $), statistisch wertlos. Kein Vorteil gegenüber M5.

**Einordnung**

- Ein **stabiler Vorteil ist nicht nachweisbar.** Out-of-Sample ist das Ergebnis ungefähr null.
- Das Ergebnis hängt an einzelnen Trades. Mit max. 100 statt 150 Punkten Stop wird es deutlich negativ
  (−2.221 $, PF 0,41). Späterer Ausstieg (12:30 oder 15:45) oder TP2 bei 3R verschlechtert es ebenfalls.
- Im 96-Varianten-Raster sind auf M5 nur 10 % der Varianten in beiden Hälften profitabel, auf M15 keine einzige.
- Echte Scalps mit engem Stop funktionieren hier nicht: Die NY-Open-Kerzen auf MNQ (~30.000 Punkte)
  brauchen Stops von median ~90 Punkten, also ~180 $ pro Kontrakt.
- Die Screenshots zeigen ausgewählte Gewinner. Ein systematischer Test aller gleichartigen Setups sieht deutlich
  nüchterner aus. Beispiel 11.09.2026 (Bild mit MNQ 1m, Short um 10:00): Die Regel steigt erst nach der
  Bestätigung tiefer ein und wird ausgestoppt, während der diskretionäre Trade im Plus lag.

**Nicht mit echtem Geld handeln**, bevor die Strategie im TradingView Strategy Tester über deutlich längere
Historie (TradingView Premium: Deep Backtesting) und danach mehrere Wochen auf einem Demokonto positiv war.
Keine Anlageberatung, keine Gewinngarantie.

## In TradingView laden

1. Chart `CME_MINI:MNQ1!`, Zeitrahmen **5 Minuten**, Handelszeiten „Electronic Trading Hours“ (Overnight-Kerzen werden gebraucht).
2. Pine Editor → Inhalt von `strategies/mnq_m5_sweep.pine` einfügen → „Zum Chart hinzufügen“.
3. Strategy Tester öffnen. Kommission und Slippage sind im Script voreingestellt. Unter Eigenschaften
   ggf. „Deep Backtesting“ für längere Historie aktivieren.
4. Alarme: „Alarm erstellen“ → Bedingung: diese Strategie → „alert() function calls only“.
   Das Script meldet jeden Sweep und jeden Einstieg mit Stop, TP1 und TP2.

Alle Regeln sind über die Einstellungen änderbar (Zeiten, Levels, Bestätigung, FVG-Pflicht, OTE-Einstieg,
Stop-Grenzen, TP-Größen, Breakeven). Das Pine-Script ist nicht lokal kompiliert. Falls TradingView einen
Fehler meldet, bitte die Meldung schicken. TradingViews Broker-Emulator füllt Orders innerhalb einer Kerze
etwas anders als der konservative Python-Test (dort gilt: Stop und Ziel in derselben Kerze = Stop), daher
weichen die Zahlen leicht ab.

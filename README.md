# Alpaca-Colude — strategia „BOS → Volume Profile → pullback în POC”

Strategie de trend-following (long și short) construită exact pe pașii din transcript.

| Pas din transcript | Implementare (`alpaca_colude/strategy.py`) |
|---|---|
| Găsește trendul | HH + HL: ultimele 2 swing high și 2 swing low cresc (short: LH + LL). Pivoții sunt confirmați după `swing_n` lumânări. |
| Marchează ultimul break of structure | Lumânare care **închide** peste ultimul swing high (un BOS per nivel). |
| Mișcarea care a creat BOS: de la HL la HH | HL = minimul dintre swing high-ul rupt și BOS; HH = maximul mișcării (se actualizează la fiecare maxim nou). |
| Fixed range volume profile pe toată mișcarea | `volume_profile.py`, interval HL → HH, `n_bins` niveluri. |
| Cauți POC | Nivelul cu cel mai mare volum. **Nu e intrare.** |
| Aștepți pullback în POC | Setup activ până când `low <= POC`; intrarea e la închiderea lumânării care atinge POC și îl respinge (`close > POC`). |
| „Trendul e încă valid?” | Dacă prețul încalcă HL-ul mișcării, setup-ul se anulează (`strict_structure=True`: și un fitil sub HL; `False`: doar închidere). |
| Stop sub cel mai adânc fitil al reacției | `min(low)` de la prima atingere a POC până la lumânarea de intrare, minus `stop_buffer_atr * ATR`. |
| Target: higher high anterior | Maximul mișcării (HH). Se ia trade-ul doar dacă RR ≥ `min_rr`. |

Shortul rulează aceeași logică pe prețuri oglindite, deci regulile sunt identice.

## Utilizare

```bash
pip install -r requirements.txt
python run.py --demo                                   # date sintetice, doar ca test de funcționare
python run.py --csv date.csv --side both               # CSV: timestamp,open,high,low,close,volume
export ALPACA_API_KEY=... ALPACA_SECRET_KEY=...
python run.py --symbol AAPL --timeframe 15Min --days 60
python run.py --symbol BTC/USD --crypto --timeframe 1Hour --days 120
python run.py --symbol AAPL --scan                     # semnal pe ultima lumânare
python -m pytest -q
```

Parametri (toți au și flag în CLI): `swing_n=5`, `atr_period=14`, `n_bins=50`, `min_move_atr=2.0`,
`min_move_bars=5`, `min_rr=1.0`, `stop_buffer_atr=0.1`, `max_wait_bars=60`, `strict_structure=True`.
Risc: 1% din equity per trade (`--risk`), notional maxim 1× equity, slippage 1 bp la intrare și la stop.

## Ce e verificat și ce nu

- Testat: POC corect, fără look-ahead (semnalele pe date trunchiate sunt identice), short = oglinda long-ului,
  scenariu construit manual care respectă fiecare regulă, invariante (stop < intrare < target, RR ≥ minim).
- `fetch_coinbase` (date publice, fără chei, cu volum real) a fost folosit pentru backtest pe SOL/ETH/INJ/STX/ZEC; `backtest(..., position_pct=0.6, fee_bps=25)` suportă mărime fixă din equity și comisioane.
- **Nu e testat** `fetch_alpaca` (nu am chei Alpaca în sesiune) și nu am rulat backtest pe date reale.
  Rezultatul din `--demo` vine din date aleatoare și **nu spune nimic despre profitabilitate**.
- Dacă stop și target sunt atinse în aceeași lumânare, se presupune stop-ul (conservator).
- Nu există încă trimitere de ordine; strategia produce doar semnale/backtest.

Nu este sfat financiar. Validează pe date reale (out-of-sample) și în paper trading înainte de bani reali.

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

## Actualizare: audit, SL fix, mărime fixă, rezultate

- `StrategyParams.fixed_stop_pct` (SL exact la x% de la intrare) și `tp_rr` (TP = x × SL); `backtest(..., fixed_notional=100)` pentru
  mărime fixă per trade, fără compunere. Drawdown-ul include acum capitalul inițial.
- `tests/reference_impl.py` = implementare independentă a strategiei, folosită pentru audit (`tests/test_reference.py`).
  Pe date reale (futures 15m/1h, 5 monede, long și short) cele două implementări dau exact aceleași trade-uri.
- `scripts/fetch_2y.py` + `scripts/grid.py` produc `results/grid_results.csv` și `results/per_coin_tables.md`
  (15 monede × 15m/30m/1h/2h/4h × SL 1,5%/2% × TP 2x/2,5x, long/short, pe ani).

## Short pe 15m, monede noi (55 simboluri USDT-M, ~4 ani)

Scripturi: `scripts/short15m_*.py`. Rezultate: `results/short15m_*.csv`. Metodă: variantele (36 = SL 1,5/2% × TP 2/2,5× × `swing_n` 3/5/8 ×
mișcare minimă 1/2/3 ATR) s-au evaluat separat pe „train” (nov 2022 – nov 2024) și „test” (nov 2024 – nov 2026).
Concluzii și limite sunt în mesajul din sesiune: câștigul e concentrat în 2025-H1, iar clasamentul monedelor nu persistă între perioade.

## Scanner în timp real (VET, short 15m) cu mărime compusă

```bash
pip install -r requirements.txt
python scan_live.py --equity 100                 # continuu; starea în vet_state.json
python scan_live.py --once                       # o singură verificare (ex. din cron la fiecare 15 min)
python scan_live.py --equity 100 --leverage 3    # mărime = equity * 3
python scan_live.py --set-equity 107.5           # sincronizează cu contul tău real
python scan_live.py --close-position             # ai închis poziția manual
python scan_live.py --replay vet.pkl --replay-bars 6000 --equity 100   # test offline pe istoric
```

- Varianta: short, SL 2%, TP 5% (2,5×SL), `swing_n` 5, mișcare ≥ 3 ATR. Datele: Binance USDT-M (publice, fără chei).
- **Nu trimite ordine.** Îți spune când să vinzi, mărimea (= equity curent × leverage) și SL/TP; urmărește poziția pe lumânări
  și, la SL/TP, actualizează equity-ul (inclusiv comisioane 0,04%/0,02% și slippage 2 bps), deci trade-ul următor intră cu
  equity-ul nou (100 → 107 după un câștig de 7; 107 → 95 după o pierdere de 12 etc.).
- Teste: `tests/test_live.py` (mărime compusă, repornire, parsare date). Pe 20.000 de lumânări reale de VET, scannerul
  produce exact aceleași 29 de trade-uri ca strategia rulată pe tot istoricul.
- Neverificat din mediul de dezvoltare: apelul live către Binance (blocat acolo, HTTP 451). Testat doar parsarea și `--replay`.

## Bot PAPER pe Binance Futures (testnet) + dashboard

```bash
export BINANCE_TESTNET_API_KEY=...  BINANCE_TESTNET_API_SECRET=...   # chei de TESTNET, doar în variabile de mediu
python paper_bot.py --selftest        # verifică ciclul complet (ordin, SL, TP, anulare, ieșire) cu mărime minimă
python paper_bot.py --leverage 3      # pornește botul; dashboard pe http://127.0.0.1:8765
python paper_bot.py --sim vet.pkl --sim-bars 6000      # simulare pe istoric, fără chei
```

- Pereche: **VETUSDT** (VETUSDC nu există ca perpetuu pe Binance Futures). Leverage 1–25 setabil din dashboard
  (se aplică la următoarea intrare); mărime = equity curent × % × leverage, compusă după fiecare trade.
- Siguranță: doar testnet/demo (mainnet refuzat), SL obligatoriu (dacă nu se poate plasa, poziția se închide), SL/TP software
  de rezervă, nu intră dacă există o poziție necunoscută pe exchange, dashboard doar pe 127.0.0.1, cheile nu trec prin dashboard.
- **Neverificat contra Binance:** clientul real (semnarea cererilor e verificată pe vectorul oficial; logica botului pe simulator).
  Ordinele condiționale (SL) merg pe `/fapi/v1/algoOrder` din 2025-12-09; parametrii nu au putut fi confirmați din documentație,
  de aceea `--selftest` trebuie rulat pe contul tău de testnet înainte de pornire. Adresa testnet poate fi
  `testnet.binancefuture.com` sau `demo-fapi.binance.com` (`--base-url`).
- Testele: `tests/test_bot.py` (semnătură, rotunjiri, client cu răspunsuri simulate, ciclu complet, leverage, SL eșuat, dashboard).

- Rezumatul discuției, deciziile și rezultatele: [`docs/DISCUTIE.md`](docs/DISCUTIE.md)

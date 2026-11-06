# Discuția: strategie BOS + Volume Profile (POC) – de la transcript la bot paper

Rezumat structurat al conversației (6 nov 2026, sesiune „New Trading strategy with volume profile”).
Nu e transcriptul literal, ci deciziile, rezultatele și limitele, ca să poți relua munca pe local.

## 1. Cererea inițială
Din transcriptul tău (trend → ultimul BOS → mișcarea de la higher low la higher high → fixed range volume profile → POC →
așteaptă pullback în POC → verifică dacă trendul e valid → intră, SL sub cel mai adânc fitil al reacției, target la
higher high-ul anterior) să se facă o strategie, apoi backtest, apoi scanner, apoi bot paper pe Binance Futures.

## 2. Ce s-a construit (branch `claude/determined-cray-4w6nj6`)
| Fișier | Rol |
|---|---|
| `alpaca_colude/strategy.py` | strategia (long/short, SL structural sau % fix, TP structural sau x·SL) |
| `alpaca_colude/volume_profile.py` | fixed range volume profile + POC |
| `alpaca_colude/backtest.py` | backtest: risc fix, % din equity, **notional fix**, comisioane separate intrare/ieșire |
| `alpaca_colude/data.py` | date: CSV, Alpaca, Coinbase, Binance (arhiva publică data.binance.vision) |
| `alpaca_colude/live.py`, `scan_live.py` | scanner în timp real (paper) cu **mărime compusă** (tot equity-ul curent) |
| `alpaca_colude/exchange.py`, `bot.py`, `dashboard.py`, `paper_bot.py` | bot paper Binance Futures **testnet** + dashboard local, leverage setabil |
| `tests/` | 45 de teste (inclusiv o a doua implementare independentă a strategiei, `reference_impl.py`) |
| `results/`, `scripts/` | rezultate (CSV) și scripturile care le produc |

## 3. Neînțelegeri și erori găsite pe parcurs
1. Eu implementasem SL ca *minim* 2%; tu ceruseși SL **fix** 1,5–2% → corectat (`fixed_stop_pct`).
2. Mărimea era 60% din equity compus; tu ai cerut **100 USDT fix** (apoi, la scanner, **tot equity-ul compus**) → corectat.
3. Drawdown-ul nu includea capitalul inițial (subestimat) → corectat.
4. Auditul logicii (implementare independentă): 20/20 comparații identice pe date reale; nu există eroare în logica strategiei.
5. Prima alegere „cea mai bună variantă” (1h long+short, TP 2×SL) nu a rezistat pe 10 monede noi (8/10 pe minus) → era selecție/noroc.

## 4. Rezultate cheie (toate din backtest, cu comisioane 0,02% intrare / 0,04% ieșire, slippage 2 bps)
- **Comisioane Alpaca crypto (0,25%/parte): toate rezultatele negative.** Pe futures (0,02/0,04%) strategia ajunge în jur de zero.
- **15 monede, 2 ani, 100 USDT fix:** 15m pozitiv în toate cele 4 variante SL1,5/2% × TP2/2,5× (+42…+308 USDT din 500), dar statistic slab
  (t ≤ 1,3) și doar în primul an; 1h clar negativ (t = −4,3 la SL1,5%/TP2×).
- **Short 15m pe 55 monede noi, ~4 ani** (36 variante; train nov 2022–nov 2024, test nov 2024–nov 2026):
  - cea mai bună variantă: **SL 2%, TP 5% (2,5×SL), swing_n 5, mișcare ≥ 3 ATR** → 10.788 trade-uri, **+1011 USDT** (train +297, test +714), t = 2,99;
    cu comision 0,05% pe ambele părți: +580 (t = 1,7);
  - câștig concentrat în 2025-H1 (+678 din 1011); ultimul semestru testat (2026-H2) este negativ (−91);
  - **clasamentul monedelor nu persistă** între perioade (corelație de rang ≈ 0,05); doar 33/55 monede pe plus.
- **Cea mai bună monedă: VET/USDT** (+155% din 100 USDT în 4 ani la 1×; ALGO +140%, WLD +128%). Per monedă, toate cele 55: `results/short15m_best_variant_per_coin_pct.csv`.
- **Leverage (cu rezervă pe cont, notional fix):** portofoliu pe 55 monede (5500 USDT): 1× +18,4%, 2× +36,8%, 3× +55,2%, 5× +91,9%, 10× +183,9%;
  drawdown de la vârf: −8%, −15%, −20%, −46%, −92% din 5500. Pe VET singură: 5× +775%, 10× +1551% (drawdown −115 / −231 USDT, serie maximă 10 pierderi).
  Fără rezervă, la 10× contul de 100 USDT ar fi scăzut sub 50 USDT în 60% din ferestrele de ~20 de luni.
- **VETUSDC nu există ca perpetuu pe Binance Futures** (doar spot) → perechea este **VETUSDT**.

## 5. Scanner și bot
- `python scan_live.py --equity 100` – semnale în timp real, mărime compusă (100 → 107 după +7, 107 → 95 după −12 etc.). Verificat: pe 20.000 de lumânări reale de VET
  produce exact aceleași 29 de trade-uri ca strategia pe tot istoricul.
- `python paper_bot.py --selftest` apoi `python paper_bot.py --leverage 3` – bot pe **testnet** + dashboard http://127.0.0.1:8765 (setări, equity, poziție, trade-uri, pe zile).

## 6. Limite (de ținut minte)
- Totul e backtest: fără funding, fără execuție reală a ordinelor limit; datele sunt doar din ultimii ~4 ani.
- Selecția „celei mai bune monede” e făcută cu privirea în urmă; nu garantează viitorul.
- **Clientul Binance real nu a fost testat** (rețeaua din mediul cloud e blocată). SL-ul merge pe `/fapi/v1/algoOrder` (din 2025-12-09); parametrii nu au putut fi
  confirmați în documentație → rulează `--selftest` pe testnet înainte de bot.
- Cheile API: doar variabile de mediu `BINANCE_TESTNET_API_KEY` / `BINANCE_TESTNET_API_SECRET`, niciodată în fișiere sau chat.

## 7. Pași următori propuși
1. Rulează `--selftest` pe testnet de pe laptop, apoi botul câteva zile (leverage setabil din dashboard) și compară cu backtest-ul.
2. Filtru de regim (short doar când BTC e în trend descendent), testat pe aceeași împărțire train/test.
3. Test pe perioade mai vechi (alte regimuri de piață) și pe alte monede.

## 8. Cum reiei pe local (ex. `C:\Claude-miki`)
```powershell
git clone -b claude/determined-cray-4w6nj6 https://github.com/mmiki76/Alpaca-Colude.git C:\Claude-miki
cd C:\Claude-miki
python -m venv .venv ; .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q
```
Altă sesiune (azi 11:27, „Transcript analysis and strategy”) a lucrat în același repo pe branch-ul `sol-4h-sweep-backtest`.

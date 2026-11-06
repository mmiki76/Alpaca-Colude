"""Implementare de REFERINȚĂ, scrisă independent (bucle simple, fără state machine) – doar pentru audit.

Citește aceeași specificație ca strategia principală, dar structura codului e diferită:
pivoții se calculează offline, volume profile se face cu bucle explicite, iar setup-urile
se parcurg secvențial (BOS -> așteptare pullback -> intrare -> simulare ieșire).
"""
from __future__ import annotations

import math

from alpaca_colude.strategy import StrategyParams, _atr


def naive_poc(highs, lows, vols, n_bins):
    lo, hi = min(lows), max(highs)
    if hi <= lo:
        return lo
    total = sum(vols)
    if total <= 0:
        vols = [1.0] * len(highs)
    step = (hi - lo) / n_bins
    prof = [0.0] * n_bins
    for H, L, V in zip(highs, lows, vols):
        b0 = min(n_bins - 1, int(math.floor((L - lo) / step)))
        b1 = min(n_bins - 1, int(math.floor((H - lo) / step)))
        share = V / (b1 - b0 + 1)
        for b in range(b0, b1 + 1):
            prof[b] += share
    best = max(range(n_bins), key=lambda b: (prof[b], -b))   # primul bin maxim
    return lo + (best + 0.5) * step


def reference_long(o, h, l, c, v, p: StrategyParams):
    n, N = len(c), p.swing_n
    atr = _atr(h, l, c, p.atr_period)

    def is_ph(k):
        return (k - N >= 0 and k + N < n and all(h[k] > h[j] for j in range(k - N, k))
                and all(h[k] >= h[j] for j in range(k + 1, k + N + 1)))

    def is_pl(k):
        return (k - N >= 0 and k + N < n and all(l[k] < l[j] for j in range(k - N, k))
                and all(l[k] <= l[j] for j in range(k + 1, k + N + 1)))

    ph = [k for k in range(n) if is_ph(k)]
    pl = [k for k in range(n) if is_pl(k)]
    used, trades = set(), []
    t = 0
    while t < n:
        # --- BOS la bara t? (pivoții confirmați = cei cu k + N <= t, deci k >= N asigurat de is_ph)
        shs = [k for k in ph if k + N <= t]
        sls = [k for k in pl if k + N <= t]
        if math.isnan(atr[t]) or len(shs) < 2 or len(sls) < 2:
            t += 1; continue
        ks = shs[-1]
        if ks in used or c[t] <= h[ks]:
            t += 1; continue
        used.add(ks)
        up = h[shs[-1]] > h[shs[-2]] and l[sls[-1]] > l[sls[-2]]
        if not up:
            t += 1; continue
        s = min(range(ks, t + 1), key=lambda j: (l[j], j))
        if l[s] < l[sls[-1]] or c[t] - l[s] < p.min_move_atr * atr[t] or t - s < p.min_move_bars:
            t += 1; continue
        # --- setup activ
        start_low = l[s]
        hi_i = max(range(s, t + 1), key=lambda j: (h[j], -j))
        mh = h[hi_i]
        poc = naive_poc(h[s:hi_i + 1], l[s:hi_i + 1], v[s:hi_i + 1], p.n_bins)
        touch = None
        j, entered = t + 1, None
        while j < n:
            if (l[j] <= start_low) if p.strict_structure else (c[j] <= start_low):
                break
            if h[j] > mh:
                hi_i, mh = j, h[j]
                poc = naive_poc(h[s:j + 1], l[s:j + 1], v[s:j + 1], p.n_bins)
                touch = None
                j += 1; continue
            if j - hi_i > p.max_wait_bars:
                break
            if l[j] <= poc:
                touch = l[j] if touch is None else min(touch, l[j])
                if c[j] > poc:
                    entered = j
                    break
            j += 1
        if entered is None:
            t = j + 1 if j < n else n
            continue
        e = entered
        entry = c[e]
        if p.fixed_stop_pct is not None:
            stop = entry - p.fixed_stop_pct * abs(entry)
        else:
            stop = min(touch - p.stop_buffer_atr * atr[e], entry - p.min_stop_pct * abs(entry))
        risk = entry - stop
        target = mh if p.tp_rr is None else entry + p.tp_rr * risk
        if not (risk > 0 and target - entry >= p.min_rr * risk):
            t = e + 1
            continue
        # --- simulare ieșire
        ex_i, ex_p, why = n - 1, c[-1], "open"
        for k in range(e + 1, n):
            if l[k] <= stop:
                ex_i, ex_p, why = k, min(stop, o[k]), "stop"; break
            if h[k] >= target:
                ex_i, ex_p, why = k, max(target, o[k]), "target"; break
        trades.append((e, entry, stop, target, ex_i, ex_p, why, poc))
        t = ex_i + 1
    return trades

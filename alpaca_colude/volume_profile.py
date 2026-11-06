"""Fixed-range volume profile (FRVP) și POC (Point of Control)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class VolumeProfile:
    edges: np.ndarray    # n_bins + 1 limite de preț
    volume: np.ndarray   # n_bins volum pe nivel de preț
    poc: float           # prețul (centrul binului) cu cel mai mare volum

    @property
    def centers(self) -> np.ndarray:
        return (self.edges[:-1] + self.edges[1:]) / 2.0


def fixed_range_volume_profile(
    high: np.ndarray, low: np.ndarray, volume: np.ndarray, n_bins: int = 50
) -> VolumeProfile:
    """Volume profile peste un interval fix de lumânări (ex. de la HL până la HH).

    Volumul fiecărei lumânări este distribuit uniform pe binii de preț pe care
    îi acoperă intervalul [low, high] al lumânării. Dacă volumul lipsește
    (suma = 0), fiecare lumânare are pondere egală (profil TPO).
    """
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    volume = np.asarray(volume, dtype=float)
    if high.size == 0:
        raise ValueError("Interval gol pentru volume profile")
    if volume.sum() <= 0:
        volume = np.ones_like(high)

    lo, hi = float(low.min()), float(high.max())
    if hi <= lo:  # toate lumânările pe același preț
        edges = np.array([lo, lo + 1e-9])
        return VolumeProfile(edges, np.array([volume.sum()]), lo)

    step = (hi - lo) / n_bins
    i0 = np.clip(((low - lo) / step).astype(int), 0, n_bins - 1)
    i1 = np.clip(((high - lo) / step).astype(int), 0, n_bins - 1)
    weight = volume / (i1 - i0 + 1)

    diff = np.zeros(n_bins + 1)
    np.add.at(diff, i0, weight)
    np.add.at(diff, i1 + 1, -weight)
    prof = np.cumsum(diff)[:n_bins]

    edges = lo + step * np.arange(n_bins + 1)
    poc = float(lo + (int(np.argmax(prof)) + 0.5) * step)
    return VolumeProfile(edges, prof, poc)

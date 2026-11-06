"""Robust cleaning of cycle-level signals.

Capacity: a one-sided Hampel filter flags cycles whose capacity drops far below
the local median. These are interrupted or partial discharges (common in CALCE).
Upward jumps are left alone because capacity regeneration after rest periods is
a real effect (visible in NASA data).

Charge features: a two-sided Hampel filter replaces spikes with the local median,
then gaps are interpolated within each cell.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MAD_SCALE = 1.4826   # MAD -> standard deviation for normal noise


def rolling_median_mad(x: pd.Series, window: int) -> tuple[pd.Series, pd.Series]:
    med = x.rolling(window, center=True, min_periods=3).median()
    mad = (x - med).abs().rolling(window, center=True, min_periods=3).median() * MAD_SCALE
    return med, mad


def hampel_flags(x: pd.Series, window: int = 11, n_sigma: float = 3.0,
                 min_abs: float = 0.0, side: str = "both") -> pd.Series:
    """True where |x - rolling median| exceeds max(n_sigma * MAD, min_abs)."""
    med, mad = rolling_median_mad(x, window)
    dev = x - med
    limit = np.maximum(n_sigma * mad.fillna(0), min_abs)
    if side == "low":
        flag = dev < -limit
    elif side == "high":
        flag = dev > limit
    else:
        flag = dev.abs() > limit
    return flag.fillna(False)


def clean_capacity(g: pd.DataFrame, window: int = 11, n_sigma: float = 3.0,
                   min_drop_soh: float = 0.015) -> pd.Series:
    """Outlier flags for one cell. Two passes catch clusters of bad cycles."""
    soh = g["soh"].astype(float)
    flags = hampel_flags(soh, window, n_sigma, min_drop_soh, side="low")
    soh2 = soh.mask(flags)
    flags2 = hampel_flags(soh2.interpolate(limit_direction="both"), window, n_sigma,
                          min_drop_soh, side="low")
    return flags | flags2


def repair_feature(x: pd.Series, window: int = 9, n_sigma: float = 3.5,
                   rel_floor: float = 0.05) -> pd.Series:
    """Replace spikes with the local median; fill gaps by interpolation."""
    x = x.astype(float)
    med, _ = rolling_median_mad(x, window)
    floor = rel_floor * x.abs().median() if x.notna().any() else 0.0
    flags = hampel_flags(x, window, n_sigma, floor, side="both")
    out = x.mask(flags, med)
    return out.interpolate(limit_direction="both")


def clean_cell(g: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    g = g.copy()
    g["soh_raw"] = g["soh"]
    g["is_outlier"] = clean_capacity(g)
    clean = g["soh"].mask(g["is_outlier"]).interpolate(limit_direction="both")
    g["soh"] = clean
    g["capacity_ah"] = g["capacity_ah"].mask(g["is_outlier"]).interpolate(limit_direction="both")
    # smoothed curve for end-of-life detection (robust to regeneration jumps)
    g["soh_smooth"] = clean.rolling(9, center=True, min_periods=1).median()
    for c in feature_cols:
        if g[c].notna().sum() >= 5:
            g[c] = repair_feature(g[c])
    return g

"""Shared regression metrics."""
from __future__ import annotations

import numpy as np


def regression_metrics(y_true, y_pred) -> dict:
    y, p = np.asarray(y_true, float), np.asarray(y_pred, float)
    err = p - y
    ss_res = float(np.sum(err ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2)) or 1e-12
    return {
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(np.sqrt(np.mean(err ** 2))),
        "r2": 1 - ss_res / ss_tot,
        "max_abs": float(np.max(np.abs(err))),
        "bias": float(np.mean(err)),
        "n": int(len(y)),
    }


def interval_coverage(y_true, lo, hi) -> float:
    y = np.asarray(y_true, float)
    return float(np.mean((y >= np.asarray(lo)) & (y <= np.asarray(hi))))


def round_dict(d, nd=5):
    if isinstance(d, dict):
        return {k: round_dict(v, nd) for k, v in d.items()}
    if isinstance(d, float):
        return round(d, nd)
    return d

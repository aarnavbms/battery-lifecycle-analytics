"""Turn a live telemetry stream into cycle rows in the project's unified schema.

A cycle is a charge phase followed by a discharge phase. From each one the same
health indicators are computed as for the NASA and CALCE data (see
batterylife/data/schema.py), so the hardware cell enters the pipeline exactly
like a laboratory cell.

    capacity_ah        coulomb counting over the discharge (integral of |i| dt)
    cc_charge_time_s   charge start until the voltage reaches 4.2 V
    cv_charge_time_s   4.2 V until the current falls to the cut-off
    charge_v_rise_s    3.9 V -> 4.2 V during constant-current charging
    resistance_ohm     voltage step when the discharge load switches on, / current
"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from ..data.schema import CYCLE_COLUMNS
from .protocol import Sample

I_ACTIVE = 0.02     # A: below this the cell is resting
V_CV = 4.195


def phases(samples: list[Sample]) -> list[tuple[str, int, int]]:
    """Split into (phase, start, end) runs of charge / discharge / rest."""
    lab = ["charge" if s.i > I_ACTIVE else "discharge" if s.i < -I_ACTIVE else "rest" for s in samples]
    runs, start = [], 0
    for k in range(1, len(lab) + 1):
        if k == len(lab) or lab[k] != lab[start]:
            runs.append((lab[start], start, k))
            start = k
    return runs


def _charge_features(ch: list[Sample]) -> dict:
    t = np.array([s.t_s for s in ch]); v = np.array([s.v for s in ch])
    out = {"cc_charge_time_s": np.nan, "cv_charge_time_s": np.nan, "charge_v_rise_s": np.nan}
    reach = np.flatnonzero(v >= V_CV)
    if len(reach):
        t_cv = t[reach[0]]
        out["cc_charge_time_s"] = float(t_cv - t[0])
        out["cv_charge_time_s"] = float(t[-1] - t_cv)
        below = np.flatnonzero((v <= 3.9) & (t <= t_cv))
        if len(below):
            out["charge_v_rise_s"] = float(t_cv - t[below[-1]])
    return out


def _discharge_features(dis: list[Sample], before: Sample | None) -> dict:
    t = np.array([s.t_s for s in dis]); v = np.array([s.v for s in dis]); i = np.array([s.i for s in dis])
    dt = np.diff(t, prepend=t[0])
    cap = float(np.sum(np.abs(i) * dt) / 3600.0)
    temp = np.array([s.temp for s in dis])
    r = np.nan
    if before is not None:
        r = float((before.v - np.mean(v[:3])) / max(np.mean(np.abs(i[:3])), 1e-6))
    return {"capacity_ah": cap, "discharge_time_s": float(t[-1] - t[0]),
            "mean_discharge_v": float(v.mean()),
            "discharge_energy_wh": float(np.sum(np.abs(v * i) * dt) / 3600.0),
            "resistance_ohm": r, "temp_max_c": float(temp.max()), "temp_rise_c": float(temp.max() - temp[0])}


def cycles_from_samples(samples: Iterable[Sample], rated_ah: float, min_points: int = 30) -> pd.DataFrame:
    samples = list(samples)
    rows, pending_charge = [], None
    runs = phases(samples)
    for idx, (ph, a, b) in enumerate(runs):
        seg = samples[a:b]
        if ph == "charge" and len(seg) >= min_points:
            pending_charge = seg
        elif ph == "discharge" and len(seg) >= min_points and pending_charge is not None:
            before = samples[a - 1] if a > 0 and runs[idx - 1][0] == "rest" else None
            row = {**_charge_features(pending_charge), **_discharge_features(seg, before)}
            row.update({"dataset": "hardware", "cell_id": seg[0].cell, "ambient_c": float(samples[0].temp),
                        "timestamp": None})
            rows.append(row)
            pending_charge = None
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=CYCLE_COLUMNS)
    df["cycle"] = np.arange(1, len(df) + 1)
    df["soh"] = df["capacity_ah"] / rated_ah
    return df.reindex(columns=CYCLE_COLUMNS)

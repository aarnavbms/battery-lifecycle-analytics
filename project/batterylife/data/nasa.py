"""Loader for the NASA PCoE Li-ion battery dataset (cells B0005, B0006, B0007, B0018).

Each .mat file holds a time-ordered list of operations: 'charge', 'discharge' and
'impedance'. A cycle row is built from every discharge, paired with the charge that
immediately preceded it. Resistance (Re + Rct) comes from the EIS measurements and
is linearly interpolated onto the discharge timestamps.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.io as sio

from ..config import NASA, RAW_DIR
from .schema import CYCLE_COLUMNS

CC_CURRENT_A = 1.5     # NASA CC charge current
V_MAX = 4.2


def _matlab_time(vec) -> datetime:
    v = [float(x) for x in np.ravel(vec)]
    sec = int(v[5]); micro = int(round((v[5] - sec) * 1e6))
    return datetime(int(v[0]), int(v[1]), int(v[2]), int(v[3]), int(v[4])) + timedelta(
        seconds=sec, microseconds=micro)


def charge_features(t: np.ndarray, v: np.ndarray, i: np.ndarray) -> dict:
    """CC/CV durations and the 3.9->4.2 V rise time of one charge curve."""
    out = {"cc_charge_time_s": np.nan, "cv_charge_time_s": np.nan, "charge_v_rise_s": np.nan}
    if len(t) < 10:
        return out
    reach = np.flatnonzero(v >= V_MAX - 0.005)
    if len(reach) == 0:
        return out
    t_cv = t[reach[0]]
    out["cc_charge_time_s"] = float(t_cv - t[0])
    after = np.flatnonzero((t > t_cv) & (np.abs(i) < 0.05))
    t_end = t[after[0]] if len(after) else t[-1]
    out["cv_charge_time_s"] = float(t_end - t_cv)
    below = np.flatnonzero((v <= 3.9) & (t <= t_cv))
    if len(below):
        out["charge_v_rise_s"] = float(t_cv - t[below[-1]])
    return out


def discharge_features(t, v, i, temp) -> dict:
    # NASA keeps logging after the load switches off (voltage recovers); keep load-on part
    on = np.flatnonzero(np.abs(i) > 1.0)
    if len(on) > 5:
        sl = slice(on[0], on[-1] + 1)
        t, v, i, temp = t[sl], v[sl], i[sl], temp[sl]
    dt = np.diff(t, prepend=t[0])
    energy = float(np.sum(np.abs(v * i) * dt) / 3600.0)
    return {
        "discharge_time_s": float(t[-1] - t[0]),
        "mean_discharge_v": float(np.mean(v)),
        "discharge_energy_wh": energy,
        "temp_max_c": float(np.max(temp)),
        "temp_rise_c": float(np.max(temp) - temp[0]),
    }


def load_cell(cell_id: str, raw_dir: Path | None = None) -> pd.DataFrame:
    path = (raw_dir or RAW_DIR / "nasa") / f"{cell_id}.mat"
    ops = sio.loadmat(path, simplify_cells=True)[cell_id]["cycle"]

    imp_t, imp_r = [], []
    rows, last_charge = [], None
    for op in ops:
        kind, d = op["type"], op["data"]
        if kind == "charge":
            last_charge = d
        elif kind == "impedance":
            re, rct = float(np.real(d["Re"])), float(np.real(d["Rct"]))
            if 0 < re < 1 and 0 < rct < 1:
                imp_t.append(_matlab_time(op["time"]).timestamp())
                imp_r.append(re + rct)
        elif kind == "discharge":
            t = np.asarray(d["Time"], float)
            v = np.asarray(d["Voltage_measured"], float)
            i = np.asarray(d["Current_measured"], float)
            temp = np.asarray(d["Temperature_measured"], float)
            row = {
                "dataset": "nasa", "cell_id": cell_id,
                "timestamp": _matlab_time(op["time"]).isoformat(timespec="seconds"),
                "capacity_ah": float(np.squeeze(d["Capacity"])),
                "ambient_c": float(op["ambient_temperature"]),
                **discharge_features(t, v, i, temp),
            }
            if last_charge is not None:
                row.update(charge_features(np.asarray(last_charge["Time"], float),
                                           np.asarray(last_charge["Voltage_measured"], float),
                                           np.asarray(last_charge["Current_measured"], float)))
            rows.append(row)

    df = pd.DataFrame(rows)
    df["cycle"] = np.arange(1, len(df) + 1)
    df["soh"] = df["capacity_ah"] / NASA.rated_capacity_ah
    if imp_t:
        ts = np.array([datetime.fromisoformat(s).timestamp() for s in df["timestamp"]])
        order = np.argsort(imp_t)
        df["resistance_ohm"] = np.interp(ts, np.asarray(imp_t)[order], np.asarray(imp_r)[order])
    else:
        df["resistance_ohm"] = np.nan
    return df.reindex(columns=CYCLE_COLUMNS)


def load(raw_dir: Path | None = None) -> pd.DataFrame:
    return pd.concat([load_cell(c, raw_dir) for c in NASA.cells], ignore_index=True)

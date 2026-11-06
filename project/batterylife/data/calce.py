"""Loader for the CALCE CS2 LCO prismatic cells (CS2_35, CS2_36, CS2_37, CS2_38).

Arbin exports are split into many .xlsx files per cell, named
CS2_xx_M_D_YY.xlsx. Files are read in date order and Cycle_Index restarts in
every file, so cycles are renumbered globally. Protocol: CC 0.55 A charge to
4.2 V, CV to 0.05 A, CC 1.1 A (1C) discharge to 2.7 V.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import CALCE, RAW_DIR
from .schema import CYCLE_COLUMNS

V_MAX = 4.2
DISCHARGE_A = 1.1


def _file_date(p: Path) -> date:
    m, d, y = re.search(r"_(\d+)_(\d+)_(\d+)\.xlsx$", p.name).groups()
    return date(2000 + int(y), int(m), int(d))


def _read_sheets(p: Path) -> pd.DataFrame:
    x = pd.ExcelFile(p)
    parts = [x.parse(s) for s in x.sheet_names if s.lower().startswith("channel")]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def _cycle_row(g: pd.DataFrame) -> dict | None:
    cur = g["Current(A)"].to_numpy(float)
    vol = g["Voltage(V)"].to_numpy(float)
    t = g["Test_Time(s)"].to_numpy(float)

    dis = cur < -0.5 * DISCHARGE_A
    chg = cur > 0.02
    if dis.sum() < 20 or chg.sum() < 20:
        return None
    # only full 1C discharges count as cycles
    if abs(np.median(cur[dis]) + DISCHARGE_A) > 0.1:
        return None

    dcap = g["Discharge_Capacity(Ah)"].to_numpy(float)[dis]
    capacity = float(dcap.max() - dcap.min())
    td, vd, idd = t[dis], vol[dis], cur[dis]
    energy = float(np.sum(np.abs(vd * idd) * np.diff(td, prepend=td[0])) / 3600)

    tc, vc, ic = t[chg], vol[chg], cur[chg]
    cc_level = np.median(ic[: max(5, len(ic) // 4)])
    reach = np.flatnonzero(vc >= V_MAX - 0.005)
    cc_time = cv_time = v_rise = np.nan
    if len(reach):
        t_cv = tc[reach[0]]
        cc_time = float(t_cv - tc[0])
        cv_time = float(tc[-1] - t_cv)
        below = np.flatnonzero((vc <= 3.9) & (tc <= t_cv))
        if len(below):
            v_rise = float(t_cv - tc[below[-1]])

    ir = g["Internal_Resistance(Ohm)"].to_numpy(float)
    ir = ir[(ir > 0) & (ir < 1)]
    return {
        "capacity_ah": capacity,
        "cc_charge_time_s": cc_time,
        "cv_charge_time_s": cv_time,
        "charge_v_rise_s": v_rise,
        "discharge_time_s": float(td[-1] - td[0]),
        "mean_discharge_v": float(vd.mean()),
        "discharge_energy_wh": energy,
        "resistance_ohm": float(np.median(ir)) if len(ir) else np.nan,
        "timestamp": pd.Timestamp(g["Date_Time"].iloc[int(np.flatnonzero(dis)[0])]).isoformat()
        if "Date_Time" in g else None,
        "_cc_level": cc_level,
    }


def load_cell(cell_id: str, raw_dir: Path | None = None) -> pd.DataFrame:
    folder = (raw_dir or RAW_DIR / "calce") / cell_id
    files = sorted(folder.glob(f"{cell_id}_*.xlsx"), key=_file_date)
    rows = []
    for f in files:
        df = _read_sheets(f)
        if df.empty:
            continue
        for _, g in df.groupby("Cycle_Index", sort=True):
            r = _cycle_row(g)
            if r is not None:
                r["source_file"] = f.name
                rows.append(r)
    out = pd.DataFrame(rows)
    out["dataset"], out["cell_id"] = "calce", cell_id
    out["cycle"] = np.arange(1, len(out) + 1)
    out["soh"] = out["capacity_ah"] / CALCE.rated_capacity_ah
    out["temp_max_c"] = out["temp_rise_c"] = np.nan
    out["ambient_c"] = np.nan
    return out.reindex(columns=CYCLE_COLUMNS)


def load(raw_dir: Path | None = None) -> pd.DataFrame:
    return pd.concat([load_cell(c, raw_dir) for c in CALCE.cells], ignore_index=True)

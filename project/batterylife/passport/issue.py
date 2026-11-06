"""Issue a Digital Battery Passport for every cell from the pipeline results.

Measurements are real (test timestamps, AI estimates from leave-one-cell-out
models). The surrounding lifecycle actors (manufacturer, vehicle maker,
repurposer, recycler) are simulated so the full passport workflow can be shown
on laboratory cells.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from ..config import DATASETS, SUSTAINABILITY, THRESHOLDS
from ..models.rul import eol_cycle
from .ledger import ActorRegistry, Passport

ASSESS_EVERY = {"nasa": 20, "calce": 100}


def _ts(t: str, days: float = 0, hours: float = 0) -> str:
    return (datetime.fromisoformat(str(t)) + timedelta(days=days, hours=hours)).isoformat(timespec="seconds")


def _r(x, nd=4):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), nd)


def _nearest(df: pd.DataFrame, cycle: int, tol: int):
    if df.empty:
        return None
    row = df.iloc[(df["cycle"] - cycle).abs().argmin()]
    return row if abs(row["cycle"] - cycle) <= tol else None


def issue_for_cell(cell: pd.DataFrame, rul: pd.DataFrame, assessment_80: pd.Series | None,
                   reg: ActorRegistry, soh_model_name: str) -> Passport:
    g = cell.reset_index(drop=True)
    ds, cid = g["dataset"].iloc[0], g["cell_id"].iloc[0]
    info = DATASETS[ds]
    p = Passport(f"DBP-{ds.upper()}-{cid}", cid)
    A = reg.actors
    t0 = g["timestamp"].iloc[0]
    ok = g[~g["is_outlier"]]

    p.append(A["MFR-01"], "MANUFACTURED", {
        "model": cid, "chemistry": info.chemistry, "form_factor": info.form_factor,
        "rated_capacity_ah": info.rated_capacity_ah, "nominal_voltage_v": info.nominal_voltage_v,
        "manufacturer": info.manufacturer, "manufacture_date": _ts(t0, -30)[:10],
        "manufacturing_site": "not disclosed (laboratory test cell)",
        "initial_capacity_ah": _r(ok["capacity_ah"].iloc[:5].median()),
        "initial_resistance_ohm": _r(ok["resistance_ohm"].iloc[:10].median()),
        "expected_cycle_life": None, "data_source": info.source}, _ts(t0, -30))
    kwh = info.rated_capacity_ah * info.nominal_voltage_v / 1000
    p.append(A["MFR-01"], "CARBON_FOOTPRINT_DECLARED", {
        "kgco2e_per_kwh": SUSTAINABILITY.manufacturing_kgco2e_per_kwh,
        "total_kgco2e": round(kwh * SUSTAINABILITY.manufacturing_kgco2e_per_kwh, 4),
        "basis": "assumed mid value of published 61-106 kg CO2e/kWh (IVL)"}, _ts(t0, -29))
    p.append(A["OEM-01"], "FIRST_LIFE_START", {"application": "EV traction (laboratory ageing test)",
                                               "ambient_c": _r(g["ambient_c"].iloc[0], 1)}, _ts(t0))

    retire = eol_cycle(g["soh_smooth"], g["cycle"], THRESHOLDS.first_life_eol)
    floor = eol_cycle(g["soh_smooth"], g["cycle"], THRESHOLDS.second_life_floor)
    last = int(g["cycle"].iloc[-1])
    step = ASSESS_EVERY[ds]
    rul80 = rul[np.isclose(rul["threshold"], THRESHOLDS.first_life_eol)]
    rul60 = rul[np.isclose(rul["threshold"], THRESHOLDS.second_life_floor)]

    def assess_at(k: int, phase_rul: pd.DataFrame, threshold: float):
        row = g.iloc[(g["cycle"] - k).abs().argmin()]
        p.append(A["AI-ASSESSOR"], "SOH_ASSESSMENT", {
            "cycle": int(row["cycle"]), "soh": _r(row["soh_pred"]), "soh_lo": _r(row["soh_lo"]),
            "soh_hi": _r(row["soh_hi"]), "soh_measured": _r(row["soh"]),
            "resistance_growth": _r(row["resistance_growth"], 3),
            "method": f"{soh_model_name} on charge-phase signals, 95% conformal interval"},
            row["timestamp"])
        snap = _nearest(phase_rul, int(row["cycle"]), 10)
        if snap is not None and not np.isnan(snap.get("rul_gbr", np.nan)):
            p.append(A["AI-ASSESSOR"], "RUL_PREDICTION", {
                "cycle": int(row["cycle"]), "threshold": threshold,
                "rul_cycles": _r(snap["rul_gbr"], 1), "rul_lo": _r(snap["rul_gbr_lo"], 1),
                "rul_hi": _r(snap["rul_gbr_hi"], 1),
                "method": "quantile gradient boosting, conformalised (80% band)"}, row["timestamp"])

    end_first = retire or last
    for k in range(step, end_first, step):
        assess_at(k, rul80, THRESHOLDS.first_life_eol)
    if retire is None:
        return p

    row = g[g.cycle == retire].iloc[0]
    p.append(A["OEM-01"], "FIRST_LIFE_RETIRED", {"cycle": int(retire), "reason": "SOH reached 80%"},
             row["timestamp"])
    assess_at(retire, rul60, THRESHOLDS.second_life_floor)
    a = assessment_80
    grade = a["grade_pred"] if a is not None else "D"
    p.append(A["AI-ASSESSOR"], "SECOND_LIFE_GRADING", {
        "cycle": int(retire), "grade": grade,
        "application": a["application"] if a is not None else "Recycling / material recovery",
        "confidence": a["confidence"] if a is not None else "low",
        "recommendation": a["recommendation"] if a is not None else "recycle",
        "service_years": _r(a["service_years"], 2) if a is not None else None,
        "co2_avoided_kg_per_60kwh_pack": _r(a["co2_avoided_kg_pack"], 1) if a is not None else None},
        _ts(row["timestamp"], hours=1))
    if grade == "D":
        p.append(A["OEM-01"], "SENT_TO_RECYCLING", {"cycle": int(retire), "reason": "graded D"},
                 _ts(row["timestamp"], hours=2))
        return p
    p.append(A["REP-01"], "REPURPOSED", {"cycle": int(retire), "application": a["application"],
                                        "new_status": "repurposed"}, _ts(row["timestamp"], hours=2))
    end_second = floor or last
    for k in range(retire + step, end_second, step):
        assess_at(k, rul60, THRESHOLDS.second_life_floor)
    if floor is not None:
        frow = g[g.cycle == floor].iloc[0]
        assess_at(floor, rul60.iloc[0:0], THRESHOLDS.second_life_floor)
        p.append(A["REP-01"], "SENT_TO_RECYCLING", {"cycle": int(floor),
                                                   "reason": "SOH reached 60% second-life floor"},
                 _ts(frow["timestamp"], hours=1))
    return p


def issue_all(features, soh_preds, rul_preds, assessments, reg, soh_models: dict) -> list[Passport]:
    sp = soh_preds[["cell_id", "cycle", "soh_pred", "soh_lo", "soh_hi"]]
    df = features.merge(sp, on=["cell_id", "cycle"], how="left")
    for c in ("soh_pred", "soh_lo", "soh_hi"):
        df[c] = df.groupby("cell_id")[c].transform(lambda x: x.interpolate(limit_direction="both"))
    out = []
    for cid, g in df.groupby("cell_id", sort=False):
        a = assessments[(assessments.cell_id == cid) & assessments.is_retirement_point]
        out.append(issue_for_cell(g, rul_preds[rul_preds.cell_id == cid],
                                  a.iloc[0] if len(a) else None, reg,
                                  soh_models[g["dataset"].iloc[0]]))
    return out

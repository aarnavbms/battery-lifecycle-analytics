"""Evaluate second-life decisions on unseen cells.

For every cell and every retirement SOH level in config.RETIREMENT_SOH_LEVELS, the
cell is assessed twice:
  predicted: from out-of-sample SOH estimates, its conformal interval and the
             calibrated RUL-to-60% prediction (what the system would decide)
  true:      from measured SOH and the real number of cycles the cell lasted
The comparison shows how often the AI decision matches the decision a perfect
lab test would give, and whether its mistakes are conservative or optimistic.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from ..config import RESULTS_DIR, RETIREMENT_SOH_LEVELS, THRESHOLDS
from ..models.evaluation import round_dict
from ..models.rul import eol_cycle
from .grading import GRADE_ORDER, assess, grade, lifecycle_stage
from .sustainability import value


def _nearest(df: pd.DataFrame, cycle: int) -> pd.Series | None:
    if df.empty:
        return None
    return df.iloc[(df["cycle"] - cycle).abs().argmin()]


def assess_fleet(features: pd.DataFrame, soh_preds: pd.DataFrame, rul_preds: pd.DataFrame) -> pd.DataFrame:
    sp = soh_preds[["cell_id", "cycle", "soh_pred", "soh_lo", "soh_hi"]]
    df = features.merge(sp, on=["cell_id", "cycle"], how="left")
    for c in ("soh_pred", "soh_lo", "soh_hi"):
        df[c] = df.groupby("cell_id")[c].transform(lambda x: x.interpolate(limit_direction="both"))
    floor = rul_preds[np.isclose(rul_preds["threshold"], THRESHOLDS.second_life_floor)]

    rows = []
    for cid, g in df.groupby("cell_id", sort=False):
        g = g.reset_index(drop=True)
        ds = g["dataset"].iloc[0]
        floor_cycle = eol_cycle(g["soh_smooth"], g["cycle"], THRESHOLDS.second_life_floor)
        fc = floor[floor.cell_id == cid]
        has_ml = fc["rul_gbr"].notna().any() if not fc.empty else False
        for level in RETIREMENT_SOH_LEVELS:
            k = eol_cycle(g["soh_smooth"], g["cycle"], level)
            if k is None:
                continue
            row = g[g.cycle == k].iloc[0]
            # cycles left to the 60% floor: truth and prediction
            if floor_cycle is not None:
                c_true = max(floor_cycle - k, 0)
            else:
                c_true = None
            snap = _nearest(fc, k) if has_ml else None
            if level <= THRESHOLDS.second_life_floor:
                c_pred = c_lo = 0.0
            elif snap is not None and abs(snap["cycle"] - k) <= 10:
                c_pred, c_lo = float(snap["rul_gbr"]), float(snap["rul_gbr_lo"])
            else:
                c_pred = c_lo = None
            # use the cycle criterion only where both truth and prediction exist
            use_cycles = c_true is not None and c_pred is not None
            res_growth = float(row["resistance_growth"])
            a = assess(float(row["soh_pred"]), float(row["soh_lo"]), res_growth,
                       c_pred if use_cycles else None, c_lo if use_cycles else None)
            g_true, app_true, _ = grade(float(row["soh_smooth"]), res_growth,
                                        c_true if use_cycles else None)
            v = value(a.grade, float(row["soh_pred"]), ds)
            rows.append({
                "dataset": ds, "cell_id": cid, "retire_soh_level": level, "cycle": int(k),
                "is_retirement_point": np.isclose(level, THRESHOLDS.first_life_eol),
                "soh_true": float(row["soh_smooth"]), "soh_est": float(row["soh_pred"]),
                "soh_lo": float(row["soh_lo"]), "soh_hi": float(row["soh_hi"]),
                "resistance_growth": res_growth,
                "cycles_to_floor_true": c_true, "cycles_to_floor_pred": c_pred,
                "cycles_to_floor_lo": c_lo, "cycle_criterion_used": use_cycles,
                "grade_pred": a.grade, "grade_true": g_true, "grade_at_lower_bound": a.grade_at_lower_bound,
                "application": a.application, "application_true": app_true,
                "confidence": a.confidence, "recommendation": a.recommendation,
                "service_years": a.service_years, "stage": lifecycle_stage(float(row["soh_pred"])),
                **{f"{k2}": v2 for k2, v2 in v.items() if k2 != "usable_kwh_cell"},
                "co2_avoided_kg": v["co2_avoided_kg_cell"],
            })
    return pd.DataFrame(rows)


def summarise(a: pd.DataFrame) -> dict:
    def block(d: pd.DataFrame) -> dict:
        p = d["grade_pred"].map(GRADE_ORDER.index)
        t = d["grade_true"].map(GRADE_ORDER.index)
        wrong = d[p != t]
        conf = d[d.confidence == "high"]
        return {
            "decisions": int(len(d)),
            "agreement": float((p == t).mean()),
            "conservative_errors": int((p > t).sum()),   # predicted a lower grade than true
            "optimistic_errors": int((p < t).sum()),     # predicted a better grade than true
            "agreement_when_high_confidence": float((conf.grade_pred == conf.grade_true).mean()) if len(conf) else None,
            "low_confidence_share": float((d.confidence == "low").mean()),
            "errors_flagged_low_confidence": float((wrong.confidence == "low").mean()) if len(wrong) else None,
            "confusion": pd.crosstab(d.grade_true, d.grade_pred).reindex(
                index=GRADE_ORDER, columns=GRADE_ORDER, fill_value=0).to_dict(),
        }
    out = {"all": block(a)}
    for ds, d in a.groupby("dataset"):
        out[ds] = block(d)
    ret = a[a.is_retirement_point]
    out["at_80pct_retirement"] = {
        "cells": int(len(ret)),
        "grades": ret["grade_pred"].value_counts().to_dict(),
        "mean_service_years": float(ret["service_years"].dropna().mean()) if ret["service_years"].notna().any() else None,
        "co2_avoided_kg_per_pack": float(ret["co2_avoided_kg_pack"].mean()),
        "value_usd_per_pack": float(ret["value_usd_pack"].mean()),
    }
    calce = a[(a.dataset == "calce") & a.cycle_criterion_used & (a.retire_soh_level > THRESHOLDS.second_life_floor)]
    if len(calce):
        err = (calce.cycles_to_floor_pred - calce.cycles_to_floor_true).abs()
        out["second_life_cycles_mae_calce"] = float(err.mean())
    return out


def run(features, soh_preds, rul_preds, save: bool = True) -> dict:
    a = assess_fleet(features, soh_preds, rul_preds)
    s = summarise(a)
    if save:
        a.to_csv(RESULTS_DIR / "second_life_assessments.csv", index=False)
        (RESULTS_DIR / "second_life_summary.json").write_text(json.dumps(round_dict(s, 4), indent=2, default=int))
    return {"assessments": a, "summary": s}

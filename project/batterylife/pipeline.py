"""End-to-end pipeline: raw data -> features -> SOH -> RUL -> second life -> passports.

    python -m batterylife run              # full run (about 6 minutes)
    python -m batterylife run --fast       # reuse saved SOH/RUL results (seconds)
    python -m batterylife run --refresh    # re-parse raw data as well
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import pandas as pd

from . import __version__
from .config import DATASETS, PASSPORT_DIR, RESULTS_DIR, THRESHOLDS, ensure_dirs
from .data.registry import load_cycles, save_quality_report
from .features.indicators import FEATURES_CSV, build_features, correlation_table
from .lifecycle import second_life
from .models import rul, soh
from .passport import store
from .passport.issue import issue_all
from .passport.ledger import verify


def _step(n, name):
    print(f"[{n}/7] {name}")
    return time.time()


def run(refresh: bool = False, fast: bool = False) -> dict:
    ensure_dirs()
    t_all = time.time()

    _step(1, "Ingest cycle data")
    cycles = load_cycles(refresh=refresh)
    quality = save_quality_report(cycles)

    _step(2, "Clean data and build health indicators")
    feats = build_features(cycles)
    feats.to_csv(FEATURES_CSV, index=False)

    have_saved = (RESULTS_DIR / "soh_predictions.csv").exists() and (RESULTS_DIR / "rul_predictions.csv").exists()
    if fast and have_saved:
        _step(3, "SOH estimation (reusing saved results)")
        soh_preds = pd.read_csv(RESULTS_DIR / "soh_predictions.csv")
        soh_metrics = json.loads((RESULTS_DIR / "soh_metrics.json").read_text())
        _step(4, "RUL prediction (reusing saved results)")
        rul_preds = pd.read_csv(RESULTS_DIR / "rul_predictions.csv")
        rul_metrics = json.loads((RESULTS_DIR / "rul_metrics.json").read_text())
    else:
        _step(3, "SOH estimation: 5 models, leave-one-cell-out, conformal intervals")
        r = soh.run(feats)
        soh_preds, soh_metrics = r["predictions"], json.loads((RESULTS_DIR / "soh_metrics.json").read_text())
        _step(4, "RUL prediction: baselines + calibrated quantile GBR")
        r = rul.run(feats, soh_preds)
        rul_preds, rul_metrics = r["predictions"], json.loads((RESULTS_DIR / "rul_metrics.json").read_text())

    _step(5, "Second-life grading and value")
    sl = second_life.run(feats, soh_preds, rul_preds)

    _step(6, "Issue and verify Digital Battery Passports")
    reg = store.create_actors()
    store.save_registry(reg)
    models = {ds: soh_metrics[ds]["primary_model"] for ds in DATASETS}
    passports = issue_all(feats, soh_preds, rul_preds, sl["assessments"], reg, models)
    public_reg = store.load_registry()
    checks = {}
    for p in passports:
        store.save_passport(p)
        checks[p.passport_id] = verify(p, public_reg)["valid"]

    _step(7, "Write summary")
    summary = build_summary(feats, quality, soh_metrics, rul_metrics, sl["summary"], passports, checks)
    summary["runtime_s"] = round(time.time() - t_all, 1)
    (RESULTS_DIR / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(f"Done in {summary['runtime_s']} s. "
          f"{sum(checks.values())}/{len(checks)} passports valid. Results in {RESULTS_DIR}")
    return summary


def build_summary(feats, quality, soh_m, rul_m, sl_s, passports, checks) -> dict:
    cells = []
    for p in passports:
        g = feats[feats.cell_id == p.battery_id]
        secs = p.sections()
        soh_last = secs["state_of_health"]["latest_assessment"]
        cells.append({
            "cell_id": p.battery_id, "dataset": g["dataset"].iloc[0], "passport_id": p.passport_id,
            "cycles": int(len(g)), "soh_start": round(float(g["soh"].iloc[0]), 4),
            "soh_end": round(float(g["soh_smooth"].iloc[-1]), 4),
            "latest_soh_est": soh_last["soh"] if soh_last else None,
            "status": p.status(), "events": len(p.events), "passport_valid": checks[p.passport_id],
            "grade": (secs["lifecycle_decision"] or {}).get("grade"),
            "application": (secs["lifecycle_decision"] or {}).get("application"),
            "outliers_removed": int(g["is_outlier"].sum()),
        })
    return {
        "project": "AI-Based Battery Lifecycle Assessment and Second-Life Management Using Digital Battery Passports",
        "version": __version__,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "thresholds": {"first_life_eol": THRESHOLDS.first_life_eol,
                       "second_life_floor": THRESHOLDS.second_life_floor},
        "data": {"cells": len(cells), "cycles": int(len(feats)),
                 "outliers_removed": int(feats["is_outlier"].sum())},
        "correlations": correlation_table(feats).to_dict(),
        "soh": {ds: {"primary_model": soh_m[ds]["primary_model"],
                     "rmse": soh_m[ds]["summary"][soh_m[ds]["primary_model"]]["rmse"],
                     "mae": soh_m[ds]["summary"][soh_m[ds]["primary_model"]]["mae"],
                     "r2": soh_m[ds]["summary"][soh_m[ds]["primary_model"]]["r2"],
                     "coverage_95": soh_m[ds]["coverage_95"]} for ds in DATASETS},
        "rul": {ds: {"mae_cycles": rul_m[ds]["first_life"]["quantile_gbr"]["mae"],
                     "mean_life": rul_m[ds]["first_life"]["mean_life_to_threshold"],
                     "coverage_80": rul_m[ds]["first_life"]["quantile_gbr"]["coverage_cqr_80"]}
                for ds in DATASETS},
        "second_life": {"agreement": sl_s["all"]["agreement"],
                        "agreement_high_conf": sl_s["all"]["agreement_when_high_confidence"],
                        "decisions": sl_s["all"]["decisions"],
                        "second_life_cycles_mae_calce": sl_s.get("second_life_cycles_mae_calce"),
                        "at_80pct": sl_s["at_80pct_retirement"]},
        "passports": {"issued": len(passports), "valid": int(sum(checks.values())),
                      "events": int(sum(len(p.events) for p in passports)),
                      "folder": "results/passports"},
        "cells": cells,
        "data_quality": quality,
    }

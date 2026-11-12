"""Assess batteries from a user's own file.

Accepted input: a CSV with one row per charge-discharge cycle.

    required   cycle, and at least one of
               capacity_ah                      measured discharge capacity
               cc_charge_time_s, cv_charge_time_s, charge_v_rise_s, resistance_ohm
                                                charging signals (AI estimate, needs a known cell type)
    optional   cell_id (several batteries in one file), resistance_ohm, timestamp

For every battery the service returns its state of health, a trend forecast of
the cycles left to 80% and 60%, a second-life grade, and (optionally) a signed
Digital Battery Passport.

How health is obtained
    measured   capacity_ah / rated capacity, when capacity is in the file
    estimated  the project's SOH model for that cell type, from charging signals
If both are present, the measured value is used for grading and the estimate is
reported next to it, so the user can see how close the model is on their cell.
"""
from __future__ import annotations

import io
import re
import secrets
import warnings
from datetime import datetime, timedelta

import joblib
import numpy as np
import pandas as pd

from ..config import DATASETS, PROCESSED_DIR, RESULTS_DIR, THRESHOLDS
from ..features.cleaning import clean_capacity
from ..lifecycle.grading import assess, grade as grade_rule, lifecycle_stage
from ..lifecycle.sustainability import value
from ..models import soh as soh_model
from ..models.rul import fade_model_rul, linear_trend_rul
from ..passport import store
from ..passport.ledger import Passport, verify
from . import CTX, db

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 200_000
MAX_CELLS = 200
MIN_TREND_CYCLES = 10
CHECKPOINTS = 8
FEATURES = soh_model.FEATURES            # cc, cv, v-rise, resistance, cycle
ALIASES = {
    "cycle": ["cycle", "cycle_index", "cycle_number", "cycle_no", "n"],
    "capacity_ah": ["capacity_ah", "capacity", "discharge_capacity_ah", "discharge_capacity", "qd", "cap_ah"],
    "cell_id": ["cell_id", "cell", "battery_id", "battery", "id"],
    "resistance_ohm": ["resistance_ohm", "resistance", "ir", "internal_resistance_ohm", "r_ohm"],
    "cc_charge_time_s": ["cc_charge_time_s", "cc_time_s", "cc_time"],
    "cv_charge_time_s": ["cv_charge_time_s", "cv_time_s", "cv_time"],
    "charge_v_rise_s": ["charge_v_rise_s", "v_rise_s", "voltage_rise_s"],
    "timestamp": ["timestamp", "date", "datetime", "time"],
}
PROFILES = {"nasa": "18650 cylindrical, 2.0 Ah (like NASA PCoE cells)",
            "calce": "LCO prismatic, 1.1 Ah (like CALCE CS2 cells)",
            "other": "Any other Li-ion cell (measured capacity only)"}


class UploadError(ValueError):
    """The file cannot be analysed; the message is safe to show to the user."""


# ------------------------------------------------------------------ parsing
def parse_csv(raw: bytes) -> pd.DataFrame:
    if len(raw) > MAX_BYTES:
        raise UploadError(f"File is larger than {MAX_BYTES // 1024 // 1024} MB.")
    try:
        df = pd.read_csv(io.BytesIO(raw), sep=None, engine="python", comment="#")
    except Exception:
        raise UploadError("Could not read the file as CSV. Save it as comma-separated text with a header row.")
    if df.empty:
        raise UploadError("The file has a header but no data rows.")
    if len(df) > MAX_ROWS:
        raise UploadError(f"File has more than {MAX_ROWS:,} rows.")
    lower = {str(c).strip().lower().replace(" ", "_"): c for c in df.columns}
    rename = {}
    for std, names in ALIASES.items():
        hit = next((lower[n] for n in names if n in lower), None)
        if hit is not None:
            rename[hit] = std
    df = df.rename(columns=rename)
    if "cycle" not in df:
        raise UploadError("No 'cycle' column found. Columns seen: " + ", ".join(map(str, list(lower)[:12])))
    has_features = all(c in df for c in ("cc_charge_time_s", "cv_charge_time_s", "charge_v_rise_s", "resistance_ohm"))
    if "capacity_ah" not in df and not has_features:
        raise UploadError("Need a 'capacity_ah' column, or all four charging signals "
                          "(cc_charge_time_s, cv_charge_time_s, charge_v_rise_s, resistance_ohm).")
    if "cell_id" not in df:
        df["cell_id"] = "CELL-1"
    df["cell_id"] = df["cell_id"].astype(str).str.strip()
    for c in [c for c in ALIASES if c in df and c not in ("cell_id", "timestamp")]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    if df["cell_id"].nunique() > MAX_CELLS:
        raise UploadError(f"More than {MAX_CELLS} batteries in one file.")
    keep = [c for c in ALIASES if c in df]
    return df[keep]


# ------------------------------------------------------------------ SOH model for a known cell type
_MODELS: dict = {}


def load_soh_model(profile: str) -> dict:
    """Saved model for this cell type; retrained from the processed data if the file is missing."""
    if profile in _MODELS:
        return _MODELS[profile]
    f = RESULTS_DIR / "models" / f"soh_{profile}.joblib"
    bundle = None
    if f.exists():
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                bundle = joblib.load(f)
        except Exception:
            bundle = None
    if bundle is None:
        import json
        feats = pd.read_csv(PROCESSED_DIR / "features.csv")
        d = feats[(feats.dataset == profile) & ~feats.is_outlier]
        m = json.loads((RESULTS_DIR / "soh_metrics.json").read_text())[profile]
        bundle = {"model": soh_model.fit(m["primary_model"], d[FEATURES], d["soh"]), "name": m["primary_model"],
                  "features": FEATURES, "halfwidth": float(np.median(list(m["conformal_halfwidth"].values())))}
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            joblib.dump(bundle, f)
        except OSError:
            pass
    _MODELS[profile] = bundle
    return bundle


# ------------------------------------------------------------------ one battery
def _round(x, nd=4):
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


def analyse_cell(g: pd.DataFrame, rated_ah: float, profile: str) -> dict:
    cid = str(g["cell_id"].iloc[0])
    g = g.dropna(subset=["cycle"]).sort_values("cycle").drop_duplicates("cycle", keep="last").reset_index(drop=True)
    notes: list[str] = []
    has_cap = "capacity_ah" in g and g["capacity_ah"].notna().sum() >= 1
    feats_ok = all(c in g for c in FEATURES if c != "cycle")
    use_model = feats_ok and profile in DATASETS
    if has_cap:
        g = g[g["capacity_ah"] > 0].reset_index(drop=True)
    if g.empty:
        raise UploadError("no usable rows (cycle and capacity must be numbers above zero)")

    est = lo = hi = None
    model_name = None
    if use_model:
        X = g[FEATURES].copy()
        ok = X.notna().all(axis=1)
        if ok.sum() >= 1:
            b = load_soh_model(profile)
            model_name = b["name"]
            pred = pd.Series(np.nan, index=g.index)
            pred[ok] = b["model"].predict(X[ok])
            pred = pred.interpolate(limit_direction="both")
            est, lo, hi = pred, pred - b["halfwidth"], pred + b["halfwidth"]
        else:
            use_model = False
            notes.append("Charging-signal columns are empty, so no AI estimate was made.")
    elif feats_ok and profile not in DATASETS:
        notes.append("Charging signals were ignored: the AI model is only trained for the two listed cell types.")

    if has_cap:
        g["soh"] = g["capacity_ah"] / rated_ah
        if g["soh"].max() > 1.3:
            raise UploadError(f"capacity is up to {g['capacity_ah'].max():.2f} Ah but rated capacity is {rated_ah} Ah; "
                              "check the rated capacity")
        flags = clean_capacity(g) if len(g) >= 11 else pd.Series(False, index=g.index)
        clean = g["soh"].mask(flags).interpolate(limit_direction="both")
        smooth = clean.rolling(9, center=True, min_periods=1).median()
        resid = (clean - smooth).to_numpy()
        noise = 1.4826 * float(np.median(np.abs(resid - np.median(resid)))) if len(g) >= 5 else 0.0
        half = max(0.01, 1.96 * noise)
        method = "measured capacity / rated capacity"
        source = "measured"
        outliers = int(flags.sum())
        if outliers:
            notes.append(f"{outliers} cycle(s) with a sudden capacity drop were treated as interrupted tests.")
    else:
        if not use_model:
            raise UploadError("no capacity column, and charging signals can only be used for the NASA-like or "
                              "CALCE-like cell types")
        smooth = est.rolling(9, center=True, min_periods=1).median()
        half = float(load_soh_model(profile)["halfwidth"])
        method = f"{model_name} model on charging signals (no discharge test needed)"
        source = "estimated"
        outliers = 0
        g["soh"] = np.nan

    cycles = g["cycle"].to_numpy(float)
    hist = smooth.to_numpy(float)
    soh_now = float(hist[-1])
    soh_lo = soh_now - half

    rg = None
    if "resistance_ohm" in g and g["resistance_ohm"].notna().sum() >= 2:
        r = g["resistance_ohm"].dropna()
        base = float(r.iloc[:5].median())
        if base > 0:
            rg = float(r.iloc[-5:].median() / base)

    # trend forecast: two methods, the spread is the uncertainty
    rul = {}
    horizon = int(min(max(3 * cycles[-1], 500), 5000))
    if len(g) >= MIN_TREND_CYCLES and np.ptp(cycles) > 0:
        window = max(5, len(g) // 6)
        unit = max(cycles[-1], 1.0)
        for name, thr in (("to_80", THRESHOLDS.first_life_eol), ("to_60", THRESHOLDS.second_life_floor)):
            lin = linear_trend_rul(cycles, hist, thr, window, horizon)
            try:
                fade = fade_model_rul(cycles, hist, thr, unit, horizon)
            except Exception:
                fade = lin
            a, b = sorted((lin, fade))
            rul[name] = {"cycles": _round(fade, 0), "lo": _round(a, 0), "hi": _round(b, 0),
                         "beyond_horizon": bool(a >= horizon), "linear": _round(lin, 0), "fade_model": _round(fade, 0)}
        if rul["to_60"]["beyond_horizon"]:
            notes.append(f"No clear downward trend yet: the cell is forecast to stay above 60% for at least {horizon} more cycles.")
    else:
        notes.append(f"Fewer than {MIN_TREND_CYCLES} cycles, so no remaining-life forecast was made.")
    left = rul.get("to_60", {}).get("cycles")
    left_lo = rul.get("to_60", {}).get("lo")

    a = assess(soh_now, soh_lo, rg, left, left_lo)
    confidence, recommendation = a.confidence, a.recommendation
    if left is not None:
        g_hi = grade_rule(soh_now, rg, rul["to_60"]["hi"])[0]
        if g_hi != a.grade:
            confidence = "low"
            recommendation = (f"Graded {a.grade} on the cautious forecast, but the two forecasts disagree "
                              f"({rul['to_60']['lo']:.0f} to {rul['to_60']['hi']:.0f} cycles left, which would be grade {g_hi}): "
                              "confirm with a capacity test before deciding")
    val = value(a.grade, soh_now, "nasa")       # pack-level figures do not depend on the cell type
    agree = None
    if has_cap and est is not None:
        import json
        m = json.loads((RESULTS_DIR / "soh_metrics.json").read_text())[profile]
        agree = {"mae": _round(float(np.mean(np.abs(est - g["soh"]))), 4), "model": model_name,
                 "estimate_now": _round(float(est.iloc[-1])), "halfwidth": _round(float(load_soh_model(profile)["halfwidth"])),
                 "rmse_on_unseen_cells": m["summary"][m["primary_model"]]["rmse"],
                 "in_training_data": cid in DATASETS[profile].cells}
        if agree["in_training_data"]:
            notes.append("This cell is part of the model's training data, so the gap between the AI estimate and "
                         "the measured value is smaller here than it would be on a new cell.")

    step = max(1, len(g) // 300)
    idx = sorted(set(range(0, len(g), step)) | {len(g) - 1})
    series = {"cycle": [int(c) for c in cycles[idx]],
              "soh": [_round(v) for v in g["soh"].to_numpy(float)[idx]],
              "soh_smooth": [_round(v) for v in hist[idx]],
              "soh_est": [_round(v) for v in est.to_numpy(float)[idx]] if est is not None else None}
    return {
        "cell_id": cid, "cycles": int(len(g)), "last_cycle": int(cycles[-1]), "rated_capacity_ah": rated_ah,
        "soh": _round(soh_now), "soh_lo": _round(soh_lo), "soh_hi": _round(soh_now + half),
        "soh_source": source, "soh_method": method, "stage": lifecycle_stage(soh_now),
        "resistance_growth": _round(rg, 3), "rul": rul, "model_check": agree,
        "grade": a.grade, "application": a.application, "confidence": confidence,
        "recommendation": recommendation, "reasons": a.reasons, "grade_at_lower_bound": a.grade_at_lower_bound,
        "service_years": a.service_years,
        "value": {k: val[k] for k in ("route", "usable_kwh_pack", "co2_avoided_kg_pack", "value_usd_pack")},
        "notes": notes, "series": series,
        "_frame": g.assign(soh_smooth=hist, soh_pred=est if est is not None else np.nan,
                           soh_lo=lo if lo is not None else np.nan, soh_hi=hi if hi is not None else np.nan,
                           is_outlier=False),
    }


# ------------------------------------------------------------------ passport for an uploaded battery
def issue_passport(res: dict, upload_id: str, filename: str, profile: str, reg) -> Passport:
    cid = re.sub(r"[^A-Za-z0-9_.-]", "_", res["cell_id"])[:40]
    p = Passport(f"DBP-UP-{upload_id}-{cid}", res["cell_id"])
    sign = lambda role: store.signer(reg, role, CTX.keys, CTX.actors_file)   # noqa: E731
    t0 = datetime.fromisoformat(db.now())
    ts = lambda k: (t0 + timedelta(seconds=k)).isoformat()                    # noqa: E731
    info = DATASETS.get(profile)
    p.append(sign("manufacturer"), "MANUFACTURED", {
        "model": res["cell_id"], "chemistry": info.chemistry if info else "Li-ion (declared by uploader)",
        "form_factor": info.form_factor if info else "not declared", "rated_capacity_ah": res["rated_capacity_ah"],
        "nominal_voltage_v": 3.7, "manufacturer": "declared by uploader", "manufacture_date": t0.date().isoformat(),
        "data_source": f"user upload: {filename}"}, ts(0))
    f = res["_frame"]
    picks = sorted(set(np.linspace(0, len(f) - 1, min(CHECKPOINTS, len(f))).round().astype(int)))
    measured = res["soh_source"] == "measured"
    half = res["soh"] - res["soh_lo"]
    base_r = f["resistance_ohm"].dropna().iloc[:5].median() if "resistance_ohm" in f and f["resistance_ohm"].notna().any() else None
    k = 1
    for i in picks:
        row = f.iloc[i]
        s = float(row["soh_smooth"])
        rg = float(row["resistance_ohm"] / base_r) if base_r and pd.notna(row.get("resistance_ohm")) else None
        p.append(sign("bms" if measured else "assessor"), "SOH_ASSESSMENT", {
            "cycle": int(row["cycle"]), "soh": round(s, 4), "soh_lo": round(s - half, 4), "soh_hi": round(s + half, 4),
            "resistance_growth": round(rg, 3) if rg else None, "method": res["soh_method"]}, ts(k))
        k += 1
    r60 = res["rul"].get("to_60")
    if r60:
        p.append(sign("assessor"), "RUL_PREDICTION", {
            "cycle": res["last_cycle"], "threshold": THRESHOLDS.second_life_floor, "rul_cycles": r60["cycles"],
            "rul_lo": r60["lo"], "rul_hi": r60["hi"],
            "method": "trend extrapolation (fade model and linear trend; range = spread of the two)"}, ts(k))
        k += 1
    p.append(sign("assessor"), "SECOND_LIFE_GRADING", {
        "cycle": res["last_cycle"], "grade": res["grade"], "application": res["application"],
        "confidence": res["confidence"], "recommendation": res["recommendation"],
        "service_years": res["service_years"]}, ts(k))
    return p


# ------------------------------------------------------------------ whole upload
GRADE_RANK = {"A": 0, "B": 1, "C": 2, "D": 3}


def analyse_only(raw: bytes, filename: str, rated_ah: float, profile: str = "other") -> dict:
    """Same result as analyse_upload, but nothing is stored and no passport is issued."""
    df = parse_csv(raw)
    results, failed = [], []
    for cid, g in df.groupby("cell_id", sort=False):
        try:
            r = analyse_cell(g, float(rated_ah), profile)
            r.pop("_frame")
            results.append(r)
        except UploadError as e:
            failed.append({"cell_id": str(cid), "problem": str(e)})
    if not results:
        raise UploadError("No battery in the file could be analysed.")
    results.sort(key=lambda r: (GRADE_RANK[r["grade"]], -r["soh"]))
    for k, r in enumerate(results, 1):
        r["rank"] = k
    return {"upload_id": "stored sample result", "filename": filename, "created_at": db.now(), "profile": profile,
            "rated_capacity_ah": float(rated_ah), "batteries": len(results), "rows": int(len(df)),
            "grades": {g: sum(r["grade"] == g for r in results) for g in "ABCD"},
            "low_confidence": sum(r["confidence"] == "low" for r in results),
            "mean_soh": _round(float(np.mean([r["soh"] for r in results]))), "results": results, "failed": failed}


def analyse_upload(raw: bytes, filename: str, rated_ah: float, profile: str = "other",
                   issue_passports: bool = True, user: dict | None = None) -> dict:
    if profile not in PROFILES:
        raise UploadError(f"Unknown cell type '{profile}'. Use one of: {', '.join(PROFILES)}.")
    if not (isinstance(rated_ah, (int, float)) and 0.01 <= rated_ah <= 1000):
        raise UploadError("Rated capacity must be a number of amp-hours between 0.01 and 1000.")
    df = parse_csv(raw)
    upload_id = secrets.token_hex(3).upper()
    results, failed = [], []
    for cid, g in df.groupby("cell_id", sort=False):
        try:
            results.append(analyse_cell(g, float(rated_ah), profile))
        except UploadError as e:
            failed.append({"cell_id": str(cid), "problem": str(e)})
    if not results:
        raise UploadError("No battery in the file could be analysed: " + failed[0]["problem"] + ".")
    results.sort(key=lambda r: (GRADE_RANK[r["grade"]], -r["soh"]))

    conn = db.connect()
    try:
        username = (user or {}).get("username", "anonymous")
        stamp = db.now()
        reg = store.signing_registry(CTX.keys, CTX.actors_file) if issue_passports else None
        conn.execute("INSERT INTO uploads VALUES (?,?,?,?,?,?,?)",
                     (upload_id, filename[:200], username, stamp, len(results), len(df), "{}"))
        for rank, r in enumerate(results, 1):
            r["rank"] = rank
            f = r.pop("_frame")
            dbid = f"UP-{upload_id}-{r['cell_id']}"
            r["db_cell_id"] = dbid
            conn.execute("INSERT INTO cells VALUES (?,?,?,?,?,?,?,?,?)",
                         (dbid, "upload", "upload", r["rated_capacity_ah"], r["cycles"],
                          float(f["soh_smooth"].iloc[0]), r["soh"], upload_id, stamp))
            get = lambda c: f[c] if c in f else pd.Series(np.nan, index=f.index)   # noqa: E731
            tab = pd.DataFrame({
                "cell_id": dbid, "cycle": f["cycle"].astype(int), "timestamp": get("timestamp").astype(object),
                "capacity_ah": get("capacity_ah"), "soh": f["soh"], "soh_smooth": f["soh_smooth"], "is_outlier": 0,
                "cc": get("cc_charge_time_s"), "cv": get("cv_charge_time_s"), "vr": get("charge_v_rise_s"),
                "r": get("resistance_ohm"), "rg": np.nan, "soh_pred": f["soh_pred"], "soh_lo": f["soh_lo"],
                "soh_hi": f["soh_hi"]})
            tab = tab.astype(object).where(pd.notna(tab), None)
            conn.executemany("INSERT INTO cycles VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             tab.itertuples(index=False, name=None))
            conn.execute(
                "INSERT INTO assessments (cell_id, source, cycle, soh, soh_lo, resistance_growth, cycles_left, grade,"
                " application, confidence, recommendation, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (dbid, "upload", r["last_cycle"], r["soh"], r["soh_lo"], r["resistance_growth"],
                 (r["rul"].get("to_60") or {}).get("cycles"), r["grade"], r["application"], r["confidence"],
                 r["recommendation"], stamp))
            if issue_passports:
                r["_frame"] = f
                p = issue_passport(r, upload_id, filename, profile, reg)
                r.pop("_frame")
                db.save_passport(conn, p)
                r["passport_id"] = p.passport_id
        if issue_passports:
            db.save_actors(conn, reg)
            good = db.registry(conn)
            for r in results:
                r["passport_valid"] = verify(db.load_passport(conn, r["passport_id"]), good)["valid"]
        counts = {g: sum(r["grade"] == g for r in results) for g in "ABCD"}
        out = {"upload_id": upload_id, "filename": filename, "created_at": stamp, "profile": profile,
               "rated_capacity_ah": float(rated_ah), "batteries": len(results), "rows": int(len(df)),
               "grades": counts, "low_confidence": sum(r["confidence"] == "low" for r in results),
               "mean_soh": _round(float(np.mean([r["soh"] for r in results]))),
               "results": results, "failed": failed}
        import json
        conn.execute("UPDATE uploads SET result = ? WHERE upload_id = ?", (json.dumps(out), upload_id))
        db.audit(conn, user, "upload.create", upload_id,
                 f"{filename}: {len(results)} batteries, grades {counts}")
        conn.commit()
        return out
    finally:
        conn.close()

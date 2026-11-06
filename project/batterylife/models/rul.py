"""Remaining useful life (RUL): cycles left until SOH reaches a threshold.

At every prediction cycle k the predictor sees only what a battery management
system would have at that moment: the out-of-sample SOH estimates for cycles
1..k (Sprint 4, never measured capacity) and the charge-phase signals.

Two predictors are compared:

1. Empirical fade model (physics-inspired curve fit, per cell, no training data)
       soh(k) = p0 - p1*k - p2*(exp(p3*k) - 1)
   linear loss (SEI growth) plus an accelerating term (lithium plating, the
   "knee"). It is fitted on the estimated history and extrapolated.

2. Quantile Gradient Boosting (data-driven, trained on the other cells)
   predicts the 10%, 50% and 90% quantiles of RUL from the current state:
   smoothed SOH estimate, fade rate, charge signals, resistance and cycle count.

Ground truth: the first cycle where the measured, smoothed SOH falls to the
threshold.
"""
from __future__ import annotations

import json
import warnings

import numpy as np
import pandas as pd
from scipy.optimize import OptimizeWarning, curve_fit
from sklearn.ensemble import GradientBoostingRegressor

from ..config import RESULTS_DIR, SEED, THRESHOLDS
from .evaluation import interval_coverage, regression_metrics, round_dict

# dataset-specific scales: how many past cycles define "recent" behaviour,
# snapshot spacing, and cycle units for the curve fit
SCALE = {"nasa": {"window": 15, "step": 1, "unit": 100.0},
         "calce": {"window": 60, "step": 5, "unit": 1000.0}}
RUL_FEATURES = ["soh_est", "fade_rate", "fade_accel", "cc_charge_time_s", "charge_v_rise_s",
                "resistance_ohm", "cycle"]
QUANTILES = (0.1, 0.5, 0.9)


def eol_cycle(soh_smooth: pd.Series, cycles: pd.Series, threshold: float) -> int | None:
    below = np.flatnonzero(soh_smooth.to_numpy() <= threshold)
    return int(cycles.iloc[below[0]]) if len(below) else None


# ------------------------------------------------------------------ fade model
def fade_curve(k, p0, p1, p2, p3):
    return p0 - p1 * k - p2 * (np.exp(p3 * k) - 1.0)


def fit_fade(k: np.ndarray, soh: np.ndarray):
    p0 = [soh[:5].mean(), max((soh[0] - soh[-1]) / max(k[-1], 1e-6), 1e-4), 1e-3, 1.0]
    bounds = ([0.3, 0.0, 0.0, 0.0], [1.3, 5.0, 2.0, 8.0])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", OptimizeWarning)
        warnings.simplefilter("ignore", RuntimeWarning)
        params, _ = curve_fit(fade_curve, k, soh, p0=p0, bounds=bounds, maxfev=20000)
    return params


def fade_model_rul(cycles: np.ndarray, soh_hist: np.ndarray, threshold: float,
                   unit: float, horizon: int) -> float:
    """Fit on history, extrapolate, return cycles until threshold (capped at horizon)."""
    k = cycles / unit
    try:
        params = fit_fade(k, soh_hist)
    except (RuntimeError, ValueError):
        # fallback: linear trend over the last third of the history
        n = max(len(k) // 3, 5)
        slope, icpt = np.polyfit(k[-n:], soh_hist[-n:], 1)
        params = None
    now = cycles[-1]
    future = np.arange(now + 1, now + horizon + 1)
    f = fade_curve(future / unit, *params) if params is not None else icpt + slope * future / unit
    hit = np.flatnonzero(f <= threshold)
    if soh_hist[-1] <= threshold:
        return 0.0
    return float(future[hit[0]] - now) if len(hit) else float(horizon)


# ------------------------------------------------------------------ snapshots
def causal_smooth(x: pd.Series, n: int = 9) -> pd.Series:
    return x.rolling(n, min_periods=1).median()


def snapshots(cell: pd.DataFrame, threshold: float, dataset: str, horizon: int) -> pd.DataFrame:
    """One row per prediction cycle k before the cell reaches the threshold."""
    sc = SCALE[dataset]
    g = cell.reset_index(drop=True)
    eol = eol_cycle(g["soh_smooth"], g["cycle"], threshold)
    if eol is None:
        return pd.DataFrame()
    est = causal_smooth(g["soh_pred"])
    w = sc["window"]
    rows = []
    start = max(w + 5, int(0.1 * eol))
    for i in range(start, len(g), sc["step"]):
        k = int(g["cycle"].iloc[i])
        if k >= eol:
            break
        hist_c, hist_s = g["cycle"].iloc[: i + 1].to_numpy(float), est.iloc[: i + 1].to_numpy(float)
        rate = (est.iloc[i - w] - est.iloc[i]) / w
        prev = (est.iloc[max(i - 2 * w, 0)] - est.iloc[i - w]) / w
        rows.append({
            "dataset": dataset, "cell_id": g["cell_id"].iloc[0], "cycle": k,
            "threshold": threshold, "eol_cycle": eol, "rul_true": eol - k,
            "life_fraction": k / eol,
            "soh_est": est.iloc[i], "fade_rate": rate * 1000, "fade_accel": (rate - prev) * 1000,
            "cc_charge_time_s": g["cc_charge_time_s"].iloc[i],
            "charge_v_rise_s": g["charge_v_rise_s"].iloc[i],
            "resistance_ohm": g["resistance_ohm"].iloc[i],
            "rul_fade": fade_model_rul(hist_c, hist_s, threshold, sc["unit"], horizon),
            "rul_linear": linear_trend_rul(hist_c, hist_s, threshold, w, horizon),
        })
    return pd.DataFrame(rows)


def quantile_models():
    return {q: GradientBoostingRegressor(loss="quantile", alpha=q, n_estimators=300, max_depth=3,
                                         learning_rate=0.05, subsample=0.8, min_samples_leaf=5,
                                         random_state=SEED) for q in QUANTILES}


def _fit_predict_quantiles(tr: pd.DataFrame, te: pd.DataFrame) -> np.ndarray:
    out = []
    for _, m in quantile_models().items():
        m.fit(tr[RUL_FEATURES], tr["rul_true"])
        out.append(m.predict(te[RUL_FEATURES]))
    q = np.sort(np.vstack(out), axis=0)          # enforce lo <= mid <= hi
    return np.maximum(q, 0)


def loco_quantile(snaps: pd.DataFrame, target_coverage: float = 0.8) -> pd.DataFrame:
    """LOCO quantile GBR with conformalised quantile regression (CQR).

    Raw quantile bands from 3 training cells are far too narrow. For each held-out
    cell, inner LOCO on the training cells gives conformity scores
    E = max(lo - y, y - hi); the band is widened by the target quantile of E.
    """
    snaps = snaps.copy()
    for cell in snaps["cell_id"].unique():
        tr, te = snaps[snaps.cell_id != cell], snaps[snaps.cell_id == cell]
        if tr.empty:
            continue
        q = _fit_predict_quantiles(tr, te)
        scores = []
        for inner in tr["cell_id"].unique():
            itr, iva = tr[tr.cell_id != inner], tr[tr.cell_id == inner]
            iq = _fit_predict_quantiles(itr, iva)
            y = iva["rul_true"].to_numpy()
            scores.append(np.maximum(iq[0] - y, y - iq[2]))
        widen = float(np.quantile(np.concatenate(scores), target_coverage))
        snaps.loc[te.index, "rul_gbr"] = q[1]
        snaps.loc[te.index, "rul_gbr_lo_raw"] = q[0]
        snaps.loc[te.index, "rul_gbr_hi_raw"] = q[2]
        snaps.loc[te.index, "rul_gbr_lo"] = np.maximum(q[0] - widen, 0)
        snaps.loc[te.index, "rul_gbr_hi"] = q[2] + widen
    return snaps


def linear_trend_rul(cycles: np.ndarray, soh_hist: np.ndarray, threshold: float,
                     window: int, horizon: int) -> float:
    """Baseline: straight line through the recent estimated SOH history."""
    n = min(len(cycles), 2 * window)
    slope, icpt = np.polyfit(cycles[-n:], soh_hist[-n:], 1)
    now_soh = icpt + slope * cycles[-1]
    if now_soh <= threshold:
        return 0.0
    if slope >= 0:
        return float(horizon)
    return float(min((threshold - now_soh) / slope, horizon))


def _checkpoint_errors(s: pd.DataFrame, col: str) -> dict:
    out = {}
    for frac in (0.25, 0.5, 0.75):
        errs = []
        for _, g in s.groupby("cell_id"):
            row = g.iloc[(g["life_fraction"] - frac).abs().argmin()]
            errs.append(abs(row[col] - row["rul_true"]))
        out[f"{int(frac * 100)}pct_life_mae"] = float(np.mean(errs))
    return out


def evaluate(s: pd.DataFrame) -> dict:
    out = {}
    for method, col in (("linear_trend", "rul_linear"), ("fade_model", "rul_fade"),
                        ("quantile_gbr", "rul_gbr")):
        if col not in s or s[col].isna().all():
            continue
        m = regression_metrics(s["rul_true"], s[col])
        m.update(_checkpoint_errors(s, col))
        m["per_cell_mae"] = {c: float(np.mean(np.abs(g[col] - g["rul_true"])))
                             for c, g in s.groupby("cell_id")}
        if method == "quantile_gbr":
            m["coverage_raw_10_90"] = interval_coverage(s["rul_true"], s["rul_gbr_lo_raw"],
                                                        s["rul_gbr_hi_raw"])
            m["coverage_cqr_80"] = interval_coverage(s["rul_true"], s["rul_gbr_lo"], s["rul_gbr_hi"])
            m["mean_band_width"] = float((s["rul_gbr_hi"] - s["rul_gbr_lo"]).mean())
        out[method] = m
    out["mean_life_to_threshold"] = float(s.groupby("cell_id")["eol_cycle"].first().mean())
    return out


def run(features_df: pd.DataFrame, soh_preds: pd.DataFrame, save: bool = True) -> dict:
    df = features_df.merge(soh_preds[["cell_id", "cycle", "soh_pred"]], on=["cell_id", "cycle"], how="left")
    df["soh_pred"] = df.groupby("cell_id")["soh_pred"].transform(
        lambda x: x.interpolate(limit_direction="both"))
    results, frames = {}, []
    for ds, horizon in (("nasa", 400), ("calce", 1500)):
        d = df[df.dataset == ds]
        results[ds] = {}
        for thr, label in ((THRESHOLDS.first_life_eol, "first_life"),
                           (THRESHOLDS.second_life_floor, "to_second_life_floor")):
            print(f"  RUL {ds} -> {thr:.0%} SOH ...")
            snaps = pd.concat([snapshots(g, thr, ds, horizon) for _, g in d.groupby("cell_id")],
                              ignore_index=True)
            if snaps.empty:
                continue
            n_cells = snaps["cell_id"].nunique()
            if n_cells >= 3:
                snaps = loco_quantile(snaps)
            else:
                for c in ("rul_gbr", "rul_gbr_lo", "rul_gbr_hi", "rul_gbr_lo_raw", "rul_gbr_hi_raw"):
                    snaps[c] = np.nan
            res = evaluate(snaps)
            res["cells_reaching_threshold"] = n_cells
            results[ds][label] = res
            frames.append(snaps)
    preds = pd.concat(frames, ignore_index=True)
    if save:
        preds.to_csv(RESULTS_DIR / "rul_predictions.csv", index=False)
        (RESULTS_DIR / "rul_metrics.json").write_text(json.dumps(round_dict(results, 3), indent=2))
    return {"metrics": results, "predictions": preds}

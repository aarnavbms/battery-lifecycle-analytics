"""State-of-health estimation from charge-phase health indicators.

Validation is leave-one-cell-out (LOCO) inside each dataset: the model never sees
any cycle of the cell it is scored on. Every cycle therefore gets an honest,
out-of-sample SOH estimate, which downstream RUL, grading and passport stages use.

Uncertainty: split-conformal intervals. For each held-out cell, the primary model
is cross-validated (LOCO) on the *training* cells only; the 95th percentile of
those absolute residuals becomes the half-width of the interval. No information
from the held-out cell is used, so the reported coverage is a fair test.
"""
from __future__ import annotations

import json
import warnings

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.exceptions import ConvergenceWarning
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, RBF, WhiteKernel
from sklearn.linear_model import Ridge
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from ..config import RESULTS_DIR, SEED
from .evaluation import interval_coverage, regression_metrics, round_dict

FEATURE_SETS = {
    # a full CC-CV charge is observed
    "full": ["cc_charge_time_s", "cv_charge_time_s", "charge_v_rise_s", "resistance_ohm", "cycle"],
    # charging may start at any state of charge below 3.9 V: no CC-duration feature
    "partial": ["cv_charge_time_s", "charge_v_rise_s", "resistance_ohm", "cycle"],
}
FEATURES = FEATURE_SETS["full"]
GP_MAX_TRAIN = 700
CONFORMAL_Q = 0.95
MODEL_NAMES = ["Ridge", "Random Forest", "Gradient Boosting", "MLP", "Gaussian Process"]


def make_model(name: str, n_features: int):
    if name == "Ridge":
        return make_pipeline(StandardScaler(), Ridge(alpha=1.0))
    if name == "Random Forest":
        return RandomForestRegressor(n_estimators=300, min_samples_leaf=3, random_state=SEED, n_jobs=-1)
    if name == "Gradient Boosting":
        return GradientBoostingRegressor(n_estimators=400, max_depth=3, learning_rate=0.05,
                                         subsample=0.8, random_state=SEED)
    if name == "MLP":
        return make_pipeline(StandardScaler(), MLPRegressor(
            hidden_layer_sizes=(64, 32), alpha=1e-3, learning_rate_init=3e-3, max_iter=2000,
            early_stopping=True, random_state=SEED))
    if name == "Gaussian Process":
        kernel = ConstantKernel(0.1) * RBF(np.ones(n_features), (1e-2, 1e3)) + WhiteKernel(1e-4, (1e-7, 1e-1))
        return make_pipeline(StandardScaler(), GaussianProcessRegressor(
            kernel=kernel, normalize_y=True, n_restarts_optimizer=1, random_state=SEED))
    raise KeyError(name)


def fit(name: str, X: pd.DataFrame, y: pd.Series):
    if name == "Gaussian Process" and len(X) > GP_MAX_TRAIN:
        idx = np.linspace(0, len(X) - 1, GP_MAX_TRAIN).round().astype(int)
        X, y = X.iloc[idx], y.iloc[idx]
    model = make_model(name, X.shape[1])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        model.fit(X, y)
    return model


def _valid(df: pd.DataFrame) -> pd.DataFrame:
    return df[~df["is_outlier"]].reset_index(drop=True)


def loco_predictions(df: pd.DataFrame, features: list[str], names=MODEL_NAMES):
    df = _valid(df)
    preds = df[["dataset", "cell_id", "cycle", "soh"]].copy()
    importance = []
    for cell in df["cell_id"].unique():
        tr, te = df[df.cell_id != cell], df[df.cell_id == cell]
        for name in names:
            m = fit(name, tr[features], tr["soh"])
            preds.loc[te.index, f"pred_{name}"] = m.predict(te[features])
            if name == "Gradient Boosting":
                importance.append(m.feature_importances_)
    imp = dict(zip(features, np.mean(importance, axis=0).round(4).tolist())) if importance else {}
    return preds, imp


def conformal_halfwidths(df: pd.DataFrame, features: list[str], name: str) -> dict:
    """95% residual quantile per held-out cell, from LOCO on the other cells only."""
    df = _valid(df)
    out = {}
    for cell in df["cell_id"].unique():
        train = df[df.cell_id != cell]
        res = []
        for inner in train["cell_id"].unique():
            tr, va = train[train.cell_id != inner], train[train.cell_id == inner]
            m = fit(name, tr[features], tr["soh"])
            res.append(np.abs(m.predict(va[features]) - va["soh"].to_numpy()))
        out[cell] = float(np.quantile(np.concatenate(res), CONFORMAL_Q))
    return out


def summarise(preds: pd.DataFrame) -> dict:
    names = [c[5:] for c in preds.columns if c.startswith("pred_")]
    out = {"summary": {n: regression_metrics(preds["soh"], preds[f"pred_{n}"]) for n in names},
           "per_cell": {}}
    for cid, g in preds.groupby("cell_id"):
        out["per_cell"][cid] = {n: regression_metrics(g["soh"], g[f"pred_{n}"]) for n in names}
    return out


def run(features_df: pd.DataFrame, save: bool = True) -> dict:
    results, all_preds = {}, []
    for ds in ("nasa", "calce"):
        d = features_df[features_df.dataset == ds]
        print(f"  SOH {ds}: benchmarking {len(MODEL_NAMES)} models (full features) ...")
        preds, imp = loco_predictions(d, FEATURE_SETS["full"])
        summ = summarise(preds)
        primary = min(summ["summary"], key=lambda n: summ["summary"][n]["rmse"])
        print(f"  SOH {ds}: primary = {primary}; calibrating conformal intervals ...")
        hw = conformal_halfwidths(d, FEATURE_SETS["full"], primary)
        preds["soh_pred"] = preds[f"pred_{primary}"]
        preds["soh_halfwidth"] = preds["cell_id"].map(hw)
        preds["soh_lo"] = preds["soh_pred"] - preds["soh_halfwidth"]
        preds["soh_hi"] = preds["soh_pred"] + preds["soh_halfwidth"]
        cov = {cid: interval_coverage(g.soh, g.soh_lo, g.soh_hi) for cid, g in preds.groupby("cell_id")}

        print(f"  SOH {ds}: partial-charge feature set ...")
        p_preds, _ = loco_predictions(d, FEATURE_SETS["partial"])
        results[ds] = {
            **summ,
            "features": FEATURE_SETS["full"],
            "primary_model": primary,
            "feature_importance_gbr": imp,
            "conformal_halfwidth": hw,
            "coverage_95": interval_coverage(preds.soh, preds.soh_lo, preds.soh_hi),
            "coverage_per_cell": cov,
            "partial_charge": {"features": FEATURE_SETS["partial"],
                               "summary": summarise(p_preds)["summary"]},
        }
        all_preds.append(preds)
        if save:
            ok = _valid(d)
            final = fit(primary, ok[FEATURES], ok["soh"])
            (RESULTS_DIR / "models").mkdir(parents=True, exist_ok=True)
            joblib.dump({"model": final, "name": primary, "features": FEATURES,
                         "halfwidth": float(np.median(list(hw.values())))},
                        RESULTS_DIR / "models" / f"soh_{ds}.joblib")
    preds = pd.concat(all_preds, ignore_index=True)
    if save:
        preds.to_csv(RESULTS_DIR / "soh_predictions.csv", index=False)
        (RESULTS_DIR / "soh_metrics.json").write_text(json.dumps(round_dict(results), indent=2))
    return {"metrics": results, "predictions": preds}

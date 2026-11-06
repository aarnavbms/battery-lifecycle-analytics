import json

import numpy as np
import pandas as pd
import pytest

from batterylife.config import RESULTS_DIR
from batterylife.models import soh
from batterylife.models.evaluation import interval_coverage, regression_metrics


def toy_cells(n_cells=4, n=120, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for c in range(n_cells):
        cyc = np.arange(1, n + 1)
        s = 1 - 0.002 * cyc * (1 + 0.1 * c)
        rows.append(pd.DataFrame({
            "dataset": "toy", "cell_id": f"T{c}", "cycle": cyc, "soh": s, "is_outlier": False,
            "cc_charge_time_s": 3000 * s + rng.normal(0, 5, n),
            "cv_charge_time_s": 6000 - 1500 * s + rng.normal(0, 20, n),
            "charge_v_rise_s": 2500 * s + rng.normal(0, 10, n),
            "resistance_ohm": 0.1 + 0.1 * (1 - s) + rng.normal(0, 0.001, n)}))
    return pd.concat(rows, ignore_index=True)


def test_regression_metrics():
    m = regression_metrics([1, 2, 3], [1, 2, 4])
    assert m["mae"] == pytest.approx(1 / 3)
    assert m["max_abs"] == 1


def test_loco_never_trains_on_test_cell():
    df = toy_cells()
    preds, _ = soh.loco_predictions(df, soh.FEATURES, names=["Ridge"])
    assert len(preds) == len(df)
    assert regression_metrics(preds.soh, preds["pred_Ridge"])["rmse"] < 0.02


def test_conformal_interval_covers_toy_data():
    df = toy_cells()
    hw = soh.conformal_halfwidths(df, soh.FEATURES, "Ridge")
    preds, _ = soh.loco_predictions(df, soh.FEATURES, names=["Ridge"])
    h = preds.cell_id.map(hw)
    assert interval_coverage(preds.soh, preds.pred_Ridge - h, preds.pred_Ridge + h) > 0.8


@pytest.mark.skipif(not (RESULTS_DIR / "soh_metrics.json").exists(), reason="run the pipeline first")
def test_saved_soh_results_meet_targets():
    m = json.loads((RESULTS_DIR / "soh_metrics.json").read_text())
    for ds, target in (("nasa", 0.03), ("calce", 0.015)):
        best = m[ds]["summary"][m[ds]["primary_model"]]["rmse"]
        assert best < target
        assert m[ds]["coverage_95"] > 0.9

import json

import numpy as np
import pandas as pd
import pytest

from batterylife.config import RESULTS_DIR
from batterylife.models import rul


def test_eol_cycle():
    s = pd.Series([1.0, 0.9, 0.85, 0.79, 0.75])
    assert rul.eol_cycle(s, pd.Series([1, 2, 3, 4, 5]), 0.8) == 4
    assert rul.eol_cycle(s, pd.Series([1, 2, 3, 4, 5]), 0.5) is None


def test_fade_model_recovers_known_curve():
    k = np.arange(1, 301, dtype=float)
    soh = rul.fade_curve(k / 100, 1.0, 0.05, 0.01, 1.2)
    true_eol = k[np.flatnonzero(rul.fade_curve(np.arange(1, 2000) / 100, 1.0, 0.05, 0.01, 1.2) <= 0.8)[0]]
    pred = rul.fade_model_rul(k[:200], soh[:200], 0.8, 100.0, 2000)
    assert abs((200 + pred) - true_eol) < 15


def test_linear_trend():
    k = np.arange(1, 101, dtype=float)
    soh = 1 - 0.001 * k
    assert rul.linear_trend_rul(k, soh, 0.8, 20, 1000) == pytest.approx(100, abs=1)
    assert rul.linear_trend_rul(k, np.ones(100), 0.8, 20, 1000) == 1000


def test_snapshots_target_is_cycles_to_threshold():
    n = 200
    cyc = np.arange(1, n + 1)
    s = 1 - 0.0015 * cyc
    g = pd.DataFrame({"cell_id": "X", "cycle": cyc, "soh_smooth": s, "soh_pred": s,
                      "cc_charge_time_s": 1.0, "charge_v_rise_s": 1.0, "resistance_ohm": 0.1})
    snaps = rul.snapshots(g, 0.8, "nasa", 400)
    eol = cyc[np.flatnonzero(s <= 0.8)[0]]
    assert (snaps["rul_true"] == eol - snaps["cycle"]).all()
    assert snaps["cycle"].max() < eol


@pytest.mark.skipif(not (RESULTS_DIR / "rul_metrics.json").exists(), reason="run the pipeline first")
def test_saved_rul_results():
    m = json.loads((RESULTS_DIR / "rul_metrics.json").read_text())
    for ds in ("nasa", "calce"):
        g = m[ds]["first_life"]["quantile_gbr"]
        assert g["mae"] < 0.15 * m[ds]["first_life"]["mean_life_to_threshold"]
        assert 0.65 < g["coverage_cqr_80"] < 0.95

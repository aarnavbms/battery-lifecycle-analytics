import numpy as np
import pandas as pd
import pytest

from batterylife.features.cleaning import clean_capacity, hampel_flags, repair_feature
from batterylife.features.indicators import SOH_FEATURES, load_features


def test_hampel_flags_isolated_drop_only():
    soh = pd.Series(np.linspace(1.0, 0.8, 200))
    soh.iloc[50] -= 0.2        # interrupted cycle
    soh.iloc[120] += 0.05      # regeneration jump (must be kept)
    flags = clean_capacity(pd.DataFrame({"soh": soh}))
    assert flags.iloc[50]
    assert not flags.iloc[120]
    assert flags.sum() == 1


def test_repair_feature_removes_spike():
    x = pd.Series(np.linspace(3000, 2000, 100))
    x.iloc[30] = 10
    y = repair_feature(x)
    assert abs(y.iloc[30] - x.iloc[29]) < 30


def test_hampel_two_sided():
    x = pd.Series(np.ones(50))
    x.iloc[10], x.iloc[20] = 5, -5
    f = hampel_flags(x, min_abs=0.5)
    assert f.iloc[10] and f.iloc[20] and f.sum() == 2


@pytest.fixture(scope="module")
def feats():
    return load_features()


def test_features_complete(feats):
    assert feats[SOH_FEATURES].notna().all().all()


def test_relative_features_start_near_one(feats):
    for _, g in feats.groupby("cell_id"):
        first = g[~g.is_outlier].iloc[:10]
        assert abs(first["cc_charge_time_rel"].median() - 1) < 0.05


def test_nasa_regeneration_is_kept(feats):
    assert feats[feats.dataset == "nasa"]["is_outlier"].sum() == 0


def test_calce_outlier_share_is_small(feats):
    share = feats[feats.dataset == "calce"]["is_outlier"].mean()
    assert 0 < share < 0.06

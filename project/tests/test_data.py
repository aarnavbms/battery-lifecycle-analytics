import numpy as np
import pandas as pd
import pytest

from batterylife.data import registry
from batterylife.data.nasa import charge_features
from batterylife.data.schema import CYCLE_COLUMNS


@pytest.fixture(scope="module")
def cycles():
    return registry.load_cycles()


def test_schema_and_cells(cycles):
    assert list(cycles.columns) == CYCLE_COLUMNS
    assert set(cycles.cell_id) == {"B0005", "B0006", "B0007", "B0018",
                                   "CS2_35", "CS2_36", "CS2_37", "CS2_38"}
    registry.validate(cycles)


def test_cycle_numbering_is_contiguous(cycles):
    for _, g in cycles.groupby("cell_id"):
        assert (np.diff(g["cycle"].to_numpy()) == 1).all()


def test_capacity_fades(cycles):
    for _, g in cycles.groupby("cell_id"):
        first, last = g["soh"].iloc[:10].median(), g["soh"].iloc[-10:].median()
        assert last < first - 0.15


def test_charge_features_on_synthetic_curve():
    t = np.arange(0, 4000, 10.0)
    v = np.clip(3.6 + t / 4000, None, 4.2)          # reaches 4.2 V at t = 2400 s
    i = np.where(v < 4.2, 1.5, np.exp(-(t - 2400) / 300) * 1.5)
    f = charge_features(t, v, i)
    # CV start is detected at 4.195 V (5 mV tolerance) -> 20 s early on this ramp
    assert abs(f["cc_charge_time_s"] - 2400) <= 25
    assert abs(f["charge_v_rise_s"] - 1200) <= 25
    assert f["cv_charge_time_s"] > 0


def test_validate_rejects_bad_rows(cycles):
    bad = cycles.head(5).copy()
    bad.loc[bad.index[0], "capacity_ah"] = -1
    with pytest.raises(ValueError):
        registry.validate(bad)

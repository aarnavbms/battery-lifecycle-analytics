"""Health indicators (HIs) for SOH and RUL models.

All SOH inputs are things a battery management system observes during an
ordinary charge, so a battery can be assessed without a full discharge test:

  cc_charge_time   constant-current phase gets shorter as capacity fades
  cv_charge_time   constant-voltage tail gets longer as resistance and polarisation grow
  charge_v_rise    3.9 -> 4.2 V rise time shrinks with capacity loss
  resistance       ohmic + charge-transfer resistance grows with ageing
  cycle            cycle count

Each HI is also divided by the cell's own baseline (median of its first valid
cycles), giving *_rel features that compare across cells with different
starting points.
"""
from __future__ import annotations

import pandas as pd

from ..config import PROCESSED_DIR
from .cleaning import clean_cell

RAW_HI = ["cc_charge_time_s", "cv_charge_time_s", "charge_v_rise_s", "resistance_ohm",
          "temp_rise_c", "temp_max_c", "mean_discharge_v", "discharge_time_s"]
REL_MAP = {
    "cc_charge_time_s": "cc_charge_time_rel",
    "cv_charge_time_s": "cv_charge_time_rel",
    "charge_v_rise_s": "charge_v_rise_rel",
    "resistance_ohm": "resistance_rel",
}
SOH_FEATURES = ["cc_charge_time_rel", "cv_charge_time_rel", "charge_v_rise_rel",
                "resistance_rel", "cycle"]
BASELINE_CYCLES = 10
FEATURES_CSV = PROCESSED_DIR / "features.csv"


def add_relative(g: pd.DataFrame) -> pd.DataFrame:
    g = g.copy()
    ok = g[~g["is_outlier"]]
    for raw, rel in REL_MAP.items():
        base = ok[raw].iloc[:BASELINE_CYCLES].median()
        g[rel] = g[raw] / base if pd.notna(base) and base else float("nan")
    g["resistance_growth"] = g["resistance_rel"]
    return g


def build_features(cycles: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for _, g in cycles.groupby("cell_id", sort=False):
        g = clean_cell(g.reset_index(drop=True), RAW_HI)
        parts.append(add_relative(g))
    return pd.concat(parts, ignore_index=True)


def load_features(refresh: bool = False) -> pd.DataFrame:
    if FEATURES_CSV.exists() and not refresh:
        return pd.read_csv(FEATURES_CSV)
    from ..data.registry import load_cycles
    df = build_features(load_cycles())
    FEATURES_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(FEATURES_CSV, index=False)
    return df


def correlation_table(df: pd.DataFrame) -> pd.DataFrame:
    cols = SOH_FEATURES + ["temp_rise_c"]
    rows = {}
    for ds, d in df[~df["is_outlier"]].groupby("dataset"):
        rows[ds] = {c: round(d[c].corr(d["soh"]), 3) for c in cols if d[c].notna().any()}
    return pd.DataFrame(rows)

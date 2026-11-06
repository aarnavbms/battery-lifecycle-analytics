"""Single entry point to the cycle-level data of every dataset.

    from batterylife.data.registry import load_cycles
    df = load_cycles()          # cached CSV if present, else parse raw files

The cache lives in data/processed/cycles_raw.csv so the dashboard and the
models can run even when the 170 MB of raw CALCE files are not on disk.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from ..config import DATASETS, PROCESSED_DIR, RAW_DIR
from . import calce, nasa
from .schema import CYCLE_COLUMNS, REQUIRED_NON_NULL

CACHE = PROCESSED_DIR / "cycles_raw.csv"
LOADERS = {"nasa": nasa.load, "calce": calce.load}


CALCE_MIN_FILES = 20   # each CS2 cell has 24-26 Arbin exports; fewer means an incomplete copy


def raw_available(dataset: str) -> bool:
    """True only when the raw files of *every* cell are present."""
    from ..config import DATASETS
    if dataset == "nasa":
        return all((RAW_DIR / "nasa" / f"{c}.mat").exists() for c in DATASETS["nasa"].cells)
    return all(len(list((RAW_DIR / "calce" / c).glob("*.xlsx"))) >= CALCE_MIN_FILES
               for c in DATASETS["calce"].cells)


def parse_raw(datasets=("nasa", "calce")) -> pd.DataFrame:
    frames = []
    for name in datasets:
        if not raw_available(name):
            raise FileNotFoundError(
                f"Raw {name} data missing or incomplete in data/raw/{name}. "
                "Run: python scripts/download_data.py (the processed data in data/processed "
                "is enough for everything except --refresh)")
        print(f"  parsing {name} ...")
        frames.append(LOADERS[name]())
    df = pd.concat(frames, ignore_index=True)[CYCLE_COLUMNS]
    validate(df)
    return df


def validate(df: pd.DataFrame) -> None:
    missing = [c for c in CYCLE_COLUMNS if c not in df]
    if missing:
        raise ValueError(f"missing columns: {missing}")
    for c in REQUIRED_NON_NULL:
        if df[c].isna().any():
            raise ValueError(f"null values in required column {c}")
    if (df["capacity_ah"] <= 0).any():
        raise ValueError("non-positive capacity found")
    dup = df.duplicated(["cell_id", "cycle"]).sum()
    if dup:
        raise ValueError(f"{dup} duplicate (cell_id, cycle) rows")


def load_cycles(refresh: bool = False) -> pd.DataFrame:
    if CACHE.exists() and not refresh:
        return pd.read_csv(CACHE)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df = parse_raw()
    df.to_csv(CACHE, index=False)
    return df


def quality_report(df: pd.DataFrame) -> dict:
    """Per-cell summary used in docs/dataset.md and the dashboard."""
    cells = []
    for (ds, cid), g in df.groupby(["dataset", "cell_id"], sort=False):
        cells.append({
            "dataset": ds, "cell_id": cid, "cycles": int(len(g)),
            "rated_capacity_ah": DATASETS[ds].rated_capacity_ah,
            "soh_start": round(float(g["soh"].iloc[0]), 4),
            "soh_end": round(float(g["soh"].iloc[-1]), 4),
            "soh_min": round(float(g["soh"].min()), 4),
            "missing_pct": {c: round(float(g[c].isna().mean() * 100), 1)
                            for c in CYCLE_COLUMNS if g[c].isna().any()},
            "resistance_start_ohm": None if g["resistance_ohm"].isna().all()
            else round(float(g["resistance_ohm"].dropna().iloc[:5].median()), 4),
        })
    return {"rows": int(len(df)), "cells": cells,
            "datasets": {k: v.name for k, v in DATASETS.items()}}


def save_quality_report(df: pd.DataFrame, path=None) -> dict:
    rep = quality_report(df)
    path = path or PROCESSED_DIR / "data_quality.json"
    path.write_text(json.dumps(rep, indent=2, default=lambda o: float(o) if isinstance(o, np.floating) else o))
    return rep

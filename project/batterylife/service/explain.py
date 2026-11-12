"""Explainability: which input signals the SOH model actually depends on.

Permutation importance, measured the same honest way as accuracy: the model is
trained on three cells, then on the fourth (unseen) cell each input column is
shuffled in turn and the rise in error is recorded. A signal the model relies
on causes a large rise; a signal it ignores causes none. Unlike the built-in
"impurity" importance of tree models, this works for any model (including the
Gaussian Process used for CALCE) and is measured on unseen data.

    python -m batterylife explain        -> results/explainability.json
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance

from ..config import PROCESSED_DIR, RESULTS_DIR, SEED
from ..models import soh as soh_model

OUT = RESULTS_DIR / "explainability.json"
FEATURES = soh_model.FEATURES


def run(save: bool = True, repeats: int = 8) -> dict:
    feats = pd.read_csv(PROCESSED_DIR / "features.csv")
    metrics = json.loads((RESULTS_DIR / "soh_metrics.json").read_text())
    out = {"method": "permutation importance on the held-out cell (leave-one-cell-out)",
           "unit": "rise in RMSE, SOH percentage points", "repeats": repeats, "features": FEATURES, "datasets": {}}
    for ds in ("nasa", "calce"):
        d = feats[(feats.dataset == ds) & ~feats.is_outlier].reset_index(drop=True)
        name = metrics[ds]["primary_model"]
        per_cell = {}
        for cell in d["cell_id"].unique():
            tr, te = d[d.cell_id != cell], d[d.cell_id == cell]
            m = soh_model.fit(name, tr[FEATURES], tr["soh"])
            r = permutation_importance(m, te[FEATURES], te["soh"], scoring="neg_root_mean_squared_error",
                                       n_repeats=repeats, random_state=SEED)
            per_cell[cell] = {f: round(float(v) * 100, 3) for f, v in zip(FEATURES, r.importances_mean)}
        mean = {f: round(float(np.mean([per_cell[c][f] for c in per_cell])), 3) for f in FEATURES}
        sd = {f: round(float(np.std([per_cell[c][f] for c in per_cell])), 3) for f in FEATURES}
        out["datasets"][ds] = {"model": name, "mean": mean, "spread_across_cells": sd, "per_cell": per_cell,
                               "top_signal": max(mean, key=mean.get)}
        print(f"  explain {ds} ({name}): " + ", ".join(f"{f}={mean[f]:.2f}" for f in FEATURES))
    if save:
        OUT.write_text(json.dumps(out, indent=2))
    return out


def load() -> dict | None:
    return json.loads(OUT.read_text()) if OUT.exists() else None

"""Regenerate every report figure in docs/figures from data/processed and results/.

    python scripts/make_figures.py
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from batterylife.config import FIG_DIR, PROCESSED_DIR, RESULTS_DIR, THRESHOLDS  # noqa: E402

plt.rcParams.update({"figure.dpi": 130, "axes.grid": True, "grid.alpha": 0.25,
                     "axes.spines.top": False, "axes.spines.right": False, "font.size": 10})
COLORS = ["#2563eb", "#f97316", "#16a34a", "#dc2626"]


def fig_raw_capacity():
    df = pd.read_csv(PROCESSED_DIR / "cycles_raw.csv")
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.2))
    for a, ds, title in [(ax[0], "nasa", "NASA PCoE (rated 2.0 Ah)"),
                         (ax[1], "calce", "CALCE CS2 (rated 1.1 Ah)")]:
        for k, (cid, g) in enumerate(df[df.dataset == ds].groupby("cell_id")):
            a.plot(g.cycle, g.soh * 100, lw=1, color=COLORS[k], label=cid)
        a.axhline(THRESHOLDS.first_life_eol * 100, color="k", ls="--", lw=.8)
        a.axhline(THRESHOLDS.second_life_floor * 100, color="#b91c1c", ls="--", lw=.8)
        a.set(title=title, xlabel="Cycle", ylabel="SOH (%)")
        a.legend(fontsize=8)
    fig.suptitle("Raw measured state of health (before cleaning)")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig01_raw_soh.png")
    plt.close(fig)


def fig_cleaning():
    p = PROCESSED_DIR / "features.csv"
    if not p.exists():
        return
    df = pd.read_csv(p)
    g = df[df.cell_id == "CS2_36"]
    fig, ax = plt.subplots(1, 2, figsize=(12, 4))
    ax[0].plot(g.cycle, g.soh_raw * 100, lw=.7, color="#94a3b8", label="raw")
    o = g[g.is_outlier]
    ax[0].scatter(o.cycle, o.soh_raw * 100, s=10, color="#dc2626", label=f"flagged ({len(o)})", zorder=3)
    ax[0].plot(g.cycle, g.soh * 100, lw=1.2, color="#2563eb", label="cleaned")
    ax[0].set(title="CS2_36: Hampel cleaning", xlabel="Cycle", ylabel="SOH (%)")
    ax[0].legend(fontsize=8)
    feats = ["cc_charge_time_rel", "cv_charge_time_rel", "charge_v_rise_rel", "resistance_rel", "cycle"]
    corr = []
    for ds in ("nasa", "calce"):
        d = df[(df.dataset == ds) & ~df.is_outlier]
        corr.append([d[f].corr(d.soh) for f in feats])
    im = ax[1].imshow(np.array(corr), cmap="RdBu", vmin=-1, vmax=1, aspect="auto")
    ax[1].set_xticks(range(len(feats)), [f.replace("_rel", "") for f in feats], rotation=20, fontsize=8)
    ax[1].set_yticks([0, 1], ["NASA", "CALCE"])
    for i in range(2):
        for j in range(len(feats)):
            ax[1].text(j, i, f"{corr[i][j]:.2f}", ha="center", va="center", fontsize=9,
                       color="white" if abs(corr[i][j]) > 0.6 else "black")
    ax[1].set_title("Correlation of health indicators with SOH")
    ax[1].grid(False)
    fig.colorbar(im, ax=ax[1], shrink=.8)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig02_cleaning_and_correlation.png")
    plt.close(fig)


def fig_soh():
    p = RESULTS_DIR / "soh_metrics.json"
    if not p.exists():
        return
    m = json.loads(p.read_text())
    pred = pd.read_csv(RESULTS_DIR / "soh_predictions.csv")
    fig, ax = plt.subplots(1, 3, figsize=(16, 4.4))
    models = list(m["nasa"]["summary"].keys())
    x = np.arange(len(models))
    for k, ds in enumerate(("nasa", "calce")):
        ax[0].bar(x + (k - .5) * .38, [m[ds]["summary"][mm]["rmse"] * 100 for mm in models], .38,
                  label=ds.upper(), color=COLORS[k])
    ax[0].set_xticks(x, models, rotation=15, fontsize=8)
    ax[0].set(ylabel="RMSE (SOH %-points)", title="SOH error, leave-one-cell-out")
    ax[0].legend()
    for a, cid, ds in [(ax[1], "B0006", "nasa"), (ax[2], "CS2_35", "calce")]:
        g = pred[pred.cell_id == cid]
        a.plot(g.cycle, g.soh * 100, color="k", lw=1, label="measured")
        a.plot(g.cycle, g.soh_pred * 100, color="#2563eb", lw=1, label=m[ds]["primary_model"])
        a.fill_between(g.cycle, g.soh_lo * 100, g.soh_hi * 100, color="#2563eb", alpha=.18,
                       label="95% conformal interval")
        a.set(title=f"{cid} (unseen during training)", xlabel="Cycle", ylabel="SOH (%)")
        a.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig03_soh_models.png")
    plt.close(fig)


def fig_rul():
    p = RESULTS_DIR / "rul_predictions.csv"
    if not p.exists():
        return
    r = pd.read_csv(p)
    r = r[r.threshold == THRESHOLDS.first_life_eol]
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.4))
    for a, cid in [(ax[0], "B0005"), (ax[1], "CS2_37")]:
        g = r[r.cell_id == cid]
        top = g.rul_true.max() * 1.6
        a.plot(g.cycle, g.rul_true, color="k", lw=1.4, label="true RUL")
        a.plot(g.cycle, g.rul_fade.clip(upper=top), color="#f97316", lw=1, label="empirical fade model")
        a.plot(g.cycle, g.rul_linear.clip(upper=top), color="#a3a3a3", lw=1, ls=":", label="linear trend")
        a.plot(g.cycle, g.rul_gbr, color="#2563eb", lw=1.4, label="quantile GBR (median)")
        a.fill_between(g.cycle, g.rul_gbr_lo, g.rul_gbr_hi, color="#2563eb", alpha=.15,
                       label="80% calibrated band (CQR)")
        a.set(title=f"{cid}: cycles left to 80% SOH (unseen cell)", xlabel="Prediction cycle",
              ylabel="Cycles left", ylim=(0, top))
        a.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig04_rul.png")
    plt.close(fig)


def fig_second_life():
    p = RESULTS_DIR / "second_life_assessments.csv"
    if not p.exists():
        return
    a = pd.read_csv(p)
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.2))
    order = ["A", "B", "C", "D"]
    cm = pd.crosstab(a.grade_true, a.grade_pred).reindex(index=order, columns=order, fill_value=0)
    ax[0].imshow(cm.values, cmap="Blues")
    for i in range(4):
        for j in range(4):
            ax[0].text(j, i, cm.values[i, j], ha="center", va="center",
                       color="white" if cm.values[i, j] > cm.values.max() * 0.55 else "black")
    ax[0].set_xticks(range(4), order)
    ax[0].set_yticks(range(4), order)
    ax[0].set(xlabel="Predicted grade", ylabel="True grade",
              title=f"Grading on unseen cells: {(a.grade_true == a.grade_pred).mean():.1%} agreement")
    ax[0].grid(False)
    c = a[(a.dataset == "calce") & a.cycle_criterion_used & (a.retire_soh_level > THRESHOLDS.second_life_floor)]
    for k, (cid, g) in enumerate(c.groupby("cell_id")):
        ax[1].scatter(g.cycles_to_floor_true, g.cycles_to_floor_pred, s=22, color=COLORS[k], label=cid)
    lim = max(c.cycles_to_floor_true.max(), c.cycles_to_floor_pred.max()) * 1.05
    ax[1].plot([0, lim], [0, lim], "k--", lw=.8)
    ax[1].set(xlabel="True cycles left to 60% SOH", ylabel="Predicted cycles left",
              title="CALCE: second-life length at retirement")
    ax[1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig05_second_life.png")
    plt.close(fig)


if __name__ == "__main__":
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    for f in (fig_raw_capacity, fig_cleaning, fig_soh, fig_rul, fig_second_life):
        f()
    print("figures written to", FIG_DIR)

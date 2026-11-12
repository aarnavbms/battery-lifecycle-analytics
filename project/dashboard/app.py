"""Analytics dashboard for the battery lifecycle and passport system.

Run from the project folder:
    python dashboard/app.py            -> http://127.0.0.1:8050

Reads everything from results/ and data/processed/ (written by
`python -m batterylife run`). Works fully offline.
"""
from __future__ import annotations

import copy
import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from flask import Flask, abort, jsonify, render_template, request  # noqa: E402
from flask.json.provider import DefaultJSONProvider  # noqa: E402

from batterylife.config import (APPLICATIONS, DATASETS, PROCESSED_DIR, RESULTS_DIR,  # noqa: E402
                                SUSTAINABILITY, THRESHOLDS)
from batterylife.lifecycle.grading import assess  # noqa: E402
from batterylife.lifecycle.sustainability import value  # noqa: E402
from batterylife.passport import crypto, store  # noqa: E402
from batterylife.passport.ledger import _body, verify  # noqa: E402
from batterylife.passport.schema import EVENT_TYPES, PUBLIC, ROLES, SECTIONS  # noqa: E402
from batterylife.service import auth, db  # noqa: E402
from dashboard.api_v1 import api as api_v1  # noqa: E402

def clean(o):
    """Make any result JSON-safe: NaN/inf -> null, numpy scalars -> Python."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


class SafeJSON(DefaultJSONProvider):
    sort_keys = False

    def dumps(self, obj, **kw):
        kw.setdefault("allow_nan", False)
        return json.dumps(clean(obj), **kw)


app = Flask(__name__)
app.json = SafeJSON(app)
app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024
app.register_blueprint(api_v1)

# sidebar navigation: (group, [(key, url, label, icon)])
NAV_GROUPS = [
    ("Project", [("overview", "/", "Home", "home")]),
    ("Analytics", [("cells", "/cells", "Cells", "cell"), ("models", "/models", "Models", "chart"),
                   ("second_life", "/second-life", "Second life", "cycle")]),
    ("Tools", [("assess", "/assess", "Assess your data", "upload")]),
    ("Trust", [("passports", "/passports", "Passports", "doc"), ("network", "/network", "Network", "graph")]),
    ("Developers", [("api", "/developers", "API", "code")]),
    ("Future", [("hardware", "/hardware", "Hardware", "chip")]),
    ("Project files", [("reports", "/reports", "Weekly reports", "file")]),
]
PAGES = [(k, url, label) for _, items in NAV_GROUPS for k, url, label, _ in items]
NAV_ICONS = {
    "home": "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z",
    "cell": "M4 7h14a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1zm16 3h1.5v4H20zM6 9.5h6v5H6z",
    "chart": "M4 20V4m0 16h16M8 16v-5m4 5V8m4 8v-3",
    "cycle": "M20 12a8 8 0 0 1-14.3 4.9M4 12a8 8 0 0 1 14.3-4.9M18.5 3v4.2h-4.2M5.5 21v-4.2h4.2",
    "doc": "M6 3h9l4 4v14H6zM14 3v5h5M9 12h7M9 16h7",
    "chip": "M7 7h10v10H7zM10 3v4m4-4v4m-4 10v4m4-4v4M3 10h4m-4 4h4m10-4h4m-4 4h4",
    "file": "M6 3h9l4 4v14H6zM14 3v5h5M9 17l2-2 2 2 3-4",
    "upload": "M12 16V4m0 0-4 4m4-4 4 4M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4",
    "graph": "M6 7a2 2 0 1 0 0-4 2 2 0 0 0 0 4zm12 2a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM8 21a2 2 0 1 0 0-4 2 2 0 0 0 0 4zm10-2a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM7.9 5.4l8.2 1.3M6.4 7l1.2 10m1.9 1.6 6.6-1.1M17.6 9l.2 6",
    "code": "M8 7l-5 5 5 5m8-10 5 5-5 5M13.5 5l-3 14",
}


# ---------------------------------------------------------------- data cache
class Store:
    def __init__(self):
        self.stamp = None
        self.load()

    def _mtime(self):
        f = RESULTS_DIR / "summary.json"
        return f.stat().st_mtime if f.exists() else None

    def load(self):
        if not (RESULTS_DIR / "summary.json").exists():
            raise SystemExit("results/summary.json not found. Run: python -m batterylife run --fast")
        self.summary = json.loads((RESULTS_DIR / "summary.json").read_text())
        self.soh_m = json.loads((RESULTS_DIR / "soh_metrics.json").read_text())
        self.rul_m = json.loads((RESULTS_DIR / "rul_metrics.json").read_text())
        self.sl_s = json.loads((RESULTS_DIR / "second_life_summary.json").read_text())
        self.feats = pd.read_csv(PROCESSED_DIR / "features.csv")
        self.soh_p = pd.read_csv(RESULTS_DIR / "soh_predictions.csv")
        self.rul_p = pd.read_csv(RESULTS_DIR / "rul_predictions.csv")
        self.assess = pd.read_csv(RESULTS_DIR / "second_life_assessments.csv")
        self.registry = store.load_registry()
        self.stamp = self._mtime()

    def fresh(self):
        if self._mtime() != self.stamp:
            self.load()
        return self


DATA = Store()


def records(df: pd.DataFrame) -> list[dict]:
    out = df.astype(object).where(pd.notna(df), None).to_dict("records")
    for r in out:
        for k, v in r.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                r[k] = None
            elif isinstance(v, (np.bool_,)):
                r[k] = bool(v)
    return out


def cols(df: pd.DataFrame, names: list[str]) -> dict:
    """Column-oriented JSON (compact for charts)."""
    return {c: [None if (isinstance(v, float) and math.isnan(v)) else v
                for v in df[c].tolist()] for c in names if c in df}


# ---------------------------------------------------------------- pages
def page(name):
    return render_template(f"{name}.html", pages=PAGES, nav_groups=NAV_GROUPS, icons=NAV_ICONS,
                           active=name, title=dict((p[0], p[2]) for p in PAGES)[name])


@app.get("/")
def overview():
    return page("overview")


@app.get("/cells")
def cells_page():
    return page("cells")


@app.get("/models")
def models_page():
    return page("models")


@app.get("/second-life")
def second_life_page():
    return page("second_life")


@app.get("/passports")
def passports_page():
    return page("passports")


@app.get("/hardware")
def hardware_page():
    return page("hardware")


@app.get("/reports")
def reports_page():
    return page("reports")


@app.get("/assess")
def assess_page():
    return page("assess")


@app.get("/network")
def network_page():
    return page("network")


@app.get("/developers")
def api_page():
    return page("api")


@app.get("/api/v1/docs")
def api_docs_redirect():
    from flask import redirect
    return redirect("/developers")


SAMPLES_DIR = ROOT / "data" / "samples"


@app.get("/samples/<path:name>")
def sample_file(name):
    from flask import send_from_directory
    return send_from_directory(SAMPLES_DIR, name, mimetype="text/csv")


REPORTS_DIR = ROOT / "docs" / "reports"


@app.get("/reports/<path:name>")
def report_file(name):
    from flask import send_from_directory
    return send_from_directory(REPORTS_DIR, name)


# ---------------------------------------------------------------- API
@app.get("/api/summary")
def api_summary():
    d = DATA.fresh()
    s = dict(d.summary)
    s.pop("data_quality", None)
    s["datasets"] = {k: {"name": v.name, "chemistry": v.chemistry, "rated_capacity_ah": v.rated_capacity_ah,
                         "cells": list(v.cells), "source": v.source} for k, v in DATASETS.items()}
    # retirement point per cell for the lifecycle band
    ret = d.assess[d.assess.is_retirement_point]
    s["retirement"] = records(ret[["cell_id", "cycle", "soh_true", "soh_est", "grade_pred",
                                   "application", "confidence"]])
    return jsonify(s)


@app.get("/api/fleet")
def api_fleet():
    d = DATA.fresh()
    out = {}
    for cid, g in d.feats.groupby("cell_id", sort=False):
        out[cid] = {"dataset": g["dataset"].iloc[0], **cols(g, ["cycle", "soh", "soh_smooth"])}
    return jsonify(out)


@app.get("/api/cell/<cid>")
def api_cell(cid):
    d = DATA.fresh()
    g = d.feats[d.feats.cell_id == cid]
    if g.empty:
        abort(404)
    p = d.soh_p[d.soh_p.cell_id == cid]
    model = d.soh_m[g["dataset"].iloc[0]]["primary_model"]
    r = d.rul_p[d.rul_p.cell_id == cid]
    a = d.assess[d.assess.cell_id == cid]
    ds = g["dataset"].iloc[0]
    return jsonify({
        "cell_id": cid, "dataset": ds, "soh_model": model,
        "rated_capacity_ah": DATASETS[ds].rated_capacity_ah,
        "series": cols(g, ["cycle", "soh_raw", "soh", "soh_smooth", "is_outlier", "cc_charge_time_s",
                           "cv_charge_time_s", "charge_v_rise_s", "resistance_growth", "temp_rise_c"]),
        "estimate": cols(p, ["cycle", "soh_pred", "soh_lo", "soh_hi"]),
        "rul80": cols(r[np.isclose(r.threshold, THRESHOLDS.first_life_eol)],
                      ["cycle", "rul_true", "rul_gbr", "rul_gbr_lo", "rul_gbr_hi", "rul_fade", "rul_linear"]),
        "rul60": cols(r[np.isclose(r.threshold, THRESHOLDS.second_life_floor)],
                      ["cycle", "rul_true", "rul_gbr", "rul_gbr_lo", "rul_gbr_hi", "rul_fade"]),
        "decisions": records(a[["retire_soh_level", "cycle", "soh_true", "soh_est", "soh_lo",
                                "resistance_growth", "cycles_to_floor_true", "cycles_to_floor_pred",
                                "grade_pred", "grade_true", "confidence", "application"]]),
        "metrics": {"soh": d.soh_m[ds]["per_cell"][cid][model],
                    "soh_coverage": d.soh_m[ds]["coverage_per_cell"][cid],
                    "rul_mae": d.rul_m[ds]["first_life"]["quantile_gbr"]["per_cell_mae"].get(cid)},
        "thresholds": {"first": THRESHOLDS.first_life_eol, "floor": THRESHOLDS.second_life_floor},
    })


@app.get("/api/hardware")
def api_hardware():
    out = {"bench_passport": None, "cycles": []}
    f = PROCESSED_DIR / "hardware_cycles.csv"
    if f.exists():
        out["cycles"] = records(pd.read_csv(f)[["cycle", "capacity_ah", "soh", "cc_charge_time_s",
                                                  "charge_v_rise_s", "resistance_ohm", "temp_rise_c"]])
    hw = [pid for pid in store.list_passports() if pid.startswith("DBP-HW-")]
    if hw:
        p = store.load_passport(hw[0])
        dec = p.sections()["lifecycle_decision"] or {}
        man = p.latest("MANUFACTURED")["data"]
        out["bench_passport"] = {"passport_id": p.passport_id, "events": len(p.events),
                                 "valid": verify(p, DATA.fresh().registry)["valid"],
                                 "grade": dec.get("grade"), "application": dec.get("application"),
                                 "source": man.get("data_source")}
    return jsonify(out)


@app.get("/api/reports")
def api_reports():
    f = REPORTS_DIR / "index.json"
    return jsonify(json.loads(f.read_text()) if f.exists() else [])


@app.get("/api/models")
def api_models():
    d = DATA.fresh()
    return jsonify({"soh": d.soh_m, "rul": d.rul_m})


@app.get("/api/second-life")
def api_second_life():
    d = DATA.fresh()
    a = d.assess
    return jsonify({
        "summary": d.sl_s,
        "assessments": records(a[["dataset", "cell_id", "retire_soh_level", "cycle", "soh_true", "soh_est",
                                  "cycles_to_floor_true", "cycles_to_floor_pred", "cycle_criterion_used",
                                  "grade_pred", "grade_true", "confidence"]]),
        "applications": [{"grade": x.grade, "name": x.name, "min_soh": x.min_soh,
                          "max_resistance_growth": x.max_resistance_growth,
                          "min_remaining_cycles": x.min_remaining_cycles,
                          "cycles_per_year": x.cycles_per_year, "description": x.description}
                         for x in APPLICATIONS],
        "assumptions": SUSTAINABILITY.__dict__,
    })


@app.post("/api/assess")
def api_assess():
    b = request.get_json(force=True) or {}
    try:
        soh = float(b["soh"])
        hw = float(b.get("halfwidth") or 0)
        rg = float(b["resistance_growth"]) if b.get("resistance_growth") not in (None, "") else None
        cyc = float(b["cycles"]) if b.get("cycles") not in (None, "") else None
        cyc_lo = float(b["cycles_lo"]) if b.get("cycles_lo") not in (None, "") else cyc
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Enter numbers for SOH, interval and resistance growth."}), 400
    if not 0 < soh <= 1.2:
        return jsonify({"error": "SOH must be between 0 and 1.2 (enter 0.78 for 78%)."}), 400
    r = assess(soh, soh - hw, rg, cyc, cyc_lo)
    return jsonify({**r.to_dict(), "value": value(r.grade, soh, b.get("dataset", "nasa"))})


def _viewer():
    """(user or None, may this request read restricted passport content?)"""
    user = auth.user_from_header(request.headers.get("Authorization"))
    return user, user is not None and auth.can(user["role"], "passport:read_full")


@app.errorhandler(auth.AuthError)
def _auth_error(e):
    return jsonify({"error": e.message}), e.status


@app.get("/api/passports")
def api_passports():
    db.ensure()
    _, full = _viewer()
    conn = db.connect()
    try:
        reg, out = db.registry(conn), []
        for row in db.list_passports(conn):
            p = db.load_passport(conn, row["passport_id"])
            out.append({"passport_id": p.passport_id, "battery_id": p.battery_id, "status": row["status"],
                        "events": row["n_events"], "valid": verify(p, reg)["valid"], "origin": row["origin"],
                        "grade": row["grade"] if full else None, "head_hash": row["head_hash"],
                        "updated_at": row["updated_at"]})
        return jsonify(out)
    finally:
        conn.close()


def _load(pid):
    db.ensure()
    conn = db.connect()
    try:
        p = db.load_passport(conn, pid)
        if p is None:
            abort(404)
        return p, db.registry(conn)
    finally:
        conn.close()


def _passport_payload(p, access, reg):
    d = p.to_dict(access)
    d["status"] = p.status()
    d["origin"] = db.passport_origin(p.passport_id)
    d["event_meta"] = {k: {"roles": sorted(v[0]), "access": v[1]} for k, v in EVENT_TYPES.items()}
    d["section_access"] = SECTIONS
    d["actors"] = reg.to_dict()
    d["roles"] = ROLES
    return d


@app.get("/api/passport/<pid>")
def api_passport(pid):
    p, reg = _load(pid)
    _, full = _viewer()
    if request.args.get("access") == "public":
        return jsonify(_passport_payload(p, PUBLIC, reg))
    if not full:
        return jsonify({"error": "The full passport is restricted. Sign in with a role that has a legitimate "
                                 "interest (for example recycler or regulator)."}), 403
    return jsonify(_passport_payload(p, "full", reg))


@app.post("/api/passport/<pid>/verify")
def api_verify(pid):
    p, reg = _load(pid)
    return jsonify(verify(p, reg))


ATTACKS = {
    "edit": "Raise a past SOH value to 99%",
    "rehash": "Raise a past SOH value and recompute every hash after it",
    "delete": "Delete a past SOH assessment",
    "backdate": "Move the latest event's date one year back",
    "impostor": "Re-sign the grading event with the recycler's key",
}


@app.get("/api/attacks")
def api_attacks():
    return jsonify(ATTACKS)


@app.post("/api/passport/<pid>/tamper")
def api_tamper(pid):
    """Apply an attack to an in-memory copy and verify it. Files are never changed."""
    attack = (request.get_json(silent=True) or {}).get("attack", "edit")
    if attack not in ATTACKS:
        return jsonify({"error": f"unknown attack {attack}"}), 400
    p, reg = _load(pid)
    p = copy.deepcopy(p)
    _, full = _viewer()
    ev = p.events
    soh_idx = next(e["index"] for e in ev if e["type"] == "SOH_ASSESSMENT")
    target = soh_idx
    detail = ""
    if attack in ("edit", "rehash"):
        old = ev[soh_idx]["data"]["soh"]
        ev[soh_idx]["data"]["soh"] = 0.99
        detail = (f"Event {soh_idx}: SOH changed from {old:.1%} to 99.0%" if full
                  else f"Event {soh_idx}: a restricted SOH value was raised to 99.0%")
        if attack == "rehash":
            prev = ev[soh_idx - 1]["hash"]
            for e in ev[soh_idx:]:
                e["prev_hash"] = prev
                e["hash"] = crypto.sha256_hex(_body(e))
                prev = e["hash"]
            detail += ", then every later hash recomputed"
    elif attack == "delete":
        del ev[soh_idx]
        detail = f"Event {soh_idx} (SOH assessment) deleted"
    elif attack == "backdate":
        target = len(ev) - 1
        ts = ev[target]["timestamp"]
        ev[target]["timestamp"] = str(int(ts[:4]) - 1) + ts[4:]
        detail = f"Event {target} re-dated from {ts[:10]} to {ev[target]['timestamp'][:10]}"
    elif attack == "impostor":
        target = next((e["index"] for e in ev if e["type"] == "SECOND_LIFE_GRADING"), soh_idx)
        key = crypto.load_private(ROOT / "results" / "keys" / "REC-01.pem") \
            if (ROOT / "results" / "keys" / "REC-01.pem").exists() else crypto.generate_key()
        ev[target]["data"]["grade"] = "A"
        ev[target]["hash"] = crypto.sha256_hex(_body(ev[target]))
        ev[target]["signature"] = crypto.sign(key, ev[target]["hash"])
        detail = f"Event {target}: grade changed to A and re-signed with another actor's key"
    result = verify(p, reg)
    return jsonify({"attack": attack, "description": ATTACKS[attack], "detail": detail,
                    "target_index": target, "result": result,
                    "note": "Applied to an in-memory copy. The passport file is unchanged."})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8050))
    print(f"Battery lifecycle dashboard: http://127.0.0.1:{port}")
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=port, debug=False)

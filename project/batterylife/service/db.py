"""SQLite database behind the REST API.

The analysis pipeline writes files (CSV, JSON passports). This module loads
them into one relational database so the API can query, filter and join, and
so uploads, users and the audit log have a durable home.

    python -m batterylife db            rebuild results/battery.db from the files

Tables
    datasets     one row per data source (nasa, calce, hardware, upload)
    cells        one row per battery
    cycles       one row per charge-discharge cycle, with model estimates
    assessments  second-life grading decisions
    actors       passport actors and their public keys (trust anchor)
    passports    one row per Digital Battery Passport
    events       the signed, hash-chained events of every passport
    users        API accounts, each with one role
    uploads      files submitted through the API
    audit_log    who did what, when
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import DATASETS, PROCESSED_DIR, RESULTS_DIR
from ..passport import store
from ..passport.crypto import canonical
from ..passport.ledger import Actor, ActorRegistry, Passport
from . import CTX

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS datasets (
    dataset_key        TEXT PRIMARY KEY,
    name               TEXT NOT NULL,
    chemistry          TEXT,
    form_factor        TEXT,
    rated_capacity_ah  REAL,
    nominal_voltage_v  REAL,
    source             TEXT
);

CREATE TABLE IF NOT EXISTS cells (
    cell_id            TEXT PRIMARY KEY,
    dataset_key        TEXT NOT NULL REFERENCES datasets(dataset_key),
    origin             TEXT NOT NULL CHECK (origin IN ('lab', 'hardware', 'upload')),
    rated_capacity_ah  REAL NOT NULL,
    n_cycles           INTEGER NOT NULL,
    first_soh          REAL,
    last_soh           REAL,
    upload_id          TEXT REFERENCES uploads(upload_id) ON DELETE CASCADE,
    created_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cycles (
    cell_id            TEXT NOT NULL REFERENCES cells(cell_id) ON DELETE CASCADE,
    cycle              INTEGER NOT NULL,
    timestamp          TEXT,
    capacity_ah        REAL,
    soh                REAL,
    soh_smooth         REAL,
    is_outlier         INTEGER NOT NULL DEFAULT 0,
    cc_charge_time_s   REAL,
    cv_charge_time_s   REAL,
    charge_v_rise_s    REAL,
    resistance_ohm     REAL,
    resistance_growth  REAL,
    soh_pred           REAL,
    soh_lo             REAL,
    soh_hi             REAL,
    PRIMARY KEY (cell_id, cycle)
);

CREATE TABLE IF NOT EXISTS assessments (
    assessment_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    cell_id            TEXT NOT NULL REFERENCES cells(cell_id) ON DELETE CASCADE,
    source             TEXT NOT NULL CHECK (source IN ('pipeline', 'upload')),
    cycle              INTEGER,
    soh                REAL NOT NULL,
    soh_lo             REAL,
    resistance_growth  REAL,
    cycles_left        REAL,
    grade              TEXT NOT NULL CHECK (grade IN ('A', 'B', 'C', 'D')),
    grade_reference    TEXT,
    application        TEXT,
    confidence         TEXT,
    recommendation     TEXT,
    created_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assess_cell ON assessments(cell_id);

CREATE TABLE IF NOT EXISTS actors (
    actor_id    TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    role        TEXT NOT NULL,
    public_key  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS passports (
    passport_id  TEXT PRIMARY KEY,
    battery_id   TEXT NOT NULL,
    origin       TEXT NOT NULL CHECK (origin IN ('lab', 'hardware', 'upload')),
    status       TEXT NOT NULL,
    grade        TEXT,
    n_events     INTEGER NOT NULL,
    head_hash    TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    passport_id  TEXT NOT NULL REFERENCES passports(passport_id) ON DELETE CASCADE,
    idx          INTEGER NOT NULL,
    timestamp    TEXT NOT NULL,
    type         TEXT NOT NULL,
    actor_id     TEXT NOT NULL,
    role         TEXT NOT NULL,
    data         TEXT NOT NULL,
    prev_hash    TEXT NOT NULL,
    hash         TEXT NOT NULL,
    signature    TEXT NOT NULL,
    PRIMARY KEY (passport_id, idx)
);
CREATE INDEX IF NOT EXISTS idx_events_actor ON events(actor_id);

CREATE TABLE IF NOT EXISTS users (
    username       TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    role           TEXT NOT NULL,
    password_hash  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS uploads (
    upload_id   TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    username    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    n_cells     INTEGER NOT NULL,
    n_rows      INTEGER NOT NULL,
    result      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    audit_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    at        TEXT NOT NULL,
    username  TEXT NOT NULL,
    role      TEXT NOT NULL,
    action    TEXT NOT NULL,
    target    TEXT,
    detail    TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None).isoformat()


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or CTX.db)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


# ------------------------------------------------------------------ passports
def passport_origin(passport_id: str) -> str:
    if passport_id.startswith("DBP-HW-"):
        return "hardware"
    if passport_id.startswith("DBP-UP-"):
        return "upload"
    return "lab"


def save_passport(conn, p: Passport) -> None:
    """Insert or replace a passport and all of its events."""
    grade = (p.sections()["lifecycle_decision"] or {}).get("grade")
    conn.execute("DELETE FROM passports WHERE passport_id = ?", (p.passport_id,))
    conn.execute("INSERT INTO passports VALUES (?,?,?,?,?,?,?,?)",
                 (p.passport_id, p.battery_id, passport_origin(p.passport_id), p.status(), grade,
                  len(p.events), p.head_hash, now()))
    conn.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?)", [
        (p.passport_id, e["index"], e["timestamp"], e["type"], e["actor_id"], e["role"],
         canonical(e["data"]).decode(), e["prev_hash"], e["hash"], e["signature"]) for e in p.events])


def load_passport(conn, passport_id: str) -> Passport | None:
    head = conn.execute("SELECT * FROM passports WHERE passport_id = ?", (passport_id,)).fetchone()
    if head is None:
        return None
    p = Passport(head["passport_id"], head["battery_id"])
    for e in conn.execute("SELECT * FROM events WHERE passport_id = ? ORDER BY idx", (passport_id,)):
        p.events.append({"index": e["idx"], "timestamp": e["timestamp"], "type": e["type"],
                         "actor_id": e["actor_id"], "role": e["role"], "data": json.loads(e["data"]),
                         "prev_hash": e["prev_hash"], "hash": e["hash"], "signature": e["signature"]})
    return p


def list_passports(conn) -> list[dict]:
    return rows(conn.execute("SELECT * FROM passports ORDER BY origin, passport_id"))


def registry(conn) -> ActorRegistry:
    reg = ActorRegistry()
    for a in conn.execute("SELECT * FROM actors"):
        reg.add(Actor(a["actor_id"], a["name"], a["role"], a["public_key"]))
    return reg


def save_actors(conn, reg: ActorRegistry) -> None:
    conn.executemany("INSERT OR REPLACE INTO actors VALUES (?,?,?,?)",
                     [(a.actor_id, a.name, a.role, a.public_key) for a in reg.actors.values()])


def audit(conn, user: dict | None, action: str, target: str | None = None, detail: str | None = None) -> None:
    u = user or {"username": "anonymous", "role": "public"}
    conn.execute("INSERT INTO audit_log (at, username, role, action, target, detail) VALUES (?,?,?,?,?,?)",
                 (now(), u["username"], u["role"], action, target, detail))


# ------------------------------------------------------------------ build from pipeline files
def _source_stamp() -> str:
    files = [RESULTS_DIR / "summary.json", CTX.actors_file, *sorted(CTX.passports.glob("DBP-*.json"))]
    return json.dumps([[f.name, f.stat().st_mtime_ns] for f in files if f.exists()])


def sync_from_files(conn) -> dict:
    """Load pipeline outputs into the database. Uploads, users and the audit log are kept."""
    conn.executescript(SCHEMA)
    for key, d in DATASETS.items():
        conn.execute("INSERT OR REPLACE INTO datasets VALUES (?,?,?,?,?,?,?)",
                     (key, d.name, d.chemistry, d.form_factor, d.rated_capacity_ah, d.nominal_voltage_v, d.source))
    conn.execute("INSERT OR IGNORE INTO datasets VALUES ('hardware','Bench hardware','Li-ion 18650','18650 cylindrical',NULL,3.7,'battery monitoring board')")
    conn.execute("INSERT OR IGNORE INTO datasets VALUES ('upload','User uploads',NULL,NULL,NULL,3.7,'files submitted through the API')")

    feats = pd.read_csv(PROCESSED_DIR / "features.csv")
    preds = pd.read_csv(RESULTS_DIR / "soh_predictions.csv")[["cell_id", "cycle", "soh_pred", "soh_lo", "soh_hi"]]
    df = feats.merge(preds, on=["cell_id", "cycle"], how="left")
    conn.execute("DELETE FROM cells WHERE origin = 'lab'")
    stamp = now()
    for cid, g in df.groupby("cell_id", sort=False):
        ds = g["dataset"].iloc[0]
        conn.execute("INSERT INTO cells VALUES (?,?,?,?,?,?,?,?,?)",
                     (cid, ds, "lab", DATASETS[ds].rated_capacity_ah, len(g), float(g["soh_smooth"].iloc[0]),
                      float(g["soh_smooth"].iloc[-1]), None, stamp))
    cols = ["cell_id", "cycle", "timestamp", "capacity_ah", "soh", "soh_smooth", "is_outlier", "cc_charge_time_s",
            "cv_charge_time_s", "charge_v_rise_s", "resistance_ohm", "resistance_growth", "soh_pred", "soh_lo", "soh_hi"]
    data = df[cols].astype(object).where(pd.notna(df[cols]), None)
    data["is_outlier"] = df["is_outlier"].astype(int)
    conn.executemany(f"INSERT INTO cycles VALUES ({','.join('?' * len(cols))})", data.itertuples(index=False, name=None))

    a = pd.read_csv(RESULTS_DIR / "second_life_assessments.csv")
    a = a.astype(object).where(pd.notna(a), None)
    conn.executemany(
        "INSERT INTO assessments (cell_id, source, cycle, soh, soh_lo, resistance_growth, cycles_left, grade,"
        " grade_reference, application, confidence, recommendation, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(r.cell_id, "pipeline", r.cycle, r.soh_est, r.soh_lo, r.resistance_growth, r.cycles_to_floor_pred,
          r.grade_pred, r.grade_true, r.application, r.confidence, r.recommendation, stamp)
         for r in a.itertuples()])

    if CTX.actors_file.exists():
        save_actors(conn, store.load_registry(CTX.actors_file))
    conn.execute("DELETE FROM passports WHERE origin IN ('lab', 'hardware')")
    n = 0
    for pid in store.list_passports(CTX.passports):
        save_passport(conn, store.load_passport(pid, CTX.passports))
        n += 1
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('source_stamp', ?)", (_source_stamp(),))
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('synced_at', ?)", (stamp,))
    conn.commit()
    return {"cells": int(df["cell_id"].nunique()), "cycles": len(df), "assessments": len(a), "passports": n}


def ensure() -> None:
    """Create or refresh the database if the pipeline files changed since the last sync."""
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        row = conn.execute("SELECT value FROM meta WHERE key = 'source_stamp'").fetchone()
        if row is None or row["value"] != _source_stamp():
            sync_from_files(conn)
        from .auth import seed_users
        seed_users(conn)
        conn.commit()
    finally:
        conn.close()


def table_counts(conn) -> dict:
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("datasets", "cells", "cycles", "assessments", "actors", "passports", "events",
                      "users", "uploads", "audit_log")}

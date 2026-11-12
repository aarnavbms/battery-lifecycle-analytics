"""REST API, version 1. Mounted at /api/v1 by dashboard/app.py.

Every route here is described in the OpenAPI document served at
/api/v1/openapi.json (see openapi.py) and shown on the "API" page.
Errors always have the shape {"error": {"code": ..., "message": ...}}.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, Response, g, jsonify, request

from batterylife.lifecycle.grading import assess
from batterylife.lifecycle.sustainability import value
from batterylife.passport import store
from batterylife.passport.ledger import verify
from batterylife.passport.schema import EVENT_TYPES, PUBLIC, REQUIRED_FIELDS, SECTIONS
from batterylife.service import CTX, analysis, auth, db, explain, network, passport_pdf

api = Blueprint("api_v1", __name__, url_prefix="/api/v1")
VERSION = "1.1.0"


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _err(status, code, message):
    return jsonify({"error": {"code": code, "message": message}}), status


@api.errorhandler(ApiError)
def _api_error(e):
    return _err(e.status, e.code, e.message)


@api.errorhandler(auth.AuthError)
def _auth_error(e):
    return _err(e.status, "unauthorized" if e.status == 401 else "forbidden" if e.status == 403 else "not_found", e.message)


@api.errorhandler(analysis.UploadError)
def _upload_error(e):
    return _err(422, "invalid_file", str(e))


@api.errorhandler(413)
def _too_large(e):
    return _err(413, "file_too_large", "The file is larger than 5 MB.")


@api.before_request
def _open():
    db.ensure()
    g.conn = db.connect()
    g.user = auth.user_from_header(request.headers.get("Authorization"))


@api.teardown_request
def _close(exc):
    conn = g.pop("conn", None)
    if conn is not None:
        conn.close()


def _body() -> dict:
    b = request.get_json(silent=True)
    if not isinstance(b, dict):
        raise ApiError(400, "bad_request", "Send a JSON object in the request body.")
    return b


def _int_arg(name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(request.args.get(name, default))))
    except ValueError:
        raise ApiError(400, "bad_request", f"'{name}' must be a whole number.")


# ------------------------------------------------------------------ system
@api.get("/health")
def health():
    return jsonify({"status": "ok", "version": VERSION, "demo_sign_in": auth.demo_enabled(),
                    "database": db.table_counts(g.conn)})


@api.get("/openapi.json")
def openapi():
    from .openapi import spec
    return jsonify(spec(VERSION))


# ------------------------------------------------------------------ accounts
@api.post("/auth/login")
def login():
    b = _body()
    out = auth.login(g.conn, str(b.get("username", "")), str(b.get("password", "")))
    db.audit(g.conn, out["user"], "auth.login")
    g.conn.commit()
    return jsonify(out)


@api.post("/auth/demo")
def demo_login():
    out = auth.demo_login(g.conn, str(_body().get("role", "")))
    db.audit(g.conn, out["user"], "auth.demo_login")
    g.conn.commit()
    return jsonify(out)


@api.get("/auth/me")
def me():
    if g.user is None:
        return jsonify({"username": None, "name": "Public visitor", "role": "public", "permissions": [], "may_sign": []})
    return jsonify(auth.describe(g.user))


@api.get("/auth/roles")
def roles():
    return jsonify({"demo_sign_in": auth.demo_enabled(),
                    "roles": [{"role": r, "description": d,
                               "permissions": sorted(p for p in auth.PERMISSIONS if auth.can(r, p)),
                               "may_sign": auth.events_allowed(r)} for r, d in auth.ROLES.items()]})


# ------------------------------------------------------------------ cells
@api.get("/cells")
def cells():
    q, args = "SELECT * FROM cells WHERE 1=1", []
    for col, key in (("origin", "origin"), ("dataset_key", "dataset")):
        if request.args.get(key):
            q += f" AND {col} = ?"
            args.append(request.args[key])
    return jsonify(db.rows(g.conn.execute(q + " ORDER BY origin, cell_id", args)))


def _cell(cell_id):
    row = g.conn.execute("SELECT * FROM cells WHERE cell_id = ?", (cell_id,)).fetchone()
    if row is None:
        raise ApiError(404, "not_found", f"No cell '{cell_id}'.")
    return dict(row)


@api.get("/cells/<cell_id>")
def cell(cell_id):
    c = _cell(cell_id)
    c["assessments"] = db.rows(g.conn.execute(
        "SELECT cycle, soh, soh_lo, resistance_growth, cycles_left, grade, grade_reference, application, confidence,"
        " recommendation, source FROM assessments WHERE cell_id = ? ORDER BY cycle", (cell_id,)))
    return jsonify(c)


@api.get("/cells/<cell_id>/cycles")
def cell_cycles(cell_id):
    _cell(cell_id)
    limit, offset = _int_arg("limit", 500, 1, 5000), _int_arg("offset", 0, 0, 10 ** 7)
    total = g.conn.execute("SELECT COUNT(*) FROM cycles WHERE cell_id = ?", (cell_id,)).fetchone()[0]
    items = db.rows(g.conn.execute("SELECT * FROM cycles WHERE cell_id = ? ORDER BY cycle LIMIT ? OFFSET ?",
                                   (cell_id, limit, offset)))
    return jsonify({"cell_id": cell_id, "total": total, "limit": limit, "offset": offset, "items": items})


@api.get("/assessments")
def assessments():
    q, args = "SELECT * FROM assessments WHERE 1=1", []
    for key in ("cell_id", "grade", "confidence", "source"):
        if request.args.get(key):
            q += f" AND {key} = ?"
            args.append(request.args[key])
    return jsonify(db.rows(g.conn.execute(q + " ORDER BY cell_id, cycle LIMIT 2000", args)))


@api.post("/grade")
def grade():
    b = _body()
    try:
        soh = float(b["soh"])
        lo = float(b["soh_lo"]) if b.get("soh_lo") is not None else None
        rg = float(b["resistance_growth"]) if b.get("resistance_growth") is not None else None
        cyc = float(b["cycles_left"]) if b.get("cycles_left") is not None else None
        cyc_lo = float(b["cycles_left_lo"]) if b.get("cycles_left_lo") is not None else None
    except (KeyError, TypeError, ValueError):
        raise ApiError(400, "bad_request", "Give 'soh' as a number; soh_lo, resistance_growth, cycles_left are optional numbers.")
    if not 0 < soh <= 1.2:
        raise ApiError(400, "bad_request", "soh must be between 0 and 1.2 (0.78 means 78%).")
    r = assess(soh, lo, rg, cyc, cyc_lo)
    return jsonify({**r.to_dict(), "value": value(r.grade, soh, "nasa")})


# ------------------------------------------------------------------ uploads
@api.post("/uploads")
def upload_create():
    user = auth.require(g.user, "upload:create")
    f = request.files.get("file")
    if f is None or not f.filename:
        raise ApiError(400, "bad_request", "Attach a CSV file in the form field 'file'.")
    try:
        rated = float(request.form.get("rated_capacity_ah", ""))
    except ValueError:
        raise ApiError(400, "bad_request", "Give 'rated_capacity_ah' as a number, for example 2.0.")
    issue = request.form.get("issue_passports", "true").lower() not in ("0", "false", "no")
    out = analysis.analyse_upload(f.read(), f.filename, rated, request.form.get("profile", "other"), issue, user)
    return jsonify(out), 201


@api.get("/uploads")
def upload_list():
    auth.require(g.user, "upload:read")
    return jsonify(db.rows(g.conn.execute(
        "SELECT upload_id, filename, username, created_at, n_cells, n_rows FROM uploads ORDER BY created_at DESC")))


@api.get("/uploads/<upload_id>")
def upload_get(upload_id):
    auth.require(g.user, "upload:read")
    row = g.conn.execute("SELECT result FROM uploads WHERE upload_id = ?", (upload_id,)).fetchone()
    if row is None:
        raise ApiError(404, "not_found", f"No upload '{upload_id}'.")
    return Response(row["result"], mimetype="application/json")


@api.delete("/uploads/<upload_id>")
def upload_delete(upload_id):
    user = auth.require(g.user, "upload:create")
    if g.conn.execute("SELECT 1 FROM uploads WHERE upload_id = ?", (upload_id,)).fetchone() is None:
        raise ApiError(404, "not_found", f"No upload '{upload_id}'.")
    g.conn.execute("DELETE FROM passports WHERE passport_id LIKE ?", (f"DBP-UP-{upload_id}-%",))
    g.conn.execute("DELETE FROM uploads WHERE upload_id = ?", (upload_id,))
    db.audit(g.conn, user, "upload.delete", upload_id)
    g.conn.commit()
    return "", 204


# ------------------------------------------------------------------ passports
def _access() -> str:
    """Full view only for signed-in roles with a legitimate interest; everyone else gets the public tier."""
    full = g.user is not None and auth.can(g.user["role"], "passport:read_full")
    if full and request.args.get("access") == "public":
        return PUBLIC
    return "full" if full else PUBLIC


def _passport(pid):
    p = db.load_passport(g.conn, pid)
    if p is None:
        raise ApiError(404, "not_found", f"No passport '{pid}'.")
    return p


@api.get("/passports")
def passports():
    reg = db.registry(g.conn)
    out = []
    for row in db.list_passports(g.conn):
        if request.args.get("origin") and row["origin"] != request.args["origin"]:
            continue
        row["valid"] = verify(db.load_passport(g.conn, row["passport_id"]), reg)["valid"]
        if _access() == PUBLIC:
            row.pop("grade")                 # the lifecycle decision is restricted content
        out.append(row)
    return jsonify(out)


@api.get("/passports/<pid>")
def passport(pid):
    p = _passport(pid)
    access = _access()
    d = p.to_dict(access)
    d.update({"status": p.status(), "origin": db.passport_origin(pid), "total_events": len(p.events),
              "viewer_role": g.user["role"] if g.user else "public",
              "section_access": SECTIONS,
              "event_meta": {k: {"roles": sorted(v[0]), "access": v[1]} for k, v in EVENT_TYPES.items()},
              "actors": db.registry(g.conn).to_dict()})
    return jsonify(d)


@api.post("/passports/<pid>/verify")
def passport_verify(pid):
    return jsonify(verify(_passport(pid), db.registry(g.conn)))


@api.get("/passports/<pid>/pdf")
def passport_pdf_file(pid):
    p = _passport(pid)
    pdf = passport_pdf.build(p, verify(p, db.registry(g.conn)), _access(), request.host_url)
    return Response(pdf, mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{pid}.pdf"'})


@api.post("/passports/<pid>/events")
def passport_append(pid):
    """Record a lifecycle event. The signed-in user's role decides which event types are allowed."""
    if g.user is None:
        raise auth.AuthError(401, "Sign in first: only an actor with the right role can add a passport event.")
    p = _passport(pid)
    if db.passport_origin(pid) == "lab":
        raise ApiError(409, "read_only", "Passports of the laboratory cells are archived results and cannot be "
                                         "changed. Upload a battery and add events to its passport instead.")
    b = _body()
    etype, data = str(b.get("type", "")), b.get("data") or {}
    if etype not in EVENT_TYPES:
        raise ApiError(400, "bad_request", f"Unknown event type. Use one of: {', '.join(EVENT_TYPES)}.")
    if not isinstance(data, dict):
        raise ApiError(400, "bad_request", "'data' must be a JSON object.")
    role = g.user["role"]
    if role not in EVENT_TYPES[etype][0]:
        allowed = ", ".join(sorted(EVENT_TYPES[etype][0]))
        raise auth.AuthError(403, f"Role '{role}' may not sign {etype}. Allowed roles: {allowed}.")
    missing = [f for f in REQUIRED_FIELDS.get(etype, []) if f not in data]
    if missing:
        raise ApiError(422, "missing_fields", f"{etype} needs these fields in 'data': {', '.join(missing)}.")
    if p.latest("RECYCLED") is not None:
        raise ApiError(409, "closed", "This battery has been recycled; its passport is closed.")
    reg = store.signing_registry(CTX.keys, CTX.actors_file)
    actor = store.signer(reg, role, CTX.keys, CTX.actors_file)
    last = max(datetime.fromisoformat(e["timestamp"]) for e in p.events)
    ts = max(datetime.fromisoformat(db.now()), last + timedelta(seconds=1)).isoformat()
    ev = p.append(actor, etype, {**data, "recorded_by": g.user["username"]}, ts)
    db.save_actors(g.conn, reg)
    db.save_passport(g.conn, p)
    db.audit(g.conn, g.user, "passport.append", pid, f"{etype} signed by {actor.actor_id}")
    g.conn.commit()
    return jsonify({"event": ev, "status": p.status(), "events": len(p.events), "head_hash": p.head_hash,
                    "valid": verify(p, db.registry(g.conn))["valid"]}), 201


# ------------------------------------------------------------------ analysis
@api.get("/network")
def network_view():
    return jsonify(network.build(g.conn, request.args.get("include_uploads") in ("1", "true")))


@api.get("/explain")
def explain_view():
    out = explain.load()
    if out is None:
        raise ApiError(404, "not_found", "Run `python -m batterylife explain` to compute explainability results.")
    return jsonify(out)


@api.get("/audit")
def audit_log():
    auth.require(g.user, "audit:read")
    limit = _int_arg("limit", 100, 1, 1000)
    return jsonify(db.rows(g.conn.execute("SELECT * FROM audit_log ORDER BY audit_id DESC LIMIT ?", (limit,))))

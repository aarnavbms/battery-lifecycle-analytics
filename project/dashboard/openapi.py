"""OpenAPI 3.0 description of the REST API (served at /api/v1/openapi.json).

Kept next to the routes; tests/test_api.py fails if a route is added without
being described here.
"""
from __future__ import annotations

from batterylife.passport.schema import EVENT_TYPES
from batterylife.service.analysis import PROFILES
from batterylife.service.auth import ROLES

ERR = {"type": "object", "properties": {"error": {"type": "object", "properties": {
    "code": {"type": "string"}, "message": {"type": "string"}}}}}


def _resp(desc, example=None, *errors):
    out = {"200": {"description": desc, "content": {"application/json": {"example": example}} if example is not None else {}}}
    names = {400: "Bad request", 401: "Not signed in", 403: "Role not allowed", 404: "Not found",
             409: "Not allowed in this state", 413: "File too large", 422: "File or data cannot be used"}
    for code in errors:
        out[str(code)] = {"description": names[code], "content": {"application/json": {"schema": ERR}}}
    return out


def _p(name, where="path", desc="", example=None, required=None, enum=None):
    s = {"type": "string"}
    if enum:
        s["enum"] = enum
    return {"name": name, "in": where, "required": where == "path" if required is None else required,
            "description": desc, "schema": s, **({"example": example} if example is not None else {})}


def _json(example, required=True):
    return {"required": required, "content": {"application/json": {"example": example}}}


def spec(version: str) -> dict:
    lock = [{"bearer": []}]
    pid = _p("pid", desc="Passport id", example="DBP-CALCE-CS2_36")
    cid = _p("cell_id", desc="Cell id", example="B0005")
    paths = {
        "/health": {"get": {"tags": ["System"], "summary": "Service status and table sizes",
                            "responses": _resp("Status", {"status": "ok", "version": version})}},
        "/openapi.json": {"get": {"tags": ["System"], "summary": "This document", "responses": _resp("OpenAPI 3.0 document")}},
        "/auth/login": {"post": {"tags": ["Accounts"], "summary": "Sign in with a username and password",
                                 "description": "Returns a bearer token valid for 8 hours. Send it as `Authorization: Bearer <token>`.",
                                 "requestBody": _json({"username": "assessor", "password": "(see batterylife/service/demo_users.json)"}),
                                 "responses": _resp("Token and user", {"token": "eyJ...", "token_type": "Bearer", "expires_in": 28800,
                                                                       "user": {"username": "assessor", "role": "assessor"}}, 400, 401)}},
        "/auth/demo": {"post": {"tags": ["Accounts"], "summary": "One-click demo sign-in as a role",
                                "description": "Only while the server runs with BLA_DEMO=1 (the default for local use).",
                                "requestBody": _json({"role": "assessor"}),
                                "responses": _resp("Token and user", None, 403, 404)}},
        "/auth/me": {"get": {"tags": ["Accounts"], "summary": "Who am I, and what may I do",
                             "security": lock, "responses": _resp("Current user (role 'public' without a token)", None, 401)}},
        "/auth/roles": {"get": {"tags": ["Accounts"], "summary": "All roles with their permissions",
                                "responses": _resp("Role catalogue")}},
        "/cells": {"get": {"tags": ["Cells"], "summary": "List batteries",
                           "parameters": [_p("origin", "query", "Where the data came from", enum=["lab", "hardware", "upload"]),
                                          _p("dataset", "query", "Dataset key", enum=["nasa", "calce", "hardware", "upload"])],
                           "responses": _resp("Cells", [{"cell_id": "B0005", "dataset_key": "nasa", "origin": "lab",
                                                         "rated_capacity_ah": 2.0, "n_cycles": 168}])}},
        "/cells/{cell_id}": {"get": {"tags": ["Cells"], "summary": "One battery with its grading decisions",
                                     "parameters": [cid], "responses": _resp("Cell", None, 404)}},
        "/cells/{cell_id}/cycles": {"get": {"tags": ["Cells"], "summary": "Cycle-by-cycle data with model estimates (paged)",
                                            "parameters": [cid, _p("limit", "query", "Rows per page, 1-5000", "500"),
                                                           _p("offset", "query", "Rows to skip", "0")],
                                            "responses": _resp("Page of cycles", None, 400, 404)}},
        "/assessments": {"get": {"tags": ["Second life"], "summary": "Second-life grading decisions",
                                 "parameters": [_p("cell_id", "query"), _p("grade", "query", enum=list("ABCD")),
                                                _p("confidence", "query", enum=["high", "low"]),
                                                _p("source", "query", enum=["pipeline", "upload"])],
                                 "responses": _resp("Assessments")}},
        "/grade": {"post": {"tags": ["Second life"], "summary": "Grade a battery from its numbers",
                            "requestBody": _json({"soh": 0.78, "soh_lo": 0.75, "resistance_growth": 1.15,
                                                  "cycles_left": 250, "cycles_left_lo": 180}),
                            "responses": _resp("Grade, application, confidence and value",
                                               {"grade": "B", "application": "Grid / home energy storage", "confidence": "low"}, 400)}},
        "/uploads": {
            "post": {"tags": ["Uploads"], "summary": "Assess your own battery data (CSV)", "security": lock,
                     "description": "One row per cycle. Needs `cycle` and `capacity_ah` (or the four charging signals). "
                                    "A `cell_id` column allows several batteries in one file; they come back ranked. "
                                    "Roles: assessor, admin.",
                     "requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {
                         "type": "object", "required": ["file", "rated_capacity_ah"], "properties": {
                             "file": {"type": "string", "format": "binary"},
                             "rated_capacity_ah": {"type": "number", "example": 2.5},
                             "profile": {"type": "string", "enum": list(PROFILES), "default": "other"},
                             "issue_passports": {"type": "boolean", "default": True}}}}}},
                     "responses": {"201": {"description": "Ranked results, one per battery"},
                                   **{k: v for k, v in _resp("", None, 400, 401, 403, 413, 422).items() if k != "200"}}},
            "get": {"tags": ["Uploads"], "summary": "List uploads", "security": lock,
                    "responses": _resp("Uploads", None, 401, 403)}},
        "/uploads/{upload_id}": {
            "get": {"tags": ["Uploads"], "summary": "Stored result of one upload", "security": lock,
                    "parameters": [_p("upload_id")], "responses": _resp("Result", None, 401, 403, 404)},
            "delete": {"tags": ["Uploads"], "summary": "Delete an upload, its cells and passports", "security": lock,
                       "parameters": [_p("upload_id")],
                       "responses": {"204": {"description": "Deleted"},
                                     **{k: v for k, v in _resp("", None, 401, 403, 404).items() if k != "200"}}}},
        "/passports": {"get": {"tags": ["Passports"], "summary": "List passports with their verification result",
                               "parameters": [_p("origin", "query", enum=["lab", "hardware", "upload"])],
                               "responses": _resp("Passports")}},
        "/passports/{pid}": {"get": {"tags": ["Passports"], "summary": "Read a passport",
                                     "description": "Without a token you get the public tier. A signed-in role with a "
                                                    "legitimate interest gets the full passport; add `?access=public` to preview the public tier.",
                                     "security": [{}, {"bearer": []}],
                                     "parameters": [pid, _p("access", "query", enum=["public"])],
                                     "responses": _resp("Passport sections and signed events", None, 404)}},
        "/passports/{pid}/verify": {"post": {"tags": ["Passports"], "summary": "Run the six integrity checks",
                                             "parameters": [pid],
                                             "responses": _resp("Verification result", {"valid": True, "events": 24, "checks": {
                                                 "chain": True, "content": True, "signatures": True, "roles": True,
                                                 "fields": True, "chronology": True}}, 404)}},
        "/passports/{pid}/pdf": {"get": {"tags": ["Passports"], "summary": "Printable passport with a QR code (PDF)",
                                         "security": [{}, {"bearer": []}], "parameters": [pid],
                                         "responses": {"200": {"description": "PDF", "content": {"application/pdf": {}}},
                                                       "404": _resp("", None, 404)["404"]}}},
        "/passports/{pid}/events": {"post": {
            "tags": ["Passports"], "summary": "Record a lifecycle event, signed for your role", "security": lock,
            "description": "The event type must be one your role may sign. Laboratory passports are read-only; "
                           "use a passport created by an upload.",
            "parameters": [_p("pid", desc="Passport id", example="DBP-UP-1A2B3C-CELL-1")],
            "requestBody": _json({"type": "REPURPOSED", "data": {"application": "Home energy storage", "new_status": "repurposed"}}),
            "responses": {"201": {"description": "The signed event"},
                          **{k: v for k, v in _resp("", None, 400, 401, 403, 404, 409, 422).items() if k != "200"}}}},
        "/network": {"get": {"tags": ["Analysis"], "summary": "Hand-off and process networks with centrality measures",
                             "parameters": [_p("include_uploads", "query", enum=["1"])],
                             "responses": _resp("Nodes, edges and measures")}},
        "/explain": {"get": {"tags": ["Analysis"], "summary": "Which signals the SOH model relies on",
                             "responses": _resp("Permutation importance per dataset", None, 404)}},
        "/audit": {"get": {"tags": ["System"], "summary": "Audit log (regulator, admin)", "security": lock,
                           "parameters": [_p("limit", "query", "1-1000", "100")],
                           "responses": _resp("Latest entries first", None, 400, 401, 403)}},
    }
    return {
        "openapi": "3.0.3",
        "info": {"title": "Battery Lifecycle Analytics API", "version": version,
                 "description": "Battery health, second-life grading and Digital Battery Passports. "
                                "Reading is open; changing anything needs a signed-in role."},
        "servers": [{"url": "/api/v1"}],
        "tags": [{"name": n} for n in ("System", "Accounts", "Cells", "Second life", "Uploads", "Passports", "Analysis")],
        "components": {"securitySchemes": {"bearer": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}},
                       "schemas": {"Error": ERR}},
        "x-roles": ROLES,
        "x-event-types": {k: sorted(v[0]) for k, v in EVENT_TYPES.items()},
        "paths": paths,
    }

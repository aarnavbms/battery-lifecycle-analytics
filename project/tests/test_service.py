"""Service layer and REST API: database, roles, uploads, network, PDF passports.

Everything runs against a temporary database and an empty key folder, which is
the situation on a fresh clone (private keys are not shipped).
"""
import io
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from batterylife.config import PASSPORT_DIR, RESULTS_DIR, ROOT
from batterylife.passport.ledger import verify
from batterylife.service import CTX, analysis, auth, db, network

pytestmark = pytest.mark.skipif(not (RESULTS_DIR / "summary.json").exists(),
                                reason="run `python -m batterylife run` first")
SAMPLES = ROOT / "data" / "samples"
FLEET = SAMPLES / "sample_fleet_12_cells_synthetic.csv"
NASA = SAMPLES / "sample_single_cell_nasa_B0005.csv"


@pytest.fixture(scope="module")
def ctx(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("service")
    old = (CTX.db, CTX.keys, CTX.actors_file)
    CTX.db, CTX.keys, CTX.actors_file = tmp / "test.db", tmp / "keys", tmp / "actors.json"
    shutil.copy(PASSPORT_DIR / "actors.json", CTX.actors_file)
    db.ensure()
    yield tmp
    CTX.db, CTX.keys, CTX.actors_file = old


@pytest.fixture(scope="module")
def client(ctx):
    from dashboard.app import app
    return app.test_client()


def token(client, role):
    return {"Authorization": "Bearer " + client.post("/api/v1/auth/demo", json={"role": role}).get_json()["token"]}


@pytest.fixture(scope="module")
def fleet(client):
    r = client.post("/api/v1/uploads", headers=token(client, "assessor"),
                    data={"file": (io.BytesIO(FLEET.read_bytes()), "fleet.csv"), "rated_capacity_ah": "2.5"})
    assert r.status_code == 201, r.get_data(as_text=True)
    return r.get_json()


# ------------------------------------------------------------------ database
def test_database_mirrors_pipeline_files(ctx):
    conn = db.connect()
    n = db.table_counts(conn)
    assert n["cells"] >= 8 and n["cycles"] >= 4631 and n["assessments"] >= 101 and n["users"] == 7
    assert conn.execute("SELECT COUNT(*) FROM cells WHERE origin = 'lab'").fetchone()[0] == 8


def test_passports_loaded_from_database_still_verify(ctx):
    conn = db.connect()
    reg = db.registry(conn)
    lab = [p for p in db.list_passports(conn) if p["origin"] == "lab"]
    assert len(lab) == 8
    for row in lab:
        assert verify(db.load_passport(conn, row["passport_id"]), reg)["valid"]


def test_sync_is_repeatable_and_keeps_uploads(ctx, fleet):
    conn = db.connect()
    before = db.table_counts(conn)
    db.sync_from_files(conn)
    assert db.table_counts(conn) == before


# ------------------------------------------------------------------ accounts and roles
def test_login_checks_the_password(client):
    users = json.loads((ROOT / "batterylife/service/demo_users.json").read_text())["users"]
    u = next(x for x in users if x["role"] == "recycler")
    ok = client.post("/api/v1/auth/login", json={"username": u["username"], "password": u["password"]})
    assert ok.status_code == 200 and ok.get_json()["user"]["role"] == "recycler"
    bad = client.post("/api/v1/auth/login", json={"username": u["username"], "password": "wrong"})
    assert bad.status_code == 401 and bad.get_json()["error"]["code"] == "unauthorized"


def test_tampered_token_is_rejected(client):
    h = token(client, "assessor")
    h["Authorization"] = h["Authorization"][:-3] + "abc"
    assert client.get("/api/v1/auth/me", headers=h).status_code == 401


def test_role_permissions():
    assert auth.can("assessor", "upload:create") and not auth.can("recycler", "upload:create")
    assert auth.can("regulator", "audit:read") and not auth.can("assessor", "audit:read")
    assert auth.events_allowed("recycler") == ["RECYCLED", "SENT_TO_RECYCLING"]


def test_public_sees_public_tier_only(client):
    pub = client.get("/api/v1/passports/DBP-CALCE-CS2_36").get_json()
    assert pub["access_level"] == "public" and "state_of_health" not in pub["sections"]
    assert all(e["type"] not in ("SOH_ASSESSMENT", "SECOND_LIFE_GRADING") for e in pub["events"])
    full = client.get("/api/v1/passports/DBP-CALCE-CS2_36", headers=token(client, "recycler")).get_json()
    assert full["access_level"] == "full" and len(full["events"]) == full["total_events"] > len(pub["events"])
    # the dashboard's own endpoint enforces the same rule
    assert client.get("/api/passport/DBP-CALCE-CS2_36?access=full").status_code == 403
    assert "grade" not in client.get("/api/v1/passports").get_json()[0]


def test_audit_log_is_for_regulators(client, fleet):
    assert client.get("/api/v1/audit").status_code == 401
    assert client.get("/api/v1/audit", headers=token(client, "assessor")).status_code == 403
    log = client.get("/api/v1/audit", headers=token(client, "regulator")).get_json()
    assert any(e["action"] == "upload.create" and e["username"] == "assessor" for e in log)


# ------------------------------------------------------------------ uploads
def test_upload_needs_the_assessor_role(client):
    data = lambda: {"file": (io.BytesIO(FLEET.read_bytes()), "fleet.csv"), "rated_capacity_ah": "2.5"}  # noqa: E731
    assert client.post("/api/v1/uploads", data=data()).status_code == 401
    assert client.post("/api/v1/uploads", data=data(), headers=token(client, "recycler")).status_code == 403


def test_fleet_upload_is_ranked_graded_and_signed(fleet):
    assert fleet["batteries"] == 12 and sum(fleet["grades"].values()) == 12 and not fleet["failed"]
    ranks = ["ABCD".index(r["grade"]) for r in fleet["results"]]
    assert ranks == sorted(ranks) and [r["rank"] for r in fleet["results"]] == list(range(1, 13))
    assert all(r["passport_valid"] and 0.4 < r["soh"] < 1.1 and r["soh_lo"] < r["soh"] for r in fleet["results"])
    assert len(set(fleet["grades"].values())) > 1          # the sample spans several grades


def test_fresh_machine_enrols_its_own_signing_actors(ctx, fleet):
    """No private keys were shipped, so local actors were created and added to the directory."""
    conn = db.connect()
    ids = [r["actor_id"] for r in conn.execute("SELECT actor_id FROM actors")]
    assert "ASSESSOR-LOCAL-1" in ids and "AI-ASSESSOR" in ids
    original = json.loads((PASSPORT_DIR / "actors.json").read_text())
    kept = json.loads(CTX.actors_file.read_text())
    assert all(kept[a]["public_key"] == original[a]["public_key"] for a in original)   # never replaced


def test_uploaded_cells_are_queryable(client, fleet):
    cells = client.get("/api/v1/cells?origin=upload").get_json()
    assert len(cells) >= 12
    page = client.get(f"/api/v1/cells/{fleet['results'][0]['db_cell_id']}/cycles?limit=5").get_json()
    assert len(page["items"]) == 5 and page["total"] == fleet["results"][0]["cycles"]


def test_ai_estimate_without_a_discharge_test(ctx):
    """Charging signals only, known cell type: health comes from the model."""
    df = pd.read_csv(NASA).drop(columns=["capacity_ah"])
    out = analysis.analyse_only(df.to_csv(index=False).encode(), "nocap.csv", 2.0, "nasa")
    r = out["results"][0]
    truth = pd.read_csv(NASA)["capacity_ah"].iloc[-9:].median() / 2.0
    assert r["soh_source"] == "estimated" and abs(r["soh"] - truth) < 0.06


def test_measured_and_estimated_are_compared(ctx):
    r = analysis.analyse_only(NASA.read_bytes(), "b5.csv", 2.0, "nasa")["results"][0]
    assert r["soh_source"] == "measured" and r["model_check"]["in_training_data"] is True
    assert r["model_check"]["mae"] < 0.05


@pytest.mark.parametrize("text,rated,needle", [
    ("a,b\n1,2\n", 2.0, "cycle"),
    ("cycle,voltage\n1,3.7\n", 2.0, "capacity_ah"),
    ("cycle,capacity_ah\n1,5.0\n2,5.0\n", 2.0, "rated capacity"),
    ("cycle,capacity_ah\n", 2.0, "no data rows"),
])
def test_bad_files_get_a_clear_message(client, text, rated, needle):
    r = client.post("/api/v1/uploads", headers=token(client, "assessor"),
                    data={"file": (io.BytesIO(text.encode()), "bad.csv"), "rated_capacity_ah": str(rated)})
    assert r.status_code == 422 and needle in r.get_json()["error"]["message"]


def test_short_history_gives_health_but_no_forecast(ctx):
    r = analysis.analyse_only(b"cycle,capacity_ah\n1,1.9\n2,1.89\n3,1.88\n", "short.csv", 2.0)["results"][0]
    assert r["rul"] == {} and r["grade"] in "ABCD" and any("no remaining-life forecast" in n for n in r["notes"])


# ------------------------------------------------------------------ signing events by role
def test_role_decides_which_events_may_be_signed(client, fleet):
    pid = fleet["results"][0]["passport_id"]
    body = {"type": "REPURPOSED", "data": {"application": "Home storage", "new_status": "repurposed"}}
    assert client.post(f"/api/v1/passports/{pid}/events", json=body).status_code == 401
    assert client.post(f"/api/v1/passports/{pid}/events", json=body, headers=token(client, "recycler")).status_code == 403
    ok = client.post(f"/api/v1/passports/{pid}/events", json=body, headers=token(client, "repurposer"))
    assert ok.status_code == 201 and ok.get_json()["valid"] and ok.get_json()["status"] == "repurposed"
    assert ok.get_json()["event"]["role"] == "repurposer"
    assert client.post(f"/api/v1/passports/{pid}/verify").get_json()["valid"]


def test_missing_fields_and_closed_passports(client, fleet):
    pid = fleet["results"][1]["passport_id"]
    r = client.post(f"/api/v1/passports/{pid}/events", headers=token(client, "assessor"),
                    json={"type": "SOH_ASSESSMENT", "data": {"cycle": 1}})
    assert r.status_code == 422 and "soh" in r.get_json()["error"]["message"]
    rec = token(client, "recycler")
    assert client.post(f"/api/v1/passports/{pid}/events", headers=rec, json={"type": "RECYCLED", "data": {}}).status_code == 201
    again = client.post(f"/api/v1/passports/{pid}/events", headers=rec, json={"type": "RECYCLED", "data": {}})
    assert again.status_code == 409


def test_laboratory_passports_are_read_only(client):
    r = client.post("/api/v1/passports/DBP-NASA-B0005/events", headers=token(client, "recycler"),
                    json={"type": "RECYCLED", "data": {}})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "read_only"


# ------------------------------------------------------------------ documents, network, docs
def test_pdf_passport(client):
    r = client.get("/api/v1/passports/DBP-CALCE-CS2_36/pdf")
    assert r.status_code == 200 and r.mimetype == "application/pdf" and r.data[:5] == b"%PDF-"
    full = client.get("/api/v1/passports/DBP-CALCE-CS2_36/pdf", headers=token(client, "regulator"))
    assert len(full.data) > len(r.data)          # the full copy has more sections and events


def test_network_measures(ctx):
    n = network.build(db.connect())
    ids = {x["id"] for x in n["handoff"]["nodes"]}
    assert {"MFR-01", "OEM-01", "AI-ASSESSOR", "REP-01", "REC-01"} <= ids
    assert n["findings"]["broker"] == "AI-ASSESSOR"
    assert abs(sum(x["pagerank"] for x in n["handoff"]["nodes"]) - 1) < 0.01
    edges = {(e["source"], e["target"]): e["weight"] for e in n["handoff"]["edges"]}
    assert edges[("MFR-01", "OEM-01")] == 8        # every lab cell goes from maker to vehicle maker
    assert sum(p["batteries"] for p in n["paths"]) == n["passports"]


def test_every_route_is_documented(client):
    from dashboard.app import app
    spec = client.get("/api/v1/openapi.json").get_json()
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/api/v1/") or rule.rule == "/api/v1/docs":
            continue
        path = rule.rule[len("/api/v1"):].replace("<", "{").replace(">", "}")
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            assert method.lower() in spec["paths"].get(path, {}), f"{method} {path} missing from openapi.py"


@pytest.mark.parametrize("url", ["/assess", "/network", "/developers"])
def test_new_pages_render(client, url):
    assert client.get(url).status_code == 200


def test_delete_upload_removes_its_data(client):
    h = token(client, "assessor")
    up = client.post("/api/v1/uploads", headers=h, data={"file": (io.BytesIO(NASA.read_bytes()), "one.csv"),
                                                         "rated_capacity_ah": "2.0", "profile": "nasa"}).get_json()
    pid = up["results"][0]["passport_id"]
    assert client.delete(f"/api/v1/uploads/{up['upload_id']}", headers=h).status_code == 204
    assert client.get(f"/api/v1/passports/{pid}").status_code == 404
    assert client.get(f"/api/v1/cells/{up['results'][0]['db_cell_id']}").status_code == 404

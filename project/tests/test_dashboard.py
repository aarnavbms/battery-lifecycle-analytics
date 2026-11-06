"""Dashboard API tests with Flask's test client (no server needed)."""
import json

import pytest

from batterylife.config import RESULTS_DIR

pytestmark = pytest.mark.skipif(not (RESULTS_DIR / "summary.json").exists(),
                                reason="run `python -m batterylife run` first")


@pytest.fixture(scope="module")
def client():
    from dashboard.app import app
    return app.test_client()


@pytest.mark.parametrize("url", ["/", "/cells", "/models", "/second-life", "/passports", "/hardware", "/reports"])
def test_pages_render(client, url):
    r = client.get(url)
    assert r.status_code == 200 and b"Battery Lifecycle Analytics" in r.data


def test_summary_is_strict_json(client):
    r = client.get("/api/summary")
    json.loads(r.data.decode())          # NaN would raise here
    assert r.get_json()["data"]["cells"] == 8


def test_cell_endpoint(client):
    d = client.get("/api/cell/CS2_36").get_json()
    assert d["dataset"] == "calce" and len(d["series"]["cycle"]) == len(d["series"]["soh"])
    assert client.get("/api/cell/NOPE").status_code == 404


def test_assess_endpoint(client):
    r = client.post("/api/assess", json={"soh": 0.78, "halfwidth": 0.03, "resistance_growth": 1.15,
                                         "cycles": 250, "cycles_lo": 180}).get_json()
    assert r["grade"] == "B" and r["confidence"] == "low"
    bad = client.post("/api/assess", json={"soh": "abc"})
    assert bad.status_code == 400 and "error" in bad.get_json()


def test_passport_public_view_hides_soh(client):
    pid = client.get("/api/passports").get_json()[0]["passport_id"]
    pub = client.get(f"/api/passport/{pid}?access=public").get_json()
    assert "state_of_health" not in pub["sections"]


@pytest.mark.parametrize("attack,check", [("edit", "content"), ("rehash", "signatures"),
                                          ("delete", "chain"), ("backdate", "chronology"),
                                          ("impostor", "signatures")])
def test_every_attack_is_detected(client, attack, check):
    pid = "DBP-CALCE-CS2_36"
    r = client.post(f"/api/passport/{pid}/tamper", json={"attack": attack}).get_json()
    assert r["result"]["valid"] is False
    assert r["result"]["checks"][check] is False
    # the file on disk is untouched
    assert client.post(f"/api/passport/{pid}/verify").get_json()["valid"] is True


def test_hardware_and_reports_api(client):
    h = client.get("/api/hardware").get_json()
    assert "cycles" in h
    r = client.get("/api/reports").get_json()
    assert isinstance(r, list)
    if r:
        assert client.get(f"/reports/{r[0]['file']}").status_code == 200

import copy

import pytest

from batterylife.passport.ledger import ActorRegistry, Passport, verify
from batterylife.passport.schema import PUBLIC

MAN = {"model": "T-1", "chemistry": "LCO", "form_factor": "18650", "rated_capacity_ah": 2.0,
       "nominal_voltage_v": 3.7, "manufacturer": "Test", "manufacture_date": "2026-01-01"}
SOH = {"cycle": 10, "soh": 0.95, "soh_lo": 0.93, "soh_hi": 0.97, "resistance_growth": 1.02, "method": "GBR"}
GRADE = {"grade": "B", "application": "Grid storage", "confidence": "high", "recommendation": "repurpose"}


@pytest.fixture()
def world():
    reg = ActorRegistry()
    a = {r: reg.create(f"{r.upper()}-1", r, r) for r in
         ("manufacturer", "oem", "bms", "assessor", "repurposer", "recycler")}
    p = Passport("DBP-TEST", "T1")
    p.append(a["manufacturer"], "MANUFACTURED", MAN, "2026-01-01T00:00:00")
    p.append(a["bms"], "SOH_ASSESSMENT", SOH, "2026-02-01T00:00:00")
    p.append(a["assessor"], "SECOND_LIFE_GRADING", GRADE, "2026-03-01T00:00:00")
    p.append(a["repurposer"], "REPURPOSED", {"application": "Grid storage"}, "2026-04-01T00:00:00")
    return reg, a, p


def test_valid_chain(world):
    reg, _, p = world
    r = verify(p, reg)
    assert r["valid"] and r["events"] == 4
    assert p.status() == "repurposed"


def test_round_trip_keeps_validity(world):
    reg, _, p = world
    p2 = Passport.from_dict(p.to_dict())
    assert verify(p2, ActorRegistry.from_dict(reg.to_dict()))["valid"]


def test_tampered_data_detected(world):
    reg, _, p = world
    p.events[1]["data"]["soh"] = 0.99
    r = verify(p, reg)
    assert not r["valid"] and r["first_bad_index"] == 1 and not r["checks"]["content"]


def test_rehashed_forgery_fails_signature(world):
    """An attacker who recomputes the hashes still cannot forge signatures."""
    from batterylife.passport import crypto
    from batterylife.passport.ledger import _body
    reg, _, p = world
    p.events[1]["data"]["soh"] = 0.99
    prev = p.events[0]["hash"]
    for ev in p.events[1:]:
        ev["prev_hash"] = prev
        ev["hash"] = crypto.sha256_hex(_body(ev))
        prev = ev["hash"]
    r = verify(p, reg)
    assert r["checks"]["chain"] and r["checks"]["content"]
    assert not r["checks"]["signatures"] and r["first_bad_index"] == 1


def test_deleted_event_detected(world):
    reg, _, p = world
    del p.events[1]
    r = verify(p, reg)
    assert not r["valid"] and not r["checks"]["chain"]


def test_unauthorised_role_rejected(world):
    _, a, p = world
    with pytest.raises(PermissionError):
        p.append(a["bms"], "SECOND_LIFE_GRADING", GRADE, "2026-05-01T00:00:00")


def test_impostor_signature_detected(world):
    reg, a, p = world
    evil = copy.deepcopy(p)
    # recycler key signs an event while claiming to be the assessor
    ev = evil.events[2]
    from batterylife.passport import crypto
    ev["signature"] = crypto.sign(a["recycler"]._private, ev["hash"])
    assert not verify(evil, reg)["checks"]["signatures"]


def test_missing_fields_rejected(world):
    _, a, p = world
    with pytest.raises(ValueError):
        p.append(a["assessor"], "SECOND_LIFE_GRADING", {"grade": "A"}, "2026-05-01T00:00:00")


def test_signed_data_is_not_aliased(world):
    reg, a, p = world
    data = dict(SOH)
    p.append(a["bms"], "SOH_ASSESSMENT", data, "2026-06-01T00:00:00")
    data["soh"] = 0.10            # caller mutates its own dict afterwards
    assert p.events[-1]["data"]["soh"] == SOH["soh"]
    assert verify(p, reg)["valid"]


def test_public_view_hides_restricted_data(world):
    _, _, p = world
    pub = p.to_dict(PUBLIC)
    assert "state_of_health" not in pub["sections"]
    assert all(e["type"] != "SOH_ASSESSMENT" for e in pub["events"])
    assert pub["sections"]["battery_status"]["status"] == "repurposed"

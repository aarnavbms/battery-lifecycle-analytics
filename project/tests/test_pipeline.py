"""Integration tests on the outputs of `python -m batterylife run`."""
import json

import pytest

from batterylife.config import RESULTS_DIR
from batterylife.passport import store
from batterylife.passport.ledger import verify

pytestmark = pytest.mark.skipif(not (RESULTS_DIR / "summary.json").exists(),
                                reason="run `python -m batterylife run` first")


def test_summary_has_all_cells():
    s = json.loads((RESULTS_DIR / "summary.json").read_text())
    assert s["data"]["cells"] == 8
    assert s["passports"]["issued"] == s["passports"]["valid"] == 8


def test_every_passport_verifies_with_public_keys_only():
    reg = store.load_registry()
    for pid in store.list_passports():
        r = verify(store.load_passport(pid), reg)
        assert r["valid"], (pid, r["issues"][:2])


def test_passport_lifecycle_is_consistent():
    for pid in store.list_passports():
        p = store.load_passport(pid)
        types = [e["type"] for e in p.events]
        assert types[0] == "MANUFACTURED"
        if "REPURPOSED" in types:
            assert types.index("SECOND_LIFE_GRADING") < types.index("REPURPOSED")
            assert types.index("FIRST_LIFE_RETIRED") < types.index("SECOND_LIFE_GRADING")
        if "SENT_TO_RECYCLING" in types:
            assert p.status() == "waste"


def test_public_copy_has_no_restricted_events():
    for f in (store.PASSPORT_DIR / "public").glob("DBP-*.json"):
        d = json.loads(f.read_text())
        assert d["access_level"] == "public"
        assert not any(e["type"] in ("SOH_ASSESSMENT", "RUL_PREDICTION", "SECOND_LIFE_GRADING")
                       for e in d["events"])

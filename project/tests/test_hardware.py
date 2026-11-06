import json

import pytest

from batterylife.hardware.cycler import cycles_from_samples, phases
from batterylife.hardware.ingest import ingest
from batterylife.hardware.protocol import ProtocolError, parse_line, to_line
from batterylife.hardware.simulator import CellModel, Simulator


def test_parse_valid_line():
    s = parse_line('{"dev":"BLM-01","cell":"HW-7","t_ms":1500,"v":3.9,"i":-1.0,"temp":26.5}')
    assert s.t_s == 1.5 and s.i == -1.0 and s.cell == "HW-7"


@pytest.mark.parametrize("line", ["not json", '{"t_ms":1,"v":3.9,"i":0}', '{"t_ms":1,"v":9.9,"i":0,"temp":25}',
                                  '{"t_ms":1,"v":"x","i":0,"temp":25}'])
def test_parse_rejects_bad_lines(line):
    with pytest.raises(ProtocolError):
        parse_line(line)


def test_round_trip():
    s = parse_line('{"t_ms":2000,"v":4.1,"i":0.5,"temp":30}')
    assert parse_line(to_line(s)) == s


@pytest.fixture(scope="module")
def sim_cycles():
    m = CellModel(rated_ah=2.0, soh=0.84)
    samples = list(Simulator(m).run(2, fade_per_cycle=0.0))
    return m, samples, cycles_from_samples(samples, 2.0)


def test_cycle_segmentation(sim_cycles):
    _, samples, cyc = sim_cycles
    kinds = [p for p, _, _ in phases(samples)]
    assert kinds.count("charge") == 2 and kinds.count("discharge") == 2
    assert len(cyc) == 2


def test_capacity_and_resistance_recovered(sim_cycles):
    m, _, cyc = sim_cycles
    assert abs(cyc["soh"].iloc[0] - m.soh) < 0.015          # coulomb counting within 1.5 %-points
    assert abs(cyc["resistance_ohm"].iloc[0] / m.r0 - 1) < 0.05
    assert cyc[["cc_charge_time_s", "cv_charge_time_s", "charge_v_rise_s"]].notna().all().all()


def test_ingest_writes_valid_signed_passport(sim_cycles, tmp_path):
    _, samples, _ = sim_cycles
    res = ingest(samples, 2.0, folder=tmp_path)
    assert res["valid"] and res["cycles"] == 2
    p = json.loads((tmp_path / f"{res['passport_id']}.json").read_text())
    types = [e["type"] for e in p["events"]]
    assert types[0] == "MANUFACTURED" and types.count("SOH_ASSESSMENT") == 2 and types[-1] == "SECOND_LIFE_GRADING"

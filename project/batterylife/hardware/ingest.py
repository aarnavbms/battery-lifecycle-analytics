"""Read telemetry from a board (serial port) or a log file, extract cycles,
grade the cell and record signed events in its Digital Battery Passport.

    python -m batterylife.hardware simulate --cycles 3 --soh 0.84 --out hardware/sample_logs/sim.jsonl
    python -m batterylife.hardware ingest --log hardware/sample_logs/sim.jsonl --rated 2.0
    python -m batterylife.hardware ingest --serial COM3 --rated 2.0 --minutes 600     (needs: pip install pyserial)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from ..config import PASSPORT_DIR, PROCESSED_DIR
from ..lifecycle.grading import assess
from ..passport import store
from ..passport.ledger import Passport, verify
from .cycler import cycles_from_samples
from .protocol import ProtocolError, parse_line, to_line
from .simulator import CellModel, Simulator


def read_log(path: Path):
    samples, bad = [], 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            samples.append(parse_line(line))
        except ProtocolError:
            bad += 1
    return samples, bad


def read_serial(port: str, baud: int, minutes: float, log_to: Path | None):
    try:
        import serial  # pyserial
    except ImportError:
        raise SystemExit("Serial input needs pyserial: pip install pyserial")
    samples, bad, end = [], 0, time.time() + minutes * 60
    fh = log_to.open("a") if log_to else None
    with serial.Serial(port, baud, timeout=2) as ser:
        print(f"Reading {port} at {baud} baud for {minutes} min (Ctrl+C to stop early)")
        try:
            while time.time() < end:
                raw = ser.readline().decode(errors="replace").strip()
                if not raw:
                    continue
                try:
                    s = parse_line(raw)
                except ProtocolError:
                    bad += 1
                    continue
                samples.append(s)
                if fh:
                    fh.write(raw + "\n")
                if len(samples) % 60 == 0:
                    print(f"  {len(samples)} samples  v={s.v:.3f} V  i={s.i:+.3f} A  T={s.temp:.1f} C")
        except KeyboardInterrupt:
            pass
    if fh:
        fh.close()
    return samples, bad


def record_in_passport(cycles: pd.DataFrame, rated_ah: float, source: str = "battery monitoring board",
                       folder: Path = PASSPORT_DIR) -> dict:
    """Append BMS measurements and an AI grading to the cell's passport."""
    reg = store.create_actors()
    store.save_registry(reg)
    A = reg.actors
    cid = str(cycles["cell_id"].iloc[0])
    pid = f"DBP-{cid}" if cid.upper().startswith("HW") else f"DBP-HW-{cid}"
    now = datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)
    path = folder / f"{pid}.json"
    if path.exists():
        p = store.load_passport(pid, folder)
        last = max(datetime.fromisoformat(e["timestamp"]) for e in p.events)
        now = max(now, last + timedelta(seconds=1))
    else:
        p = Passport(pid, cid)
        p.append(A["MFR-01"], "MANUFACTURED", {
            "model": cid, "chemistry": "Li-ion 18650 (bench cell)", "form_factor": "18650 cylindrical",
            "rated_capacity_ah": rated_ah, "nominal_voltage_v": 3.7, "manufacturer": "unknown (bench cell)",
            "manufacture_date": now.date().isoformat(), "data_source": source},
            now.isoformat())
    base_r = float(cycles["resistance_ohm"].dropna().iloc[0]) if cycles["resistance_ohm"].notna().any() else None
    for k, row in cycles.iterrows():
        rg = float(row["resistance_ohm"]) / base_r if base_r else None
        ts = (now + timedelta(seconds=k + 1)).isoformat()
        p.append(A["BMS-01"], "SOH_ASSESSMENT", {
            "cycle": int(row["cycle"]), "soh": round(float(row["soh"]), 4),
            "soh_lo": round(float(row["soh"]) - 0.01, 4), "soh_hi": round(float(row["soh"]) + 0.01, 4),
            "resistance_growth": round(rg, 3) if rg else None, "capacity_ah": round(float(row["capacity_ah"]), 4),
            "temp_max_c": round(float(row["temp_max_c"]), 2),
            "method": "coulomb counting on board telemetry (measured, +/-1% sensor tolerance)"}, ts)
    last = cycles.iloc[-1]
    rg = float(last["resistance_ohm"]) / base_r if base_r else None
    a = assess(float(last["soh"]), float(last["soh"]) - 0.01, rg)
    p.append(A["AI-ASSESSOR"], "SECOND_LIFE_GRADING", {
        "cycle": int(last["cycle"]), "grade": a.grade, "application": a.application,
        "confidence": a.confidence, "recommendation": a.recommendation},
        (now + timedelta(seconds=len(cycles) + 2)).isoformat())
    store.save_passport(p, folder)
    v = verify(p, store.load_registry())
    return {"passport_id": pid, "events": len(p.events), "valid": v["valid"], "grade": a.grade,
            "application": a.application, "soh": float(last["soh"])}


def ingest(samples, rated_ah: float, bad: int = 0, folder: Path = PASSPORT_DIR) -> dict:
    cycles = cycles_from_samples(samples, rated_ah)
    if cycles.empty:
        raise SystemExit(f"No complete charge+discharge cycle found in {len(samples)} samples.")
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out = PROCESSED_DIR / "hardware_cycles.csv"
    cycles.to_csv(out, index=False)
    dev = samples[0].dev if samples else "unknown"
    src = f"simulated monitoring board ({dev})" if dev.startswith("SIM") else f"battery monitoring board ({dev})"
    res = record_in_passport(cycles, rated_ah, src, folder)
    res.update({"samples": len(samples), "rejected_lines": bad, "cycles": len(cycles), "cycles_csv": str(out)})
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m batterylife.hardware")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("simulate", help="write a simulated telemetry log")
    s.add_argument("--cycles", type=int, default=3)
    s.add_argument("--soh", type=float, default=0.85)
    s.add_argument("--fade", type=float, default=0.004, help="SOH lost per cycle")
    s.add_argument("--rated", type=float, default=2.0)
    s.add_argument("--cell", default="HW-001")
    s.add_argument("--out", type=Path, default=Path("hardware/sample_logs/sim.jsonl"))
    g = sub.add_parser("ingest", help="ingest a log file or a serial port")
    g.add_argument("--log", type=Path)
    g.add_argument("--serial")
    g.add_argument("--baud", type=int, default=115200)
    g.add_argument("--minutes", type=float, default=600)
    g.add_argument("--rated", type=float, default=2.0)
    a = ap.parse_args(argv)
    if a.cmd == "simulate":
        sim = Simulator(CellModel(rated_ah=a.rated, soh=a.soh, cell=a.cell))
        a.out.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        with a.out.open("w") as fh:
            for smp in sim.run(a.cycles, a.fade):
                fh.write(to_line(smp) + "\n")
                n += 1
        print(f"wrote {n} samples ({a.cycles} cycles) to {a.out}")
    else:
        if a.log:
            samples, bad = read_log(a.log)
        elif a.serial:
            samples, bad = read_serial(a.serial, a.baud, a.minutes, Path("hardware/sample_logs/serial.jsonl"))
        else:
            ap.error("give --log FILE or --serial PORT")
        print(json.dumps(ingest(samples, a.rated, bad), indent=2))


if __name__ == "__main__":
    sys.exit(main())

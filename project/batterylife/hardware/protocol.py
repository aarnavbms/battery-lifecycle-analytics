"""Telemetry protocol between a battery monitoring board and the pipeline.

The board (see hardware/firmware/battery_logger) sends one JSON object per line
over USB serial (115200 baud) or MQTT, about once per second:

    {"dev":"BLM-01","cell":"HW-001","t_ms":123456,"v":3.912,"i":-0.998,"temp":27.4,"phase":"discharge"}

Fields
    dev    board identifier
    cell   battery identifier (becomes the passport's battery_id)
    t_ms   milliseconds since the board started
    v      terminal voltage, volts
    i      current, amperes; positive = charging, negative = discharging
    temp   cell surface temperature, degrees C
    phase  'charge' | 'discharge' | 'rest' (informational; the pipeline re-derives it)
"""
from __future__ import annotations

import json
from dataclasses import dataclass

LIMITS = {"v": (0.0, 5.0), "i": (-20.0, 20.0), "temp": (-40.0, 120.0)}


@dataclass(frozen=True)
class Sample:
    t_s: float
    v: float
    i: float
    temp: float
    dev: str = "unknown"
    cell: str = "HW-001"


class ProtocolError(ValueError):
    pass


def parse_line(line: str) -> Sample:
    """Parse and validate one telemetry line; raises ProtocolError on bad input."""
    try:
        d = json.loads(line)
    except json.JSONDecodeError as e:
        raise ProtocolError(f"not JSON: {line[:60]!r}") from e
    for k in ("t_ms", "v", "i", "temp"):
        if k not in d:
            raise ProtocolError(f"missing field {k}")
    try:
        s = Sample(float(d["t_ms"]) / 1000.0, float(d["v"]), float(d["i"]), float(d["temp"]),
                   str(d.get("dev", "unknown")), str(d.get("cell", "HW-001")))
    except (TypeError, ValueError) as e:
        raise ProtocolError(f"bad number in {line[:60]!r}") from e
    for k, (lo, hi) in LIMITS.items():
        val = getattr(s, k)
        if not lo <= val <= hi:
            raise ProtocolError(f"{k}={val} outside {lo}..{hi}")
    return s


def to_line(s: Sample, phase: str = "") -> str:
    return json.dumps({"dev": s.dev, "cell": s.cell, "t_ms": int(round(s.t_s * 1000)),
                       "v": round(s.v, 4), "i": round(s.i, 4), "temp": round(s.temp, 2),
                       "phase": phase}, separators=(",", ":"))

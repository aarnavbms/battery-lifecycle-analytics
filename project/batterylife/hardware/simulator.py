"""Software stand-in for the monitoring board: a simple equivalent-circuit cell.

Lets the hardware pipeline be developed and tested before any board exists.
Model: open-circuit voltage as a function of state of charge, a series
resistance, CC-CV charging to 4.2 V, CC discharge to 2.7 V, and a first-order
thermal model. Capacity and resistance are set from the cell's SOH, so a
known answer is available to check the pipeline against.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Iterator

from .protocol import Sample


@dataclass
class CellModel:
    rated_ah: float = 2.0
    soh: float = 0.90
    r0_fresh: float = 0.060          # ohm, fresh-cell series resistance
    v_max: float = 4.2
    v_min: float = 2.7
    ambient_c: float = 25.0
    i_charge: float = 1.0             # A, CC charge current
    i_discharge: float = 1.0          # A, CC discharge current
    i_cutoff: float = 0.05            # A, end of CV phase
    rest_s: int = 300
    noise: float = 0.002
    cell: str = "HW-001"
    dev: str = "SIM-01"

    @property
    def capacity_ah(self) -> float:
        return self.rated_ah * self.soh

    @property
    def r0(self) -> float:
        # resistance grows as the cell ages
        return self.r0_fresh * (1 + 2.0 * (1 - self.soh) ** 1.1 * 3)


def ocv(soc: float) -> float:
    soc = min(max(soc, 0.0), 1.0)
    return 3.30 + 0.55 * soc + 0.35 * soc ** 2 - 0.30 * math.exp(-18 * soc)


class Simulator:
    def __init__(self, model: CellModel, dt: float = 1.0, seed: int = 7):
        self.m, self.dt = model, dt
        self.soc, self.temp, self.t = 0.02, model.ambient_c, 0.0
        self.rng = random.Random(seed)

    def _sample(self, v: float, i: float) -> Sample:
        n = self.m.noise
        return Sample(self.t, v + self.rng.gauss(0, n), i + self.rng.gauss(0, n / 2),
                      self.temp + self.rng.gauss(0, 0.05), self.m.dev, self.m.cell)

    def _step(self, i: float):
        self.soc += i * self.dt / 3600.0 / self.m.capacity_ah
        heat = i * i * self.m.r0
        self.temp += self.dt * (heat * 0.15 - 0.012 * (self.temp - self.m.ambient_c))
        self.t += self.dt

    def rest(self, seconds: int) -> Iterator[Sample]:
        for _ in range(int(seconds / self.dt)):
            yield self._sample(ocv(self.soc), 0.0)
            self._step(0.0)

    def charge(self) -> Iterator[Sample]:
        m = self.m
        while ocv(self.soc) + m.i_charge * m.r0 < m.v_max and self.soc < 1.0:   # CC
            yield self._sample(ocv(self.soc) + m.i_charge * m.r0, m.i_charge)
            self._step(m.i_charge)
        while True:                                                            # CV
            i = (m.v_max - ocv(self.soc)) / m.r0
            if i < m.i_cutoff or self.soc >= 1.0:
                break
            i = min(i, m.i_charge)
            yield self._sample(m.v_max, i)
            self._step(i)

    def discharge(self) -> Iterator[Sample]:
        m = self.m
        while True:
            v = ocv(self.soc) - m.i_discharge * m.r0
            if v <= m.v_min or self.soc <= 0:
                break
            yield self._sample(v, -m.i_discharge)
            self._step(-m.i_discharge)

    def cycle(self) -> Iterator[Sample]:
        yield from self.rest(self.m.rest_s // 2)
        yield from self.charge()
        yield from self.rest(self.m.rest_s)
        yield from self.discharge()
        yield from self.rest(self.m.rest_s // 2)

    def run(self, cycles: int, fade_per_cycle: float = 0.0) -> Iterator[Sample]:
        for _ in range(cycles):
            yield from self.cycle()
            self.m.soh = max(0.3, self.m.soh - fade_per_cycle)

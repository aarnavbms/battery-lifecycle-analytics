"""Second-life grading and application matching.

A retired battery is graded on three things the passport records:
  1. estimated SOH (with its 95% interval)
  2. resistance growth relative to the fresh cell (safety and power capability)
  3. predicted cycles left until the 60% second-life floor

Grades follow the application catalogue in config.APPLICATIONS:
  A  EV re-use / light e-mobility
  B  grid or home energy storage
  C  backup power
  D  recycle

Uncertainty-aware: if the grade computed from the lower SOH bound differs from
the grade from the point estimate, the decision is marked low-confidence and a
laboratory capacity test is recommended before the battery is redeployed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from ..config import APPLICATIONS, THRESHOLDS

GRADE_ORDER = ["A", "B", "C", "D"]
RECYCLE = "Recycling / material recovery"


@dataclass
class Assessment:
    grade: str
    application: str
    reasons: list[str]
    confidence: str            # 'high' | 'low'
    recommendation: str
    grade_at_lower_bound: str
    service_years: float | None

    def to_dict(self) -> dict:
        return asdict(self)


def grade(soh: float, resistance_growth: float | None, cycles_left: float | None = None) -> tuple[str, str, list[str]]:
    """Return (grade, application, reasons) for one set of measurements.

    cycles_left = None skips the cycle requirement (when no estimate exists).
    """
    reasons = []
    for app in APPLICATIONS:
        fails = []
        if soh < app.min_soh:
            fails.append(f"SOH {soh:.1%} < {app.min_soh:.0%}")
        if resistance_growth is not None and resistance_growth > app.max_resistance_growth:
            fails.append(f"resistance x{resistance_growth:.2f} > x{app.max_resistance_growth:.2f}")
        if cycles_left is not None and cycles_left < app.min_remaining_cycles:
            fails.append(f"{cycles_left:.0f} cycles left < {app.min_remaining_cycles}")
        if not fails:
            reasons.append(f"meets {app.name} requirements")
            return app.grade, app.name, reasons
        reasons.append(f"not {app.grade}: " + "; ".join(fails))
    return "D", RECYCLE, reasons


def assess(soh: float, soh_lo: float | None, resistance_growth: float | None,
           cycles_left: float | None = None, cycles_left_lo: float | None = None) -> Assessment:
    g, app, reasons = grade(soh, resistance_growth, cycles_left)
    g_lo, _, _ = grade(soh_lo if soh_lo is not None else soh, resistance_growth,
                       cycles_left_lo if cycles_left_lo is not None else cycles_left)
    confident = g_lo == g
    if g == "D":
        rec = "Send to certified recycler; record SENT_TO_RECYCLING in passport"
    elif confident:
        rec = f"Repurpose for {app}"
    else:
        rec = f"Likely {app}, but uncertainty spans grade {g_lo}: run a laboratory capacity test first"
    years = None
    if g != "D" and cycles_left is not None:
        cpy = next(a.cycles_per_year for a in APPLICATIONS if a.grade == g)
        years = round(cycles_left / cpy, 2)
    return Assessment(g, app, reasons, "high" if confident else "low", rec, g_lo, years)


def lifecycle_stage(soh: float) -> str:
    if soh >= THRESHOLDS.first_life_eol:
        return "First life"
    if soh >= THRESHOLDS.second_life_floor:
        return "Second-life window"
    return "End of life"

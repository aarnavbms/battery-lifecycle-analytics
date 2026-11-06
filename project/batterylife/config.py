"""Central configuration: paths, dataset metadata and lifecycle thresholds.

Every threshold used anywhere in the project lives here, so the report, the
pipeline and the dashboard always agree on the numbers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
RESULTS_DIR = ROOT / "results"
PASSPORT_DIR = RESULTS_DIR / "passports"
KEYS_DIR = RESULTS_DIR / "keys"
FIG_DIR = ROOT / "docs" / "figures"

SEED = 42


@dataclass(frozen=True)
class DatasetInfo:
    name: str
    chemistry: str
    form_factor: str
    rated_capacity_ah: float
    nominal_voltage_v: float
    manufacturer: str
    cells: tuple[str, ...]
    source: str


NASA = DatasetInfo(
    name="NASA PCoE",
    chemistry="Li-ion (LiCoO2-based 18650)",
    form_factor="18650 cylindrical",
    rated_capacity_ah=2.0,
    nominal_voltage_v=3.7,
    manufacturer="Unknown (NASA Ames test cells)",
    cells=("B0005", "B0006", "B0007", "B0018"),
    source="B. Saha and K. Goebel (2007). Battery Data Set, NASA Ames Prognostics Data Repository",
)

CALCE = DatasetInfo(
    name="CALCE CS2",
    chemistry="LiCoO2 (LCO) prismatic",
    form_factor="Prismatic",
    rated_capacity_ah=1.1,
    nominal_voltage_v=3.7,
    manufacturer="Unknown (CALCE CS2 test cells)",
    cells=("CS2_35", "CS2_36", "CS2_37", "CS2_38"),
    source="CALCE Battery Research Group, University of Maryland, CS2 dataset",
)

DATASETS = {"nasa": NASA, "calce": CALCE}


@dataclass(frozen=True)
class LifecycleThresholds:
    """Health thresholds that split a battery's life into stages.

    first_life_eol: EV traction end-of-life (SOH below which a pack leaves the car).
    second_life_floor: below this SOH re-use is no longer worthwhile -> recycle.
    max_resistance_growth: resistance increase (x fresh) above which a cell is
        considered unsafe/unfit for demanding re-use.
    """
    first_life_eol: float = 0.80
    second_life_floor: float = 0.60
    max_resistance_growth: float = 2.0


THRESHOLDS = LifecycleThresholds()


@dataclass(frozen=True)
class SecondLifeApplication:
    name: str
    grade: str
    min_soh: float
    max_resistance_growth: float
    min_remaining_cycles: int
    cycles_per_year: int
    description: str


# Application catalogue used by the second-life matcher (Sprint 6).
# Requirements are project assumptions documented in docs/final_report.md.
APPLICATIONS = (
    SecondLifeApplication("EV re-use / light e-mobility", "A", 0.80, 1.30, 300, 250,
                          "Re-use in low-demand vehicles, e-scooters, e-rickshaws"),
    SecondLifeApplication("Grid / home energy storage", "B", 0.70, 1.60, 200, 300,
                          "Stationary storage with daily cycling at low C-rate"),
    SecondLifeApplication("Backup power (telecom, UPS)", "C", 0.60, 2.00, 50, 20,
                          "Rarely cycled standby supply"),
)

# Sustainability assumptions (Sprint 6). Configurable; sources in docs/final_report.md.
@dataclass(frozen=True)
class SustainabilityAssumptions:
    """All values are assumptions for illustration; change them here.

    manufacturing footprint: IVL Swedish Environmental Research Institute reports
    61-106 kg CO2e per kWh for NMC battery production; 75 is used as a mid value.
    """
    manufacturing_kgco2e_per_kwh: float = 75.0
    new_battery_usd_per_kwh: float = 115.0       # assumed new storage battery price
    second_life_price_fraction: float = 0.45     # repurposed price as share of new
    recycling_credit_usd_per_kwh: float = 8.0    # assumed recovered material value
    reference_pack_kwh: float = 60.0             # results scaled to a typical EV pack


SUSTAINABILITY = SustainabilityAssumptions()

# SOH levels at which a pack may be retired (warranty end, accident, resale).
# Grading is evaluated at every level to test all grade boundaries.
RETIREMENT_SOH_LEVELS = tuple(round(x, 3) for x in
                              [0.90, 0.875, 0.85, 0.825, 0.80, 0.775, 0.75, 0.725,
                               0.70, 0.675, 0.65, 0.625, 0.60, 0.575, 0.55])



@dataclass
class ModelConfig:
    soh_features: list[str] = field(default_factory=lambda: [
        "cc_charge_time_rel", "cv_charge_time_rel", "charge_v_rise_rel",
        "resistance_rel", "cycle_norm"])
    rul_horizon_threshold: float = 0.80
    rul_start_fraction: float = 0.2


MODEL = ModelConfig()


def ensure_dirs() -> None:
    for d in (PROCESSED_DIR, RESULTS_DIR, PASSPORT_DIR, KEYS_DIR, FIG_DIR):
        d.mkdir(parents=True, exist_ok=True)

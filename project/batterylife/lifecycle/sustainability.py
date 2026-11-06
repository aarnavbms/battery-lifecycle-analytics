"""Environmental and economic value of a lifecycle decision.

Results are given per cell and scaled to a reference EV pack (config, 60 kWh) at
the same SOH, so the numbers are meaningful at vehicle scale. All coefficients
are assumptions in config.SUSTAINABILITY.

CO2 avoided by re-use is an upper bound: it assumes the repurposed battery fully
displaces the manufacture of a new battery of the same usable capacity.
"""
from __future__ import annotations

from ..config import DATASETS, SUSTAINABILITY as S


def cell_energy_kwh(dataset: str, soh: float) -> float:
    info = DATASETS[dataset]
    return soh * info.rated_capacity_ah * info.nominal_voltage_v / 1000.0


def value(grade: str, soh: float, dataset: str) -> dict:
    usable_cell = cell_energy_kwh(dataset, soh)
    usable_pack = soh * S.reference_pack_kwh
    if grade == "D":
        co2_pack = 0.0
        value_pack = usable_pack / max(soh, 1e-9) * S.recycling_credit_usd_per_kwh
        route = "recycle"
    else:
        co2_pack = usable_pack * S.manufacturing_kgco2e_per_kwh
        value_pack = usable_pack * S.new_battery_usd_per_kwh * S.second_life_price_fraction
        route = "re-use"
    scale = usable_cell / usable_pack if usable_pack else 0.0
    return {
        "route": route,
        "usable_kwh_cell": round(usable_cell, 5),
        "usable_kwh_pack": round(usable_pack, 2),
        "co2_avoided_kg_pack": round(co2_pack, 1),
        "co2_avoided_kg_cell": round(co2_pack * scale, 4),
        "value_usd_pack": round(value_pack, 0),
    }

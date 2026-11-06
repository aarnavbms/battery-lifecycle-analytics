"""Digital Battery Passport (DBP) schema.

Aligned with the passport content and access tiers of Regulation (EU) 2023/1542
(Article 77, Annex XIII), simplified for this project:

  * every piece of passport content enters through a signed event
  * each event type may only be issued by certain actor roles
  * each event type and each derived section has an access level

Battery status values follow the regulation's wording:
original, repurposed, re-used, remanufactured, waste.
"""
from __future__ import annotations

SCHEMA_VERSION = "1.0"

PUBLIC, RESTRICTED = "public", "legitimate_interest"

ROLES = {
    "manufacturer": "Cell / battery manufacturer (economic operator placing it on the market)",
    "oem": "Vehicle manufacturer (first-life operator)",
    "bms": "Battery management system (automated measurements)",
    "assessor": "AI lifecycle assessor (this system)",
    "repurposer": "Second-life integrator (repurposes the battery)",
    "recycler": "Certified recycler",
}

# event type -> (roles allowed to issue it, access level, new battery status or None)
EVENT_TYPES = {
    "MANUFACTURED":            ({"manufacturer"}, PUBLIC, "original"),
    "CARBON_FOOTPRINT_DECLARED": ({"manufacturer"}, PUBLIC, None),
    "FIRST_LIFE_START":        ({"oem"}, PUBLIC, None),
    "SOH_ASSESSMENT":          ({"bms", "assessor"}, RESTRICTED, None),
    "RUL_PREDICTION":          ({"assessor"}, RESTRICTED, None),
    "FIRST_LIFE_RETIRED":      ({"oem"}, PUBLIC, None),
    "SECOND_LIFE_GRADING":     ({"assessor"}, RESTRICTED, None),
    "REPURPOSED":              ({"repurposer"}, PUBLIC, "repurposed"),
    "SENT_TO_RECYCLING":       ({"repurposer", "oem", "recycler"}, PUBLIC, "waste"),
    "RECYCLED":                ({"recycler"}, PUBLIC, None),
}

# fields required in the data of specific events
REQUIRED_FIELDS = {
    "MANUFACTURED": ["model", "chemistry", "form_factor", "rated_capacity_ah",
                     "nominal_voltage_v", "manufacturer", "manufacture_date"],
    "CARBON_FOOTPRINT_DECLARED": ["kgco2e_per_kwh", "total_kgco2e"],
    "SOH_ASSESSMENT": ["cycle", "soh", "soh_lo", "soh_hi", "resistance_growth", "method"],
    "RUL_PREDICTION": ["cycle", "threshold", "rul_cycles", "rul_lo", "rul_hi", "method"],
    "SECOND_LIFE_GRADING": ["grade", "application", "confidence", "recommendation"],
}

# derived passport sections and their access level (Annex XIII-style tiers)
SECTIONS = {
    "general_information": PUBLIC,
    "carbon_footprint": PUBLIC,
    "performance_and_durability": PUBLIC,
    "battery_status": PUBLIC,
    "state_of_health": RESTRICTED,
    "lifecycle_decision": RESTRICTED,
}

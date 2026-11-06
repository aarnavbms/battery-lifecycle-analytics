"""Unified cycle-level schema shared by every dataset loader.

One row = one full charge + discharge cycle of one cell. Loaders must return a
DataFrame with exactly these columns (NaN where a dataset has no such signal).
"""
CYCLE_COLUMNS = [
    "dataset",            # 'nasa' | 'calce'
    "cell_id",            # e.g. 'B0005', 'CS2_35'
    "cycle",              # 1..N, counted over complete discharge cycles
    "timestamp",          # start of the discharge (ISO string) when known
    "capacity_ah",        # measured discharge capacity
    "soh",                # capacity_ah / rated capacity
    "cc_charge_time_s",   # duration of the constant-current charge phase
    "cv_charge_time_s",   # duration of the constant-voltage charge phase
    "charge_v_rise_s",    # time for terminal voltage to rise 3.9 V -> 4.2 V during CC charge
    "discharge_time_s",   # duration of the CC discharge to cut-off
    "mean_discharge_v",   # average terminal voltage during discharge
    "discharge_energy_wh",
    "resistance_ohm",     # NASA: Re+Rct from EIS (interpolated); CALCE: Arbin internal resistance
    "temp_max_c",         # max cell surface temperature during discharge (NASA only)
    "temp_rise_c",        # temp_max - temp at start of discharge (NASA only)
    "ambient_c",
]

REQUIRED_NON_NULL = ["dataset", "cell_id", "cycle", "capacity_ah", "soh"]

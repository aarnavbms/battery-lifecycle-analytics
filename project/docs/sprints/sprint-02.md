# Sprint 2: Data Ingestion and Quality

**Planned week:** Week 2 (Mon 9 Nov - Fri 13 Nov 2026) · **Git tag:** `sprint-02`

## Sprint goal
Parse both real datasets into one validated cycle-level table.

## Backlog

| Item | Status |
| --- | --- |
| Unified schema for cycle-level data | Done |
| NASA `.mat` loader (charge, discharge, impedance) | Done |
| CALCE Arbin `.xlsx` loader (100 files, global cycle numbering) | Done |
| Registry with CSV cache and validation | Done |
| Data quality report | Done |
| Unit tests | Done (5 passing) |

## What was built

| File | Purpose |
| --- | --- |
| `batterylife/data/schema.py` | 16 standard columns, required fields |
| `batterylife/data/nasa.py` | Pairs each discharge with its preceding charge; interpolates EIS resistance onto discharge times |
| `batterylife/data/calce.py` | Orders files by date, keeps only full 1C discharges, extracts charge phases and internal resistance |
| `batterylife/data/registry.py` | `load_cycles()`, `validate()`, `quality_report()` |
| `tests/test_data.py` | Schema, contiguous cycles, fade check, synthetic charge curve, validation |
| `docs/dataset.md` | Dataset description and quality findings |
| `scripts/make_figures.py` | Figure generator (Figure 1) |

## Results
- 4,631 cycles from 8 cells: NASA 636, CALCE 3,995.
- Health indicators already track SOH in NASA data:

  | Indicator | Correlation with SOH |
  | --- | --- |
  | CC charge time | 0.84 |
  | 3.9-4.2 V rise time | 0.86 |
  | CV charge time | -0.70 |
  | Resistance | -0.69 |

- Full parse takes about 30 s, mostly the CALCE Excel files; the cached CSV loads in under 1 s.

## Issues found and fixed
| Issue | Fix |
| --- | --- |
| NASA resistance came out constant | pandas 3 stores datetimes in microseconds, so seconds were wrong; switched to Python `datetime.timestamp()` |
| NASA discharge time included rest after cut-off | Keep only the period with load current above 1 A |
| One test expected exact CV-start time | CV start is detected at 4.195 V; test tolerance corrected |

## Next sprint
Cleaning (Hampel filter) and feature engineering for the models.

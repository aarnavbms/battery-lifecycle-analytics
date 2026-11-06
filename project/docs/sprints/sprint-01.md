# Sprint 1: Scoping, Architecture and Data Acquisition

**Planned week:** Week 1 (Mon 2 Nov - Fri 6 Nov 2026) · **Git tag:** `sprint-01`

## Sprint goal
Fix the project scope, design the architecture, and secure real battery data.

## Backlog

| Item | Status |
| --- | --- |
| Define problem statement and objectives | Done |
| Survey public battery ageing datasets | Done |
| Choose datasets: NASA PCoE + CALCE CS2 | Done |
| Download and store raw data | Done |
| Design system architecture | Done |
| Set up repository, config, requirements | Done |

## What was built

| File | Purpose |
| --- | --- |
| `batterylife/config.py` | Paths, dataset metadata, lifecycle thresholds (80% / 60%), second-life application catalogue, sustainability assumptions |
| `scripts/download_data.py` | Fetches raw data from a public mirror with git |
| `docs/architecture.md` | Layered architecture, data flow, passport design |
| `docs/figures/architecture.png` | Architecture diagram |
| `requirements.txt`, `.gitignore` | Environment and repository hygiene |

## Key decisions
- **Two real datasets instead of simulated data.**
  - NASA PCoE: 4 cells (B0005, B0006, B0007, B0018) with charge, discharge and impedance (EIS) records.
  - CALCE CS2: 4 cells (CS2_35 to CS2_38) cycled to deep fade.

  NASA gives resistance and temperature. CALCE covers the whole first and second life, reaching 15-27% SOH.
- **Lifecycle thresholds:** first-life end at 80% SOH, second-life floor at 60% SOH, maximum resistance growth 2x for re-use.
- **SOH inputs must be observable during charging,** so discharge capacity is never an input.
- **Passport** aligned with Regulation (EU) 2023/1542 Annex XIII, with signed events and access levels.

## Risks
| Risk | Mitigation |
| --- | --- |
| Only 8 cells in total | Leave-one-cell-out validation; report per-cell errors honestly |
| CALCE raw data is 170 MB | Not stored in git; download script provided |
| Two datasets use different chemistries and protocols | Per-cell relative features; models trained per dataset |

## Next sprint
Data ingestion: parse both datasets into one cycle-level table and check data quality.

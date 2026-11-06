# Sprint 10: Final Report, Documentation and Release

**Planned week:** Week 10 (Mon 4 Jan - Fri 8 Jan 2027) · **Git tags:** `sprint-10`, `v1.0`

## Sprint goal
Package the project for submission: final report, documentation, reproducibility check and release.

## Backlog

| Item | Status |
| --- | --- |
| Final report with all results and references | Done (`docs/final_report.md`) |
| User guide for Windows / Anaconda | Done (`docs/user_guide.md`) |
| Documentation index and sprint table | Done (`docs/README.md`) |
| Project README | Done |
| Clean full re-run and metric cross-check | Done |
| Release tag v1.0 | Done |

## Verification before release
- Full pipeline from cleaned data: 294 s, 8 of 8 passports valid.
- Every number in the final report was taken from `results/*.json` after the final run. Two Sprint 4 Ridge values were corrected by 0.01 percentage points to match.
- `pytest`: 61 tests pass, covering data, features, SOH, RUL, grading, passport, pipeline and dashboard.
- Dashboard: all five pages render with no browser errors in light and dark themes and at phone width.

## Deliverables

| Deliverable | Location |
| --- | --- |
| Source code | `batterylife/`, `dashboard/`, `scripts/`, `tests/` |
| Results | `results/` (metrics, predictions, passports) |
| Report and documentation | `docs/` |
| Launchers | `run_dashboard.bat`, `run_pipeline.bat` |

## Suggested viva demo (5 minutes)
1. Overview: explain the lifecycle band.
2. Cells, CS2_36: estimate vs measurement, the RUL band, the decisions table.
3. Second life: move the SOH slider across 80% and watch the grade and confidence change.
4. Passports, CS2_36: press **Verify**, then **Simulate tampering** with "Raise a past SOH value and recompute every hash". The signature check catches it.

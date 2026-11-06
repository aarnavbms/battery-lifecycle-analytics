# Sprint 8: Pipeline Integration, CLI and Passport Issuance

**Planned week:** Week 8 (Mon 21 Dec - Fri 25 Dec 2026) · **Git tag:** `sprint-08`

## Sprint goal
Connect every stage into one reproducible command and issue a verified passport for each of the 8 real cells.

## Backlog

| Item | Status |
| --- | --- |
| Pipeline orchestrator (7 stages) | Done |
| Command-line interface | Done |
| Passport issuance from pipeline results | Done |
| Chronology check in verification | Done |
| Summary file for the dashboard | Done |
| Integration tests | Done (4 new, 47 total) |
| Full clean run and reproducibility check | Done (294 s; identical metrics on re-run) |

## What was built

| File | Purpose |
| --- | --- |
| `batterylife/pipeline.py` | `run(refresh, fast)`, `build_summary()` |
| `batterylife/__main__.py` | CLI: `run`, `verify`, `tamper-demo`, `assess`, `passport` |
| `batterylife/passport/issue.py` | Builds each cell's lifecycle: manufacture, first life, AI assessments, retirement, grading, repurposing, recycling |
| `tests/test_pipeline.py` | Summary, verification with public keys only, lifecycle order, public copies |

## Commands

```bash
python -m batterylife run              # full pipeline, about 5 minutes
python -m batterylife run --fast       # reuse saved model results, about 2 seconds
python -m batterylife verify           # verify every passport
python -m batterylife tamper-demo DBP-CALCE-CS2_36
python -m batterylife assess --soh 0.78 --soh-lo 0.74 --resistance 1.2 --cycles 250
python -m batterylife passport DBP-NASA-B0005 --public
```

## Results
- **8 passports, 164 signed events, 8 of 8 valid.** CS2_35 to CS2_38 and B0006 reach the 60% floor and end with status `waste` (sent to recycling). B0005, B0007 and B0018 end as `repurposed`.
- **Tamper demo on CS2_36:** raising an SOH value from 0.96 to 0.99 fails the content check at event 3. Recomputing every hash after the edit then fails the signature check.
- **What-if assessment:** SOH 78% (lower bound 74%), resistance x1.2, 250 cycles left gives Grade B, grid storage, low confidence: "uncertainty spans grade C: run a laboratory capacity test first".

## Issues found and fixed
| Issue | Fix |
| --- | --- |
| Passport timestamps went backwards: repurposing was dated 21 days after retirement, but the lab kept cycling | Administrative events now follow retirement by hours; a new **chronology** check in `verify()` makes this a hard failure |
| Summary stored an absolute server path | Relative path |

## Note on simulated actors
The measurements and timestamps in each passport are real test data, and the SOH and RUL values come from models that never saw that cell. The manufacturer, vehicle maker, repurposer and recycler are simulated actors, so the full passport workflow can be shown on laboratory cells.

## Next sprint
The analytics dashboard.

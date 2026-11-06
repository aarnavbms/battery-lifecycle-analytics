# Sprint 7: Digital Battery Passport

**Planned week:** Week 7 (Mon 14 Dec - Fri 18 Dec 2026) · **Git tag:** `sprint-07`

## Sprint goal
Build a tamper-evident, signed Digital Battery Passport aligned with the EU Battery Regulation.

## Regulatory context
Regulation (EU) 2023/1542 requires a digital passport for EV, light-means-of-transport and industrial batteries above 2 kWh from **18 February 2027** (Article 77). Annex XIII lists the content and splits access between:
- the public
- persons with a legitimate interest (repairers, repurposers, recyclers)
- authorities

The regulation names five battery statuses: original, repurposed, re-used, remanufactured and waste.

## Backlog

| Item | Status |
| --- | --- |
| Schema: event types, roles, required fields, access levels | Done |
| Ed25519 key pairs per actor | Done |
| Hash-chained, signed ledger | Done |
| Five-way verification | Done |
| Derived passport sections; public view | Done |
| JSON store and actor directory | Done |
| Tests including attack scenarios | Done (10 new, 43 total) |

## What was built

| File | Purpose |
| --- | --- |
| `batterylife/passport/schema.py` | 10 event types, 6 roles, required fields, section access levels |
| `batterylife/passport/crypto.py` | Canonical JSON, SHA-256, Ed25519 sign and verify, key files |
| `batterylife/passport/ledger.py` | `Actor`, `ActorRegistry`, `Passport.append()`, `sections()`, `to_dict(access)`, `verify()` |
| `batterylife/passport/store.py` | Save and load passports, public copies, actor directory, default actors |
| `tests/test_passport.py` | Valid chain, round trip, tampering, re-hashed forgery, deletion, wrong role, impostor key, missing fields, aliasing, public view |

## Event catalogue

| Event | Who may issue it | Access | Sets status |
| --- | --- | --- | --- |
| MANUFACTURED | manufacturer | public | original |
| CARBON_FOOTPRINT_DECLARED | manufacturer | public | |
| FIRST_LIFE_START | oem | public | |
| SOH_ASSESSMENT | bms, assessor | restricted | |
| RUL_PREDICTION | assessor | restricted | |
| FIRST_LIFE_RETIRED | oem | public | |
| SECOND_LIFE_GRADING | assessor | restricted | |
| REPURPOSED | repurposer | public | repurposed |
| SENT_TO_RECYCLING | repurposer, oem, recycler | public | waste |
| RECYCLED | recycler | public | |

## Verification: what each attack triggers

| Attack | Detected by |
| --- | --- |
| Edit a past value (for example raise SOH) | content hash |
| Edit a value **and** recompute every hash | Ed25519 signature |
| Delete or reorder an event | chain index and `prev_hash` |
| Sign with another actor's key | signature |
| Issue an event your role is not allowed to | refused at write time; flagged at verify |
| Omit required data | refused at write time; flagged at verify |

## Issues found and fixed
- **Signed data was aliased.** `append()` stored the caller's dict object, so the caller could change signed data after signing. A test that ran after another test caught this, because the module-level fixture had been mutated. Data is now deep-copied through JSON at signing time, and a dedicated test guards it.

## Limitations
This is a single-store, tamper-evident ledger, not a distributed blockchain. Someone with write access could delete a whole passport file. Anchoring each passport's head hash on a public ledger, or in the regulator's registry, is future work.

## Next sprint
Integrate everything into one pipeline and command-line tool, and issue passports for all 8 real cells.

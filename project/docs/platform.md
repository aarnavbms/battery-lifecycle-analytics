# Software platform (version 1.1)

Version 1.0 was an analysis pipeline with a dashboard. Version 1.1 turns it into a software platform: a database, a documented REST API, user roles, a tool that assesses any user's battery file, network analysis of the passport ecosystem, model explainability, printable passports, automated tests in the cloud and a container image.

| Part | Where | What it does |
| --- | --- | --- |
| Database | `batterylife/service/db.py` | SQLite database with 10 tables, built from the pipeline's result files |
| REST API | `dashboard/api_v1.py`, `dashboard/openapi.py` | 23 endpoints under `/api/v1`, described in OpenAPI 3.0 |
| Roles | `batterylife/service/auth.py` | 8 roles, password login, signed tokens (JWT), audit log |
| Assess your data | `batterylife/service/analysis.py` | CSV in; health, forecast, grade and signed passport out |
| Network analysis | `batterylife/service/network.py` | Hand-off and process networks with centrality measures (NetworkX) |
| Explainability | `batterylife/service/explain.py` | Permutation importance of the SOH models on unseen cells |
| PDF passport | `batterylife/service/passport_pdf.py` | Printable passport with a QR code |
| CI | `.github/workflows/tests.yml` | Runs the 102 tests on every push |
| Container | `Dockerfile`, `docker-compose.yml` | One command to run the website and API |

## 1. Architecture

```
 Browser (10 pages)            Other software (curl, scripts)
        |                                  |
        +----------- HTTP / JSON ----------+
                         |
            Flask app  (dashboard/app.py)
              |                    |
     page routes + charts     REST API v1  (dashboard/api_v1.py)
                                   |
                    Service layer  (batterylife/service/)
        auth | analysis | network | explain | passport_pdf | db
              |                    |                   |
     Passport ledger        ML models and rules     SQLite database
   (batterylife/passport)  (models/, lifecycle/)   (results/battery.db)
              |                    |                   ^
              +------ result files (results/, data/processed/) ------+
                         written by `python -m batterylife run`
```

The pipeline stays the source of the research results. The database is a query layer on top of its files, plus the home of everything users create (uploads, their passports, the audit log).

## 2. Database

Rebuild at any time with `python -m batterylife db`. The server also rebuilds it automatically when the result files change.

| Table | Key | Holds | Links to |
| --- | --- | --- | --- |
| `datasets` | `dataset_key` | NASA, CALCE, hardware, upload | |
| `cells` | `cell_id` | One row per battery | `datasets`, `uploads` |
| `cycles` | `cell_id, cycle` | Cycle data with the model's SOH estimate and interval | `cells` |
| `assessments` | `assessment_id` | Second-life grading decisions | `cells` |
| `actors` | `actor_id` | Passport actors and their public keys | |
| `passports` | `passport_id` | Status, grade, head hash | |
| `events` | `passport_id, idx` | Signed, hash-chained events | `passports`, `actors` |
| `users` | `username` | API accounts, one role each, hashed password | |
| `uploads` | `upload_id` | Files assessed through the API and their results | `users` |
| `audit_log` | `audit_id` | Who did what, and when | `users` |

Deleting an upload removes its cells, cycles, assessments and passports (foreign keys with cascade). Passports read back from the database produce the same hashes as the JSON files, so they still verify; a test checks this.

## 3. Roles and access

| Role | Passport view | May sign | Extra |
| --- | --- | --- | --- |
| Public visitor (no account) | Public tier | nothing | |
| Manufacturer | Full | manufactured, carbon footprint | |
| Vehicle maker | Full | first life start, first life retired, sent to recycling | |
| Assessor | Full | SOH assessment, RUL prediction, second-life grading | assess uploads, issue passports |
| Repurposer | Full | repurposed, sent to recycling | |
| Recycler | Full | recycled, sent to recycling | |
| Regulator | Full | nothing | audit log |
| Administrator | Full | nothing | uploads, audit log |

- **Two tiers.** The public tier is what a QR code on the battery shows. Health records and the second-life decision are restricted to roles with a legitimate interest, following Annex XIII of Regulation (EU) 2023/1542.
- **Checked twice.** The API refuses a request from the wrong role. The passport ledger separately refuses an event whose signer has the wrong role, so the rule also holds for anyone verifying the chain later.
- **Sign-in.** `POST /api/v1/auth/login` returns a token valid for 8 hours. Passwords are stored as salted PBKDF2 hashes.
- **Demo mode.** With `BLA_DEMO=1` (the default) the "Viewing as" menu signs in to a demo account with one click. Set `BLA_DEMO=0` and replace `batterylife/service/demo_users.json` (or set `BLA_USERS_FILE`) for real accounts.
- **Laboratory passports are read-only.** Events can only be added to passports created from uploads or the hardware bench.

## 4. REST API

The full list, with a "Send request" button for each endpoint, is on the **API** page (`/developers`). The machine-readable description is at `/api/v1/openapi.json`.

```
POST /api/v1/auth/login             sign in
GET  /api/v1/cells                  list batteries
GET  /api/v1/cells/{id}/cycles      cycle data, paged
POST /api/v1/grade                  grade a battery from its numbers
POST /api/v1/uploads                assess a CSV file            (assessor)
GET  /api/v1/passports/{id}         read a passport; the view depends on your role
POST /api/v1/passports/{id}/verify  run the six integrity checks
GET  /api/v1/passports/{id}/pdf     printable passport with QR code
POST /api/v1/passports/{id}/events  record a lifecycle event     (role-specific)
GET  /api/v1/network                network measures
GET  /api/v1/audit                  audit log                    (regulator)
```

Errors always have the shape `{"error": {"code": "...", "message": "..."}}` with a matching HTTP status (400, 401, 403, 404, 409, 413, 422).

## 5. Assess your own data

Input is a CSV with one row per cycle.

| Column | Needed | Meaning |
| --- | --- | --- |
| `cycle` | yes | Cycle number |
| `capacity_ah` | yes, unless the charging signals are given | Measured discharge capacity |
| `cell_id` | no | Battery name; several batteries in one file are ranked |
| `resistance_ohm` | no | Internal resistance; its growth affects the grade |
| `cc_charge_time_s`, `cv_charge_time_s`, `charge_v_rise_s` | no | Charging signals for the AI estimate |

What happens to each battery:
1. **Health.** Measured capacity over rated capacity, cleaned with the same drop-only Hampel filter as the pipeline and smoothed over nine cycles. If charging signals are present and the cell type is one of the two trained types, the SOH model's estimate is reported next to it. If there is no capacity column, the model's estimate is used alone.
2. **Forecast.** Two trend methods (the fade model and a straight line) extend the curve to 80% and 60%. The range between them is reported.
3. **Grade.** The same A to D rules as the pipeline. The result is marked low confidence if the grade changes at the lower health bound or between the two forecasts.
4. **Passport.** A signed passport is issued, with up to eight health checkpoints, the forecast and the grade.

Limits to state honestly:
- The trend forecasts are rough. On the laboratory cells these two methods were off by 50 to 80 cycles on NASA cells (life about 72) and 145 to 390 on CALCE cells (life about 578). The learned RUL model (8 and 47 cycles) needs training data for the cell type, so it is not used for uploads.
- The AI estimate applies only to cells like the NASA or CALCE ones. For other cells, measured capacity is required.
- The single-cell sample is a real NASA cell that is in the training data, so its AI-versus-measured gap is optimistic. The result says so.
- The fleet sample is synthetic.

## 6. Network analysis

Each signed event is an interaction between an actor and a battery. Two directed networks are built from the 172 events on the 9 study passports.

- **Hand-off network (actor to actor).** An edge A to B is added each time B signs the event after A on the same battery.
- **Process network (event type to event type).** How often one lifecycle step follows another.

Measures: weighted in- and out-degree, betweenness centrality, PageRank, density and reciprocity.

| Actor | Batteries | Events | In | Out | Betweenness | PageRank |
| --- | --- | --- | --- | --- | --- | --- |
| AI-ASSESSOR | 9 | 120 | 25 | 21 | 0.250 | 0.448 |
| REP-01 (repurposer) | 8 | 13 | 13 | 8 | 0.000 | 0.265 |
| OEM-01 (vehicle maker) | 8 | 16 | 16 | 16 | 0.050 | 0.196 |
| BMS-01 | 1 | 6 | 1 | 1 | 0.050 | 0.032 |
| MFR-01 (manufacturer) | 9 | 17 | 0 | 9 | 0.000 | 0.029 |
| REC-01 (recycler) | 0 | 0 | 0 | 0 | 0.000 | 0.029 |

Findings:
- **The assessor is the broker.** It has the highest betweenness and PageRank: every battery passes through it between first and second life. It is the single point the passport system depends on, which is an argument for accrediting more than one assessor.
- **The manufacturer is a pure source** (out 9, in 0), as expected for the start of the chain.
- **The recycler is isolated.** No battery in the study reached final recycling, so it has signed nothing.
- **The network is sparse** (density 0.23) and partly two-way (reciprocity 0.57), because batteries return to the assessor after each lifecycle step.

Limit: the network is small (6 actors, 9 batteries), and the surrounding actors are simulated, as stated in the final report. The method is general and updates automatically as passports are added.

## 7. Explainability

Permutation importance, measured on the held-out cell in each leave-one-cell-out fold: shuffle one input and record how much the error rises.

| Signal | NASA (Gradient Boosting) | CALCE (Gaussian Process) |
| --- | --- | --- |
| CC charge time | 3.50 | 20.64 |
| CV charge time | 0.09 | 0.85 |
| 3.9-4.2 V rise time | 4.50 | 8.75 |
| Resistance | 0.02 | 3.27 |
| Cycle count | 1.59 | 0.52 |

Values are the rise in RMSE in SOH percentage points. Both models depend mainly on how long constant-current charging lasts and how fast the voltage rises, which is physically sensible: an aged cell reaches 4.2 V sooner. Cycle count matters little, so the models are reading the cell's condition and not just its age. Run `python -m batterylife explain` to recompute.

## 8. Running it

```
python dashboard/app.py                  website and API on http://127.0.0.1:8050
python -m batterylife serve --port 8050  the same
python -m batterylife db [--reset]       rebuild the database
python -m pytest -q                      102 tests
docker compose up --build                container (not built or tested in the development sandbox)
```

Environment variables: `PORT`, `HOST`, `BLA_DEMO` (1 or 0), `BLA_SECRET` (token signing secret), `BLA_USERS_FILE`.

Private signing keys are not in the repository. On a fresh clone the existing passports still verify (public keys are shipped), and the first upload enrols new local signing actors, for example `ASSESSOR-LOCAL-1`, and adds their public keys to the directory. Existing keys are never replaced.

## 9. The hosted website

The GitHub Pages copy has no server. It carries the same ten pages with the data embedded.
- Passport verification and tamper tests run in the browser with real cryptography.
- Roles are simulated in the browser; they show the two tiers but protect nothing, because that page's data is public anyway.
- "Assess your data" returns the server's stored results for the two samples. Any other file gets a lighter in-browser analysis (measured health, straight-line forecast, no passport).
- The API page shows the documentation without the "Send request" buttons.

## 10. Tests

`tests/test_service.py` adds 29 tests on a temporary database with no private keys: database sync, login and tokens, the two access tiers, upload validation and ranking, AI-only estimation, role-based signing, read-only laboratory passports, PDF output, network measures, and a check that every API route is documented.

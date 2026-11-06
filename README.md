# Battery Lifecycle Analytics

**AI-Based Battery Lifecycle Assessment and Second-Life Management Using Digital Battery Passports**

### [Open the live website](https://aarnavbms.github.io/battery-lifecycle-analytics/) · [Weekly reports (PDF)](reports/) · [Project code](project/)

![Home](project/docs/screenshots/home.png)

The system takes real lithium-ion ageing data and:
1. estimates each battery's **state of health (SOH)** from ordinary charging data
2. predicts its **remaining useful life (RUL)** with calibrated uncertainty
3. decides its **second life**: EV re-use, home or grid storage, backup power, or recycling
4. records every step in a **Digital Battery Passport** of SHA-256-chained, Ed25519-signed events, aligned with EU Regulation 2023/1542

It is built on **8 real cells** from NASA PCoE and CALCE CS2, **4,631 charge-discharge cycles**.

## Results (on cells the models never saw)

| Task | NASA PCoE | CALCE CS2 |
| --- | --- | --- |
| SOH estimation error (RMSE) | 2.20 %-points | 0.81 %-points |
| 95% interval coverage | 95.0% | 97.7% |
| Remaining-life error, to 80% SOH | 8.2 cycles (life about 72) | 46.6 cycles (life about 578) |
| Second-life grade matches lab grade | 87.8% | 80.0% |

- **Passports:** every one verifies. All five tested attacks are detected: edited data, re-hashed forgery, deleted event, back-dated event and impostor signature.

## The website

| Page | What it shows |
| --- | --- |
| Home | The fleet draining through its recorded life, how the system works, lifecycle at a glance |
| Cells | Measured vs estimated SOH with 95% band, RUL vs truth, health indicators, decisions |
| Models | Five SOH models and three RUL methods compared |
| Second life | Interactive grader, AI vs lab confusion matrix, rules and assumptions |
| Passports | Passport document view, live verification and tamper simulation in your browser |
| Hardware | Live telemetry console: simulated board or a real ESP32 over USB |
| Weekly reports | Seven weekly status reports as PDFs |

| Passport tamper detection | Hardware console |
| --- | --- |
| ![Passport](project/docs/screenshots/passport.png) | ![Hardware](project/docs/screenshots/hardware.png) |

## Hardware integration (future option)

A bench logger (ESP32 + INA219 + DS18B20 + TP4056, about INR 1,500) streams one JSON line per second. The pipeline:
- computes capacity by coulomb counting, plus the same charging health indicators the models use
- grades the cell
- appends signed `SOH_ASSESSMENT` events to its passport

Firmware, ingest code, simulator and tests are included. Details are in [project/docs/hardware.md](project/docs/hardware.md).

## Repository layout

```
index.html, plotly.min.js   the live website (GitHub Pages)
reports/                    weekly status reports, weeks 1-7 (PDF)
project/                    full source code
  batterylife/              data loaders, cleaning, features, SOH and RUL models, grading, passport, hardware
  dashboard/                Flask app (local version of the website)
  hardware/firmware/        ESP32 bench-logger firmware
  scripts/                  figures, static export, report generator
  tests/                    73 pytest tests
  docs/                     final report, architecture, dataset, hardware, sprint reports, figures
  data/processed, results/  processed data, metrics, predictions, passports
```

## Run it locally

```
cd project
pip install -r requirements.txt
python dashboard/app.py               # http://127.0.0.1:8050
python -m batterylife run --fast      # rebuild results
python -m pytest -q                   # 73 tests
```

## Data sources
- B. Saha and K. Goebel (2007). Battery Data Set, NASA Ames Prognostics Data Repository.
- CALCE Battery Research Group, University of Maryland, CS2 battery data.

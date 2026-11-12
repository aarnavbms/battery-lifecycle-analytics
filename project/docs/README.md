# Documentation

| Document | Contents |
| --- | --- |
| [final_report.md](final_report.md) | Full project report: problem, data, method, results, discussion, references |
| [architecture.md](architecture.md) | System design, data flow, passport design, repository layout |
| [dataset.md](dataset.md) | NASA and CALCE data, unified schema, data quality findings |
| [user_guide.md](user_guide.md) | How to install, run the dashboard, re-run the analysis |
| [platform.md](platform.md) | Version 1.1 software platform: database, REST API, roles, uploads, network analysis, explainability |
| [hardware.md](hardware.md) | Future hardware integration: parts, wiring, firmware, roadmap, safety |
| [reports/](reports/) | Weekly status reports for the faculty, weeks 1-7 (PDF) |
| [sprints/](sprints/) | One report per weekly sprint (use as the weekly status report to faculty) |
| [figures/](figures/) | Every figure used in the reports, including dashboard screenshots |

## Weekly sprint reports

| Sprint | Planned week | Report | Main result |
| --- | --- | --- | --- |
| 1 | Mon 2 - Fri 6 Nov 2026 | [sprint-01.md](sprints/sprint-01.md) | Architecture; real datasets chosen |
| 2 | 9 - 13 Nov | [sprint-02.md](sprints/sprint-02.md) | 4,631 cycles from 8 cells, validated |
| 3 | 16 - 20 Nov | [sprint-03.md](sprints/sprint-03.md) | Cleaning removes 120 interrupted cycles; indicators r = 0.93-1.00 |
| 4 | 23 - 27 Nov | [sprint-04.md](sprints/sprint-04.md) | SOH RMSE 2.20% NASA, 0.81% CALCE; 95-98% interval coverage |
| 5 | 30 Nov - 4 Dec | [sprint-05.md](sprints/sprint-05.md) | RUL error 8 / 47 cycles; calibrated bands |
| 6 | 7 - 11 Dec | [sprint-06.md](sprints/sprint-06.md) | 83% grade agreement; 89% when confident |
| 7 | 14 - 18 Dec | [sprint-07.md](sprints/sprint-07.md) | Signed, hash-chained passport; attack tests |
| 8 | 21 - 25 Dec | [sprint-08.md](sprints/sprint-08.md) | One-command pipeline; 8 valid passports |
| 9 | 28 Dec - 1 Jan | [sprint-09.md](sprints/sprint-09.md) | Analytics dashboard |
| 10 | 4 - 8 Jan 2027 | [sprint-10.md](sprints/sprint-10.md) | Final report, release v1.0 |

Each report follows the same structure: sprint goal, backlog with status, what was built, results, issues and fixes, next sprint.

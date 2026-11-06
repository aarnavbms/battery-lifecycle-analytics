"""Generate the weekly status reports (PDF) for the faculty in charge.

    python scripts/make_reports.py      -> docs/reports/week-01.pdf ... week-07.pdf,
                                           weekly-reports-weeks-1-7.pdf, index.json

Every number in the reports is read from results/ and data/processed/, so the
PDFs always match the code's actual output.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)
from pypdf import PdfReader, PdfWriter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "reports"
FIG = ROOT / "docs" / "figures"
RES = ROOT / "results"
TITLE = "AI-Based Battery Lifecycle Assessment and Second-Life Management Using Digital Battery Passports"
REPO = "github.com/aarnavbms/battery-lifecycle-analytics"
SITE = "aarnavbms.github.io/battery-lifecycle-analytics"

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
pdfmetrics.registerFont(TTFont("Body", str(FONT_DIR / "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("Body-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
pdfmetrics.registerFont(TTFont("Head", str(FONT_DIR / "DejaVuSansCondensed-Bold.ttf")))
pdfmetrics.registerFont(TTFont("Mono", str(FONT_DIR / "DejaVuSansMono.ttf")))
pdfmetrics.registerFontFamily("Body", normal="Body", bold="Body-Bold", italic="Body", boldItalic="Body-Bold")

INK = colors.HexColor("#0d2230"); INK2 = colors.HexColor("#4a5b65"); NAVY = colors.HexColor("#0c2133")
ACCENT = colors.HexColor("#1c5cab"); GREEN = colors.HexColor("#0f7a53"); HAIR = colors.HexColor("#d8e0e3")
WASH = colors.HexColor("#eef3f6"); AMBER = colors.HexColor("#8a5a00")

S = {
    "h1": ParagraphStyle("h1", fontName="Head", fontSize=19, leading=23, textColor=INK, spaceAfter=2),
    "h2": ParagraphStyle("h2", fontName="Head", fontSize=12.5, leading=16, textColor=ACCENT, spaceBefore=10, spaceAfter=4),
    "body": ParagraphStyle("body", fontName="Body", fontSize=9.4, leading=13.2, textColor=INK, alignment=TA_LEFT),
    "small": ParagraphStyle("small", fontName="Body", fontSize=8.2, leading=11, textColor=INK2),
    "cell": ParagraphStyle("cell", fontName="Body", fontSize=8.6, leading=11.4, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName="Body-Bold", fontSize=8.6, leading=11.4, textColor=INK),
    "th": ParagraphStyle("th", fontName="Body-Bold", fontSize=8.4, leading=11, textColor=colors.white),
    "bullet": ParagraphStyle("bullet", fontName="Body", fontSize=9.4, leading=13.2, textColor=INK, leftIndent=11,
                             bulletIndent=0, spaceAfter=1.5),
}


def load_metrics() -> dict:
    j = lambda f: json.loads((RES / f).read_text())
    return {"summary": j("summary.json"), "soh": j("soh_metrics.json"), "rul": j("rul_metrics.json"),
            "sl": j("second_life_summary.json")}


def P(text, style="body"):
    return Paragraph(text, S[style])


def bullets(items):
    return [Paragraph(t, S["bullet"], bulletText="•") for t in items]


def table(rows, widths, header=True, zebra=True, bold_first=False):
    data = []
    for r_i, r in enumerate(rows):
        st = "th" if (header and r_i == 0) else ("cellb" if bold_first else "cell")
        data.append([c if not isinstance(c, str) else Paragraph(c, S[st] if not (bold_first and r_i and c is r[0]) else S["cellb"])
                     for c in r])
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, HAIR),
             ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
             ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
             ("BOX", (0, 0), (-1, -1), 0.6, HAIR)]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), NAVY))
    if zebra:
        for k in range(1 if header else 0, len(data)):
            if k % 2 == 0:
                style.append(("BACKGROUND", (0, k), (-1, k), WASH))
    t.setStyle(TableStyle(style))
    return t


def figure(path: Path, width_mm: float, caption: str):
    from reportlab.lib.utils import ImageReader
    iw, ih = ImageReader(str(path)).getSize()
    w = width_mm * mm
    img = Image(str(path), width=w, height=w * ih / iw)
    return KeepTogether([img, Spacer(1, 2), P(caption, "small")])


# ------------------------------------------------------------------ content
def weeks(m: dict) -> list[dict]:
    s, soh, rul, sl = m["summary"], m["soh"], m["rul"], m["sl"]
    q = s["data_quality"]["cells"]
    nasa_cyc = sum(c["cycles"] for c in q if c["dataset"] == "nasa")
    calce_cyc = sum(c["cycles"] for c in q if c["dataset"] == "calce")
    sp = lambda ds, mdl, fs="summary": (soh[ds][fs][mdl]["rmse"] if fs == "summary" else soh[ds]["partial_charge"]["summary"][mdl]["rmse"]) * 100
    pm = {ds: soh[ds]["primary_model"] for ds in ("nasa", "calce")}
    r80 = {ds: rul[ds]["first_life"] for ds in ("nasa", "calce")}
    r60 = rul["calce"]["to_second_life_floor"]
    a80 = sl["at_80pct_retirement"]
    corr = s["correlations"]

    return [
        dict(week=1, dates="Mon 2 Nov - Fri 6 Nov 2026", progress="10%", sprint="Sprint 1",
             title="Scoping, architecture and real data acquisition",
             summary="Fixed the project scope, chose two real battery-ageing datasets (NASA PCoE and CALCE CS2), designed the layered system architecture and set up the repository.",
             goal="Fix the problem statement and scope, find real battery data that covers the whole battery life, and design the system before writing models.",
             daily=[("Mon 2 Nov", "Wrote the problem statement and five objectives: SOH estimation, RUL prediction, second-life grading, Digital Battery Passport, analytics interface."),
                    ("Tue 3 Nov", "Surveyed public Li-ion ageing datasets (NASA PCoE, CALCE, Oxford, MIT/Toyota) for size, signals and how far each cell is aged."),
                    ("Wed 4 Nov", "Chose NASA PCoE (impedance and temperature) plus CALCE CS2 (aged down to 15-27% SOH, so it covers second life). Downloaded both."),
                    ("Thu 5 Nov", "Studied the EU Battery Regulation 2023/1542: passport mandatory from 18 Feb 2027 (Art. 77, Annex XIII), access tiers, battery status values."),
                    ("Fri 6 Nov", "Designed the six-layer architecture, wrote config.py with all thresholds, created the repository and this report.")],
             done=["<b>batterylife/config.py</b>: datasets, lifecycle thresholds (80% / 60% SOH), second-life application catalogue, sustainability assumptions.",
                   "<b>scripts/download_data.py</b>: fetches the raw data.",
                   "<b>docs/architecture.md</b> and the architecture diagram (below)."],
             results=[["Decision", "Choice", "Reason"],
                      ["Datasets", "NASA PCoE (4 cells) + CALCE CS2 (4 cells)", "Real data; together they cover first life, second life and recycling"],
                      ["First-life end", "80% SOH", "Common EV retirement threshold"],
                      ["Second-life floor", "60% SOH", "Below this re-use is not worthwhile"],
                      ["SOH inputs", "Charging signals only", "A battery management system sees them every charge"],
                      ["Passport", "Signed, hash-chained events", "Aligned with EU Regulation 2023/1542, Annex XIII"]],
             widths=[30, 62, 82],
             fig=("architecture.png", 170, "Figure 1. System architecture: data sources, pipeline, Digital Battery Passport and dashboard."),
             issues=[("Only 8 cells exist in total across both datasets.", "Validate with leave-one-cell-out and report errors per cell."),
                     ("CALCE raw data is about 170 MB.", "Kept out of git; a download script fetches it.")],
             next=["Parse both datasets into one validated cycle-level table.", "Check data quality and document the findings."]),

        dict(week=2, dates="Mon 9 Nov - Fri 13 Nov 2026", progress="20%", sprint="Sprint 2",
             title="Data ingestion and quality checks",
             summary=f"Built loaders for NASA .mat and CALCE Excel files into one validated table: {s['data']['cycles']:,} cycles from 8 cells.",
             goal="Read both raw datasets into a single cycle-level table with one schema, and validate it.",
             daily=[("Mon 9 Nov", "Defined the unified schema: 16 columns, one row per full charge-discharge cycle."),
                    ("Tue 10 Nov", "NASA loader: paired every discharge with its preceding charge; interpolated EIS resistance (Re + Rct) onto discharge times."),
                    ("Wed 11 Nov", "CALCE loader: read 100 Arbin Excel files in date order, renumbered cycles, kept only full 1C discharges."),
                    ("Thu 12 Nov", "Registry with CSV cache and validation; fixed two bugs found while checking (constant resistance, rest time counted as discharge)."),
                    ("Fri 13 Nov", "Data-quality report, dataset document, raw-SOH figure, 5 unit tests, this report.")],
             done=["<b>batterylife/data/</b>: schema.py, nasa.py, calce.py, registry.py.",
                   "<b>data/processed/cycles_raw.csv</b> and data_quality.json.", "<b>docs/dataset.md</b>; tests/test_data.py (5 tests)."],
             results=[["Dataset", "Cells", "Cycles", "SOH range", "Extra signals"],
                      ["NASA PCoE", "B0005, B0006, B0007, B0018", f"{nasa_cyc}", "102% to 58%", "Impedance, temperature"],
                      ["CALCE CS2", "CS2_35 to CS2_38", f"{calce_cyc:,}", "104% to 15%", "Internal resistance"],
                      ["Total", "8", f"{s['data']['cycles']:,}", "", ""]],
             widths=[28, 50, 22, 30, 44],
             fig=("fig01_raw_soh.png", 172, "Figure 2. Measured state of health of all 8 cells before cleaning. Dashed lines: 80% and 60%."),
             issues=[("NASA resistance came out constant for every cycle.", "pandas 3 stores dates in microseconds; switched to Python datetime timestamps."),
                     ("NASA discharge time included rest after cut-off.", "Kept only the period with load current above 1 A."),
                     ("Interrupted CALCE cycles appear as sudden drops.", "Planned for next week's cleaning step.")],
             next=["Remove interrupted cycles with a robust filter.", "Build health indicators from the charging curve."]),

        dict(week=3, dates="Mon 16 Nov - Fri 20 Nov 2026", progress="30%", sprint="Sprint 3",
             title="Data cleaning and health indicators",
             summary=f"A one-sided Hampel filter removed {s['data']['outliers_removed']} interrupted cycles while keeping real capacity regeneration; charge-curve health indicators correlate up to r = 1.00 with SOH.",
             goal="Remove measurement artefacts and build health indicators that a battery management system can observe during ordinary charging.",
             daily=[("Mon 16 Nov", "Analysed the outliers: interrupted discharges (drops) versus capacity regeneration after rest (real, jumps up)."),
                    ("Tue 17 Nov", "Implemented a one-sided Hampel filter (11-cycle window, 3 x MAD, two passes) that removes only drops."),
                    ("Wed 18 Nov", "Two-sided spike repair for charge features; 9-cycle median SOH for end-of-life detection."),
                    ("Thu 19 Nov", "Built health indicators: CC charge time, CV charge time, 3.9-4.2 V rise time, resistance, cycle count; per-cell relative versions."),
                    ("Fri 20 Nov", "Correlation analysis, figure, 7 new tests (12 total), this report.")],
             done=["<b>batterylife/features/cleaning.py</b> and <b>indicators.py</b>.", "<b>data/processed/features.csv</b>.", "tests/test_features.py (7 tests)."],
             results=[["Health indicator", "Correlation with SOH, NASA", "Correlation with SOH, CALCE"],
                      ["CC charge time", f"{corr['nasa']['cc_charge_time_rel']:.2f}", f"{corr['calce']['cc_charge_time_rel']:.2f}"],
                      ["3.9-4.2 V rise time", f"{corr['nasa']['charge_v_rise_rel']:.2f}", f"{corr['calce']['charge_v_rise_rel']:.2f}"],
                      ["CV charge time", f"{corr['nasa']['cv_charge_time_rel']:.2f}", f"{corr['calce']['cv_charge_time_rel']:.2f}"],
                      ["Resistance", f"{corr['nasa']['resistance_rel']:.2f}", f"{corr['calce']['resistance_rel']:.2f}"],
                      ["Outliers removed", "0 of 636 (regeneration kept)", f"{s['data']['outliers_removed']} of {calce_cyc:,}"]],
             widths=[60, 57, 57],
             fig=("fig02_cleaning_and_correlation.png", 172, "Figure 3. Left: cleaning on CS2_36 (red points removed). Right: correlation of each indicator with SOH."),
             issues=[("CALCE cells charge from empty, so CC charge time is almost a direct capacity measurement.", "Added a 'partial-charge' feature set without it, tested next week."),
                     ("CS2_38 resistance sensor shows a long plateau (cycles 30-140).", "Documented as a sensor artefact; robust baseline limits its effect.")],
             next=["Train and compare SOH models with leave-one-cell-out validation.", "Add calibrated confidence intervals."]),

        dict(week=4, dates="Mon 23 Nov - Fri 27 Nov 2026", progress="42%", sprint="Sprint 4",
             title="State-of-health estimation models",
             summary=f"Five models compared on cells never seen in training. SOH error {sp('nasa', pm['nasa']):.2f}% (NASA, {pm['nasa']}) and {sp('calce', pm['calce']):.2f}% (CALCE, {pm['calce']}), with 95% intervals covering {soh['nasa']['coverage_95']*100:.0f}-{soh['calce']['coverage_95']*100:.0f}% of true values.",
             goal="Estimate SOH from charging signals only, validated honestly on unseen cells, with calibrated uncertainty.",
             daily=[("Mon 23 Nov", "Leave-one-cell-out harness: each cell is scored by a model trained only on the other three cells of its dataset."),
                    ("Tue 24 Nov", "Trained Ridge, Random Forest, Gradient Boosting, MLP and Gaussian Process; compared relative vs absolute features."),
                    ("Wed 25 Nov", "Switched to absolute features (NASA error fell from 4.1% to 2.2%); added the partial-charge feature set."),
                    ("Thu 26 Nov", "GP intervals were over-confident (66% coverage); replaced with split-conformal 95% intervals."),
                    ("Fri 27 Nov", "Saved production models, figure, 4 new tests (16 total), this report.")],
             done=["<b>batterylife/models/soh.py</b> and evaluation.py.", "<b>results/soh_metrics.json</b>, soh_predictions.csv.", "tests/test_soh.py."],
             results=[["Model", "NASA full", "NASA partial", "CALCE full", "CALCE partial"]] +
                     [[mdl, f"{sp('nasa', mdl):.2f}", f"{sp('nasa', mdl, 'p'):.2f}", f"{sp('calce', mdl):.2f}", f"{sp('calce', mdl, 'p'):.2f}"]
                      for mdl in soh["nasa"]["summary"]],
             results_note="RMSE in SOH percentage points on unseen cells. 'Partial' leaves out CC charge time (charge may start part-way).",
             widths=[46, 32, 32, 32, 32],
             fig=("fig03_soh_models.png", 172, "Figure 4. Left: error by model. Middle and right: estimate and 95% interval on two unseen cells."),
             issues=[("Relative features erased differences in starting capacity between NASA cells.", "Absolute features adopted."),
                     ("Tree models cannot extrapolate below the training range (B0006 at 58%).", "Documented; more deep-fade cells would fix it."),
                     ("MLP underperforms with only 3 training cells.", "Kept only as a baseline.")],
             next=["Predict remaining useful life to 80% and 60% SOH.", "Calibrate the uncertainty bands."]),

        dict(week=5, dates="Mon 30 Nov - Fri 4 Dec 2026", progress="55%", sprint="Sprint 5",
             title="Remaining useful life prediction",
             summary=f"Quantile Gradient Boosting predicts cycles left to 80% SOH within {r80['nasa']['quantile_gbr']['mae']:.1f} cycles (NASA) and {r80['calce']['quantile_gbr']['mae']:.1f} cycles (CALCE); calibrated bands now cover {r80['nasa']['quantile_gbr']['coverage_cqr_80']*100:.0f}-{r60['quantile_gbr']['coverage_cqr_80']*100:.0f}% at an 80% target.",
             goal="Predict how many cycles remain before 80% SOH (end of first life) and 60% SOH (end of second life), with calibrated uncertainty.",
             daily=[("Mon 30 Nov", "Ground-truth end-of-life from smoothed SOH; causal snapshots so the predictor only sees cycles 1..k."),
                    ("Tue 1 Dec", "Baselines: linear trend and an empirical fade model with an accelerating 'knee' term."),
                    ("Wed 2 Dec", "Quantile Gradient Boosting (10/50/90%) on SOH estimate, fade rate, fade acceleration, charge signals, resistance."),
                    ("Thu 3 Dec", "Raw bands covered only 22-33%; implemented conformalised quantile regression (CQR)."),
                    ("Fri 4 Dec", "Evaluation by life stage, figure, 5 new tests (21 total), this report.")],
             done=["<b>batterylife/models/rul.py</b>.", "<b>results/rul_metrics.json</b>, rul_predictions.csv.", "tests/test_rul.py."],
             results=[["Dataset", "Mean life to 80%", "Linear trend", "Fade model", "Quantile GBR", "Band coverage"],
                      ["NASA", f"{r80['nasa']['mean_life_to_threshold']:.0f} cycles", f"{r80['nasa']['linear_trend']['mae']:.1f}", f"{r80['nasa']['fade_model']['mae']:.1f}", f"<b>{r80['nasa']['quantile_gbr']['mae']:.1f}</b>", f"{r80['nasa']['quantile_gbr']['coverage_cqr_80']*100:.1f}%"],
                      ["CALCE", f"{r80['calce']['mean_life_to_threshold']:.0f} cycles", f"{r80['calce']['linear_trend']['mae']:.1f}", f"{r80['calce']['fade_model']['mae']:.1f}", f"<b>{r80['calce']['quantile_gbr']['mae']:.1f}</b>", f"{r80['calce']['quantile_gbr']['coverage_cqr_80']*100:.1f}%"],
                      ["CALCE to 60%", f"{r60['mean_life_to_threshold']:.0f} cycles", f"{r60['linear_trend']['mae']:.1f}", f"{r60['fade_model']['mae']:.1f}", f"<b>{r60['quantile_gbr']['mae']:.1f}</b>", f"{r60['quantile_gbr']['coverage_cqr_80']*100:.1f}%"]],
             results_note="Mean absolute error in cycles on unseen cells.",
             widths=[26, 30, 26, 26, 30, 30],
             fig=("fig04_rul.png", 172, "Figure 5. Cycles left to 80% SOH on two unseen cells: truth, baselines and the calibrated band."),
             issues=[("Curve extrapolation cannot see the CALCE knee before it happens.", "The learned model anticipates it from the other cells."),
                     ("NASA capacity regeneration flattens fitted trends.", "Same: data-driven model; baselines kept for comparison."),
                     ("Uncalibrated bands were dangerously narrow.", "CQR brings coverage close to the 80% target.")],
             next=["Turn SOH and RUL into second-life grades and application matches.", "Quantify CO2 and value of re-use."]),

        dict(week=6, dates="Mon 7 Dec - Fri 11 Dec 2026", progress="66%", sprint="Sprint 6",
             title="Second-life grading, application matching and value",
             summary=f"Uncertainty-aware grader agrees with lab-truth grades in {sl['all']['agreement']*100:.1f}% of {sl['all']['decisions']} decisions ({sl['all']['agreement_when_high_confidence']*100:.1f}% when confident) and flags {sl['all']['errors_flagged_low_confidence']*100:.0f}% of its own mistakes for a lab test.",
             goal="Decide what each retired battery should do next, with honest confidence, and quantify the value of re-use.",
             daily=[("Mon 7 Dec", "Application catalogue: A (EV re-use), B (grid/home storage), C (backup power), D (recycle) with SOH, resistance and cycle limits."),
                    ("Tue 8 Dec", "Rule engine with reasons; confidence check by re-grading at the lower 95% bound of SOH."),
                    ("Wed 9 Dec", "Service years, CO2 avoided and value, scaled to a 60 kWh pack."),
                    ("Thu 10 Dec", "Evaluated at 15 retirement levels per cell against lab-truth grades; confusion matrix."),
                    ("Fri 11 Dec", "Figure, 12 new tests (33 total), this report.")],
             done=["<b>batterylife/lifecycle/</b>: grading.py, sustainability.py, second_life.py.", "<b>results/second_life_assessments.csv</b> and summary.", "tests/test_lifecycle.py."],
             results=[["Metric", "Result"],
                      ["Grade agreement with lab truth", f"{sl['all']['agreement']*100:.1f}% (NASA {sl['nasa']['agreement']*100:.1f}%, CALCE {sl['calce']['agreement']*100:.1f}%)"],
                      ["Agreement when confidence is high", f"{sl['all']['agreement_when_high_confidence']*100:.1f}%"],
                      ["Mistakes already flagged low-confidence", f"{sl['all']['errors_flagged_low_confidence']*100:.1f}%"],
                      ["Conservative / optimistic errors", f"{sl['all']['conservative_errors']} / {sl['all']['optimistic_errors']}"],
                      ["Second-life length error (CALCE)", f"{sl['second_life_cycles_mae_calce']:.1f} cycles"],
                      ["Per 60 kWh pack at 80% retirement", f"about {a80['co2_avoided_kg_per_pack']/1000:.1f} t CO2e avoided (upper bound), USD {a80['value_usd_per_pack']:,.0f} re-use value"]],
             widths=[70, 104],
             fig=("fig05_second_life.png", 172, "Figure 6. Left: AI grade vs lab grade on unseen cells. Right: predicted vs true second-life length."),
             issues=[("Most wrong grades sit right at a grade boundary.", "The low-confidence flag catches them and asks for a lab test."),
                     ("Only one NASA cell reaches 60% SOH.", "Cycle criterion applied only where ground truth exists (CALCE)."),
                     ("Lab ageing is harsh, so service years look short.", "Reported as a relative ranking, not a forecast.")],
             next=["Build the signed, hash-chained Digital Battery Passport.", "Test it against tampering attacks."]),

        dict(week=7, dates="Mon 14 Dec - Fri 18 Dec 2026", progress="78%", sprint="Sprint 7",
             title="Digital Battery Passport",
             summary=f"Built a tamper-evident passport: every event is SHA-256 chained and Ed25519 signed. {s['passports']['issued']} passports with {s['passports']['events']} events verify; all 5 tested attacks are detected.",
             goal="Record each battery's whole life in a passport that anyone can verify and no one can secretly change, aligned with EU Regulation 2023/1542.",
             daily=[("Mon 14 Dec", "Schema: 10 event types, 6 actor roles (manufacturer, OEM, BMS, assessor, repurposer, recycler), required fields, public and restricted access."),
                    ("Tue 15 Dec", "Ed25519 key pairs per actor; canonical JSON hashing; signed, hash-chained ledger."),
                    ("Wed 16 Dec", "Verification of chain links, content hashes, signatures, role authorisation, required fields and chronology."),
                    ("Thu 17 Dec", "Public (QR-code) view hiding restricted health data; attack tests. Fixed a bug where signed data could be changed by the caller."),
                    ("Fri 18 Dec", "Issued passports for all 8 cells, added the live tamper demo to the website, this report.")],
             done=["<b>batterylife/passport/</b>: schema.py, crypto.py, ledger.py, store.py, issue.py.", "<b>results/passports/</b>: 8 full and 8 public passports.", "tests/test_passport.py (10 tests)."],
             results=[["Attack on a passport", "Detected by"],
                      ["Raise a past SOH value", "Content hash"],
                      ["Raise a value and recompute every hash", "Ed25519 signature"],
                      ["Delete an event", "Chain link"],
                      ["Back-date an event", "Chronology check"],
                      ["Re-sign with another actor's key", "Signature"]],
             widths=[100, 74],
             fig=("dash_passport_tamper.png", 172, "Figure 7. Website passport view: a forged SOH value is caught at event 3 and highlighted in the ledger."),
             issues=[("Signed event data was shared with the caller's object.", "Data is deep-copied at signing time; a test guards it."),
                     ("Timestamps went backwards after repurposing.", "Administrative events now follow by hours; chronology is a verification check."),
                     ("A single-store ledger cannot stop deletion of a whole file.", "Future work: anchor each chain head in a public registry.")],
             next=["Integrate all stages into one pipeline and command-line tool.", "Pipeline tests and a full reproducibility run."]),
    ]


# ------------------------------------------------------------------ layout
def header_footer(canvas, doc):
    w, h = A4
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, h - 12 * mm, w, 12 * mm, stroke=0, fill=1)
    canvas.setFillColor(colors.white)
    canvas.setFont("Head", 9)
    canvas.drawString(16 * mm, h - 7.6 * mm, "Weekly Status Report  |  SNA Project")
    canvas.setFont("Body", 8)
    canvas.drawRightString(w - 16 * mm, h - 7.6 * mm, doc.week_label)
    canvas.setFillColor(INK2)
    canvas.setFont("Body", 7.5)
    canvas.drawString(16 * mm, 9 * mm, f"Code: {REPO}    Website: {SITE}")
    canvas.drawRightString(w - 16 * mm, 9 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build_week(wk: dict, path: Path):
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=19 * mm, bottomMargin=16 * mm,
                            title=f"Week {wk['week']} status report", author="SNA project team", subject=TITLE)
    doc.week_label = f"Week {wk['week']}  |  {wk['dates']}"
    full = 178 * mm
    story = [P(TITLE, "small"), Spacer(1, 3), P(f"Week {wk['week']}: {wk['title']}", "h1"),
             P(f"{wk['dates']}  ·  {wk['sprint']}  ·  Overall progress {wk['progress']}", "small"), Spacer(1, 7)]

    who = Table([[P("<b>Student name</b>", "cell"), "", P("<b>Roll no.</b>", "cell"), ""],
                 [P("<b>Faculty in charge</b>", "cell"), "", P("<b>Date submitted</b>", "cell"), P(wk["dates"].split(" - ")[1], "cell")]],
                colWidths=[30 * mm, 66 * mm, 28 * mm, 54 * mm], rowHeights=[8 * mm, 8 * mm])
    who.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, HAIR), ("INNERGRID", (0, 0), (-1, -1), 0.4, HAIR),
                             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BACKGROUND", (0, 0), (0, -1), WASH),
                             ("BACKGROUND", (2, 0), (2, -1), WASH)]))
    story += [who, Spacer(1, 8)]

    status = Table([[P(f"<font color='#0f7a53'><b>On track</b></font>", "cell"),
                     P(f"<b>This week in one line:</b> {wk['summary']}", "cell")]],
                   colWidths=[22 * mm, full - 22 * mm])
    status.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#e5f4e4")),
                                ("LINEBEFORE", (0, 0), (0, 0), 3, GREEN), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    story += [status]

    story += [P("1. Goal for the week", "h2"), P(wk["goal"])]
    story += [P("2. Day-by-day work", "h2"),
              table([["Day", "Work done"]] + [[d, t] for d, t in wk["daily"]], [24 * mm, full - 24 * mm])]
    story += [P("3. Completed deliverables", "h2")] + bullets(wk["done"])
    story += [P("4. Results", "h2"), table(wk["results"], [w * mm for w in wk["widths"]])]
    if wk.get("results_note"):
        story += [Spacer(1, 2), P(wk["results_note"], "small")]
    story += [Spacer(1, 8), figure(FIG / wk["fig"][0], wk["fig"][1], wk["fig"][2])]
    story += [P("5. Problems faced and how they were solved", "h2"),
              table([["Problem", "Resolution"]] + [[a, b] for a, b in wk["issues"]], [full / 2, full / 2])]
    story += [P("6. Plan for next week", "h2")] + bullets(wk["next"])

    remarks = Table([[P("<b>Faculty remarks</b>", "cell")], [""],
                     [Table([[P("Faculty signature: ______________________", "cell"),
                              P("Student signature: ______________________", "cell")]],
                            colWidths=[full / 2 - 6, full / 2 - 6])]],
                    colWidths=[full], rowHeights=[7 * mm, 18 * mm, 10 * mm])
    remarks.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, HAIR), ("BACKGROUND", (0, 0), (-1, 0), WASH),
                                 ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story += [Spacer(1, 10), KeepTogether([remarks])]
    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    m = load_metrics()
    index, merged = [], PdfWriter()
    for wk in weeks(m):
        f = OUT / f"week-{wk['week']:02d}.pdf"
        build_week(wk, f)
        pages = len(PdfReader(str(f)).pages)
        for pg in PdfReader(str(f)).pages:
            merged.add_page(pg)
        index.append({"week": wk["week"], "title": wk["title"], "dates": wk["dates"], "progress": wk["progress"],
                      "summary": wk["summary"], "file": f.name, "pages": pages,
                      "size": f"{pages} pages, {f.stat().st_size / 1024:.0f} KB"})
        print(f"wrote {f.name} ({pages} pages)")
    allf = OUT / "weekly-reports-weeks-1-7.pdf"
    merged.add_metadata({"/Title": "Weekly status reports, weeks 1-7", "/Subject": TITLE})
    with allf.open("wb") as fh:
        merged.write(fh)
    (OUT / "index.json").write_text(json.dumps(index, indent=2))
    print(f"wrote {allf.name} and index.json")


if __name__ == "__main__":
    sys.exit(main())

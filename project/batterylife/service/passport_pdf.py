"""Printable Digital Battery Passport (PDF) with a QR code.

The QR code opens the passport on the server that issued the document and
carries the head hash, so a reader can check that the printed copy matches the
live record. The content respects the reader's access tier: a public copy
leaves out the restricted sections and events.
"""
from __future__ import annotations

import io
from pathlib import Path
from urllib.parse import quote

from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..passport.ledger import Passport
from ..passport.schema import EVENT_TYPES, PUBLIC, SECTIONS

PUBLIC_SITE = "https://aarnavbms.github.io/battery-lifecycle-analytics/"
INK, MUTED, HAIR, BLUE = colors.HexColor("#14202b"), colors.HexColor("#5b6975"), colors.HexColor("#d5dce2"), colors.HexColor("#1c5cab")
GRADE = {"A": "#1a8f63", "B": "#1c5cab", "C": "#b7791f", "D": "#b4412f"}
BODY, BOLD, MONO = "Helvetica", "Helvetica-Bold", "Courier"


def _fonts() -> None:
    """Use the DejaVu fonts that ship with matplotlib; fall back to the PDF base fonts."""
    global BODY, BOLD, MONO
    if BODY != "Helvetica":
        return
    try:
        import matplotlib
        d = Path(matplotlib.__file__).parent / "mpl-data" / "fonts" / "ttf"
        pdfmetrics.registerFont(TTFont("DBP-Body", str(d / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DBP-Bold", str(d / "DejaVuSans-Bold.ttf")))
        pdfmetrics.registerFont(TTFont("DBP-Mono", str(d / "DejaVuSansMono.ttf")))
        BODY, BOLD, MONO = "DBP-Body", "DBP-Bold", "DBP-Mono"
    except Exception:
        pass


def passport_url(passport_id: str, head_hash: str, base_url: str = PUBLIC_SITE) -> str:
    base = base_url if base_url.endswith("/") else base_url + "/"
    page = "#passports" if "github.io" in base else "passports"
    return f"{base}{page}?id={quote(passport_id)}&head={head_hash[:16]}"


def _qr(text: str, size: float) -> Drawing:
    w = QrCodeWidget(text, barLevel="M")
    x0, y0, x1, y1 = w.getBounds()
    d = Drawing(size, size, transform=[size / (x1 - x0), 0, 0, size / (y1 - y0), 0, 0])
    d.add(w)
    return d


def _fmt(v) -> str:
    if v is None:
        return "not recorded"
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)


def build(p: Passport, verification: dict, access: str = "full", base_url: str = PUBLIC_SITE) -> bytes:
    _fonts()
    public = access == PUBLIC
    def st(name, **kw):
        return ParagraphStyle(name, **{"fontName": BODY, "fontSize": 9, "leading": 12.5, "textColor": INK, **kw})
    h1 = ParagraphStyle("h1", fontName=BOLD, fontSize=19, leading=23, textColor=INK)
    h2 = ParagraphStyle("h2", fontName=BOLD, fontSize=11, leading=14, textColor=BLUE, spaceBefore=10, spaceAfter=4)
    body, small = st("body"), st("small", fontSize=7.5, leading=10, textColor=MUTED)
    mono = ParagraphStyle("mono", fontName=MONO, fontSize=7, leading=9, textColor=INK)
    url = passport_url(p.passport_id, p.head_hash, base_url)
    secs = p.sections()
    events = p.events
    if public:
        secs = {k: v for k, v in secs.items() if SECTIONS[k] == PUBLIC}
        events = [e for e in p.events if EVENT_TYPES[e["type"]][1] == PUBLIC]
    grade = (p.sections()["lifecycle_decision"] or {}).get("grade")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm,
                            bottomMargin=14 * mm, title=f"Digital Battery Passport {p.passport_id}",
                            author="Battery Lifecycle Analytics")
    W = A4[0] - 32 * mm
    ok = verification["valid"]
    verdict = ("<font color='#1a8f63'><b>VERIFIED</b></font>: all " if ok else "<font color='#b4412f'><b>NOT VALID</b></font>: failed ") + \
        (f"{verification['events']} events pass the six checks" if ok else
         ", ".join(k for k, v in verification["checks"].items() if not v))
    head = [
        Paragraph("DIGITAL BATTERY PASSPORT", ParagraphStyle("k", fontName=BOLD, fontSize=8, textColor=MUTED, leading=11)),
        Paragraph(p.passport_id, h1),
        Spacer(1, 3),
        Paragraph(f"Battery <b>{p.battery_id}</b> &nbsp;·&nbsp; Status <b>{p.status()}</b>"
                  + ("" if public or not grade else f" &nbsp;·&nbsp; Second-life grade <font color='{GRADE[grade]}'><b>{grade}</b></font>"), body),
        Paragraph(verdict, body),
        Paragraph(f"Access tier: <b>{'public' if public else 'legitimate interest (full)'}</b>. "
                  "Schema aligned with Regulation (EU) 2023/1542, Article 77 and Annex XIII.", small),
    ]
    story = [Table([[head, _qr(url, 30 * mm)]], colWidths=[W - 34 * mm, 34 * mm],
                   style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                     ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("ALIGN", (1, 0), (1, 0), "RIGHT")])),
             Paragraph("Scan to open the live record and check that it matches this copy.", small)]

    titles = {"general_information": "General information", "carbon_footprint": "Carbon footprint",
              "performance_and_durability": "Performance and durability", "battery_status": "Battery status",
              "state_of_health": "State of health (restricted)", "lifecycle_decision": "Lifecycle decision (restricted)"}
    for key, sec in secs.items():
        if not sec:
            continue
        flat = {}
        for k, v in sec.items():
            if isinstance(v, dict):
                flat.update({f"{k.replace('latest_', '')}: {kk}": vv for kk, vv in v.items()})
            else:
                flat[k] = v
        rows = [[Paragraph(k.replace("_", " "), small), Paragraph(_fmt(v), body)] for k, v in flat.items()]
        if not rows:
            continue
        story += [Paragraph(titles.get(key, key), h2),
                  Table(rows, colWidths=[52 * mm, W - 52 * mm],
                        style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.3, HAIR),
                                          ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                                          ("LEFTPADDING", (0, 0), (-1, -1), 0)]))]

    story.append(Paragraph(f"Signed event chain ({len(events)} {'public ' if public else ''}events)", h2))
    hdr = [Paragraph(f"<b>{t}</b>", small) for t in ("#", "Date", "Event", "Signed by", "Hash")]
    rows = [hdr] + [[Paragraph(str(e["index"]), small), Paragraph(e["timestamp"][:10], small),
                     Paragraph(e["type"].replace("_", " ").title(), small), Paragraph(e["actor_id"], small),
                     Paragraph(e["hash"][:20] + "…", mono)] for e in events]
    story.append(Table(rows, colWidths=[9 * mm, 21 * mm, 52 * mm, 44 * mm, W - 126 * mm], repeatRows=1,
                       style=TableStyle([("LINEBELOW", (0, 0), (-1, 0), 0.8, INK), ("LINEBELOW", (0, 1), (-1, -1), 0.25, HAIR),
                                         ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                                         ("LEFTPADDING", (0, 0), (-1, -1), 0), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")])))
    story += [Spacer(1, 8), Paragraph("Head hash (fingerprint of the whole chain)", small), Paragraph(p.head_hash, mono),
              Spacer(1, 4),
              Paragraph("Each event stores the SHA-256 hash of the event before it and an Ed25519 signature from the actor "
                        "who issued it. Changing, deleting or re-ordering any event changes the head hash and fails "
                        "verification. This printed copy is a snapshot; the live record is authoritative.", small)]
    doc.build(story)
    return buf.getvalue()

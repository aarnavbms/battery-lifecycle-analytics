"""Export the dashboard as one self-contained web page (no server needed).

    python scripts/export_static.py          -> site/index.html

Every API response is captured from the Flask app and embedded. Grading and
passport verification run in the browser (dashboard/static_site/runtime.js),
using the exact signed bytes of every passport event.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dashboard.app import ATTACKS, NAV_GROUPS, NAV_ICONS, app  # noqa: E402
import base64  # noqa: E402
from batterylife.passport import store  # noqa: E402
from batterylife.passport.crypto import canonical  # noqa: E402
from batterylife.passport.ledger import _body  # noqa: E402
from batterylife.passport.schema import REQUIRED_FIELDS  # noqa: E402

STATIC = ROOT / "dashboard" / "static"
OUT = ROOT / "site" / "index.html"
PLOTLY_FILE = ROOT / "vendor" / "plotly-2.35.2.min.js"   # plotly.js v2.35.2 (MIT), shipped next to the page
PUBLIC_DIR = ROOT / "site" / "public"
VIEWS = [(k.replace("_", "-"), url, label) for _, items in NAV_GROUPS for k, url, label, _ in items]
SCRIPTS = {"overview": "overview.js", "cells": "cells.js", "models": "models.js", "second-life": "second_life.js",
           "passports": "passports.js", "hardware": "hardware.js", "reports": "reports.js"}
REPORTS = ROOT / "docs" / "reports"

# single-page navigation instead of separate URLs
PATCHES = {
    "overview.js": [("location.href = `/cells?cell=${tr.dataset.cell}`", 'APP.go("cells", { cell: tr.dataset.cell })')],
    "cells.js": [('new URLSearchParams(location.search).get("cell")', 'APP.param("cell")'),
                 ('history.replaceState(null, "", `?cell=${id}`);', "")],
    "passports.js": [('new URLSearchParams(location.search).get("id")', 'APP.param("id")'),
                     ('history.replaceState(null, "", `?id=${current}`);', "")],
}

EXTRA_CSS = """
/* hosted version */
body::before { content: ""; position: fixed; inset: 0 0 auto; height: env(safe-area-inset-top, 0px);
               z-index: 30; background: var(--hero-bg); }
main { padding: 32px max(32px, env(safe-area-inset-right, 0px)) 48px max(32px, env(safe-area-inset-left, 0px)); }
.foot { padding-left: max(32px, env(safe-area-inset-left, 0px)); padding-right: max(32px, env(safe-area-inset-right, 0px)); }
.hosted-note { color: var(--muted); font-size: 13px; margin: -18px 0 22px; max-width: 80ch; }
@media (max-width: 760px) {
  .top { padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
  main { padding: 20px max(16px, env(safe-area-inset-right, 0px)) 40px max(16px, env(safe-area-inset-left, 0px)); }
  .foot { padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
}
"""


def capture(client) -> dict:
    get = {}
    for url in ["/api/summary", "/api/fleet", "/api/models", "/api/second-life", "/api/passports", "/api/attacks",
                "/api/hardware", "/api/reports"]:
        get[url] = client.get(url).get_json()
    for c in get["/api/summary"]["cells"]:
        get[f"/api/cell/{c['cell_id']}"] = client.get(f"/api/cell/{c['cell_id']}").get_json()
    bodies, actors, meta = {}, None, None
    for pid in store.list_passports():
        for acc in ("full", "public"):
            get[f"/api/passport/{pid}?access={acc}"] = client.get(f"/api/passport/{pid}?access={acc}").get_json()
        p = store.load_passport(pid)
        bodies[pid] = [canonical(_body(e)).decode() for e in p.events]
        full = get[f"/api/passport/{pid}?access=full"]
        actors, meta = full["actors"], full["event_meta"]
    sl = get["/api/second-life"]
    return {"get": get, "bodies": bodies, "actors": actors, "event_meta": meta,
            "required_fields": REQUIRED_FIELDS, "applications": sl["applications"],
            "assumptions": sl["assumptions"], "attacks": ATTACKS}


def main_block(html: str) -> str:
    m = re.search(r"<main>(.*)</main>", html, re.S)
    inner = m.group(1)
    # inline images served from /static/img so the page has no extra requests
    def data_uri(mt):
        f = STATIC / "img" / mt.group(1)
        return 'src="data:image/png;base64,' + base64.b64encode(f.read_bytes()).decode() + '"'
    return re.sub(r'src="/static/img/([^"]+)"', data_uri, inner)


def sidebar() -> str:
    groups = []
    for group, items in NAV_GROUPS:
        links = "".join(
            f'<a href="#{k.replace("_", "-")}" data-nav="{k.replace("_", "-")}"><svg viewBox="0 0 24 24" aria-hidden="true">'
            f'<path d="{NAV_ICONS[icon]}"/></svg><span>{label}</span></a>' for k, _, label, icon in items)
        groups.append(f'<div class="nav-group"><span class="nav-label">{group}</span>{links}</div>')
    return "".join(groups)


def page_script(name: str) -> str:
    src = (STATIC / "js" / SCRIPTS[name]).read_text()
    for old, new in PATCHES.get(SCRIPTS[name], []):
        if old not in src:
            raise SystemExit(f"patch target not found in {SCRIPTS[name]}: {old}")
        src = src.replace(old, new)
    body = src.strip()
    assert body.startswith("(async () => {") and body.endswith("})();"), name
    return f'APP.register("{name}", async () => {{{body[len("(async () => {"):-len("})();")]}}});'


def build() -> Path:
    client = app.test_client()
    data = capture(client)
    sections = []
    for name, url, _ in VIEWS:
        inner = main_block(client.get(url).get_data(as_text=True))
        sections.append(f'<section data-view="{name}" hidden>{inner}</section>')
    nav = "".join(f'<a href="#{n}" data-nav="{n}">{label}</a>' for n, _, label in VIEWS)
    css = (STATIC / "css" / "app.css").read_text() + EXTRA_CSS
    data_json = json.dumps(data, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    scripts = "\n".join(page_script(n) for n, _, _ in VIEWS)
    icon = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect x='4' y='9' width='22' height='14' rx='3' fill='none' stroke='%231c5cab' stroke-width='2.5'/%3E%3Crect x='26' y='13' width='3' height='6' rx='1' fill='%231c5cab'/%3E%3Crect x='7' y='12' width='9' height='8' rx='1' fill='%231baf7a'/%3E%3C/svg%3E"
    html = f"""<title>Battery Lifecycle Analytics</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="icon" href="{icon}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,400..800&family=IBM+Plex+Mono:wght@500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>{css}</style>
<div class="shell">
<aside class="side" aria-label="Site navigation">
  <a class="brand" href="#overview">
    <svg viewBox="0 0 32 32" aria-hidden="true"><rect x="3" y="9" width="23" height="14" rx="3"/><rect class="tip" x="26" y="13" width="3" height="6" rx="1"/><rect class="charge" x="6" y="12" width="10" height="8" rx="1"/></svg>
    <span>Battery Lifecycle<small>Analytics &amp; Passports</small></span>
  </a>
  <nav aria-label="Sections">{sidebar()}</nav>
  <div class="side-foot">
    <button class="theme" id="themeToggle" type="button" aria-label="Switch light or dark theme">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3a9 9 0 1 0 9 9 7 7 0 0 1-9-9z"/></svg><span>Theme</span>
    </button>
    <p>8 real Li-ion cells. NASA PCoE and CALCE CS2 data.</p>
  </div>
</aside>
<div class="content">
<main>
{''.join(sections)}
</main>
<footer class="foot">Data from the NASA PCoE and CALCE CS2 ageing tests. Every model score is measured on cells the model never saw. Passport checks run in your browser with SHA-256 and Ed25519.</footer>
</div>
</div>
<script src="plotly.min.js"></script>
<script>window.__STATIC__ = {data_json};</script>
<script>{(ROOT / 'dashboard' / 'static_site' / 'runtime.js').read_text()}</script>
<script>{(STATIC / 'js' / 'common.js').read_text()}
UI.get = APP.get; UI.post = APP.post;</script>
<script>{scripts}</script>
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html)
    shutil.copyfile(PLOTLY_FILE, OUT.parent / "plotly.min.js")
    # standalone public website: full HTML document + Plotly, deployable to any static host
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    (PUBLIC_DIR / "index.html").write_text(
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '<style>:root{color-scheme:light;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}'
        'body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>\n</head>\n<body>\n'
        + html.replace('<meta name="claude:viewport-fit-sides" content="cover">\n', '') + '</body>\n</html>\n')
    shutil.copyfile(PLOTLY_FILE, PUBLIC_DIR / "plotly.min.js")
    (PUBLIC_DIR / ".nojekyll").write_text("")
    if REPORTS.exists():
        (PUBLIC_DIR / "reports").mkdir(exist_ok=True)
        for f in REPORTS.glob("*.pdf"):
            shutil.copyfile(f, PUBLIC_DIR / "reports" / f.name)
    return OUT


if __name__ == "__main__":
    p = build()
    print(f"wrote {p} ({p.stat().st_size / 1e6:.2f} MB)")

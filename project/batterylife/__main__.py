"""Command-line interface.

    python -m batterylife run [--fast] [--refresh]
    python -m batterylife verify [PASSPORT_ID ...]
    python -m batterylife tamper-demo [PASSPORT_ID]
    python -m batterylife assess --soh 0.78 --soh-lo 0.74 --resistance 1.2 [--cycles 250]
    python -m batterylife passport PASSPORT_ID [--public]
    python -m batterylife db                 rebuild the API database from the result files
    python -m batterylife explain            compute which signals the SOH models rely on
    python -m batterylife serve [--port N]   start the website and REST API
"""
from __future__ import annotations

import argparse
import copy
import json
import sys


def cmd_run(a):
    from .pipeline import run
    run(refresh=a.refresh, fast=a.fast)


def cmd_verify(a):
    from .passport import store
    from .passport.ledger import verify
    reg = store.load_registry()
    ids = a.ids or store.list_passports()
    bad = 0
    for pid in ids:
        r = verify(store.load_passport(pid), reg)
        bad += not r["valid"]
        print(f"{pid:22s} {'VALID' if r['valid'] else 'INVALID':8s} events={r['events']:3d} "
              f"head={r['head_hash'][:16]}...")
        for i in r["issues"][:5]:
            print(f"    event {i['index']} ({i['type']}): {i['check']} - {i['problem']}")
    sys.exit(1 if bad else 0)


def cmd_tamper(a):
    from .passport import store
    from .passport.ledger import verify
    reg = store.load_registry()
    pid = a.id or store.list_passports()[0]
    p = store.load_passport(pid)
    idx = next(e["index"] for e in p.events if e["type"] == "SOH_ASSESSMENT")
    print(f"Passport {pid}: {len(p.events)} events, verification: {verify(p, reg)['valid']}")
    forged = copy.deepcopy(p)
    old = forged.events[idx]["data"]["soh"]
    forged.events[idx]["data"]["soh"] = 0.99
    r = verify(forged, reg)
    print(f"Changed SOH in event {idx} from {old} to 0.99 -> valid={r['valid']}, "
          f"first bad event={r['first_bad_index']}, failed checks="
          f"{[k for k, v in r['checks'].items() if not v]}")
    from .passport import crypto
    from .passport.ledger import _body
    prev = forged.events[idx - 1]["hash"]
    for ev in forged.events[idx:]:
        ev["prev_hash"] = prev
        ev["hash"] = crypto.sha256_hex(_body(ev))
        prev = ev["hash"]
    r = verify(forged, reg)
    print(f"Attacker also recomputes all hashes -> valid={r['valid']}, failed checks="
          f"{[k for k, v in r['checks'].items() if not v]} (signatures cannot be forged)")


def cmd_assess(a):
    from .lifecycle.grading import assess
    r = assess(a.soh, a.soh_lo, a.resistance, a.cycles, a.cycles_lo)
    print(json.dumps(r.to_dict(), indent=2))


def cmd_passport(a):
    from .passport import store
    p = store.load_passport(a.id)
    print(json.dumps(p.to_dict("public" if a.public else "full")["sections"], indent=2))


def cmd_db(a):
    from .service import CTX, db
    if CTX.db.exists() and a.reset:
        CTX.db.unlink()
    conn = db.connect()
    print("synced:", db.sync_from_files(conn))
    from .service.auth import seed_users
    seed_users(conn)
    conn.commit()
    print("tables:", db.table_counts(conn))
    print("database:", CTX.db)


def cmd_explain(a):
    from .service import explain
    explain.run()
    print("wrote", explain.OUT)


def cmd_serve(a):
    import os
    import runpy
    from .config import ROOT
    os.environ.setdefault("PORT", str(a.port))
    runpy.run_path(str(ROOT / "dashboard" / "app.py"), run_name="__main__")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m batterylife", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the full pipeline")
    r.add_argument("--fast", action="store_true", help="reuse saved SOH/RUL results")
    r.add_argument("--refresh", action="store_true", help="re-parse raw data files")
    r.set_defaults(f=cmd_run)
    v = sub.add_parser("verify", help="verify passports")
    v.add_argument("ids", nargs="*")
    v.set_defaults(f=cmd_verify)
    t = sub.add_parser("tamper-demo", help="show that tampering is detected")
    t.add_argument("id", nargs="?")
    t.set_defaults(f=cmd_tamper)
    s = sub.add_parser("assess", help="grade a battery from its measurements")
    s.add_argument("--soh", type=float, required=True)
    s.add_argument("--soh-lo", type=float)
    s.add_argument("--resistance", type=float, default=None, help="resistance growth, x fresh")
    s.add_argument("--cycles", type=float, default=None, help="predicted cycles left to 60%%")
    s.add_argument("--cycles-lo", type=float, default=None)
    s.set_defaults(f=cmd_assess)
    p = sub.add_parser("passport", help="print passport sections")
    p.add_argument("id")
    p.add_argument("--public", action="store_true")
    p.set_defaults(f=cmd_passport)
    d = sub.add_parser("db", help="rebuild the API database from the result files")
    d.add_argument("--reset", action="store_true", help="delete the database first (drops uploads and the audit log)")
    d.set_defaults(f=cmd_db)
    sub.add_parser("explain", help="permutation importance of the SOH models").set_defaults(f=cmd_explain)
    sv = sub.add_parser("serve", help="start the website and REST API")
    sv.add_argument("--port", type=int, default=8050)
    sv.set_defaults(f=cmd_serve)
    a = ap.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()

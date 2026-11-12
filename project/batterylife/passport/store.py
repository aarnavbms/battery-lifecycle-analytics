"""File-based passport store: one JSON per passport plus the actor directory.

results/passports/<passport_id>.json        full passport (all events)
results/passports/public/<passport_id>.json public view (QR-code level)
results/passports/actors.json               public keys of every actor
results/keys/<actor_id>.pem                 private keys (never committed)
"""
from __future__ import annotations

import json
from pathlib import Path

from ..config import KEYS_DIR, PASSPORT_DIR
from . import crypto
from .ledger import Actor, ActorRegistry, Passport
from .schema import PUBLIC

ACTORS_FILE = PASSPORT_DIR / "actors.json"

DEFAULT_ACTORS = [
    ("MFR-01", "DemoCell Manufacturing (test-cell supplier)", "manufacturer"),
    ("OEM-01", "EV maker (first-life operator)", "oem"),
    ("BMS-01", "On-board battery management system", "bms"),
    ("AI-ASSESSOR", "AI lifecycle assessor (this project)", "assessor"),
    ("REP-01", "Second-life energy-storage integrator", "repurposer"),
    ("REC-01", "Certified battery recycler", "recycler"),
]


def create_actors(keys_dir: Path = KEYS_DIR) -> ActorRegistry:
    reg = ActorRegistry()
    for aid, name, role in DEFAULT_ACTORS:
        key_path = keys_dir / f"{aid}.pem"
        if key_path.exists():
            key = crypto.load_private(key_path)
            reg.add(Actor(aid, name, role, crypto.public_key_b64(key), key))
        else:
            a = reg.create(aid, name, role)
            crypto.save_private(a._private, key_path)
    return reg


def signing_registry(keys_dir: Path = KEYS_DIR, path: Path = ACTORS_FILE) -> ActorRegistry:
    """Actor directory with private keys attached where this machine holds them.

    Unlike create_actors, this never replaces a published public key: an actor
    whose private key is not on this machine stays verify-only.
    """
    reg = load_registry(path) if path.exists() else ActorRegistry()
    for a in reg.actors.values():
        key_path = keys_dir / f"{a.actor_id}.pem"
        if key_path.exists():
            key = crypto.load_private(key_path)
            if crypto.public_key_b64(key) == a.public_key:
                a._private = key
    return reg


def signer(reg: ActorRegistry, role: str, keys_dir: Path = KEYS_DIR, path: Path = ACTORS_FILE):
    """An actor of this role that can sign here. If none exists (for example on
    a fresh clone, where private keys are not shipped), a new local actor is
    enrolled and its public key is added to the directory."""
    for a in reg.actors.values():
        if a.role == role and a._private is not None:
            return a
    n = 1
    while f"{role.upper()}-LOCAL-{n}" in reg.actors:
        n += 1
    a = reg.create(f"{role.upper()}-LOCAL-{n}", f"Local {role} node (enrolled on this machine)", role)
    crypto.save_private(a._private, keys_dir / f"{a.actor_id}.pem")
    save_registry(reg, path)
    return a


def save_registry(reg: ActorRegistry, path: Path = ACTORS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(reg.to_dict(), indent=2))


def load_registry(path: Path = ACTORS_FILE) -> ActorRegistry:
    return ActorRegistry.from_dict(json.loads(path.read_text()))


def save_passport(p: Passport, folder: Path = PASSPORT_DIR) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{p.passport_id}.json").write_text(json.dumps(p.to_dict("full"), indent=2))
    (folder / "public").mkdir(exist_ok=True)
    (folder / "public" / f"{p.passport_id}.json").write_text(json.dumps(p.to_dict(PUBLIC), indent=2))


def load_passport(passport_id: str, folder: Path = PASSPORT_DIR) -> Passport:
    return Passport.from_dict(json.loads((folder / f"{passport_id}.json").read_text()))


def list_passports(folder: Path = PASSPORT_DIR) -> list[str]:
    return sorted(p.stem for p in folder.glob("DBP-*.json"))

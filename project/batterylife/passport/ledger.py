"""Signed, hash-chained event ledger behind every Digital Battery Passport.

Event layout
    index, timestamp, type, actor_id, role, data, prev_hash   <- signed body
    hash       = SHA-256 of the canonical JSON of the body
    signature  = Ed25519 signature of `hash` by the actor's private key

Verification checks, for every event:
    1. index is sequential and prev_hash equals the previous event's hash (chain)
    2. hash matches the body (content integrity)
    3. the actor is known and the signature is valid (authenticity)
    4. the actor's role may issue this event type (authorisation)
    5. required data fields are present (completeness)
    6. timestamps never go backwards (chronology)
Any edit, deletion, reordering or forgery is reported with the first bad index.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import crypto
from .schema import EVENT_TYPES, REQUIRED_FIELDS, SCHEMA_VERSION, SECTIONS, PUBLIC

GENESIS = "0" * 64


@dataclass
class Actor:
    actor_id: str
    name: str
    role: str
    public_key: str
    _private: object = field(default=None, repr=False)

    def public(self) -> dict:
        return {"actor_id": self.actor_id, "name": self.name, "role": self.role,
                "public_key": self.public_key}


class ActorRegistry:
    """Directory of actors and their public keys (the trust anchor)."""

    def __init__(self):
        self.actors: dict[str, Actor] = {}

    def create(self, actor_id: str, name: str, role: str) -> Actor:
        key = crypto.generate_key()
        a = Actor(actor_id, name, role, crypto.public_key_b64(key), key)
        self.actors[actor_id] = a
        return a

    def add(self, actor: Actor) -> None:
        self.actors[actor.actor_id] = actor

    def get(self, actor_id: str) -> Actor | None:
        return self.actors.get(actor_id)

    def to_dict(self) -> dict:
        return {aid: a.public() for aid, a in self.actors.items()}

    @classmethod
    def from_dict(cls, d: dict) -> "ActorRegistry":
        r = cls()
        for aid, a in d.items():
            r.add(Actor(aid, a["name"], a["role"], a["public_key"]))
        return r


def _body(ev: dict) -> dict:
    return {k: ev[k] for k in ("index", "timestamp", "type", "actor_id", "role", "data", "prev_hash")}


class Passport:
    def __init__(self, passport_id: str, battery_id: str):
        self.passport_id = passport_id
        self.battery_id = battery_id
        self.events: list[dict] = []

    # -------------------------------------------------------------- writing
    def append(self, actor: Actor, event_type: str, data: dict, timestamp: str) -> dict:
        if actor._private is None:
            raise PermissionError(f"actor {actor.actor_id} has no private key in this process")
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unknown event type {event_type}")
        allowed, _, _ = EVENT_TYPES[event_type]
        if actor.role not in allowed:
            raise PermissionError(f"role '{actor.role}' may not issue {event_type}")
        missing = [f for f in REQUIRED_FIELDS.get(event_type, []) if f not in data]
        if missing:
            raise ValueError(f"{event_type} missing fields {missing}")
        # deep-copy through JSON: the signed record must not alias caller objects,
        # and every value must be JSON-serialisable to hash reproducibly
        data = json.loads(json.dumps(data))
        ev = {"index": len(self.events), "timestamp": timestamp, "type": event_type,
              "actor_id": actor.actor_id, "role": actor.role, "data": data,
              "prev_hash": self.events[-1]["hash"] if self.events else GENESIS}
        ev["hash"] = crypto.sha256_hex(_body(ev))
        ev["signature"] = crypto.sign(actor._private, ev["hash"])
        self.events.append(ev)
        return ev

    # -------------------------------------------------------------- reading
    @property
    def head_hash(self) -> str:
        return self.events[-1]["hash"] if self.events else GENESIS

    def status(self) -> str:
        s = "unknown"
        for ev in self.events:
            new = EVENT_TYPES.get(ev["type"], (None, None, None))[2]
            if new:
                s = new
        return s

    def latest(self, event_type: str) -> dict | None:
        for ev in reversed(self.events):
            if ev["type"] == event_type:
                return ev
        return None

    def sections(self) -> dict:
        """Current passport content, derived only from signed events."""
        man = self.latest("MANUFACTURED")
        cf = self.latest("CARBON_FOOTPRINT_DECLARED")
        soh = self.latest("SOH_ASSESSMENT")
        rul = self.latest("RUL_PREDICTION")
        grade = self.latest("SECOND_LIFE_GRADING")
        m = man["data"] if man else {}
        return {
            "general_information": {k: m.get(k) for k in (
                "model", "manufacturer", "manufacture_date", "chemistry", "form_factor",
                "rated_capacity_ah", "nominal_voltage_v", "manufacturing_site")},
            "carbon_footprint": cf["data"] if cf else None,
            "performance_and_durability": {k: m.get(k) for k in (
                "rated_capacity_ah", "initial_capacity_ah", "initial_resistance_ohm",
                "expected_cycle_life", "cut_off_voltage_v")},
            "battery_status": {"status": self.status(), "events": len(self.events),
                               "last_event": self.events[-1]["type"] if self.events else None},
            "state_of_health": {"latest_assessment": soh["data"] if soh else None,
                                "latest_rul": rul["data"] if rul else None},
            "lifecycle_decision": grade["data"] if grade else None,
        }

    def to_dict(self, access: str = "full") -> dict:
        secs = self.sections()
        events = self.events
        if access == PUBLIC:
            secs = {k: v for k, v in secs.items() if SECTIONS[k] == PUBLIC}
            events = [e for e in self.events if EVENT_TYPES[e["type"]][1] == PUBLIC]
        return {"schema_version": SCHEMA_VERSION, "passport_id": self.passport_id,
                "battery_id": self.battery_id, "access_level": access,
                "head_hash": self.head_hash, "sections": secs, "events": events}

    @classmethod
    def from_dict(cls, d: dict) -> "Passport":
        p = cls(d["passport_id"], d["battery_id"])
        p.events = [dict(e) for e in d["events"]]
        return p


def verify(passport: Passport, registry: ActorRegistry) -> dict:
    issues, prev, prev_ts = [], GENESIS, ""
    checks = {"chain": True, "content": True, "signatures": True, "roles": True, "fields": True,
              "chronology": True}
    for i, ev in enumerate(passport.events):
        def flag(kind, msg):
            checks[kind] = False
            issues.append({"index": i, "type": ev.get("type"), "check": kind, "problem": msg})
        if ev.get("index") != i:
            flag("chain", f"index {ev.get('index')} at position {i} (event deleted or reordered)")
        if ev.get("prev_hash") != prev:
            flag("chain", "prev_hash does not match previous event")
        if crypto.sha256_hex(_body(ev)) != ev.get("hash"):
            flag("content", "hash does not match event content (data was modified)")
        actor = registry.get(ev.get("actor_id"))
        if actor is None:
            flag("signatures", f"unknown actor {ev.get('actor_id')}")
        else:
            if not crypto.verify_signature(actor.public_key, ev.get("hash", ""), ev.get("signature", "")):
                flag("signatures", f"invalid signature for actor {actor.actor_id}")
            if actor.role != ev.get("role"):
                flag("roles", f"event claims role '{ev.get('role')}' but actor is '{actor.role}'")
        etype = EVENT_TYPES.get(ev.get("type"))
        if etype is None:
            flag("roles", "unknown event type")
        elif ev.get("role") not in etype[0]:
            flag("roles", f"role '{ev.get('role')}' may not issue {ev.get('type')}")
        missing = [f for f in REQUIRED_FIELDS.get(ev.get("type"), []) if f not in ev.get("data", {})]
        if missing:
            flag("fields", f"missing fields {missing}")
        ts = str(ev.get("timestamp", ""))
        if ts < prev_ts:
            flag("chronology", f"timestamp {ts} is earlier than previous event ({prev_ts})")
        prev, prev_ts = ev.get("hash"), max(ts, prev_ts)
    return {"passport_id": passport.passport_id, "valid": not issues, "events": len(passport.events),
            "checks": checks, "first_bad_index": issues[0]["index"] if issues else None,
            "issues": issues, "head_hash": passport.head_hash}

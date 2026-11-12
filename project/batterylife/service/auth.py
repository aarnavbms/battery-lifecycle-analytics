"""Accounts, roles and access tokens.

Roles mirror the passport's actor roles, plus two that only read:
    public        no account: sees the public passport tier (what a QR code shows)
    manufacturer, oem, assessor, repurposer, recycler
                  "persons with a legitimate interest": see the full passport and
                  may record the lifecycle events their role is allowed to sign
    regulator     authority: sees everything, including the audit log
    admin         everything

The same rule is enforced twice: here, by the API, and again by the passport
ledger, which refuses an event whose signer has the wrong role.

Tokens are JSON Web Tokens (HS256), valid for 8 hours.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path

import jwt
from werkzeug.security import check_password_hash, generate_password_hash

from ..passport.schema import EVENT_TYPES
from . import CTX

TOKEN_HOURS = 8
ROLES = {
    "public": "Anyone, no account (public passport tier)",
    "manufacturer": "Cell or battery manufacturer",
    "oem": "Vehicle maker (first-life operator)",
    "assessor": "AI lifecycle assessor (runs assessments, issues passports)",
    "repurposer": "Second-life integrator",
    "recycler": "Certified recycler",
    "regulator": "Market surveillance authority (read-only, sees the audit log)",
    "admin": "System administrator",
}
PERMISSIONS = {
    "passport:read_full": {"manufacturer", "oem", "assessor", "repurposer", "recycler", "regulator", "admin"},
    "upload:create": {"assessor", "admin"},
    "upload:read": {"assessor", "regulator", "admin"},
    "audit:read": {"regulator", "admin"},
}


class AuthError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def demo_enabled() -> bool:
    return os.environ.get("BLA_DEMO", "1") != "0"


def can(role: str, permission: str) -> bool:
    return role in PERMISSIONS.get(permission, set())


def events_allowed(role: str) -> list[str]:
    """Passport event types this role may sign."""
    if role == "admin":
        return []
    return sorted(t for t, (roles, _, _) in EVENT_TYPES.items() if role in roles)


def _secret() -> str:
    env = os.environ.get("BLA_SECRET")
    if env:
        return env
    f = Path(CTX.keys) / "api_secret.txt"
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(secrets.token_hex(32))
    return f.read_text().strip()


def seed_users(conn) -> None:
    """Create the accounts in the users file if they do not exist yet."""
    f = Path(os.environ.get("BLA_USERS_FILE") or Path(__file__).with_name("demo_users.json"))
    have = {r["username"] for r in conn.execute("SELECT username FROM users")}
    for u in json.loads(f.read_text())["users"]:
        if u["username"] not in have:
            conn.execute("INSERT INTO users VALUES (?,?,?,?)",
                         (u["username"], u["name"], u["role"],
                          generate_password_hash(u["password"], method="pbkdf2:sha256:200000")))


def issue_token(user: dict) -> dict:
    exp = int(time.time()) + TOKEN_HOURS * 3600
    token = jwt.encode({"sub": user["username"], "name": user["name"], "role": user["role"], "exp": exp},
                       _secret(), algorithm="HS256")
    return {"token": token, "token_type": "Bearer", "expires_in": TOKEN_HOURS * 3600, "user": describe(user)}


def describe(user: dict) -> dict:
    role = user["role"]
    return {"username": user["username"], "name": user["name"], "role": role,
            "permissions": sorted(p for p in PERMISSIONS if can(role, p)),
            "may_sign": events_allowed(role)}


def login(conn, username: str, password: str) -> dict:
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username or "",)).fetchone()
    if row is None or not check_password_hash(row["password_hash"], password or ""):
        raise AuthError(401, "Wrong username or password.")
    return issue_token(dict(row))


def demo_login(conn, role: str) -> dict:
    if not demo_enabled():
        raise AuthError(403, "Demo sign-in is switched off on this server (BLA_DEMO=0).")
    row = conn.execute("SELECT * FROM users WHERE role = ? ORDER BY username LIMIT 1", (role or "",)).fetchone()
    if row is None:
        raise AuthError(404, f"No demo account with role '{role}'.")
    return issue_token(dict(row))


def user_from_header(header: str | None) -> dict | None:
    """Decode 'Authorization: Bearer <token>'. None means public access."""
    if not header:
        return None
    parts = header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise AuthError(401, "Authorization header must be 'Bearer <token>'.")
    try:
        c = jwt.decode(parts[1], _secret(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise AuthError(401, "Token expired. Sign in again.")
    except jwt.InvalidTokenError:
        raise AuthError(401, "Invalid token.")
    return {"username": c["sub"], "name": c.get("name", c["sub"]), "role": c["role"]}


def require(user: dict | None, permission: str) -> dict:
    if user is None:
        raise AuthError(401, "Sign in first: this action needs an account.")
    if not can(user["role"], permission):
        allowed = ", ".join(sorted(PERMISSIONS[permission]))
        raise AuthError(403, f"Role '{user['role']}' may not do this. Allowed roles: {allowed}.")
    return user

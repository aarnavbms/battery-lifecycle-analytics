"""Ed25519 keys and signatures for passport actors, plus canonical hashing."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_hex(obj) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def generate_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def public_key_b64(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return b64(raw)


def load_public(b64key: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(b64key))


def sign(key: Ed25519PrivateKey, message: str) -> str:
    return b64(key.sign(message.encode()))


def verify_signature(pub_b64: str, message: str, sig_b64: str) -> bool:
    try:
        load_public(pub_b64).verify(base64.b64decode(sig_b64), message.encode())
        return True
    except (InvalidSignature, ValueError):
        return False


def save_private(key: Ed25519PrivateKey, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))


def load_private(path: Path) -> Ed25519PrivateKey:
    return serialization.load_pem_private_key(path.read_bytes(), password=None)

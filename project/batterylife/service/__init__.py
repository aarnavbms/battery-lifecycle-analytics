"""Service layer: database, accounts and roles, data upload, network analysis,
explainability and passport documents. The REST API (dashboard/api_v1.py) is a
thin HTTP wrapper around this package.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import KEYS_DIR, PASSPORT_DIR, RESULTS_DIR


@dataclass
class Context:
    """Where the service keeps its state. Tests point these at a temp folder."""
    db: Path = RESULTS_DIR / "battery.db"
    keys: Path = KEYS_DIR
    actors_file: Path = PASSPORT_DIR / "actors.json"
    passports: Path = PASSPORT_DIR


CTX = Context()

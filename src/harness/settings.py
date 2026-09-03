"""Credentials and paths, loaded from .env.

Secrets live in .env (gitignored) and never in code, arguments, or run records.
Run records are committed as results, so anything that reaches them is public.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RUNS = ROOT / "runs"


@lru_cache(maxsize=1)
def _load() -> None:
    load_dotenv(ROOT / ".env")


def require(name: str) -> str:
    _load()
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"{name} is not set. Copy .env.example to .env and fill it in."
        )
    return value


def optional(name: str, default: str = "") -> str:
    _load()
    return os.environ.get(name, default).strip() or default


def github_token() -> str:
    return require("GITHUB_TOKEN")


def openrouter_key() -> str:
    return require("OPENROUTER_API_KEY")

"""Where the pipeline reads and writes.

The checkout stays small. Paper text lives under MENTIONS_DATA, which
defaults to <project>/data and can point at a disk that holds the cache:

    MENTIONS_DATA=/var/lib/mentions uv run mentions-pipeline

That directory keeps records.jsonl, hits.jsonl, the harvest cursor, the
bulk PDFs, the extracted text, the year-split corpus, and the local
SQLite file. Charts and the daily summary stay in MENTIONS_OUTPUT,
default <project>/output. The static site stays in the checkout.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    raw = os.environ.get("MENTIONS_DATA", "").strip()
    path = Path(raw).expanduser() if raw else ROOT / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def output_dir() -> Path:
    raw = os.environ.get("MENTIONS_OUTPUT", "").strip()
    path = Path(raw).expanduser() if raw else ROOT / "output"
    path.mkdir(parents=True, exist_ok=True)
    return path

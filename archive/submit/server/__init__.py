"""OfficeQA Arena server package."""
from __future__ import annotations

import os
from pathlib import Path

from server.tools import OfficeQATools

ROOT = Path(__file__).resolve().parents[1]


def _candidate_db_paths() -> list[str]:
    candidates = [
        os.environ.get("OFFICEQA_SQLITE_DB", ""),
        os.environ.get("OFFICEQA_DB", ""),
        "/app/corpus/officeqa_corpus.sqlite3",
        "/app/corpus/officeqa_subset.sqlite3",
        str(ROOT / "data" / "officeqa_corpus.sqlite3"),
        str(ROOT / "data" / "officeqa_subset.sqlite3"),
    ]
    return [c for c in candidates if c]


def load_tools(db_path: str | None = None) -> OfficeQATools:
    """Instantiate OfficeQATools using the explicit db_path or auto-detection."""
    if db_path:
        return OfficeQATools(db_path)

    for candidate in _candidate_db_paths():
        if Path(candidate).exists():
            return OfficeQATools(candidate)

    raise RuntimeError(
        "No database path found. Pass db_path or set OFFICEQA_SQLITE_DB."
    )

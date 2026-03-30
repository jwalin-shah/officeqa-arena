"""OfficeQA Arena server package."""
from __future__ import annotations

from server.tools import OfficeQATools


def load_tools(db_path: str | None = None) -> OfficeQATools:
    """Instantiate OfficeQATools, reading *db_path* or OFFICEQA_SQLITE_DB env var."""
    import os

    path = db_path or os.environ.get("OFFICEQA_SQLITE_DB", "")
    if not path:
        raise RuntimeError(
            "No database path. Pass db_path or set OFFICEQA_SQLITE_DB env var."
        )
    return OfficeQATools(path)

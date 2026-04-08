#!/usr/bin/env python3
"""Compatibility wrapper for legacy entrypoints.

Canonical submission server is server.mcp_stdio.
Keep this file only so older commands do not drift onto a different tool surface.
"""
from __future__ import annotations

from server.mcp_stdio import main


if __name__ == "__main__":
    main()

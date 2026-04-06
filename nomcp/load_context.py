#!/usr/bin/env python3
"""Load a large section of a Treasury Bulletin file for full-context reading.

Usage:
    python3 /installed-agent/load_context.py <file> <center_line> [radius]

Examples:
    python3 /installed-agent/load_context.py treasury_bulletin_1955_06.txt 170
    python3 /installed-agent/load_context.py treasury_bulletin_1955_06.txt 170 300

Shows `radius` lines around center_line (default 200). Use this when you need
to see the full document context: multiple tables, footnotes, unit headers.
"""

import os
import sys
from pathlib import Path

CORPUS_DIR = os.environ.get("CORPUS_DIR", "/app/corpus")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    filename = sys.argv[1]
    center = int(sys.argv[2])
    radius = int(sys.argv[3]) if len(sys.argv) > 3 else 200

    fpath = Path(filename)
    if not fpath.exists():
        fpath = Path(CORPUS_DIR) / filename
    if not fpath.exists():
        print(f"File not found: {filename}")
        sys.exit(1)

    lines = fpath.read_text(errors="replace").splitlines()
    start = max(0, center - 1 - radius)
    end = min(len(lines), center - 1 + radius)

    # Show file info
    print(f"--- {fpath.name} lines {start+1}-{end} (of {len(lines)} total) ---")

    # Scan for units/title near the top of our range
    for i in range(start, end):
        print(f"{i+1:5d} | {lines[i]}")

    print(f"\n--- End of {fpath.name} [{end - start} lines shown] ---")


if __name__ == "__main__":
    main()

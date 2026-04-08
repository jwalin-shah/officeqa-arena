#!/usr/bin/env python3
"""Table parser: converts HTML tables in treasury .txt files to clean pipe-delimited output.
Usage: python3 t.py FILENAME [SEARCH_TERM]
  - With no search term: prints all tables with headers
  - With search term: prints only rows matching the term
"""
import sys, re, os

def parse_html_tables(html):
    """Extract tables from HTML, handling rowspan/colspan."""
    tables = []
    for table_match in re.finditer(r'<table>(.*?)</table>', html, re.DOTALL):
        table_html = table_match.group(1)
        rows_raw = re.findall(r'<tr>(.*?)</tr>', table_html, re.DOTALL)

        # Build grid handling rowspan/colspan
        grid = []
        pending = {}  # (row, col) -> value for rowspan carries

        for ri, row_html in enumerate(rows_raw):
            cells = re.findall(r'<(th|td)(.*?)>(.*?)</(?:th|td)>', row_html, re.DOTALL)
            row = []
            ci = 0

            # Fill pending rowspan cells
            while (ri, ci) in pending:
                row.append(pending.pop((ri, ci)))
                ci += 1

            for tag, attrs, content in cells:
                while (ri, ci) in pending:
                    row.append(pending.pop((ri, ci)))
                    ci += 1

                # Clean content
                val = re.sub(r'<[^>]+>', '', content).strip()

                # Parse colspan/rowspan
                colspan = int(m.group(1)) if (m := re.search(r'colspan="(\d+)"', attrs)) else 1
                rowspan = int(m.group(1)) if (m := re.search(r'rowspan="(\d+)"', attrs)) else 1

                for c in range(colspan):
                    while (ri, ci) in pending:
                        row.append(pending.pop((ri, ci)))
                        ci += 1
                    row.append(val if c == 0 else "")
                    # Set pending for rowspan
                    for r in range(1, rowspan):
                        pending[(ri + r, ci)] = val if c == 0 else ""
                    ci += 1

            # Drain any remaining pending
            while (ri, ci) in pending:
                row.append(pending.pop((ri, ci)))
                ci += 1

            grid.append(row)

        if grid:
            tables.append(grid)

    return tables

def clean_num(val):
    """Clean a cell value: handle footnotes, parentheses=negative, etc."""
    v = val.strip()
    # Remove footnote markers like 1/, 2/, etc.
    v = re.sub(r'\s*\d+/', '', v)
    # Handle parentheses = negative
    if v.startswith('(') and v.endswith(')'):
        v = '-' + v[1:-1]
    # Handle 'p' for preliminary
    v = v.rstrip(' p')
    return v

def format_table(grid, table_idx):
    """Format a grid as labeled pipe-delimited text."""
    if not grid:
        return ""

    lines = []
    # Find header rows (typically first 1-2 rows with th-like content)
    # Use first row as headers
    headers = grid[0] if grid else []

    # If second row looks like sub-headers (short strings), merge with first
    merged_headers = list(headers)
    data_start = 1
    if len(grid) > 1:
        row2 = grid[1]
        # Check if row2 is sub-headers (most cells are short or empty)
        non_empty = [c for c in row2 if c.strip()]
        if non_empty and all(len(c) < 30 for c in non_empty):
            # Might be sub-headers - check if they look non-numeric
            numeric = sum(1 for c in non_empty if re.match(r'^[\d,.\-()$ ]+$', c.strip()))
            if numeric < len(non_empty) / 2:
                # Merge headers
                merged_headers = []
                for i in range(max(len(headers), len(row2))):
                    h1 = headers[i].strip() if i < len(headers) else ""
                    h2 = row2[i].strip() if i < len(row2) else ""
                    if h1 and h2:
                        merged_headers.append(f"{h1} > {h2}")
                    else:
                        merged_headers.append(h1 or h2)
                data_start = 2

    lines.append(f"=== TABLE {table_idx + 1} ===")
    lines.append(" | ".join(h.strip() for h in merged_headers))
    lines.append("-" * 40)

    for row in grid[data_start:]:
        # Pad row to header length
        padded = row + [""] * (len(merged_headers) - len(row))
        cleaned = [clean_num(c) for c in padded[:len(merged_headers)]]

        # Add column labels for non-empty data rows
        if any(c.strip() for c in cleaned):
            labeled_cells = []
            for i, c in enumerate(cleaned):
                labeled_cells.append(c.strip())
            lines.append(" | ".join(labeled_cells))

    return "\n".join(lines)

def parse_pipe_tables(text):
    """Parse markdown pipe-delimited tables."""
    tables = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        # Find separator row (| --- | --- | ...)
        if re.match(r'^\|[\s-]+\|', lines[i]):
            sep_idx = i
            # Header is line(s) before separator
            header_start = sep_idx - 1
            while header_start > 0 and '|' in lines[header_start - 1] and lines[header_start - 1].strip().startswith('|'):
                header_start -= 1

            # Parse header
            header_cells = []
            for hi in range(header_start, sep_idx):
                cells = [c.strip() for c in lines[hi].split('|')]
                cells = [c for c in cells if c]  # remove empty from leading/trailing |
                if not header_cells:
                    header_cells = cells
                else:
                    # Merge sub-headers
                    for ci in range(min(len(header_cells), len(cells))):
                        if cells[ci] and cells[ci] != header_cells[ci]:
                            header_cells[ci] = f"{header_cells[ci]} > {cells[ci]}"

            # Data rows after separator
            grid = [header_cells]
            j = sep_idx + 1
            while j < len(lines) and '|' in lines[j]:
                cells = [c.strip() for c in lines[j].split('|')]
                cells = [c for c in cells if c or len([x for x in cells if x]) > 1]
                # Remove empty from leading/trailing pipe
                if cells and cells[0] == '':
                    cells = cells[1:]
                if cells and cells[-1] == '':
                    cells = cells[:-1]
                if cells:
                    grid.append(cells)
                j += 1

            if len(grid) > 1:
                tables.append(grid)
            i = j
        else:
            i += 1
    return tables

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 t.py FILENAME [SEARCH_TERM]")
        sys.exit(1)

    filepath = sys.argv[1]
    search = sys.argv[2].lower() if len(sys.argv) > 2 else None

    if not os.path.exists(filepath):
        # Try /app/resources/ prefix
        alt = os.path.join("/app/resources", filepath)
        if os.path.exists(alt):
            filepath = alt
        else:
            print(f"File not found: {filepath}")
            sys.exit(1)

    content = open(filepath).read()

    # Try HTML tables first, then pipe tables
    tables = parse_html_tables(content)
    source = "HTML"
    if not tables:
        tables = parse_pipe_tables(content)
        source = "pipe"

    if not tables:
        print("No tables found. Raw content (first 3000 chars):")
        print(content[:3000])
        sys.exit(0)

    for i, grid in enumerate(tables):
        formatted = format_table(grid, i)
        if search:
            lines = formatted.split("\n")
            header_lines = lines[:3]
            matching = [l for l in lines[3:] if search in l.lower()]
            if matching:
                print("\n".join(header_lines))
                for m in matching:
                    print(m)
                print()
        else:
            print(formatted)
            print()

if __name__ == "__main__":
    main()

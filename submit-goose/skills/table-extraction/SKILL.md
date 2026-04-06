---
name: table-extraction
description: How to accurately extract values from Treasury Bulletin tables. Use when reading tables with many columns, similar row labels, or when you need to verify you have the right cell.
---

## Accurate Table Extraction

Wide tables (10+ columns) cause misreads. To verify you have the right value:

1. Identify the EXACT row label asked. "National defense" ≠ "National defense and veterans" ≠ "Total national security"
2. Count columns from the header to confirm which column has your target year/period
3. For wide tables, extract just the row you need:
   grep "row label" file.txt
   Then count pipe-separated values to match the column header.
4. Cross-check: if the page file has the value AND the full .txt has it, they should match. If not, trust the page file.

## Common Table Traps
- "Total" rows already include sub-items. Never sum a parent with its children.
- Some tables wrap across pages. Check if there is a "Continued" table on the next page.
- Footnote markers (1/, 2/, r/, p/) appear inside numbers — strip them before computing.
- Values like "(*)" or "-" mean zero or not applicable, not missing data.
- Column headers with ">" indicate multi-level headers flattened. Read carefully.

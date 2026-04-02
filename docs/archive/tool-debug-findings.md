# Baked-in MCP Tool Debug Findings

**Date**: 2026-03-30
**Container**: `bb8ea608dbea` on sentient droplet
**Server code**: `/app/mcp_server_sse.py` -> `/app/src/mcp_tool_impl.py`

## Executive Summary

The baked-in MCP tools on the droplet have **three independent failure modes** that compound to make `extract_values` and `search_documents` return empty results, even though the underlying SQLite DB has 18.4M cells of data.

---

## Root Cause 1: `extract_values` ignores `table_pk` and misapplies metric filter

**Location**: `/app/src/mcp_tool_impl.py`, lines ~1200-1208

**Bug**: `extract_values` builds its `targets` list using only `file_id` and `table_title`, discarding the `table_pk` returned by `search_tables`:

```python
# Line 1200-1204 (baked-in version)
targets = [
    (str(c.get("file_id") or ""), str(c.get("table_title") or ""), float(c.get("score") or 0.0))
    for c in candidates
    if str(c.get("file_id") or "").strip()
]
```

It then calls `query_table_rows(file_id=fid, table_title=title, row_label=metric, year=year)`.

**Why this fails**: In Treasury Bulletin tables, the row_labels are often **fiscal years** ("1940") while the expenditure categories appear as **column_labels** ("National defense"). Filtering `row_pattern="national defense"` against year-labeled rows returns 0 results.

**Our local fix** (already in `/Users/jwalinshah/projects/officeqa-arena/server/tools.py`):
- Uses `table_pk` when available for faster direct lookups
- Tries `column_label=metric` first, then `row_label=metric`, then no filter (cascade)

## Root Cause 2: `search_documents` and `search_corpus` return 0 results

**Location**: `/app/src/corpus_tools.py` -> `/app/src/corpus.py` `discover_source_files()`

**Bug**: `discover_source_files()` globs for `treasury_bulletin_*.txt` in the corpus root (`/app/corpus/`), but the .txt files are actually in `/app/corpus/transformed/`.

```
/app/corpus/
  officeqa_corpus.sqlite3     (11 GB - has data)
  officeqa_corpus_subset.sqlite3
  transformed/                (contains 697 .txt files)
    treasury_bulletin_1940_04.txt
    treasury_bulletin_1968_06.txt
    ...
```

Result: `discover_source_files()` returns `[]`, so `search_corpus` returns 0 candidates, so `search_documents` returns 0 documents.

This also means the **document_fallback path** in `extract_values` (lines 1186-1197) also fails.

## Root Cause 3: `document_elements` table is empty

**DB Schema Status** (from `/app/corpus/officeqa_corpus.sqlite3`):

| Table | Row Count | Status |
|-------|-----------|--------|
| `documents` | 697 | OK |
| `document_texts` | 697 | OK |
| `document_elements` | **0** | EMPTY |
| `table_groups` | **0** | EMPTY |
| `normalized_cells` | **0** | EMPTY |
| `table_columns` | **0** | EMPTY |
| `table_first_tables` | 92,425 | OK |
| `table_first_table_cells` | 18,419,962 | OK |
| `facts` | 5,818,952 | OK |
| `facts_fts` | indexed | OK |

The `officeqa_core` MCP tools (`get_blocks_for_file`, `get_block_by_id`, `retrieve_and_check`) query the `document_elements` table which has 0 rows, making them completely useless.

The working data path is: `table_first_tables` + `table_first_table_cells` (accessed via `src.ingestion_db`).

---

## Working vs Broken Tool Paths

### Working:
- `search_tables(query, year_range)` -- uses `ingestion_db.search_tables()` which queries `table_first_tables` via FTS. Returns candidates with `table_pk`.
- `query_table_rows(table_pk=X, year=Y)` -- uses `ingestion_db.get_table_cells(table_pk=X)` which queries `table_first_table_cells`. Returns actual data rows.
- `query_facts(query, year)` -- uses FTS5 on `facts` table. Returns data but quality is poor (metric labels contain year strings).
- `get_table_profile(table_pk)` -- works via `ingestion_db`.
- `compute_expression()` -- pure arithmetic, works fine.

### Broken:
- `extract_values()` -- search_tables works, but row fetch fails due to Root Cause 1.
- `search_documents()` / `search_corpus()` -- returns 0 results due to Root Cause 2.
- `get_file_structure(file_id)` -- uses `CorpusTool.inspect_file_structure()` which depends on .txt files in wrong directory.
- `find_candidate_evidence()` -- depends on search_documents which is broken.
- `lookup_numeric_answer()` -- likely broken for same reasons.
- All `officeqa_core` tools -- useless due to empty `document_elements`.

---

## Recommended Fixes

### Fix 1: Patch `extract_values` in `mcp_tool_impl.py`

Replace the `_fetch` function and targets construction:

```python
# Step 2: Build targets WITH table_pk
targets = [
    (c.get("table_pk"), str(c.get("file_id") or ""), str(c.get("table_title") or ""), float(c.get("score") or 0.0))
    for c in candidates
    if str(c.get("file_id") or "").strip()
]

def _fetch(pk, fid, title):
    kwargs = {"limit": 20}
    if pk:
        kwargs["table_pk"] = pk
    else:
        kwargs["file_id"] = fid
        kwargs["table_title"] = title
    if year is not None:
        kwargs["year"] = int(year)
    if mo is not None:
        kwargs["month"] = mo
    # Try column_label first, then row_label, then no metric filter
    if m:
        kwargs["column_label"] = m
    result = self.query_table_rows(**kwargs)
    if not result.get("rows") and m:
        kwargs.pop("column_label", None)
        kwargs["row_label"] = m
        result = self.query_table_rows(**kwargs)
    if not result.get("rows") and m:
        kwargs.pop("row_label", None)
        result = self.query_table_rows(**kwargs)
    return result
```

### Fix 2: Fix corpus root for discover_source_files

In `OfficeQAMCPTools.__init__` or `CorpusTool.__init__`, detect that `.txt` files live in `transformed/` subdirectory:

```python
# If no .txt files in corpus_root, try corpus_root/transformed
if not list(corpus_root.glob("treasury_bulletin_*.txt")):
    transformed = corpus_root / "transformed"
    if transformed.is_dir() and list(transformed.glob("treasury_bulletin_*.txt")):
        corpus_root = transformed
```

### Fix 3: Workaround strategy for our harness

Since we cannot modify the container code, our local MCP stdio server should:
1. **Prefer `search_tables` + `query_table_rows(table_pk=...)` path** -- this works end-to-end
2. **Never rely on `extract_values`** from the SSE server -- it's broken
3. **Never rely on `search_documents`** -- it's broken
4. **Use `query_facts` as a fast first-pass** for simple lookups
5. **Implement our own `extract_values` locally** using the working primitives

---

## Verification Commands

```bash
# Confirm search_tables works
docker exec bb8ea608dbea python3 -c "..." # returns candidates with table_pk

# Confirm query_table_rows works with table_pk
docker exec bb8ea608dbea python3 -c "..." # returns actual data rows

# Confirm extract_values is broken
docker exec bb8ea608dbea python3 -c "..." # returns {"results": [], "count": 0}
```

## Data Structure Insight

Treasury Bulletin tables have two common layouts:

1. **Years as rows, categories as columns**: row_label="1940", column_label="National defense"
2. **Categories as rows, years as columns**: row_label="National defense", column_label="1940"

The baked-in code assumes layout #2 only (passes metric as row_label). Our fix handles both by trying column_label first, then row_label, then no filter.

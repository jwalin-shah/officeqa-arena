---
name: search architecture decision
description: Decision to simplify search_tables from 500-line complex scorer to lightweight recall-oriented retrieval
type: project
---

Current search_tables in db.py has ~500 lines of Python scoring (family classification, alignment tiers, scope diagnostics) ported from the complex version in officeqa-core/ingestion_db.py. This takes 1-2s per call and sometimes misses the right table entirely.

**Why:** The old officeqa-core had a TWO-TIER approach: simple `search_table_profiles()` (~100-300ms, 5 scoring factors) AND complex `search_tables()` (1-2s, 50+ scoring components). We accidentally ported only the complex one.

**How to apply:** Replace the current scoring with lightweight recall-oriented search. Keep term matching for candidate generation but simplify scoring to ~5 transparent factors (title match, year overlap, monthly data presence, column match, family match). Let the model do selection from metadata.

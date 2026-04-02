# Comparison Question Failure Analysis

- Run: `pool-20260402T094504Z`
- Comparison pass rate: **34/78 (43.6%)** — worst operation type
- Failures analyzed: **44 tasks**

---

## Failure Mode Breakdown

### 1. Wrong Value Selected — 21 failures (47.7%)

The agent retrieved data but picked the wrong row, wrong table variant, or a partial subset.

| UID | Expected | Submitted | Notes |
|-----|----------|-----------|-------|
| UID0019 | 1169.41 million | 1821.27 | Wrong net options positions row |
| UID0025 | 142 | 190 | Wrong public works revision (PWA/housing) row |
| UID0036 | 9.89% | 13.69 | Wrong year range or row for FX share change |
| UID0038 | 2382 | 2293 | Off by ~89, slightly wrong liabilities sub-row |
| UID0082 | 5.3 | 8.3 | Wrong Treasury debt holder row |
| UID0085 | 0.068 | 0.001 | Wrong source for California Internal Revenue share |
| UID0089 | -118255.5 | -112960.75 | Wrong data for quartile calculation |
| UID0101 | [-0.153, 0.847, -1.162] | [-0.150, 0.850, -1.146] | Close but wrong, slightly off values |
| UID0123 | [34.4, 0.391] | [34.4, 0.860] | Second value from wrong row |
| UID0124 | [7.1, 82] | [7.3, 86] | Both values slightly off |
| UID0133 | 78.42 | 89.03 | Wrong base year or wrong liabilities category |
| UID0156 | -1299 | -2298 | Wrong balance component or double-counted |
| UID0159 | 39.31 | 38.50 | Slightly wrong asset category selection |
| UID0165 | 4928 | 1167 | Picked wrong Treasury securities category |
| UID0172 | 372507.20 | 143536.21 | Partial sum — missed foreign country rows |
| UID0183 | 0.3267 | 0.3932 | Wrong numerator or denominator for ratio |
| UID0190 | -11 | -22 | Off by 2×, double-counted receipts |
| UID0191 | 0.00324 | 0.00288 | Slightly wrong denominator in rate |
| UID0213 | -550.3 | -906.9 | Wrong balance account row |
| UID0244 | 504.12 | 561.37 | Wrong month values for trust account receipts |
| UID0246 | 44605.38 | 10446.17 | Grabbed partial securities category not total |

**Root cause:** `resolve_numeric_evidence` returning `ambiguous_candidates` — model picks `recommended_value` (highest bulletin vintage) without verifying it matches the question's specific context (revised figures, correct sub-category, all-foreign totals).

**Fix applied:** Added explicit instructions in both prompts to verify BOTH values are correct before computing, and to prefer the highest-vintage bulletin but cross-check the row label matches the question exactly.

---

### 2. Arithmetic / Formula Error — 12 failures (27.3%)

Agent found approximately correct values but applied the wrong formula or had percent/decimal confusion.

| UID | Expected | Submitted | Error type |
|-----|----------|-----------|------------|
| UID0055 | 0.0 | 0.1 | WWII=1945, Korean=1950 — tiny rounding error, should be exactly 0 |
| UID0060 | 13.009% | 12.497 | CAGR wrong n_years (counted inclusive years instead of gap) |
| UID0076 | 22.80 | 17.12 | Percentage point diff — used wrong pair of values |
| UID0077 | 4.61% | 5.84 | Percent contribution change — wrong base computation |
| UID0094 | -0.119 | -0.0519 | Geometric rate — wrong exponent in formula |
| UID0158 | 0.55 | 1.2 | 2-month moving average — wrong period or stale values |
| UID0193 | 3.9970 | NO_ANSWER | submit_answer called with no `answer` field (empty) |
| UID0196 | -156.11 | -265.7 | Inflation-adjusted MoM change — wrong CPI base year |
| UID0209 | 0.1 | 9.6 | Ratio of % changes — got ~96× off (percent treated as decimal in ratio) |
| UID0239 | 0.045 | 4.828 | Continuous rate — returned percent (4.8%) instead of decimal (0.048) |
| UID0243 | 264.632 | 444.097 | Wrong inflation adjustment or wrong debt year |
| UID0245 | -0.113 | -10.727 | Yield change — percent not divided by 100 (off by ~95×) |

**Root cause (most impactful):** Percent/decimal confusion in UID0209, UID0239, UID0245. Agent computed a value as percent (e.g. 4.5%) but the question expected a decimal (0.045). Also CAGR n_years: model counts inclusive years (e.g. 1990-to-2000 = 11) instead of the gap (= 10).

**Fix applied:**
- Added `pct_change_decimal(old, new)` helper that returns decimal directly (no ×100).
- Added explicit CAGR n_years note: n = end_year − start_year (the gap, not inclusive count).
- Added prompt instruction: "If pct_change gives 4.5 but answer needs 0.045, divide by 100."

---

### 3. Unit / Scale Mismatch — 3 failures (6.8%)

| UID | Expected | Submitted | Notes |
|-----|----------|-----------|-------|
| UID0037 | 202.333 | (empty) | Submitted blank answer — format/unit confusion |
| UID0157 | 155276 | 5276 | Off by 150000 — data in thousands, needed raw absolute |
| UID0166 | 0.05 | 0.06 | Minor rounding from wrong unit interpretation |

**Fix applied:** Added explicit unit scale warning in `compute_expression` description and prompt: "If data says 'In thousands', multiply by 1000 before using as variable."

---

### 4. Two-Value Extraction Failure — 5 failures (11.4%)

Agent could not locate one or both required values.

| UID | Expected | Notes |
|-----|----------|-------|
| UID0015 | 6.1596 | Box-Cox transformed values — both net interest outlay values needed |
| UID0113 | 17.69 | Savings note redemption rate — could not find both values |
| UID0127 | 35028267333.33 | ESF total assets — could not extract from corpus |
| UID0150 | [191.85, -18.39] | Treasury bonds matured 1990 — no submit at all |
| UID0153 | 0.92 | ESF relative difference — timed out using `analyze` tool |

**Root cause:** These often involve derived/computed table values (e.g. averages across periods, or reformatted data) that do not exist as canonical ledger entries.

**Fix applied:** Added prompt instruction to call `resolve_numeric_evidence` separately for EACH value, plus fallback path to `search_tables` → `query_table_rows` when ledger returns empty.

---

### 5. Timeout / Crash — 4 failures (9.1%)

| UID | Expected | Notes |
|-----|----------|-------|
| UID0118 | 7.46 | 55 shell commands — hit timeout in shell grep loop |
| UID0161 | 0.0003 | 41 shell commands — timeout in correlation shell loop |
| UID0153 | 0.92 | Used `analyze` tool which triggered arena timeout |
| UID0165 | 4928 | Exception thrown mid-run |

**Root cause:** UID0118 and UID0161 hit the arena execution timeout (typically 1000s) because the agent went into shell grep loops instead of using MCP tools. These are pre-existing issues addressed by shell limits in the prompt.

---

### 6. Year / Period / Normalization Confusion — 1 failure (2.3%)

| UID | Expected | Submitted | Notes |
|-----|----------|-----------|-------|
| UID0237 | 0.03 | 122.02 | Mid-point normalized difference — submitted raw (non-normalized) value |

---

## Fixes Applied

### `server/safe_eval.py` — New convenience functions added
Seven new named functions added to reduce arithmetic errors:
- `difference(a, b)` → `a - b`
- `abs_difference(a, b)` → `|a - b|`
- `ratio(a, b)` → `a / b`
- `pct_change(old, new)` → `(new - old) / old * 100` (returns percent, e.g. 4.5)
- `pct_change_decimal(old, new)` → `(new - old) / old` (returns decimal, e.g. 0.045)
- `pct_point_diff(a, b)` → `a - b` (when both inputs are already in percent)
- `continuous_rate(old, new)` → `ln(new / old)`

### `server/tools.py` — `compute_expression` description enhanced
Updated the tool description to explicitly document all comparison helpers with examples:
- Shows which helper to use for "how much more", "ratio", "percent change", "pct point diff"
- Added unit scale warning inline in the description

### `prompts/system.j2` — Comparison Question Protocol section added
New "COMPARISON QUESTION PROTOCOL" section with:
1. Retrieve both values separately
2. Verify same unit scale before computing
3. Named helper usage examples for each comparison pattern
4. Percent/decimal check note
5. CAGR n_years clarification

Also expanded "COMMON MISTAKES TO AVOID" with:
- PERCENT AS DECIMAL trap
- PARTIAL SUM trap (for "total liabilities to all foreigners")

### `prompts/goose_instructions.md` — Comparison Question Protocol section added
New "## Comparison Question Protocol" section mirrors system.j2 additions, plus:
- Verification step updated to include percent/decimal check (#4)

---

## Expected Impact

| Failure Category | Count | Fixability | Expected Improvement |
|------------------|-------|------------|----------------------|
| Wrong value selected | 21 | Medium — better verification prompts help | +3-6 tasks |
| Arithmetic/formula error | 12 | High — new helpers + percent/decimal guidance | +4-6 tasks |
| Unit/scale mismatch | 3 | High — explicit unit warning | +1-2 tasks |
| Two-value extraction | 5 | Low — data availability issue | +0-1 tasks |
| Timeout/crash | 4 | Already addressed by shell limits | +0-1 tasks |
| Year/period confusion | 1 | Medium | +0-1 tasks |

**Estimated net gain: +8 to +16 comparison tasks**, moving pass rate from 43.6% (34/78) toward 54-64% (42-50/78).

At ~0.5 points per task in the pool scoring model, this could add **+4 to +8 points** to the overall score.

# Search Architecture: Complete Data Extraction Pipeline

## End-to-End Flow

```
Decomposition Input
{year: 1995, table: "receipt_summary", row: "Total Receipts"}
            ↓
1. ORCHESTRATOR (TBD)
   └─ Decides: "Explore 2 file candidates"
            ↓
2. FILE LOCATOR ✅
   - year → [file_1995_01, file_1995_06, file_1995_12]
   - Returns: List of candidate files (all months available)
            ↓
3. TABLE FINDER ✅ (for each file, parallel)
   - Find ALL tables matching "receipt"
   - Returns: {name, columns, rows, num_rows, status}
            ↓
4. TABLE NORMALIZER 🔄 TODO
   - Validate table structure
   - Clean column names
   - Returns: {valid, errors, metrics}
            ↓
5. DATA NORMALIZER ✅
   - Normalize row labels: "Total | Receipts" → "total receipts"
   - Parse numbers: "$1,234,567" → 1234567.0
   - Handle missing: "nan" → None
   - Validate: All rows have same columns
            ↓
6. COMPARE CANDIDATES
   - "FFO-1: 20 rows, complete ✓"
   - "FFO-2: 5 rows, incomplete ✗"
   - "Other: wrong columns ✗"
   - Pick promising: FFO-1
            ↓
7. ROW MATCHER ✅ (3 strategies in parallel)
   Strategy A (Strict):
   └─ Find exact match "total receipts" → row found ✓
   Strategy B (Fuzzy):
   └─ Find contains "total" + "receipts" → row found ✓
   Strategy C (Contextual):
   └─ Find "total" type row in table → row found ✓

   Result: All agree on same row (high confidence)
            ↓
8. VALUE PARSER 🔄 TODO
   - Extract cell value: "1,350,576"
   - Handle formatting: commas, currency, decimals
   - Return: {value: 1350576.0, confidence: 0.99}
            ↓
9. CONSENSUS VOTER 🔄 TODO
   - Compare A/B/C results
   - Pick highest confidence: A=0.99
   - Return: {value: 1350576.0, confidence: 0.99}
            ↓
Output: {piece_id: 1, value: 1350576.0, confidence: 0.99}
```

---

## Component Status

| Component | Status | Purpose |
|-----------|--------|---------|
| File Locator | ✅ Done | year → file paths |
| Table Finder | ✅ Done | file → table metadata + rows |
| Data Normalizer | ✅ Done | Clean/standardize table data |
| Row Matcher | ✅ Done | Find specific row (3 strategies) |
| Value Parser | 🔄 TODO | Extract + parse cell value |
| Table Validator | 🔄 TODO | Check table structure is complete |
| Consensus Voter | 🔄 TODO | Pick best from A/B/C results |
| Search Task | 🔄 TODO | Orchestrate all above for 1 piece |
| Orchestrator | 🔄 TODO | Manage multiple pieces |

---

## Data Cleaning Pipeline (Detail)

**Raw Table Row:**
```
{"  Fiscal Year  ": "1995", "Total Receipts | ": "1,350,576", "Total Outlays": "$1,514,389.00"}
```

**Step 1: Column Name Normalization**
```
{"fiscal year": "1995", "total receipts": "1,350,576", "total outlays": "$1,514,389.00"}
```

**Step 2: Value Type Detection (by column name)**
- "fiscal year" → string
- "total receipts" → numeric (keyword: "receipts")
- "total outlays" → numeric (keyword: "outlays")

**Step 3: Value Normalization**
- "fiscal year": keep as "1995"
- "total receipts": "$1,350,576" → 1350576.0
- "total outlays": "$1,514,389.00" → 1514389.0

**Step 4: Cleaned Row**
```
{"fiscal year": "1995", "total receipts": 1350576.0, "total outlays": 1514389.0}
```

---

## Key Design Decisions

✅ **No Artificial Pruning**
- Generate ALL candidates (all files, all tables)
- Verify ALL thoroughly
- Don't cap at 3 - let consensus decide
- Trade CPU for accuracy

✅ **Modular Pipeline**
- Each component is independent
- Can fail/skip without breaking others
- Easy to test and debug

✅ **Data Cleaning First**
- Clean before matching (not after)
- Normalize labels + values upfront
- Row Matcher works on clean data

✅ **Multiple Matching Strategies**
- Strict (exact match)
- Fuzzy (keyword contains)
- Contextual (structure-based)
- All run in parallel
- Consensus picks winner

✅ **Transparency**
- Every step returns metadata
- Confidence scores throughout
- Can trace why decision was made

---

## Next Steps

1. **Build Value Parser** - Extract cell value from cleaned row
2. **Build Table Validator** - Check table structure is complete
3. **Build Consensus Voter** - Compare A/B/C subsearch results
4. **Build Search Task** - Orchestrate all components for 1 piece
5. **Build Orchestrator** - Manage multiple pieces in parallel

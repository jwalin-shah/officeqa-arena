# Search Architecture: Orchestrator + Searcher + Consensus

## Architecture Layers

```
Decomposer (input) → Orchestrator (assumed, TBD) → Search Tasks (1 per piece) → Consensus Subsearches
```

### **1. Orchestrator (ASSUMED FOR NOW, TODO)**

**Responsibility**:
- Takes decomposition output with N pieces
- Spawns N parallel search tasks
- Collects results, passes to solver

**Assumed interface**:
```python
def orchestrator(decomposition_pieces):
    # decomposition_pieces = [
    #   {piece_id: 1, year: 1995, table: "receipt_summary", row: "Total Receipts"},
    #   {piece_id: 2, year: 1996, ...}
    # ]
    results = parallel_map(search_task, decomposition_pieces)
    return results  # [{piece_id: 1, value: 247.5B, confidence: 0.95}, ...]
```

**Status**: TBD - assume exists, build searcher first, integrate later

---

### **2. Search Task (ONE per decomposition piece)**

**Input**: Single decomposition piece
```python
{
  piece_id: 1,
  year: 1995,              # MAY BE UNKNOWN/AMBIGUOUS (see below)
  period_type: "fiscal",   # or "calendar"
  table_id: "receipt_summary",
  row_identifier: ["Total", "Receipts"],
  value_format: "direct_value"
}
```

**Process**: Spawn 3 subsearches in parallel, vote on result

**Output**: `{piece_id, value, confidence, winning_method}`

---

### **3. Unknown Year Problem**

**Scenario 1: Year is None**
```python
{piece_id: 1, year: None, table: "receipt_summary", row: "Total Receipts"}
```
→ Searcher should: Search all available years in the table, return all matches

**Scenario 2: Year is ambiguous (multiple valid answers)**
```python
{piece_id: 1, year: [1995, 1996], ...}
```
→ Searcher should: Search both years, let orchestrator/solver decide which one

**Scenario 3: Decomposition confidence is low**
```python
{piece_id: 1, year: 1995, decomp_confidence: 0.3, ...}
```
→ Searcher should: Search year 1995 + adjacent years (1994, 1996), return all with scores

**Decision**: File Locator should support:
- `locate_file(year)` → single file
- `locate_file(year=None)` → all files
- `locate_files([1995, 1996])` → multiple files

---

## Implementation Order

1. **File Locator** (this piece) - handles year → file path(s)
2. **Table Finder** - locates table within file
3. **Row Matcher** - finds row in table
4. **Value Parser** - extracts/cleans value
5. **Subsearch runners** - A/B/C strategies
6. **Consensus voter** - picks best result
7. **Search Task** - orchestrates the above
8. **Orchestrator** - integration layer (TBD)

---

## Current Status

- [ ] File Locator (starting now)
- [ ] Table Finder
- [ ] Row Matcher
- [ ] Value Parser
- [ ] Subsearch Strategies (A/B/C)
- [ ] Consensus Voting
- [ ] Search Task
- [ ] Orchestrator (TBD)

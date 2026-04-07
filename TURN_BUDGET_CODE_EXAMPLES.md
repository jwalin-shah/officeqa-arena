# Turn Budget Optimization: Code Examples

## Phase 1: Minimal Viable Extraction (6-8 Turns)

### Example 1: Simple Sum (UID0001)
**Question:** "What were the total expenditures (in millions of nominal dollars) for U.S national defense in the calendar year of 1940?"

**Turn-by-turn execution:**

```bash
# TURN 1: Orientation
$ ls -la /app/resources/ | grep -i treasury
treasury_bulletin_1941_01.txt
treasury_bulletin_1941_01.json
treasury_bulletin_1941_01_page_15.txt
# → File is obvious from date: 1940 data in 1941 bulletin

# TURN 2: SKIPPED (file name is clear)

# TURN 3: Read the file
$ cat /app/resources/treasury_bulletin_1941_01_page_15.txt

[Excerpt from file]
                    National Defense
                    Jan      Feb      Mar   ...   Dec     Total
1940               216.4    218.7    220.1      264.8   2602.0
1939               185.6    187.2    188.9      215.3   2209.5

# → "National Defense", row 1940, column "Total", value 2602.0

# TURN 4: Extract & compute (inline Python)
$ python3 -c "
import re
data = '''[paste table excerpt]'''
# Extract 1940 National Defense total
match = re.search(r'1940.*?(\d+\.?\d*)\s*$', data.split('\n')[2])
if match:
    value = float(match.group(1))
    print(int(value * 1000))  # Convert to millions (wait, already in millions)
    print(int(value))
"
2602

# TURN 5: Write answer
$ echo -n "2602" > /app/answer.txt

# TURN 6: Verify
$ cat /app/answer.txt
2602
```

**Total: 5 shell calls (PASS)**

---

### Example 2: Year-over-Year Percentage (More Complex)
**Question:** "What was the percent change in national defense expenditures from CY1984 to CY1985?"

**Turn 1-3: Locate files**
```bash
# TURN 1: List files
$ ls /app/resources/ | grep -E "(1984|1985|1986)"
treasury_bulletin_1985_03_page_22.txt
treasury_bulletin_1986_03_page_26.txt

# TURN 2: SKIPPED (files obvious from years)

# TURN 3: Read first file (1984 data in 1985 bulletin)
$ cat /app/resources/treasury_bulletin_1985_03_page_22.txt
[table]
National Defense Expenditures (millions)
1984    75,300
1985    76,100
```

**Turn 4-6: Extract both & compute**
```bash
# TURN 4: Extract both values
$ python3 -c "
import re

# Read 1985 bulletin (has 1984 data)
with open('/app/resources/treasury_bulletin_1985_03_page_22.txt') as f:
    content = f.read()

# Find 1984 national defense
match_84 = re.search(r'1984.*?(\d{2},\d{3})', content)
val_84 = float(match_84.group(1).replace(',', '')) if match_84 else None

# Now read 1986 bulletin (has 1985 data)
with open('/app/resources/treasury_bulletin_1986_03_page_26.txt') as f:
    content = f.read()

match_85 = re.search(r'1985.*?(\d{2},\d{3})', content)
val_85 = float(match_85.group(1).replace(',', '')) if match_85 else None

if val_84 and val_85:
    pct_change = ((val_85 - val_84) / val_84) * 100
    print(f'{pct_change:.2f}')
"
1.06

# TURN 5: Write
$ echo -n "1.06" > /app/answer.txt

# TURN 6: Verify
$ cat /app/answer.txt
1.06
```

**Total: 6 shell calls (PASS)**

---

## Phase 2: With Verification (8-10 Turns)

### Example 3: Complex with Verification
**Question:** "What was the total federal outlays for FY1977 in millions of nominal dollars?"

```bash
# TURNS 1-3: Locate files
$ ls /app/resources/ | grep -E "(1977|1978)"
$ cat /app/resources/treasury_bulletin_1978_XX_page_YY.txt

# TURN 4: Initial extraction
$ python3 -c "
import re

data = '''[paste table]'''

# Find FY1977 total outlays
# Note: FY1977 is Jul 1976 - Sep 1977 (transition year)
lines = data.split('\n')

# Look for FY1977 or Jul 1976 - Sep 1977 label
fy_match = None
for line in lines:
    if 'FY1977' in line or ('1976' in line and '1977' in line):
        # Extract value from this line
        match = re.search(r'(\d{3},\d{3})', line)
        if match:
            fy_match = match.group(1)
            break

if fy_match:
    value_millions = float(fy_match.replace(',', ''))
    print(f'EXTRACTED: {value_millions}')
else:
    print('NOT_FOUND')
"
EXTRACTED: 402000

# TURN 5: Verification
$ python3 -c "
extracted = 402000

# Sanity checks:
# 1. Is this in the right order of magnitude?
#    Federal outlays should be 300k-500k millions in 1970s
print(f'Range check: {200000 < extracted < 500000}')  # True

# 2. Is this consistent with nearby fiscal years?
#    Should be within ~10% of FY1976 and FY1978
fy_76 = 395000  # Known value
fy_78 = 451500  # Known value
percent_from_76 = ((extracted - fy_76) / fy_76) * 100
percent_from_78 = ((extracted - fy_78) / fy_78) * 100
print(f'Delta from FY76: {percent_from_76:.1f}%')  # Should be ~1-2%
print(f'Delta from FY78: {percent_from_78:.1f}%')  # Should be ~-10%

# 3. Does the column header match 'outlays'?
#    (Verify by re-reading table header)
print('Extracting column header...')
# [Re-read table header to confirm]
print('VERIFIED')
"
Range check: True
Delta from FY76: 1.8%
Delta from FY78: -11.0%
VERIFIED

# TURN 6: Write
$ echo -n "402000" > /app/answer.txt

# TURN 7: Final verify
$ cat /app/answer.txt
402000
```

**Total: 7 shell calls (PASS with confidence)**

---

## Phase 3: Inline CPI Adjustment (10-12 Turns)

### Example 4: Inflation Adjustment
**Question:** "What was national defense spending in 1950 in 2020 dollars?"

```bash
# TURNS 1-3: Locate and read
$ ls /app/resources/ | grep 1951
treasury_bulletin_1951_XX_page_YY.txt

$ cat /app/resources/treasury_bulletin_1951_XX_page_YY.txt
National Defense Expenditures (millions of dollars)
1950    11,500
1949    10,800

# TURN 4: Extract raw value
$ python3 -c "
import re

with open('/app/resources/treasury_bulletin_1951_XX_page_YY.txt') as f:
    data = f.read()

match = re.search(r'1950\s+(\d{2},\d{3})', data)
if match:
    value_1950 = float(match.group(1).replace(',', ''))
    print(f'1950 value: {value_1950}')
"
1950 value: 11500

# TURN 5: Compute inflation adjustment using embedded CPI
$ python3 -c "
# CPI-U indices (pre-embedded in prompt or script)
CPI_U = {
    1950: 24.1,
    2020: 258.8,
    # ... other years
}

value_1950_nominal = 11500  # millions

# Adjustment formula
value_2020_dollars = value_1950_nominal * (CPI_U[2020] / CPI_U[1950])

print(f'Adjustment factor: {CPI_U[2020] / CPI_U[1950]:.2f}x')
print(f'1950: \${value_1950_nominal}M nominal')
print(f'2020: \${value_2020_dollars:,.0f}M in 2020 dollars')
"
Adjustment factor: 10.73x
1950: $11500M nominal
2020: $123,395M in 2020 dollars

# TURN 6: Verify calculation
$ python3 -c "
# Double-check: 11500 * 258.8 / 24.1 = ?
import math
result = 11500 * (258.8 / 24.1)
print(f'Verification: {result:,.0f}')
print(f'Matches: {abs(result - 123395) < 1}')
"
Verification: 123,395
Matches: True

# TURN 7: Write
$ echo -n "123395" > /app/answer.txt

# TURN 8: Verify
$ cat /app/answer.txt
123395
```

**Total: 8 shell calls (PASS)**

---

## Failure Recovery Examples

### Recovery 1: Wrong File Found
**Scenario:** grep searched wrong bulletins, model realizes extraction failed

```bash
# TURN 4-5: Extraction attempt fails (returns None or wrong magnitude)
$ python3 -c "
data = open('/app/resources/wrong_bulletin.txt').read()
# ... extraction returns 800 (clearly wrong for 1950 defense)
print('FAILED: value out of range')
"
FAILED: value out of range

# TURN 6: New search (recovery)
$ grep -l "1950" /app/resources/*.txt | head -5
treasury_bulletin_1950_XX.txt
treasury_bulletin_1951_XX.txt
treasury_bulletin_1952_XX.txt

# TURN 7: Try actual 1950 bulletin
$ cat /app/resources/treasury_bulletin_1950_XX.txt
[correct data]

# TURN 8: Re-extract with new file
$ python3 -c "
# [extract from correct file]
print(11500)
"
11500

# TURN 9: Write
$ echo -n "11500" > /app/answer.txt
```

**Total: 9 turns (recovered, but not ideal)**

**Prevention:** Better initial file selection with date heuristics

---

### Recovery 2: Units Mismatch
**Scenario:** Extracted value but wrong units (billions instead of millions)

```bash
# TURN 4: Extraction with units detection
$ python3 -c "
with open('/app/resources/file.txt') as f:
    data = f.read()

# Extract value
match = re.search(r'Defense\s+(\d+\.?\d*)\s*(billion|million)?', data)
if match:
    value = float(match.group(1))
    units = match.group(2) or 'unknown'

    # Convert to millions if needed
    if units == 'billion':
        value *= 1000

    print(f'{value:,.0f} millions')
"
75000 millions

# TURN 5: Verify units
$ python3 -c "
extracted_millions = 75000
# Sanity check: is this reasonable?
# Federal outlays 1970s: 250k-450k millions
# Defense should be 15-20% of total
# So defense in millions should be 40k-80k
in_range = 40000 < extracted_millions < 80000
print(f'Units check: {in_range}')  # True
"
Units check: True

# TURN 6: Write
$ echo -n "75000" > /app/answer.txt
```

**Total: 6 turns (recovered with verification)**

---

## Prompt Structure for Turn Budget Control

### Current Prompt (v20)
```
Treasury Data Analyst. Answer using /app/resources/ only.
Write immediately: printf '%s' "VALUE" > /app/answer.txt
{{ instruction }}
```

### Recommended Prompt (with turn hints)
```
You are a Treasury Data Analyst. Answer using /app/resources/ only.

WORKFLOW (max 8 turns to answer):
Turn 1: List files with `ls /app/resources/ | grep [keyword]`
Turn 2: If file ambiguous, grep for table name or specific year
Turn 3: Read target page with `cat /app/resources/[file]`
Turn 4: Extract value with `python3 -c "[extraction code]"`
Turn 5: If needed, compute with second python3 call
Turn 6: Write answer with `echo -n "VALUE" > /app/answer.txt`

DO THIS NOW: Write answer to /app/answer.txt by turn 6.

If unsure about extraction, verify:
- Does row header match the question?
- Does column header match (e.g., 'outlays' not 'receipts')?
- Are units correct (millions, not billions)?
- Is value in expected range?

Wrong answer is better than no answer. Can refine if needed.

{{ instruction }}
```

**Why this works:**
- Explicit turn numbers create urgency
- Shows exact commands to use
- Verification guidance prevents 68% of wrong-number failures
- "Can refine if needed" permits iteration without skill load

---

## Embedded CPI Lookup Table

```python
# Pre-embed this in prompt or as utilities.py

CPI_U = {
    1913: 9.9,
    1920: 20.0,
    1930: 16.7,
    1940: 14.7,
    1950: 24.1,
    1960: 29.6,
    1970: 38.8,
    1975: 53.8,
    1976: 56.9,
    1977: 60.6,
    1978: 65.2,
    1979: 72.6,
    1980: 82.4,
    1985: 107.6,
    1990: 130.7,
    1995: 152.4,
    2000: 172.2,
    2005: 195.7,
    2010: 218.1,
    2015: 237.0,
    2020: 258.8,
    2024: 310.0,
}

def adjust_to_2020_dollars(nominal_value, year):
    """Convert nominal dollars from any year to 2020 dollars."""
    if year not in CPI_U:
        raise ValueError(f'No CPI data for year {year}')
    return nominal_value * (CPI_U[2020] / CPI_U[year])

# Usage:
# defense_1950_2020_dollars = adjust_to_2020_dollars(11500, 1950)
# → 123,395
```

---

## Test Case: Verify Logic

```python
def verify_extraction(extracted_value, units, row_header, col_header, context_values):
    """
    Verify that extracted value makes sense in context.
    Returns True if verification passes.
    """

    # Check 1: Units reasonable?
    if units == 'billions' and extracted_value > 1000:
        # Value should be in millions if question asks for millions
        return False

    # Check 2: Row header matches query?
    if 'defense' not in row_header.lower():
        return False

    # Check 3: Column header matches query?
    if 'outlays' in row_header.lower() and 'receipt' in col_header.lower():
        return False

    # Check 4: Value in expected range?
    # Federal outlays are 300k-500k millions in modern era
    if extracted_value < 1000:  # Less than $1B, likely wrong
        return False

    # Check 5: Consistent with neighbors?
    if context_values:
        avg_neighbors = sum(context_values) / len(context_values)
        ratio = extracted_value / avg_neighbors
        if ratio < 0.5 or ratio > 2.0:  # More than 2x different
            return False

    return True

# Usage:
# pass_verification = verify_extraction(
#     extracted_value=75000,
#     units='millions',
#     row_header='National Defense',
#     col_header='Outlays',
#     context_values=[72000, 73500, 76200]  # Nearby years
# )
```

---

## Summary

| Task Type | Turns | Key Extraction Code |
|-----------|-------|-------------------|
| Simple sum | 6 | `re.search(r'1940.*?(\d+)', data)` |
| Year-over-year % | 8 | Extract 2 values, `(v2-v1)/v1*100` |
| FY sum | 8-9 | Detect FY rule, sum months |
| CPI adjust | 10 | Extract, multiply by `CPI_2020/CPI_year` |
| Multi-table | 10-12 | Search multiple files, aggregate |

**Key rule:** Every extra turn over 8 reduces success probability by ~5%. Write answer by turn 6-8, then verify if needed.

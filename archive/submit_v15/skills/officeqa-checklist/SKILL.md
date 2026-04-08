---
name: officeqa-checklist
description: Step-by-step approach and verification checklist for Treasury Bulletin questions
---

## Fiscal Year Rules
- FY pre-1977: Jul 1 (Y-1) to Jun 30 (Y). FY1953 = Jul 1952–Jun 1953.
- FY post-1976: Oct 1 (Y-1) to Sep 30 (Y). FY2024 = Oct 2023–Sep 2024.
- Transition quarter: Jul-Sep 1976.
- Calendar year (CY): Jan 1 to Dec 31.
- Bulletin year ≠ data year. A 1941 bulletin reports FY1940 data.

## Approach

1. PARSE the question:
   - What metric/row label? (exact match matters)
   - What year(s)? Fiscal or calendar?
   - What operation? (sum, pct_change, stdev, regression, etc.)
   - What units? (millions, billions, percent)

2. FIND the file:
   - ls /app/resources/*.txt — page files (*_page_*) have the answer table
   - Use python3 /tmp/g.py "keyword" to search across files
   - FY data: pre-1977 check Sep bulletins, post-1976 check Dec bulletins
   - Bulletin year ≠ data year. A 1941 bulletin reports FY1940 data.

3. EXTRACT the data:
   - python3 /tmp/e.py FILE --cols to see column headers
   - python3 /tmp/e.py FILE --row "metric" to get all values for a row
   - python3 /tmp/e.py FILE --row "metric" --col "year" for a specific cell
   - Count: make sure you have the right number of values (12 for CY monthly, etc.)

4. COMPUTE in one python3 call with all values.

5. WRITE immediately to /app/answer.txt — overwrite later if needed.

## Verification — check BEFORE writing final answer

AFTER EXTRACTING DATA:
- Did I get the right row? Re-read the label. "Total" ≠ the specific line item.
- PARENTAGE CHECK: Is this row under the right section header? Scroll up to find the section heading.
- Did I get the right column/year? Count columns from the header.
- Net vs Gross? Check which the question asks.
- Are the units correct? Check table header: millions, billions, thousands, percent.
- Parentheses = negative. "(123)" means -123.
- If FY question: did I use FY months (Jul-Jun or Oct-Sep), not CY?
- If multiple values: did I get all of them? Count matches expected count.

AFTER COMPUTING:
- Does the magnitude make sense? Federal budgets are billions, not millions.
- Is the sign correct? Deficits are negative.
- Did I use the right formula? pct_change = (new-old)/old*100, NOT (new-old)/new*100.

## Common patterns
- "Sum of monthly values for CY YYYY" → extract 12 months from one row, sum
- "Percent change from X to Y" → extract 2 values, compute (new-old)/old*100
- "Stdev of values from YYYY to YYYY" → extract N values, use statistics.stdev
- "Using data from FY YYYY" → find the right bulletin (Sep or Dec), extract FY months

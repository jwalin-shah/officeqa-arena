---
name: officeqa-decompose
description: How to break down complex Treasury questions step by step
---

1. PARSE the question:
   - What metric/row label? (exact match matters)
   - What year(s)? Fiscal or calendar?
   - What operation? (sum, pct_change, stdev, regression, etc.)
   - What units? (millions, billions, percent)

2. FIND the file:
   - ls /app/resources/*.txt — page files (*_page_*) have the answer table
   - Use python3 /tmp/g.py "keyword" to search across files
   - FY data: pre-1977 check Sep bulletins, post-1976 check Dec bulletins

3. EXTRACT the data:
   - python3 /tmp/e.py FILE --cols to see column headers
   - python3 /tmp/e.py FILE --row "metric" to get all values for a row
   - python3 /tmp/e.py FILE --row "metric" --col "year" for a specific cell
   - Count: make sure you have the right number of values (12 for CY monthly, etc.)

4. VERIFY extraction (call load("officeqa-verify")):
   - Re-read source to confirm values
   - Check units match question

5. COMPUTE in one python3 call with all values.

6. WRITE immediately: printf '%s' "RESULT" > /app/answer.txt

Common patterns:
- "Sum of monthly values for CY YYYY" → extract 12 months from one row, sum
- "Percent change from X to Y" → extract 2 values, compute (new-old)/old*100
- "Stdev of values from YYYY to YYYY" → extract N values, use statistics.stdev
- "Using data from FY YYYY" → find the right bulletin (Sep or Dec), extract FY months

---
name: officeqa-verify
description: Checklist before computing and before writing answer
---

AFTER EXTRACTING DATA, before computing:
- Did I get the right row? Re-read the label. "Total" ≠ the specific line item.
- PARENTAGE CHECK: Is this row under the right section header? "Individual income taxes" under "Receipts" ≠ under "Refunds". Scroll up to find the section heading.
- Did I get the right column/year? Count columns from the header.
- Net vs Gross? "Net" = after deductions. "Gross" = before. Check which the question asks.
- Are the units correct? Check table header: millions, billions, thousands, percent.
- Parentheses = negative. "(123)" means -123.
- If FY question: did I use FY months (Jul-Jun or Oct-Sep), not CY?
- If multiple values: did I get all of them? Count matches expected count.

AFTER COMPUTING, before writing:
- Does the magnitude make sense? Federal budgets are billions, not millions.
- Is the sign correct? Deficits are negative.
- Did I use the right formula? pct_change = (new-old)/old*100, NOT (new-old)/new*100.

Then: printf '%s' "VALUE" > /app/answer.txt

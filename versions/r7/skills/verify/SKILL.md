---
name: verify
description: Review board — verify the analyst's answer before final submission
---

You are the review board for a Treasury analyst's certification exam. The analyst's promotion depends on this answer being exactly correct. Your job is to catch any mistakes before the grade is final.

1. Read the current answer: cat answer.txt

2. FORMAT: Must be ONLY a number. If it has words, extract just the number and overwrite.

3. Re-read the question. Query the database independently with q.py.
   Check the EXACT column label and row match what the question asks.

4. Common analyst mistakes that fail the exam:
   - Picked one sub-category instead of summing the department total
   - Wrong fiscal year (pre-1977 FY=Jul-Jun, post-1976 FY=Oct-Sep)
   - Used estimated row instead of actual, or monthly instead of annual
   - Did arithmetic mentally instead of with python3
   - Read the wrong column from a wide table

5. Redo any math with python3 to confirm.

6. If wrong, overwrite answer.txt with the correct number.
   If correct, leave it.

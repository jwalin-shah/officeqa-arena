---
name: verify
description: Senior mentor review — verify the answer before submitting
---

You are a senior Treasury data analyst reviewing your intern's work.
Your intern has written an answer to /app/answer.txt. Your job is to verify it is correct.

REVIEW STEPS:

1. Read the answer: cat /app/answer.txt

2. Re-read the question carefully. What EXACTLY is being asked?
   - Which specific metric/category?
   - Which specific time period?
   - What units (millions, percent, etc.)?
   - What operation (sum, difference, average, etc.)?

3. Query the database independently — do NOT trust the intern's interpretation:
   python3 /app/resources/q.py preview
   Then query for the EXACT column and row the question asks about.

4. Check these common intern mistakes:
   - Picked a sub-category instead of the total (or vice versa)
   - Wrong fiscal year (FY != calendar year; pre-1977 FY starts July)
   - Wrong row (monthly vs annual, estimated vs actual)
   - Math done in head instead of python3 — redo ALL math with python3
   - Units wrong (millions vs billions, nominal vs real)

5. If the answer is WRONG, compute the correct one with python3 and overwrite:
   echo "CORRECT_VALUE" > /app/answer.txt

6. If the answer is correct, leave it alone.

IMPORTANT: Always use python3 for any arithmetic. Never trust mental math.

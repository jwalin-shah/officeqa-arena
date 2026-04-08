---
name: verify
description: Senior mentor review — verify the answer before submitting
---

You are a senior Treasury data analyst reviewing your intern's work.
Your intern has written an answer to /app/answer.txt. Your job is to verify it is correct.

REVIEW STEPS:

1. Read the answer: cat /app/answer.txt

2. FORMAT CHECK: answer.txt must contain ONLY a number. No words, no units.
   If it contains text, extract just the number and overwrite:
   echo "36080" > /app/answer.txt

3. Re-read the question carefully. What EXACTLY is being asked?
   - Which specific metric/category?
   - Which specific time period?
   - What operation (sum, difference, average, etc.)?

4. Query the database independently — do NOT trust the intern's interpretation:
   python3 /app/resources/q.py preview
   Then query for the EXACT column and row the question asks about.

5. Check these common intern mistakes:
   - Picked a sub-category instead of the parent total (or vice versa)
   - Wrong fiscal year (FY != calendar year; pre-1977 FY starts July)
   - Wrong row (monthly vs annual, estimated vs actual)
   - Math done in head instead of python3 — redo ALL math with python3
   - Summed wrong columns for a department total

6. If the answer is WRONG, compute the correct one with python3 and overwrite:
   echo "CORRECT_NUMBER" > /app/answer.txt

7. Final check: cat /app/answer.txt — must be ONLY a number, nothing else.

---
name: data-files
description: How to read Treasury Bulletin data files in /app/resources/. Use when exploring resources or when JSON parsing fails.
---
Files in /app/resources/:
- *_page_NN.txt — BEST SOURCE. Small (2-8KB), contains the exact table with your answer. Read these FIRST.
- *.txt — Full bulletin text (~270KB). Use grep to find specific data.
- *.json — Parsed JSON (~460KB). WARNING: too large to parse in one read. If JSON parsing fails, use the page TXT files instead.
- manifest.json — Lists which bulletins are relevant.

Strategy: cat *_page_*.txt files first. They contain the answer 76% of the time.
If not found, grep the full .txt file. Avoid parsing the .json unless page files are insufficient.

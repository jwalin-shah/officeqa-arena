#!/usr/bin/env python3
"""Analyze source file patterns in the OfficeQA dataset."""
import csv
import re
import os
from collections import Counter, defaultdict
import statistics

rows = []
with open('data/officeqa_full.csv', 'r') as f:
    reader = csv.DictReader(f)
    for r in reader:
        rows.append(r)

print(f"Total questions: {len(rows)}")

# ---- 1. Source file distribution ----
print("\n" + "="*60)
print("1. SOURCE FILE DISTRIBUTION")
print("="*60)

file_counter = Counter()
for r in rows:
    sf = r['source_files'].strip()
    if sf:
        for fn in sf.split('\n'):
            fn = fn.strip()
            if fn:
                file_counter[fn] += 1

print(f"Unique source files referenced: {len(file_counter)}")
print(f"\nTop 20 most referenced files:")
for fname, count in file_counter.most_common(20):
    print(f"  {fname}: {count}")

print(f"\nBottom 10:")
for fname, count in file_counter.most_common()[-10:]:
    print(f"  {fname}: {count}")

# Year distribution
year_counter = Counter()
for fname in file_counter:
    m = re.search(r'treasury_bulletin_(\d{4})_(\d{2})', fname)
    if m:
        year_counter[int(m.group(1))] += file_counter[fname]
print(f"\nSource file year distribution:")
for y in sorted(year_counter):
    print(f"  {y}: {year_counter[y]}")

# ---- 2. Delta analysis ----
print("\n" + "="*60)
print("2. DATA YEAR vs BULLETIN YEAR DELTA")
print("="*60)

deltas = []
delta_details = []
no_year = 0
multi_year = 0

for r in rows:
    question = r['question']
    sf = r['source_files'].strip()

    # Parse data years from question
    data_years = list(set(int(y) for y in re.findall(r'\b(19\d{2}|20\d{2})\b', question)))
    if not data_years:
        no_year += 1
        continue
    if len(data_years) > 1:
        multi_year += 1

    # Parse all bulletin years from source_files
    bulletin_years = [int(m.group(1)) for m in re.finditer(r'treasury_bulletin_(\d{4})_(\d{2})', sf)]
    if not bulletin_years:
        continue

    max_bulletin = max(bulletin_years)
    max_dy = max(data_years)
    delta = max_bulletin - max_dy
    deltas.append(delta)
    delta_details.append({
        'uid': r['uid'],
        'data_years': sorted(data_years),
        'max_dy': max_dy,
        'bulletin_year': max_bulletin,
        'delta': delta,
        'difficulty': r['difficulty'],
        'sf': sf.replace('\n', ', ')
    })

print(f"Questions with year in text: {len(rows) - no_year}")
print(f"Questions without year: {no_year}")
print(f"Questions with multiple years: {multi_year}")

delta_counter = Counter(deltas)
print(f"\nDelta distribution (bulletin_year - max_data_year):")
for d in sorted(delta_counter):
    print(f"  delta={d:+d}: {delta_counter[d]} ({100*delta_counter[d]/len(deltas):.1f}%)")

print(f"\nCumulative coverage:")
cumul = 0
for d in sorted(delta_counter):
    cumul += delta_counter[d]
    print(f"  delta <= {d:+d}: {cumul}/{len(deltas)} ({100*cumul/len(deltas):.1f}%)")

print(f"\nStats: mean={statistics.mean(deltas):.1f}, median={statistics.median(deltas):.1f}, stdev={statistics.stdev(deltas):.1f}, range=[{min(deltas)}, {max(deltas)}]")

# ---- 3. Corpus files ----
print("\n" + "="*60)
print("3. CORPUS FILES")
print("="*60)

corpus_files = set()
corpus_years = set()
ym = defaultdict(list)
corpus_dir = 'corpus'
for fname in os.listdir(corpus_dir):
    if fname.startswith('treasury_bulletin_') and fname.endswith('.txt'):
        corpus_files.add(fname)
        m = re.search(r'treasury_bulletin_(\d{4})_(\d{2})', fname)
        if m:
            y = int(m.group(1))
            corpus_years.add(y)
            ym[y].append(int(m.group(2)))

print(f"Total corpus files: {len(corpus_files)}")
print(f"Years in corpus: {min(corpus_years)}-{max(corpus_years)}, unique years={len(corpus_years)}")
for y in sorted(ym):
    print(f"  {y}: {len(ym[y])} months {sorted(ym[y])}")

# ---- 4. Missing source files ----
print("\n" + "="*60)
print("4. MISSING SOURCE FILES (not in corpus)")
print("="*60)

missing = []
for r in rows:
    sf = r['source_files'].strip()
    files = [fn.strip() for fn in sf.split('\n') if fn.strip()]
    for fn in files:
        if fn not in corpus_files:
            missing.append((r['uid'], fn, r['difficulty']))

missing_file_counter = Counter(fn for _, fn, _ in missing)
missing_uid_counter = Counter()
for uid, fn, diff in missing:
    missing_uid_counter[uid] = 1

print(f"Total references to missing files: {len(missing)}")
print(f"Unique questions affected: {len(missing_uid_counter)}")
print(f"Unique missing files: {len(missing_file_counter)}")
if missing_file_counter:
    print("\nMissing files (file: # questions):")
    for fname, count in missing_file_counter.most_common():
        print(f"  {fname}: {count}")
    print(f"\nDifficulty of affected questions:")
    diff_counter = Counter(d for _, _, d in missing)
    for d, c in diff_counter.most_common():
        print(f"  {d}: {c}")

# ---- 5. Large delta ----
print("\n" + "="*60)
print("5. LARGE DELTA (>5)")
print("="*60)

large = [d for d in delta_details if d['delta'] > 5]
print(f"Count: {len(large)}")
pre39 = [d for d in large if d['max_dy'] < 1939]
print(f"  data_year < 1939: {len(pre39)}")
print(f"  data_year >= 1939: {len(large) - len(pre39)}")

yc = Counter(d['max_dy'] for d in large)
print(f"\nBy data year:")
for y in sorted(yc):
    print(f"  {y}: {yc[y]}")

dc = Counter(d['difficulty'] for d in large)
print(f"\nBy difficulty: {dict(dc)}")

print(f"\nAll large-delta questions (sorted by delta desc):")
for d in sorted(large, key=lambda x: -x['delta']):
    print(f"  {d['uid']}: dy={d['data_years']}, bull={d['bulletin_year']}, delta={d['delta']:+d}, file={d['sf'][:80]}")

# ---- Negative delta ----
print("\n" + "="*60)
print("NEGATIVE DELTA (bulletin before data year)")
print("="*60)
neg = [d for d in delta_details if d['delta'] < 0]
print(f"Count: {len(neg)}")
for d in sorted(neg, key=lambda x: x['delta']):
    print(f"  {d['uid']}: dy={d['data_years']}, bull={d['bulletin_year']}, delta={d['delta']:+d}")

# ---- Window recommendations ----
print("\n" + "="*60)
print("RECOMMENDED SEARCH WINDOWS")
print("="*60)
sorted_deltas = sorted(deltas)
for pct in [50, 75, 80, 90, 95, 99, 100]:
    idx = max(0, int(len(sorted_deltas) * pct / 100) - 1)
    print(f"  {pct}th percentile: delta <= {sorted_deltas[idx]:+d}")

# Also show: what % would a window of [0, N] capture?
print(f"\nCapture rates for window [0, N]:")
for n in [1, 2, 3, 4, 5, 6, 7, 8, 10, 15, 20]:
    captured = sum(1 for d in deltas if 0 <= d <= n)
    print(f"  [0, {n}]: {captured}/{len(deltas)} ({100*captured/len(deltas):.1f}%)")

print(f"\nCapture rates for window [-1, N]:")
for n in [1, 2, 3, 4, 5, 6, 7, 8, 10, 15, 20]:
    captured = sum(1 for d in deltas if -1 <= d <= n)
    print(f"  [-1, {n}]: {captured}/{len(deltas)} ({100*captured/len(deltas):.1f}%)")

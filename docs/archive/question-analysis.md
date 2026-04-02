# OfficeQA Arena: Question Pattern Analysis

## 1. Dataset Overview

| Metric | Value |
|--------|-------|
| Total questions (full CSV) | 246 |
| Dev set questions (dev.jsonl) | 20 |
| All dev questions are "hard" difficulty | Yes |

### Difficulty Distribution (Full Dataset)

| Difficulty | Count | Percent |
|------------|-------|---------|
| Hard | 133 | 54.1% |
| Easy | 113 | 45.9% |

### Source File Distribution

| Type | Count |
|------|-------|
| Single-source (one bulletin) | 126 |
| Multi-source (2+ bulletins) | 120 |
| Multi-source & hard | 65 |
| Multi-source & easy | 55 |

---

## 2. Dev Set: Per-Question Categorization

### Category 1 -- Simple Lookup (single value from one table)
- **UID0012**: Highest spending department in FY1955 (1 source, but requires scanning a table for the max)

### Category 2 -- Multi-Step Computation (math on extracted values)
- **UID0005**: Absolute difference of 1953 vs 1940 defense spending, inflation-adjusted via CPI-U (2 sources + external CPI data)
- **UID0010**: Treasury Japanese Yen investment converted to actual yen via Macrotrends exchange rate (1 source + external FX data)
- **UID0009**: Weighted average denomination of US currency in circulation -- requires total value / total count (1 source, multi-step)
- **UID0017**: Total bids + percent noncash rollover from foreign investors for 2-year notes (1 source, multi-part)
- **UID0019**: Absolute difference in net options positions for JPY vs GBP, converted via exchange rates (1 source, multi-step)
- **UID0032**: Sum tobacco values Feb-Jun 1940 minus sum wool values same months (1 source, multi-step aggregation)
- **UID0036**: Change in US liquidity ratio between dot-com bust year and 2008 bailout year -- requires decoding historical event references (1 source, multi-step + domain knowledge)

### Category 3 -- Multi-Year / Time-Series (spans multiple years of data)
- **UID0007**: Geometric mean of monthly expenditures Mar 1942 - Oct 1948 (1 source, 79 months)
- **UID0018**: Geometric mean of monthly judiciary outlays Jan 1984 - Mar 1987 (4 sources, 39 months)
- **UID0029**: Average yield spread across all months 1960-1969 (1 source, 120 months)
- **UID0027**: Find month/year of max yield spread 1960-1969 (1 source, time-series scan)
- **UID0025**: Absolute difference in public works spending 1934 vs 1946 (2 sources)

### Category 4 -- Cross-Table (needs data from multiple tables/bulletins)
- **UID0028**: Find min yield spread month (table 1), then look up railroad retirement receipts for that month (table 2, different bulletin)
- **UID0022**: Collect annual agriculture outlays 1990-1998 from 2 bulletins, then regress + predict

### Category 5 -- Decomposition (concept requires domain knowledge to resolve)
- **UID0005**: "national defense and associated activities" -- must identify correct line items
- **UID0009**: Must determine which bureau merged with Public Debt to form Bureau of Fiscal Service (domain knowledge: Financial Management Service)
- **UID0036**: Must decode "dot-com bubble burst" -> Amazon lowest stock year (2001) and "housing bubble crash" -> bank bailout year (2008)

### Category 6 -- Regression / Statistical
- **UID0013**: OLS linear regression on income tax receipts 1929-1942, return slope + intercept
- **UID0015**: Box-Cox transformation (lambda=0.75) on net interest outlays, compute difference
- **UID0022**: Linear regression on agriculture outlays 1990-1998, predict 1999

### Category 7 -- Visual / Chart Reading
- **UID0030**: Count local maxima on line plots on a specific page (requires visual/chart interpretation)
- **UID0031**: Read from Chart TF-G when outlays exceeded receipts (visual)
- **UID0035**: Count leading digit '1' across all datapoints on a specific page (visual/counting)

### Summary Table

| Category | Dev UIDs | Count |
|----------|----------|-------|
| Simple Lookup | 0012 | 1 |
| Multi-Step Computation | 0005, 0009, 0010, 0017, 0019, 0032, 0036 | 7 |
| Multi-Year/Time-Series | 0007, 0018, 0025, 0027, 0029 | 5 |
| Cross-Table | 0022, 0028 | 2 |
| Regression/Statistical | 0013, 0015, 0022 | 3 |
| Visual/Chart Reading | 0030, 0031, 0035 | 3 |
| Decomposition/Domain Knowledge | 0005, 0009, 0036 | 3 |

Note: Several questions fall into multiple categories (e.g., UID0005 is multi-step + decomposition + cross-source; UID0022 is cross-table + regression).

---

## 3. Answer Format Patterns

### Full Dataset (246 questions)

| Format | Count | Example |
|--------|-------|---------|
| Pure number (with commas) | 196 | `2,602` or `39482.03` |
| Bracket list | 21 | `[0.096, -184.143]` |
| Percentage with % sign | 16 | `1608.80%`, `69%`, `9.89%` |
| Number + "million" suffix | 5 | `36080 million`, `1169.41 million` |
| Number + "billion" suffix | 2 | `997.3 billion` |
| Date string | 2 | `March 3, 1977`, `August 1986` |
| Dollar sign prefix | 3 | `$37,921,314`, `$2,760.44` |
| Negative with unicode minus | 2 | `-3.524`, `-156.11` |

### Key Observations on Answer Formats
1. **~80% are plain numbers** (possibly with commas as thousands separators).
2. **Bracket lists** contain 2-3 values (sometimes 12+ for time-series), comma-separated. Numbers inside may contain commas too (e.g., `[374,443, 381,327, ...]`), making parsing tricky.
3. **Rounding precision varies widely**: "nearest whole number", "nearest hundredths", "nearest thousandths", "4 decimal places", "5 significant digits".
4. **Unit suffixes are inconsistent**: some answers say "million", most don't (units are implicit from the question).
5. **Percentage answers**: some use `%` sign, some are pure decimals; question text specifies "report as a percent value" vs "report as a decimal".
6. **Unicode minus signs** (U+2212) appear in some answers rather than ASCII hyphens.

### Dev Set Answer Formats

| UID | Answer | Format |
|-----|--------|--------|
| 0005 | `39482.03` | Plain number, 2 decimals |
| 0007 | `4962.46` | Plain number, 2 decimals |
| 0009 | `32.703` | Plain number, 3 decimals |
| 0010 | `935851121560` | Large integer, no commas |
| 0012 | `36080 million` | Number + unit |
| 0013 | `[0.096, -184.143]` | Bracket list, 3 decimals |
| 0015 | `6.1596` | Plain number, 4 decimals |
| 0017 | `[10102000000, 4.73]` | Bracket list, mixed precision |
| 0018 | `81.406` | Plain number, 3 decimals |
| 0019 | `1169.41 million` | Number + unit |
| 0022 | `[273.28, 54244, 56703]` | Bracket list, mixed precision |
| 0025 | `142` | Integer |
| 0027 | `3069` | Integer (encoded month*100 + year) |
| 0028 | `92000000` | Large integer |
| 0029 | `0.88525` | Plain number, 5 sig figs |
| 0030 | `18` | Integer |
| 0031 | `1990` | Year (integer) |
| 0032 | `11.60` | Plain number, 2 decimals |
| 0035 | `104` | Integer |
| 0036 | `9.89%` | Percentage with % sign |

---

## 4. Year/Era Distribution (Full Dataset)

Questions reference years spanning 1890s-2020s. Here are the top decades by mention count in question text:

| Decade | Year Mentions |
|--------|--------------|
| 1960s | 85 |
| 1940s | 80 |
| 1970s | 77 |
| 1980s | 63 |
| 1990s | 60 |
| 2000s | 58 |
| 1950s | 54 |
| 2010s | 54 |
| 1930s | 42 |
| 2020s | 18 |
| 1920s | 2 |
| 1890s | 1 |

Top 10 most-referenced individual years:
1. 1970 (27 mentions)
2. 1939 (22)
3. 1980 (21)
4. 2010 (17)
5. 1981 (16)
6. 1960 (15)
7. 1940 (14)
8. 1948, 1990, 1969 (13 each)

Note: Round-number years (decade boundaries) are over-represented because many questions use ranges like "1960-1969".

---

## 5. Difficulty Drivers

Based on analysis, the factors that make questions "hard":

| Factor | Description |
|--------|-------------|
| Statistical transforms | Box-Cox, geometric mean, OLS regression, KL divergence, Zipf, VaR, exponential smoothing, CAGR, coefficient of variation |
| Multi-source lookups | Data from 2-4 different Treasury Bulletins |
| Long time series | Aggregating 40-120 monthly values |
| External data needed | CPI-U from Minneapolis Fed, exchange rates from Macrotrends |
| Domain knowledge | Must decode references to historical events, bureau mergers, legislative acts |
| Visual interpretation | Chart reading, counting features on plots |
| Encoded references | "the calendar year Amazon's stock reached its lowest point" instead of "2001" |

### Estimated Category Distribution (Full 246 Questions)

| Category | Estimated Count |
|----------|----------------|
| Statistical/Regression | ~51 (keyword-matched) |
| Cross-table (multi-source) | ~120 |
| Multi-year time series | ~60+ |
| Visual/Chart | ~10-15 |
| Simple lookup | ~30-40 |

---

## 6. Implications for the Solver

1. **Answer extraction must handle multiple formats**: plain numbers, bracket lists, percentages, unit suffixes, dollar signs, unicode minus signs.
2. **Statistical computation library needed**: OLS regression, geometric mean, Box-Cox, KL divergence, coefficient of variation, exponential smoothing.
3. **Multi-source retrieval is common** (~49% of questions): the system must be able to search across multiple bulletin files.
4. **Rounding precision varies per question**: must parse the rounding instruction from the question text.
5. **Historical event decoding**: some questions reference events indirectly (dot-com crash, Korean War start, COVID pandemic declaration) -- the solver needs general knowledge or a lookup table.
6. **Chart/visual questions** (~6% estimated) are likely unsolvable with text-only data; these may require OCR artifacts or accepting losses.

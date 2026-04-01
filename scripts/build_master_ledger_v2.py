#!/usr/bin/env python3
"""Build master_ledger_v2 from the full 11GB corpus DB.

Reads from `facts` table (5.8M rows with entity, metric, value, unit,
provenance) and materializes a clean, deduped, hierarchical fact store
into the slim/serving DB.

Architecture:
  11GB DB (source of truth) --> this script --> slim DB (serving artifact)

Tables created in target DB:
  - canonical_facts     : deduplicated facts with hierarchical keys
  - fact_aliases        : multiple search paths per fact
  - ledger_audit        : build stats and quality metrics

Key design decisions:
  - column_label is classified as "time" or "dimension"
  - canonical_key = entity context ONLY (no time component)
  - time columns are NOT junk — they're valid, just temporal
  - conflicts = same canonical_key + time_key + same unit + same family + different value

Usage:
    python3 scripts/build_master_ledger_v2.py \\
        --source /path/to/11gb_corpus.sqlite3 \\
        --target /path/to/slim_v2.sqlite3
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

# ── Classification ────────────────────────────────────────────────

_MONTH_NAMES = {
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
    "nov", "dec", "january", "february", "march", "april", "june", "july",
    "august", "september", "october", "november", "december", "sept",
}

_COL_N_PATTERN = re.compile(r"^col_\d+$", re.IGNORECASE)
_BARE_YEAR_PATTERN = re.compile(r"^\d{4}$")
_DATE_RL_PATTERN = re.compile(
    r"^(?:\d{4}-?)?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?$",
    re.IGNORECASE,
)
# Matches things like "1934", "1934-01", "Fiscal year 1938", "First 6 months fiscal year"
_TIME_METRIC_PATTERN = re.compile(
    r"^(?:\d{4}(?:-\d{2})?|"
    r"(?:first|last|actual|estimated|calendar|fiscal)\s+.*(?:year|month|quarter)|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*\d{0,4}|"
    r"\d{4}\s*[-–]\s*\d{4}|"  # year ranges like "1934-1938"
    r"(?:fy|cy)\s*\d{4}"
    r")$",
    re.IGNORECASE,
)


def _classify_metric_type(column_label: str) -> str:
    """Classify whether a column_label represents time or a real dimension.

    Returns "time", "dimension", or "junk".
    """
    if not column_label or len(column_label.strip()) < 2:
        return "junk"
    cl = column_label.strip()
    cl_lower = cl.lower().rstrip(".")

    # Definite junk: unnamed columns
    if _COL_N_PATTERN.match(cl_lower):
        return "junk"

    # Time indicators: bare years, months, date patterns, fiscal year phrases
    if _BARE_YEAR_PATTERN.match(cl_lower):
        return "time"
    if cl_lower in _MONTH_NAMES:
        return "time"
    if _DATE_RL_PATTERN.match(cl):
        return "time"
    if _TIME_METRIC_PATTERN.match(cl):
        return "time"

    # Everything else is a real dimension/metric
    return "dimension"


def _is_real_junk(label: str) -> bool:
    """True only for genuinely garbage labels (col_N, empty, OCR noise)."""
    if not label or len(label.strip()) < 2:
        return True
    if _COL_N_PATTERN.match(label.strip()):
        return True
    return False


# ── Normalization ─────────────────────────────────────────────────

def _normalize_slug(text: str) -> str:
    """Normalize text into a slug for matching."""
    if not text:
        return ""
    s = text.lower().strip()
    s = re.sub(r"\s*\d+/", "", s)  # footnote markers
    s = re.sub(r"[^\w\s\-]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _build_time_key(year: int | None, month: int | None) -> str | None:
    if year is None:
        return None
    if month is not None and 1 <= month <= 12:
        return f"{year}-{int(month):02d}"
    return str(year)


def _parse_bulletin_date(source_file: str) -> str:
    m = re.search(r"(\d{4})_(\d{2})", source_file or "")
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return "0000-00"


def _normalize_unit(unit_str: str) -> tuple[str, float]:
    if not unit_str:
        return ("unknown", 1.0)
    u = unit_str.lower()
    multiplier = 1.0
    if "billion" in u:
        multiplier = 1_000_000_000
    elif "million" in u:
        multiplier = 1_000_000
    elif "thousand" in u:
        multiplier = 1_000

    if "dollar" in u:
        return ("dollars", multiplier)
    elif "piece" in u:
        return ("pieces", multiplier)
    elif "percent" in u or "%" in u:
        return ("percent", 1.0)
    else:
        return ("other", multiplier)


# ── Canonical key construction ────────────────────────────────────

def _build_canonical_key(
    table_family: str,
    table_title: str,
    row_label: str,
    column_label: str,
    metric_type: str,
) -> str:
    """Build a hierarchical canonical key.

    CRITICAL: canonical_key = entity context only. Time columns are excluded.
    - If metric_type == "time": column_label is NOT part of the key
    - If metric_type == "dimension": column_label IS part of the key
    """
    parts = []

    if table_family and table_family != "other":
        parts.append(_normalize_slug(table_family))

    if table_title:
        tt = re.sub(r"^Table\s+[\w.-]+\s*[-—.]\s*", "", table_title, flags=re.IGNORECASE)
        tt = re.sub(r"\s*[-—]\s*(?:Continued|Cont\.?)\.?$", "", tt, flags=re.IGNORECASE)
        tt_norm = _normalize_slug(tt)
        if tt_norm and len(tt_norm) > 3:
            parts.append(tt_norm)

    # Row label: strip if it's purely a date/year
    if row_label:
        rl = row_label.strip()
        if not _DATE_RL_PATTERN.match(rl) and not _BARE_YEAR_PATTERN.match(rl):
            rl_norm = _normalize_slug(rl)
            if rl_norm and len(rl_norm) > 1:
                parts.append(rl_norm)

    # Column label: ONLY include if it's a dimension (not time, not junk)
    if metric_type == "dimension" and column_label:
        cl_norm = _normalize_slug(column_label)
        if cl_norm and len(cl_norm) > 1:
            parts.append(cl_norm)

    return " > ".join(parts) if parts else ""


# ── Main build ────────────────────────────────────────────────────

def build_ledger_v2(
    source_conn: sqlite3.Connection,
    target_conn: sqlite3.Connection,
) -> dict:
    audit = {
        "source_facts_read": 0,
        "dropped_null_value": 0,
        "dropped_null_year": 0,
        "dropped_junk_entity": 0,
        "dropped_junk_column": 0,
        "dropped_no_key": 0,
        "metric_type_time": 0,
        "metric_type_dimension": 0,
        "metric_type_junk": 0,
        "candidate_rows": 0,
        "canonical_facts": 0,
        "total_variants": 0,
        "max_variants_per_key": 0,
        "real_conflicts": 0,
        "aliases_created": 0,
        "build_time_s": 0,
    }

    t0 = time.time()

    # ── Load table metadata ──
    print("Loading table metadata...")
    table_meta = {}
    for row in source_conn.execute("""
        SELECT table_pk, table_title, source_file, section_path,
               table_type, data_category, table_family,
               period_basis, frequency, units_line,
               min_year, max_year
        FROM table_index
    """).fetchall():
        table_meta[row["table_pk"]] = dict(row)

    # Load dedup groups for latest-source resolution
    print("Loading dedup groups...")
    dedup_canonical = {}
    for dg in source_conn.execute(
        "SELECT table_title_norm, table_family, table_pks, bulletins FROM table_dedup_groups"
    ).fetchall():
        pks = [int(p) for p in dg["table_pks"].split(",")]
        bulletins = dg["bulletins"].split(",") if dg["bulletins"] else []
        if bulletins:
            latest = max(bulletins, key=lambda b: _parse_bulletin_date(b))
            latest_date = _parse_bulletin_date(latest)
            for pk in pks:
                meta = table_meta.get(pk)
                if meta and _parse_bulletin_date(meta["source_file"]) == latest_date:
                    dedup_canonical[pk] = True
                elif pk not in dedup_canonical:
                    dedup_canonical[pk] = False

    # ── Create target tables ──
    print("Creating target tables...")
    target_conn.execute("DROP TABLE IF EXISTS canonical_facts")
    target_conn.execute("""
        CREATE TABLE canonical_facts (
            fact_pk INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_key TEXT NOT NULL,
            entity_key TEXT NOT NULL,
            metric_key TEXT NOT NULL,
            metric_type TEXT NOT NULL,
            time_key TEXT NOT NULL,
            year INTEGER,
            month INTEGER,
            value REAL NOT NULL,
            unit_type TEXT,
            unit_multiplier REAL DEFAULT 1.0,
            unit_raw TEXT,
            table_title TEXT,
            table_family TEXT,
            section_path TEXT,
            row_label TEXT,
            column_label TEXT,
            period_basis TEXT,
            frequency TEXT,
            source_file TEXT,
            source_table_pk INTEGER,
            bulletin_date TEXT,
            confidence REAL,
            is_canonical INTEGER DEFAULT 1,
            variant_count INTEGER DEFAULT 1
        )
    """)

    target_conn.execute("DROP TABLE IF EXISTS fact_aliases")
    target_conn.execute("""
        CREATE TABLE fact_aliases (
            alias_pk INTEGER PRIMARY KEY AUTOINCREMENT,
            fact_pk INTEGER NOT NULL,
            alias_type TEXT NOT NULL,
            alias_text TEXT NOT NULL,
            alias_norm TEXT NOT NULL,
            FOREIGN KEY (fact_pk) REFERENCES canonical_facts(fact_pk)
        )
    """)

    target_conn.execute("DROP TABLE IF EXISTS ledger_audit")
    target_conn.execute("""
        CREATE TABLE ledger_audit (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # ── Stream facts ──
    print("Reading facts from source DB...")
    candidates: dict[tuple[str, str], list[dict]] = defaultdict(list)

    cursor = source_conn.execute("""
        SELECT f.entity, f.metric, f.year, f.month, f.value, f.unit,
               f.table_pk, f.row_label, f.column_label, f.source_file,
               f.row_ordinal, f.column_ordinal
        FROM facts f
        WHERE f.value IS NOT NULL
    """)

    batch_count = 0
    for row in cursor:
        audit["source_facts_read"] += 1
        batch_count += 1

        if batch_count % 500_000 == 0:
            print(f"  ... {batch_count:,} facts read, {len(candidates):,} candidate keys")

        entity = row["entity"] or ""
        year = row["year"]
        value = row["value"]
        table_pk = row["table_pk"]
        source_file = row["source_file"] or ""

        if value is None:
            audit["dropped_null_value"] += 1
            continue
        if year is None:
            # ── Attempt to recover year from context ──
            meta_tmp = table_meta.get(table_pk, {})
            min_yr = meta_tmp.get("min_year")
            max_yr = meta_tmp.get("max_year")
            if min_yr is not None and max_yr is not None and min_yr == max_yr:
                # Table covers exactly one year — safe to infer
                year = min_yr
                audit.setdefault("recovered_year_from_table", 0)
                audit["recovered_year_from_table"] += 1
            else:
                # Infer from bulletin date (year before publication)
                bd = _parse_bulletin_date(source_file)
                if bd and bd != "0000-00":
                    bd_year = int(bd.split("-")[0])
                    bd_month = int(bd.split("-")[1])
                    # Bulletins typically report on the previous year's data
                    # if published in Q1, or current year if published later
                    inferred = bd_year - 1 if bd_month <= 3 else bd_year
                    # Only use if it falls within the table's year range
                    if (min_yr is not None and max_yr is not None
                            and min_yr <= inferred <= max_yr):
                        year = inferred
                        audit.setdefault("recovered_year_from_bulletin", 0)
                        audit["recovered_year_from_bulletin"] += 1
                    else:
                        audit["dropped_null_year"] += 1
                        continue
                else:
                    audit["dropped_null_year"] += 1
                    continue
        if len(entity.strip()) < 3:
            audit["dropped_junk_entity"] += 1
            continue

        meta = table_meta.get(table_pk, {})
        table_title = meta.get("table_title", "")
        table_family = meta.get("table_family", "other")
        section_path = meta.get("section_path", "")

        rl = row["row_label"] or ""
        cl = row["column_label"] or ""

        # CORE FIX: classify the column
        metric_type = _classify_metric_type(cl)
        audit[f"metric_type_{metric_type}"] += 1

        # Drop only real junk (col_N, empty)
        if metric_type == "junk":
            audit["dropped_junk_column"] += 1
            continue

        # Build canonical key — time columns excluded
        canonical_key = _build_canonical_key(
            table_family, table_title, rl, cl, metric_type
        )
        if not canonical_key:
            audit["dropped_no_key"] += 1
            continue

        time_key = _build_time_key(year, row["month"])
        if not time_key:
            audit["dropped_null_year"] += 1
            continue

        bulletin_date = _parse_bulletin_date(source_file)
        unit_type, unit_mult = _normalize_unit(meta.get("units_line", ""))

        # metric_key: real metric for dimension columns, "value" for time columns
        if metric_type == "dimension":
            metric_key = _normalize_slug(cl)
        else:
            metric_key = "value"

        candidates[(canonical_key, time_key)].append({
            "value": value,
            "rl": rl,
            "cl": cl,
            "metric_type": metric_type,
            "metric_key": metric_key,
            "table_pk": table_pk,
            "source_file": source_file,
            "bulletin_date": bulletin_date,
            "table_title": table_title,
            "table_family": table_family,
            "section_path": section_path,
            "period_basis": meta.get("period_basis", ""),
            "frequency": meta.get("frequency", ""),
            "unit_type": unit_type,
            "unit_multiplier": unit_mult,
            "unit_raw": meta.get("units_line", ""),
            "entity": entity,
            "year": year,
            "month": row["month"],
            "is_latest_bulletin": dedup_canonical.get(table_pk, True),
        })

    print(f"  Total facts read: {audit['source_facts_read']:,}")
    print(f"  Candidate keys: {len(candidates):,}")
    print(f"  Metric types: time={audit['metric_type_time']:,} dimension={audit['metric_type_dimension']:,} junk={audit['metric_type_junk']:,}")

    # ── Dedup ──
    print("Deduplicating...")
    audit["candidate_rows"] = sum(len(v) for v in candidates.values())

    fact_rows = []
    alias_rows = []

    for (canonical_key, time_key), variants in candidates.items():
        audit["total_variants"] += len(variants)
        if len(variants) > audit["max_variants_per_key"]:
            audit["max_variants_per_key"] = len(variants)

        # Real conflict: same canonical_key + time_key + same unit_type + same family + different values
        by_context: dict[tuple[str, str], set[float]] = defaultdict(set)
        for v in variants:
            ctx = (v["unit_type"], v["table_family"])
            by_context[ctx].add(round(v["value"], 4))
        real_conflicts = sum(1 for vals in by_context.values() if len(vals) > 1)
        if real_conflicts > 0:
            audit["real_conflicts"] += 1

        # Pick canonical: latest bulletin wins
        best = max(variants, key=lambda v: (
            v["is_latest_bulletin"],
            v["bulletin_date"],
        ))

        fact_idx = len(fact_rows)
        fact_rows.append((
            canonical_key,
            _normalize_slug(best["entity"]),
            best["metric_key"],
            best["metric_type"],
            time_key,
            best["year"],
            best["month"],
            best["value"],
            best["unit_type"],
            best["unit_multiplier"],
            best["unit_raw"],
            best["table_title"],
            best["table_family"],
            best["section_path"],
            best["rl"],
            best["cl"],
            best["period_basis"],
            best["frequency"],
            best["source_file"],
            best["table_pk"],
            best["bulletin_date"],
            0.9,
            1,
            len(variants),
        ))

        # Aliases
        seen_aliases = set()

        def _add_alias(atype: str, text: str):
            norm = _normalize_slug(text)
            if norm and (atype, norm) not in seen_aliases:
                seen_aliases.add((atype, norm))
                alias_rows.append((fact_idx, atype, text.strip(), norm))

        _add_alias("entity", best["entity"])
        if best["table_title"]:
            _add_alias("table_title", best["table_title"])
        if best["section_path"]:
            _add_alias("section_path", best["section_path"])
        # Row label: real metric in many cases
        if best["rl"] and not _DATE_RL_PATTERN.match(best["rl"]) and not _BARE_YEAR_PATTERN.match(best["rl"]):
            _add_alias("row_label", best["rl"])
        # Column label: only if it's a dimension
        if best["metric_type"] == "dimension" and best["cl"]:
            _add_alias("column_label", best["cl"])
        # Combined for compound searches
        if best["rl"] and best["cl"] and best["metric_type"] == "dimension":
            _add_alias("combined", f"{best['rl']} {best['cl']}")

    audit["canonical_facts"] = len(fact_rows)
    audit["aliases_created"] = len(alias_rows)

    # ── Write ──
    print(f"Writing {len(fact_rows):,} canonical facts...")
    BATCH = 10000
    for i in range(0, len(fact_rows), BATCH):
        batch = fact_rows[i : i + BATCH]
        target_conn.executemany("""
            INSERT INTO canonical_facts (
                canonical_key, entity_key, metric_key, metric_type, time_key,
                year, month, value,
                unit_type, unit_multiplier, unit_raw,
                table_title, table_family, section_path,
                row_label, column_label, period_basis, frequency,
                source_file, source_table_pk, bulletin_date,
                confidence, is_canonical, variant_count
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, batch)
        if (i + BATCH) % 100000 < BATCH:
            target_conn.commit()
            print(f"  ... {min(i + BATCH, len(fact_rows)):,}/{len(fact_rows):,}")

    target_conn.commit()

    # Write aliases
    print(f"Writing {len(alias_rows):,} aliases...")
    pk_map = {}
    for row in target_conn.execute("SELECT fact_pk FROM canonical_facts ORDER BY fact_pk"):
        pk_map[len(pk_map)] = row[0]

    alias_batch = []
    for fact_idx, atype, atext, anorm in alias_rows:
        real_pk = pk_map.get(fact_idx)
        if real_pk is not None:
            alias_batch.append((real_pk, atype, atext, anorm))
        if len(alias_batch) >= BATCH:
            target_conn.executemany(
                "INSERT INTO fact_aliases (fact_pk, alias_type, alias_text, alias_norm) VALUES (?,?,?,?)",
                alias_batch,
            )
            alias_batch.clear()
    if alias_batch:
        target_conn.executemany(
            "INSERT INTO fact_aliases (fact_pk, alias_type, alias_text, alias_norm) VALUES (?,?,?,?)",
            alias_batch,
        )
    target_conn.commit()

    # ── Indexes ──
    print("Building indexes...")
    target_conn.execute("CREATE INDEX idx_cf_canonical ON canonical_facts(canonical_key)")
    target_conn.execute("CREATE INDEX idx_cf_entity ON canonical_facts(entity_key)")
    target_conn.execute("CREATE INDEX idx_cf_metric ON canonical_facts(metric_key)")
    target_conn.execute("CREATE INDEX idx_cf_time ON canonical_facts(time_key)")
    target_conn.execute("CREATE INDEX idx_cf_year ON canonical_facts(year)")
    target_conn.execute("CREATE INDEX idx_cf_family ON canonical_facts(table_family)")
    target_conn.execute("CREATE INDEX idx_cf_entity_time ON canonical_facts(entity_key, time_key)")
    target_conn.execute("CREATE INDEX idx_cf_canonical_time ON canonical_facts(canonical_key, time_key)")
    target_conn.execute("CREATE INDEX idx_cf_metric_type ON canonical_facts(metric_type)")

    target_conn.execute("CREATE INDEX idx_fa_norm ON fact_aliases(alias_norm)")
    target_conn.execute("CREATE INDEX idx_fa_type ON fact_aliases(alias_type)")
    target_conn.execute("CREATE INDEX idx_fa_pk ON fact_aliases(fact_pk)")
    target_conn.commit()

    audit["build_time_s"] = round(time.time() - t0, 1)

    # ── Audit stats ──
    print("\nComputing audit stats...")
    for k, v in audit.items():
        target_conn.execute(
            "INSERT OR REPLACE INTO ledger_audit (key, value) VALUES (?, ?)",
            (k, str(v)),
        )

    # Real junk rate: only col_N and empty/short labels
    junk_check = target_conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN metric_key LIKE 'col_%' THEN 1 ELSE 0 END) as col_n,
            SUM(CASE WHEN length(metric_key) < 2 THEN 1 ELSE 0 END) as short
        FROM canonical_facts
    """).fetchone()
    total = junk_check[0] or 1
    real_junk = (junk_check[1] or 0) + (junk_check[2] or 0)
    target_conn.execute(
        "INSERT OR REPLACE INTO ledger_audit VALUES (?, ?)",
        ("real_junk_rate", f"{real_junk}/{total} ({100*real_junk/total:.2f}%)"),
    )

    # Metric type distribution
    mt_dist = target_conn.execute("""
        SELECT metric_type, COUNT(*) FROM canonical_facts GROUP BY metric_type
    """).fetchall()
    for row in mt_dist:
        target_conn.execute(
            "INSERT OR REPLACE INTO ledger_audit VALUES (?, ?)",
            (f"metric_type_{row[0]}", f"{row[1]:,}"),
        )

    # Variant distribution
    variant_dist = target_conn.execute("""
        SELECT
            SUM(CASE WHEN variant_count = 1 THEN 1 ELSE 0 END),
            SUM(CASE WHEN variant_count BETWEEN 2 AND 5 THEN 1 ELSE 0 END),
            SUM(CASE WHEN variant_count BETWEEN 6 AND 20 THEN 1 ELSE 0 END),
            SUM(CASE WHEN variant_count > 20 THEN 1 ELSE 0 END)
        FROM canonical_facts
    """).fetchone()
    target_conn.execute(
        "INSERT OR REPLACE INTO ledger_audit VALUES (?, ?)",
        ("variant_distribution",
         f"unique={variant_dist[0]:,} low(2-5)={variant_dist[1]:,} "
         f"med(6-20)={variant_dist[2]:,} high(>20)={variant_dist[3]:,}"),
    )

    target_conn.commit()
    return audit


def main():
    parser = argparse.ArgumentParser(description="Build master_ledger_v2 from 11GB corpus")
    parser.add_argument(
        "--source",
        default=str(Path.home() / "projects/archive/officeqa-legacy/external/officeqa/treasury_bulletins_parsed/officeqa_corpus.sqlite3"),
    )
    parser.add_argument("--target", default="/tmp/officeqa_slim_v2.sqlite3")
    args = parser.parse_args()

    if not Path(args.source).exists():
        print(f"ERROR: Source DB not found at {args.source}")
        sys.exit(1)
    if not Path(args.target).exists():
        print(f"ERROR: Target DB not found at {args.target}")
        sys.exit(1)

    source_conn = sqlite3.connect(f"file:{args.source}?mode=ro", uri=True)
    source_conn.row_factory = sqlite3.Row
    target_conn = sqlite3.connect(args.target)
    target_conn.row_factory = sqlite3.Row

    print(f"Source: {args.source}")
    print(f"Target: {args.target}\n")

    audit = build_ledger_v2(source_conn, target_conn)

    source_conn.close()
    target_conn.close()

    print("\n" + "=" * 60)
    print("BUILD AUDIT REPORT")
    print("=" * 60)
    print(f"\n  {'Source facts read':>30s}: {audit['source_facts_read']:>12,}")
    print(f"  {'Dropped (null year)':>30s}: {audit['dropped_null_year']:>12,}")
    print(f"  {'Dropped (junk entity)':>30s}: {audit['dropped_junk_entity']:>12,}")
    print(f"  {'Dropped (junk column)':>30s}: {audit['dropped_junk_column']:>12,}")
    print(f"  {'Dropped (no canonical key)':>30s}: {audit['dropped_no_key']:>12,}")
    print(f"\n  {'Metric type: time':>30s}: {audit['metric_type_time']:>12,}")
    print(f"  {'Metric type: dimension':>30s}: {audit['metric_type_dimension']:>12,}")
    print(f"  {'Metric type: junk (dropped)':>30s}: {audit['metric_type_junk']:>12,}")
    print(f"\n  {'Candidate rows':>30s}: {audit['candidate_rows']:>12,}")
    print(f"  {'Canonical facts':>30s}: {audit['canonical_facts']:>12,}")
    compression = audit['candidate_rows'] / max(audit['canonical_facts'], 1)
    print(f"  {'Compression ratio':>30s}: {compression:>12.1f}x")
    print(f"  {'Max variants per key':>30s}: {audit['max_variants_per_key']:>12,}")
    print(f"  {'Real conflicts':>30s}: {audit['real_conflicts']:>12,}")
    print(f"  {'(same key+time+unit+family)':>30s}")
    print(f"\n  {'Canonical facts written':>30s}: {audit['canonical_facts']:>12,}")
    print(f"  {'Aliases created':>30s}: {audit['aliases_created']:>12,}")
    print(f"  {'Build time':>30s}: {audit['build_time_s']:>12.1f}s")
    print("=" * 60)


if __name__ == "__main__":
    main()

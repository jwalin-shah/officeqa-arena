#!/usr/bin/env python3
"""Analyze MCP telemetry from live runs to understand tool usage patterns,
session outcomes, and failure modes."""

import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

TELEMETRY_PATH = "results/telemetry_live_latest.jsonl"
SAMPLES_DIR = ".arena/samples"

# Tools whose args contain search-like queries
SEARCH_TOOLS = {
    "search_canonical", "search_tables", "extract_values",
    "search_ledger", "grep_corpus", "get_time_series",
    "get_multi_year_series",
}

# Tools that indicate answer submission
SUBMIT_TOOLS = {"submit_answer"}


def load_telemetry(path):
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def load_sample_questions(samples_dir):
    """Load question text from each sample's instruction.md."""
    questions = {}
    if not os.path.isdir(samples_dir):
        return questions
    for entry in sorted(os.listdir(samples_dir)):
        inst_path = os.path.join(samples_dir, entry, "instruction.md")
        if os.path.isfile(inst_path):
            with open(inst_path) as f:
                text = f.read()
            # The question is typically the first paragraph before "## Available Resources"
            parts = text.split("## Available Resources")
            q_text = parts[0].strip() if parts else text.strip()
            questions[entry] = q_text
    return questions


def segment_sessions(events):
    """Split events into sessions using mcp_started as boundary."""
    sessions = []
    current = []
    for ev in events:
        if ev.get("event") == "test":
            continue
        if ev.get("event") == "mcp_started":
            if current:
                sessions.append(current)
            current = [ev]
        else:
            current.append(ev)
    if current:
        sessions.append(current)
    return sessions


def extract_years_from_args(args):
    """Pull year-like numbers from tool args."""
    years = set()
    if not args:
        return years
    for key, val in args.items():
        s = str(val)
        for m in re.findall(r'\b(1[89]\d{2}|20[0-2]\d)\b', s):
            years.add(int(m))
    return years


def extract_queries_from_args(args):
    """Pull query/search strings from tool args."""
    queries = []
    if not args:
        return queries
    for key in ("query", "metric", "pattern"):
        if key in args and args[key]:
            queries.append(str(args[key]))
    return queries


def analyze_session(session_events):
    """Analyze a single session and return a summary dict."""
    info = {
        "tool_calls": [],
        "tool_counts": Counter(),
        "queries": [],
        "years": set(),
        "answers": [],
        "auto_submits": [],
        "submit_answers": [],
        "errors": [],
        "empty_search_canonical": 0,
        "search_ledger_errors": 0,
        "extract_values_errors": 0,
        "budget_warnings": 0,
        "ts_start": None,
        "ts_end": None,
    }

    for ev in session_events:
        ts = ev.get("ts")
        if ts:
            if info["ts_start"] is None:
                info["ts_start"] = ts
            info["ts_end"] = ts

        event_type = ev.get("event")

        if event_type == "tool_call":
            tool = ev.get("tool", "")
            args = ev.get("args", {})
            is_error = ev.get("is_error", False)
            preview = ev.get("result_preview", "")

            info["tool_calls"].append(tool)
            info["tool_counts"][tool] += 1

            # Extract queries
            if tool in SEARCH_TOOLS:
                info["queries"].extend(extract_queries_from_args(args))

            # Extract years
            info["years"].update(extract_years_from_args(args))

            # Check for errors
            if is_error:
                info["errors"].append(f"{tool}: {preview[:120]}")
                if tool == "search_ledger":
                    info["search_ledger_errors"] += 1
                if tool == "extract_values":
                    info["extract_values_errors"] += 1

            # Check for empty search_canonical
            if tool == "search_canonical" and not is_error:
                if '"count": 0' in preview or '"results": []' in preview:
                    info["empty_search_canonical"] += 1

            # Budget exceeded warnings
            if "budget_exceeded" in preview:
                info["budget_warnings"] += 1

            # Submit answer
            if tool == "submit_answer":
                answer = args.get("answer", "")
                info["submit_answers"].append(answer)

        elif event_type == "auto_submit":
            info["auto_submits"].append({
                "answer": ev.get("answer", ""),
                "reason": ev.get("reason", ""),
            })

    return info


def infer_topic(queries, years):
    """Combine search queries and years into a topic string."""
    if not queries:
        return "(no queries)"
    # Deduplicate while preserving rough order
    seen = set()
    unique = []
    for q in queries:
        ql = q.lower().strip()
        if ql not in seen:
            seen.add(ql)
            unique.append(q.strip())
    topic = "; ".join(unique[:4])  # cap at 4 queries
    if len(unique) > 4:
        topic += f" (+{len(unique)-4} more)"
    if years:
        topic += f" [{','.join(str(y) for y in sorted(years))}]"
    return topic


def tokenize(text):
    """Simple word tokenizer for fuzzy matching."""
    return set(re.findall(r'[a-z]+', text.lower()))


def match_to_samples(session_info, sample_questions):
    """Try to fuzzy-match a session to a known sample question."""
    if not sample_questions:
        return None, 0.0

    # Build a token set from session queries + years
    session_text = " ".join(session_info["queries"])
    for y in session_info["years"]:
        session_text += f" {y}"
    session_tokens = tokenize(session_text)

    if not session_tokens:
        return None, 0.0

    best_uid = None
    best_score = 0.0

    for uid, q_text in sample_questions.items():
        q_tokens = tokenize(q_text)
        if not q_tokens:
            continue
        overlap = len(session_tokens & q_tokens)
        # Jaccard-like but weight toward question coverage
        score = overlap / max(len(q_tokens), 1)
        if score > best_score:
            best_score = score
            best_uid = uid

    if best_score >= 0.15:  # low threshold since queries are fragments
        return best_uid, best_score
    return None, 0.0


def classify_outcome(info):
    """Determine whether session succeeded, failed, and why."""
    has_submit = len(info["submit_answers"]) > 0
    has_auto = len(info["auto_submits"]) > 0
    final_answer = None

    if has_submit:
        final_answer = info["submit_answers"][-1]
    elif has_auto:
        final_answer = info["auto_submits"][-1]["answer"]

    reasons = []
    if info["search_ledger_errors"] > 0:
        reasons.append("search_ledger_broken")
    if info["extract_values_errors"] > 0:
        reasons.append("extract_values_broken")
    if info["empty_search_canonical"] > 0:
        reasons.append(f"canonical_empty_x{info['empty_search_canonical']}")
    if info["budget_warnings"] > 0:
        reasons.append("budget_exceeded")
    if has_auto:
        for a in info["auto_submits"]:
            if a["reason"]:
                reasons.append(f"auto:{a['reason']}")
    if not has_submit and not has_auto:
        reasons.append("no_answer")

    total_calls = len(info["tool_calls"])
    search_calls = sum(1 for t in info["tool_calls"] if t in SEARCH_TOOLS)
    waste_ratio = search_calls / max(total_calls, 1)

    return {
        "has_answer": has_submit or has_auto,
        "final_answer": final_answer,
        "method": "submit" if has_submit else ("auto" if has_auto else "none"),
        "reasons": reasons,
        "total_calls": total_calls,
        "search_calls": search_calls,
        "waste_ratio": waste_ratio,
    }


def format_table(rows, headers):
    """Format a simple ASCII table."""
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))

    sep = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"
    header_line = "|" + "|".join(f" {h:<{col_widths[i]}} " for i, h in enumerate(headers)) + "|"

    lines = [sep, header_line, sep]
    for row in rows:
        line = "|" + "|".join(f" {str(c):<{col_widths[i]}} " for i, c in enumerate(row)) + "|"
        lines.append(line)
    lines.append(sep)
    return "\n".join(lines)


def main():
    base = Path(__file__).resolve().parent.parent
    telemetry_path = base / TELEMETRY_PATH
    samples_dir = base / SAMPLES_DIR

    # Load data
    events = load_telemetry(telemetry_path)
    print(f"Loaded {len(events)} events from {telemetry_path}")

    sample_questions = load_sample_questions(samples_dir)
    print(f"Loaded {len(sample_questions)} sample questions\n")

    # Segment into sessions
    sessions = segment_sessions(events)
    print(f"Found {len(sessions)} sessions (mcp_started boundaries)\n")

    # Analyze each session
    results = []
    for i, sess_events in enumerate(sessions):
        info = analyze_session(sess_events)
        outcome = classify_outcome(info)
        topic = infer_topic(info["queries"], info["years"])
        matched_uid, match_score = match_to_samples(info, sample_questions)

        results.append({
            "session": i + 1,
            "info": info,
            "outcome": outcome,
            "topic": topic,
            "matched_uid": matched_uid,
            "match_score": match_score,
        })

    # ---- Session Summary Table ----
    print("=" * 120)
    print("SESSION SUMMARY")
    print("=" * 120)

    rows = []
    for r in results:
        o = r["outcome"]
        info = r["info"]
        tool_summary = ", ".join(f"{t}:{c}" for t, c in info["tool_counts"].most_common(5))
        reason_str = "; ".join(o["reasons"][:3]) if o["reasons"] else "ok"
        uid_str = r["matched_uid"] or "-"
        if r["match_score"] > 0:
            uid_str += f" ({r['match_score']:.0%})"
        answer_str = str(o["final_answer"])[:20] if o["final_answer"] else "-"
        topic_str = r["topic"][:70]

        rows.append([
            r["session"],
            topic_str,
            uid_str,
            tool_summary[:50],
            o["total_calls"],
            answer_str,
            o["method"],
            reason_str[:40],
        ])

    headers = ["#", "Topic (inferred)", "Match", "Top Tools", "Calls", "Answer", "How", "Issues"]
    print(format_table(rows, headers))

    # ---- Aggregate Stats ----
    print("\n" + "=" * 120)
    print("AGGREGATE STATISTICS")
    print("=" * 120)

    total_sessions = len(results)
    with_answer = sum(1 for r in results if r["outcome"]["has_answer"])
    without_answer = total_sessions - with_answer
    submit_count = sum(1 for r in results if r["outcome"]["method"] == "submit")
    auto_count = sum(1 for r in results if r["outcome"]["method"] == "auto")

    print(f"\nSessions total:         {total_sessions}")
    print(f"  With answer:          {with_answer} ({with_answer/max(total_sessions,1)*100:.0f}%)")
    print(f"    via submit_answer:  {submit_count}")
    print(f"    via auto_submit:    {auto_count}")
    print(f"  Without answer:       {without_answer}")

    # Matched to samples
    matched = sum(1 for r in results if r["matched_uid"])
    print(f"\nMatched to samples:     {matched}/{total_sessions}")

    # Failure reasons
    print("\n--- Failure / Warning Reasons ---")
    reason_counts = Counter()
    for r in results:
        for reason in r["outcome"]["reasons"]:
            reason_counts[reason] += 1
    for reason, count in reason_counts.most_common():
        print(f"  {reason:<40} {count}")

    # Tool waste stats
    print("\n--- Tool Usage Stats ---")
    total_tool_calls = sum(r["outcome"]["total_calls"] for r in results)
    total_search_calls = sum(r["outcome"]["search_calls"] for r in results)
    total_errors = sum(len(r["info"]["errors"]) for r in results)
    total_empty_canonical = sum(r["info"]["empty_search_canonical"] for r in results)
    total_budget_warnings = sum(r["info"]["budget_warnings"] for r in results)

    print(f"  Total tool calls:               {total_tool_calls}")
    print(f"  Search-type calls:              {total_search_calls} ({total_search_calls/max(total_tool_calls,1)*100:.0f}%)")
    print(f"  Error calls:                    {total_errors}")
    print(f"  Empty search_canonical results: {total_empty_canonical}")
    print(f"  Budget exceeded warnings:       {total_budget_warnings}")

    avg_calls = total_tool_calls / max(total_sessions, 1)
    print(f"  Avg calls per session:          {avg_calls:.1f}")

    # Per-tool frequency
    print("\n--- Tool Frequency (all sessions) ---")
    tool_freq = Counter()
    tool_errors = Counter()
    for r in results:
        for t, c in r["info"]["tool_counts"].items():
            tool_freq[t] += c
        for err in r["info"]["errors"]:
            tool_name = err.split(":")[0]
            tool_errors[tool_name] += 1

    for tool, count in tool_freq.most_common():
        err_ct = tool_errors.get(tool, 0)
        err_str = f" ({err_ct} errors)" if err_ct else ""
        print(f"  {tool:<30} {count:>4}{err_str}")

    # Sessions that burned through budget without answering
    wasted = [r for r in results if not r["outcome"]["has_answer"]]
    if wasted:
        print(f"\n--- Sessions with NO answer ({len(wasted)}) ---")
        for r in wasted:
            print(f"  Session {r['session']}: {r['topic'][:80]}")
            print(f"    Calls: {r['outcome']['total_calls']}, "
                  f"Searches: {r['outcome']['search_calls']}, "
                  f"Issues: {'; '.join(r['outcome']['reasons'])}")

    # Sessions with multiple submit_answers (revised answers)
    revised = [r for r in results if len(r["info"]["submit_answers"]) > 1]
    if revised:
        print(f"\n--- Sessions with revised answers ({len(revised)}) ---")
        for r in revised:
            answers = r["info"]["submit_answers"]
            print(f"  Session {r['session']}: answers={answers}")

    print()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import json
import sys
import re
from pathlib import Path
from collections import defaultdict

traces_dir = Path("/Users/jwalinshah/projects/officeqa-arena/results/traces/latest/")

uids = [
    "officeqa-uid0012", "officeqa-uid0018", "officeqa-uid0029", "officeqa-uid0030", "officeqa-uid0032",
    "officeqa-uid0036", "officeqa-uid0037", "officeqa-uid0044", "officeqa-uid0057", "officeqa-uid0062",
    "officeqa-uid0069", "officeqa-uid0073", "officeqa-uid0077", "officeqa-uid0083", "officeqa-uid0084"
]

failure_categories = defaultdict(int)
results = []

for uid in uids:
    filepath = traces_dir / f"{uid}.json"
    if not filepath.exists():
        print(f"SKIP {uid}: file not found")
        continue

    try:
        with open(filepath) as f:
            trace = json.load(f)

        # Get trajectory steps
        trajectory = trace.get("trajectory", {})
        steps = trajectory.get("steps", [])

        if not steps:
            print(f"SKIP {uid}: no steps")
            continue

        # First step contains the raw message text
        first_step = steps[0]
        message_str = first_step.get("message", "")
        tool_calls = first_step.get("tool_calls") or []

        # Extract question from message (usually in thinking or context)
        question = None
        if "asking about" in message_str:
            match = re.search(r"asking about (.{0,100}?)[.\n]", message_str, re.IGNORECASE)
            if match:
                question = match.group(1)
        if not question and "is asking" in message_str:
            match = re.search(r"is asking (?:for |about |)?(.{0,100}?)[.\n]", message_str, re.IGNORECASE)
            if match:
                question = match.group(1)

        # Extract final answer - look for the assistant's final response
        final_answer = None
        # Find the last text content block
        if '"type":"text","text":"' in message_str:
            matches = re.findall(r'"type":"text","text":"([^"]{1,200})', message_str)
            if matches:
                final_answer = matches[-1]

        # Analyze root cause
        root_cause = "unknown"
        if not tool_calls:
            root_cause = "no_tool_calls"
            failure_categories["no_tool_calls"] += 1
        elif len(tool_calls) < 2:
            root_cause = "insufficient_search"
            failure_categories["insufficient_search"] += 1
        else:
            # Check for specific error patterns
            if "unable" in message_str.lower() or "cannot" in message_str.lower():
                root_cause = "tool_failure"
                failure_categories["tool_failure"] += 1
            elif "error" in message_str.lower():
                root_cause = "execution_error"
                failure_categories["execution_error"] += 1
            else:
                root_cause = "wrong_answer"
                failure_categories["wrong_answer"] += 1

        # Extract better question if available
        if not question:
            # Try to extract from thinking block
            thinking_match = re.search(r'"thinking":"([^"]{0,100})', message_str)
            if thinking_match:
                text = thinking_match.group(1)
                if "asking" in text.lower():
                    question = text[:60]

        summary = f"{uid}: Q=[{question if question else 'N/A'}] | Tools={len(tool_calls)} | Root={root_cause}"
        results.append((uid, question, len(tool_calls), root_cause, final_answer))
        print(summary)

    except Exception as e:
        print(f"ERROR {uid}: {e}")
        import traceback
        traceback.print_exc()

print("\n" + "="*80)
print("DETAILED RESULTS")
print("="*80)
for uid, question, tool_count, root_cause, answer in results:
    print(f"\n{uid}:")
    print(f"  Root Cause: {root_cause}")
    print(f"  Tool Calls: {tool_count}")
    if question:
        print(f"  Question: {question}")
    if answer:
        print(f"  Answer: {answer[:100]}")

print("\n" + "="*80)
print("FAILURE CATEGORIES")
print("="*80)
for cat, count in sorted(failure_categories.items(), key=lambda x: -x[1]):
    pct = (count / len(results)) * 100 if results else 0
    print(f"{cat}: {count} ({pct:.1f}%)")

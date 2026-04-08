#!/usr/bin/env python3
import json
from pathlib import Path
import re

traces_dir = Path("/Users/jwalinshah/projects/officeqa-arena/results/traces/latest/")

uids = [
    "officeqa-uid0012", "officeqa-uid0018", "officeqa-uid0029", "officeqa-uid0030", "officeqa-uid0032",
    "officeqa-uid0036", "officeqa-uid0037", "officeqa-uid0044", "officeqa-uid0057", "officeqa-uid0062",
    "officeqa-uid0069", "officeqa-uid0073", "officeqa-uid0077", "officeqa-uid0083", "officeqa-uid0084"
]

results = {}

for uid in uids:
    filepath = traces_dir / f"{uid}.json"
    with open(filepath) as f:
        trace = json.load(f)

    steps = trace.get("trajectory", {}).get("steps", [])
    if not steps:
        continue

    first_step = steps[0]
    message_str = first_step.get("message", "")
    tool_calls = first_step.get("tool_calls") or []

    # Extract thinking
    thinking_match = re.search(r'"thinking":"([^"]*(?:[\\"][^"]*)*)"', message_str)
    thinking = thinking_match.group(1) if thinking_match else ""

    # Extract the question from thinking
    question = None
    if "asking about" in thinking:
        match = re.search(r"asking (?:about|for) ([^.\n]{1,150})", thinking)
        if match:
            question = match.group(1)

    # Get last 3-5 text blocks to see final answer
    text_blocks = re.findall(r'"type":"text","text":"([^"]{1,500})', message_str)

    # Check if tool calls exist
    used_tools = len(tool_calls) if tool_calls else 0

    # Analyze the final text blocks for errors
    final_answer = text_blocks[-1][:300] if text_blocks else ""

    # Detect root cause
    root_cause = "hallucination"  # default - no tool calls

    # Check message for specific clues
    if "I don't have" in message_str:
        root_cause = "claimed_no_access"
    elif "Unable to" in message_str:
        root_cause = "unable_to_process"
    elif "error" in message_str.lower() and used_tools > 0:
        root_cause = "tool_error"
    elif "NO MATCH" in message_str or "Pattern" in message_str:
        root_cause = "regex_parsing_failure"
    elif "hallucinate" in message_str.lower() or "I apologize" in message_str:
        root_cause = "acknowledged_hallucination"

    results[uid] = {
        "question": question,
        "tool_calls": used_tools,
        "final_answer": final_answer,
        "root_cause": root_cause,
        "thinking": thinking[:200] if thinking else ""
    }

# Print results
print("="*100)
print("DETAILED ANALYSIS OF 15 ALWAYS-FAILING TRACES")
print("="*100)

for uid in uids:
    r = results[uid]
    print(f"\n{uid}")
    print(f"  ROOT CAUSE: {r['root_cause']}")
    print(f"  Question: {r['question'] if r['question'] else 'N/A'}")
    print(f"  Tool Calls: {r['tool_calls']}")
    print(f"  Final Answer: {r['final_answer'][:100]}...")
    print(f"  Thinking: {r['thinking']}")

# Summary by root cause
print("\n" + "="*100)
print("ROOT CAUSE SUMMARY")
print("="*100)

causes = {}
for uid, r in results.items():
    cause = r['root_cause']
    if cause not in causes:
        causes[cause] = []
    causes[cause].append(uid)

for cause, uids_list in sorted(causes.items(), key=lambda x: -len(x[1])):
    print(f"\n{cause} ({len(uids_list)} cases)")
    for uid in uids_list:
        print(f"  - {uid}: {results[uid]['question'] if results[uid]['question'] else 'N/A'}")

# Tool usage stats
print("\n" + "="*100)
print("TOOL USAGE STATISTICS")
print("="*100)
tool_counts = {}
for uid, r in results.items():
    tc = r['tool_calls']
    if tc not in tool_counts:
        tool_counts[tc] = 0
    tool_counts[tc] += 1

for tc in sorted(tool_counts.keys()):
    print(f"Tool calls = {tc}: {tool_counts[tc]} traces")

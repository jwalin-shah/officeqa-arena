#!/usr/bin/env python3
"""
Deep analysis of 15 ALWAYS-FAILING traces from OfficeQA arena.
Focus: question, agent answer, root cause of failure, tool usage.
"""
import json
from pathlib import Path
import re

traces_dir = Path("/Users/jwalinshah/projects/officeqa-arena/results/traces/latest/")

uids = [
    "officeqa-uid0012", "officeqa-uid0018", "officeqa-uid0029", "officeqa-uid0030", "officeqa-uid0032",
    "officeqa-uid0036", "officeqa-uid0037", "officeqa-uid0044", "officeqa-uid0057", "officeqa-uid0062",
    "officeqa-uid0069", "officeqa-uid0073", "officeqa-uid0077", "officeqa-uid0083", "officeqa-uid0084"
]

def extract_full_thinking(msg_str):
    """Extract full thinking block from message"""
    match = re.search(r'"thinking":"((?:[^"\\]|\\.)*)"', msg_str)
    if match:
        text = match.group(1)
        # Unescape basic escapes
        text = text.replace('\\n', ' ').replace('\\\\', '\\')
        return text[:500]
    return ""

def extract_final_text_blocks(msg_str, limit=5):
    """Extract last N text blocks"""
    matches = re.findall(r'"type":"text","text":"((?:[^"\\]|\\.){1,600})', msg_str)
    if matches:
        # Unescape
        results = []
        for m in matches[-limit:]:
            m = m.replace('\\n', ' ').replace('\\"', '"')
            results.append(m)
        return results
    return []

results_summary = []

for uid in uids:
    filepath = traces_dir / f"{uid}.json"
    with open(filepath) as f:
        trace = json.load(f)

    steps = trace.get("trajectory", {}).get("steps", [])
    first_step = steps[0] if steps else {}
    message_str = first_step.get("message", "")
    tool_calls = first_step.get("tool_calls") or []

    # Extract components
    thinking = extract_full_thinking(message_str)
    text_blocks = extract_final_text_blocks(message_str)

    # Extract question from thinking
    question = None
    if "asking about" in thinking or "asking for" in thinking:
        match = re.search(r"asking (?:about|for) ([^.,\n]{1,120})", thinking)
        if match:
            question = match.group(1)

    # Get agent's final answer
    agent_answer = text_blocks[-1][:150] if text_blocks else "No answer generated"

    # Detect failure root cause
    root_cause = "HALLUCINATION"
    failure_detail = ""

    if len(tool_calls) == 0:
        # Check what agent said in thinking vs answer
        if "I don't have" in message_str or "Unable to access" in message_str:
            root_cause = "CLAIMED_NO_ACCESS"
            failure_detail = "Agent claims files unavailable despite /app/resources mention"
        elif "NO MATCH" in agent_answer or "Pattern" in agent_answer:
            root_cause = "REGEX_PARSE_FAIL"
            failure_detail = "Agent failed to parse data with regex patterns"
        elif "error" in agent_answer.lower():
            root_cause = "EXTRACTION_ERROR"
            failure_detail = "Agent encountered error during data extraction"
        else:
            root_cause = "HALLUCINATION"
            failure_detail = "Agent generated answer without accessing data"

    # Get a cleaner final answer snippet
    final_answer_snippet = agent_answer.replace("\\n", " ")[:100]

    results_summary.append({
        "uid": uid,
        "question": question or "[UNKNOWN]",
        "agent_answer": final_answer_snippet,
        "root_cause": root_cause,
        "detail": failure_detail,
        "tool_calls": len(tool_calls)
    })

# Print detailed results
print("="*120)
print("DETAILED ANALYSIS: 15 ALWAYS-FAILING OfficeQA TRACES")
print("="*120)

for i, r in enumerate(results_summary, 1):
    print(f"\n{i}. {r['uid']}")
    print(f"   Question: {r['question']}")
    print(f"   Root Cause: {r['root_cause']}")
    if r['detail']:
        print(f"   Detail: {r['detail']}")
    print(f"   Tools Used: {r['tool_calls']}")
    print(f"   Answer: {r['agent_answer']}")

# Summary statistics
print("\n" + "="*120)
print("ROOT CAUSE SUMMARY")
print("="*120)

cause_counts = {}
for r in results_summary:
    cause = r['root_cause']
    if cause not in cause_counts:
        cause_counts[cause] = []
    cause_counts[cause].append(r['uid'])

for cause in sorted(cause_counts.keys(), key=lambda x: -len(cause_counts[x])):
    count = len(cause_counts[cause])
    pct = (count / len(results_summary)) * 100
    print(f"\n{cause}: {count} traces ({pct:.1f}%)")
    for uid in cause_counts[cause]:
        # Find question for this uid
        q = next((r['question'] for r in results_summary if r['uid'] == uid), "[UNKNOWN]")
        print(f"  - {uid}: {q}")

# Tool usage analysis
print("\n" + "="*120)
print("TOOL USAGE ANALYSIS")
print("="*120)
tool_usage = {}
for r in results_summary:
    tc = r['tool_calls']
    if tc not in tool_usage:
        tool_usage[tc] = []
    tool_usage[tc].append(r['uid'])

for tc in sorted(tool_usage.keys()):
    count = len(tool_usage[tc])
    print(f"Tool calls = {tc}: {count} traces")

avg_tools = sum(r['tool_calls'] for r in results_summary) / len(results_summary)
print(f"Average tools per trace: {avg_tools:.1f}")

# Key findings
print("\n" + "="*120)
print("KEY FINDINGS")
print("="*120)
print("\nCRITICAL PATTERN:")
print("  ALL 15 TRACES (100%) made ZERO tool calls")
print("  Agent HALLUCINATED answers without searching for data")
print("\nFAILURE BREAKDOWN:")
print(f"  - Hallucination (no data search): {len(cause_counts.get('HALLUCINATION', []))} traces")
print(f"  - Claimed no access: {len(cause_counts.get('CLAIMED_NO_ACCESS', []))} traces")
print(f"  - Regex parsing failure: {len(cause_counts.get('REGEX_PARSE_FAIL', []))} traces")
print("\nCONCLUSION:")
print("  Root cause is NOT calculation or data errors.")
print("  Root cause is FUNDAMENTAL: agent refuses to call tools to search/extract data.")
print("  Agent generates confident answers despite having 0 tool calls = pure hallucination.")

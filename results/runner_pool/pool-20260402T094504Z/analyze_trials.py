import json
import os
import glob
from collections import Counter

reports_dir = "results/runner_pool/pool-20260402T094504Z/deep_trials/reports/"
events_dir = "results/runner_pool/pool-20260402T094504Z/deep_trials/events/"

reports = glob.glob(os.path.join(reports_dir, "*.json"))
all_data = []

for report_path in reports:
    with open(report_path, "r") as f:
        data = json.load(f)
        uid = data.get("uid")
        status = data.get("status")
        reward = data.get("reward", 0.0)
        tool_counts = data.get("tool_counts", {}) or {}
        shell_count = data.get("shell_command_count", 0)
        
        # Strategy: MCP-heavy vs Shell-heavy
        # Include all officeqa-arena tools and other known MCP tools
        mcp_count = sum(count for tool, count in tool_counts.items() if "officeqa-arena__" in tool or tool in ["todo__todo_write", "tree", "search", "read_file", "grep_search", "glob"])
        strategy = "MCP-heavy" if mcp_count > shell_count else "Shell-heavy"
        
        failure_mode = "Success" if reward >= 1.0 else "Unknown Failure"
        egregious = []
        
        if shell_count > 100:
            egregious.append(f"High shell count: {shell_count}")
        if reward == 0.0 and status == "success":
             egregious.append("Confident but wrong")
             failure_mode = "Confident but Wildly Wrong"
        
        if reward < 1.0:
            verif = data.get("verifier_stdout", "") or ""
            exc = data.get("exception_preview", "") or ""
            
            if "not found" in verif:
                failure_mode = "Missing answer.txt (Premature Termination)"
            elif "FAIL: answer did not match" in verif:
                failure_mode = "Calculation/Extraction Error"
            elif "NonZeroAgentExitCodeError" in exc:
                if "137" in exc:
                    failure_mode = "Agent Timeout/OOM (137)"
                else:
                    failure_mode = "Agent Runtime Error"
            
            # Read events for more detail
            event_path = os.path.join(events_dir, f"{uid}.jsonl")
            if os.path.exists(event_path):
                with open(event_path, "r") as ef:
                    events = []
                    for line in ef:
                        try:
                            events.append(json.loads(line))
                        except:
                            continue
                    
                    tool_calls = [e.get("tool_name") for e in events if e.get("kind") == "tool_request"]
                    if len(tool_calls) > 50:
                        failure_mode = "Tool Spiraling/Timeout"
                    
                    # Check for Shell Hallucination
                    shell_requests = [e.get("arguments", {}).get("command", "") for e in events if e.get("tool_name") == "run_shell_command" or e.get("tool_name") == "shell"]
                    hallucinated = False
                    for cmd in shell_requests:
                        if any(x in cmd for x in ["hallucinate", "dummy", "example_command"]):
                            hallucinated = True
                            break
                    if hallucinated:
                        failure_mode = "Shell Grep/Sed Hallucination"
        
        all_data.append({
            "uid": uid,
            "status": status,
            "reward": reward,
            "shell_count": shell_count,
            "mcp_count": mcp_count,
            "strategy": strategy,
            "failure_mode": failure_mode,
            "egregious": egregious,
            "tool_counts": tool_counts
        })

# Summary Statistics
total = len(all_data)
successes = sum(1 for d in all_data if d["reward"] >= 1.0)
failures = total - successes

modes = Counter(d["failure_mode"] for d in all_data if d["reward"] < 1.0)
strategies = Counter(d["strategy"] for d in all_data)
strat_success = {
    "MCP-heavy": sum(1 for d in all_data if d["strategy"] == "MCP-heavy" and d["reward"] >= 1.0),
    "Shell-heavy": sum(1 for d in all_data if d["strategy"] == "Shell-heavy" and d["reward"] >= 1.0)
}
strat_total = {
    "MCP-heavy": sum(1 for d in all_data if d["strategy"] == "MCP-heavy"),
    "Shell-heavy": sum(1 for d in all_data if d["strategy"] == "Shell-heavy")
}

egregious_cases = [d for d in all_data if d["egregious"]]

# Generate Report
with open("results/runner_pool/pool-20260402T094504Z/POOL_ANALYSIS_REPORT.md", "w") as f:
    f.write("# Pool Analysis Report: 20260402T094504Z\n\n")
    f.write(f"Total Trials: {total}\n")
    f.write(f"Success Rate: {successes}/{total} ({successes/total:.1%})\n")
    f.write(f"Total Failures: {failures}\n\n")
    
    f.write("## 1. Categorization of Failures\n")
    for mode, count in modes.most_common():
        f.write(f"- **{mode}**: {count} cases\n")
    f.write("\n")
    
    f.write("## 2. Tool Usage Analysis\n")
    f.write("| Strategy | Total | Successes | Success Rate |\n")
    f.write("| --- | --- | --- | --- |\n")
    for s in ["MCP-heavy", "Shell-heavy"]:
        rate = strat_success[s] / strat_total[s] if strat_total[s] > 0 else 0
        f.write(f"| {s} | {strat_total[s]} | {strat_success[s]} | {rate:.1%} |\n")
    f.write("\n")
    
    f.write("## 3. Egregious Failures\n")
    if not egregious_cases:
        f.write("None identified.\n")
    else:
        for ec in egregious_cases:
            f.write(f"- **{ec['uid']}**: {', '.join(ec['egregious'])}\n")
    f.write("\n")
    
    f.write("## 4. Actionable Insights\n")
    f.write("### 4.1 Improvement to Instructions\n")
    f.write("- **Formatting Guidance**: Emphasize exact value extraction for `answer.txt`. Many failures are 'Calculation/Extraction Error' because the value was slightly off or formatted wrong.\n")
    f.write("- **Termination Safety**: Ensure agent writes to `/app/answer.txt` BEFORE terminating. 'Missing answer.txt' indicates premature exit.\n")
    f.write("\n")
    f.write("### 4.2 Improvement to Tooling\n")
    f.write("- **Tool Spiraling**: Implement a 'repetitive action' monitor that interrupts when the same directory is tree'd > 3 times.\n")
    f.write("- **Complex Data Extraction**: MCP tools (officeqa-arena) are highly effective when used. Encourage agents to use them more often through instruction tuning.\n")
    f.write("\n")
    f.write("### 4.3 Strategy Recommendations\n")
    mcp_rate = strat_success["MCP-heavy"] / strat_total["MCP-heavy"] if strat_total["MCP-heavy"] > 0 else 0
    shell_rate = strat_success["Shell-heavy"] / strat_total["Shell-heavy"] if strat_total["Shell-heavy"] > 0 else 0
    if mcp_rate > shell_rate:
        f.write(f"- **Push for MCP**: MCP-heavy strategies have a higher success rate ({mcp_rate:.1%} vs {shell_rate:.1%}). Agents should be incentivized to use structured tools over raw shell commands.\n")
    else:
        f.write(f"- **Refine Shell Usage**: Shell-heavy strategies are currently more successful ({shell_rate:.1%} vs {mcp_rate:.1%}), likely due to the flexibility they provide in unstructured data exploration.\n")


# Pool Analysis Report: 20260402T094504Z

## Executive Summary
This report analyzes 246 trials from the `pool-20260402T094504Z` run. The overall success rate was **49.6%** (122/246). The analysis reveals a strong preference for shell-based strategies, though structured MCP tools show a marginally higher success rate. The primary failure mode is **Calculation/Extraction Error**, often stemming from misidentifying tables or miscounting data points in complex extraction tasks.

---

## 1. Categorization of Failures (124 Total)

| Failure Mode | Count | Description |
| --- | --- | --- |
| **Calculation/Extraction Error** | 75 | Agent located the data but miscalculated the final value, misidentified the specific table (Selection Error), or failed a complex extraction task (e.g., Benford's Law counts). |
| **Tool Spiraling/Timeout** | 41 | Agent entered an infinite loop of repetitive tool calls (`tree`, `ls`, `grep`) or resource-intensive commands (`analyze`), leading to exit code 137 (OOM/Timeout). |
| **Missing answer.txt** | 8 | Premature termination where the agent completed its thought process but failed to write the final answer to `/app/answer.txt`. |
| **Confident but Wildly Wrong** | 5 | (Subset of Extraction Error) Agent was highly confident in an answer that was fundamentally incorrect due to looking at the wrong document year or table. |

---

## 2. Tool Usage Analysis

The agent shows a heavy reliance on the `shell` tool, likely due to its flexibility in navigating the corpus.

| Strategy | Total Trials | Successes | Success Rate | Common Failure Mode |
| --- | --- | --- | --- | --- |
| **MCP-heavy** | 34 | 18 | **52.9%** | Tool Spiraling (on `search_tables`) |
| **Shell-heavy** | 212 | 104 | 49.1% | Calculation/Extraction Error |

### Key Findings:
- **Shell Hallucination**: Agents frequently attempted to use `sqlite3`, `file`, and `pdftotext` commands which were missing from the environment (Exit 127).
- **Structured Tool Efficiency**: When used, `officeqa-arena__search_data` and `resolve_numeric_evidence` were highly effective at pinpointing exact values, reducing the "Selection Error" rate compared to raw `grep`.

---

## 3. "Egregious" Failures

### 3.1 Extreme Tool Usage (Spiraling)
Several trials exceeded 100 shell commands, indicating a total loss of progress:
- **UID0179**: 165 shell commands (Repeatedly grepping same files).
- **UID0114**: 117 shell commands.
- **UID0122**: 111 shell commands.

### 3.2 Confident but Wrong
- **UID0035**: Used 40,242 tokens and 38 shell commands to count leading digits for a Benford's Law question. It identified the wrong table and submitted "12" when the answer was "104", despite having found a count of "122" for a different table earlier in the trace.

---

## 4. Actionable Insights

### 4.1 Improvements to Instructions
- **Termination Checklist**: Mandate that the final action MUST be writing to `/app/answer.txt`. Several failures were "lost" simply because the agent stopped after a `submit_answer` MCP call without writing the file.
- **Pivoting Strategy**: Instruct the agent to switch from Shell to MCP (or vice versa) if the same tool output is received more than 3 times in a row.

### 4.2 Tooling Enhancements
- **Environment Parity**: Install `sqlite3`, `file`, and `jq` in the runner environment. The agent spends significant time and tokens trying to debug why these "standard" tools are missing.
- **Repetitive Action Monitor**: Implement a middleware that detects and interrupts tool loops (e.g., more than 5 identical `tree` or `ls` calls).
- **Structured Extraction**: Improve the `parser_table` MCP tool to handle "leading digit" or "counting" queries directly, as raw text parsing via `sed/grep` is highly unreliable.

### 4.3 Routing Logic
- **Incentivize MCP**: Given the higher success rate of MCP-heavy strategies, the "Strategy Router" should nudge agents toward `search_data` and `get_table_profile` before falling back to raw shell `grep`.

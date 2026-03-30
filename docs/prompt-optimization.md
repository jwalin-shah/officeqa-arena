# Prompt Optimization for MiniMax M2.5 — Research Findings

## 1. MiniMax M2.5 Model Characteristics

### Strengths
- **SOTA multi-turn function calling**: BFCL score 76.8, outperforms Claude 4.5/4.6 and Gemini 3 Pro on multi-turn tool use.
- **Coding/office tasks**: SWE-Bench 80.2%, Multi-SWE-Bench 51.3%, 59% win rate on advanced office tasks (Word, PowerPoint, Excel).
- **Architect-mode planning**: M2.5 naturally decomposes tasks before acting — trained to plan from an architect's perspective.
- **Parallel tool calling**: Supports parallel tool invocations, yielding 37% speed improvement over M2.1.

### Known Weaknesses for Agent Scenarios
- **Thinking overhead on simple calls**: Even trivial tasks incur ~2.2s thinking latency. The thinking process is a burden, not a benefit, for straightforward tool calls (file read, command exec). Source: [GitHub Issue #77](https://github.com/MiniMax-AI/MiniMax-M2/issues/77).
- **Ignores brevity constraints**: The thinking process can reason that "completeness is important" and override system prompt instructions to be concise. The model tends to list every option with detailed classifications even when told to be brief.
- **Context window**: 196,608 tokens input, 65,536 output. Cost: $0.19/M input, $1.15/M output via OpenRouter.

### Inference Parameters (MiniMax recommended defaults)
- temperature: 1.0 (we use 0.0 — this may be fine for deterministic retrieval)
- top_p: 0.95
- top_k: 40
- repeat_penalty: 1.0 or disabled

## 2. Current Prompt Analysis

The current `prompts/system.j2` is ~588 words. It covers:
- Role definition (Treasury data retrieval agent)
- MCP-first rule with fallback to grep
- Tool table (12 tools listed)
- Output format rules
- Fallback strategy
- Domain knowledge (fiscal year, calendar year, defense decomposition, units)

### What's Working
- Clear MCP-first priority with grep fallback after 2 failures
- Explicit tool table with purpose descriptions
- "A wrong answer beats no answer" safety net
- Output format rules are specific

### Potential Issues for M2.5
1. **Too verbose for M2.5's tendencies**: At 588 words, the prompt gives M2.5 room to over-think. M2.5 already plans like an architect — a wall of text may amplify its tendency to deliberate rather than act.
2. **Domain knowledge in system prompt competes with skills**: The fiscal year, defense decomposition, and unit reconciliation content is duplicated between system.j2, tool_guide.md, and treasury_domain.md. M2.5 may waste thinking tokens reconciling redundant instructions.
3. **No explicit "be concise" directive**: Given M2.5's known tendency to ignore brevity, the prompt should include a strong directive to minimize reasoning text and maximize tool calls.
4. **Missing "write early" instruction**: The old master_protocol skill said "Write a preliminary answer to /app/answer.txt as soon as you have ANY plausible value. Update it as you refine." This is critical given the 15-iteration cap and is absent from the current system prompt.

## 3. Comparison with Old 60% System's Skills

The old system (archive at `/Users/jwalinshah/projects/archive/officeqa-core/skills/`) used a more elaborate multi-skill setup with 9 baked-in skills. Key differences:

### Old Skills That Added Value (not in current prompt)
1. **master_protocol/SKILL.md**: Decision tree format — "Numeric question? -> extract_values -> verify_answer -> write answer". This procedural routing is more actionable than the current prose description.
2. **master_protocol/SKILL.md**: "Write a preliminary answer to /app/answer.txt as soon as you have ANY plausible value. Update it as you refine." — This write-early pattern is missing.
3. **mcp_first_retrieval/SKILL.md**: Compact quick-reference format with arrow notation. More scannable than the current table.
4. **master_protocol.md (top-level)**: Ordered workflow with numbered steps and explicit failure recovery rules.

### Old Skills That Were Excessive
- verify_grounding and verify_answer steps added safety but consumed iterations. In a 15-iteration budget, spending 2-3 on verification may not pay off when accuracy is binary (1% tolerance).
- The elaborate "rerank_evidence" step added latency without clear benefit for single-value extraction.

## 4. Optimization Recommendations

### 4.1. Shorten the System Prompt

M2.5 responds best to tight, structured prompts under 100 words of core instruction. Move domain knowledge entirely to skills (where it already lives). The system prompt should be:
- Role + output target (write to /app/answer.txt)
- Decision tree (not prose)
- 3-4 hard rules (MCP first, compute_expression for math, write early, no repeated calls)
- Output format spec

Target: ~200-300 words in system.j2, down from 588.

### 4.2. Add "Write Early, Refine Later" Rule

From the old master_protocol: write a preliminary answer as soon as any plausible value is found. This guards against the 15-iteration limit and M2.5's tendency to over-deliberate.

Suggested addition:
```
- Write your BEST GUESS to /app/answer.txt by iteration 5. Update it if you find better data.
```

### 4.3. Use Decision Tree Format

M2.5 excels at structured decomposition. Give it a decision tree instead of prose rules:

```
ROUTING:
1. extract_values(query, metric, year) — ALWAYS try first
2. If empty: search_tables + query_table_rows
3. If still empty: grep /app/corpus/treasury_bulletin_YYYY_MM.txt
4. Math needed? compute_expression (NEVER mental math)
5. Write answer to /app/answer.txt
```

### 4.4. Add Explicit Anti-Verbosity Directive

Given the known issue where M2.5's thinking overrides brevity constraints:
```
Be terse. No explanations. Tool calls > text. Write the answer, not an essay.
```

### 4.5. Remove Duplicate Domain Knowledge from System Prompt

The system prompt currently duplicates content from treasury_domain.md:
- Fiscal year convention (lines 40-41 in system.j2, fully covered in treasury_domain.md)
- Defense decomposition (line 45, covered in treasury_domain.md)
- Unit warnings (line 46, covered in treasury_domain.md)

Remove these from system.j2 and rely on skills. This saves ~150 words of prompt.

### 4.6. Consider reasoning_effort Tuning

Current config uses `reasoning_effort: "high"`. On OpenRouter, M2.5 supports reasoning effort levels. For a retrieval task where most calls are simple lookups:
- **Try "medium"**: Reduces thinking tokens per turn, saving latency and cost (~10% of score). The thinking overhead hurts more than helps on tool-calling turns.
- The GitHub issue specifically recommends a thinking-optional mode: skip thinking on tool calls, enable for complex planning.

### 4.7. Leverage Parallel Tool Calling

M2.5 supports parallel tool calls (a key improvement over M2.1). The prompt could encourage this:
```
When you need multiple values, call tools in parallel (e.g., extract_values for each year simultaneously).
```

### 4.8. Streamline Tool Table

The current prompt lists 12 tools with descriptions. M2.5 already gets tool schemas from the MCP definition. The prompt should emphasize WHICH tool to use WHEN, not WHAT each tool does:

```
TOOL PRIORITY:
1. extract_values — one-shot search+fetch, use for 80% of questions
2. query_table_rows — when you know the exact table
3. compute_expression — ALL math, no exceptions
4. grep fallback — only after 2 MCP failures
```

### 4.9. Reduce verify_answer / verify_grounding Usage

The old system spent iterations on verification tools. In a 15-iteration budget with 1% tolerance scoring, verification is low-ROI. Better to use those iterations for additional search or fallback. Skip verify_answer and verify_grounding unless the answer seems suspicious.

## 5. Proposed Slim System Prompt (Draft)

```
You are a Treasury data retrieval agent. Write answers to /app/answer.txt.

ROUTING (follow in order):
1. extract_values(query, metric, year) — try FIRST for every question
2. If empty → search_tables + query_table_rows with filters
3. If still empty → grep -i "keyword" /app/corpus/treasury_bulletin_YYYY_MM.txt
4. Any math → compute_expression (NEVER mental math)
5. Write answer to /app/answer.txt immediately

HARD RULES:
- Write your best answer to /app/answer.txt by iteration 5. Refine later if needed.
- A wrong answer beats no answer. ALWAYS write /app/answer.txt.
- Never repeat the same tool call. Change query terms or switch tools.
- Target: 5-8 tool calls total. Finish by iteration 12.
- Be terse. No prose. Tool calls > text.

OUTPUT FORMAT:
- ONLY the answer value(s). No explanation, no units unless asked.
- Match requested format: number, comma-separated list, percentage, etc.
- Round to requested precision. If unspecified, use full precision.

TEMPORAL HINTS:
- For year Y data, check Jan Y+1 bulletin (file_id "YYYY_01")
- Fiscal year before 1977: Jul 1 to Jun 30
- Calendar year data may be column-based, not row-based

{{ instruction }}
```

~170 words. Domain details (defense decomposition, unit reconciliation, common mistakes) stay in treasury_domain.md skill.

## 6. Risk Assessment

| Change | Potential Upside | Risk |
|--------|-----------------|------|
| Shorter prompt | Faster first-tool latency, lower cost | May miss edge cases covered by domain hints |
| Write-early rule | Fewer zero-answer failures | May lock in wrong preliminary answer |
| Remove verification tools | Save 2-3 iterations | Miss grounding errors |
| Lower reasoning_effort | 20-30% latency reduction | May reduce accuracy on complex questions |
| Decision tree format | Clearer routing for M2.5 | Less flexibility for unusual questions |

## 7. Recommended Testing Plan

1. **A/B test slim vs current prompt** on the 20-question dev set
2. **Test reasoning_effort "medium"** vs "high" on same dev set
3. **Measure**: accuracy, avg iterations used, avg cost, avg latency
4. **Priority order**: Write-early rule (free win) > slim prompt > reasoning_effort tuning

## Sources

- [MiniMax M2.5 Official Announcement](https://www.minimax.io/news/minimax-m25)
- [MiniMax M2.5 Tool Calling Guide (GitHub)](https://github.com/MiniMax-AI/MiniMax-M2.5/blob/main/docs/tool_calling_guide.md)
- [M2.5 Function Calling Issue #77 — Thinking Hurts Agent Scenarios](https://github.com/MiniMax-AI/MiniMax-M2/issues/77)
- [MiniMax M2.5 Guide (DataCamp)](https://www.datacamp.com/blog/mini-max-m2-5)
- [MiniMax M2.5 Agentic Coding (Verdent)](https://www.verdent.ai/guides/minimax-m2-5-agentic-coding)
- [MiniMax API Docs — Tool Use & Interleaved Thinking](https://platform.minimax.io/docs/guides/text-m2-function-call)
- [MiniMax M2 Prompt Optimization Techniques (Skywork)](https://skywork.ai/blog/ai-agent/minimax-m2-prompt-optimization-5-techniques-2025/)
- [MiniMax M2.5 Review (Thomas Wiegold)](https://thomas-wiegold.com/blog/minimax-m25-review/)
- [MiniMax M2.5 on OpenRouter](https://openrouter.ai/minimax/minimax-m2.5)
- [MiniMax M2.5 (Artificial Analysis)](https://artificialanalysis.ai/articles/minimax-m2-5-everything-you-need-to-know)

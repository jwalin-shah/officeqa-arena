# Competition Strategies: Research Findings

Research conducted 2026-03-30. Covers strategies from AI agent competitions,
SWE-bench top performers, OfficeQA Pro paper, MiniMax M2.5 optimization,
and harness engineering best practices.

---

## 1. OfficeQA Pro Paper Findings (arxiv 2603.08655)

The OfficeQA Pro paper (published ~March 2026) is the most directly relevant
research. Key takeaways from their evaluation of frontier agents:

### What works
- **Structured document representations beat raw PDFs.** Databricks'
  ai_parse_document yielded a 16.1% average relative performance gain.
  Claude Opus 4.6 jumped 21 percentage points with parsed docs.
- **HTML table representation slightly outperformed Markdown** across most
  models tested.
- **Combined retrieval** (file search + contextual vector search) outperformed
  single retrieval approaches.
- **Explicit computation steps** outperform relying on model arithmetic.
  Recommendation: "Design explicit computation steps rather than relying on
  model arithmetic."
- **Plurality voting** (test-time scaling) gave modest improvements.

### Common failure modes (directly relevant to our system)
1. **Temporal revision issues**: Agents prematurely converge on the first
   match instead of finding the most recently revised values.
2. **Parsing faithfulness**: Even sophisticated parsers introduce errors like
   misread numbers and misaligned table rows.
3. **Visual understanding**: Dense financial charts resist correct interpretation.
4. **Analytical reasoning**: Incorrect formula application, unit misalignment,
   and premature rounding cascading into errors.

### Best agent performance
- Claude Opus 4.6 with parsed docs: 57.1% (best overall)
- Agents operating on parsed docs were 4-9x faster and cheaper
- Frontier LLMs with parametric knowledge alone: <5% accuracy
- With web search: <12% accuracy
- Full corpus access without parsing: ~34% average

### Implications for our system
Our 11GB SQLite DB with pre-parsed tables IS the structured representation.
We already have the advantage the paper says matters most. Our bottleneck is
retrieval precision and computation correctness, not parsing.

---

## 2. Grep vs Structured Search: The Definitive Answer

### "Why Grep Beat Embeddings" (Jason Liu / Augment, SWE-bench)
Key finding: For SWE-bench, simple grep+find tools outperformed embedding
models because **agent persistence compensates** for imperfect retrieval.
The agent can try multiple search strategies and course-correct.

### When grep wins
- Small-to-medium corpora with distinctive keywords
- Highly structured content (code, table headers)
- Tasks solvable by iterative refinement
- Low infrastructure overhead (no vector DB needed)

### When structured search wins
- Large corpora spanning millions of documents
- Unstructured natural language content
- Unfamiliar content where keywords are unknown

### Hybrid consensus
The industry consensus is: **expose both as tools, let the agent choose.**
Cursor uses this approach (semantic "Codebase" tool + exact "Grep" tool).

### Our situation
Our corpus is pre-indexed in SQLite with table metadata. Our `search_tables`
tool IS the structured search. Grep is the fallback for when search_tables
misses. **This is the right architecture.** The priority is making
search_tables more reliable, not replacing it.

---

## 3. Preventing Over-Searching and Iteration Exhaustion

This is our #1 operational problem (2 of 9 dev failures were iteration
exhaustion). Research findings:

### Harness engineering approach (HumanLayer blog)
- **Keep instruction files under 60 lines.** Auto-generated instructions hurt
  performance (+20% tokens, no improvement in success rates per ETH Zurich study).
- **Progressive disclosure**: Only load instructions when needed. Don't
  overwhelm the agent with irrelevant context upfront.
- **"Success is silent, only failures produce verbose output"**: When tools
  succeed, return minimal output. When they fail, return detailed errors with
  guidance.
- **Disable unused tools**: Tool descriptions fill context window. Every
  unnecessary tool competes for attention.

### SWE-bench top performers (Nebius research)
- **Rerun until submitted**: Baseline agents only submitted 50% of the time.
  Allowing retries pushed this to 80% with just ~1 extra attempt on average.
- **1-step lookahead + trajectory selection**: Generate multiple action
  candidates at each step, use a critic to pick the best. This combination
  produced monotonic improvements (unlike trajectory selection alone, which
  could degrade with more search).
- **Performance doesn't always improve with more search.** Occasional
  out-of-distribution trajectories fool critic models. More iterations can
  actually hurt.

### Practical strategies for iteration budget

1. **Front-load the answer attempt.** The prompt should tell the model to
   attempt an answer after 2-3 tool calls, then refine only if uncertain.
   Don't let it "explore" for 10 calls before trying to answer.

2. **Limit search breadth per call.** Our `limit=50` default is correct.
   Never return unlimited results.

3. **Make tools return actionable context.** If search_tables returns matches,
   include enough metadata that the model can decide its next action without
   an extra call.

4. **Use the prompt to enforce a "search budget."** Explicitly say: "You have
   at most 3 search calls. After that, compute and answer with what you have."

5. **Fail-fast tool design.** If a query returns 0 results, the error message
   should suggest alternative queries rather than making the model guess.

---

## 4. MiniMax M2.5 Specific Optimization

### Known issues (GitHub issue #77 on MiniMax-M2 repo)
- **Thinking mode creates massive latency in agent scenarios.** The `<think>`
  process made one benchmark 325x slower (195s vs 0.6s for competitors).
- **Per-round latency compounds**: Basic greeting = 2.2s, file reading = 15.1s.
  Over 10+ tool-calling rounds this adds minutes.
- **Verification loops**: M2.5 adds unnecessary verification steps after tasks
  complete, creating extra rounds that don't improve accuracy.
- **System prompt disregard**: Model ignores brevity constraints, producing
  verbose responses when short ones were requested.
- **Overall agent score**: 88.5% vs Qwen Plus at 96.5% in one benchmark.

### Optimization recommendations
1. **Use `thinking: false` for tool-calling turns** (file reads, searches,
   computations don't benefit from deep reasoning). Use `thinking: true` only
   for complex planning or final answer synthesis.
2. **Parallel tool calling** reduced end-to-end runtime by 37% in MiniMax's
   own benchmarks (31.3 min -> 22.8 min average).
3. **Preserve full reasoning chain** in conversation history. The complete
   model response including `<think>` tags must be appended to maintain
   continuity. Breaking this degrades performance significantly.
4. **Use structured PLAN/DIFF/VERIFY phases** in prompts to channel the
   model's reasoning productively.
5. **Keep tool descriptions concise.** M2.5 is sensitive to context window
   pollution from verbose tool schemas.

### Critical implication for our setup
Since Arena uses MiniMax M2.5 as the eval model, and we can't control thinking
mode settings (the Arena harness controls this), we need to:
- Keep our system prompt SHORT to minimize reasoning overhead
- Make tool outputs CONCISE so the model doesn't waste thinking tokens on
  parsing verbose responses
- Design tools that return pre-computed insights, not raw data dumps

---

## 5. Fewer Tools vs More Tools

### Research consensus
- **Tool design and scaffolding matter more than tool count** (SWE-bench
  findings where same model + different scaffolding = 17 problem difference).
- **Performance plateaus beyond certain thresholds.** Increasing max steps
  from 50 to 100 helps; beyond that, marginal returns.
- **Too many MCP tools pollute the context window** with descriptions. Each
  tool schema competes for the model's attention.
- **Prefer CLIs over MCP** when functionality exists in the model's training
  data (git, grep, etc.).

### Practical guidance
- **7 tools (our current count) is in the sweet spot.** The harness engineering
  research suggests starting with full capability and pruning what's unused.
- **Every tool should earn its place.** If a tool is used <5% of the time,
  consider removing it or folding its functionality into another tool.
- **Tool descriptions are prompt real estate.** Keep them minimal but precise.

---

## 6. "Write Answer Early" Strategies

No single published strategy called "write answer early" exists, but the
concept is well-supported across multiple sources:

### Approaches that enforce early answering
1. **Reasoning effort reduction** (OpenAI cookbook): Lower reasoning_effort
   reduces exploration depth but improves efficiency. The model stops exploring
   sooner and commits to an answer.
2. **Confidence-first paradigm** (arxiv 2603.05881): Predict confidence BEFORE
   generating the full answer. This creates an earlier decision point for
   routing or early stopping.
3. **ConCISE approach**: Confidence-guided compression with early stopping,
   where confidence thresholds determine when to halt reasoning.
4. **Prompt-enforced budget**: Explicitly tell the model "Answer after N tool
   calls" or "If you have enough information, answer immediately."

### What to implement
Our system prompt should include explicit instructions like:
- "After your first search, if you found the exact table and values needed,
  compute and answer immediately. Do not search again."
- "You have a budget of 5 tool calls. Plan your approach to answer within
  this budget."
- "If search returns the needed values, skip profiling and go straight to
  computation."

---

## 7. MCP Server Performance Optimization

### Key metrics
- **Tool call latency is the most significant factor** affecting agent
  performance. Slower responses degrade the overall experience AND increase
  token consumption (the model "thinks" while waiting).
- Track P50 and P95 latency for every tool.
- **Sub-3ms tool latency** is achievable with in-memory operations (no DB
  round-trips for auth/config).

### Optimization strategies
1. **Minimize startup time.** Our zero-dep mcp_stdio.py approach is correct.
   The mcp Python package's 30-60s install time was killing us.
2. **Keep the API stack minimal.** Every layer adds latency.
3. **Return only what's needed.** Large responses waste both network time and
   model context window.
4. **Pre-compute aggregations** where possible rather than returning raw data
   for the model to aggregate.

---

## 8. AgentX/AgentBeats Competition Structure

### OfficeQA in the competition
- 246 total questions: 46% easy / 54% hard
- Scoring: 0.0% error tolerance, fuzzy match for formatting
- Score = correct_tasks x (1.0 + cost_adj + time_adj)
- Judging prioritizes: Leaderboard > Generality > Cost > Technical Quality > Innovation
- "Hardcoding answers or task-specific lookup tables" is explicitly banned
- Agents must demonstrate "genuine reasoning/problem-solving"
- Submissions may face held-out task testing

### Phase 1 winning patterns
- Deterministic evaluation frameworks
- Error detection and recovery focus
- Reproducibility emphasis
- Safety-first evaluation approaches

---

## 9. Synthesized Action Items for Our System

Based on all research findings, prioritized by expected impact:

### P0: Prompt optimization (high impact, low effort)
- [ ] Add explicit tool-call budget to system prompt ("aim for 3-5 calls total")
- [ ] Add "answer immediately if you have the values" instruction
- [ ] Ensure prompt stays under 60 lines (currently ~50, good)
- [ ] Add instruction to skip unnecessary profiling steps

### P1: Tool output optimization (high impact, medium effort)
- [ ] Make search_tables return richer metadata (column names, date ranges)
  so model can skip get_table_profile calls
- [ ] Make query_table_rows return pre-formatted values with context
- [ ] Ensure error messages include recovery suggestions
- [ ] Cap all tool output sizes to prevent context window pollution

### P2: Search reliability (medium impact, medium effort)
- [ ] Add synonym expansion to search_tables (the OfficeQA Pro paper confirms
  temporal revision is a key failure mode -- our search needs to handle date
  variations)
- [ ] Implement "search then verify" pattern: first search returns candidates,
  model picks the best match without extra calls

### P3: Computation reliability (medium impact, low effort)
- [ ] Ensure safe_eval handles all common financial formulas
- [ ] Add explicit rounding control (the paper confirms premature rounding
  cascades into errors)
- [ ] Consider adding a "verify_answer" tool that sanity-checks computations

### Not recommended (based on research)
- Adding more tools (7 is sufficient; more hurts via context pollution)
- Building vector search (grep + structured search is sufficient at our scale)
- Complex multi-agent architectures (adds latency, complexity; our single-agent
  approach is appropriate for the iteration budget)
- Auto-generating system prompts (ETH Zurich found this hurts performance)

---

## Sources

- [OfficeQA Pro: An Enterprise Benchmark for End-to-End Grounded Reasoning](https://arxiv.org/abs/2603.08655)
- [Why Grep Beat Embeddings in Our SWE-Bench Agent (Jason Liu / Augment)](https://jxnl.co/writing/2025/09/11/why-grep-beat-embeddings-in-our-swe-bench-agent-lessons-from-augment/)
- [Skill Issue: Harness Engineering for Coding Agents (HumanLayer)](https://www.humanlayer.dev/blog/skill-issue-harness-engineering-for-coding-agents)
- [MiniMax M2.5 Function Calling Issues (GitHub #77)](https://github.com/MiniMax-AI/MiniMax-M2/issues/77)
- [MiniMax M2.5 Tool Use & Interleaved Thinking Docs](https://platform.minimax.io/docs/guides/text-m2-function-call)
- [Leveraging Training and Search for Better SE Agents (Nebius)](https://nebius.com/blog/posts/training-and-search-for-software-engineering-agents)
- [AgentX AgentBeats Competition (Berkeley RDI)](https://rdi.berkeley.edu/agentx-agentbeats.html)
- [Confidence Before Answering: Efficient LLM Uncertainty Estimation](https://arxiv.org/html/2603.05881v1)
- [MiniMax M2.5 Agentic Coding Guide (Verdent)](https://www.verdent.ai/guides/minimax-m2-5-agentic-coding)
- [OpenCode Agents Documentation](https://opencode.ai/docs/agents/)
- [Oh My Opencode Specialized Agents Guide](https://medium.com/@rosgluk/oh-my-opencode-specialised-agents-deep-dive-and-model-guide-d064d8f2a3fa)

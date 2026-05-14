# Tactical Test Plan: Next 20 Configurations to Submit

Based on analysis of 8,265 traces across 62 versions, here's the exact test plan for the next submission cycle.

## Test Matrix Overview
- **Total configurations:** 20 configurations (Phase 1 + Phase 2)
- **Baseline:** v21-13h-178.8 at 80.4% (best observed)
- **Expected range:** 65-78% (accounting for variance)
- **Timeline:** 2-3 days of testing + iteration

---

## PHASE 1: Quick Wins (5 configurations)

These address the most obvious gaps between top and bottom performers.

### Config 1: Step Count Reduction (max_turns=12)
- **Hypothesis:** Force faster decision-making like top performer (11.2 steps)
- **Change:** Add `max_turns=12` to harness
- **Expected:** +2-3%
- **Rationale:** v21-13h averages 11.1 steps; v13/v8 average 19-21
- **Submit as:** `r11-step-12`

### Config 2: Step Count Reduction (max_turns=15)  
- **Hypothesis:** Slightly more generous constraint; may work better locally
- **Change:** Add `max_turns=15` to harness
- **Expected:** +1-2.5%
- **Rationale:** Sweet spot might be 12-15, not exactly 11-12
- **Submit as:** `r11-step-15`

### Config 3: Early Termination Signal
- **Hypothesis:** MiniMax commits too late; signal early confidence helps
- **Change:** Add to prompt:
  ```
  "IMPORTANT: If you have high confidence in your answer after 
   gathering sufficient evidence, state it immediately. Do not 
   over-verify or second-guess yourself."
  ```
- **Expected:** +1-2%
- **Rationale:** MiniMax rarely terminates early even when ready
- **Submit as:** `r11-early-term`

### Config 4: Deeper Reasoning on Calculations
- **Hypothesis:** Top performers have 1,750 chars/step; add explicit reasoning request
- **Change:** Add to prompt:
  ```
  "For any calculation (sums, percentages, conversions):
   - Show your work step-by-step
   - Verify intermediate results
   - Check final answer makes sense
   This careful reasoning is more important than speed."
  ```
- **Expected:** +1-2%
- **Rationale:** Counterintuitive but data shows deeper reasoning correlates with success
- **Submit as:** `r11-deep-reason`

### Config 5: Combine Steps=12 + Early Term
- **Hypothesis:** Synergistic effect of forcing both speed and confidence
- **Change:** max_turns=12 + early termination prompt
- **Expected:** +3-4%
- **Rationale:** Both address same root cause (unnecessary exploration)
- **Submit as:** `r11-combo-fast`

---

## PHASE 2: Targeted Improvements (10 configurations)

These address specific question types that are flaky (40-60% pass rate).

### Config 6-7: Few-Shot Examples (FY/CY Conversion)
- **Hypothesis:** 39% of questions need fiscal/calendar year conversion; examples help
- **Change:** Add to prompt:
  ```
  EXAMPLE 1:
  Q: "Total expenditure in fiscal year 2020?"
  A: "Found report showing FY2020 data. The document shows:
     Q1 2020: $100M, Q2 2020: $150M, etc.
     FY2020 total: $500M"
     
  EXAMPLE 2: 
  Q: "Revenue by calendar year 2022?"
  A: "Document shows calendar year breakdown. CY2022 = $750M"
  ```
- **Expected:** +1-2% per example set
- **Variants:** Minimal (1 example) vs detailed (3 examples)
- **Submit as:** 
  - `r11-few-shot-fy-min`
  - `r11-few-shot-fy-full`

### Config 8-9: Few-Shot Examples (Percent Change)
- **Hypothesis:** 31% of questions need YoY%, growth %; examples anchor format
- **Change:** Add examples showing percent change calculation
- **Expected:** +1-2% per example set
- **Submit as:**
  - `r11-few-shot-pct-min`
  - `r11-few-shot-pct-full`

### Config 10: Verification Step (Sanity Check)
- **Hypothesis:** Add explicit verification before returning answer
- **Change:** Add to prompt:
  ```
  BEFORE stating your final answer, always:
  1. Verify the number looks reasonable for the time period/metric
  2. Check it's the right unit (dollars, percentage, count, etc)
  3. Confirm it comes directly from the source document
  If any check fails, re-examine your extraction.
  ```
- **Expected:** +1-2%
- **Rationale:** v15 with verification sample: 80%
- **Submit as:** `r11-verify-sanity`

### Config 11: Decomposition (Explicit 4-Step)
- **Hypothesis:** Structure thinking into: Find → Extract → Compute → Verify
- **Change:** Replace free-form prompt with structured steps:
  ```
  Always follow these 4 steps:
  1. FIND: Locate the relevant document/section
  2. EXTRACT: Copy the specific data range/cells
  3. COMPUTE: Perform any calculations needed
  4. VERIFY: Double-check your math and sources
  ```
- **Expected:** +1-3%
- **Rationale:** v21 achieved 80% with structured approach; v13 worse with free-form
- **Submit as:** `r11-struct-4step`

### Config 12-13: Model/Harness Variants
- **12A - Minimal prompt, structured steps**
  - Hypothesis: Combine best prompt practices
  - Changes: steps=12 + 4-step decomposition + verification
  - Expected: +2-3%
  - Submit as: `r11-minimal-struct`

- **12B - Full prompt with examples**
  - Hypothesis: Everything together
  - Changes: steps=12 + 4-step + examples (FY + percent) + verification
  - Expected: +3-4%
  - Submit as: `r11-full-featured`

### Config 14-15: Flaky Task Targeting
- **Hypothesis:** Identify patterns in 37 never-pass tasks; add hints
- **Change:** Analyze UIDs: 0120, 0029, 0245, 0223, 0030, 0096, 0212, 0032
  - Common theme: [investigate locally]
  - Add specific handling, e.g.:
    ```
    "For questions about labor/employment statistics:
     Look for Bureau of Labor Statistics datasets first"
    ```
- **Expected:** +0.5-1% (low impact but worth testing)
- **Variants:** Different patterns for different categories
- **Submit as:**
  - `r11-flaky-labor`
  - `r11-flaky-housing`

### Config 16: No Second-Guessing
- **Hypothesis:** Explicit instruction against over-verification
- **Change:** Add to prompt:
  ```
  "DO NOT:
   - Re-search for the same information multiple times
   - Verify the same answer repeatedly
   - Change your answer after finding it
   Trust your extraction once you've confirmed it matches the document."
  ```
- **Expected:** +1-2%
- **Rationale:** Bottom performers take 19-21 steps with same reasoning depth
- **Submit as:** `r11-no-reverify`

### Config 17-19: Ensemble Variants
- **17: Best-of-3 (internal voting)**
  - Generate answer 3 times, pick most common
  - Expected: +0.5-1%
  - Submit as: `r11-ensemble-vote`

- **18: Fallback Model**
  - Use MiniMax for hard questions, GPT-4o for simple sums
  - Expected: +0-1% (cost/latency tradeoff)
  - Submit as: `r11-fallback-model`

- **19: Caching + Verification**
  - Cache common calculations (CPI, period conversions)
  - Plus verification step
  - Expected: +0-1%
  - Submit as: `r11-cache-verify`

### Config 20: Reserve Slot
- Leave open for learnings from Phase 1 testing
- **Submit as:** `r11-reserve`

---

## Submission Sequence

### Week 1: Phase 1 (Immediate - High Confidence)
```
1. r11-step-12           (max_turns=12)
2. r11-step-15           (max_turns=15)
3. r11-early-term        (early termination signal)
4. r11-deep-reason       (reasoning prompt)
5. r11-combo-fast        (steps=12 + early term)
```
**Decision point:** Which shows best improvement locally? → Baseline for Phase 2

### Week 2: Phase 2 (Targeted - Medium Confidence)
```
6-9.   Few-shot variants (minimal/full for FY and percent)
10-11. Verification + decomposition
12-13. Minimal struct + full featured
14-15. Flaky task targeting (labor, housing, etc.)
```
**Decision point:** Which few-shot + structure combo works best?

### Week 3: Phase 2 Cont + Ensemble (Lower Confidence)
```
16. No second-guessing prompt
17-19. Ensemble variants
```
**Final submission:** Best from Phase 1+2, expect 72-75%

---

## Local Testing Protocol

For each configuration:
1. Run `run_local_r8.sh` with variant (50 tasks, 2 min timeout)
2. Compare pass rate vs baseline (v21-13h ~80% local)
3. Log:
   - Tasks passed
   - Avg step count
   - Common failure types
   - Time per task

Example output:
```
r11-step-12:
  Pass rate: 75% (75/100)
  Avg steps: 11.8
  Improvement: +2-3% expected in arena
  Common failures: Long calculations (5%), FY conversions (3%)
```

---

## Risk Mitigation

1. **If Phase 1 shows <1% improvement:** Skip to ensemble techniques
2. **If FY-conversions remain flaky:** Add FY↔CY conversion helper
3. **If always-fail tasks spike:** Revert early-termination signal
4. **If local outperforms arena by >10%:** Too much overfitting; cap at turns=12-15

---

## Success Criteria

| Metric | Target | Stretch |
|--------|--------|---------|
| Local baseline (v21-13h simulation) | 68-72% | 75%+ |
| Arena submission score | 72-75% | 76-78% |
| Step count reduction | 12-14 avg | <12 avg |
| Never-pass taskspent < 37 | 35 | 33 |

---

## Appendix: Version Details for Reference

**Current Best (v21-13h-178.8)**
- Pass rate: 80.4%
- Avg steps: 11.1
- Model: minimax-m2.5
- Approach: Forced 4-step decomposition

**Worst Case (v13/v13-1d-150.4)**
- Pass rate: 57.3%
- Avg steps: 17.7-20.8
- Model: minimax-m2.5
- Approach: Free-form exploration

**Key Gap:** 23.1 percentage points with SAME model
→ Optimization lever is purely prompt/approach

# Research & Documentation Index

All research, analysis, and implementation for v21 is documented below.

## 📊 Analysis Documents

### CORRECT_SCORES.md
**What:** Actual correct scores vs arena-reported scores for all versions
**Key Finding:** Arena undercounted scores by 5-13% due to grading bugs
**Contains:**
- Corrected scores table (v8-v20)
- Why arena's scores were wrong
- Breakdown of remaining 68 failures
- Recommended next steps based on failure analysis

### V21_COMPLETE_RESEARCH.md ⭐
**What:** Comprehensive research document with 8 parts
**Key Finding:** Decomposition + pre-built functions expected to reach 75-78%
**Contains:**
- Part 1: Correct scoring methodology
- Part 2: Detailed failure analysis (missing vs wrong numbers)
- Part 3: Why previous approaches failed (v15, SQLite, urllib)
- Part 4: v21 solution design
- Part 5: Implementation details
- Part 6: Risk analysis and mitigation
- Part 7: Research conclusions
- Part 8: Future work suggestions

### V21_STRATEGY.md
**What:** Why decomposition beats SQLite and sub-LLM calls
**Key Finding:** ROI comparison shows v21 is best approach
**Contains:**
- Analysis of 68 failures by type
- Whether pre-built functions help each type
- Detailed breakdown of sub-LLM call costs
- ROI comparison table
- Why v15 (with tools) lost to v20 (without tools)

### ANSWER_TO_YOUR_QUESTION.md
**What:** Direct answer to user's question about decomposition + APIs
**Key Finding:** Yes to decomposition, no to urllib sub-calls
**Contains:**
- Your exact question
- Why sub-LLM calls are overkill
- What v21 implements
- Comparison to alternatives
- Files created and next steps

## 📁 Implementation Documents

### v21/README.md
**What:** Full documentation of v21 approach and architecture
**Contains:**
- Overview of 3 components (decomposition, functions, output)
- Expected improvement breakdown
- 4-step process explanation
- Pre-built function reference
- Testing instructions
- Risk mitigation

### v21/DEPLOY.md
**What:** Step-by-step deployment guide
**Contains:**
- Quick start instructions
- What changed vs v20
- Local testing steps
- Arena monitoring commands
- Troubleshooting guide
- Iteration tips if results are lower than expected

### SQLITE_DB_ANALYSIS.md
**What:** Detailed analysis of whether SQLite DB would help
**Key Finding:** Only 2-4% improvement max, high effort
**Contains:**
- Breakdown of 68 failures
- What SQLite can/can't fix
- Cost-benefit analysis
- Recommendation against SQLite approach

## 🔍 Supporting Analysis

### score_versions.py
**What:** Python script to score all versions correctly
**Usage:** `python3 score_versions.py`
**Outputs:** Corrected scores for v8-v20 using official reward.py logic

### calcs.py
**What:** Raw calculation implementations for v21
**Contains:** 
- sum_values(), arithmetic_mean(), geometric_mean()
- pct_change(), cagr(), stdev_sample(), stdev_population()
- median(), range_val(), kullback_leibler_divergence()

### tools.py
**What:** High-level tools and helpers for v21
**Contains:**
- identify_metric(question) — detect what type of calculation
- identify_time_period(question) — extract year/month info
- calculate(metric, values) — unified calculation interface
- extract_numbers(text) — reliable number extraction
- search_and_extract(pattern) — search files and extract numbers
- verify_answer(answer) — sanity check on answers

## 📋 Memory Saved

### project_v21_decomposition.md
**What:** Project memory for future sessions
**Contains:**
- v21 architecture summary
- Expected results
- Key insights
- Related memories

## 🎯 Quick Reference

### To Understand the Problem
1. Start with: CORRECT_SCORES.md
2. Then read: V21_COMPLETE_RESEARCH.md (Part 2)

### To Understand the Solution
1. Read: V21_STRATEGY.md
2. Then read: v21/README.md
3. For deployment: v21/DEPLOY.md

### To Deploy v21
1. Review: v21/DEPLOY.md (Quick Start section)
2. Run: `cp v21/arena.yaml arena.yaml && arena submit`
3. Grade: `python3 score_versions.py`

### To Understand Why Not SQLite/urllib
1. Read: SQLITE_DB_ANALYSIS.md
2. Or: V21_STRATEGY.md section "Why NOT Sub-LLM Calls"
3. Or: ANSWER_TO_YOUR_QUESTION.md

### To Understand the Approach Directly
1. Read: ANSWER_TO_YOUR_QUESTION.md (answers your exact question)
2. Then: v21/README.md (implementation details)

## 📊 Document Sizes

| Document | Size | Focus |
|----------|------|-------|
| CORRECT_SCORES.md | 4 KB | Grading analysis |
| V21_COMPLETE_RESEARCH.md | 12 KB | Comprehensive research |
| V21_STRATEGY.md | 8 KB | Decision rationale |
| ANSWER_TO_YOUR_QUESTION.md | 6 KB | Your question answered |
| SQLITE_DB_ANALYSIS.md | 4 KB | SQLite cost-benefit |
| v21/README.md | 6 KB | v21 documentation |
| v21/DEPLOY.md | 4 KB | Deployment guide |
| v21/prompt.j2 | 3 KB | 4-step prompt |
| v21/tools.py | 7 KB | Calculation tools |
| v21/calcs.py | 3 KB | Raw implementations |
| **Total** | ~57 KB | Complete analysis |

## 🔄 Document Relationships

```
USER QUESTION
    ↓
    ├─→ ANSWER_TO_YOUR_QUESTION.md [Start here for direct answer]
    │
    ├─→ V21 DESIGN
    │   ├─→ V21_STRATEGY.md [Why this approach]
    │   ├─→ v21/README.md [How it works]
    │   └─→ v21/DEPLOY.md [How to deploy]
    │
    ├─→ ROOT CAUSE ANALYSIS
    │   ├─→ CORRECT_SCORES.md [Problem discovery]
    │   └─→ V21_COMPLETE_RESEARCH.md [Deep analysis]
    │
    └─→ ALTERNATIVES REJECTED
        ├─→ SQLITE_DB_ANALYSIS.md [Why not SQLite]
        └─→ V21_STRATEGY.md [Why not urllib]
```

## 🚀 Next Steps

1. **Understand:** Read ANSWER_TO_YOUR_QUESTION.md (5 min)
2. **Review:** Read v21/README.md (10 min)
3. **Test:** Run `bash v21/test_locally.sh` (2 min)
4. **Deploy:** Follow v21/DEPLOY.md (2 min)
5. **Monitor:** Wait for results (24-48 hours)
6. **Score:** Run `python3 score_versions.py` (1 min)
7. **Iterate:** If <75%, adjust prompt per DEPLOY.md suggestions

## 📝 Important Notes

- All documents are current as of 2026-04-07
- v21 is ready to deploy immediately
- No dependencies beyond standard Python (statistics module)
- All scoring uses official reward.py logic
- Memory saved for future sessions in project_v21_decomposition.md

---

**Status:** ✅ Complete
**Expected Improvement:** +5-8% (75-78% total)
**Deployment:** Ready to submit
**Documentation:** Comprehensive and interconnected


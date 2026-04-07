#!/bin/bash
# A/B test: run two git branches on the same UIDs, 10 workers each
# Usage: ./run_ab_test.sh
# Runs on r1 (8GB, 4 cores) with 20 total workers (10 per variant)

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
TIMESTAMP=$(date +%s)

# Tune set (20) — UIDs we've been tuning on
TUNE="UID0001 UID0003 UID0004 UID0005 UID0008 UID0010 UID0011 UID0021 UID0026 UID0027 UID0028 UID0033 UID0041 UID0050 UID0097 UID0015 UID0017 UID0006 UID0022 UID0035"

# Eval set (60) — never touched, proves generalization
EVAL="UID0007 UID0016 UID0018 UID0019 UID0024 UID0038 UID0040 UID0042 UID0043 UID0045 UID0047 UID0051 UID0055 UID0059 UID0060 UID0070 UID0075 UID0076 UID0077 UID0079 UID0082 UID0087 UID0090 UID0091 UID0095 UID0107 UID0108 UID0109 UID0112 UID0117 UID0118 UID0128 UID0129 UID0135 UID0138 UID0150 UID0158 UID0160 UID0162 UID0164 UID0171 UID0172 UID0175 UID0184 UID0187 UID0194 UID0199 UID0200 UID0204 UID0209 UID0210 UID0212 UID0224 UID0227 UID0228 UID0231 UID0234 UID0237 UID0243 UID0244"

ALL_UIDS="$TUNE $EVAL"

echo "=== A/B TEST ==="
echo "Variant A: main (baseline)"
echo "Variant B: ab/both (suppression + narrative + precompute)"
echo "Tune set: 20 UIDs | Eval set: 60 UIDs | Total: 80"
echo "Workers per variant: 10 | Started: $(date)"
echo ""

# Save current branch
ORIG_BRANCH=$(git rev-parse --abbrev-ref HEAD)

# --- Variant A: checkout main, run in background ---
WORKDIR_A="/tmp/ab_variant_a"
rm -rf "$WORKDIR_A"
git worktree add "$WORKDIR_A" main 2>/dev/null || (git worktree remove "$WORKDIR_A" --force 2>/dev/null; git worktree add "$WORKDIR_A" main)

echo "Launching Variant A (main)..."
(
    cd "$WORKDIR_A"
    export PATH="$HOME/.local/bin:$PATH"
    bash run_parallel.sh 10 $ALL_UIDS > /tmp/ab_variant_a_${TIMESTAMP}.log 2>&1
    echo ""
    echo "=== VARIANT A (main) DONE ==="
    # Split results into tune/eval
    echo "TUNE SET:"
    for uid in $TUNE; do grep "\[$uid\]" /tmp/ab_variant_a_${TIMESTAMP}.log 2>/dev/null; done
    echo "EVAL SET:"
    for uid in $EVAL; do grep "\[$uid\]" /tmp/ab_variant_a_${TIMESTAMP}.log 2>/dev/null; done
) &
PID_A=$!

# --- Variant B: checkout ab/both, run in background ---
WORKDIR_B="/tmp/ab_variant_b"
rm -rf "$WORKDIR_B"
git worktree add "$WORKDIR_B" ab/both 2>/dev/null || (git worktree remove "$WORKDIR_B" --force 2>/dev/null; git worktree add "$WORKDIR_B" ab/both)

echo "Launching Variant B (ab/both)..."
(
    cd "$WORKDIR_B"
    export PATH="$HOME/.local/bin:$PATH"
    bash run_parallel.sh 10 $ALL_UIDS > /tmp/ab_variant_b_${TIMESTAMP}.log 2>&1
    echo ""
    echo "=== VARIANT B (ab/both) DONE ==="
    echo "TUNE SET:"
    for uid in $TUNE; do grep "\[$uid\]" /tmp/ab_variant_b_${TIMESTAMP}.log 2>/dev/null; done
    echo "EVAL SET:"
    for uid in $EVAL; do grep "\[$uid\]" /tmp/ab_variant_b_${TIMESTAMP}.log 2>/dev/null; done
) &
PID_B=$!

echo "Variant A PID: $PID_A"
echo "Variant B PID: $PID_B"
echo ""
echo "Monitor:"
echo "  tail -f /tmp/ab_variant_a_${TIMESTAMP}.log"
echo "  tail -f /tmp/ab_variant_b_${TIMESTAMP}.log"
echo ""
echo "Quick check:"
echo "  grep -cE 'PASS|FAIL' /tmp/ab_variant_a_${TIMESTAMP}.log /tmp/ab_variant_b_${TIMESTAMP}.log"
echo ""

# Wait for both
wait $PID_A $PID_B

echo ""
echo "============================================"
echo "=== A/B TEST COMPLETE ==="
echo "============================================"

# Summary
for variant in a b; do
    LOG="/tmp/ab_variant_${variant}_${TIMESTAMP}.log"
    LABEL=$([ "$variant" = "a" ] && echo "main" || echo "ab/both")
    echo ""
    echo "--- Variant ${variant^^} ($LABEL) ---"

    TUNE_P=0; TUNE_F=0; EVAL_P=0; EVAL_F=0
    for uid in $TUNE; do
        r=$(grep "\[$uid\]" "$LOG" 2>/dev/null | grep -oE 'PASS|FAIL' | head -1)
        [ "$r" = "PASS" ] && TUNE_P=$((TUNE_P+1)) || TUNE_F=$((TUNE_F+1))
    done
    for uid in $EVAL; do
        r=$(grep "\[$uid\]" "$LOG" 2>/dev/null | grep -oE 'PASS|FAIL' | head -1)
        [ "$r" = "PASS" ] && EVAL_P=$((EVAL_P+1)) || EVAL_F=$((EVAL_F+1))
    done
    echo "  Tune set: $TUNE_P/20 pass ($(( TUNE_P * 100 / 20 ))%)"
    echo "  Eval set: $EVAL_P/60 pass ($(( EVAL_P * 100 / 60 ))%)"
    echo "  Combined: $(( TUNE_P + EVAL_P ))/80 pass ($(( (TUNE_P + EVAL_P) * 100 / 80 ))%)"
done

echo ""
echo "DONE $(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Cleanup worktrees
git worktree remove "$WORKDIR_A" --force 2>/dev/null
git worktree remove "$WORKDIR_B" --force 2>/dev/null

#!/bin/bash
# Run the same UIDs with different models for comparison
# Usage: ./run_model_comparison.sh <model> <logfile> [UIDs...]
# Example: ./run_model_comparison.sh deepseek/deepseek-chat-v3-0324 /tmp/model_deepseek.log UID0001 UID0003 UID0004

set -euo pipefail

MODEL="${1:?Usage: $0 <model> <logfile> [UIDs...]}"
LOGFILE="${2:?Usage: $0 <model> <logfile> [UIDs...]}"
shift 2

UIDS=("$@")
if [ ${#UIDS[@]} -eq 0 ]; then
    # Default test set — 10 representative UIDs
    UIDS=(UID0001 UID0003 UID0004 UID0005 UID0008 UID0010 UID0021 UID0027 UID0033 UID0041)
fi

echo "=== Model Comparison: $MODEL ===" | tee "$LOGFILE"
echo "UIDs: ${UIDS[*]}" | tee -a "$LOGFILE"
echo "Started: $(date)" | tee -a "$LOGFILE"
echo "" | tee -a "$LOGFILE"

export GOOSE_MODEL="$MODEL"
export GOOSE_PROVIDER=openrouter

cd "$(dirname "$0")"
bash run_local_v14.sh --batch "${UIDS[@]}" 2>&1 | tee -a "$LOGFILE"

echo "" | tee -a "$LOGFILE"
echo "=== SUMMARY ===" | tee -a "$LOGFILE"
grep -E 'PASS|FAIL|NO_ANS' "$LOGFILE" | grep -oE 'PASS|FAIL|NO_ANS' | sort | uniq -c | tee -a "$LOGFILE"
echo "Finished: $(date)" | tee -a "$LOGFILE"

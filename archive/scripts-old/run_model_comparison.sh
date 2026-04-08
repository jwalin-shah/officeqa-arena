#!/bin/bash
# Run the same UIDs with different models for comparison via Dedalus API
# Usage: ./run_model_comparison.sh <model> <logfile> [UIDs...]
# Example: ./run_model_comparison.sh anthropic/claude-haiku-4-5-20251001 /tmp/model_haiku.log UID0001 UID0003

set -euo pipefail

MODEL="${1:?Usage: $0 <model> <logfile> [UIDs...]}"
LOGFILE="${2:?Usage: $0 <model> <logfile> [UIDs...]}"
shift 2

UIDS=("$@")
if [ ${#UIDS[@]} -eq 0 ]; then
    # Default: 20 representative UIDs (mix of always-pass, flaky, always-fail)
    UIDS=(UID0001 UID0003 UID0005 UID0008 UID0012 UID0021 UID0026 UID0027 UID0029 UID0034 UID0041 UID0047 UID0055 UID0065 UID0074 UID0083 UID0092 UID0101 UID0111 UID0120)
fi

echo "=== Model Comparison: $MODEL ===" | tee "$LOGFILE"
echo "UIDs: ${UIDS[*]}" | tee -a "$LOGFILE"
echo "Tasks: ${#UIDS[@]}" | tee -a "$LOGFILE"
echo "Started: $(date)" | tee -a "$LOGFILE"
echo "" | tee -a "$LOGFILE"

# Use Dedalus API (OpenAI-compatible)
export GOOSE_PROVIDER=openai
export GOOSE_MODEL="$MODEL"
export OPENAI_API_KEY="${DEDALUS_API_KEY:?DEDALUS_API_KEY not set}"
export OPENAI_BASE_PATH="https://api.dedaluslabs.ai/v1/chat/completions"
export GOOSE_DISABLE_KEYRING=true
export GOOSE_MAX_TURNS=40
export GOOSE_TEMPERATURE=0.0
export GOOSE_CONTEXT_LIMIT=128000

cd "$(dirname "$0")"
bash run_local_v24.sh --parallel "${UIDS[@]}" 2>&1 | tee -a "$LOGFILE"

echo "" | tee -a "$LOGFILE"
echo "=== SUMMARY ===" | tee -a "$LOGFILE"
grep -cE 'PASS \(' "$LOGFILE" | xargs -I{} echo "PASS: {}" | tee -a "$LOGFILE"
grep -cE 'FAIL \(' "$LOGFILE" | xargs -I{} echo "FAIL: {}" | tee -a "$LOGFILE"
grep -c 'NO ANSWER' "$LOGFILE" | xargs -I{} echo "NO_ANSWER: {}" | tee -a "$LOGFILE"
echo "Finished: $(date)" | tee -a "$LOGFILE"

#!/bin/bash
# Run multiple tasks in parallel with oracle resources
# Usage: ./run_batch_v7.sh 10    (run 10 random tasks, 5 parallel)
#        ./run_batch_v7.sh 20 10  (run 20 tasks, 10 parallel)

set -euo pipefail
cd "$(dirname "$0")"

N_TASKS="${1:-10}"
N_PARALLEL="${2:-5}"
CSV="/tmp/officeqa_full.csv"

# Get all UIDs
ALL_UIDS=$(python3 -c "
import csv
with open('$CSV') as f:
    uids = [r['uid'] for r in csv.DictReader(f)]
import random
random.shuffle(uids)
for u in uids[:$N_TASKS]:
    print(u)
")

echo "Running $N_TASKS tasks, $N_PARALLEL parallel"
echo "UIDs: $ALL_UIDS" | tr '\n' ' '
echo ""

# Run in parallel batches
RESULTS_FILE="/tmp/arena_batch_results_$(date +%s).txt"
> "$RESULTS_FILE"

run_one() {
    local uid=$1
    timeout 360 ./run_local_v7.sh "$uid" > /tmp/arena_batch_log_${uid}.log 2>&1
    local ans=$(cat /tmp/arena_local_${uid}/answer.txt 2>/dev/null || echo "NONE")
    local expected=$(python3 -c "
import csv
with open('$CSV') as f:
    for r in csv.DictReader(f):
        if r['uid'] == '$uid':
            print(r['answer'])
            break
")
    echo "$uid|$ans|$expected" >> "$RESULTS_FILE"
    echo "  Done: $uid got=$ans expected=$expected"
}

# Export function for xargs
export -f run_one
export CSV RESULTS_FILE

echo "$ALL_UIDS" | xargs -P "$N_PARALLEL" -I{} bash -c 'run_one {}'

echo ""
echo "===== RESULTS ====="
PASS=0
FAIL=0
while IFS='|' read -r uid got expected; do
    # Simple check: strip commas and compare
    got_clean=$(echo "$got" | tr -d ',')
    exp_clean=$(echo "$expected" | tr -d ',')
    if [ "$got_clean" = "$exp_clean" ]; then
        echo "PASS $uid: $got (expected $expected)"
        PASS=$((PASS + 1))
    elif [ "$got" = "NONE" ]; then
        echo "FAIL $uid: NO ANSWER (expected $expected)"
        FAIL=$((FAIL + 1))
    else
        # Check with 1% tolerance
        MATCH=$(python3 -c "
try:
    import re
    got = '$got'.strip()
    exp = '$expected'.strip()
    # Handle arrays
    if got.startswith('[') and exp.startswith('['):
        g = [float(x) for x in re.findall(r'[-\d.]+', got)]
        e = [float(x) for x in re.findall(r'[-\d.]+', exp)]
        if len(g) == len(e) and all(abs(a-b) <= max(0.01*abs(b), 0.01) for a,b in zip(g,e)):
            print('PASS')
        else:
            print('FAIL')
    else:
        g = float(re.sub(r'[,%\$]', '', got))
        e = float(re.sub(r'[,%\$]', '', exp))
        if abs(g - e) <= max(0.01 * abs(e), 0.01):
            print('PASS')
        else:
            print('FAIL')
except:
    print('FAIL')
" 2>/dev/null)
        if [ "$MATCH" = "PASS" ]; then
            echo "PASS $uid: $got ≈ $expected (within 1%)"
            PASS=$((PASS + 1))
        else
            echo "FAIL $uid: $got ≠ $expected"
            FAIL=$((FAIL + 1))
        fi
    fi
done < "$RESULTS_FILE"

echo ""
echo "===== SCORE: $PASS/$((PASS + FAIL)) ($((PASS * 100 / (PASS + FAIL)))%) ====="

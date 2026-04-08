#!/bin/bash
PROMPT_FILE="${1:?Usage: $0 prompt_file UID0004 UID0013 ...}"
shift
PASS=0; FAIL=0; NOANS=0; TOTAL=0
for UID in "$@"; do
    echo ""
    echo "============================================"
    /home/daytona/officeqa-arena/run_sandbox.sh "$UID" "$PROMPT_FILE" 2>&1
    TOTAL=$((TOTAL+1))
    if [ -f /app/answer.txt ]; then
        GOT=$(cat /app/answer.txt)
        TASK_UID_UPPER=$(echo "$UID" | tr "[:lower:]" "[:upper:]")
        TASK_DIR="/tmp/task_${TASK_UID_UPPER}"
        EXPECTED=$(cat "$TASK_DIR/${TASK_UID_UPPER}/answer.txt" 2>/dev/null || echo "0")
        RESULT=$(python3 -c "
got = '''$GOT'''.strip().replace(',','').replace('\$','').replace('%','')
exp = '''$EXPECTED'''.strip().replace(',','').replace('\$','').replace('%','')
try:
    g, e = float(got), float(exp)
    pct = abs(g - e) / abs(e) * 100 if e != 0 else 0
    print('PASS' if pct <= 1 else 'FAIL')
except:
    print('FAIL')
" 2>/dev/null || echo "FAIL")
        if [ "$RESULT" = "PASS" ]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); fi
    else
        NOANS=$((NOANS+1))
    fi
    echo "TALLY: $PASS pass / $FAIL fail / $NOANS noans / $TOTAL total"
done
echo ""
echo "========== FINAL =========="
echo "PASS: $PASS / $TOTAL"
echo "FAIL: $FAIL / $TOTAL"
echo "NO_ANSWER: $NOANS / $TOTAL"
python3 -c "print(f'Rate: {$PASS/$TOTAL*100:.1f}%')" 2>/dev/null

#!/bin/bash
# 3 sandboxes × 3 arena processes each = 9 parallel runs covering all 246 tasks.
# Usage: ./launch-sandboxes.sh
set -e

SNAPSHOT_NAME="officeqa-arena-runner"
OPENROUTER_API_KEY="${OPENROUTER_API_KEY:?Must set OPENROUTER_API_KEY}"
ARENA_TOKEN=$(awk -F' = ' '/token/{print $2}' ~/.arena/credentials 2>/dev/null | head -1)
GH_TOKEN=$(gh auth token 2>/dev/null)

# 246 UIDs split into 9 groups (~27 each), interleaved for even difficulty spread
GROUP1="uid0001,uid0010,uid0019,uid0028,uid0037,uid0046,uid0055,uid0064,uid0073,uid0082,uid0091,uid0100,uid0109,uid0118,uid0127,uid0136,uid0145,uid0154,uid0163,uid0172,uid0181,uid0190,uid0199,uid0208,uid0217,uid0226,uid0235,uid0244"
GROUP2="uid0002,uid0011,uid0020,uid0029,uid0038,uid0047,uid0056,uid0065,uid0074,uid0083,uid0092,uid0101,uid0110,uid0119,uid0128,uid0137,uid0146,uid0155,uid0164,uid0173,uid0182,uid0191,uid0200,uid0209,uid0218,uid0227,uid0236,uid0245"
GROUP3="uid0003,uid0012,uid0021,uid0030,uid0039,uid0048,uid0057,uid0066,uid0075,uid0084,uid0093,uid0102,uid0111,uid0120,uid0129,uid0138,uid0147,uid0156,uid0165,uid0174,uid0183,uid0192,uid0201,uid0210,uid0219,uid0228,uid0237,uid0246"
GROUP4="uid0004,uid0013,uid0022,uid0031,uid0040,uid0049,uid0058,uid0067,uid0076,uid0085,uid0094,uid0103,uid0112,uid0121,uid0130,uid0139,uid0148,uid0157,uid0166,uid0175,uid0184,uid0193,uid0202,uid0211,uid0220,uid0229,uid0238"
GROUP5="uid0005,uid0014,uid0023,uid0032,uid0041,uid0050,uid0059,uid0068,uid0077,uid0086,uid0095,uid0104,uid0113,uid0122,uid0131,uid0140,uid0149,uid0158,uid0167,uid0176,uid0185,uid0194,uid0203,uid0212,uid0221,uid0230,uid0239"
GROUP6="uid0006,uid0015,uid0024,uid0033,uid0042,uid0051,uid0060,uid0069,uid0078,uid0087,uid0096,uid0105,uid0114,uid0123,uid0132,uid0141,uid0150,uid0159,uid0168,uid0177,uid0186,uid0195,uid0204,uid0213,uid0222,uid0231,uid0240"
GROUP7="uid0007,uid0016,uid0025,uid0034,uid0043,uid0052,uid0061,uid0070,uid0079,uid0088,uid0097,uid0106,uid0115,uid0124,uid0133,uid0142,uid0151,uid0160,uid0169,uid0178,uid0187,uid0196,uid0205,uid0214,uid0223,uid0232,uid0241"
GROUP8="uid0008,uid0017,uid0026,uid0035,uid0044,uid0053,uid0062,uid0071,uid0080,uid0089,uid0098,uid0107,uid0116,uid0125,uid0134,uid0143,uid0152,uid0161,uid0170,uid0179,uid0188,uid0197,uid0206,uid0215,uid0224,uid0233,uid0242"
GROUP9="uid0009,uid0018,uid0027,uid0036,uid0045,uid0054,uid0063,uid0072,uid0081,uid0090,uid0099,uid0108,uid0117,uid0126,uid0135,uid0144,uid0153,uid0162,uid0171,uid0180,uid0189,uid0198,uid0207,uid0216,uid0225,uid0234,uid0243"

setup_sandbox() {
  local NAME=$1
  local G1=$2
  local G2=$3
  local G3=$4

  echo "=== [$NAME] Creating ==="
  daytona create --snapshot "$SNAPSHOT_NAME" --name "$NAME" 2>&1 | grep -v "^time=\|level=warning"

  echo "=== [$NAME] Credentials ==="
  daytona exec "$NAME" -- bash -c "echo '[default]' > /root/.arena/credentials && echo 'token = ${ARENA_TOKEN}' >> /root/.arena/credentials" 2>&1 | grep -v "^time=\|level=warning"

  echo "=== [$NAME] Cloning project ==="
  daytona exec "$NAME" -- bash -c "cd /workspace && git clone https://${GH_TOKEN}@github.com/jwalin-shah/officeqa-final final" 2>&1 | grep -v "^time=\|level=warning"

  echo "=== [$NAME] Running 3 parallel groups ==="
  daytona exec "$NAME" -- bash -c "
    export ARENA_NO_AUTO_UPDATE=1
    export PATH=/root/.arena/bin:\$PATH
    export OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
    cd /workspace/final
    arena test --filter 'officeqa-{${G1}}' > /tmp/run1.log 2>&1 &
    arena test --filter 'officeqa-{${G2}}' > /tmp/run2.log 2>&1 &
    arena test --filter 'officeqa-{${G3}}' > /tmp/run3.log 2>&1 &
    wait
    echo DONE
    cat /tmp/run1.log /tmp/run2.log /tmp/run3.log
  " 2>&1 | grep -v "^time=\|level=warning"

  echo "=== [$NAME] Complete ==="
}

# Sandbox 1: groups 1,2,3
setup_sandbox "officeqa-runner-1" "$GROUP1" "$GROUP2" "$GROUP3" &

# Sandbox 2: groups 4,5,6
setup_sandbox "officeqa-runner-2" "$GROUP4" "$GROUP5" "$GROUP6" &

# Sandbox 3: groups 7,8,9
setup_sandbox "officeqa-runner-3" "$GROUP7" "$GROUP8" "$GROUP9" &

wait
echo "=== All 246 tasks complete ==="

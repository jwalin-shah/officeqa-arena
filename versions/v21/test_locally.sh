#!/bin/bash
# Test v21 decomposition approach on a few questions

set -e

PROJECT_ROOT="/Users/jwalinshah/projects/officeqa-arena"
cd "$PROJECT_ROOT"

# Create test directory
TEST_DIR="/tmp/v21_test"
mkdir -p "$TEST_DIR"

# Test UIDs: Mix of easy/hard, different failure types
TEST_UIDS=(
    "officeqa-uid0001"  # Basic sum (v20 got this right)
    "officeqa-uid0004"  # Percent change (v20 failed: missing number)
    "officeqa-uid0005"  # Range calculation (v20 failed: wrong number)
    "officeqa-uid0012"  # Highest spending (v20 failed: wrong row)
    "officeqa-uid0021"  # Gross interest (v20 failed: missing number)
)

echo "========================================"
echo "Testing v21 Decomposition Approach"
echo "========================================"
echo ""

for uid in "${TEST_UIDS[@]}"; do
    echo "Testing $uid..."

    # Check if resources exist
    if [ ! -d ".arena/samples/$uid/resources" ]; then
        echo "  ⚠️ Resources not found, skipping"
        continue
    fi

    # Create test workspace
    WORK_DIR="$TEST_DIR/$uid"
    mkdir -p "$WORK_DIR"
    cp -r ".arena/samples/$uid/resources" "$WORK_DIR/"

    # Run the test using python directly (simulating arena environment)
    python3 << PYTHON_TEST
import sys
import os
from pathlib import Path

# Setup
work_dir = "$WORK_DIR"
os.chdir(work_dir)
sys.path.insert(0, "$PROJECT_ROOT/v21")

# Load question
import json
import csv

gold_answers = {}
questions = {}
with open("$PROJECT_ROOT/data/officeqa_full.csv", "r") as f:
    reader = csv.DictReader(f)
    for row in reader:
        gold_answers[row["uid"]] = row["answer"]
        questions[row["uid"]] = row["question"]

uid = "$uid".replace("officeqa-", "").upper()
question = questions.get(uid, "?")
expected = gold_answers.get(uid, "?")

print(f"  Q: {question[:80]}...")
print(f"  Expected: {expected}")

# Run the model simulation
# For now, just show what would happen
from tools import identify_metric, identify_time_period, extract_numbers

metric = identify_metric(question)
period = identify_time_period(question)

print(f"  Identified metric: {metric}")
print(f"  Time period: {period}")
print()
PYTHON_TEST
done

echo ""
echo "========================================"
echo "Test complete!"
echo "========================================"
echo ""
echo "Next: Compare v21 results to v20 baseline"
echo "To submit to arena: cp arena.yaml .. && arena submit"

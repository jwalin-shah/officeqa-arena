#!/usr/bin/env python3
"""
Quick test of v22 on a small sample of questions.
Usage: python3 test_v22_sample.py [--uids UID1 UID2 ...] [--sample 10] [--parallel 5]
"""
import subprocess
import sys
import csv
from pathlib import Path

CSV_PATH = "/tmp/officeqa_full.csv"
REPO_ROOT = Path(__file__).parent
RUN_SCRIPT = REPO_ROOT / "run_local_v22.sh"

def get_all_uids():
    """Get all UIDs from CSV."""
    uids = []
    with open(CSV_PATH) as f:
        for row in csv.DictReader(f):
            uids.append(row['uid'].upper())
    return uids

def get_sample(n=10):
    """Get a random sample of UIDs."""
    import random
    all_uids = get_all_uids()
    return random.sample(all_uids, min(n, len(all_uids)))

def run_tests(uids, parallel=1):
    """Run tests for given UIDs."""
    if parallel > 1:
        cmd = [str(RUN_SCRIPT), "--parallel"] + list(uids)
        env = f"PARALLEL={parallel}"
        result = subprocess.run(f"{env} {' '.join(cmd)}", shell=True, cwd=REPO_ROOT)
    else:
        cmd = [str(RUN_SCRIPT), "--batch"] + list(uids)
        result = subprocess.run(cmd, cwd=REPO_ROOT)
    return result.returncode

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--uids", nargs="*", help="Specific UIDs to test")
    parser.add_argument("--sample", type=int, default=10, help="Random sample size")
    parser.add_argument("--parallel", type=int, default=1, help="Parallelism level")
    args = parser.parse_args()

    if args.uids:
        test_uids = [uid.upper() for uid in args.uids]
    else:
        test_uids = get_sample(args.sample)

    print(f"Testing {len(test_uids)} questions with v22...")
    print(f"UIDs: {test_uids[:5]}{'...' if len(test_uids) > 5 else ''}")
    print()

    run_tests(test_uids, parallel=args.parallel)

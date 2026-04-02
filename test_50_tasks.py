#!/usr/bin/env python3
"""
Local test of the 50-task split (19 OOM-fix + 31 others).
Tests using Claude as the agent to avoid burning OpenRouter credits.
"""

import sys
import json
from pathlib import Path

# The 50 test UIDs: 19 from OOM-fix run + 31 others
ORIGINAL_19 = [
    "uid0001", "uid0007", "uid0011", "uid0014", "uid0021", "uid0022", "uid0027", "uid0028",
    "uid0034", "uid0053", "uid0114", "uid0118", "uid0153", "uid0161", "uid0165", "uid0179",
    "uid0188", "uid0208", "uid0216"
]

ADDITIONAL_31 = [
    "uid0002", "uid0003", "uid0004", "uid0005", "uid0006", "uid0008", "uid0009", "uid0010",
    "uid0012", "uid0013", "uid0015", "uid0016", "uid0017", "uid0018", "uid0019", "uid0020",
    "uid0023", "uid0024", "uid0025", "uid0026", "uid0029", "uid0030", "uid0031", "uid0032",
    "uid0033", "uid0035", "uid0036", "uid0037", "uid0038", "uid0039", "uid0040"
]

ALL_50 = ORIGINAL_19 + ADDITIONAL_31

def main():
    import argparse
    from test_local_harness import run_test_suite
    
    parser = argparse.ArgumentParser(description="Test 50-task split locally")
    parser.add_argument("--batch", type=int, choices=[1, 2], help="Test batch 1 or 2 (split for manageability)")
    parser.add_argument("--max-turns", type=int, default=15, help="Max turns per question")
    parser.add_argument("--quiet", action="store_true", help="Quiet mode")
    parser.add_argument("--output", type=str, help="Output file for results (JSON)")
    args = parser.parse_args()
    
    # Split 50 into 2 batches of 25 each
    if args.batch == 1:
        test_uids = ALL_50[:25]
        batch_name = "Batch 1: Original 19 + 6 others"
    elif args.batch == 2:
        test_uids = ALL_50[25:]
        batch_name = "Batch 2: Remaining 25 others"
    else:
        test_uids = ALL_50
        batch_name = "Full 50-task suite"
    
    print(f"\n{'='*60}")
    print(f"Testing: {batch_name} ({len(test_uids)} questions)")
    print(f"{'='*60}\n")
    
    results = run_test_suite(
        question_ids=test_uids,
        max_turns=args.max_turns,
        verbose=not args.quiet
    )
    
    # Summary
    passed = sum(1 for r in results if r.get("correct"))
    accuracy = 100 * passed / len(results) if results else 0
    total_tool_calls = sum(len(r.get("tool_calls", [])) for r in results)
    total_elapsed = sum(r.get("elapsed_s", 0) for r in results)
    
    print(f"\n{'='*60}")
    print(f"SUMMARY: {passed}/{len(results)} correct ({accuracy:.1f}%)")
    print(f"Total tool calls: {total_tool_calls}")
    print(f"Total elapsed: {total_elapsed:.1f}s")
    print(f"Avg time per question: {total_elapsed/len(results):.1f}s")
    print(f"{'='*60}\n")
    
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(json.dumps({
            "batch": batch_name,
            "accuracy": accuracy,
            "passed": passed,
            "total": len(results),
            "total_tool_calls": total_tool_calls,
            "total_elapsed_s": total_elapsed,
            "results": results
        }, indent=2))
        print(f"Results saved to: {args.output}")

if __name__ == "__main__":
    main()

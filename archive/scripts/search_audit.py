#!/usr/bin/env python3
"""Audit search_tables quality across all questions.

For each question, runs search_tables and checks:
1. Does the expected source file appear in results?
2. At what rank? With what score?
3. What table families dominate the results?

No LLM calls — just tool evaluation.
"""
import csv
import json
import re
import sys
import time
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server import load_tools


def extract_years(text: str) -> list[int]:
    return [int(y) for y in re.findall(r'\b(1[89]\d{2}|20\d{2})\b', text)]


def extract_search_query(question: str) -> str:
    """Extract a reasonable search query from a question."""
    # Remove common question framing
    q = question.lower()
    # Extract key noun phrases
    q = re.sub(r'\b(what|were|was|how|much|many|using|specifically|only|reported|values|'
               r'for|all|individual|the|of|in|and|to|from|with|that|this|by|'
               r'according|based|on|its|these|corresponding|calculate|compute|'
               r'determine|find|between|rounded|nearest|place|report|return|'
               r'your|answer|as|a|an|not|do|if|or|is|are|has|been|have|had|'
               r'including|should|shouldn|contain|any|figure|value|number|'
               r'total|sum|absolute|percent|difference|mean|average)\b', ' ', q)
    q = re.sub(r'[^a-z0-9\s]', ' ', q)
    q = re.sub(r'\s+', ' ', q).strip()
    # Keep first 8 meaningful tokens
    tokens = [t for t in q.split() if len(t) >= 3][:8]
    return ' '.join(tokens)


def load_questions(csv_path: Path) -> list[dict]:
    questions = []
    with open(csv_path, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            source_files = [s.strip() for s in (row.get('source_files') or '').split('\n') if s.strip()]
            years = extract_years(row.get('question', ''))
            questions.append({
                'uid': row.get('uid', ''),
                'question': row.get('question', ''),
                'answer': row.get('answer', ''),
                'source_files': source_files,
                'years': years,
                'difficulty': row.get('difficulty', ''),
            })
    return questions


def _save_results(results: list[dict], output_path: str) -> None:
    found = sum(1 for r in results if r.get('found'))
    total = len(results)
    errors = sum(1 for r in results if 'error' in r)
    found_ranks = [r['found_rank'] for r in results if r.get('found_rank')]
    output = {
        'summary': {
            'total': total,
            'found': found,
            'not_found': total - found - errors,
            'errors': errors,
            'rank_1': sum(1 for r in found_ranks if r == 1),
            'rank_top3': sum(1 for r in found_ranks if r <= 3),
            'rank_top5': sum(1 for r in found_ranks if r <= 5),
            'rank_top10': sum(1 for r in found_ranks if r <= 10),
        },
        'results': results,
    }
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)


def audit_search(tools, questions: list[dict], output_path: str = '') -> list[dict]:
    results = []
    for i, q in enumerate(questions):
        uid = q['uid']
        query_text = extract_search_query(q['question'])
        years = q['years']
        expected_files = set(q['source_files'])

        year_range = [min(years), max(years)] if years else None

        t0 = time.time()
        try:
            search_result = tools.search_tables(
                query=query_text,
                year_range=year_range,
                limit=15,
            )
        except Exception as e:
            results.append({'uid': uid, 'error': str(e)})
            continue
        elapsed = time.time() - t0

        candidates = search_result.get('candidates', [])
        candidate_files = [c['file_id'] for c in candidates]
        candidate_pks = [c['table_pk'] for c in candidates]

        # Check if expected files appear
        found_files = expected_files & set(candidate_files)
        best_rank = None
        best_score = None
        for rank, c in enumerate(candidates):
            if c['file_id'] in expected_files:
                if best_rank is None:
                    best_rank = rank + 1
                    best_score = c['score']
                break

        results.append({
            'uid': uid,
            'query': query_text[:80],
            'years': years,
            'expected_files': list(expected_files),
            'found': bool(found_files),
            'found_rank': best_rank,
            'found_score': best_score,
            'num_candidates': len(candidates),
            'top_score': candidates[0]['score'] if candidates else None,
            'top_file': candidates[0]['file_id'] if candidates else None,
            'top_title': candidates[0]['table_title'][:60] if candidates else None,
            'elapsed_s': round(elapsed, 3),
        })

        if (i + 1) % 25 == 0:
            found_count = sum(1 for r in results if r.get('found'))
            print(f"  [{i+1}/{len(questions)}] {found_count}/{len(results)} found so far", flush=True)
            # Incremental save
            if output_path:
                _save_results(results, output_path)

    # Final save
    if output_path:
        _save_results(results, output_path)

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', required=True)
    parser.add_argument('--questions', default=str(ROOT / 'data' / 'officeqa_full.csv'))
    parser.add_argument('--output', default='/tmp/search_audit.json')
    parser.add_argument('--limit', type=int, default=0, help='Limit number of questions (0=all)')
    args = parser.parse_args()

    questions = load_questions(Path(args.questions))
    if args.limit > 0:
        questions = questions[:args.limit]
    print(f"Loaded {len(questions)} questions")

    tools = load_tools(db_path=args.db)

    t0 = time.time()
    results = audit_search(tools, questions, output_path=args.output)
    total_time = time.time() - t0

    # Summary stats
    found = sum(1 for r in results if r.get('found'))
    total = len(results)
    errors = sum(1 for r in results if 'error' in r)

    found_ranks = [r['found_rank'] for r in results if r.get('found_rank')]
    rank_1 = sum(1 for r in found_ranks if r == 1)
    rank_top3 = sum(1 for r in found_ranks if r <= 3)
    rank_top5 = sum(1 for r in found_ranks if r <= 5)
    rank_top10 = sum(1 for r in found_ranks if r <= 10)

    not_found = [r for r in results if not r.get('found') and 'error' not in r]

    print(f"\n{'='*60}")
    print(f"Search Audit Results ({total_time:.1f}s total)")
    print(f"{'='*60}")
    print(f"Total questions: {total}")
    print(f"Expected file found in results: {found}/{total} ({100*found/total:.1f}%)")
    print(f"Errors: {errors}")
    print(f"\nRank distribution (of {len(found_ranks)} found):")
    print(f"  Rank 1: {rank_1} ({100*rank_1/max(len(found_ranks),1):.1f}%)")
    print(f"  Top 3:  {rank_top3} ({100*rank_top3/max(len(found_ranks),1):.1f}%)")
    print(f"  Top 5:  {rank_top5} ({100*rank_top5/max(len(found_ranks),1):.1f}%)")
    print(f"  Top 10: {rank_top10} ({100*rank_top10/max(len(found_ranks),1):.1f}%)")

    print(f"\nNot found ({len(not_found)} questions):")
    for r in not_found[:20]:
        print(f"  {r['uid']}: expected={r.get('expected_files')} query={r.get('query','')[:60]}")

    # Write full results
    output = {
        'summary': {
            'total': total,
            'found': found,
            'not_found': len(not_found),
            'errors': errors,
            'rank_1': rank_1,
            'rank_top3': rank_top3,
            'rank_top5': rank_top5,
            'rank_top10': rank_top10,
        },
        'results': results,
    }
    with open(args.output, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nFull results written to {args.output}")


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Grade model comparison results with lenient number extraction.
Usage: python3 grade_model_results.py /tmp/arena_app_UID*/answer.txt
  or:  python3 grade_model_results.py --dir /tmp --uids UID0001,UID0003,...
"""
import csv, re, sys, os

CSV_PATH = os.environ.get('CSV_PATH', '/tmp/officeqa_full.csv')

DEFAULT_UIDS = [
    'UID0001','UID0003','UID0005','UID0008','UID0012','UID0021','UID0026','UID0027',
    'UID0029','UID0034','UID0041','UID0047','UID0055','UID0065','UID0074','UID0083',
    'UID0092','UID0101','UID0111','UID0120'
]

def load_gold(csv_path):
    gold = {}
    with open(csv_path) as f:
        for r in csv.DictReader(f):
            gold[r['uid'].upper()] = r['answer']
    return gold

def extract_number(text):
    """Extract the most likely numeric answer, handling verbose model output."""
    text = text.strip()
    first_line = text.split('\n')[0].strip()

    # Handle array answers like [-1832816, -2049753, 216937]
    arr_match = re.search(r'\[([^\]]+)\]', first_line)
    if arr_match:
        return arr_match.group(0)  # Return the array as-is

    # Clean and find numbers
    cleaned = first_line.replace('$','').replace('%','').strip()
    # Remove markdown bold
    cleaned = cleaned.replace('**','').replace('*','')
    # Find numbers with optional commas, decimals, negative sign
    nums = re.findall(r'-?[\d,]+\.?\d*', cleaned)
    if nums:
        val = nums[0].replace(',','')
        if val and val != '-':
            try:
                return float(val)
            except ValueError:
                pass

    # Try whole text first 5 lines
    for line in text.split('\n')[:5]:
        cleaned = line.replace('$','').replace('%','').replace('**','').replace('*','')
        nums = re.findall(r'-?[\d,]+\.?\d*', cleaned)
        if nums:
            try:
                val = float(nums[0].replace(',',''))
                if abs(val) < 1e12 and val not in range(1800, 2030):  # Skip years
                    return val
            except:
                continue
    return None

def grade(got_raw, expected_raw):
    """Returns (pass, got_value, expected_value, pct_diff)"""
    # Handle array answers
    if expected_raw.strip().startswith('['):
        # Parse array elements by splitting on comma (careful: commas in numbers vs delimiters)
        exp_inner = expected_raw.strip().strip('[]')
        exp_parts = [x.strip() for x in exp_inner.split(',')]
        exp_nums = []
        for p in exp_parts:
            m = re.search(r'-?[\d]+\.?\d*', p)
            if m:
                exp_nums.append(m.group())
        got_str = str(got_raw) if got_raw else ''
        got_nums = re.findall(r'-?[\d.]+', str(got_str).replace(',',''))
        if len(exp_nums) == len(got_nums):
            all_close = all(
                abs(float(g) - float(e)) / max(abs(float(e)), 1e-10) <= 0.01
                for g, e in zip(got_nums, exp_nums)
            )
            if all_close:
                return True, got_raw, expected_raw, 0.0
        return False, got_raw, expected_raw, 100.0

    if got_raw is None:
        return False, None, expected_raw, 100.0

    exp_clean = expected_raw.replace(',','').replace('$','').replace('%','')
    # Remove text like "million", "millions"
    exp_clean = re.sub(r'\s*(million|billion|thousands?)s?\s*', '', exp_clean, flags=re.I).strip()

    try:
        got = float(got_raw) if not isinstance(got_raw, float) else got_raw
        exp = float(exp_clean)
        if exp == 0:
            pct = 0 if got == 0 else 100
        else:
            pct = abs(got - exp) / abs(exp) * 100
        return pct <= 1, got, exp, pct
    except:
        return False, got_raw, expected_raw, 100.0

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dir', default='/tmp', help='Base directory for arena_app_UID* dirs')
    parser.add_argument('--uids', default=None, help='Comma-separated UIDs')
    parser.add_argument('--csv', default=CSV_PATH)
    parser.add_argument('--model', default='unknown', help='Model name for display')
    args = parser.parse_args()

    uids = args.uids.split(',') if args.uids else DEFAULT_UIDS
    gold = load_gold(args.csv)

    passed = 0
    failed = 0
    no_answer = 0

    for uid in uids:
        ans_file = os.path.join(args.dir, f'arena_app_{uid}', 'answer.txt')
        expected = gold.get(uid, '???')

        if not os.path.exists(ans_file) or os.path.getsize(ans_file) == 0:
            print(f'{uid}: NO_ANSWER  expected={expected}')
            no_answer += 1
            continue

        with open(ans_file) as f:
            raw = f.read().strip()

        got_val = extract_number(raw)
        is_pass, got, exp, pct = grade(got_val, expected)

        if is_pass:
            print(f'{uid}: PASS  got={got} expected={exp}')
            passed += 1
        else:
            print(f'{uid}: FAIL  got={got} expected={exp} diff={pct:.1f}%  raw={raw.split(chr(10))[0][:70]}')
            failed += 1

    total = len(uids)
    print(f'\n=== {args.model} ===')
    print(f'PASS: {passed}/{total} ({passed*100//total}%)')
    print(f'FAIL: {failed}  NO_ANSWER: {no_answer}')

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Score a got vs expected answer. Prints PASS or FAIL."""
import ast, base64, re, sys

def parse_num(s):
    s = s.strip().replace(',', '').replace('$', '').replace('%', '')
    m = re.match(r'^([-\d.]+)\s*(billion|million|thousand|B|M|K)s?\b', s, re.I)
    if m:
        v = float(m.group(1))
        u = m.group(2).lower()
        if u in ('billion', 'b'): v *= 1e9
        elif u in ('million', 'm'): v *= 1e6
        elif u in ('thousand', 'k'): v *= 1e3
        return v
    return float(s)

def fuzzy_eq(g, e):
    if e == 0: return g == 0
    return abs(g - e) / abs(e) * 100 <= 1

def score(got_b64, exp_b64):
    got_raw = base64.b64decode(got_b64).decode().strip()
    exp_raw = base64.b64decode(exp_b64).decode().strip()

    # List format: [a, b, c]
    if exp_raw.startswith('[') and got_raw.startswith('['):
        try:
            gl = [float(str(x).replace(',', '').replace('$', '').replace('%', '')) for x in ast.literal_eval(got_raw)]
            el = [float(str(x).replace(',', '').replace('$', '').replace('%', '')) for x in ast.literal_eval(exp_raw)]
            if len(gl) == len(el) and all(fuzzy_eq(g, e) for g, e in zip(gl, el)):
                return 'PASS'
            return 'FAIL'
        except Exception:
            return 'PASS' if got_raw == exp_raw else 'FAIL'

    # Numeric comparison
    try:
        g, e = parse_num(got_raw), parse_num(exp_raw)
        if fuzzy_eq(g, e):
            return 'PASS'
        # Try without unit multiplier (got=140.9 vs exp='140.9 Billion')
        e_raw = float(re.sub(r'[^\d.\-]', '', exp_raw.replace(',', '')))
        if fuzzy_eq(g, e_raw):
            return 'PASS'
        return 'FAIL'
    except Exception:
        # String comparison fallback
        return 'PASS' if got_raw.lower().strip() == exp_raw.lower().strip() else 'FAIL'

if __name__ == '__main__':
    print(score(sys.argv[1], sys.argv[2]))

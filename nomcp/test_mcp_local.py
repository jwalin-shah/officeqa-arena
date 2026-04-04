#!/usr/bin/env python3
"""Local MCP server test harness — replicates the arena environment exactly.

For each question:
1. Creates a temp /app/resources/ dir with the same files the arena provides
2. Starts the MCP server as a subprocess (stdio JSON-RPC)
3. Sends tool calls and evaluates results against ground truth

Usage:
    # Test all always-fail questions from the v2_157 run
    python3 test_mcp_local.py --mode always-fail

    # Test specific UIDs
    python3 test_mcp_local.py --uids UID0001,UID0004,UID0010

    # Test first N questions
    python3 test_mcp_local.py --first 10

    # Test only the MCP server's data retrieval (no LLM)
    python3 test_mcp_local.py --mode retrieval-only --first 20
"""
import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parent.parent
NOMCP_DIR = Path(__file__).parent
MCP_SERVER = NOMCP_DIR / "mcp_server.py"
CORPUS_DIR = REPO_ROOT / "corpus"
JSONS_DIR = Path("/tmp/officeqa_jsons")
CSV_PATH = Path("/tmp/officeqa_full.csv")
TRACES_DIR = NOMCP_DIR / "results" / "traces" / "v2_157"

# ── Load questions + answers ───────────────────────────────────────────

def load_questions() -> list[dict]:
    with open(CSV_PATH) as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["source_files_list"] = [
            s.strip() for s in r["source_files"].strip().split("\n") if s.strip()
        ]
    return rows


def get_always_fail_uids() -> set[str]:
    """Get UIDs that scored 0 in the v2_157 run."""
    fail_uids = set()
    if not TRACES_DIR.exists():
        return fail_uids
    for f in TRACES_DIR.iterdir():
        if not f.name.endswith(".json"):
            continue
        data = json.loads(f.read_text())
        if data.get("reward", 1) == 0:
            uid = f.name.replace("officeqa-", "").replace(".json", "").upper()
            fail_uids.add(uid)
    return fail_uids


# ── Resource setup (replicates arena container) ───────────────────────

def setup_resources(question: dict, tmp_dir: str) -> str:
    """Create /tmp/resources/<uid>/ with the same files the arena provides."""
    res_dir = os.path.join(tmp_dir, "resources")
    os.makedirs(res_dir, exist_ok=True)

    source_files = question["source_files_list"]

    for src_file in source_files:
        base = src_file.replace(".txt", "")  # e.g. treasury_bulletin_1941_01

        # 1. Copy the raw TXT from corpus/
        txt_path = CORPUS_DIR / src_file
        if txt_path.exists():
            shutil.copy2(txt_path, os.path.join(res_dir, src_file))

        # 2. Copy the parsed JSON from /tmp/officeqa_jsons/
        json_name = base + ".json"
        json_path = JSONS_DIR / json_name
        if json_path.exists():
            shutil.copy2(json_path, os.path.join(res_dir, json_name))

    # 3. Create manifest.json (mirrors arena format)
    manifest = {
        "task_id": question["uid"].lower(),
        "question": question["question"],
        "source_files": source_files,
    }
    with open(os.path.join(res_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f)

    return res_dir


# ── MCP client (talks to server via stdio) ────────────────────────────

class MCPClient:
    def __init__(self, resources_dir: str):
        self.proc = subprocess.Popen(
            [sys.executable, str(MCP_SERVER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "RESOURCES_DIR": resources_dir},
            text=True,
        )
        assert self.proc.stdin is not None
        assert self.proc.stdout is not None
        assert self.proc.stderr is not None
        self._stdin = self.proc.stdin
        self._stdout = self.proc.stdout
        self._stderr = self.proc.stderr
        self._msg_id = 0
        # Initialize
        self._call("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-harness", "version": "1.0"},
        })
        self._notify("notifications/initialized", {})

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    def _send(self, msg: dict):
        line = json.dumps(msg) + "\n"
        self._stdin.write(line)
        self._stdin.flush()

    def _recv(self) -> dict:
        line = self._stdout.readline()
        if not line:
            raise RuntimeError("MCP server closed stdout")
        return json.loads(line.strip())

    def _call(self, method: str, params: dict) -> dict:
        msg_id = self._next_id()
        self._send({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params})
        return self._recv()

    def _notify(self, method: str, params: dict):
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def list_tools(self) -> list[dict]:
        resp = self._call("tools/list", {})
        return resp.get("result", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict) -> dict:
        resp = self._call("tools/call", {"name": name, "arguments": arguments})
        result = resp.get("result", {})
        content = result.get("content", [])
        if content and content[0].get("type") == "text":
            return json.loads(content[0]["text"])
        return result

    def close(self):
        try:
            self._stdin.close()
        except Exception:
            pass
        try:
            self.proc.kill()
            self.proc.wait(timeout=3)
        except Exception:
            pass

    @property
    def stderr_output(self) -> str:
        """Non-blocking stderr read after process is killed."""
        try:
            self.proc.kill()
            self.proc.wait(timeout=2)
        except Exception:
            pass
        try:
            return self._stderr.read()
        except Exception:
            return ""


# ── Scoring (matches arena's fuzzy numeric) ───────────────────────────

def parse_numeric(s: str) -> float | None:
    """Parse answer string to numeric value."""
    if not s:
        return None
    s = str(s).strip().replace(",", "").replace("$", "").replace("%", "")
    # Handle parenthetical negatives
    m = re.match(r"^\(([0-9.]+)\)$", s)
    if m:
        s = "-" + m.group(1)
    try:
        return float(s)
    except ValueError:
        return None


def score_answer(predicted: str, ground_truth: str, tolerance: float = 0.01) -> float:
    """Score: 1.0 for match within tolerance, 0.0 otherwise."""
    pred_val = parse_numeric(predicted)
    gt_val = parse_numeric(ground_truth)

    if pred_val is None or gt_val is None:
        # String comparison fallback
        return 1.0 if predicted.strip() == ground_truth.strip() else 0.0

    if gt_val == 0:
        return 1.0 if abs(pred_val) < 0.01 else 0.0

    rel_error = abs(pred_val - gt_val) / abs(gt_val)
    return 1.0 if rel_error <= tolerance else 0.0


# ── Test modes ─────────────────────────────────────────────────────────

def test_retrieval_only(questions: list[dict], verbose: bool = False):
    """Test just the MCP server's find_values — no LLM needed.

    For each question, call find_values with keywords from the question
    and check if the ground truth value appears anywhere in the results.
    """
    print(f"\n{'='*60}")
    print(f"RETRIEVAL TEST: {len(questions)} questions")
    print(f"{'='*60}\n")

    found = 0
    not_found = 0
    errors = 0

    for qi, q in enumerate(questions):
        uid = q["uid"]
        answer = q["answer"]
        question_text = q["question"]

        # Extract search terms from question
        # Simple heuristic: key nouns
        search_query = question_text[:200]

        with tempfile.TemporaryDirectory() as tmp_dir:
            res_dir = setup_resources(q, tmp_dir)
            try:
                client = MCPClient(res_dir)
                stderr = ""

                # Call find_values
                result = client.call_tool("find_values", {"query": search_query})

                stderr = client.stderr_output
                client.close()

                # Check if ground truth appears in results
                gt_val = parse_numeric(answer)
                result_str = json.dumps(result)

                hit = False
                if gt_val is not None:
                    # Check all numeric values in results
                    nums = re.findall(r'-?[\d,]+\.?\d*', result_str)
                    for n in nums:
                        nv = parse_numeric(n)
                        if nv is not None and gt_val != 0 and abs(nv - gt_val) / abs(gt_val) <= 0.01:
                            hit = True
                            break
                        elif gt_val == 0 and nv is not None and abs(nv) < 0.01:
                            hit = True
                            break

                if hit:
                    found += 1
                    status = "FOUND"
                else:
                    not_found += 1
                    status = "MISS"

                # Parse table count from stderr
                table_info = ""
                if stderr:
                    m = re.search(r'Loaded: (\d+) tables', stderr)
                    if m:
                        table_info = f" ({m.group(1)} tables)"

                if verbose or status == "MISS":
                    print(f"[{qi+1:3d}/{len(questions)}] {uid} {status}{table_info}: answer={answer}")
                    if status == "MISS" and verbose:
                        # Show what find_values returned
                        results = result.get("results", [])[:2]
                        for r in results:
                            print(f"    -> {r.get('row_label', '')}: {r.get('value', '')}")

            except Exception as e:
                errors += 1
                print(f"[{qi+1:3d}/{len(questions)}] {uid} ERROR: {e}")
                continue

    print(f"\n{'='*60}")
    print(f"RETRIEVAL RESULTS: {found}/{len(questions)} found ({found/len(questions)*100:.1f}%)")
    print(f"  Missed: {not_found}, Errors: {errors}")
    print(f"{'='*60}")


def test_full_pipeline(questions: list[dict], verbose: bool = False):
    """Test the full MCP server pipeline — simulates what MiniMax would do.

    For each question:
    1. find_values with query keywords + year
    2. If no results, try read_page
    3. compute if math needed
    4. Score against ground truth
    """
    print(f"\n{'='*60}")
    print(f"FULL PIPELINE TEST: {len(questions)} questions")
    print(f"{'='*60}\n")

    correct = 0
    wrong = 0
    errors = 0
    results_log = []

    for qi, q in enumerate(questions):
        uid = q["uid"]
        answer = q["answer"]
        question_text = q["question"]
        difficulty = q.get("difficulty", "")

        with tempfile.TemporaryDirectory() as tmp_dir:
            res_dir = setup_resources(q, tmp_dir)
            try:
                client = MCPClient(res_dir)

                # Extract year from question
                year_match = re.findall(r'\b(1[89]\d{2}|20[0-2]\d)\b', question_text)
                years = sorted(set(year_match))

                # Extract key terms (simplified keyword extraction)
                # Remove common words and focus on domain terms
                terms = question_text.lower()
                for stopword in ["what", "were", "the", "total", "of", "for", "in", "a", "an",
                                 "this", "that", "which", "how", "much", "many", "is", "was",
                                 "u.s", "u.s.", "federal", "government", "million", "millions",
                                 "nominal", "dollars", "dollar", "figure", "should", "include",
                                 "expenditures", "expenditure"]:
                    terms = terms.replace(stopword, " ")
                terms = " ".join(terms.split()[:8])

                # Step 1: find_values
                search_args = {"query": terms}
                if years:
                    search_args["year"] = years[0]

                fv_result = client.call_tool("find_values", search_args)

                # Try to extract a value
                predicted = None
                fv_results = fv_result.get("results", [])

                if fv_results:
                    top = fv_results[0]
                    val = top.get("value", "")
                    if isinstance(val, dict):
                        # Row data — try to find the year column
                        for yr in years:
                            for k, v in val.items():
                                if yr in str(k):
                                    predicted = str(v)
                                    break
                            if predicted:
                                break
                        if not predicted:
                            # Take first numeric value
                            for k, v in val.items():
                                if parse_numeric(str(v)) is not None:
                                    predicted = str(v)
                                    break
                    else:
                        predicted = str(val)

                # Step 2: If no results, try broader search or read_page
                if predicted is None and fv_result.get("status") == "no_results":
                    # Try with just the first source file
                    src = q["source_files_list"][0]
                    rp_result = client.call_tool("read_page", {
                        "filename": src,
                        "pattern": terms.split()[0] if terms.split() else "",
                    })
                    # Can't easily extract from raw text without LLM
                    predicted = "0"

                if predicted is None:
                    predicted = "0"

                client.close()

                # Score
                sc = score_answer(predicted, answer)
                if sc >= 1.0:
                    correct += 1
                    status = "CORRECT"
                else:
                    wrong += 1
                    status = "WRONG"

                results_log.append({
                    "uid": uid,
                    "question": question_text[:100],
                    "answer": answer,
                    "predicted": predicted,
                    "score": sc,
                    "difficulty": difficulty,
                })

                if verbose or status == "WRONG":
                    print(f"[{qi+1:3d}/{len(questions)}] {uid} {status} ({difficulty}): "
                          f"predicted={predicted}, answer={answer}")

            except Exception as e:
                errors += 1
                results_log.append({
                    "uid": uid, "answer": answer, "predicted": "ERROR",
                    "score": 0, "error": str(e),
                })
                print(f"[{qi+1:3d}/{len(questions)}] {uid} ERROR: {e}")

    print(f"\n{'='*60}")
    print(f"PIPELINE RESULTS: {correct}/{len(questions)} correct ({correct/len(questions)*100:.1f}%)")
    print(f"  Wrong: {wrong}, Errors: {errors}")
    print(f"{'='*60}")

    # Save results
    out_path = NOMCP_DIR / "test_mcp_local_results.json"
    with open(out_path, "w") as f:
        json.dump(results_log, f, indent=2)
    print(f"Results saved to {out_path}")


def test_server_startup(questions: list[dict]):
    """Quick test: just start the server for each question and check it loads."""
    print(f"\n{'='*60}")
    print(f"SERVER STARTUP TEST: {len(questions)} questions")
    print(f"{'='*60}\n")

    for qi, q in enumerate(questions[:5]):
        uid = q["uid"]
        with tempfile.TemporaryDirectory() as tmp_dir:
            res_dir = setup_resources(q, tmp_dir)
            files = os.listdir(res_dir)
            client = MCPClient(res_dir)
            tools = client.list_tools()
            stderr = client.stderr_output
            client.close()
            # Parse loaded info
            m = re.search(r'Loaded: (\d+) tables, (\d+) files, (\d+) FTS', stderr)
            if m:
                print(f"  {uid}: {m.group(1)} tables, {m.group(2)} files, {m.group(3)} FTS labels "
                      f"({len(files)} resource files, {len(tools)} tools)")
            else:
                print(f"  {uid}: {len(files)} resource files, {len(tools)} tools, stderr: {stderr[:100]}")


# ── Main ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Local MCP server test harness")
    parser.add_argument("--mode", choices=["retrieval-only", "full", "startup"],
                        default="retrieval-only",
                        help="Test mode")
    parser.add_argument("--uids", type=str, default="",
                        help="Comma-separated UIDs to test (e.g. UID0001,UID0004)")
    parser.add_argument("--first", type=int, default=0,
                        help="Test first N questions")
    parser.add_argument("--always-fail", action="store_true",
                        help="Test only always-fail questions from v2_157")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show detailed output for all questions")
    args = parser.parse_args()

    all_questions = load_questions()
    print(f"Loaded {len(all_questions)} questions from {CSV_PATH}")

    # Filter questions
    if args.uids:
        uid_set = {u.strip().upper() for u in args.uids.split(",")}
        questions = [q for q in all_questions if q["uid"].upper() in uid_set]
        print(f"Filtered to {len(questions)} UIDs: {args.uids}")
    elif args.always_fail:
        fail_uids = get_always_fail_uids()
        questions = [q for q in all_questions if q["uid"].upper() in fail_uids]
        print(f"Filtered to {len(questions)} always-fail questions")
    elif args.first > 0:
        questions = all_questions[:args.first]
        print(f"Testing first {len(questions)} questions")
    else:
        questions = all_questions
        print(f"Testing all {len(questions)} questions")

    if not questions:
        print("No questions matched filters!")
        return

    if args.mode == "startup":
        test_server_startup(questions)
    elif args.mode == "retrieval-only":
        test_retrieval_only(questions, verbose=args.verbose)
    elif args.mode == "full":
        test_full_pipeline(questions, verbose=args.verbose)


if __name__ == "__main__":
    main()

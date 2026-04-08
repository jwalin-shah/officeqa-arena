#!/usr/bin/env python3
"""
Parallel decomposition runner - runs multiple LLM calls concurrently.
"""

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Add current dir to path
sys.path.insert(0, ".")

CORPUS_DIR = os.environ.get("CORPUS_DIR", "./corpus")
API_KEY = os.environ.get("OPENROUTER_API_KEY", "")


def load_questions():
    with open("temp_questions.json", "r") as f:
        return json.load(f)


def call_llm_simple(question):
    """Simple LLM call without the full minimax_solve_v3 imports"""
    import urllib.request

    if not API_KEY:
        return None

    prompt = f"""Decompose this question to understand what data is needed.

QUESTION: {question}

RULES:
- period_type: use "fiscal" ONLY if question says "FY" or "fiscal year". Use "calendar" for "calendar year" or years without fiscal qualifier.
- computation: if question asks "total" or "sum", use "sum". Use "direct" only for single specific values.
- value_format: for calendar year with total/sum, use "monthly_series" (12 months). For fiscal year, use "annual_total".
- data_year: only output the number (e.g., 1940, 1985), not the full question.

Output ONLY JSON starting with {{
  "data_year": "",
  "topic": "",
  "period_type": "",
  "computation": "",
  "value_format": "",
  "years_needed": [],
  "search_terms": [],
  "notes": ""
}}"""

    payload = json.dumps(
        {
            "model": "minimax/minimax-m2.5",
            "messages": [
                {
                    "role": "system",
                    "content": "You are a precise data analyst. Output ONLY valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
            "max_tokens": 1024,
        }
    ).encode()

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=payload,
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode())
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"Error on question: {e}", file=sys.stderr)
        return None


def parse_json_response(text):
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        import re

        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group())
            except:
                pass
    return None


def process_question(q):
    """Process a single question"""
    question = q["question"]
    qid = q["id"]

    response = call_llm_simple(question)
    if not response:
        return {"id": qid, "error": "LLM failed", "question": question}

    result = parse_json_response(response)
    if result:
        return {"id": qid, "result": result, "question": question}

    return {"id": qid, "error": "Parse failed", "raw": response, "question": question}


def main():
    questions = load_questions()
    print(f"Processing {len(questions)} questions with up to 10 concurrent workers...")

    results = []
    completed = 0

    # Use 10 concurrent workers to stay within rate limits while being faster
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(process_question, q): q for q in questions}

        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            completed += 1
            if completed % 20 == 0:
                print(f"Completed {completed}/{len(questions)}...", file=sys.stderr)

    # Sort by id
    results.sort(key=lambda x: x["id"])

    # Save results
    with open("decomposition_results.json", "w") as f:
        json.dump(results, f, indent=2)

    # Summary
    success = sum(1 for r in results if "result" in r)
    failed = sum(1 for r in results if "error" in r)
    print(f"Done! Success: {success}, Failed: {failed}")
    print(f"Saved to decomposition_results.json")


if __name__ == "__main__":
    main()

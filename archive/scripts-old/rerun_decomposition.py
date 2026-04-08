#!/usr/bin/env python3
"""
Re-run decomposition on previously failed questions with improved prompt.
"""

import json
import os
import sys
import urllib.request
import re

API_KEY = os.environ.get("OPENROUTER_API_KEY", "")


def load_questions():
    with open("temp_questions_rerun.json", "r") as f:
        return json.load(f)


def call_llm_simple(question):
    if not API_KEY:
        return None

    prompt = f"""Decompose this question to understand what data is needed.

QUESTION: {question}

RULES:
- period_type: use "fiscal" ONLY if question explicitly says "FY" or "fiscal year". Use "calendar" for "calendar year" or just a year like "in 1940".
- computation: if question asks for "total" or "sum", use "sum" (not "direct"). Only use "direct" if asking for a single specific value.
- value_format: for calendar year with "total" or "sum", use "monthly_series" (sum of 12 months). For fiscal year, use "annual_total".

Output JSON:
- data_year: year(s) to look for
- topic: what data category
- period_type: fiscal OR calendar (be precise!)
- computation: sum OR difference OR percent_change OR geometric_mean OR direct OR average
- value_format: monthly_series OR annual_total OR multi_year
- years_needed: list of all years
- search_terms: keywords
- notes: special handling

Output only valid JSON, starting with {{."""

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
        print(f"Error: {e}", file=sys.stderr)
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
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group())
            except:
                pass
    return None


def process_question(q):
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
    print(f"Re-running {len(questions)} questions with improved prompt...")

    results = []
    for i, q in enumerate(questions):
        result = process_question(q)
        results.append(result)
        if (i + 1) % 5 == 0:
            print(f"Completed {i + 1}/{len(questions)}...", file=sys.stderr)

    # Save results
    with open("decomposition_results_v2.json", "w") as f:
        json.dump(results, f, indent=2)

    # Compare to old results
    with open("decomposition_results.json", "r") as f:
        old_results = json.load(f)

    # Analyze improvements
    improved = 0
    same = 0
    for r in results:
        idx = r["id"]
        old = old_results[idx].get("result", {})
        new = r.get("result", {})

        # Check period_type
        if old.get("period_type") != new.get("period_type"):
            improved += 1
        elif old.get("computation") != new.get("computation"):
            improved += 1
        else:
            same += 1

    print(f"Done! Same: {same}, Improved: {improved}")
    print("Saved to decomposition_results_v2.json")


if __name__ == "__main__":
    main()

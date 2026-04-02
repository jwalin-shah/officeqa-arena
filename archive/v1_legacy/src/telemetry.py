"""Structured telemetry for OfficeQA agent runs.

Logs answer provenance, tool usage, and failure categories
for post-hoc analysis without storing benchmark answers.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class RunTelemetry:
    """Collects structured telemetry for a single question run."""

    def __init__(self, question: str, question_id: str = ""):
        self.question = question
        self.question_id = question_id
        self.start_time = time.time()
        self.tool_calls: list[dict[str, Any]] = []
        self.answer_source: str = ""  # "ledger", "extract_values", "time_series", "grep", "fallback"
        self.answer_provenance: dict[str, Any] = {}
        self.verification_result: dict[str, Any] = {}
        self.failure_category: str = ""  # populated post-hoc
        self.iterations_used: int = 0
        self.final_answer: str = ""

    def log_tool_call(self, name: str, args: dict, result: Any, latency_s: float):
        entry = {
            "tool": name,
            "args_keys": list(args.keys()),
            "latency_s": round(latency_s, 3),
            "result_size": len(json.dumps(result, default=str)) if result else 0,
            "had_error": isinstance(result, dict) and "error" in result,
            "had_results": False,
        }
        if isinstance(result, dict):
            if result.get("results"):
                entry["had_results"] = True
                entry["result_count"] = result.get("count", len(result["results"]))
            elif result.get("rows"):
                entry["had_results"] = True
                entry["result_count"] = len(result["rows"])
            elif result.get("series"):
                entry["had_results"] = True
                entry["result_count"] = len(result["series"])
            if result.get("verdict"):
                entry["had_verdict"] = True
                entry["verdict_confidence"] = result["verdict"].get("confidence")
        self.tool_calls.append(entry)

    def set_answer_source(self, source: str, provenance: dict[str, Any] | None = None):
        self.answer_source = source
        if provenance:
            self.answer_provenance = provenance

    def set_verification(self, result: dict[str, Any]):
        self.verification_result = {
            "verified": result.get("verified", False),
            "warnings_count": len(result.get("warnings", [])),
            "warnings": result.get("warnings", [])[:3],
        }

    def finalize(self, answer: str, iterations: int) -> dict[str, Any]:
        self.final_answer = answer
        self.iterations_used = iterations
        elapsed = time.time() - self.start_time

        # Determine answer source from tool call history
        if not self.answer_source:
            for tc in reversed(self.tool_calls):
                if tc["tool"] == "compute_expression" and not tc["had_error"]:
                    self.answer_source = "compute"
                    break
                elif tc["tool"] == "search_ledger" and tc["had_results"]:
                    self.answer_source = "ledger"
                    break
                elif tc["tool"] == "extract_values" and tc.get("had_verdict"):
                    self.answer_source = "extract_values_verdict"
                    break
                elif tc["tool"] == "extract_values" and tc["had_results"]:
                    self.answer_source = "extract_values"
                    break
                elif tc["tool"] == "grep_corpus" and tc["had_results"]:
                    self.answer_source = "grep"
                    break

        # Tool usage summary
        tool_counts: dict[str, int] = {}
        for tc in self.tool_calls:
            tool_counts[tc["tool"]] = tool_counts.get(tc["tool"], 0) + 1

        return {
            "question_id": self.question_id,
            "elapsed_s": round(elapsed, 2),
            "iterations": self.iterations_used,
            "total_tool_calls": len(self.tool_calls),
            "tool_counts": tool_counts,
            "answer_source": self.answer_source,
            "has_answer": bool(answer),
            "verified": self.verification_result.get("verified"),
            "verification_warnings": self.verification_result.get("warnings_count", 0),
            "failure_category": self.failure_category,
        }


def save_telemetry(entries: list[dict], path: str = "results/telemetry.jsonl"):
    """Append telemetry entries to a JSONL file."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        for entry in entries:
            f.write(json.dumps(entry, default=str) + "\n")

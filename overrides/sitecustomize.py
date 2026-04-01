"""Restrict TerminalTool to answer-file writes only.

Loaded automatically by Python's site.py when PYTHONPATH includes
/installed-agent/overrides.  Installs an import hook (sys.meta_path)
that patches TerminalExecutor.__call__ the moment
openhands.tools.terminal.impl is first imported -- i.e. before the
agent loop starts.

The agent is forced to use MCP tools (search_canonical, search_ledger,
extract_values, compute_expression) for all data retrieval instead of
grep/cat/sed on raw files.
"""

import importlib
import importlib.abc
import re
import sys

# ---------------------------------------------------------------------------
# Allow-list: only these commands may pass through to the real executor.
# Everything else gets a helpful error nudging the agent to MCP tools.
# ---------------------------------------------------------------------------

_ANSWER_FILE = "/app/answer.txt"

_ALLOWED_PATTERNS: list[re.Pattern] = [
    # Empty command  (retrieve pending output from a long-running cmd)
    re.compile(r"^$"),
    # Ctrl-C / Ctrl-D / Ctrl-Z  (interrupt / EOF / suspend signals)
    re.compile(r"^C-[a-z]$"),
    # Write the final answer via echo / printf / tee / cat-heredoc
    re.compile(r"(?:echo|printf)\s.*>\s*" + re.escape(_ANSWER_FILE)),
    re.compile(r"cat\s*<<.*>\s*" + re.escape(_ANSWER_FILE)),
    re.compile(r"tee\s+" + re.escape(_ANSWER_FILE)),
    # Read the answer file back (sanity-check)
    re.compile(r"^cat\s+" + re.escape(_ANSWER_FILE) + r"\s*$"),
    # Package management (setup phase)
    re.compile(r"^(pip3?|python3?\s+-m\s+pip|apt-get|apt)\s"),
    # Harmless filesystem helpers
    re.compile(r"^(mkdir|chmod|ls|pwd|cd|test|true|false)\s"),
    re.compile(r"^(mkdir|chmod|ls|pwd|cd|test|true|false)$"),
    # Python one-liners that write the answer file
    re.compile(r"python.*" + re.escape(_ANSWER_FILE)),
]


def _is_allowed(cmd: str) -> bool:
    """Return True if *cmd* is on the allow-list."""
    cmd = cmd.strip()
    if not cmd:
        return True
    return any(pat.search(cmd) for pat in _ALLOWED_PATTERNS)


# ---------------------------------------------------------------------------
# Import hook -- patches TerminalExecutor.__call__ once, on first import.
# ---------------------------------------------------------------------------

class _TerminalPatchFinder(importlib.abc.MetaPathFinder):
    """Intercepts ``import openhands.tools.terminal.impl`` and patches it."""

    _active = True  # class-level flag to fire only once

    # Python >= 3.4 MetaPathFinder API  (find_module still works in 3.12)
    def find_module(self, fullname, path=None):
        if self._active and fullname == "openhands.tools.terminal.impl":
            return self  # claim we can load it
        return None

    def load_module(self, fullname):
        # Deactivate *before* the real import to avoid infinite recursion.
        type(self)._active = False
        sys.meta_path.remove(self)

        # Let the real loader do its job.
        mod = importlib.import_module(fullname)
        sys.modules[fullname] = mod  # ensure it stays cached

        # Patch TerminalExecutor.__call__
        executor_cls = getattr(mod, "TerminalExecutor", None)
        if executor_cls is not None:
            _original_call = executor_cls.__call__

            def _restricted_call(self_exec, action, conversation=None):
                cmd = getattr(action, "command", "").strip()
                if _is_allowed(cmd):
                    return _original_call(self_exec, action, conversation)

                # ---- blocked ----
                from openhands.tools.terminal.definition import TerminalObservation  # type: ignore[import-not-found]

                return TerminalObservation.from_text(
                    text=(
                        f"BLOCKED: Terminal is restricted to writing {_ANSWER_FILE}.\n"
                        "Use MCP tools for ALL data retrieval:\n"
                        "  search_canonical(query, year)          -- start here\n"
                        "  search_ledger(metric, year)            -- fallback\n"
                        "  extract_values(query, metric, year)    -- raw extraction\n"
                        "  compute_expression(expr, variables)    -- arithmetic\n"
                        "\n"
                        f'To write your answer:  echo -n "VALUE" > {_ANSWER_FILE}'
                    ),
                    command=cmd,
                    exit_code=1,
                )

            executor_cls.__call__ = _restricted_call

        return mod


# Install the hook at interpreter startup (sitecustomize runs before user code).
sys.meta_path.insert(0, _TerminalPatchFinder())

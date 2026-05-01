"""LoggingAndFallbackFilesystemBackend: subclass of deepagents.FilesystemBackend
that logs every ls/glob call as structured JSON.

Phase 2 ships LOGGING ONLY. Fallback is gated on T2/T2.5 producing a
deterministic RED — see plan §2.5 row 'Conditional fallback shipping'.

Logging policy (CP-P1-003):
  - Sanitize path/pattern (strip \\n \\r \\x00, truncate 500 chars) before
    json.dumps to prevent log injection.
  - INFO level: tool name + sanitized path + result count.
  - DEBUG level: raw input arguments (only enabled in diagnostic runs).

Logger name: ``drug_target.fs_backend``
"""

from __future__ import annotations

import json
import logging
import time

from deepagents.backends import FilesystemBackend
from deepagents.backends.protocol import GlobResult, LsResult

logger = logging.getLogger("drug_target.fs_backend")

_LOG_TRUNC = 500


def _sanitize_for_log(value: object) -> str:
    """Strip newlines/CR/null bytes; truncate to _LOG_TRUNC chars (CP-P1-003)."""
    if value is None:
        return ""
    s = str(value).replace("\n", "\\n").replace("\r", "\\r").replace("\x00", "\\x00")
    if len(s) > _LOG_TRUNC:
        s = s[:_LOG_TRUNC] + "...[TRUNCATED]"
    return s


class LoggingAndFallbackFilesystemBackend(FilesystemBackend):
    """Drop-in replacement for FilesystemBackend with structured logging.

    Future T6 will add a fallback branch that engages when ``ls``/``glob``
    return empty for a directory that is non-empty on real disk. The fallback
    is intentionally NOT implemented in Phase 2 — see plan §2.5 row
    "Conditional fallback shipping" and CP-P1-002 conditional gate.
    """

    def ls(self, path: str) -> LsResult:
        result = super().ls(path)
        entries_count = len(result.entries) if result.entries else 0
        logger.info(
            json.dumps(
                {
                    "tool": "ls",
                    "path": _sanitize_for_log(path),
                    "result_count": entries_count,
                    "error": _sanitize_for_log(result.error) if result.error else None,
                    "timestamp": time.time(),
                }
            )
        )
        return result

    def glob(self, pattern: str, path: str = "/") -> GlobResult:
        result = super().glob(pattern, path=path)
        matches_count = len(result.matches) if result.matches else 0
        logger.info(
            json.dumps(
                {
                    "tool": "glob",
                    "pattern": _sanitize_for_log(pattern),
                    "path": _sanitize_for_log(path),
                    "result_count": matches_count,
                    "error": _sanitize_for_log(result.error) if result.error else None,
                    "timestamp": time.time(),
                }
            )
        )
        return result

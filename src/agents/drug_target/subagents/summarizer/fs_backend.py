"""LoggingAndFallbackFilesystemBackend: subclass of deepagents.FilesystemBackend
with two additions:
  1. Structured JSON logging of every ls/glob call.
  2. Auto-normalization of absolute paths to root-relative when the path
     lives inside root_dir and virtual_mode=True. This protects against
     LLM non-determinism — even when the LLM ignores prompt guidance and
     calls ls("/abs/path/data_dir/...") instead of ls("/..."), the backend
     transparently rewrites the path to the virtual root-relative form.

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
    """Drop-in replacement for FilesystemBackend with structured logging and T6 fallback.

    When virtual_mode=True and the LLM passes an absolute disk path that equals
    or descends from root_dir, ``_normalize_virtual_path`` rewrites it to the
    virtual root-relative form before calling super(). This transparently handles
    LLM non-determinism where the model uses absolute paths despite prompt guidance.
    """

    def _normalize_virtual_path(self, path: str) -> tuple[str, bool]:
        """Normalize an absolute path to root-relative if inside root_dir.

        Returns (normalized_path, was_normalized).
        Only engages when virtual_mode=True and path is absolute.
        Out-of-root paths pass through unchanged.
        """
        if not self.virtual_mode:
            return path, False
        try:
            from pathlib import Path as _Path

            if not path or not _Path(path).is_absolute():
                return path, False
            resolved_path = _Path(path).resolve()
            resolved_root = self.cwd.resolve()
            if resolved_path == resolved_root:
                return "/", True
            try:
                relative = resolved_path.relative_to(resolved_root)
                return "/" + str(relative), True
            except ValueError:
                return path, False
        except (OSError, RuntimeError):
            return path, False

    def ls(self, path: str) -> LsResult:
        normalized, was_normalized = self._normalize_virtual_path(path)
        result = super().ls(normalized)
        entries_count = len(result.entries) if result.entries else 0
        log_entry: dict[str, object] = {
            "tool": "ls",
            "path": _sanitize_for_log(normalized),
            "result_count": entries_count,
            "error": _sanitize_for_log(result.error) if result.error else None,
            "timestamp": time.time(),
        }
        if was_normalized:
            log_entry["normalized"] = True
            log_entry["original_path"] = _sanitize_for_log(path)
        logger.info(json.dumps(log_entry))
        return result

    def glob(self, pattern: str, path: str = "/") -> GlobResult:
        normalized, was_normalized = self._normalize_virtual_path(path)
        result = super().glob(pattern, path=normalized)
        matches_count = len(result.matches) if result.matches else 0
        log_entry: dict[str, object] = {
            "tool": "glob",
            "pattern": _sanitize_for_log(pattern),
            "path": _sanitize_for_log(normalized),
            "result_count": matches_count,
            "error": _sanitize_for_log(result.error) if result.error else None,
            "timestamp": time.time(),
        }
        if was_normalized:
            log_entry["normalized"] = True
            log_entry["original_path"] = _sanitize_for_log(path)
        logger.info(json.dumps(log_entry))
        return result

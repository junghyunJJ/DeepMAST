"""RED tests for WriteFileArgGuardMiddleware._normalize_path + __init__(backend_root).

These tests are intentionally RED until Task #6 implements:
  - WriteFileArgGuardMiddleware.__init__(*, backend_root: str | None = None)
  - WriteFileArgGuardMiddleware._normalize_path(args, backend_root) -> dict | ToolMessage

Contract (from plan §2.1.C):
  - Returns updated args dict with normalized file_path, OR a BLOCKED ToolMessage
    with JSON content {"ok": false, "error": "<reason>", ...}
  - Always rejects .. traversal in Path(raw).parts
  - Always rejects empty/non-string file_path (also checks "path" key as fallback)
  - backend_root=None: skips absolute-vs-root check; .. and empty checks still apply
  - backend_root set:
      absolute inside root  -> args with file_path rewritten to relative
      absolute outside root -> BLOCKED ToolMessage
      relative              -> args with file_path unchanged
  - Symlinks resolved via Path.resolve(strict=False) then is_relative_to()
  - Error messages use _redact_path() — no raw filesystem paths in output
"""

from __future__ import annotations

import json
import platform
import unicodedata

import pytest
from langchain_core.messages import ToolMessage

from src.agents.deep_interpreter.middleware.write_file_guard import (
    WriteFileArgGuardMiddleware,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_blocked(result: object) -> bool:
    """Return True if result is a BLOCKED ToolMessage (ok=false JSON content)."""
    if not isinstance(result, ToolMessage):
        return False
    try:
        data = json.loads(result.content)
        return data.get("ok") is False
    except (json.JSONDecodeError, AttributeError):
        return False


def _args(file_path: str) -> dict:
    return {"file_path": file_path, "content": "data"}


# ---------------------------------------------------------------------------
# Backward-compat: no-args construction must still work
# ---------------------------------------------------------------------------

def test_backward_compat_no_args_construction():
    """WriteFileArgGuardMiddleware() with no args must still work (backward compat)."""
    middleware = WriteFileArgGuardMiddleware()
    assert isinstance(middleware, WriteFileArgGuardMiddleware)


def test_backward_compat_patched_request_unchanged():
    """Existing _patched_request behaviour must not regress after __init__ change."""
    from langgraph.prebuilt.tool_node import ToolCallRequest

    middleware = WriteFileArgGuardMiddleware()
    req = ToolCallRequest(
        tool_call={"id": "tc_x", "name": "write_file", "args": {"file_path": "/ok.txt", "content": {"a": 1}}},
        tool=None,
        state={},
        runtime=None,  # type: ignore[arg-type]
    )
    patched = middleware._patched_request(req)
    assert isinstance(patched.tool_call["args"]["content"], str)


# ---------------------------------------------------------------------------
# __init__ with backend_root keyword arg (RED — not yet implemented)
# ---------------------------------------------------------------------------

def test_init_accepts_backend_root_keyword_arg():
    """WriteFileArgGuardMiddleware(backend_root='/abs/root') must be accepted."""
    # Task #6 adds __init__(*, backend_root: str | None = None).
    # Currently raises TypeError because the class has no custom __init__.
    middleware = WriteFileArgGuardMiddleware(backend_root="/abs/root")
    assert isinstance(middleware, WriteFileArgGuardMiddleware)


def test_init_backend_root_none_is_default():
    """WriteFileArgGuardMiddleware() and WriteFileArgGuardMiddleware(backend_root=None) must both work."""
    m1 = WriteFileArgGuardMiddleware()
    m2 = WriteFileArgGuardMiddleware(backend_root=None)
    assert isinstance(m1, WriteFileArgGuardMiddleware)
    assert isinstance(m2, WriteFileArgGuardMiddleware)


# ---------------------------------------------------------------------------
# _normalize_path — core scenarios (RED — method not yet implemented)
# ---------------------------------------------------------------------------

class TestNormalizePathRootPrefixStrip:
    """Scenario 1: absolute path inside root → rewritten to relative."""

    def test_normalize_path_absolute_inside_root_returns_relative(self):
        """Absolute path inside backend_root is stripped to relative path."""
        middleware = WriteFileArgGuardMiddleware(backend_root="/abs/root")
        args = _args("/abs/root/sub/file.json")

        result = middleware._normalize_path(args, backend_root="/abs/root")

        assert isinstance(result, dict), "Expected dict (pass-through), got ToolMessage"
        assert result["file_path"] == "sub/file.json"


class TestNormalizePathOutsideReject:
    """Scenario 2: absolute path outside root → BLOCKED."""

    def test_normalize_path_absolute_outside_root_is_blocked(self):
        """Absolute path outside backend_root must return a BLOCKED ToolMessage."""
        middleware = WriteFileArgGuardMiddleware(backend_root="/abs/root")
        args = _args("/abs/other/file.json")

        result = middleware._normalize_path(args, backend_root="/abs/root")

        assert _is_blocked(result), (
            f"Expected BLOCKED ToolMessage with ok=false, got: {result!r}"
        )


class TestNormalizePathRelativePass:
    """Scenario 3: relative path → passes through unchanged."""

    def test_normalize_path_relative_path_unchanged(self):
        """Relative paths must pass through with file_path unchanged."""
        middleware = WriteFileArgGuardMiddleware(backend_root="/abs/root")
        args = _args("evidence/x.json")

        result = middleware._normalize_path(args, backend_root="/abs/root")

        assert isinstance(result, dict), "Expected dict (pass-through), got ToolMessage"
        assert result["file_path"] == "evidence/x.json"


class TestNormalizePathVirtualRootPass:
    """DeepAgents virtual root paths should resolve under backend_root."""

    def test_normalize_path_virtual_root_file_returns_relative(self):
        middleware = WriteFileArgGuardMiddleware(backend_root="/abs/root")
        args = _args("/interpretation_guide.md")

        result = middleware._normalize_path(args, backend_root="/abs/root")

        assert isinstance(result, dict), "Expected dict (pass-through), got ToolMessage"
        assert result["file_path"] == "interpretation_guide.md"


class TestNormalizePathEmptyReject:
    """Scenario 4: empty file_path → BLOCKED."""

    @pytest.mark.parametrize("backend_root", ["/abs/root", None])
    def test_normalize_path_empty_file_path_is_blocked(self, backend_root):
        """Empty file_path must be rejected regardless of backend_root."""
        middleware = WriteFileArgGuardMiddleware(backend_root=backend_root)
        args = _args("")

        result = middleware._normalize_path(args, backend_root=backend_root)

        assert _is_blocked(result), (
            f"Expected BLOCKED for empty path with backend_root={backend_root!r}, got: {result!r}"
        )


class TestNormalizePathTraversalReject:
    """Scenario 5: .. traversal → BLOCKED."""

    def test_normalize_path_dotdot_traversal_is_blocked(self):
        """Paths containing .. components must be blocked."""
        middleware = WriteFileArgGuardMiddleware(backend_root="/abs/root")
        args = _args("evidence/../../etc/x")

        result = middleware._normalize_path(args, backend_root="/abs/root")

        assert _is_blocked(result), (
            f"Expected BLOCKED for .. traversal, got: {result!r}"
        )

    def test_normalize_path_dotdot_at_start_is_blocked(self):
        """../etc/passwd style traversal must be blocked."""
        middleware = WriteFileArgGuardMiddleware(backend_root="/abs/root")
        args = _args("../etc/passwd")

        result = middleware._normalize_path(args, backend_root="/abs/root")

        assert _is_blocked(result), (
            f"Expected BLOCKED for leading .. traversal, got: {result!r}"
        )


class TestNormalizePathSymlinkContainment:
    """Scenario 6: symlink inside root → passes, rewritten to relative."""

    @pytest.mark.skipif(platform.system() == "Windows", reason="POSIX-only symlink test")
    def test_normalize_path_symlink_inside_root_passes(self, tmp_path):
        """Symlink pointing inside backend_root must be allowed and rewritten."""
        root = tmp_path / "root"
        sub = root / "sub"
        sub.mkdir(parents=True)
        target_file = sub / "x.json"
        target_file.write_text("{}")

        # Create symlink inside root pointing to target inside root
        link = tmp_path / "link"
        link.symlink_to(target_file)

        middleware = WriteFileArgGuardMiddleware(backend_root=str(root))
        args = _args(str(link))

        result = middleware._normalize_path(args, backend_root=str(root))

        assert isinstance(result, dict), (
            f"Symlink inside root should pass, got BLOCKED: {result!r}"
        )
        # Resolved path relative to root should be sub/x.json
        assert result["file_path"] == "sub/x.json"


class TestNormalizePathSymlinkEscape:
    """Scenario 7: symlink escaping root → BLOCKED."""

    @pytest.mark.skipif(platform.system() == "Windows", reason="POSIX-only symlink test")
    def test_normalize_path_symlink_escape_is_blocked(self, tmp_path):
        """Symlink pointing outside backend_root must be blocked."""
        root = tmp_path / "root"
        root.mkdir()

        # Symlink inside root that points to /etc/passwd (outside root)
        link = root / "escape_link"
        link.symlink_to("/etc/passwd")

        middleware = WriteFileArgGuardMiddleware(backend_root=str(root))
        args = _args(str(link))

        result = middleware._normalize_path(args, backend_root=str(root))

        assert _is_blocked(result), (
            f"Symlink escaping root should be BLOCKED, got: {result!r}"
        )


class TestNormalizePathBackendRootNone:
    """Scenarios 8 & 9: backend_root=None — skip absolute check, still reject traversal."""

    def test_normalize_path_backend_root_none_relative_passes(self):
        """Scenario 8: relative path with backend_root=None must pass unchanged."""
        middleware = WriteFileArgGuardMiddleware()
        args = _args("evidence/x.json")

        result = middleware._normalize_path(args, backend_root=None)

        assert isinstance(result, dict), (
            f"Relative path + backend_root=None should pass, got: {result!r}"
        )
        assert result["file_path"] == "evidence/x.json"

    def test_normalize_path_backend_root_none_traversal_still_blocked(self):
        """Scenario 9: .. traversal with backend_root=None must still be blocked."""
        middleware = WriteFileArgGuardMiddleware()
        args = _args("evidence/../etc/x")

        result = middleware._normalize_path(args, backend_root=None)

        assert _is_blocked(result), (
            f".. traversal should be BLOCKED even with backend_root=None, got: {result!r}"
        )


class TestNormalizePathUnicodeNormalization:
    """Scenario 10: NFC and NFD encodings of the same path yield same result."""

    def test_normalize_path_nfc_nfd_same_result(self, tmp_path):
        """NFC and NFD representations of the same filename must normalize identically."""
        # 'súb' — the accent can be NFC (precomposed) or NFD (decomposed)
        nfc_name = unicodedata.normalize("NFC", "súb")   # súb precomposed
        nfd_name = unicodedata.normalize("NFD", "súb")   # su + combining accent

        root = tmp_path / "root"
        # Create directory with NFC name
        target_dir = root / nfc_name
        target_dir.mkdir(parents=True)
        target_file = target_dir / "file.json"
        target_file.write_text("{}")

        backend_root = str(root)
        middleware = WriteFileArgGuardMiddleware(backend_root=backend_root)

        # Build args using NFC path
        nfc_abs_path = str(target_file)
        nfd_abs_path = nfc_abs_path.replace(nfc_name, nfd_name)

        result_nfc = middleware._normalize_path(_args(nfc_abs_path), backend_root=backend_root)
        result_nfd = middleware._normalize_path(_args(nfd_abs_path), backend_root=backend_root)

        # Both must pass (return dict, not BLOCKED)
        assert isinstance(result_nfc, dict), f"NFC path should pass, got: {result_nfc!r}"
        assert isinstance(result_nfd, dict), f"NFD path should pass, got: {result_nfd!r}"

        # Both must normalize to the same relative file_path
        assert result_nfc["file_path"] == result_nfd["file_path"], (
            f"NFC result {result_nfc['file_path']!r} != NFD result {result_nfd['file_path']!r}"
        )


class TestNormalizePathErrorMessagesRedacted:
    """Error messages must use _redact_path() — no full filesystem paths leaked."""

    def test_normalize_path_blocked_message_redacts_path(self, tmp_path):
        """BLOCKED ToolMessage content must not contain the raw filesystem path."""
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside" / "secret.json"

        middleware = WriteFileArgGuardMiddleware(backend_root=str(root))
        args = _args(str(outside))

        result = middleware._normalize_path(args, backend_root=str(root))

        assert _is_blocked(result), "Expected BLOCKED ToolMessage"
        # The raw path from tmp_path should NOT appear verbatim in the error message
        assert str(outside) not in result.content, (
            f"Full path {str(outside)!r} leaked into error message: {result.content!r}"
        )


class TestNormalizePathPathKeyFallback:
    """Falls back to 'path' arg key when 'file_path' is absent."""

    def test_normalize_path_uses_path_key_when_file_path_absent(self):
        """If args has 'path' but not 'file_path', it must still be checked/normalized."""
        middleware = WriteFileArgGuardMiddleware(backend_root="/abs/root")
        args = {"path": "evidence/../etc/x", "content": "data"}  # no 'file_path' key

        result = middleware._normalize_path(args, backend_root="/abs/root")

        assert _is_blocked(result), (
            f".. traversal via 'path' key should be BLOCKED, got: {result!r}"
        )


# ---------------------------------------------------------------------------
# Async coverage: awrap_tool_call path (F2 — CV-P1-001)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_awrap_tool_call_normalizes_root_prefix_async() -> None:
    """awrap_tool_call path: absolute write_file path inside backend_root is rewritten to relative.

    Mirrors TestNormalizePathRootPrefixStrip.test_normalize_path_absolute_inside_root_returns_relative
    but exercises the async awrap_tool_call code path end-to-end (including the
    _normalize_path call embedded inside awrap_tool_call).
    """
    from langgraph.prebuilt.tool_node import ToolCallRequest
    from langchain_core.messages import ToolMessage as _TM

    middleware = WriteFileArgGuardMiddleware(backend_root="/abs/root")

    # Build a real ToolCallRequest with write_file + absolute path inside root
    captured_args: dict = {}

    async def async_handler(req: ToolCallRequest) -> _TM:
        captured_args.update(req.tool_call.get("args") or {})
        return _TM(content="written", tool_call_id=req.tool_call.get("id", ""))

    req = ToolCallRequest(
        tool_call={
            "id": "tc_async_001",
            "name": "write_file",
            "args": {"file_path": "/abs/root/sub/file.json", "content": "data"},
        },
        tool=None,
        state={},
        runtime=None,  # type: ignore[arg-type]
    )

    result = await middleware.awrap_tool_call(req, async_handler)

    # Handler must have been called with the rewritten relative path
    assert isinstance(result, _TM), f"Expected ToolMessage, got {type(result)}"
    assert captured_args.get("file_path") == "sub/file.json", (
        f"awrap_tool_call must rewrite absolute-inside-root to relative; "
        f"got file_path={captured_args.get('file_path')!r}"
    )


@pytest.mark.asyncio
async def test_awrap_tool_call_blocked_path_preserves_tool_call_id() -> None:
    """Blocked write_file responses must keep the originating tool_call_id."""
    from langgraph.prebuilt.tool_node import ToolCallRequest

    middleware = WriteFileArgGuardMiddleware(backend_root="/abs/root")

    async def async_handler(req: ToolCallRequest) -> ToolMessage:
        return ToolMessage(content="unexpected", tool_call_id=req.tool_call.get("id", ""))

    req = ToolCallRequest(
        tool_call={
            "id": "tc_async_blocked",
            "name": "write_file",
            "args": {"file_path": "/abs/other/file.json", "content": "data"},
        },
        tool=None,
        state={},
        runtime=None,  # type: ignore[arg-type]
    )

    result = await middleware.awrap_tool_call(req, async_handler)

    assert isinstance(result, ToolMessage)
    assert _is_blocked(result)
    assert result.tool_call_id == "tc_async_blocked"


@pytest.mark.asyncio
async def test_awrap_tool_call_virtual_root_path_rewrites_to_relative() -> None:
    """awrap_tool_call path: virtual root file path is passed as relative."""
    from langgraph.prebuilt.tool_node import ToolCallRequest

    middleware = WriteFileArgGuardMiddleware(backend_root="/abs/root")
    captured_args: dict = {}

    async def async_handler(req: ToolCallRequest) -> ToolMessage:
        captured_args.update(req.tool_call.get("args") or {})
        return ToolMessage(content="written", tool_call_id=req.tool_call.get("id", ""))

    req = ToolCallRequest(
        tool_call={
            "id": "tc_async_virtual",
            "name": "write_file",
            "args": {"file_path": "/interpretation_guide.md", "content": "data"},
        },
        tool=None,
        state={},
        runtime=None,  # type: ignore[arg-type]
    )

    result = await middleware.awrap_tool_call(req, async_handler)

    assert isinstance(result, ToolMessage)
    assert captured_args.get("file_path") == "interpretation_guide.md"

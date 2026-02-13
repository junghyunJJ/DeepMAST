import os

from functools import lru_cache
from pathlib import Path
from typing import Any

# Shared cancel/skip keywords used across all agents for consistent HITL handling
CANCEL_KEYWORDS: frozenset[str] = frozenset({
    "skip", "no", "reject", "cancel", "n", "아니오", "취소",
})

from langchain_core.messages import (
    AIMessage,
    convert_to_messages,
    filter_messages,
)


@lru_cache(1)
def load_env_file() -> None:
    """프로젝트 루트의 .env 파일을 로드.

    DEPRECATED: This function uses synchronous I/O which can block the event loop in ASGI contexts.
    Use src.base.async_env.load_env_async() for async contexts instead.
    Only use this in synchronous CLI scripts.
    """
    import warnings
    warnings.warn(
        "load_env_file() is deprecated due to blocking I/O. "
        "Use src.base.async_env.load_env_async() for async contexts instead.",
        DeprecationWarning,
        stacklevel=2
    )

    # Keep implementation for backward compatibility with synchronous scripts
    project_root = Path(__file__).parent.parent.parent
    env_path = project_root / '.env'
    if env_path.exists():
        with env_path.open(encoding='utf-8') as f:
            for line in f:
                stripped_line = line.strip()
                if stripped_line.startswith('#') or not stripped_line:
                    continue
                parsed_line = stripped_line
                if '=' in parsed_line:
                    key, value = parsed_line.split('=', 1)
                    value = value.strip('\'"')
                    os.environ[key] = value


def extract_ai_messages_from_response(
    react_agent_response: dict[str, Any],
) -> list[AIMessage]:
    """응답에서 AI 메시지를 추출하는 공통 함수.

    Args:
        react_agent_response: 에이전트 응답 딕셔너리 (full_messages 키 포함)

    Returns:
        List[AIMessage]: 추출된 AI 메시지 리스트
    """
    original_messages = react_agent_response.get('full_messages', [])
    converted_messages = convert_to_messages(original_messages)
    return filter_messages(converted_messages, include_types=[AIMessage])

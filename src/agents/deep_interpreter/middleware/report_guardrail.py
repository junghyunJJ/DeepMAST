from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

from src.agents.deep_interpreter.report_guardrails import run_report_guardrail


class ReportGuardrailMiddleware(AgentMiddleware):
    """Run report validation/repair after interpreter output is complete."""

    def __init__(self, *, data_dir: str | Path | None = None, provider: str | None = None) -> None:
        super().__init__()
        self._data_dir = Path(data_dir).expanduser() if data_dir else None
        self._provider = provider

    def _resolved_data_dir(self) -> Path | None:
        if self._data_dir is not None:
            return self._data_dir
        env_data_dir = os.getenv("DEEP_INTERPRETER_DATA_DIR")
        return Path(env_data_dir).expanduser() if env_data_dir else None

    def _run(self) -> dict[str, Any] | None:
        data_dir = self._resolved_data_dir()
        if data_dir is None:
            return None

        result = run_report_guardrail(data_dir, provider=self._provider)
        if result.get("status") == "skipped":
            return None
        if result.get("status") == "failed":
            final_error_count = result.get("final_error_count", "unknown")
            validation_path = data_dir / "report_validation_final.json"
            raise RuntimeError(
                "Report guardrail failed with "
                f"{final_error_count} hard error(s); see {validation_path}"
            )

        return {
            "messages": [
                AIMessage(
                    content=json.dumps(
                        {"report_guardrail": result},
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
            ]
        }

    def after_agent(
        self, state: AgentState[Any], runtime: Runtime[Any] | None
    ) -> dict[str, Any] | None:
        return self._run()

    async def aafter_agent(
        self, state: AgentState[Any], runtime: Runtime[Any] | None
    ) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._run)

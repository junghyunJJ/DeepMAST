"""Token usage tracker for LangChain/LangGraph agent pipelines.

Captures per-model, per-subagent token usage via LangChain callbacks
and estimates API costs based on known pricing tables.

Usage:
    from scripts.token_tracker import TokenUsageTracker

    tracker = TokenUsageTracker()
    # Add to LangChain callbacks:
    config = {"callbacks": [tracker]}
    # After run:
    tracker.print_summary()
    tracker.save_report("token_usage.json")
"""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

# $/1M tokens (input, output) — updated 2025-06
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-5-nano": (0.10, 0.40),
    # Anthropic
    "claude-sonnet-4-5-20250929": (3.00, 15.00),
    "claude-haiku-4-5-20251001": (0.80, 4.00),
    "claude-opus-4-5-20250414": (15.00, 75.00),
    # Google
    "gemini-2.5-flash": (0.15, 0.60),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-3.1-flash-lite-preview": (0.075, 0.30),
    # OpenRouter (popular)
    "moonshotai/kimi-k2.5": (0.20, 0.80),
    "qwen/qwen3-235b-a22b": (0.20, 0.80),
    "deepseek/deepseek-r1": (0.55, 2.19),
    # Ollama (free, local)
    "qwen3.5:122b": (0.0, 0.0),
    "qwen3:32b": (0.0, 0.0),
}


class TokenUsageTracker(BaseCallbackHandler):
    """Thread-safe LLM token usage tracker with per-model cost estimation."""

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        # run_id -> model name mapping (set on_llm_start, read on_llm_end)
        self._run_models: dict[str, str] = {}
        # Aggregated usage: model -> {input_tokens, output_tokens, calls}
        self._by_model: dict[str, dict[str, int]] = defaultdict(
            lambda: {"input_tokens": 0, "output_tokens": 0, "calls": 0}
        )
        # Per-call log for detailed analysis
        self._call_log: list[dict[str, Any]] = []
        self._start_time = time.time()

    # -- Callbacks ----------------------------------------------------------

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        model = self._extract_model_name(serialized, kwargs)
        with self._lock:
            self._run_models[str(run_id)] = model

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        model = self._extract_model_name(serialized, kwargs)
        with self._lock:
            self._run_models[str(run_id)] = model

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        with self._lock:
            model = self._run_models.pop(str(run_id), "unknown")

        input_tokens = 0
        output_tokens = 0

        # Method 1: usage_metadata on AIMessage (most reliable)
        for batch in response.generations:
            for gen in batch:
                msg = getattr(gen, "message", None)
                if msg is None:
                    continue
                usage = getattr(msg, "usage_metadata", None)
                if usage and isinstance(usage, dict):
                    input_tokens += usage.get("input_tokens", 0)
                    output_tokens += usage.get("output_tokens", 0)

        # Method 2: llm_output fallback (OpenAI-style)
        if input_tokens == 0 and output_tokens == 0 and response.llm_output:
            tu = response.llm_output.get("token_usage", {})
            input_tokens = tu.get("prompt_tokens", 0)
            output_tokens = tu.get("completion_tokens", 0)

        if input_tokens == 0 and output_tokens == 0:
            return  # No usage data available (e.g., Ollama without metrics)

        with self._lock:
            self._by_model[model]["input_tokens"] += input_tokens
            self._by_model[model]["output_tokens"] += output_tokens
            self._by_model[model]["calls"] += 1
            self._call_log.append({
                "timestamp": time.time() - self._start_time,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "tags": tags or [],
            })

    # -- Model name extraction ----------------------------------------------

    @staticmethod
    def _extract_model_name(serialized: dict[str, Any], kwargs: dict) -> str:
        """Extract model name from serialized dict or kwargs."""
        # Try serialized kwargs first
        ser_kwargs = serialized.get("kwargs", {})
        model = ser_kwargs.get("model") or ser_kwargs.get("model_name")
        if model:
            return model

        # Try invocation_params
        inv = kwargs.get("invocation_params", {})
        model = inv.get("model") or inv.get("model_name")
        if model:
            return model

        # Fallback: last element of serialized ID path
        id_path = serialized.get("id", [])
        if id_path:
            return id_path[-1]

        return "unknown"

    # -- Cost estimation ----------------------------------------------------

    def _estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost in USD for a given model and token counts."""
        # Try exact match first, then prefix match
        pricing = MODEL_PRICING.get(model)
        if not pricing:
            for key, val in MODEL_PRICING.items():
                if key in model or model in key:
                    pricing = val
                    break
        if not pricing:
            return 0.0
        input_rate, output_rate = pricing
        return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000

    # -- Reporting ----------------------------------------------------------

    def get_summary(self) -> dict[str, Any]:
        """Return structured usage summary."""
        with self._lock:
            models = dict(self._by_model)

        total_input = sum(m["input_tokens"] for m in models.values())
        total_output = sum(m["output_tokens"] for m in models.values())
        total_calls = sum(m["calls"] for m in models.values())
        total_cost = 0.0

        model_details = []
        for model, usage in sorted(models.items(), key=lambda x: -(x[1]["input_tokens"] + x[1]["output_tokens"])):
            cost = self._estimate_cost(model, usage["input_tokens"], usage["output_tokens"])
            total_cost += cost
            model_details.append({
                "model": model,
                "input_tokens": usage["input_tokens"],
                "output_tokens": usage["output_tokens"],
                "total_tokens": usage["input_tokens"] + usage["output_tokens"],
                "calls": usage["calls"],
                "estimated_cost_usd": round(cost, 4),
            })

        return {
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_input + total_output,
            "total_calls": total_calls,
            "total_estimated_cost_usd": round(total_cost, 4),
            "by_model": model_details,
            "elapsed_seconds": round(time.time() - self._start_time, 1),
        }

    def print_summary(self) -> None:
        """Print human-readable usage summary to stdout."""
        summary = self.get_summary()
        print(f"\n{'=' * 62}")
        print("TOKEN USAGE SUMMARY")
        print(f"{'=' * 62}")
        print(f"  Total calls:        {summary['total_calls']}")
        print(f"  Total input tokens:  {summary['total_input_tokens']:,}")
        print(f"  Total output tokens: {summary['total_output_tokens']:,}")
        print(f"  Total tokens:        {summary['total_tokens']:,}")
        print(f"  Estimated cost:      ${summary['total_estimated_cost_usd']:.4f}")
        print(f"  Elapsed:             {summary['elapsed_seconds']:.1f}s")
        print(f"{'─' * 62}")
        for m in summary["by_model"]:
            print(
                f"  {m['model']:<35s} "
                f"{m['total_tokens']:>10,} tok  "
                f"({m['calls']:>3} calls)  "
                f"${m['estimated_cost_usd']:.4f}"
            )
        print(f"{'=' * 62}\n")

    def save_report(self, path: str | Path) -> None:
        """Save detailed usage report to JSON file."""
        summary = self.get_summary()
        with self._lock:
            summary["call_log"] = list(self._call_log)
        Path(path).write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

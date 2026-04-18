from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import shutil
import statistics
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from langchain.agents import create_agent

logger = logging.getLogger(__name__)

# Mode toggle for B / B' / C experiments (P0.8).
#   B       — kwargs pinned in both arms (null control, kwarg-pinned appendix)
#   B_prime — kwargs stripped from prompt, hint on skill_on arm only
#   C       — all B' behavior + schema isolation on skill_off arm
BENCHMARK_MODE = Literal["B", "B_prime", "C"]

from src.agents.deep_interpreter.agent import DeepInterpreterConfig, _build_skill_registry
from src.agents.deep_interpreter.middleware import WriteFileArgGuardMiddleware
from src.agents.deep_interpreter.subagents.configs import SUBAGENT_CONFIGS
from src.agents.deep_interpreter.subagents.prompts import SUBAGENT_PROMPTS
from src.agents.deep_interpreter.tools.literature import _calculate_coverage
from src.agents.deep_interpreter.tools.standalone_fs import read_file, write_file
from src.agents.model import create_llm
from src.agents.shared.skill_activator import SkillActivator


DEFAULT_CASES_PATH = Path("docs/benchmarks/cci_skill_ablation/cases/cci_full_cases.json")
DEFAULT_RESULTS_ROOT = Path("docs/benchmarks/harness_x_model/results")
DEFAULT_WORKSPACE_ROOT = Path("docs/benchmarks/harness_x_model/workspaces")

MODEL_PRESETS: dict[str, dict[str, Any]] = {
    "qwen3.5:122b": {"provider": "ollama", "model_kwargs": {"model": "qwen3.5:122b"}},
    "qwen3.5:35b": {"provider": "ollama", "model_kwargs": {"model": "qwen3.5:35b"}},
}

CONDITIONS: tuple[dict[str, Any], ...] = (
    {"condition": "strong_off", "model": "qwen3.5:122b", "model_strength": "strong", "skill_on": False},
    {"condition": "strong_on", "model": "qwen3.5:122b", "model_strength": "strong", "skill_on": True},
    {"condition": "weak_off", "model": "qwen3.5:35b", "model_strength": "weak", "skill_on": False},
    {"condition": "weak_on", "model": "qwen3.5:35b", "model_strength": "weak", "skill_on": True},
)

BENCHMARK_APPENDIX_BPRIME_C = """
## Benchmark Mode Override

You are running inside a literature-search benchmark harness.

In this mode, **do not call `load_analysis_data`**. The benchmark workspace already provides the search context:

1. Read `/data_path.txt` to get the workspace directory.
2. Read `/benchmark_case.json` to get the exact benchmark case payload.
3. Extract `search_context` from that file and write it to `/search_context.json`.
4. Run `search_literature_dynamic` using:
   - `genes=search_context["genes"]`
   - `pathways=search_context["pathways"]`
   - `celltypes=search_context["celltypes"]`
   - `disease=search_context["disease"]`
   - `output_path="papers.json"`
   - `data_dir=data_path.strip()`
5. If coverage is still insufficient, you may use `search_literature` or `search_pubmed_advanced` for follow-up searches.
6. Finish only after `/papers.json` exists.

Use the provided benchmark case context directly. Do not inspect raw CSVs or expect a production analysis directory.
""".strip()


# Mode-B appendix — restores the kwarg-pin bullets that `BENCHMARK_APPENDIX_BPRIME_C`
# removed. Used when `benchmark_mode="B"` is selected (null-control experiment: both
# arms pin `enable_lr_pair_queries=True` + `coverage_weighted_sort=True`).
BENCHMARK_APPENDIX_B_PINNED = """
## Benchmark Mode Override

You are running inside a literature-search benchmark harness.

In this mode, **do not call `load_analysis_data`**. The benchmark workspace already provides the search context:

1. Read `/data_path.txt` to get the workspace directory.
2. Read `/benchmark_case.json` to get the exact benchmark case payload.
3. Extract `search_context` from that file and write it to `/search_context.json`.
4. Run `search_literature_dynamic` using:
   - `genes=search_context["genes"]`
   - `pathways=search_context["pathways"]`
   - `celltypes=search_context["celltypes"]`
   - `disease=search_context["disease"]`
   - `output_path="papers.json"`
   - `data_dir=data_path.strip()`
   - `enable_lr_pair_queries=True`
   - `coverage_weighted_sort=True`
5. If coverage is still insufficient, you may use `search_literature` or `search_pubmed_advanced` for follow-up searches.
6. Finish only after `/papers.json` exists.

Use the provided benchmark case context directly. Do not inspect raw CSVs or expect a production analysis directory.
""".strip()


# Legacy alias — preserve backward compat for any external caller still using
# the old name. Points to the B'/C variant (current default mode="C").
BENCHMARK_APPENDIX = BENCHMARK_APPENDIX_BPRIME_C

HARDCODED_SKILL_BLOCK = """## MANDATORY: Skill Evaluation Protocol
The Skill Activator will prompt you to evaluate available skills at the start.
Follow the 3-phase protocol:
- Phase 1: QUICK SCREEN — answer YES (literature search requires skill guides)
- Phase 2: EVALUATE — mark `biomedical-literature-search` as YES, then call
  `read_skill_file(skill_path="<path from harness prompt>")` to load the workflow
- Phase 3: IMPLEMENT — proceed with the 4-phase search workflow from the loaded SKILL.md

**IMPORTANT: Tool distinction**
- `read_skill_file` — for skill documents only (e.g., SKILL.md files)
- `read_file` — for data files only (e.g., /data_path.txt, /papers.json)
Do NOT use `read_file` to load skill documents.
"""

BENCHMARK_SKILL_BLOCK = """## Skill Evaluation Protocol
The benchmark harness appends the active skill list below.
Evaluate only those listed skills and load only the files exposed there.

**IMPORTANT: Tool distinction**
- `read_skill_file` — for skill documents only (e.g., SKILL.md files)
- `read_file` — for data files only (e.g., /data_path.txt, /papers.json, /benchmark_case.json)
Do NOT use `read_file` to load skill documents.
"""


# Reframe B': strip kwarg hints from the production SEARCHER_PROMPT so the LLM
# must decide on its own whether to activate the advanced retrieval kwargs.
# Skill ON arm reintroduces them via BENCHMARK_SKILL_KWARG_HINT below; skill
# OFF arm sees no kwarg guidance and falls back to defaults (False).
_SEARCHER_PROMPT_KWARG_STRIPS: tuple[str, ...] = (
    (
        ",\n"
        "    enable_lr_pair_queries=True,   # SEARCHER opts in to L-R pair query injection\n"
        "    coverage_weighted_sort=True,   # SEARCHER opts in to hub-coverage truncation (auto-enabled by sentinel, this line is documentation belt-and-suspenders)"
    ),
    (
        "# L-R pair queries are generated ONLY when enable_lr_pair_queries=True (SEARCHER only).\n"
        "# When enable_lr_pair_queries=True, coverage_weighted_sort is auto-enabled internally\n"
        "# regardless of caller value (SEARCHER mode sentinel — keeps PLANNER/REPORTER unaffected).\n"
    ),
    (
        " Set `enable_lr_pair_queries=True` to inject L-R pair queries — SEARCHER only;"
        " PLANNER/REPORTER should leave it default (False)."
    ),
    # Architect-flagged behavioral leak: this paragraph describes the exact
    # skill-gated fan-out without naming the kwarg, so a weak OFF-arm LLM
    # could infer "the tool always fans out" and emit matching singleton
    # queries unprompted — contaminating both the ON/OFF signal AND the
    # detection proxy.
    (
        "# Iter-0 also injects deterministic singleton gene queries (one gene per query)\n"
        "# so every input gene gets its own focused BioMCP search and appears in at least\n"
        "# one query slot, regardless of LLM compliance with the prompt instruction.\n"
    ),
)


BENCHMARK_SKILL_KWARG_HINT = """## Advanced Kwargs (activated by biomedical-literature-search skill)

When calling `search_literature_dynamic`, set these kwargs to activate the
full production retrieval pipeline:

- `enable_lr_pair_queries=True` — activates deterministic gene fan-out (one
  BioMCP query per input gene) and hybrid pathway query injection. Without
  this, only LLM-generated queries are used.
- `coverage_weighted_sort=True` — activates hub-coverage greedy truncation
  (selects final 30 papers to maximize gene coverage). Without this, pure
  SJR sort is used.

These kwargs together trigger production SEARCHER behavior. Do not set them
if you lack guidance on which kwargs are appropriate for your task.
""".strip()


@dataclass(slots=True)
class SearchTrialResult:
    case_id: str
    category: str
    lr_pair: str
    condition: str
    model: str
    model_strength: str
    skill_on: bool
    repeat: int
    trial_index: int
    timestamp_utc: str
    total_papers: int = 0
    # Primary endpoint (tag-on, production semantics; REV5 §4 clarified)
    genes_coverage_pct: float = 0.0
    pathways_coverage_pct: float | None = None
    coverage_pass: bool = False
    # Secondary sensitivity endpoint (tag-off; defangs REV5 §1 critique)
    genes_coverage_pct_tagoff: float = 0.0
    pathways_coverage_pct_tagoff: float | None = None
    coverage_pass_tagoff: bool = False
    # BioMCP telemetry (best-effort coarse proxies for REV5 §6 + §8 Gate B)
    biomcp_latency_ms: float = 0.0
    biomcp_error: str | None = None
    biomcp_paper_count_raw: int = 0
    latency_s: float = 0.0
    search_iterations: int | None = None
    think_success: bool | None = None
    # Reframe B': proxy for whether the LLM set enable_lr_pair_queries=True.
    # Inferred from the presence of deterministic singleton gene queries
    # (one query per input gene, no keywords) in saved.generated_queries.
    used_lr_pair_queries: bool | None = None
    n_deterministic_queries: int | None = None
    n_llm_queries: int | None = None
    # Reframe C: L-R co-occurrence (non-saturating quality endpoint).
    lr_cooccurrence_count: int = 0
    lr_cooccurrence_rate: float = 0.0
    # Rev 4 — 3-dimensional primary endpoint (celltype) + audit trail fields.
    # See PREREGISTRATION.md §Primary analysis for why celltype is primary.
    benchmark_mode: str = "C"  # BENCHMARK_MODE; stored as str for msgpack/json compat
    celltypes_coverage_pct: float = 0.0
    celltypes_coverage_pct_tagoff: float = 0.0
    # P0.8.5 resume safety — per-trial SHA-256 of the cases file content.
    cases_sha256: str = ""
    trial_workspace: str = ""
    papers_path: str = ""
    search_context_path: str = ""
    error: str | None = None


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _split_gene_symbol(symbol: str) -> list[str]:
    return [part.strip() for part in str(symbol).split("_") if part and part.strip()]


def _derive_disease_context(bundle: dict[str, Any]) -> str:
    tissue_context = str(bundle.get("tissue_context", "") or "").strip()
    lowered = tissue_context.lower()
    if "breast cancer" in lowered:
        return "breast cancer"
    if tissue_context:
        return tissue_context

    diseases = bundle.get("disease_associations") or []
    if diseases:
        return str(diseases[0]).strip()
    return "cancer"


def normalize_case(case: dict[str, Any]) -> dict[str, Any]:
    bundle = case.get("input_bundle") or {}
    ligand = str(bundle.get("ligand", "")).strip()
    receptor = str(bundle.get("receptor", "")).strip()
    genes = list(dict.fromkeys(_split_gene_symbol(ligand) + _split_gene_symbol(receptor)))
    pathways = [str(x).strip() for x in (bundle.get("pathway_associations") or []) if str(x).strip()]
    celltypes = sorted(
        {
            str(x).strip()
            for x in (bundle.get("ligand_cell_types") or []) + (bundle.get("receptor_cell_types") or [])
            if str(x).strip()
        }
    )
    disease = _derive_disease_context(bundle)

    search_context = {
        "genes": genes,
        "pathways": pathways,
        "celltypes": celltypes,
        "disease": disease,
        "lr_pair": case.get("lr_pair", f"{ligand}-{receptor}"),
        "category": case.get("category", ""),
    }
    return {
        "case_id": case["case_id"],
        "category": case.get("category", ""),
        "lr_pair": case.get("lr_pair", f"{ligand}-{receptor}"),
        "genes": genes,
        "pathways": pathways,
        "celltypes": celltypes,
        "disease": disease,
        "search_context": search_context,
        "raw_case": case,
    }


def load_cases(path: str | Path = DEFAULT_CASES_PATH) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Cases JSON must be a list")
    return payload


def select_pilot_cases(cases: list[dict[str, Any]], per_category: int = 2) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for case in sorted(cases, key=lambda item: str(item["case_id"])):
        grouped.setdefault(str(case.get("category", "")), []).append(case)
    selected: list[dict[str, Any]] = []
    for category in sorted(grouped):
        selected.extend(grouped[category][:per_category])
    return selected


def build_trial_schedule(
    cases: list[dict[str, Any]],
    repeats: int,
    seed: int = 42,
    conditions: tuple[dict[str, Any], ...] = CONDITIONS,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    schedule: list[dict[str, Any]] = []
    trial_index = 1
    ordered_cases = sorted(cases, key=lambda item: str(item["case_id"]))

    for repeat in range(1, repeats + 1):
        case_order = ordered_cases[:]
        rng.shuffle(case_order)
        for case in case_order:
            # Option β with model-stickiness: group conditions by model strength,
            # shuffle skill_on order inside each model block, then randomize
            # which model block runs first. Bounds intra-case model swaps to at
            # most 1 (REV5 §2 target; the previous interleaved shuffle produced
            # ~226 swaps over a 360-trial full run).
            strong = [dict(c) for c in conditions if c["model_strength"] == "strong"]
            weak = [dict(c) for c in conditions if c["model_strength"] == "weak"]
            rng.shuffle(strong)
            rng.shuffle(weak)
            case_conditions = (strong + weak) if rng.random() < 0.5 else (weak + strong)
            for condition in case_conditions:
                schedule.append(
                    {
                        "trial_index": trial_index,
                        "repeat": repeat,
                        "case_id": case["case_id"],
                        **condition,
                    }
                )
                trial_index += 1
    return schedule


def _skill_names_for_trial(skill_on: bool) -> tuple[str, ...]:
    names = ["pubmed-eutils-search", "html-report-generator"]
    if skill_on:
        names.insert(0, "biomedical-literature-search")
    return tuple(names)


def _render_skill_harness_prompt(skill_on: bool) -> str:
    cfg = DeepInterpreterConfig(agent_skill_names=_skill_names_for_trial(skill_on))
    registry = _build_skill_registry(cfg)
    harness = SkillActivator(skill_registry=registry)
    skills_block = harness._format_available_skills()
    return harness._prompt_template.replace("{{available_skills}}", skills_block)


def compose_searcher_prompt(
    skill_on: bool,
    *,
    benchmark_mode: str = "C",
) -> str:
    """Compose the benchmark-mode SEARCHER prompt.

    Mode B: kwargs pinned in BOTH arms via BENCHMARK_APPENDIX_B_PINNED; no
        prompt strips; no skill-only kwarg hint. Null-control experiment.
    Mode B_prime: kwargs stripped from prompt; skill_on arm gets kwarg hint;
        skill_off arm has no hint. OFF arm still sees the full tool schema.
    Mode C: same as B_prime at prompt level; additionally `_searcher_tools`
        applies schema isolation on the OFF arm (handled downstream).
    """
    if benchmark_mode not in ("B", "B_prime", "C"):
        raise ValueError(
            f"benchmark_mode must be one of 'B', 'B_prime', 'C'; got {benchmark_mode!r}"
        )

    base = SUBAGENT_PROMPTS["searcher"].replace(HARDCODED_SKILL_BLOCK, BENCHMARK_SKILL_BLOCK)

    if benchmark_mode == "B":
        # Mode B: do NOT strip kwarg mentions from the prompt; both arms see
        # the production kwarg references. Both arms get the B-pinned appendix
        # (kwarg bullets present). No skill-only hint.
        appendix = BENCHMARK_APPENDIX_B_PINNED
        base = base.strip()
        harness_prompt = _render_skill_harness_prompt(skill_on)
    else:
        # Modes B_prime and C: strip kwarg mentions from the production prompt.
        for section in _SEARCHER_PROMPT_KWARG_STRIPS:
            if section not in base:
                raise RuntimeError(
                    "SEARCHER_PROMPT kwarg strip failed — section missing; "
                    "update _SEARCHER_PROMPT_KWARG_STRIPS to match prompts.py."
                )
            base = base.replace(section, "")
        base = base.strip()
        appendix = BENCHMARK_APPENDIX_BPRIME_C
        harness_prompt = _render_skill_harness_prompt(skill_on)
        if skill_on:
            harness_prompt = f"{harness_prompt}\n\n{BENCHMARK_SKILL_KWARG_HINT}"

    return f"{base}\n\n{appendix}\n\n{harness_prompt}".strip()


def _make_benchmark_search_tool(skill_on: bool) -> Any:
    """Return a (possibly schema-restricted) version of search_literature_dynamic.

    Reframe C: tool-schema isolation.
    - skill_on=True  → original tool unchanged (full schema, LLM sees all kwargs)
    - skill_on=False → wrapper with ``enable_lr_pair_queries`` and
      ``coverage_weighted_sort`` removed from the schema and hardcoded to False.
      The LLM cannot discover hidden parameters.
    """
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field
    from src.agents.deep_interpreter.tools.literature import search_literature_dynamic

    if skill_on:
        return search_literature_dynamic  # original tool with full schema

    # Build a restricted Pydantic model that omits the two kwargs.
    class RestrictedSearchInput(BaseModel):
        genes: list[str] = Field(description="List of gene names from analysis")
        pathways: list[str] = Field(description="List of pathways identified")
        celltypes: list[str] = Field(description="List of cell types in analysis")
        disease: str = Field(description="Disease context")
        max_results: int = Field(default=30, description="Maximum number of papers to return")
        target_gene_coverage: float = Field(default=0.6)
        target_pathway_coverage: float = Field(default=0.5)
        max_iterations: int = Field(default=3)
        enforce_disease_match: bool = Field(default=True)
        output_path: str = Field(default="")
        data_dir: str = Field(default="")
        rerank_mode: str = Field(default="off")
        rerank_top_n: int = Field(default=12)
        rerank_min_confidence: float = Field(default=0.70)
        llm_provider: str = Field(default="")
        sort_by_journal_quality: bool = Field(default=True)
        query_cache: list[dict] | None = Field(default=None)
        record_queries: bool = Field(default=False)
        # NOTE: enable_lr_pair_queries and coverage_weighted_sort intentionally omitted

    def _restricted_search(**kwargs: Any) -> dict:
        # Force hidden kwargs to False
        kwargs["enable_lr_pair_queries"] = False
        kwargs["coverage_weighted_sort"] = False
        # search_literature_dynamic is @tool-decorated (StructuredTool).
        # Call .invoke() instead of direct call to avoid
        # "StructuredTool object is not callable" error.
        return search_literature_dynamic.invoke(kwargs)

    return StructuredTool.from_function(
        func=_restricted_search,
        name="search_literature_dynamic",
        description=search_literature_dynamic.description,
        args_schema=RestrictedSearchInput,
    )


def _searcher_tools(skill_on: bool = True, *, benchmark_mode: str = "C") -> list[Any]:
    """Return searcher tools, applying schema isolation only in mode C OFF arm.

    - Mode B: no schema isolation (both arms use full tool; kwargs pinned via
      appendix text — verified via the mode-parameterized tests in P0.4).
    - Mode B_prime: no schema isolation (LLM may discover kwargs from schema;
      but the prompt strips remove the hints so the OFF arm should default).
    - Mode C: schema isolation active on OFF arm (wrapper forces kwargs to
      False; args_schema hides the two advanced kwargs).
    """
    apply_isolation = benchmark_mode == "C" and not skill_on
    base_tools = []
    for tool in SUBAGENT_CONFIGS["searcher"]["tools"]:
        name = getattr(tool, 'name', '') or ''
        if 'search_literature_dynamic' in name:
            if apply_isolation:
                base_tools.append(_make_benchmark_search_tool(skill_on=False))
            else:
                base_tools.append(tool)  # unrestricted tool
        else:
            base_tools.append(tool)
    return base_tools + [write_file, read_file]


_last_ollama_model: str | None = None
_ollama_lock = threading.Lock()


def _ensure_ollama_model_ready(model_label: str) -> None:
    """Unload other Ollama models before loading ``model_label``.

    Ollama on A100 80GB cannot hold qwen3.5:122b + qwen3.5:35b simultaneously
    (combined ~124GB VRAM). Without explicit unload, the /api/generate endpoint
    wedges silently when a second model needs to load. This helper checks
    /api/ps, unloads any model that isn't ``model_label``, then returns.

    P1.3 hardening: wrap check-then-set in `_ollama_lock` (TOCTOU defense),
    replace bare `except Exception: pass` with typed exceptions + logger.
    """
    import urllib.error
    import urllib.request

    global _last_ollama_model
    with _ollama_lock:
        if _last_ollama_model == model_label:
            return

        base_url = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        try:
            ps_resp = urllib.request.urlopen(f"{base_url}/api/ps", timeout=10).read()
            loaded = json.loads(ps_resp).get("models", [])
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            logger.warning("Ollama /api/ps probe failed (%s); assuming no models loaded.", exc)
            loaded = []

        for m in loaded:
            name = m.get("name", "")
            if name and name != model_label:
                try:
                    req = urllib.request.Request(
                        f"{base_url}/api/generate",
                        data=json.dumps({"model": name, "keep_alive": 0}).encode(),
                        headers={"Content-Type": "application/json"},
                    )
                    urllib.request.urlopen(req, timeout=30)
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    logger.warning("Ollama unload of %s failed: %s", name, exc)

        _last_ollama_model = model_label


def build_searcher_for_trial(
    *,
    model_label: str,
    skill_on: bool,
    workspace_dir: str | Path,
    temperature: float = 0.3,
    benchmark_mode: str = "C",
):
    # P1.2 — SSL preflight warning (Linux only).
    if sys.platform.startswith("linux") and not os.environ.get("SSL_CERT_FILE"):
        import warnings as _warnings
        _warnings.warn(
            "SSL_CERT_FILE is not set. PubMed E-utilities will likely fail with "
            "CERTIFICATE_VERIFY_FAILED and burn recursion_limit=150 silently. "
            "export SSL_CERT_FILE=/etc/pki/tls/certs/ca-bundle.crt",
            RuntimeWarning,
            stacklevel=2,
        )
    _ensure_ollama_model_ready(model_label)
    preset = MODEL_PRESETS[model_label]
    workspace = Path(workspace_dir).expanduser().resolve()
    os.environ["DEEP_INTERPRETER_DATA_DIR"] = str(workspace)
    llm = create_llm(
        provider=preset["provider"],
        temperature=temperature,
        **preset["model_kwargs"],
    )
    # Attach production WriteFileArgGuardMiddleware so qwen models can pass
    # dict / list `content` to write_file without tripping Pydantic's
    # `Input should be a valid string` schema error. Without this middleware,
    # OFF-arm trials loop until recursion limit, producing the
    # papers_not_written failure pattern observed in pilot run 1.
    agent = create_agent(
        model=llm,
        tools=_searcher_tools(skill_on=skill_on, benchmark_mode=benchmark_mode),
        system_prompt=compose_searcher_prompt(skill_on=skill_on, benchmark_mode=benchmark_mode),
        middleware=[WriteFileArgGuardMiddleware()],
    )
    return agent.with_config({"recursion_limit": 150})


def prepare_trial_workspace(
    *,
    workspace_dir: str | Path,
    normalized_case: dict[str, Any],
    clean: bool = True,
) -> Path:
    workspace = Path(workspace_dir).expanduser().resolve()
    if clean and workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "data_path.txt").write_text(str(workspace), encoding="utf-8")
    (workspace / "benchmark_case.json").write_text(
        json.dumps(normalized_case, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return workspace


def build_user_prompt(normalized_case: dict[str, Any]) -> str:
    return (
        "Read /benchmark_case.json, search literature for that benchmark case, "
        "and write /papers.json. Use the provided benchmark case context directly."
    )


def load_completed_trial_indices(results_dir: str | Path) -> set[int]:
    """Return trial_indices whose latest row completed without error.

    Trials whose latest row carries a non-empty ``error`` field are NOT treated
    as completed; the resume loop will retry them. Earlier revisions marked a
    trial as complete as soon as any row existed, silently freezing transient
    failures (``papers_not_written``, BioMCP timeouts, recursion_limit hits)
    into the dataset.
    """
    path = Path(results_dir)
    if not path.exists():
        return set()
    latest: dict[int, dict[str, Any]] = {}
    for item in sorted(path.glob("trial_*.jsonl")):
        for line in item.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            trial_index = payload.get("trial_index")
            if isinstance(trial_index, int):
                latest[trial_index] = payload
    return {idx for idx, payload in latest.items() if not payload.get("error")}


def write_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def run_single_trial(
    *,
    case: dict[str, Any],
    condition: dict[str, Any],
    repeat: int,
    trial_index: int,
    workspace_root: str | Path,
    temperature: float = 0.3,
    benchmark_mode: str = "C",
    cases_sha256: str = "",
) -> SearchTrialResult:
    normalized = normalize_case(case)
    workspace = Path(workspace_root) / f"trial_{trial_index:04d}_{normalized['case_id']}_{condition['condition']}"
    prepare_trial_workspace(workspace_dir=workspace, normalized_case=normalized)

    result = SearchTrialResult(
        case_id=normalized["case_id"],
        category=normalized["category"],
        lr_pair=normalized["lr_pair"],
        condition=condition["condition"],
        model=condition["model"],
        model_strength=condition["model_strength"],
        skill_on=bool(condition["skill_on"]),
        repeat=repeat,
        trial_index=trial_index,
        timestamp_utc=_utc_now(),
        benchmark_mode=benchmark_mode,
        cases_sha256=cases_sha256,
        trial_workspace=str(workspace),
        papers_path=str(workspace / "papers.json"),
        search_context_path=str(workspace / "search_context.json"),
    )

    agent = build_searcher_for_trial(
        model_label=condition["model"],
        skill_on=bool(condition["skill_on"]),
        workspace_dir=workspace,
        temperature=temperature,
        benchmark_mode=benchmark_mode,
    )
    prompt = build_user_prompt(normalized)

    started = time.perf_counter()
    try:
        agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    except Exception as exc:  # pragma: no cover - integration path
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        result.latency_s = round(time.perf_counter() - started, 3)

    papers_file = workspace / "papers.json"
    if not papers_file.exists():
        result.error = result.error or "papers_not_written"
        result.biomcp_latency_ms = round(result.latency_s * 1000.0, 2)
        result.biomcp_paper_count_raw = 0
        result.biomcp_error = result.error
        return result

    saved = json.loads(papers_file.read_text(encoding="utf-8"))
    papers = saved.get("papers", []) if isinstance(saved, dict) else []
    coverage = saved.get("coverage") if isinstance(saved, dict) else None
    if coverage is None:
        coverage = _calculate_coverage(
            papers=papers,
            genes=normalized["genes"],
            pathways=normalized["pathways"],
            celltypes=normalized["celltypes"],
            use_retrieval_tags=True,
        )

    # Secondary sensitivity endpoint — recompute tag-off against the same papers.
    # This exists to demonstrate that any observed skill effect is robust to the
    # retrieval-tag provenance gate criticized in REV5 §1.
    coverage_tagoff = _calculate_coverage(
        papers=papers,
        genes=normalized["genes"],
        pathways=normalized["pathways"],
        celltypes=normalized["celltypes"],
        use_retrieval_tags=False,
    )

    gene_pct = float(coverage.get("genes_coverage_pct", 0.0))
    pathway_pct = coverage.get("pathways_coverage_pct")
    gene_pct_tagoff = float(coverage_tagoff.get("genes_coverage_pct", 0.0))
    pathway_pct_tagoff = coverage_tagoff.get("pathways_coverage_pct")

    result.total_papers = int(coverage.get("total_papers", len(papers)))
    result.genes_coverage_pct = gene_pct
    result.pathways_coverage_pct = None if not normalized["pathways"] else float(pathway_pct or 0.0)
    result.coverage_pass = gene_pct >= 60.0 and (
        not normalized["pathways"] or float(pathway_pct or 0.0) >= 50.0
    )
    result.genes_coverage_pct_tagoff = gene_pct_tagoff
    result.pathways_coverage_pct_tagoff = (
        None if not normalized["pathways"] else float(pathway_pct_tagoff or 0.0)
    )
    result.coverage_pass_tagoff = gene_pct_tagoff >= 60.0 and (
        not normalized["pathways"] or float(pathway_pct_tagoff or 0.0) >= 50.0
    )
    # Rev 4 — celltype coverage (primary endpoint, per PREREGISTRATION.md).
    result.celltypes_coverage_pct = float(coverage.get("celltypes_coverage_pct", 0.0) or 0.0)
    result.celltypes_coverage_pct_tagoff = float(
        coverage_tagoff.get("celltypes_coverage_pct", 0.0) or 0.0
    )
    result.search_iterations = saved.get("iterations")
    result.think_success = saved.get("think_success")

    # Reframe B' proxy: detect whether the LLM activated enable_lr_pair_queries.
    # When True, iter-0 emits one deterministic singleton query per input gene
    # (genes=[single_gene], keywords=[]). Absence across all input genes is
    # strong evidence the kwarg defaulted to False.
    queries = saved.get("generated_queries") if isinstance(saved, dict) else None
    if isinstance(queries, list):
        input_genes = {g.upper() for g in normalized["genes"]}
        deterministic_singletons = 0
        llm_queries = 0
        for q in queries:
            if not isinstance(q, dict):
                continue
            genes = q.get("genes") or []
            keywords = q.get("keywords") or []
            if len(genes) == 1 and not keywords and str(genes[0]).upper() in input_genes:
                deterministic_singletons += 1
            else:
                llm_queries += 1
        result.n_deterministic_queries = deterministic_singletons
        result.n_llm_queries = llm_queries
        # Architect-hardened proxy: every input gene must have its own
        # singleton slot AND the LLM must have emitted at least one non-
        # singleton query. The latter rules out the degenerate case where
        # the LLM naturally produces only gene-singleton queries (2-gene
        # cases like EGF/RACK1 would trivially match otherwise).
        result.used_lr_pair_queries = (
            len(input_genes) > 0
            and deterministic_singletons >= len(input_genes)
            and llm_queries >= 1
        )

    # Reframe C: L-R co-occurrence — count papers mentioning BOTH ligand
    # AND receptor in title+abstract. Non-saturating quality endpoint.
    import re as _re
    lr_pair = normalized["search_context"].get("lr_pair", "")
    lr_parts = [p.strip() for p in lr_pair.split("-") if p.strip()]
    if len(lr_parts) >= 2:
        lig_pat = _re.compile(rf"\b{_re.escape(lr_parts[0])}\b", _re.IGNORECASE)
        rec_pat = _re.compile(rf"\b{_re.escape(lr_parts[1])}\b", _re.IGNORECASE)
        lr_cooccur = 0
        for p in papers:
            text = f"{p.get('title', '')} {p.get('abstract', '')}"
            if lig_pat.search(text) and rec_pat.search(text):
                lr_cooccur += 1
        result.lr_cooccurrence_count = lr_cooccur
        result.lr_cooccurrence_rate = round(lr_cooccur / len(papers), 4) if papers else 0.0

    # BioMCP telemetry (best-effort). Precise instrumentation of
    # _search_with_biomcp is Tier-2 work; for now we use total trial latency and
    # the saved papers count as coarse proxies. REV5 §6 outage rule keys on
    # ``biomcp_paper_count_raw == 0 AND biomcp_latency_ms > 30_000``.
    result.biomcp_latency_ms = round(result.latency_s * 1000.0, 2)
    result.biomcp_paper_count_raw = len(papers)
    saved_error = saved.get("error") if isinstance(saved, dict) else None
    if saved_error:
        result.biomcp_error = str(saved_error)
    elif result.error:
        result.biomcp_error = result.error
    return result


def summarize_results(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_condition: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_condition.setdefault(str(row["condition"]), []).append(row)

    summary = {
        "generated_at": _utc_now(),
        "trial_count": len(rows),
        "conditions": {},
    }
    for condition, condition_rows in sorted(by_condition.items()):
        n = len(condition_rows)
        coverage_passes = sum(1 for row in condition_rows if row.get("coverage_pass"))
        summary["conditions"][condition] = {
            "n": n,
            "coverage_pass_rate": round(coverage_passes / n, 4) if n else 0.0,
            "mean_genes_coverage_pct": round(
                sum(float(row.get("genes_coverage_pct", 0.0)) for row in condition_rows) / n, 3
            ) if n else 0.0,
            "mean_total_papers": round(
                sum(float(row.get("total_papers", 0.0)) for row in condition_rows) / n, 3
            ) if n else 0.0,
            "mean_latency_s": round(
                sum(float(row.get("latency_s", 0.0)) for row in condition_rows) / n, 3
            ) if n else 0.0,
            "errors": sum(1 for row in condition_rows if row.get("error")),
        }
    return summary


def load_trial_rows(results_dir: str | Path) -> list[dict[str, Any]]:
    """Return one row per trial_index — the latest successful retry wins.

    When a trial errors (``papers_not_written``, transient BioMCP failure) and
    is later retried via the resume path, both rows are appended to the same
    JSONL file. Downstream analysis (``summarize_results``, ``check_pilot_gates``,
    ``harness_x_model_glmm.R``) must not see stale error rows; we dedupe by
    ``trial_index`` keeping the latest non-error row, falling back to the
    latest row overall if every attempt failed.
    """
    base = Path(results_dir)
    if not base.exists():
        return []
    latest_ok: dict[int, dict[str, Any]] = {}
    latest_any: dict[int, dict[str, Any]] = {}
    for path in sorted(base.glob("trial_*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            trial_index = payload.get("trial_index")
            if not isinstance(trial_index, int):
                continue
            latest_any[trial_index] = payload
            if not payload.get("error"):
                latest_ok[trial_index] = payload
    return [latest_ok.get(idx, latest_any[idx]) for idx in sorted(latest_any)]


# ---------------------------------------------------------------------------
# P0.8.5 — Resume safety guards (mode coherence + cases-hash coherence)
# ---------------------------------------------------------------------------


def compute_cases_sha256(cases_path: str | Path) -> str:
    """SHA-256 of the cases file content. ~1ms on ~100KB.

    Used both as a per-trial audit field (`SearchTrialResult.cases_sha256`) and
    as the integrity check for resume (`check_cases_coherence`).
    """
    return hashlib.sha256(Path(cases_path).read_bytes()).hexdigest()


def check_mode_coherence(results_dir: str | Path, requested_mode: str) -> None:
    """Abort if resume attempts a different benchmark_mode than existing trials.

    Empty results dir → no-op (first run).
    Legacy rows missing ``benchmark_mode`` → warn + skip (pre-P0.8 archives).
    Mode mismatch → SystemExit with recovery hints.
    """
    rows = load_trial_rows(results_dir)
    if not rows:
        return
    existing = rows[0].get("benchmark_mode")
    if existing is None or existing == "":
        logger.warning(
            "check_mode_coherence: existing rows in %s lack benchmark_mode field "
            "(pre-P0.8 archive); cannot verify mode coherence on resume. "
            "Assuming requested mode '%s' is intentional.",
            results_dir, requested_mode,
        )
        return
    if existing != requested_mode:
        raise SystemExit(
            f"Mode mismatch: existing trials in {results_dir} used benchmark_mode='{existing}', "
            f"but --mode='{requested_mode}' was passed. Mixing modes would corrupt the pilot. "
            f"Recovery: (a) pass --mode={existing} to resume, OR "
            f"(b) use a different --results-dir, OR (c) archive existing dir and start fresh."
        )


def check_cases_coherence(results_dir: str | Path, current_sha: str) -> None:
    """Abort if the cases file was modified since the pilot started.

    The deterministic schedule (`build_trial_schedule(cases, ..., seed=42)`)
    depends on stable case ordering/content. Any mutation → trial_index N
    maps to a different (case, condition, repeat) tuple on resume.

    Empty results dir → no-op.
    Legacy rows missing ``cases_sha256`` → warn + skip.
    Hash mismatch → SystemExit with recovery hints.
    """
    rows = load_trial_rows(results_dir)
    if not rows:
        return
    existing = rows[0].get("cases_sha256")
    if not existing:
        logger.warning(
            "check_cases_coherence: existing rows in %s lack cases_sha256 field "
            "(pre-P0.8 archive); cannot verify cases-file coherence on resume.",
            results_dir,
        )
        return
    if existing != current_sha:
        raise SystemExit(
            f"Cases file modified since last run: existing trials hashed {existing[:8]}..., "
            f"current file hashes {current_sha[:8]}.... "
            f"The deterministic schedule would produce different trial_index mappings "
            f"→ data integrity breach. "
            f"Recovery: (a) restore the original cases file, OR "
            f"(b) use a different --results-dir to start fresh."
        )


def check_pilot_gates(
    rows: list[dict[str, Any]],
    *,
    benchmark_mode: str | None = None,
) -> dict[str, Any]:
    """Evaluate REV5 §8 pilot gates on a collection of serialized trial rows.

    Gate A (saturation, Rev 4): if ``celltypes_coverage_pct`` median ≥ 90
        in BOTH ``strong_on`` AND ``strong_off``, the primary endpoint is
        saturated and the interaction effect is mechanically unmeasurable;
        switch to retrieval diversity / novelty. Replaces pre-Rev4 gene-based
        check (gene coverage was saturated at 100% in all pre-update arms,
        making that gate mechanically useless).
    Gate Null (mode B only, Rev 4): median celltype Δ (on − off) must be
        < 3 pp in BOTH strong and weak model families. Flags measurement
        contamination — mode B is a null control that must produce Δ ≈ 0.
        Evaluated only when ``benchmark_mode == "B"`` is passed explicitly
        or inferred from the rows' ``benchmark_mode`` field.
    Gate B (BioMCP health): error rate < 5% and median ``biomcp_latency_ms``
        < 10 min. Fails REV5 §6 outage rule if infrastructure is degraded.
    Gate C (distributional): each condition must have > 3 unique rounded
        ``celltypes_coverage_pct`` values. Fewer → LMM secondary invalid.
    Variance: per-case between-condition std-dev of ``celltypes_coverage_pct``
        must average ≥ 2 percentage points.

    Returns a dict with per-gate status, metric values, aggregate
    ``all_passed`` flag, and human-readable ``messages`` for any failures.
    """
    gates: dict[str, Any] = {}
    messages: list[str] = []

    def _cell(row: dict[str, Any]) -> float:
        """Rev 4: celltype coverage is the primary endpoint for all gates."""
        return float(row.get("celltypes_coverage_pct", 0.0) or 0.0)

    # Infer mode from rows if not explicitly passed (backward compat).
    if benchmark_mode is None:
        modes_in_rows = {r.get("benchmark_mode") for r in rows if r.get("benchmark_mode")}
        if len(modes_in_rows) == 1:
            benchmark_mode = next(iter(modes_in_rows))

    strong_on = [r for r in rows if r.get("condition") == "strong_on"]
    strong_off = [r for r in rows if r.get("condition") == "strong_off"]
    weak_on = [r for r in rows if r.get("condition") == "weak_on"]
    weak_off = [r for r in rows if r.get("condition") == "weak_off"]

    if strong_on and strong_off:
        on_median = statistics.median(_cell(r) for r in strong_on)
        off_median = statistics.median(_cell(r) for r in strong_off)
        saturated = on_median >= 90.0 and off_median >= 90.0
        gates["gate_a"] = {
            "passed": not saturated,
            "endpoint": "celltypes_coverage_pct",
            "strong_on_median_pct": round(on_median, 2),
            "strong_off_median_pct": round(off_median, 2),
            "threshold_pct": 90.0,
        }
        if saturated:
            messages.append(
                "Gate A FAIL: celltype endpoint saturated in both strong arms "
                f"(strong_on median {on_median:.1f}%, strong_off median {off_median:.1f}%); "
                "switch primary endpoint to unique_PMIDs / novelty per REV5 §8.1."
            )
    else:
        gates["gate_a"] = {
            "passed": False,
            "note": "insufficient strong-arm samples",
            "strong_on_n": len(strong_on),
            "strong_off_n": len(strong_off),
        }
        messages.append("Gate A INCONCLUSIVE: missing strong_on or strong_off rows.")

    # Gate Null (Rev 4) — mode B only. Null-control integrity: per-arm Δ must be
    # < 3 pp. If B is not null, the measurement scaffolding is contaminated and
    # the re-pilot must STOP before firing B' / C.
    if benchmark_mode == "B":
        deltas: dict[str, float | None] = {"strong": None, "weak": None}
        if strong_on and strong_off:
            deltas["strong"] = statistics.median(_cell(r) for r in strong_on) - \
                               statistics.median(_cell(r) for r in strong_off)
        if weak_on and weak_off:
            deltas["weak"] = statistics.median(_cell(r) for r in weak_on) - \
                             statistics.median(_cell(r) for r in weak_off)
        max_abs_delta = max((abs(d) for d in deltas.values() if d is not None), default=0.0)
        null_ok = all(
            (d is None) or abs(d) < 3.0 for d in deltas.values()
        ) and any(d is not None for d in deltas.values())
        gates["gate_null"] = {
            "passed": null_ok,
            "delta_strong_pp": None if deltas["strong"] is None else round(deltas["strong"], 2),
            "delta_weak_pp": None if deltas["weak"] is None else round(deltas["weak"], 2),
            "max_abs_delta_pp": round(max_abs_delta, 2),
            "threshold_pp": 3.0,
            "mode": "B",
        }
        if not null_ok:
            messages.append(
                f"Gate Null FAIL (mode B): celltype Δ exceeds 3 pp threshold "
                f"(strong={deltas['strong']}, weak={deltas['weak']}). "
                "Null control is contaminated — STOP and investigate measurement path "
                "before firing B' / C re-pilots."
            )
    else:
        # Gate Null only applies to mode B. For B' / C, skip silently (mode-scoped gate).
        gates["gate_null"] = {
            "passed": True,
            "skipped": True,
            "reason": f"Gate Null only applies to mode=B; got mode={benchmark_mode}",
        }

    n = len(rows)
    if n > 0:
        error_count = sum(1 for r in rows if r.get("biomcp_error") or r.get("error"))
        error_rate = error_count / n
        raw_latencies = [float(r.get("biomcp_latency_ms", 0.0) or 0.0) for r in rows]
        latencies = [x for x in raw_latencies if x > 0]
        lat_median = statistics.median(latencies) if latencies else 0.0
        healthy = error_rate < 0.05 and lat_median < 600_000
        gates["gate_b"] = {
            "passed": healthy,
            "error_rate": round(error_rate, 4),
            "latency_ms_median": round(lat_median, 2),
            "error_rate_threshold": 0.05,
            "latency_ms_threshold": 600_000,
            "n_rows": n,
            "n_errors": error_count,
        }
        if not healthy:
            messages.append(
                f"Gate B FAIL: BioMCP error rate {error_rate:.2%} "
                f"(threshold < 5%) or median latency {lat_median / 1000:.1f}s "
                "(threshold < 600s). Apply §6 outage exclusion or re-pilot."
            )
    else:
        gates["gate_b"] = {"passed": False, "note": "no rows"}
        messages.append("Gate B INCONCLUSIVE: no rows.")

    by_condition: dict[str, list[float]] = {}
    for row in rows:
        by_condition.setdefault(str(row.get("condition", "")), []).append(_cell(row))
    cluster_counts = {
        cond: len({round(x, 0) for x in vals}) for cond, vals in by_condition.items()
    }
    worst_cluster = min(cluster_counts.values()) if cluster_counts else 0
    distributional_ok = worst_cluster > 3
    gates["gate_c"] = {
        "passed": distributional_ok,
        "unique_rounded_values_per_condition": cluster_counts,
        "minimum_observed": worst_cluster,
        "threshold": 3,
    }
    if not distributional_ok:
        messages.append(
            "Gate C FAIL: at least one condition has <= 3 discrete rounded coverage "
            f"values ({cluster_counts}). LMM secondary invalid — drop to GLMM-only "
            "per REV5 §8.3."
        )

    by_case: dict[str, list[float]] = {}
    for row in rows:
        by_case.setdefault(str(row.get("case_id", "")), []).append(_cell(row))
    stddevs = [statistics.stdev(v) for v in by_case.values() if len(v) >= 2]
    mean_stdev = sum(stddevs) / len(stddevs) if stddevs else 0.0
    variance_ok = mean_stdev >= 2.0
    gates["variance"] = {
        "passed": variance_ok,
        "mean_per_case_stdev_pct": round(mean_stdev, 3),
        "threshold_pct": 2.0,
        "n_cases_with_multi_rows": len(stddevs),
    }
    if not variance_ok and stddevs:
        messages.append(
            f"Variance LOW: mean per-case between-condition std-dev {mean_stdev:.2f}pp "
            "< 2pp. Consider raising temperature to 0.5 per REV5 §8 step 5."
        )

    gate_keys = ["gate_a", "gate_b", "gate_c", "variance"]
    if benchmark_mode == "B":
        gate_keys.append("gate_null")
    all_passed = all(gates[key].get("passed", False) for key in gate_keys)
    gates["all_passed"] = all_passed
    gates["messages"] = messages
    gates["generated_at"] = _utc_now()
    gates["benchmark_mode"] = benchmark_mode
    return gates


def parse_common_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--cases-file", default=str(DEFAULT_CASES_PATH), help="Path to the case pack JSON.")
    parser.add_argument("--results-dir", required=True, help="Directory for per-trial outputs.")
    parser.add_argument("--workspace-root", required=True, help="Directory for per-trial workspaces.")
    parser.add_argument("--temperature", type=float, default=0.3, help="LLM temperature for generator models.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for schedule generation.")
    # P0.8 — benchmark_mode toggle. Default C preserves current behavior for
    # existing callers. Env var BENCHMARK_MODE is an override fallback.
    parser.add_argument(
        "--mode",
        choices=["B", "B_prime", "C"],
        default=os.environ.get("BENCHMARK_MODE", "C"),
        help=(
            "Benchmark mode: B (null control, kwargs pinned both arms), "
            "B_prime (prompt-level strip + skill-only kwarg hint), "
            "C (B_prime + tool-schema isolation on OFF arm, default)."
        ),
    )
    return parser


def serialize_result(result: SearchTrialResult) -> dict[str, Any]:
    return asdict(result)

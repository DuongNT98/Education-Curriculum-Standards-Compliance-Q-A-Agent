"""AgentCore Platform v1.0 — inner step 3: gap analysis (gap_analysis path only)."""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from shared.services.llm.azure_openai_client import AzureOpenAIClient
from shared.utils.audit_logger import emit_trace_event

from src.services import curriculum_service as cs

_SYSTEM_PROMPT = (
    "You are a curriculum coverage assessor. Given one lesson plan and one "
    "MEXT gakushu shido yoryo standard, classify the lesson plan's coverage "
    f"of that standard as exactly one of: {', '.join(cs.COVERAGE_LEVELS)}. "
    "Binary pass/fail is prohibited. Respond with only that one term — no "
    "punctuation, no explanation."
)


class GapAnalysisNode(FunctionNode):
    """Compare lesson-plan objectives against retrieved standards.

    Runs only on the gap_analysis path — classifies each retrieved standard as
    exceeds_standard / meets_standard / partially_meets / does_not_meet
    (binary pass/fail is prohibited). standard_lookup and hour_requirement
    paths pass through unchanged. A real LLM (Azure OpenAI) refines the
    deterministic keyword-overlap level — genuine semantic comparison the
    overlap ratio can't capture (e.g. paraphrased objectives). The client is
    built fresh per invocation from ctx.secrets (never cached on self — see
    _llm_refine); any failure silently keeps the deterministic level.
    """

    # S-1 (CoE R1 #2): inner subgraph node — ANONYMOUS. Caller trust is
    # authenticated once at the outer backbone; inner nodes must not
    # re-demand a higher trust level.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def __init__(self, llm: Any = None) -> None:
        # `llm` is a test-double seam only — register_nodes() never passes one
        # in production. The real client is built fresh per invocation in
        # _llm_refine() from ctx.secrets, not cached on self: node instances
        # are constructed in register_nodes() (registry LRU cache, shared
        # across every invocation) before any request's secrets are
        # provisioned, and caching one caller's client would leave it visible
        # to the next caller.
        self._llm = llm

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if cs.is_upstream_error(state.get("status")):
            emit_trace_event(
                "gap_analysis_skipped_upstream_error",
                {"correlation_id": state.get("correlation_id")},
                state,
            )
            return {"status": AgentStatus.ERROR.value}

        if state.get("query_type") != cs.GAP_ANALYSIS:
            emit_trace_event(
                "gap_analysis_skipped",
                {"correlation_id": state.get("correlation_id"), "query_type": state.get("query_type")},
                state,
            )
            return {"status": AgentStatus.SUCCESS.value}

        lesson_plan_text = state.get("lesson_plan_text", "")
        standards = state.get("retrieved_standards", []) or []
        if not lesson_plan_text.strip():
            emit_trace_event(
                "gap_analysis_rejected_missing_lesson_plan",
                {"correlation_id": state.get("correlation_id")},
                state,
            )
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["GapAnalysisNode: lesson_plan_text is required for gap_analysis"],
            }

        gaps = [self._assess_one(lesson_plan_text, s, state) for s in standards] or [
            self._assess_one(lesson_plan_text, {"section": "unspecified", "text": ""}, state)
        ]
        overall = cs.aggregate_coverage_status(gaps)

        emit_trace_event(
            "gaps_assessed",
            {"correlation_id": state.get("correlation_id"), "n_gaps": len(gaps), "coverage_status": overall},
            state,
        )
        return {"coverage_gaps": gaps, "coverage_status": overall, "status": AgentStatus.SUCCESS.value}

    def _assess_one(self, lesson_plan_text: str, standard: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        standard_id = standard.get("section") or "unspecified"
        level = self._deterministic_level(lesson_plan_text, standard)
        level = self._llm_refine(lesson_plan_text, standard, level, state)
        return {"standard_id": standard_id, "status": level}

    @staticmethod
    def _deterministic_level(lesson_plan_text: str, standard: dict[str, Any]) -> str:
        standard_text = str(standard.get("text", "") or "")
        if not standard_text:
            return cs.PARTIALLY_MEETS
        overlap = sum(1 for token in standard_text.split() if token in lesson_plan_text)
        ratio = overlap / max(len(standard_text.split()), 1)
        if ratio >= 0.8:
            return cs.MEETS
        if ratio > 0:
            return cs.PARTIALLY_MEETS
        return cs.DOES_NOT_MEET

    def _llm_refine(self, lesson_plan_text: str, standard: dict[str, Any], base: str, state: dict[str, Any]) -> str:
        try:
            llm = self._llm
            if llm is None:
                ctx = InvocationContext.from_state(state)
                llm = AzureOpenAIClient(
                    {
                        "api_key": ctx.secrets.require("AZURE_OPENAI_API_KEY"),
                        "azure_endpoint": ctx.secrets.require("AZURE_OPENAI_ENDPOINT"),
                        "azure_deployment": ctx.secrets.require("AZURE_OPENAI_DEPLOYMENT"),
                    }
                )
            response = llm.complete(
                [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"standard={standard.get('text', '')[:300]} lesson_plan={lesson_plan_text[:300]}",
                    },
                ]
            )
            refined = str(response.get("content", "")).strip().lower()
            return refined if refined in cs.COVERAGE_LEVELS else base
        except Exception as exc:  # noqa: BLE001 — degrade to deterministic level
            import logging

            logging.getLogger(__name__).warning("gap analysis LLM refine failed: %s", exc)
            return base

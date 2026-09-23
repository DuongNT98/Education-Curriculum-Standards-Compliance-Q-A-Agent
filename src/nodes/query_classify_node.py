"""AgentCore Platform v1.0 — inner step 1: query classification."""

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from shared.services.llm.azure_openai_client import AzureOpenAIClient
from shared.utils.audit_logger import emit_trace_event

from src.services import curriculum_service as cs

_SYSTEM_PROMPT = (
    "You are a curriculum-compliance query classifier. Classify the request "
    f"as exactly one of: {', '.join(cs.VALID_QUERY_TYPES)}. Respond with only "
    "that one word — no punctuation, no explanation."
)


class QueryClassifyNode(FunctionNode):
    """Classify standard_lookup / gap_analysis / hour_requirement and route.

    The inner subgraph receives only the JSON string user_input (seeded from
    the outer validated_input), so this first inner node reconstructs the
    payload. A real LLM (Azure OpenAI) refines the deterministic keyword
    classification — genuine NL reasoning over ambiguous JA/EN phrasing the
    keyword heuristic can miss. The client is built fresh per invocation from
    ctx.secrets (never cached on self — see _llm_refine); any failure (no
    secret configured, API error, malformed response) silently keeps the
    deterministic result, which is always produced first and is never itself
    a failure mode.
    """

    # S-1 (CoE R1 #2): inner subgraph node — ANONYMOUS. Caller trust is
    # authenticated once at the outer backbone (pre_process); inner nodes
    # must not re-demand a higher trust level.
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
        raw = state.get("user_input", "")
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            payload = None
        if not isinstance(payload, dict) or (not payload.get("query_text") and not payload.get("lesson_plan_text")):
            emit_trace_event(
                "query_classify_rejected_missing_input",
                {"correlation_id": state.get("correlation_id")},
                state,
            )
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["QueryClassifyNode: missing query_text/lesson_plan_text in inner input"],
            }

        query_text = payload.get("query_text", "") or ""
        lesson_plan_text = payload.get("lesson_plan_text", "") or ""

        # Re-validate the outer InputSanitizeNode's precondition: the outer
        # pre_process -> main edge is unconditional (fires even when
        # pre_process returned ERROR), so a student-PII rejection upstream
        # does not by itself stop the inner subgraph from running on the raw
        # user_input. Re-check here (verified precedent on a sibling template).
        if cs.contains_student_pii(query_text) or cs.contains_student_pii(lesson_plan_text):
            emit_trace_event(
                "query_classify_rejected_student_pii",
                {"correlation_id": state.get("correlation_id")},
                state,
            )
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": [
                    "QueryClassifyNode: student PII (name/ID) rejected — not required for curriculum compliance"
                ],
            }

        hinted_type = payload.get("query_type")
        query_type = cs.classify_query_type(query_text or lesson_plan_text, hinted_type)
        query_type = self._llm_refine(query_text, lesson_plan_text, query_type, state)

        emit_trace_event(
            "query_classified",
            {"correlation_id": state.get("correlation_id"), "query_type": query_type},
            state,
        )
        return {
            "query_text": query_text,
            "lesson_plan_text": lesson_plan_text,
            "subject": str(payload.get("subject", "") or ""),
            "grade_level": str(payload.get("grade_level", "") or ""),
            "query_type": query_type,
            "status": AgentStatus.SUCCESS.value,
        }

    def _llm_refine(self, query_text: str, lesson_plan_text: str, base: str, state: dict[str, Any]) -> str:
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
                    {"role": "user", "content": (query_text or lesson_plan_text)[:500]},
                ]
            )
            refined = str(response.get("content", "")).strip().lower()
            return refined if refined in cs.VALID_QUERY_TYPES else base
        except Exception as exc:  # noqa: BLE001 — degrade to deterministic classification
            import logging

            logging.getLogger(__name__).warning("query classify LLM refine failed: %s", exc)
            return base

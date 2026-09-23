"""AgentCore Platform v1.0 — inner step 2: curriculum retrieval / hour lookup."""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services import curriculum_service as cs


class CurriculumRetrieveNode(FunctionNode):
    """Dual-component retrieval: VectorRAG standards OR deterministic hour table.

    standard_lookup / gap_analysis path: dense retrieval from the 学習指導要領
    KB via the injected `retriever`. hour_requirement path: deterministic
    structured lookup from `config/hour_requirements/{grade_level}.json` —
    never VectorRAG, exact by construction.
    """

    # S-1 (CoE R1 #2): inner subgraph node — ANONYMOUS. Caller trust is
    # authenticated once at the outer backbone; inner nodes must not
    # re-demand a higher trust level.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def __init__(
        self, retriever: Any = None, top_k: int = 5, hour_requirements_path: str = "config/hour_requirements/"
    ) -> None:
        self._retriever = retriever
        self._top_k = top_k
        self._hour_requirements_path = hour_requirements_path

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if cs.is_upstream_error(state.get("status")):
            emit_trace_event(
                "curriculum_retrieve_skipped_upstream_error",
                {"correlation_id": state.get("correlation_id")},
                state,
            )
            return {"status": AgentStatus.ERROR.value}

        query_type = state.get("query_type", "")
        subject = state.get("subject", "")
        grade_level = state.get("grade_level", "")

        if query_type == cs.HOUR_REQUIREMENT:
            return self._retrieve_hour_requirement(state, subject, grade_level)
        return self._retrieve_standards(state, subject, grade_level)

    def _retrieve_hour_requirement(self, state: dict[str, Any], subject: str, grade_level: str) -> dict[str, Any]:
        table = cs.load_hour_requirements(self._hour_requirements_path, grade_level)
        entry = cs.hour_lookup_for_subject(table, subject)
        emit_trace_event(
            "hour_requirement_retrieved",
            {"correlation_id": state.get("correlation_id"), "subject": subject, "grade_level": grade_level},
            state,
        )
        if entry is None:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["CurriculumRetrieveNode: no hour-requirement entry for subject/grade_level"],
            }
        return {
            "hour_requirement": entry,
            "kb_source_ref": entry.get("source_ref", ""),
            "status": AgentStatus.SUCCESS.value,
        }

    def _retrieve_standards(self, state: dict[str, Any], subject: str, grade_level: str) -> dict[str, Any]:
        query_text = state.get("query_text") or state.get("lesson_plan_text", "")
        standards = self._search(query_text, subject, grade_level)
        citations = [
            {"subject": subject, "grade_level": grade_level, "section": s.get("section", "")} for s in standards
        ]
        emit_trace_event(
            "curriculum_retrieved",
            {"correlation_id": state.get("correlation_id"), "n_standards": len(standards)},
            state,
        )
        return {
            "retrieved_standards": standards,
            "mext_citations": citations,
            "kb_source_ref": cs.KB_NAMESPACE,
            "status": AgentStatus.SUCCESS.value,
        }

    def _search(self, query_text: str, subject: str, grade_level: str) -> list[dict[str, Any]]:
        if self._retriever is None:
            return []
        try:
            return list(
                self._retriever.search(
                    query=query_text,
                    filters={"namespace": cs.KB_NAMESPACE, "subject": subject, "grade_level": grade_level},
                    top_k=self._top_k,
                )
            )
        except Exception as exc:  # noqa: BLE001 — degrade, keep standards empty
            import logging

            logging.getLogger(__name__).warning("curriculum retrieval failed: %s", exc)
            return []

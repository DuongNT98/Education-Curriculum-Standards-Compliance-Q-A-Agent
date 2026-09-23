"""AgentCore Platform v1.0 — outer post_process: OutputGateNode (S-3 gate)."""

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services import curriculum_service as cs


class OutputGateNode(FunctionNode):
    """Finalize + S-3 deterministic output gate.

    Asserts a citation (MEXT reference or hour-table source_ref) is present on
    every answer and that no student-identifier-shaped value leaked into the
    output text. The preservation+filter variant of the S-3 hook rejects
    output that drops the citation or leaks an identifier.
    """

    # S-1: outer boundary node — matches agent.yaml required_trust_level.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if cs.is_upstream_error(state.get("status")):
            emit_trace_event(
                "output_skipped_upstream_error",
                {"correlation_id": state.get("correlation_id")},
                state,
            )
            return {"status": AgentStatus.ERROR.value}

        query_type = state.get("query_type", "")
        answer_text = self._build_answer_text(state, query_type)

        emit_trace_event(
            "output_gated",
            {"correlation_id": state.get("correlation_id"), "query_type": query_type},
            state,
        )
        return {
            "answer_text": answer_text,
            # _extra_security_gate_output() below receives THIS dict as its
            # `result` argument (the framework's S-3 hook contract passes the
            # node's own execute() return, not the full accumulated graph
            # state) — query_type/mext_citations/hour_requirement must be
            # carried at the top level here too, or the citation-required
            # check silently never fires (always sees query_type=None).
            "query_type": query_type,
            "mext_citations": state.get("mext_citations", []),
            "hour_requirement": state.get("hour_requirement", {}),
            "formatted_output": {
                "answer_text": answer_text,
                "mext_citations": state.get("mext_citations", []),
                "coverage_gaps": state.get("coverage_gaps", []),
                "coverage_status": state.get("coverage_status", ""),
                "hour_requirement": state.get("hour_requirement", {}),
                "kb_source_ref": state.get("kb_source_ref", ""),
            },
            "status": AgentStatus.SUCCESS.value,
        }

    @staticmethod
    def _build_answer_text(state: dict[str, Any], query_type: str) -> str:
        if query_type == cs.HOUR_REQUIREMENT:
            hr = state.get("hour_requirement") or {}
            return (
                f"{hr.get('subject', '')} minimum hours ({hr.get('grade_level', '')}): "
                f"{hr.get('min_hours', 'unknown')} — source: {hr.get('source_ref', '')}"
            )
        if query_type == cs.GAP_ANALYSIS:
            status = state.get("coverage_status", "")
            n_gaps = len(state.get("coverage_gaps", []))
            return f"Coverage status: {status} ({n_gaps} standard(s) assessed)"
        citations = state.get("mext_citations", [])
        return f"{len(citations)} 学習指導要領 reference(s) retrieved"

    def _extra_security_gate_output(self, state: dict[str, Any]) -> dict[str, Any]:
        """S-3 preservation + filter variant (framework-invoked; never raises)."""
        answer_text = state.get("answer_text", "") or ""
        query_type = state.get("query_type", "")

        if cs.leaks_student_identifier(answer_text):
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["OutputGateNode: student-identifier-shaped value blocked from output"],
            }

        has_citation = bool(state.get("mext_citations")) or bool(
            (state.get("hour_requirement") or {}).get("source_ref")
        )
        if query_type in (cs.STANDARD_LOOKUP, cs.GAP_ANALYSIS, cs.HOUR_REQUIREMENT) and not has_citation:
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["OutputGateNode: citation or source reference missing"],
            }
        return state

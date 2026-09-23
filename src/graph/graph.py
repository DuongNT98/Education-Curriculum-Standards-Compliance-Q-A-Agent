"""AgentCore Platform v1.0 — EDU-C2-012 outer graph (Cat 2).

Outer (AgentBaseGraph): initialize -> pre_process(InputSanitizeNode) ->
main(CurriculumGraphNode) -> post_process(OutputGateNode) -> finalize.
Inner (BaseGraph): query_classify -> curriculum_retrieve -> gap_analysis.

The GraphNode wrapper lives in THIS file (not src/nodes/) matching the
scaffold canonical placement for a Cat 2 outer main-slot wrapper — this keeps
the PB-6 invoke-order probe scoped to `src/nodes/` single-step nodes instead
of pulling the whole inner subgraph into that probe. This placement does NOT
exempt CurriculumGraphNode from boundary testing: see
tests/proof_of_boundary/test_pb_graphnode_boundary.py for the dedicated S-1 /
boundary-mapping coverage this outer node requires.
"""

from typing import Any, ClassVar, cast

from framework.graph.agent_base_graph import AgentBaseGraph
from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_state import AgentState
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.nodes.input_sanitize_node import InputSanitizeNode
from src.nodes.output_gate_node import OutputGateNode
from src.schemas.state import State


class CurriculumGraphNode(GraphNode):
    """Wraps the inner curriculum compliance workflow (main slot)."""

    # S-1: outer main-slot wrapper — first node in the outer backbone to
    # receive caller input via extract_input(); matches agent.yaml
    # required_trust_level and sibling outer nodes (InputSanitizeNode /
    # OutputGateNode). Inner subgraph nodes stay ANONYMOUS (see 3b).
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL
    error_strategy: ClassVar[str] = "propagate"
    propagate_hitl: ClassVar[bool] = False

    def __init__(
        self,
        llm: Any = None,
        retriever: Any = None,
        top_k: int = 5,
        hour_requirements_path: str = "config/hour_requirements/",
    ) -> None:
        super().__init__()
        self._llm = llm
        self._retriever = retriever
        self._top_k = top_k
        self._hour_requirements_path = hour_requirements_path

    def get_subgraph(self) -> Any:
        from src.graph.curriculum_workflow_graph import CurriculumWorkflowGraph

        sg = CurriculumWorkflowGraph(config=self._parent_config())
        sg.compile()
        return sg

    def extract_input(self, state: AgentState) -> str:
        emit_trace_event(
            "curriculum_workflow_dispatched",
            {"correlation_id": state.get("correlation_id")},
            state,
        )
        return cast(str, state.get("validated_input", state.get("user_input", "")))

    def merge_output(self, state: AgentState, sub_result: dict[str, Any]) -> dict[str, Any]:
        emit_trace_event(
            "curriculum_workflow_completed",
            {"correlation_id": state.get("correlation_id"), "query_type": sub_result.get("query_type")},
            state,
        )
        return {
            "query_type": sub_result.get("query_type", ""),
            "retrieved_standards": sub_result.get("retrieved_standards", []),
            "mext_citations": sub_result.get("mext_citations", []),
            "coverage_gaps": sub_result.get("coverage_gaps", []),
            "coverage_status": sub_result.get("coverage_status", ""),
            "hour_requirement": sub_result.get("hour_requirement", {}),
            "kb_source_ref": sub_result.get("kb_source_ref", ""),
            "status": sub_result.get("status"),
        }

    def _parent_config(self) -> dict[str, Any]:
        return {
            "llm": self._llm,
            "retriever": self._retriever,
            "top_k": self._top_k,
            "hour_requirements_path": self._hour_requirements_path,
        }


class Graph(AgentBaseGraph):
    """EDU-C2-012 — Education Curriculum Standards & Compliance Q&A Agent."""

    @property
    def name(self) -> str:
        return "edu-c2-012"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()
        llm = self.config.get("llm") if hasattr(self, "config") else None
        retriever = self.config.get("retriever") if hasattr(self, "config") else None
        top_k = self.config.get("top_k", 5) if hasattr(self, "config") else 5
        hour_requirements_path = (
            self.config.get("hour_requirements_path", "config/hour_requirements/")
            if hasattr(self, "config")
            else "config/hour_requirements/"
        )
        self._nodes["pre_process"] = InputSanitizeNode()
        self._nodes["main"] = CurriculumGraphNode(
            llm=llm, retriever=retriever, top_k=top_k, hour_requirements_path=hour_requirements_path
        )
        self._nodes["post_process"] = OutputGateNode()

    # add_edges() is NOT overridden — backbone wiring belongs to the framework.

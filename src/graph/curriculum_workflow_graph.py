"""AgentCore Platform v1.0 — EDU-C2-012 inner curriculum compliance workflow (Cat 2).

Instantiated by CurriculumGraphNode.get_subgraph(). Receives only the JSON
string user_input (seeded from the outer validated_input); the first inner
node reconstructs the payload.

Pipeline: query_classify -> curriculum_retrieve -> gap_analysis
(gap_analysis is a no-op pass-through unless query_type == "gap_analysis").
"""

from typing import Any

from langgraph.graph import END, START

from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus

from src.nodes.curriculum_retrieve_node import CurriculumRetrieveNode
from src.nodes.gap_analysis_node import GapAnalysisNode
from src.nodes.query_classify_node import QueryClassifyNode
from src.schemas.state import State


class CurriculumWorkflowGraph(BaseGraph):
    """Inner multi-step curriculum compliance workflow."""

    @property
    def name(self) -> str:
        return "edu_c2_012_curriculum_workflow"

    @property
    def state_schema(self) -> type:
        return State

    def _validate_config(self) -> None:
        pass

    def register_nodes(self) -> None:
        llm = self.config.get("llm") if hasattr(self, "config") else None
        retriever = self.config.get("retriever") if hasattr(self, "config") else None
        top_k = self.config.get("top_k", 5) if hasattr(self, "config") else 5
        hour_requirements_path = (
            self.config.get("hour_requirements_path", "config/hour_requirements/")
            if hasattr(self, "config")
            else "config/hour_requirements/"
        )
        self._nodes["query_classify"] = QueryClassifyNode(llm=llm)
        self._nodes["curriculum_retrieve"] = CurriculumRetrieveNode(
            retriever=retriever, top_k=top_k, hour_requirements_path=hour_requirements_path
        )
        self._nodes["gap_analysis"] = GapAnalysisNode(llm=llm)

    def add_edges(self) -> None:
        self._sg.add_edge(START, "query_classify")
        self._sg.add_edge("query_classify", "curriculum_retrieve")
        self._sg.add_edge("curriculum_retrieve", "gap_analysis")
        self._sg.add_edge("gap_analysis", END)

    def route(self, state: AgentState) -> str:
        # Required by ABC; this topology is linear so route() is never invoked
        # (no add_conditional_edges() calls it).
        return END if state.get("status") == AgentStatus.ERROR.value else "gap_analysis"

    def get_output(self, state: AgentState) -> dict[str, Any]:
        return {
            "query_type": state.get("query_type", ""),
            "retrieved_standards": state.get("retrieved_standards", []),
            "mext_citations": state.get("mext_citations", []),
            "coverage_gaps": state.get("coverage_gaps", []),
            "coverage_status": state.get("coverage_status", ""),
            "hour_requirement": state.get("hour_requirement", {}),
            "kb_source_ref": state.get("kb_source_ref", ""),
            "status": state.get("status"),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
        }

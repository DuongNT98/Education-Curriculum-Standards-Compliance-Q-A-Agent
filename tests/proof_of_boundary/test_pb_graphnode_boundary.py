# GraphNode Boundary Verification — CurriculumGraphNode (outer main-slot wrapper, Cat 2)
#
# PB-6 (test_pb_invoke_order.py) only discovers concrete BaseNode subclasses under
# src/nodes/. CurriculumGraphNode lives in src/graph/graph.py (scaffold-canonical
# placement for a Cat 2 outer main-slot GraphNode wrapper, keeping PB-6 scoped to
# single-step nodes instead of pulling the whole inner subgraph into that probe).
# That placement does NOT exempt it from boundary testing: it is the first outer
# node to receive caller input via extract_input() and is therefore a real S-1
# security boundary. This file supplies the dedicated coverage PB-6 cannot reach.

from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import CurriculumGraphNode
from src.nodes.query_classify_node import QueryClassifyNode


def _node() -> CurriculumGraphNode:
    return CurriculumGraphNode(llm=None, retriever=None, top_k=5, hour_requirements_path="config/hour_requirements/")


class TestGraphNodeS1TrustGate:
    """S-1: BaseNode.__call__ must deny before execute()/get_subgraph() ever runs."""

    def test_insufficient_trust_denied_before_execute(self, monkeypatch):
        node = _node()
        called = []
        monkeypatch.setattr(node, "get_subgraph", lambda: called.append("get_subgraph"))
        monkeypatch.setattr(node, "extract_input", lambda state: called.append("extract_input"))

        result = node({"caller_trust_level": TrustLevel.ANONYMOUS.value})

        assert result["status"] == AgentStatus.ERROR.value
        assert any("S-1 trust gate denied" in log for log in result.get("error_log", []))
        assert called == []  # execute() (and therefore get_subgraph/extract_input) never ran

    def test_sufficient_trust_reaches_execute(self, monkeypatch):
        node = _node()
        monkeypatch.setattr(node, "extract_input", lambda state: "query")
        monkeypatch.setattr(
            node,
            "merge_output",
            lambda state, sub_result: {"status": AgentStatus.SUCCESS.value},
        )

        class _FakeSubgraph:
            name = "fake"

            def invoke(self, user_input, session_id=None, ctx=None):
                return {"status": AgentStatus.SUCCESS.value}

        monkeypatch.setattr(node, "get_subgraph", lambda: _FakeSubgraph())

        result = node(
            {
                "caller_trust_level": TrustLevel.VERIFIED_EXTERNAL.value,
                "correlation_id": "c-1",
                "session_id": "s-1",
                "thread_id": "t-1",
                "trace_id": "tr-1",
            }
        )
        assert result["status"] == AgentStatus.SUCCESS.value


class TestGraphNodeBoundaryMapping:
    """Boundary mapping — extract_input()/merge_output() must map explicitly, not leak raw state."""

    def test_extract_input_only_reads_validated_input_contract(self):
        node = _node()
        state = {
            "validated_input": '{"query_text": "hours"}',
            "user_input": "raw caller text should not be preferred",
            "correlation_id": "c-2",
        }
        result = node.extract_input(state)
        assert result == state["validated_input"]

    def test_extract_input_falls_back_to_user_input_when_unvalidated(self):
        node = _node()
        state = {"user_input": "plain text", "correlation_id": "c-3"}
        result = node.extract_input(state)
        assert result == "plain text"

    def test_merge_output_maps_explicit_fields_no_raw_passthrough(self):
        node = _node()
        sub_result = {
            "query_type": "hour_requirement",
            "retrieved_standards": [{"section": "1"}],
            "mext_citations": [{"section": "1"}],
            "coverage_gaps": [],
            "coverage_status": "meets_standard",
            "hour_requirement": {"min_hours": 100},
            "kb_source_ref": "mext_gakushu_shidoyoryo",
            "status": AgentStatus.SUCCESS.value,
            # A field NOT in the merge_output contract — must not leak into parent state.
            "internal_subgraph_debug_trace": ["step1", "step2"],
        }
        merged = node.merge_output({"correlation_id": "c-4"}, sub_result)

        assert merged["query_type"] == "hour_requirement"
        assert merged["hour_requirement"] == {"min_hours": 100}
        assert merged["status"] == AgentStatus.SUCCESS.value
        assert "internal_subgraph_debug_trace" not in merged


class TestInnerEntryNodeDelegatesGating:
    """Delegation is deliberate: the inner entry node (QueryClassifyNode) is a
    FunctionNode, so it inherits the @final S-2/S-3 gates automatically — the
    outer CurriculumGraphNode does not need to (and per framework/nodes/graph_node.py
    does not) re-run S-2/S-3 itself; it delegates to the inner subgraph's own
    security boundary."""

    def test_inner_entry_node_is_function_node_with_gates(self):
        import pytest
        from framework.nodes.function_node import FunctionNode

        assert issubclass(QueryClassifyNode, FunctionNode)
        if not hasattr(FunctionNode, "_security_gate_input"):
            pytest.skip("local wheel rc1 stub lacks _security_gate_input/_output — CI wheel 1.0.0 is gate of record")
        assert hasattr(QueryClassifyNode, "_security_gate_input")
        assert hasattr(QueryClassifyNode, "_security_gate_output")

# EDU-C2-012 — Integration test: full graph compile + invoke (3 query-type paths).

import json

from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import Graph


class FakeLLM:
    def complete(self, *a, **k):
        return "classification rationale"


class FakeRetriever:
    def search(self, query, filters, top_k):
        return [{"section": "middle_school_math_2_number_and_algebra", "text": "objective a objective b"}]


def _ctx(session="it-1"):
    return InvocationContext(session_id=session, caller_trust_level=TrustLevel.VERIFIED_EXTERNAL, caller_id="tester")


def _agent(retriever=None):
    a = Graph(config={"llm": FakeLLM(), "retriever": retriever, "max_retry": 1})
    a.compile()
    return a


def test_standard_lookup_path():
    payload = json.dumps({"query_text": "中学校2年数学の必修内容は？", "subject": "math", "grade_level": "middle_school_year_2"})
    result = _agent(retriever=FakeRetriever()).invoke(payload, ctx=_ctx("it-standard"))
    assert result["status"] in (AgentStatus.SUCCESS, AgentStatus.SUCCESS.value)
    nh = result.get("node_history") or []
    assert len(nh) >= 5, f"expected >=5 nodes, got {len(nh)}: {nh}"
    out = result.get("output") or {}
    assert out.get("mext_citations")


def test_gap_analysis_path():
    payload = json.dumps(
        {
            "query_text": "このレッスンプランは学習指導要領を満たしていますか？",
            "lesson_plan_text": "objective a objective b covered fully",
            "query_type": "gap_analysis",
            "subject": "math",
            "grade_level": "middle_school_year_2",
        }
    )
    result = _agent(retriever=FakeRetriever()).invoke(payload, ctx=_ctx("it-gap"))
    assert result["status"] in (AgentStatus.SUCCESS, AgentStatus.SUCCESS.value)
    out = result.get("output") or {}
    assert out.get("coverage_gaps")
    assert out.get("coverage_status")


def test_hour_requirement_path():
    payload = json.dumps({"query_text": "中学校2年数学の標準授業時数は？", "query_type": "hour_requirement", "subject": "math", "grade_level": "middle_school_year_2"})
    result = _agent().invoke(payload, ctx=_ctx("it-hour"))
    assert result["status"] in (AgentStatus.SUCCESS, AgentStatus.SUCCESS.value)
    out = result.get("output") or {}
    assert out.get("hour_requirement", {}).get("min_hours") == 105


def test_empty_input_errors():
    result = _agent().invoke("", ctx=_ctx("it-empty"))
    assert result["status"] in (
        AgentStatus.ERROR, AgentStatus.ERROR.value, AgentStatus.CANCELLED, AgentStatus.CANCELLED.value,
    )


def test_student_pii_rejected():
    payload = json.dumps({"query_text": "student_id 99999 coverage check"})
    result = _agent().invoke(payload, ctx=_ctx("it-pii"))
    assert result["status"] in (AgentStatus.ERROR, AgentStatus.ERROR.value)


def test_no_secret_in_output():
    payload = json.dumps({"query_text": "中学校2年数学の必修内容は？", "subject": "math", "grade_level": "middle_school_year_2"})
    result = _agent(retriever=FakeRetriever()).invoke(payload, ctx=_ctx("it-secret"))
    blob = json.dumps(result, default=str).lower()
    assert "sk-" not in blob and "eyj" not in blob

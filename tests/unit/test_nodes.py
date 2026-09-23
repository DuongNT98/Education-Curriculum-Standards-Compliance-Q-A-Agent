# EDU-C2-012 — Unit tests (per node: success + error/edge).

import json

from framework.schemas.agent_status import AgentStatus

from src.nodes.curriculum_retrieve_node import CurriculumRetrieveNode
from src.nodes.gap_analysis_node import GapAnalysisNode
from src.nodes.input_sanitize_node import InputSanitizeNode
from src.nodes.output_gate_node import OutputGateNode
from src.nodes.query_classify_node import QueryClassifyNode
from src.services import curriculum_service as cs


def _s(**kw):
    st = {"node_history": [], "error_log": [], "execution_time": {}, "correlation_id": "c"}
    st.update(kw)
    return st


class _FakeLLM:
    """Test-double for AzureOpenAIClient's .complete(messages) -> {"content": ...} contract."""

    def __init__(self, content: str | None = None, raise_exc: Exception | None = None):
        self._content = content
        self._raise = raise_exc

    def complete(self, messages):
        if self._raise is not None:
            raise self._raise
        return {"content": self._content}


class TestInputSanitizeNode:
    def setup_method(self):
        self.node = InputSanitizeNode()

    def test_success(self):
        p = json.dumps({"query_text": "中学校2年数学の必修内容は？", "subject": "math", "grade_level": "middle_school_year_2"})
        r = self.node.execute(_s(user_input=p))
        assert r["status"] == AgentStatus.SUCCESS
        assert json.loads(r["validated_input"])["subject"] == "math"

    def test_empty(self):
        assert self.node.execute(_s(user_input=""))["status"] == AgentStatus.ERROR

    def test_missing_query_and_lesson_plan(self):
        p = json.dumps({"subject": "math"})
        assert self.node.execute(_s(user_input=p))["status"] == AgentStatus.ERROR

    def test_rejects_student_pii(self):
        p = json.dumps({"query_text": "student_id 12345 lesson coverage?"})
        assert self.node.execute(_s(user_input=p))["status"] == AgentStatus.ERROR

    def test_plain_text_input(self):
        r = self.node.execute(_s(user_input="高等学校における保健体育の標準単位数は？"))
        assert r["status"] == AgentStatus.SUCCESS


class TestQueryClassifyNode:
    def setup_method(self):
        self.node = QueryClassifyNode()

    def test_hour_requirement_classification(self):
        inner = json.dumps({"query_text": "高等学校の保健体育の標準単位数は？"})
        r = self.node.execute(_s(user_input=inner))
        assert r["status"] == AgentStatus.SUCCESS
        assert r["query_type"] == cs.HOUR_REQUIREMENT

    def test_gap_analysis_classification(self):
        inner = json.dumps({"query_text": "このレッスンプランは学習指導要領を満たしていますか？", "lesson_plan_text": "..."})
        r = self.node.execute(_s(user_input=inner))
        assert r["query_type"] == cs.GAP_ANALYSIS

    def test_hinted_type_wins(self):
        inner = json.dumps({"query_text": "some question", "query_type": "standard_lookup"})
        r = self.node.execute(_s(user_input=inner))
        assert r["query_type"] == cs.STANDARD_LOOKUP

    def test_missing_input(self):
        assert self.node.execute(_s(user_input=json.dumps({})))["status"] == AgentStatus.ERROR


class TestQueryClassifyNodeLLM:
    """BL-06..BL-08 — LLM refinement via AzureOpenAIClient, built fresh per invocation."""

    def _inner(self, query_text=""):
        return json.dumps({"query_text": query_text})

    def test_llm_refines_classification(self):
        node = QueryClassifyNode(llm=_FakeLLM(content="gap_analysis"))
        r = node.execute(_s(user_input=self._inner("ambiguous phrasing with no keyword match")))
        assert r["status"] == AgentStatus.SUCCESS
        assert r["query_type"] == cs.GAP_ANALYSIS

    def test_llm_failure_degrades_to_deterministic(self):
        node = QueryClassifyNode(llm=_FakeLLM(raise_exc=RuntimeError("api down")))
        r = node.execute(_s(user_input=self._inner("高等学校の保健体育の標準単位数は？")))
        assert r["status"] == AgentStatus.SUCCESS
        assert r["query_type"] == cs.HOUR_REQUIREMENT

    def test_llm_out_of_taxonomy_response_degrades(self):
        node = QueryClassifyNode(llm=_FakeLLM(content="not_a_real_type"))
        r = node.execute(_s(user_input=self._inner("高等学校の保健体育の標準単位数は？")))
        assert r["query_type"] == cs.HOUR_REQUIREMENT

    def test_no_llm_configured_degrades(self):
        # Real production shape: no secret provisioned, no llm= injected.
        node = QueryClassifyNode()
        r = node.execute(_s(user_input=self._inner("高等学校の保健体育の標準単位数は？")))
        assert r["status"] == AgentStatus.SUCCESS
        assert r["query_type"] == cs.HOUR_REQUIREMENT


class TestCurriculumRetrieveNode:
    def setup_method(self):
        self.node = CurriculumRetrieveNode()

    def test_hour_requirement_lookup(self):
        r = self.node.execute(_s(query_type=cs.HOUR_REQUIREMENT, subject="math", grade_level="middle_school_year_2"))
        assert r["status"] == AgentStatus.SUCCESS
        assert r["hour_requirement"]["min_hours"] == 105
        assert r["kb_source_ref"]

    def test_hour_requirement_no_match(self):
        r = self.node.execute(_s(query_type=cs.HOUR_REQUIREMENT, subject="unknown_subject", grade_level="middle_school_year_2"))
        assert r["status"] == AgentStatus.ERROR

    def test_standard_lookup_no_retriever_degrades(self):
        r = self.node.execute(_s(query_type=cs.STANDARD_LOOKUP, query_text="q", subject="math", grade_level="middle_school_year_2"))
        assert r["status"] == AgentStatus.SUCCESS
        assert r["retrieved_standards"] == []
        assert r["kb_source_ref"] == cs.KB_NAMESPACE

    def test_upstream_error_propagates(self):
        r = self.node.execute(_s(status=AgentStatus.ERROR.value))
        assert r["status"] == AgentStatus.ERROR


class TestGapAnalysisNode:
    def setup_method(self):
        self.node = GapAnalysisNode()

    def test_skips_non_gap_path(self):
        r = self.node.execute(_s(query_type=cs.STANDARD_LOOKUP))
        assert r["status"] == AgentStatus.SUCCESS
        assert "coverage_gaps" not in r

    def test_gap_analysis_four_level_coverage(self):
        standards = [{"section": "std-1", "text": "objective a objective b"}]
        r = self.node.execute(
            _s(query_type=cs.GAP_ANALYSIS, lesson_plan_text="objective a objective b covered fully", retrieved_standards=standards)
        )
        assert r["status"] == AgentStatus.SUCCESS
        assert r["coverage_status"] in cs.COVERAGE_LEVELS
        assert all(g["status"] in cs.COVERAGE_LEVELS for g in r["coverage_gaps"])
        # Binary pass/fail is prohibited — must be one of the 4 levels, never a bare bool.
        assert r["coverage_status"] not in (True, False)

    def test_missing_lesson_plan_text(self):
        r = self.node.execute(_s(query_type=cs.GAP_ANALYSIS, retrieved_standards=[]))
        assert r["status"] == AgentStatus.ERROR

    def test_upstream_error(self):
        assert self.node.execute(_s(status=AgentStatus.ERROR.value))["status"] == AgentStatus.ERROR


class TestGapAnalysisNodeLLM:
    """BL-09..BL-11 — LLM refinement via AzureOpenAIClient, built fresh per invocation."""

    _standards = [{"section": "std-1", "text": "objective a objective b"}]

    def test_llm_refines_coverage_level(self):
        node = GapAnalysisNode(llm=_FakeLLM(content="exceeds_standard"))
        r = node.execute(
            _s(query_type=cs.GAP_ANALYSIS, lesson_plan_text="objective a objective b covered fully", retrieved_standards=self._standards)
        )
        assert r["status"] == AgentStatus.SUCCESS
        assert r["coverage_gaps"][0]["status"] == cs.EXCEEDS

    def test_llm_failure_degrades_to_deterministic(self):
        node = GapAnalysisNode(llm=_FakeLLM(raise_exc=RuntimeError("api down")))
        r = node.execute(
            _s(query_type=cs.GAP_ANALYSIS, lesson_plan_text="objective a objective b covered fully", retrieved_standards=self._standards)
        )
        assert r["status"] == AgentStatus.SUCCESS
        assert r["coverage_gaps"][0]["status"] in cs.COVERAGE_LEVELS

    def test_llm_out_of_taxonomy_response_degrades(self):
        node = GapAnalysisNode(llm=_FakeLLM(content="pass"))
        r = node.execute(
            _s(query_type=cs.GAP_ANALYSIS, lesson_plan_text="objective a objective b covered fully", retrieved_standards=self._standards)
        )
        assert r["coverage_gaps"][0]["status"] in cs.COVERAGE_LEVELS

    def test_no_llm_configured_degrades(self):
        # Real production shape: no secret provisioned, no llm= injected.
        node = GapAnalysisNode()
        r = node.execute(
            _s(query_type=cs.GAP_ANALYSIS, lesson_plan_text="objective a objective b covered fully", retrieved_standards=self._standards)
        )
        assert r["status"] == AgentStatus.SUCCESS
        assert r["coverage_gaps"][0]["status"] in cs.COVERAGE_LEVELS


class TestOutputGateNode:
    def setup_method(self):
        self.node = OutputGateNode()

    def test_success_standard_lookup(self):
        r = self.node.execute(_s(query_type=cs.STANDARD_LOOKUP, mext_citations=[{"subject": "math"}]))
        assert r["status"] == AgentStatus.SUCCESS
        assert r["answer_text"]

    def test_upstream_error(self):
        assert self.node.execute(_s(status=AgentStatus.ERROR.value))["status"] == AgentStatus.ERROR

    def test_s3_gate_blocks_missing_citation(self):
        bad = _s(query_type=cs.STANDARD_LOOKUP, answer_text="no citation here", mext_citations=[], hour_requirement={})
        assert self.node._extra_security_gate_output(bad)["status"] == AgentStatus.ERROR

    def test_s3_gate_blocks_student_identifier_leak(self):
        bad = _s(query_type=cs.STANDARD_LOOKUP, answer_text="student number 1234-5678-9012", mext_citations=[{"subject": "math"}])
        assert self.node._extra_security_gate_output(bad)["status"] == AgentStatus.ERROR

    def test_s3_gate_passes_valid(self):
        good = _s(query_type=cs.STANDARD_LOOKUP, answer_text="1 reference retrieved", mext_citations=[{"subject": "math"}])
        assert self.node._extra_security_gate_output(good) is good

    def test_s3_gate_fires_through_real_call_not_just_in_isolation(self):
        """Regression: _extra_security_gate_output() receives execute()'s OWN
        return value (the framework's S-3 hook contract), not the full
        accumulated graph state. Calling _extra_security_gate_output()
        directly with a hand-built state (as the tests above do) can mask a
        node that forgets to carry query_type/mext_citations into its own
        execute() return — the citation-required check would then always see
        query_type=None and silently never fire. Drive it through the real
        __call__()/execute() path with VERIFIED_EXTERNAL trust to catch that.
        """
        from framework.schemas.trust_level import TrustLevel

        state = _s(
            caller_trust_level=TrustLevel.VERIFIED_EXTERNAL.value,
            query_type=cs.STANDARD_LOOKUP,
            mext_citations=[],
            hour_requirement={},
        )
        result = self.node(state)
        assert result["status"] == AgentStatus.ERROR
        assert "citation" in result["error_log"][0].lower()

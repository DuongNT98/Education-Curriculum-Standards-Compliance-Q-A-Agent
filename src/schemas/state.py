"""AgentCore Platform v1.0 — EDU-C2-012 state schema."""

# Flat TypedDict only (msgpack-safe). Extend AgentState with agent-specific
# fields; no credentials, secrets, or Pydantic models in State.

from typing import Any, NotRequired

from framework.schemas.agent_state import AgentState


class State(AgentState):
    """Education Curriculum Standards & Compliance Q&A Agent state.

    Shared fields (user_input, validated_input, status, node_history, result,
    formatted_output, ...) are inherited from AgentState. All agent-specific
    fields are NotRequired[...] (CoE C8) and read via state.get(...).
    """

    # AgentState is a TypedDict at runtime, but the SDK ships no py.typed marker,
    # so mypy sees it as Any and no longer recognizes State as a TypedDict body -
    # it then rejects every NotRequired[] below as used outside a TypedDict
    # definition. This is a mypy/stub-visibility limitation, not a code error
    # (verified: TypedDict-ness and NotRequired all work correctly at runtime).
    lesson_plan_text: NotRequired[str]  # type: ignore[valid-type]
    subject: NotRequired[str]  # type: ignore[valid-type]
    grade_level: NotRequired[str]  # type: ignore[valid-type]
    # standard_lookup | gap_analysis | hour_requirement
    query_type: NotRequired[str]  # type: ignore[valid-type]
    # Retrieved 学習指導要領 standard passages (VectorRAG path).
    retrieved_standards: NotRequired[list[dict[str, Any]]]  # type: ignore[valid-type]
    mext_citations: NotRequired[list[dict[str, Any]]]  # type: ignore[valid-type]
    # Per-standard 4-level coverage (gap_analysis path only).
    coverage_gaps: NotRequired[list[dict[str, Any]]]  # type: ignore[valid-type]
    coverage_status: NotRequired[str]  # type: ignore[valid-type]
    # Deterministic minimum-hour lookup result (hour_requirement path only).
    hour_requirement: NotRequired[dict[str, Any]]  # type: ignore[valid-type]
    kb_source_ref: NotRequired[str]  # type: ignore[valid-type]
    answer_text: NotRequired[str]  # type: ignore[valid-type]

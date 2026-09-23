"""AgentCore Platform v1.0 — outer pre_process: InputSanitizeNode (S-1 + S-2)."""

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.services import curriculum_service as cs

MAX_INPUT_CHARS = 100_000


class InputSanitizeNode(FunctionNode):
    """Validate the request and reject student PII before it enters state.

    Accepts a JSON payload:
        {"query_text": "<text>", "lesson_plan_text": "<text>" (optional),
         "subject": "<subject>" (optional), "grade_level": "<grade>" (optional),
         "query_type": "<hint>" (optional)}
    Plain-text input (not JSON) is treated as query_text. Rejects payloads
    containing student-PII markers (names, IDs) — curriculum compliance
    operates on lesson-plan structure only, never student data (S-1).
    """

    # S-1: outer boundary node — matches agent.yaml required_trust_level.
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        raw = state.get("user_input", "")
        emit_trace_event(
            "input_sanitize_started",
            {"correlation_id": state.get("correlation_id")},
            state,
        )
        if not isinstance(raw, str) or not raw.strip():
            return {"status": AgentStatus.ERROR.value, "error_log": ["InputSanitizeNode: empty input"]}
        if len(raw) > MAX_INPUT_CHARS:
            return {"status": AgentStatus.ERROR.value, "error_log": ["InputSanitizeNode: input too large"]}

        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                payload = {"query_text": raw}
        except (ValueError, TypeError):
            payload = {"query_text": raw}

        query_text = str(payload.get("query_text", "") or "")
        lesson_plan_text = str(payload.get("lesson_plan_text", "") or "")
        subject = str(payload.get("subject", "") or "")
        grade_level = str(payload.get("grade_level", "") or "")
        query_type_hint = payload.get("query_type")

        if not query_text.strip() and not lesson_plan_text.strip():
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["InputSanitizeNode: 'query_text' or 'lesson_plan_text' is required"],
            }

        # S-1 deterministic student-PII rejection — before any downstream processing.
        if cs.contains_student_pii(query_text) or cs.contains_student_pii(lesson_plan_text):
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": [
                    "InputSanitizeNode: student PII (name/ID) rejected — not required for curriculum compliance"
                ],
            }

        normalized = {
            "query_text": query_text,
            "lesson_plan_text": lesson_plan_text,
            "subject": subject,
            "grade_level": grade_level,
            "query_type": query_type_hint,
        }
        return {
            "lesson_plan_text": lesson_plan_text,
            "subject": subject,
            "grade_level": grade_level,
            "validated_input": json.dumps(normalized, ensure_ascii=False),
            "status": AgentStatus.SUCCESS.value,
        }

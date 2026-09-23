"""AgentCore Platform v1.0 — curriculum compliance helpers (deterministic).

Service layer: pure deterministic domain helpers (the "Tool" layer the Agent
wraps). No routing, no credentials, no side effects. LLM reasoning and
orchestration stay in the nodes.
"""

from __future__ import annotations

import json
import re
from typing import Any

STANDARD_LOOKUP = "standard_lookup"
GAP_ANALYSIS = "gap_analysis"
HOUR_REQUIREMENT = "hour_requirement"
VALID_QUERY_TYPES = (STANDARD_LOOKUP, GAP_ANALYSIS, HOUR_REQUIREMENT)

# Knowledge-base namespace + revision stamp.
KB_NAMESPACE = "mext_gakushu_shidoyoryo"
CURRICULUM_REVISION_YEAR = "2020"

# 4-level coverage taxonomy — binary pass/fail is prohibited (S-3).
EXCEEDS = "exceeds_standard"
MEETS = "meets_standard"
PARTIALLY_MEETS = "partially_meets"
DOES_NOT_MEET = "does_not_meet"
COVERAGE_LEVELS = (EXCEEDS, MEETS, PARTIALLY_MEETS, DOES_NOT_MEET)
# Worst-first ordering for aggregating an overall coverage_status.
_SEVERITY_ORDER = (DOES_NOT_MEET, PARTIALLY_MEETS, MEETS, EXCEEDS)

# Deterministic keyword fallback for query-type classification (LLM refines).
_HOUR_KEYWORDS = ("標準単位数", "授業時数", "minimum hours", "required hours", "hour requirement")
_GAP_KEYWORDS = ("満たしています", "meets the", "lesson plan", "学習計画", "gap")

# Student-PII markers — curriculum compliance operates on lesson-plan structure
# only; student names/IDs are irrelevant and must not enter state (S-1).
_STUDENT_PII_MARKERS = (
    "student_id",
    "student_name",
    "生徒氏名",
    "学籍番号",
    "生徒ID",
    "生徒番号",
)


def contains_student_pii(text: str) -> bool:
    """Deterministic marker scan — S-1 input trust gate (not an LLM check)."""
    low = (text or "").lower()
    return any(marker.lower() in low for marker in _STUDENT_PII_MARKERS)


def classify_query_type(text: str, hinted_type: str | None = None) -> str:
    """Deterministic keyword-based classification fallback.

    An LLM refines this in the node; this guarantees a defined result even
    when no LLM is configured.
    """
    if hinted_type in VALID_QUERY_TYPES:
        return hinted_type
    low = (text or "").lower()
    if any(kw.lower() in low for kw in _HOUR_KEYWORDS):
        return HOUR_REQUIREMENT
    if any(kw.lower() in low for kw in _GAP_KEYWORDS):
        return GAP_ANALYSIS
    return STANDARD_LOOKUP


def load_hour_requirements(hour_requirements_path: str, grade_level: str) -> dict[str, Any] | None:
    """Deterministic structured lookup — never VectorRAG (exact by construction)."""
    import os

    if not grade_level:
        return None
    path = os.path.join(hour_requirements_path, f"{grade_level}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        loaded: dict[str, Any] = json.load(f)
        return loaded


def hour_lookup_for_subject(table: dict[str, Any] | None, subject: str) -> dict[str, Any] | None:
    """Extract the min-hours entry for one subject from a loaded grade table."""
    if not table or not subject:
        return None
    entries = table.get("subjects", {})
    entry = entries.get(subject)
    if entry is None:
        return None
    return {
        "subject": subject,
        "grade_level": table.get("grade_level"),
        "min_hours": entry.get("min_hours"),
        "source_ref": table.get("source_ref", ""),
    }


def aggregate_coverage_status(coverage_gaps: list[dict[str, Any]]) -> str:
    """Overall coverage_status = worst-case level among per-standard entries."""
    if not coverage_gaps:
        return DOES_NOT_MEET
    levels = {g.get("status") for g in coverage_gaps}
    for level in _SEVERITY_ORDER:
        if level in levels:
            return level
    return DOES_NOT_MEET


def is_upstream_error(status: Any) -> bool:
    val = getattr(status, "value", status)
    return bool(val == "error")


_PII_LEAK_RE = re.compile(r"\b\d{4}-?\d{4}-?\d{4}\b")


def leaks_student_identifier(text: str) -> bool:
    """Deterministic output-side re-check for a 12-digit ID-shaped pattern."""
    return bool(_PII_LEAK_RE.search(text or ""))

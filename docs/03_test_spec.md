# Test Specification

## Test Strategy
- Coverage target: every node ≥1 unit success + ≥1 error/edge; full graph ≥1 integration per query-type path
- Test types: Unit (`tests/unit/`) / Integration (`tests/integration/`) / Proof-of-boundary (`tests/proof_of_boundary/`)

## Framework Compliance Tests (Mandatory)

| TC-ID | Test | Expected Result | Result |
|-------|------|----------------|--------|
| TC-01 | State contract: flat TypedDict | Type check pass, no Pydantic/dataclass | PASS |
| TC-02 | SecurityViolationError fires on invalid input | Error raised, no exception | PASS |
| TC-03 | No JWT/Credential in State | CI `gate-credential-scan`: 0 violations (S-5 enforcement moved to the CI gate) | PASS |
| TC-04 | InvocationContext via configurable only | Never stored in State after invoke | PASS |
| TC-05 | S-4: no duplicate lifecycle events in `execute()` | `node_start` / `node_complete` / `node_error` absent from `execute()` body | 0 duplicates |
| TC-06 | S-2: `_security_gate_input()` not overridden (`FunctionNode` subclass) | `TypeError` raised at class definition if overridden (`@final` enforced by framework) | 0 overrides |
| TC-07 | S-3: `_security_gate_output()` not overridden (`FunctionNode` subclass) | `TypeError` raised at class definition if overridden (`@final` enforced by framework) | 0 overrides |
| TC-08 | `required_trust_level` enforced | Insufficient trust → refused | PASS |
| TC-09 | S-2: `_extra_security_gate_input()` non-trivial when domain checks needed | Default framework PII scan on `user_input` sufficient; student-PII rejection implemented as a deterministic check in `InputSanitizeNode.execute()` itself | N/A (see design rationale) |
| TC-10 | S-3: `_extra_security_gate_output()` non-trivial when domain checks needed | `OutputGateNode` blocks output missing citation/source_ref + blocks student-identifier leak | Hook body non-trivial |
| TC-11 | S-4: at least one domain `emit_trace_event()` inside each `execute()` | Domain event emitted on every invocation path | ≥1 per node (all 5) |

## Proof-of-Boundary Tests (Mandatory)

| PB-ID | Boundary | Test | Expected Result | Result |
|-------|----------|------|----------------|--------|
| PB-1 | BaseNode → EventEmitter | `emit_trace_event()` fires on every invocation path | No silent failures | PASS |
| PB-2 | State serialization | Post-invoke State is primitives only | No Pydantic/dataclass | PASS |
| PB-3 | L1 → External service | VectorRAG retriever + LLM injected via config | Real data retrieval (FakeRetriever/FakeLLM in integration test) | PASS |
| PB-4 | Import isolation | No Level 0 imports | AST scan: 0 violations | PASS |
| PB-5 | Checkpoint safety | No JWT/Pydantic in checkpoint | Inspection pass | PASS |
| PB-6 | Invoke execution order | `__call__()`: S-1 trust gate → S-4 `node_start` → S-2 `_security_gate_input` → `execute()` → S-3 `_security_gate_output` → S-4 `node_complete` | Order verified for all 5 `FunctionNode`s (GraphNode excluded — deliberate delegated lifecycle) | PASS |
| PB-7 | HITL interrupt propagation | N/A — `hitl.enabled` not set | Auto-skip stub present (exact-name, required every template) | SKIP (N/A) |

## Business Logic Tests

| TC-ID | Test | Input | Expected Result | Result |
|-------|------|-------|----------------|--------|
| BL-01 | Standard lookup path | Curriculum question + subject/grade | `mext_citations[]` populated, `answer_text` set | PASS |
| BL-02 | Gap analysis 4-level coverage | Lesson-plan text + `query_type=gap_analysis` | `coverage_gaps[]` per standard, `coverage_status` ∈ 4-level taxonomy (never binary) | PASS |
| BL-03 | Hour-requirement deterministic lookup | `query_type=hour_requirement`, subject/grade | Exact `min_hours` from `config/hour_requirements/{grade}.json` | PASS |
| BL-04 | Student-PII rejection | Input containing `student_id`/生徒氏名-style marker | `InputSanitizeNode` returns ERROR before entering state | PASS |
| BL-05 | Citation-required output gate | Output missing `mext_citations`/`source_ref` | `OutputGateNode._extra_security_gate_output` blocks | PASS |
| BL-06 | LLM refines query classification | Well-formed Azure OpenAI test-double response | `query_type` overrides the deterministic keyword result | PASS |
| BL-07 | LLM query-classify failure degrades | Test double raises / returns out-of-taxonomy text | `query_type` falls back to the deterministic keyword result, `status=success` | PASS |
| BL-08 | No LLM configured degrades (query_classify) | No secret bound, no `llm=` injected (real production shape) | `query_type` = deterministic keyword result, `status=success` | PASS |
| BL-09 | LLM refines gap-analysis coverage level | Well-formed Azure OpenAI test-double response | Per-standard `status` overrides the deterministic overlap-ratio level | PASS |
| BL-10 | LLM gap-analysis failure degrades | Test double raises / returns out-of-taxonomy text | Per-standard `status` falls back to the deterministic overlap level, `status=success` | PASS |
| BL-11 | No LLM configured degrades (gap_analysis) | No secret bound, no `llm=` injected (real production shape) | Per-standard `status` = deterministic overlap level, `status=success` | PASS |

## Test Execution Summary
- Execution date: 2026-07-10
- Total tests: unit (25) + integration (6) + proof_of_boundary (4, incl. PB-7 auto-skip)
- Pass: all / Fail: 0 / Skip: 1 (PB-7, N/A — HITL not enabled)
- Coverage: every node has ≥1 success + ≥1 error/edge unit test; all 3 query-type paths covered at integration level

# Template Design Specification

## Position in AgentCore Architecture

- **Agent Class**: `Graph` (`src/graph/graph.py`)
- **L1 Base**: `AgentBaseGraph` (L1 direct) — outer graph; Cat 2 pattern (outer + `GraphNode` main
  slot + inner `BaseGraph` subgraph). `RAGAgent` is a pattern reference in `agent.yaml base_type`
  only, not an inheritance target.
- **Three-Layer Separation**:
  - State: flat TypedDict composition (no Pydantic — msgpack incompatible)
  - Node: L1 inheritance (Template Method: `execute(self, state: dict) -> dict` override only)
  - Graph: composition (`register_nodes()` for node substitution)

## Architecture Overview

### Node Configuration

| Node | Responsibility | Input State | Output State | Inherits/Overrides |
|------|---------------|-------------|--------------|-------------------|
| initialize | Session/schema setup | — | `schema_version`, `session_id` | InitializeNode (default) |
| pre_process | `InputSanitizeNode` — validate, reject student PII (S-1/S-2), serialize `validated_input` | `user_input` | `lesson_plan_text`, `subject`, `grade_level`, `validated_input` | `FunctionNode` |
| main | `CurriculumGraphNode` — wraps inner curriculum-compliance workflow | `validated_input` | `query_type`, `retrieved_standards`, `mext_citations`, `coverage_gaps`, `coverage_status`, `hour_requirement`, `kb_source_ref` | `GraphNode` |
| post_process | `OutputGateNode` — assemble `answer_text`, S-3 citation-required gate | merged main output | `answer_text`, `formatted_output` | `FunctionNode` |
| finalize | Response metadata | — | `response_metadata`, `total_time_ms` | FinalizeNode (default) |

**Inner subgraph** (`src/graph/curriculum_workflow_graph.py`, instantiated by `CurriculumGraphNode`):

| Inner node | Responsibility | LLM? |
|---|---|---|
| `query_classify` | Classify `standard_lookup` / `gap_analysis` / `hour_requirement`; extract subject/grade | ✅ (deterministic fallback) |
| `curriculum_retrieve` | VectorRAG standards retrieval (standard_lookup/gap_analysis) OR deterministic hour-table lookup (`config/hour_requirements/{grade_level}.json`) | ❌ |
| `gap_analysis` | (gap_analysis path only) lesson-plan vs standards → 4-level coverage per standard; no-op pass-through on other paths | ✅ (deterministic fallback) |

### Data Flow

```
START → initialize → pre_process(InputSanitizeNode) → main(CurriculumGraphNode) → post_process(OutputGateNode) → finalize → END
                                                              │
                                                              ▼ (inner subgraph)
                                            query_classify → curriculum_retrieve → gap_analysis → END
```

### State Definition

| Field | Type | Purpose | Required |
|-------|------|---------|----------|
| `lesson_plan_text` | `NotRequired[str]` | Lesson-plan content for gap analysis | No |
| `subject` | `NotRequired[str]` | Subject hint (e.g. `math`) | No |
| `grade_level` | `NotRequired[str]` | Grade-level hint (e.g. `middle_school_year_2`) | No |
| `query_type` | `NotRequired[str]` | `standard_lookup` / `gap_analysis` / `hour_requirement` | No |
| `retrieved_standards` | `NotRequired[list[dict]]` | Retrieved 学習指導要領 passages (VectorRAG path) | No |
| `mext_citations` | `NotRequired[list[dict]]` | MEXT citation records (subject/grade/section) | No |
| `coverage_gaps` | `NotRequired[list[dict]]` | Per-standard 4-level coverage (gap_analysis path) | No |
| `coverage_status` | `NotRequired[str]` | Aggregate coverage status (worst-case level) | No |
| `hour_requirement` | `NotRequired[dict]` | Deterministic min-hours lookup result | No |
| `kb_source_ref` | `NotRequired[str]` | KB namespace or hour-table source reference | No |
| `answer_text` | `NotRequired[str]` | Final assembled answer text | No |

**State Constraints (mandatory):**
- Flat TypedDict only (primitives + JSON-serializable types)
- No JWT, API keys, credentials in State (checkpoint DB leakage)
- InvocationContext via `config["configurable"]` only (not in State)
- No Pydantic models, dataclass, arbitrary Python objects (msgpack incompatible)

## Framework Utilization

### Shared Components Used
- [x] InvocationContext (correlation_id, session_id, permissions, credential handle)
- [ ] ConnectionPolicy (retry/timeout strategy) — default `max_retry`/`timeout_seconds` only
- [x] SecurityViolationError (fail-closed ERROR dicts, no raise)
- [x] S-2: `_extra_security_gate_input()` — not overridden (default PII scan on `user_input`
      sufficient); domain-specific student-PII rejection is implemented as a deterministic check
      in `InputSanitizeNode.execute()` itself (rejects before entering state)
- [x] S-3: `_extra_security_gate_output()` — `OutputGateNode` implements the preservation+filter
      variant: blocks output missing a citation/source_ref, and blocks output leaking a
      student-identifier-shaped value (12-digit pattern)
- [x] S-4: `emit_trace_event()` — at least one domain-specific event inside each `execute()`
      (mandatory; no `node_start`/`node_complete`/`node_error` re-emitted)

> **S-2/S-3 gate behaviour by node type (ADR-017):**
> - `FunctionNode` subclass → framework `@final` gate always runs automatically;
>   extend via `_extra_security_gate_input()` / `_extra_security_gate_output()` only
> - `GraphNode` (`CurriculumGraphNode`) → deliberate no-op (inner subgraph nodes are all
>   `ANONYMOUS`-trust `FunctionNode`s; the outer boundary gates at pre/post_process)

### Composition Pattern

- **Pattern**: `GraphNode` (subgraph) — Cat 2, outer `AgentBaseGraph` + `GraphNode` main slot +
  inner `BaseGraph` (`CurriculumWorkflowGraph`)
- **Composition target**: `src/graph/curriculum_workflow_graph.py`
- **Error propagation strategy**: `propagate` (fail-fast; no HITL in this template)

## Import Isolation Confirmation
- [x] Template does not import agenticstar-platform SDK (Level 0)
- [x] Import targets: framework/ and shared/ only (no agents/base/ required)

## Security Notes (from scaffold issue)

- **S-1**: `InputSanitizeNode` (outer) rejects any input containing student-PII markers
  (names, IDs) before it enters state — curriculum compliance operates on lesson-plan structure
  and objectives only.
- **S-2**: No APPI concern — 学習指導要領 is a public document; lesson plans contain no student
  personal data.
- **S-3**: `OutputGateNode` requires a citation (MEXT reference or hour-table `source_ref`) on
  every answer; gap analysis reports specific standard IDs with 4-level granularity — binary
  pass/fail is prohibited by construction (`coverage_status` is always one of
  `exceeds_standard`/`meets_standard`/`partially_meets`/`does_not_meet`).
- **Secrets (LLM refinement)**: `query_classify` and `gap_analysis` each build an
  `AzureOpenAIClient` fresh per invocation, inside `execute()`, resolving
  `AZURE_OPENAI_API_KEY`/`AZURE_OPENAI_ENDPOINT`/`AZURE_OPENAI_DEPLOYMENT` via
  `InvocationContext.from_state(state).secrets.require(...)` — declared in
  `config/agent.yaml requires.secrets`, never cached on the node instance (registry LRU-cached
  node instances are shared across callers), never read from `config/config.yaml`. **Error
  handling**: any failure in that path (secret not provisioned, API error, malformed/
  out-of-taxonomy response) is caught and silently keeps the deterministic keyword/overlap
  result already computed — the pipeline never raises or returns `status=error` over an LLM
  outage; a missing secret is a fully supported deployment shape, not a degraded one.

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| L1 base type | AgentBaseGraph | AutonomousBaseGraph | **AgentBaseGraph** | Fixed multi-step compliance workflow, not an autonomous loop |
| Composition pattern | Flat 3-node (Cat 1 style) | GraphNode + inner subgraph (Cat 2) | **GraphNode + inner subgraph** | 3 distinct query-type paths + `GapAnalysisNode` comparative step require Cat 2 pattern (`gate-composition`) |
| Hour-requirement storage | VectorRAG | Deterministic CSV/JSON | **Deterministic CSV/JSON** (`config/hour_requirements/`) | Exact minimum-hour figures must never be approximated |

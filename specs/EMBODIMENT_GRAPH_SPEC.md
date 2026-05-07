# Embodiment Graph Spec v0.3

A graph describes one task-oriented collaboration of nodes within a two-layer architecture:

1. **Cooperation Network** (upper layer) — determines which node-pairs are approved for cooperation by a human operator. Governed by a cooperation policy.
2. **Execution Network** (lower layer) — defines concrete data-flow and control edges between approved pairs, with ordering semantics (serial, parallel, conditional).

Graphs must describe an **intent**, not enumerate pairwise connections.

## Schema

```yaml
schema: embodiment_graph/v3
graph_id: <slug>
name: Human-readable Name
intent: One sentence describing what the graph achieves.
trigger_keywords: [describe, observe, ...]     # keywords for intent-matching graph selection
safety_level: sensor_only | motion_supervised | full_humanoid

cooperation_network:
  policy_ref: <path_or_inline>          # path to cooperation_policy/v1 file, or "inline"
  default_approval: approved            # default if pair is not listed
  # Only needed when policy_ref is "inline":
  pairs:
    - source: <node_id>
      target: <node_id>
      approval: approved | denied | pending_human_review
      approved_by: <operator_id | "policy_default">

roles:
  - role_id: <slug>
    description: Why this role exists.
    required_capabilities: [observe, listen, ...]
    preferred_nodes: [<node_id>, ...]      # optional hint
    minimum: 1                              # default 1
    maximum: 1                              # default 1; use 9999 for "all available"

nodes:
  - id: <node_id>
    role: <role_id>
    participant_type: robot_node | sensor_node | agent_node
    node_type: physical_robot | sensor | perception_model | llm_agent | human_operator
    agent_subtype: llm_agent | human_operator    # required when participant_type is agent_node
    required_capabilities: [...]

edges:
  - source: <node_id>
    target: <node_id>
    edge_type: observation_stream | command | query | approval_request | feedback | context_feed | memory
    ordering: serial | parallel | conditional
    condition: <expression>                 # required when ordering is conditional
    protocol_hint: http | ros | grpc | local
    data_direction: push | pull | bidirectional
    latency_estimate_ms: <int | null>       # null for human response time
    dormant: false                          # true when cooperation is revoked; edge exists but is inactive

constraints:
  allow_motion: false
  allow_manipulation: false
  allow_audio_output: false
  forbidden_actions: [navigate, grasp, pick, ...]   # required, non-empty for sensor_only graphs

readiness_checks:
  - all_required_nodes_exist
  - required_capabilities_are_safe
  - sensor_artifacts_available_or_capture_allowed
  - no_forbidden_action_in_task
  - cooperation_approved_for_all_active_edges     # NEW in v3

failure_modes:
  - id: node_missing
    when: required node id is not in topology
    attribution: topology
  - id: node_offline
    when: node exists but adapter/endpoint is unreachable
    attribution: hardware
  - id: capability_missing
    when: node does not declare a required safe capability
    attribution: configuration
  - id: forbidden_action_requested
    when: task asks for an action listed in constraints.forbidden_actions
    attribution: planner
  - id: cooperation_denied
    when: edge required by task is dormant (cooperation revoked)
    attribution: cooperation_policy
  - id: sensor_artifact_missing
    when: expected image/audio file is not produced
    attribution: sensor
  - id: unverified_audio_pickup
    when: audio file exists but RMS is zero or speech is not detected
    attribution: sensor
  - id: approval_timeout
    when: human_operator did not respond within configured timeout
    attribution: human_operator

recovery:
  auto_allowed:
    - retry_passive_health_check
    - choose_alternate_observer
    - downgrade_multiview_to_single_view
    - use_alternate_non_dormant_path
  requires_confirmation:
    - any_motion
    - any_manipulation
    - audio_output
    - safety_level_promotion
    - reactivate_dormant_edge
  not_recoverable:
    - missing_capable_executor
    - all_paths_dormant

outputs:
  - episode_trace
  - readiness_report
  - cooperation_state_snapshot
  - <task-specific output>
```

## Two-Layer Architecture

### Layer 1: Cooperation Network

The cooperation network is a **permission layer**. Each undirected pair of nodes has an approval state:

| State | Meaning |
|-------|---------|
| `approved` | Execution edges between this pair are active |
| `denied` | All execution edges between this pair are dormant |
| `pending_human_review` | Edges dormant until human approves |

**Default**: All pairs are `approved` unless the cooperation policy explicitly denies them.

When a pair's approval changes from `approved` to `denied`:
- All execution edges (in either direction) between those two nodes become `dormant: true`
- The edges are NOT deleted from the graph — they remain as potential paths
- The agent sees them in EMBODIMENT.md under "Cooperation boundaries > Dormant"
- If the pair is later re-approved, edges become `dormant: false` again

**Rollback**: Resetting to policy file defaults clears all runtime overrides atomically.

### Layer 2: Execution Network

The execution network defines HOW approved nodes collaborate. Each edge has:

| Field | Purpose |
|-------|---------|
| `ordering` | Whether this edge runs serial (after predecessor), parallel (concurrent), or conditional (gated) |
| `condition` | For conditional edges: the boolean expression that must be true |
| `protocol_hint` | Communication protocol hint for agent planning (not enforced) |
| `data_direction` | Who initiates: source pushes, target pulls, or bidirectional |
| `latency_estimate_ms` | Expected latency; helps agent plan realistic workflows |
| `dormant` | Whether the cooperation layer has deactivated this edge |

**Ordering semantics**:
- `parallel`: Multiple edges from the same source (or to the same target) execute concurrently
- `serial`: This edge waits for all preceding serial edges in the execution path to complete
- `conditional`: This edge only executes if `condition` evaluates to true at runtime

## Node Participant Types

Every node declares a `participant_type`:

| Type | Description | Example |
|------|-------------|---------|
| `robot_node` | Physical robot body | Unitree G1 |
| `sensor_node` | Standalone sensor device | USB camera, microphone |
| `agent_node` | Software agent or human operator | LLM planner, human supervisor |

Agent nodes require `agent_subtype`:
- `llm_agent` — an LLM-based planner/executor (Claude, GPT, local model)
- `human_operator` — a human participating in the execution loop

## Edge Types

| Edge Type | Meaning | Typical Direction |
|-----------|---------|-------------------|
| `observation_stream` | Sensor data flowing to a consumer | sensor → agent |
| `command` | Action instruction | agent → robot |
| `query` | Request for information | agent → sensor |
| `approval_request` | Gated action requiring human approval | llm_agent → human_operator |
| `feedback` | Result or status returned | target → source |
| `context_feed` | Planning context or scene description | perception → planner |
| `memory` | Persistent state or episode data | any → any |

## Required Top-Level Keys

Validators must enforce:

- `schema` (must be `embodiment_graph/v3`)
- `graph_id`
- `name`
- `intent`
- `trigger_keywords` (non-empty; used for intent-matching graph selection)
- `safety_level`
- `cooperation_network` (policy_ref or inline pairs)
- `roles` (non-empty)
- `nodes` (non-empty, at least one `participant_type: agent_node`)
- `edges` (non-empty; each edge must have `ordering` and `protocol_hint`)
- `constraints.forbidden_actions` (non-empty if `safety_level: sensor_only`)
- `readiness_checks` (non-empty; must include `cooperation_approved_for_all_active_edges`)
- `failure_modes` (non-empty)
- `recovery`
- `outputs`

## Naming

Graph IDs describe **what the graph does**, not which nodes it connects:

Good:
```text
cooperative_dual_view_observation
motion_with_human_confirmation
sensor_health_audit
```

Bad:
```text
g1_realsense__usb_camera__dual_view
g1__human__llm_graph
```

## Backwards Compatibility

| Schema | Status |
|--------|--------|
| `embodiment_graph/v3` | Current; full two-layer support |
| `embodiment_graph/v2` | Accepted with deprecation warning; no cooperation layer, no edge ordering |
| `embodiment_graph/v1` | Legacy pairwise; accepted with deprecation warning |

The builder internally upgrades v2 graphs for validation: missing `cooperation_network` defaults to `{default_approval: approved}`, missing `ordering` defaults to `parallel`, missing `participant_type` inferred from `node_type`.

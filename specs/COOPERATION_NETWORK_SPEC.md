# Cooperation Network Spec v0.1

The cooperation network is the **upper layer** of the embodiments two-layer graph architecture. It controls WHICH nodes are permitted to collaborate, while the execution network (lower layer) controls HOW they collaborate.

## Purpose

Physical robot systems need human oversight over which autonomous agents and hardware nodes can interact. The cooperation network provides:

1. A declarative policy file defining default approval states
2. Runtime override capability for dynamic revocation/approval
3. Atomic rollback to policy defaults
4. First-class human-in-loop participation

## Schema: `cooperation_policy/v1`

```yaml
schema: cooperation_policy/v1
name: <policy_name>
version: <semver>
description: <one-line purpose>

default_approval: approved | denied | pending_human_review

pairs:
  - source: <node_id>
    target: <node_id>
    approval: approved | denied | pending_human_review
    reason: <why this override exists>
    approved_by: <operator_id | "policy_default">
    approved_at: <epoch | null>
    revoked_at: <epoch | null>

global_constraints:
  sensor_only_nodes_cannot_initiate_motion_edges: true
  agent_nodes_require_explicit_registration: true
  human_operator_must_exist_for_supervisor_class: true

rollback:
  trigger: manual | on_safety_violation
  target: this_file
```

## Approval States

| State | Execution Edges | Agent Visibility |
|-------|-----------------|------------------|
| `approved` | Active; agent can plan through them | Listed under "Active cooperation" |
| `denied` | Dormant; hidden from execution | Listed under "Dormant cooperation" |
| `pending_human_review` | Dormant until human confirms | Listed under "Pending approval" |

**Default**: `approved` — all node pairs can cooperate unless explicitly denied. This is the recommended default for most deployments.

## Pair Directionality

Cooperation is **bidirectional by default**. If `source: A, target: B` is denied, then ALL execution edges between A and B (in either direction) become dormant. To deny only one direction, the runtime must use execution-level constraints instead.

## Dormant Edge Semantics

When cooperation is revoked between two nodes:

1. All execution edges between the pair gain `dormant: true`
2. The edges remain in the graph definition — they are NOT deleted
3. The agent sees them as "potential but currently inactive" paths
4. Readiness check `cooperation_approved_for_all_active_edges` prevents planning through dormant edges
5. If cooperation is re-approved, edges become `dormant: false` immediately

Dormant edges serve as documentation of WHAT cooperation would look like if approved. This enables:
- Agents to suggest re-enabling cooperation when needed
- Humans to understand what they're approving before granting access
- Zero-delay reactivation when approval is granted

## Runtime Override API

The cooperation network supports runtime modifications via a simple API:

### `cooperation.approve(source, target, operator_id)`

Activates cooperation between two nodes. Sets `dormant: false` on all execution edges between them.

```json
{
  "action": "cooperation.approve",
  "source": "g1_real_sensor_only",
  "target": "llm_planner",
  "operator_id": "human_operator_01",
  "timestamp": 1714377600.0
}
```

### `cooperation.revoke(source, target, operator_id)`

Deactivates cooperation between two nodes. Sets `dormant: true` on all execution edges between them.

```json
{
  "action": "cooperation.revoke",
  "source": "g1_real_sensor_only",
  "target": "external_llm_agent",
  "operator_id": "human_operator_01",
  "reason": "Untrusted agent detected",
  "timestamp": 1714377600.0
}
```

### `cooperation.rollback()`

Resets ALL runtime overrides to the policy file defaults. This is an **atomic operation**:

```json
{
  "action": "cooperation.rollback",
  "operator_id": "human_operator_01",
  "target": "policy_file"
}
```

**Rollback behavior**:
1. Read the cooperation policy file from disk
2. Discard all runtime override state
3. Recompute `dormant` flags on all edges based on policy file pairs
4. Return the new cooperation state

### `cooperation.list()`

Returns the current cooperation state (policy defaults + any runtime overrides).

```json
{
  "action": "cooperation.list"
}
```

Response:
```json
{
  "default_approval": "approved",
  "active_overrides": [
    {"source": "a", "target": "b", "approval": "denied", "operator_id": "..."}
  ],
  "computed_pairs": [
    {"source": "a", "target": "b", "effective_approval": "denied", "source_is": "runtime_override"},
    {"source": "a", "target": "c", "effective_approval": "approved", "source_is": "policy_default"}
  ]
}
```

## Human Operator as Participant

A `human_operator` is a first-class node in the graph, not just an external approver. It participates in the execution network as both:

1. **Approval gate**: Other nodes send `approval_request` edges to the human; execution waits for response
2. **Active collaborator**: The human can be source of `command` or `feedback` edges

The human_operator node:
- Has `participant_type: agent_node` and `agent_subtype: human_operator`
- Is ALWAYS approved to cooperate with any node (via `global_constraints.human_operator_overrides`)
- Can receive `approval_request` edges from `llm_agent` nodes
- Can send `command` edges to robot nodes (direct teleoperation)
- Can send `feedback` edges back to `llm_agent` nodes

## Global Constraints

These constraints apply regardless of per-pair approval:

| Constraint | Effect |
|-----------|--------|
| `sensor_only_nodes_cannot_initiate_motion_edges` | A sensor_node cannot be source of a `command` edge with motion intent |
| `agent_nodes_require_explicit_registration` | Agent nodes must be listed in registry before they can participate |
| `human_operator_must_exist_for_supervisor_class` | If safety_level requires supervisor, graph must include a human_operator node |

## Interaction with Safety Profiles

The cooperation network and safety profiles are **independent but composable**:

- Safety profile determines WHAT actions are allowed (forbidden, confirmation, safe)
- Cooperation network determines WHO can interact with whom

If a safety profile forbids motion, then even an approved cooperation pair cannot execute motion edges. Safety takes precedence.

| Safety Profile | Cooperation Restriction |
|---------------|------------------------|
| `sensor_only` | Only sensor-class edges active; motion/command edges dormant regardless of approval |
| `motion_supervised` | Motion edges require human approval in execution flow |
| `full_humanoid` | All edge types active if cooperation approved |

## Validation Rules

The builder validates cooperation networks:

1. All `source` and `target` in `pairs[]` must reference valid node IDs in the registry
2. `default_approval` must be one of the three valid states
3. `rollback.target` must be `this_file` (future versions may support other targets)
4. If a graph has edges between two nodes that are `denied` in the cooperation policy, those edges must have `dormant: true`
5. Graphs with `safety_level: sensor_only` cannot have non-dormant `command` edges

## File Placement

```
<package>/
  cooperation_policy.yaml         # package-level policy
  embodiment.yaml                 # references policy via cooperation_network.policy_ref

policies/
  default_cooperation_policy.yaml # system-level default
```

Packages may inline the policy (for self-contained distribution) or reference an external file (for shared policies across packages).

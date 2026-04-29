# Embodiment Graph Spec v0.2

A graph in `<package>/graphs/*.yaml` describes one task-oriented or role-oriented collaboration of physical/topology nodes.

Graphs must not be generated as pairwise (A-B, A-C, B-C) explosions. They must describe an intent.

## Schema

```yaml
schema: embodiment_graph/v2
graph_id: <slug>
name: Human-readable Name
intent: One sentence describing what the graph achieves.
safety_level: sensor_only | motion_with_confirmation | manipulation_with_confirmation

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
    node_type: physical_robot | sensor | perception_model | ...
    required_capabilities: [...]

edges:
  - source: <node_id>
    target: <node_id>
    edge_type: observation_stream | query | command | memory | ...

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
  - id: sensor_artifact_missing
    when: expected image/audio file is not produced
    attribution: sensor
  - id: unverified_audio_pickup
    when: audio file exists but RMS is zero or speech is not detected
    attribution: sensor

recovery:
  auto_allowed:
    - retry_passive_health_check
    - choose_alternate_observer
    - downgrade_multiview_to_single_view
  requires_confirmation:
    - any_motion
    - any_manipulation
    - audio_output
    - safety_level_promotion
  not_recoverable:
    - missing_capable_executor

outputs:
  - episode_trace
  - readiness_report
  - <task-specific output>
```

## Required sections

Validators must enforce these top-level keys:

- `schema` (must be `embodiment_graph/v2`)
- `graph_id`
- `name`
- `intent`
- `safety_level`
- `roles` (non-empty)
- `nodes` (non-empty)
- `constraints.forbidden_actions` (non-empty if `safety_level: sensor_only`)
- `readiness_checks` (non-empty)
- `failure_modes` (non-empty)
- `recovery`
- `outputs`

## Naming

Graph IDs should describe **what the graph does**, not which nodes it connects:

Good:

```text
sensor_only_multiview_observation
audio_readiness_check
single_view_fallback_observation
```

Bad:

```text
g1_realsense__usb_camera__dual_view
g1__mic__camera_graph
```

## Backwards compatibility

The legacy schema `embodiment_graph/v1` (pairwise nodes/edges only) is still accepted by the validator but is deprecated. The legacy composer at `embodiments/composer_legacy/` emits v1.

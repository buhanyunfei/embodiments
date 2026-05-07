---
name: g1_usb_dual_view
description: Dual-view sensor collaboration with G1 RealSense ego view and external USB camera. Includes LLM planner and human-in-loop.
version: 0.4.0
kind: embodiment_context
active_safety_profile: sensor_only
workflows:
  - dual_view_observation
  - sensor_health_audit
---

# G1 + USB Camera Dual-View Embodiment Context

This is the agent's primary instruction for this embodiment. Read it like a `SKILL.md`. It describes available hardware, agent nodes, tool interfaces, cooperation boundaries, and execution workflows.

## When to use

- Task asks to describe, compare, or summarize the workspace from multiple angles.
- Task needs both ego (robot-mounted) and third-person (external) views.
- G1 is online and external USB camera is connected.
- Health check or connectivity audit of sensors is needed.

## When not to use

- G1 needs to move (use a motion-capable embodiment).
- Audio output is required (forbidden here).
- Only one camera is reachable — recover into single-view via `downgrade_multiview_to_single_view`, or use a single-sensor context.
- All cooperation paths to a target node are dormant.

## Active safety profile

Active profile: **`sensor_only`** — Capture-only mode. Only safe-class actions. Locomotion, manipulation, and audio output are forbidden.

| class | behavior under this profile |
|---|---|
| `safe` | plan freely |
| `motion` | **forbidden** |
| `manipulation` | **forbidden** |
| `audio_output` | **forbidden** |

## Available nodes

### `g1_real_sensor_only` — G1 Sensor-Only Observer
- Type: `physical_robot` · Participant: `robot_node` · Role: `robot_local_view`
- Sensors: `realsense_color_camera`
- Limits: `{"sensor_only": true, "movement_allowed": false, "manipulation_allowed": false}`
- Safe capabilities: `observe, inspect, perceive`

### `g1_realsense_color_sensor` — G1 RealSense Color Sensor
- Type: `sensor` · Participant: `sensor_node` · Role: `robot_local_view`
- Parent robot: `g1_real_sensor_only`
- Safe capabilities: `observe, perceive`

### `usb_camera_real` — External USB Camera
- Type: `sensor` · Participant: `sensor_node` · Role: `external_view`
- Safe capabilities: `observe, perceive`

### `llm_planner` — LLM Planning Agent
- Type: `agent_node` · Participant: `agent_node` · Role: `planner`
- Agent subtype: `llm_agent`
- Safe capabilities: `plan, reason, describe`

### `human_operator` — Human Operator
- Type: `agent_node` · Participant: `agent_node` · Role: `supervisor`
- Agent subtype: `human_operator`
- Safe capabilities: `approve, supervise, override, rollback`

## Tool interfaces

### `g1_real_sensor_only` tools

| Operation | Protocol | Endpoint | Latency | Safety Class |
|-----------|----------|----------|---------|--------------|
| `health_check` | http | GET /health | ~50ms | safe |
| `get_state` | http | GET /state | ~30ms | safe |

### `g1_realsense_color_sensor` tools

| Operation | Protocol | Endpoint | Latency | Safety Class |
|-----------|----------|----------|---------|--------------|
| `capture_frame` | http | POST /sensors/capture | ~200ms | safe |

### `usb_camera_real` tools

| Operation | Protocol | Endpoint | Latency | Safety Class |
|-----------|----------|----------|---------|--------------|
| `capture_frame` | http | POST /sensors/capture | ~150ms | safe |
| `health_check` | http | GET /health | ~30ms | safe |

### `llm_planner` tools

| Operation | Protocol | Endpoint | Latency | Safety Class |
|-----------|----------|----------|---------|--------------|
| `generate_plan` | tool_call | tool_call | ~3000ms | safe |
| `describe_scene` | tool_call | tool_call | ~2000ms | safe |

### `human_operator` tools

| Operation | Protocol | Endpoint | Latency | Safety Class |
|-----------|----------|----------|---------|--------------|
| `request_approval` | tool_call | tool_call | variable | safe |
| `provide_feedback` | tool_call | tool_call | variable | safe |

## Cooperation boundaries

### Active cooperation

| Source | Target | Approved By |
|--------|--------|-------------|
| `g1_realsense_color_sensor` | `perception_vision` | policy_default |
| `usb_camera_real` | `perception_vision` | policy_default |
| `perception_vision` | `llm_planner` | policy_default |
| `llm_planner` | `human_operator` | policy_default |
| `llm_planner` | `g1_real_sensor_only` | policy_default |
| `llm_planner` | `usb_camera_real` | policy_default |

### Dormant cooperation (revoked or pending)

_None — all pairs are active._

### Rollback

To reset all runtime overrides: call `cooperation.rollback()`. Restores policy file defaults atomically.

## Execution workflows

### Workflow: Dual-view observation
1. [parallel] `capture_frame` → `g1_realsense_color_sensor` (http, ~200ms)
2. [parallel] `capture_frame` → `usb_camera_real` (http, ~150ms)
3. [serial] send both frames → `perception_vision` via `describe_scene` (local, ~2000ms)
4. [serial] return fused dual-view description → `llm_planner`
5. [serial] present result to user (or forward to `human_operator` if feedback needed)

### Workflow: Single-view fallback
1. [serial] detect that one camera is offline (health_check fails)
2. [serial] trigger `downgrade_multiview_to_single_view` recovery
3. [serial] `capture_frame` → remaining camera
4. [serial] describe with single-view context, tag result `single_view_fallback`

### Workflow: Health audit
1. [parallel] `health_check` → `g1_real_sensor_only` (http, ~50ms)
2. [parallel] `health_check` → `usb_camera_real` (http, ~30ms)
3. [serial] aggregate results → `llm_planner`
4. [serial] report connectivity status to user

## How to plan

The agent selects the appropriate graph by matching user intent to trigger keywords:

| Workflow ID | Intent | Trigger Keywords |
|-------------|--------|------------------|
| `dual_view_observation` | Describe workspace using both views with human oversight | describe, observe, see, look, view |
| `sensor_health_audit` | Check connectivity and readiness of all hardware | health, status, check, ready, online |

### Worked examples

1. "Describe what you see from both viewpoints."
   → Select workflow `dual_view_observation`. Call `g1_realsense_color_sensor.capture_frame` and `usb_camera_real.capture_frame` in parallel. Send both frame paths to `llm_planner.describe_scene`. Return fused description.

2. "USB camera unplugged. What now?"
   → Trigger `downgrade_multiview_to_single_view` recovery. Call `g1_realsense_color_sensor.capture_frame` only. Tag result `single_view_fallback`.

3. "Have G1 walk to the table for a closer look."
   → **REFUSE** — `walk` is forbidden under `sensor_only`. Suggest switching to `motion_supervised` profile.

4. "Are all sensors online?"
   → Select workflow `sensor_health_audit`. Call `g1_real_sensor_only.health_check` and `usb_camera_real.health_check` in parallel. Report status.

### Planning rules

1. Match user intent to graph via `trigger_keywords`.
2. Check cooperation boundaries — do not plan through dormant edges.
3. Check safety profile before any non-safe action.
4. For confirmation-class actions: route through `human_operator.request_approval`.
5. Do not invent capabilities not in the registry.
6. Use tool interfaces for concrete execution — generate actual tool calls.

## Forbidden actions

```text
navigate
walk
move
turn
grasp
pick
place
carry
hand_over
open_door
whole_body_motion
arm_motion
hand_motion
audio_output
```

If the user requests a forbidden action, refuse and explain which profile would allow it.

## Failure modes

| Code | When it fires | Attribution |
|---|---|---|
| `node_missing` | Camera node absent from topology | topology |
| `node_offline` | Capture/health endpoint unreachable | hardware |
| `cooperation_denied` | Edge is dormant (cooperation revoked) | cooperation_policy |
| `forbidden_action_requested` | Task action is in forbidden list | planner |
| `sensor_artifact_missing` | Expected frame file not produced | sensor |
| `approval_timeout` | Human did not respond | human_operator |

## Recovery

**Auto-recovery**: retry passive health check; downgrade multi-view to single-view; use alternate non-dormant path; skip offline node.

**Requires confirmation**: any motion, any manipulation, audio output, reactivate dormant edge, safety level promotion.

**Not recoverable**: requests for navigation/grasp/carry; all cooperation paths dormant; missing capable executor.

## Runtime integration

1. Mount this package via the agent system's embodiment loader (`embodiments.activate("g1_usb_dual_view")`).
2. Context: inject this `EMBODIMENT.md` into the agent's system prompt.
3. Tools: register all `tool_interface.operations` (non-forbidden, non-dormant) as callable tools.
4. Cooperation: enforce cooperation boundaries before tool dispatch — check `cooperation_network` state.
5. Safety: check `forbidden_actions` + `requires_confirmation` at the executor before dispatch.
6. Rollback: `cooperation.rollback()` resets runtime overrides to policy file defaults.

---
name: g1_usb_dual_view
description: Sensor-only collaboration context that pairs G1 RealSense ego view with an external USB third-person view. Use for "describe the workspace from two angles" tasks while G1 stays as observer.
version: 0.3.0
kind: embodiment_context
primary_agent_doc: EMBODIMENT.md
primary_graph: sensor_only_dual_view_observation
---

# G1 + USB Camera Dual-view Embodiment Context

This is a sensor-only collaboration context that pairs a Unitree G1's ego RealSense view with an external USB camera for a third-person view. It is the intended context for "describe the scene with two views" tasks while the G1 is restricted to observer role.

## When to use

- The task asks to describe, compare, or summarize the workspace from multiple angles.
- A robot-local view is needed in addition to a third-person view.
- The G1 is online and the external USB camera is connected to the host.

## When not to use

- The G1 is allowed to move (use a different, executor-capable embodiment).
- Audio output is required (forbidden here).
- Only one camera is reachable — recover into single-view via `recovery.auto_allowed: downgrade_multiview_to_single_view`, or use the `current_lab_sensor_context` graph instead.

## Available nodes

(also inlined in `embodiment.yaml > registry.nodes`)

### `g1_real_sensor_only` — G1 Sensor-Only Observer
- Type: `physical_robot` · Role: `robot_local_view`
- Safe capabilities: `observe, inspect, perceive`
- Limits: `sensor_only=true`, motion+manipulation disabled.

### `g1_realsense_color_sensor` — G1 RealSense Color Sensor
- Type: `sensor` · Role: `robot_local_view`
- Safe capabilities: `observe, perceive`
- Parent robot: `g1_real_sensor_only`

### `usb_camera_real` — External USB Camera
- Type: `sensor` · Role: `external_view`
- Safe capabilities: `observe, perceive`

## How to plan

The single primary graph is `sensor_only_dual_view_observation` (inlined in `embodiment.yaml > graphs[0]`).

- *User*: "Describe what you see from both viewpoints."
  *Plan*: capture one frame each from `g1_realsense_color_sensor` and `usb_camera_real`; send both to `perception_vision`; return a single dual-view description.
- *User*: "USB camera unplugged. What now?"
  *Plan*: trigger `downgrade_multiview_to_single_view` recovery; continue with `g1_realsense_color_sensor` only and tag the result `single_view_fallback`.
- *User*: "Have G1 walk to the table for a closer look."
  *Plan*: refuse — `walk` is forbidden. Offer to capture closer frames if a fixed camera or a different ego-camera can reach the area.

Planning rules:

1. Always use both views when both are reachable; downgrade only when one is offline.
2. Use `perception_vision` (a runtime-provided perception model role) to fuse the two streams.
3. Never plan motion through this context.
4. Pull frames via the existing adapters; do not open new network endpoints automatically.

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

## Failure modes

| Code | When it fires | Attribution |
|---|---|---|
| `node_missing` | One of the two camera nodes is absent from topology | topology |
| `node_offline` | Capture probe fails for either sensor | hardware |
| `sensor_artifact_missing` | At least one expected frame file was not produced | sensor |
| `forbidden_action_requested` | Task contained a forbidden action | planner |

## Recovery

Auto-recovery:

- `retry_passive_health_check`;
- `downgrade_multiview_to_single_view`.

Requires explicit user confirmation:

- any motion, any manipulation, audio output;
- promoting the package out of `sensor_only`.

Not recoverable here:

- requests for navigation, grasp, carry, or handover.

## Runtime integration

A topology runtime should:

1. parse this `EMBODIMENT.md` for planner-grounding context;
2. read `embodiment.yaml > registry.nodes` and register the three nodes (only with user authorization);
3. load the inlined `graphs[0]` as the task template;
4. enforce `safety.forbidden_actions` at the executor before any dispatch;
5. surface failure-mode codes verbatim in the episode trace.

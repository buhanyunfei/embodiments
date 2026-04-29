---
name: unitree_g1_sensor_only
description: Sensor-only embodiment for a Unitree G1. Forbids motion, manipulation, and audio output. Use for ego/local-view observation through onboard RealSense, plus passive presence checks.
version: 0.2.0
kind: robot
primary_agent_doc: EMBODIMENT.md
---

# Unitree G1 Sensor-only Embodiment

This package describes a Unitree G1 used as a **sensor/observer node only**. The G1 has arms, hands, and legs physically present, but every motor action is forbidden by this embodiment. Read this file before planning any task that touches a G1 node.

## When to use

Use this package when the task requires:

- ego/local view through the G1's RealSense color camera (`g1_realsense_color_sensor`);
- passive presence verification of the G1 on the network (control IP `192.168.123.161`, dev IP `192.168.123.164`);
- audio readiness *check* (capture only, never output);
- onboarding the G1 into a topology runtime in a strictly observer role.

## When not to use

Do not use this package for walking, navigating, arm/hand/whole-body motion, grasping, picking, placing, carrying, handover, opening doors, or producing sound through the G1 speakers. If the user's task requires any of those, refuse and ask them to switch to a verified executor-capable embodiment. Do not silently substitute this package for a missing executor.

## Available nodes

This package introduces two topology nodes (also defined inline in `embodiment.yaml > registry.nodes`).

### `g1_real_sensor_only` — G1 Sensor-Only Observer

- Type: `physical_robot` · Role: `robot_local_view`
- Safe capabilities: `observe, inspect, listen, perceive, health_check`
- Sensors: `realsense_color_camera, realsense_depth_camera, onboard_audio_capture, lowstate_readonly`
- Limits: `sensor_only=true, movement_allowed=false, manipulation_allowed=false`
- Verified evidence (`evidence/probe_2026-04-28.json`): RealSense D435I serial `233722071669`, firmware `5.16.0.1`; `/dev/video0`–`/dev/video5` present; one color frame captured to `hub/static/frames/g1_realsense_color.jpg` without any motor command.
- Unverified: G1 microphone pickup — default `arecord` produced WAV with RMS=0; route still needs verification.

### `g1_realsense_color_sensor` — G1 RealSense Color Sensor

- Type: `sensor` · Role: `robot_local_view`
- Safe capabilities: `observe, perceive`
- Parent robot: `g1_real_sensor_only`

## How to plan

Treat the G1 here strictly as an observer.

- *User*: "Show me what G1 sees."
  *Plan*: capture one frame from `g1_realsense_color_sensor` to `hub/static/frames/g1_realsense_color.jpg`. Send to a runtime-provided perception model. Return scene description.
- *User*: "Is the G1 microphone working?"
  *Plan*: record 1–2 s on `g1_real_sensor_only`. Report RMS. **Tag the result `unverified_audio_pickup`** if RMS is zero (current evidence shows that path is unverified).
- *User*: "Have G1 walk forward 1 meter."
  *Plan*: refuse. `walk` is in this package's forbidden list. Suggest the user switch to (or onboard) an executor-capable embodiment.
- *User*: "Carry the box for me."
  *Plan*: refuse. `carry` is forbidden. Offer an alternative: observe the box from `g1_realsense_color_sensor` and describe it.

Planning rules:

1. Use the registry node ids verbatim — do not invent new ones.
2. Run `probes/passive_probe.py` to confirm both networks reachable; run `probes/sensor_probe.py` before assuming RealSense is enumerable.
3. Audio recording is allowed for capture verification, but `audio_output` is forbidden under any condition.

## Forbidden actions

These must not be planned or executed through this package under any condition.

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
| `node_offline` | Control or dev network unreachable, or SSH path closed | hardware |
| `sensor_artifact_missing` | RealSense capture script ran but no frame file produced | sensor |
| `unverified_audio_pickup` | Recording produced but RMS is zero | sensor |
| `forbidden_action_requested` | Task asked for navigate/grasp/walk/audio_output | planner |

## Recovery

Auto-recovery (no confirmation needed):

- retry the passive probe;
- fall back from RealSense to lowstate read-only;
- swap to an external USB camera as third-person view (use the `usb_1080p_camera` package or a graph that combines them).

Requires explicit user confirmation:

- any motion, any manipulation, any audio output;
- promoting this package out of `sensor_only` (requires verified executor evidence and explicit policy).

Not recoverable here:

- requests for navigation, grasp, carry, or handover.

## Runtime integration

A topology runtime should:

1. parse this `EMBODIMENT.md` for planner-grounding context;
2. read `embodiment.yaml > registry.nodes` and register the two nodes (only with user authorization);
3. enforce `safety.forbidden_actions` and `safety.requires_confirmation_for` at the executor, not just the planner;
4. run `probes/` only during explicit onboarding, never during build.

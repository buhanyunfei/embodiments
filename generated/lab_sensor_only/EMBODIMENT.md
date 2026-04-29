---
name: lab_sensor_only
description: 'Embodiment context for 5 device(s). Active profile: sensor_only. Switch
  profile or constrain via prompt to change allowed actions.'
version: 0.3.0
kind: embodiment_context
active_safety_profile: sensor_only
primary_graph: observation
---

# Lab Sensor Only

This file is the agent's primary instruction for this embodiment context. Read it the way you would read a `SKILL.md`. It describes the **full capability set** of available hardware and how to plan with it safely.

## When to use this embodiment

Use this when the task involves 5 real device(s) listed below. This is real hardware — never substitute a mock node for a missing real one.

## When not to use this embodiment

Do not use this embodiment for tasks that require capabilities not present in the device registry, or when a device is offline and no valid fallback exists.

## Active safety profile

Active profile: **`sensor_only`** — Capture-only mode. Only safe-class actions. Locomotion, manipulation, and audio output are forbidden. Use for first-time onboarding, read-only inspection, and any session where the robot must not move.

| class | behavior under this profile |
|---|---|
| `safe` | plan freely |
| `motion` | **forbidden** |
| `manipulation` | **forbidden** |
| `audio_output` | **forbidden** |

## Changing the safety profile

The user can change the safety profile at prompt time. Available profiles:

- **`sensor_only`**: Locomotion + manipulation + audio_output forbidden. Read-only. ← current
- **`motion_supervised`**: Locomotion enabled with confirmation. Manipulation forbidden. Good for mobile inspection.
- **`full_humanoid`**: All capabilities available. Motion requires confirmation. Manipulation requires confirmation + supervisor.

## Available nodes

### `camera_usb_real` — USB Camera Sensor
- Type: `sensor` · Role: `external_view`

  Capability status under active profile:

  | capability | class | active profile status |
  |---|---|---|
  | `capture_frame` | `unknown` | `confirmation` |
  | `perceive` | `safe` | `safe` |
  | `vision` | `unknown` | `confirmation` |

### `g1_real_sensor_only` — G1 Sensor-Only Observer
- Type: `physical_robot` · Role: `robot_local_view`
- Sensors: `realsense_color_camera, realsense_depth_camera, onboard_audio_capture, lowstate_readonly`
- Limits: `{"movement_allowed": false, "manipulation_allowed": false, "sensor_only": true, "g1_ctrl_ip": "192.168.123.161", "g1_dev_ip": "192.168.123.164"}`
- Profile note: # G1 Real Sensor-Only Session Profile

  Capability status under active profile:

  | capability | class | active profile status |
  |---|---|---|
  | `inspect` | `safe` | `safe` |
  | `listen` | `safe` | `safe` |
  | `observe` | `safe` | `safe` |
  | `perceive` | `safe` | `safe` |
  | `standby` | `safe` | `safe` |
  | `wait` | `safe` | `safe` |

### `g1_realsense_color_sensor` — G1 RealSense Color Sensor
- Type: `sensor` · Role: `robot_local_view`
- Last sensor artifact: `hub/static/frames/g1_realsense_color.jpg`

  Capability status under active profile:

  | capability | class | active profile status |
  |---|---|---|
  | `capture_frame` | `unknown` | `confirmation` |
  | `observe` | `safe` | `safe` |
  | `perceive` | `safe` | `safe` |
  | `vision` | `unknown` | `confirmation` |

### `usb_camera_real` — External USB Camera
- Type: `sensor` · Role: `external_view`
- Last sensor artifact: `hub/static/frames/usb_camera.jpg`

  Capability status under active profile:

  | capability | class | active profile status |
  |---|---|---|
  | `capture_frame` | `unknown` | `confirmation` |
  | `observe` | `safe` | `safe` |
  | `perceive` | `safe` | `safe` |
  | `vision` | `unknown` | `confirmation` |

### `usb_mic_real` — External USB Microphone
- Type: `sensor` · Role: `audio_input`
- Last audio RMS: `560` (verified)

  Capability status under active profile:

  | capability | class | active profile status |
  |---|---|---|
  | `audio_capture` | `unknown` | `confirmation` |
  | `listen` | `safe` | `safe` |
  | `voice_input` | `unknown` | `confirmation` |

## How to plan

The primary graph is `observation` (inlined in `embodiment.yaml > graphs[0]`).

Worked examples mapping user requests to plans:

- *User*: "Describe the workspace."
  *Plan*: capture frames from `g1_real_sensor_only` (ego) and `camera_usb_real` (third-person); send to `perception_vision`; return dual-view description. No motion required.

- *User*: "Is the microphone working?"
  *Plan*: record 1–2 s on `g1_real_sensor_only`; report RMS. Tag `unverified_audio_pickup` if RMS stays zero.

- *User*: "Walk forward 1 meter."
  *Plan*: **refuse** — `walk` is forbidden under the `sensor_only` profile. Tell the user to switch to `motion_supervised` profile and try again.

- *User*: "Pick up the cup."
  *Plan*: **refuse** — `pick` is forbidden under the `sensor_only` profile. Tell the user to switch to `full_humanoid` profile (which requires supervisor signoff) and try again.

- *User*: "Describe what the robot sees compared to the external camera."
  *Plan*: run `observation` graph; assign `g1_real_sensor_only` to `robot_local_view` role, `camera_usb_real` to `external_view`, `perception_vision` to `perception_model`. Return fused dual-view description.

Planning rules:

1. Check the active safety profile before planning any non-safe-class action.
2. For motion-class actions: obtain explicit user confirmation in the current conversation scope.
3. For manipulation-class actions: obtain confirmation + supervisor signoff before proceeding.
4. Do not invent capabilities not in the node registry.
5. Do not proceed past a failed readiness check.
6. Report results tagged with any `unverified_*` codes where evidence is absent.

## Forbidden actions

Under the **active profile**, these actions must not be planned or executed:

_None forbidden under this profile. Confirm + supervisor rules still apply to motion/manipulation._

If the user requests a forbidden action, refuse and explain which profile would allow it.

## Failure modes

| Code | When it fires | Attribution |
|---|---|---|
| `node_missing` | Required node not in topology | topology |
| `node_offline` | Node unreachable | hardware |
| `capability_missing` | Node lacks required capability | configuration |
| `forbidden_action_requested` | Task action is forbidden under active profile | planner |
| `missing_confirmation` | Motion/manipulation planned without prior confirmation | planner |
| `sensor_artifact_missing` | Frame/audio file not produced | sensor |
| `unverified_audio_pickup` | Audio captured but RMS=0 | sensor |

## Recovery

Auto-recovery:

- retry passive health check;
- choose alternate observer;
- downgrade multi-view to single-view.

Requires explicit confirmation:

- any motion, any manipulation, audio output (default if no profile specified).

Not recoverable:

- requests for a capability class that is forbidden under the active profile and the user refuses to switch profiles.

## Runtime integration

1. Parse this `EMBODIMENT.md` as planner-grounding context.
2. Read `embodiment.yaml > registry.nodes` for the full device registry.
3. Read `embodiment.yaml > graphs[0]` for the primary observation graph.
4. Read `embodiment.yaml > safety.active_safety_profile` to confirm the active profile.
5. Enforce the profile at the executor — check `forbidden_actions` + `requires_confirmation` before dispatch.
6. Surface all failure codes verbatim in episode traces.

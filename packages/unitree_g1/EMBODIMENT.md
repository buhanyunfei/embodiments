---
name: unitree_g1
description: >
  Full-capability embodiment for Unitree G1 humanoid. Covers sensing, locomotion, manipulation, and
  audio. Active profile gates what the agent may plan immediately vs. confirm vs. supervisor-signoff.
  Default profile is sensor_only (safe for first onboard). Switch to motion_supervised or full_humanoid
  to unlock locomotion and manipulation.
version: 0.3.0
kind: robot
primary_agent_doc: EMBODIMENT.md
default_safety_profile: sensor_only
---

# Unitree G1 Humanoid Embodiment

This file is the agent's primary instruction for the Unitree G1. It describes the **full capability space** — sensing, locomotion, manipulation, and audio — together with the safety rules that gate each class. Read it the way you read a `SKILL.md` before planning any task involving the G1.

The G1 is a bipedal humanoid with: two arms + dexterous hands, leg locomotion, an onboard Intel RealSense D435I (RGB + depth), microphones, speakers, and an onboard Ubuntu compute unit at `192.168.123.164` (dev) / `192.168.123.161` (ctrl).

## When to use

- Any task that involves a Unitree G1 physically present in the deployment.
- When the user needs first-person ego view, audio presence check, locomotion, or manipulation through the G1.
- When onboarding G1 into a topology runtime as any role (observer, actor, or collaborator).

## When not to use

- When the G1 is absent from topology or powered off.
- When a task requires capabilities not listed in this package.
- When no safety profile has been confirmed by the user and the task requires motion or manipulation.

## Active safety profile

> **Default: `sensor_only`**. Switch to a richer profile by including `--safety-profile` in the onboarding command or by explicitly stating the profile in your conversation prompt.

| Profile | Locomotion | Manipulation | Audio output |
|---|---|---|---|
| `sensor_only` | **forbidden** | **forbidden** | **forbidden** |
| `motion_supervised` | requires confirmation | **forbidden** | requires confirmation |
| `full_humanoid` | requires confirmation | requires confirmation + supervisor | requires confirmation |

### Changing the profile at prompt time

A user can say any of the following, and you should select the matching profile:

- "Just observe / sensor only / no motion" → `sensor_only`
- "Let G1 walk / navigate / move" → `motion_supervised`
- "Let G1 pick up / grasp / carry / hand over" → `full_humanoid`

Never switch to a higher-risk profile silently. Always state which profile you are using.

## Available nodes

### `g1_real_sensor_only` — G1 Humanoid (main node)

- Type: `physical_robot` · Role: `robot_local_view`
- IPs: ctrl `192.168.123.161`, dev `192.168.123.164`
- Sensors: `realsense_color_camera`, `realsense_depth_camera`, `onboard_audio_capture`, `imu`, `lowstate_readonly`

Full capability table:

| capability | class | sensor_only | motion_supervised | full_humanoid |
|---|---|---|---|---|
| `perceive` | safe | ✅ plan freely | ✅ | ✅ |
| `observe` | safe | ✅ | ✅ | ✅ |
| `inspect` | safe | ✅ | ✅ | ✅ |
| `listen` | safe | ✅ (audio RMS=0 in test, see evidence) | ✅ | ✅ |
| `health_check` | safe | ✅ | ✅ | ✅ |
| `wait` / `standby` | safe | ✅ | ✅ | ✅ |
| `walk` | motion | ❌ forbidden | ⚠️ confirm first | ⚠️ confirm first |
| `turn` | motion | ❌ | ⚠️ | ⚠️ |
| `navigate` | motion | ❌ | ⚠️ | ⚠️ |
| `whole_body_motion` | motion | ❌ | ⚠️ | ⚠️ |
| `reach` | manipulation | ❌ | ❌ | ⚠️ + supervisor |
| `grasp` | manipulation | ❌ | ❌ | ⚠️ + supervisor |
| `pick` | manipulation | ❌ | ❌ | ⚠️ + supervisor |
| `place` | manipulation | ❌ | ❌ | ⚠️ + supervisor |
| `carry` | manipulation | ❌ | ❌ | ⚠️ + supervisor |
| `hand_over` | manipulation | ❌ | ❌ | ⚠️ + supervisor |
| `arm_motion` | manipulation | ❌ | ❌ | ⚠️ + supervisor |
| `hand_motion` | manipulation | ❌ | ❌ | ⚠️ + supervisor |
| `audio_output` | audio_output | ❌ | ⚠️ confirm | ⚠️ confirm |

### `g1_realsense_color_sensor` — G1 RealSense D435I

- Type: `sensor` · Role: `robot_local_view`
- Parent robot: `g1_real_sensor_only`
- Capabilities: `observe`, `perceive` (safe in all profiles)
- Serial: `233722071669` · Firmware: `5.16.0.1`
- Last captured frame: `hub/static/frames/g1_realsense_color.jpg`

## How to plan

### Sensor-only tasks (any profile)

- *User*: "What does the G1 see?"
  *Plan*: capture one frame from `g1_realsense_color_sensor`; send to `perception_vision`; return description. No motion needed.

- *User*: "Is G1's microphone working?"
  *Plan*: record 1–2 s via `g1_real_sensor_only` listen capability. Report RMS. **Tag `unverified_audio_pickup`** if RMS=0 (current evidence shows this for the default route).

### Motion tasks (motion_supervised or full_humanoid profile required)

- *User*: "Walk to the table."
  *Plan (sensor_only)*: **refuse** — `walk` is forbidden. Say: "The active profile is `sensor_only`. Switch to `motion_supervised` to enable locomotion."
  *Plan (motion_supervised)*: ask "Confirm: G1 will walk to the table. Proceed?" → if confirmed, plan `walk` + `navigate`; run `obstacle_check` and `floor_clear` readiness checks first.

- *User*: "Turn left 90°."
  *Plan (sensor_only)*: **refuse** — `turn` is forbidden.
  *Plan (motion_supervised)*: confirm "G1 will turn left 90°" → if confirmed, plan `turn`.

### Manipulation tasks (full_humanoid profile required)

- *User*: "Pick up the cup."
  *Plan (sensor_only)*: **refuse** — `pick` is forbidden. Suggest switching to `full_humanoid`.
  *Plan (motion_supervised)*: **refuse** — `pick` is forbidden in this profile. Suggest `full_humanoid`.
  *Plan (full_humanoid)*: require user confirmation AND supervisor signoff. State "This requires supervisor sign-off. Confirm pick action for `g1_real_sensor_only`?" → if both obtained, plan `grasp` + `pick`; run `object_identified` + `grasp_plan_verified` readiness.

- *User*: "Carry the box to the shelf."
  *Plan*: Same as pick — requires `full_humanoid` + supervisor. Refuse otherwise.

### G1 + USB camera collaboration

- *User*: "Show me the scene from both the robot's view and the external camera."
  *Plan*: assign `g1_realsense_color_sensor` to `robot_local_view` role, `usb_camera_real` to `external_view`; send both to `perception_vision`; return dual-view description. No motion required.

## Forbidden actions

Under **`sensor_only`** (default) all motion, manipulation, and audio output actions are forbidden:

```text
walk
turn
navigate
move
whole_body_motion
follow
reach
grasp
pick
place
carry
hand_over
open_door
arm_motion
hand_motion
audio_output
```

Under **`motion_supervised`**: manipulation class actions are forbidden.
Under **`full_humanoid`**: nothing is absolutely forbidden at framework level; supervisor readiness gates manipulation.

**Never fabricate a rationale to bypass these.** Tell the user which profile is needed.

## Failure modes

| Code | When it fires | Attribution |
|---|---|---|
| `node_offline` | G1 ctrl/dev network unreachable, SSH closed | hardware |
| `sensor_artifact_missing` | RealSense script ran but no frame file produced | sensor |
| `unverified_audio_pickup` | Recording produced but RMS=0 | sensor |
| `forbidden_action_requested` | Task asks for a class forbidden by active profile | planner |
| `missing_confirmation` | Motion/manipulation planned without prior user confirmation | planner |
| `missing_supervisor` | Manipulation attempted without supervisor signoff | planner |

## Recovery

Auto-recovery:
- retry passive health check (ping ctrl + dev IPs);
- fall back to lowstate read-only if RealSense unavailable;
- use external USB camera as third-person view fallback.

Requires confirmation:
- any motion, any audio output (in `motion_supervised` or higher);
- any manipulation (in `full_humanoid` only).

Requires supervisor:
- manipulation execution (in `full_humanoid`).

Not recoverable:
- requests for a forbidden-class action when the user refuses to switch profiles.

## Runtime integration

1. Parse this `EMBODIMENT.md` for planner context; note the `default_safety_profile`.
2. Read `embodiment.yaml > registry.nodes` for the node list.
3. Read `embodiment.yaml > safety_profiles` to understand the full profile options.
4. Enforce the active profile at the executor — check `forbidden_classes` + `confirmation_classes` + `supervisor_classes` before dispatch.
5. Run `probes/passive_probe.py` on first onboard; run `probes/sensor_probe.py` before sensor tasks.
6. Use `adapters/g1_adapter.py` for HTTP-based command dispatch (motion commands require active confirmation token before the adapter accepts them).

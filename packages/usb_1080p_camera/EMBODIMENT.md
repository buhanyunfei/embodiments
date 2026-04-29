---
name: usb_1080p_camera
description: Sensor-only embodiment for a generic 1080P USB camera (and optional USB mic). Use for third-person workspace observation and microphone capture-readiness checks. No motion. No audio output.
version: 0.2.0
kind: sensor
primary_agent_doc: EMBODIMENT.md
---

# 1080P USB Camera Embodiment

This package describes a generic external USB camera (1080p) plus an optional USB microphone, used as sensor nodes for observation and audio-capture readiness checks.

## When to use

- The task needs a third-person view of the workspace from a fixed external camera.
- The task needs an audio readiness check from a microphone independent of any robot.
- Lightweight sensor-only onboarding without any robot dependency.

## When not to use

- The user wants audio playback / speech output (forbidden here even though the device may have output).
- The task needs an ego/local view from a robot — use `unitree_g1_sensor_only` for that.
- Any task that needs motion or manipulation; this package has no executor.

## Available nodes

This package introduces two topology nodes (also inlined in `embodiment.yaml > registry.nodes`).

### `usb_camera_real` — External USB Camera

- Type: `sensor` · Role: `external_view`
- Safe capabilities: `observe, perceive`
- Verified evidence (`evidence/probe_2026-04-28.json`): `/dev/video0` (and `/dev/video1`) present, card 2 reports "1080P USB Camera". Single frame captured to `hub/static/frames/usb_camera.jpg`.

### `usb_mic_real` — External USB Microphone

- Type: `sensor` · Role: `audio_input`
- Safe capabilities: `listen`
- ALSA: `plughw:2,0`. Sample rate 16 kHz.
- Verified evidence: 2 s recording produced **non-zero RMS** (≈560) — pickup is verified.

## How to plan

- *User*: "Take a photo of the workspace."
  *Plan*: capture one frame from `usb_camera_real` to `hub/static/frames/usb_camera.jpg`. Return image path.
- *User*: "Is the desk microphone alive?"
  *Plan*: record 1–2 s on `usb_mic_real` at 16 kHz. Report RMS. Pickup is already verified (RMS≈560 in evidence), so a fresh non-zero result confirms readiness; tag `unverified_audio_pickup` only if the new recording is silent.
- *User*: "Stream the camera over the internet."
  *Plan*: refuse without explicit user confirmation; this package does not auto-expose endpoints. The runtime must require user authorization for any new network exposure.
- *User*: "Play a beep on the speaker."
  *Plan*: refuse. `audio_output` is forbidden in this embodiment.

Planning rules:

1. Run `probes/passive_probe.py` to confirm `/dev/video*` exists before capture.
2. Run `probes/sensor_probe.py` to capture a single frame; do not stream continuously by default.
3. Use the node ids verbatim. Both nodes default to `sensor_only=true`.

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
| `node_offline` | `/dev/video*` device disappeared (cable, hub, USB port) | hardware |
| `sensor_artifact_missing` | Capture script ran but no frame file | sensor |
| `unverified_audio_pickup` | New recording produced but RMS is zero | sensor |
| `forbidden_action_requested` | Task asked for `audio_output` or motion | planner |

## Recovery

Auto-recovery:

- retry passive probe;
- fall back to a lower resolution if the requested resolution is unavailable.

Requires explicit user confirmation:

- any audio output;
- exposing the camera stream to a network endpoint.

Not recoverable here:

- requests for motion or manipulation; this package has no executor.

## Runtime integration

A topology runtime should:

1. parse this `EMBODIMENT.md` for planner-grounding context;
2. read `embodiment.yaml > registry.nodes` and register `usb_camera_real` (and `usb_mic_real` if present) on user authorization;
3. enforce `safety.forbidden_actions` at the executor;
4. run capture probes only during explicit onboarding, never during build.

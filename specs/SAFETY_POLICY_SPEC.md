# Embodiment Safety Policy Spec v0.1

Embodiment packages describe physical entities. Safety is not optional. Five invariants apply.

## Invariant 1 — Build is offline

Building or validating a package must not contact hardware, must not call any HTTP/SSH endpoint, and must not actuate a robot. The builder is a static archiver.

Hardware probing is a separate explicit step, performed by `probes/passive_probe.py` or `probes/sensor_probe.py`, never during build.

## Invariant 2 — Install does not move

Installing a package must not move hardware, must not produce audio, and must not write to a robot command endpoint. A package that violates this rule is invalid.

## Invariant 3 — sensor-only by default

A package, profile, or registry node marked `sensor_only: true` must not declare any of the following as a safe action or default capability:

```text
navigate, walk, move, turn,
grasp, pick, place, carry, hand_over, open_door,
whole_body_motion, arm_motion, hand_motion,
audio_output
```

If a sensor-only package needs one of these, it must:

1. drop `sensor_only`;
2. provide verified evidence under `evidence/`;
3. add an explicit `policies/safety.yaml` that promotes safety level;
4. require explicit user authorization at runtime.

The builder validator enforces (1) statically. The runtime enforces (4) at executor dispatch.

## Invariant 4 — Forbidden actions are explicit and non-empty

A `embodiment_context` package must declare a non-empty `safety.forbidden_actions` in `embodiment.yaml`. An empty or missing list is a validation error.

A graph with `safety_level: sensor_only` must declare a non-empty `constraints.forbidden_actions`.

## Invariant 5 — No mock substitution for missing real hardware

If a package or generated graph references a real-device node and that node is not present in topology, the runtime must fail fast. It must not silently substitute a mock node, a stub adapter, or a cached frame.

`robot_mode="hub"` must not silently degrade to `mock`.

## LLM constraints

When the composer runs in `--mode llm-assisted`, the LLM may improve prose. It must not:

- invent capabilities not in `registry/nodes.yaml`;
- remove forbidden actions;
- promote a sensor-only robot to executor;
- claim verified evidence not present under `evidence/`;
- add motion/manipulation graphs unless `policies/safety.yaml` promotes them.

The composer applies a deterministic validator to the LLM output and falls back to the deterministic doc on any violation. The fallback reason is recorded in `LLM_REJECTED.json` next to the package for review.

## Credentials

- Packages must not contain API keys, SSH keys, robot tokens, or per-deployment IP addresses in `embodiment.yaml`.
- `evidence/*.json` may contain IPs only if they are intentional public-facing artifacts; otherwise they should be redacted.
- The composer must not log full `api_key` values; only `sk-...****` is acceptable.

## Forbidden actions reference

The framework's default forbidden set:

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

Individual packages may add to this set but must not remove from it.

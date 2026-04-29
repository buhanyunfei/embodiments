# Building Embodiments

This guide shows how to author and build an embodiment package in the slim 2-file layout.

## 1. Pick the kind

```text
robot                 single robot model
sensor                single sensor (camera, mic, lidar, ...)
actuator              gripper, base, arm, ...
hardware_rig          fixed multi-device setup
embodiment_graph      a single collaboration graph
embodiment_context    a deployment-level context with one or more graphs (recommended top-level)
```

## 2. Create the directory

```bash
mkdir -p embodiments/packages/my_robot/{evidence,probes,adapters}
touch embodiments/packages/my_robot/EMBODIMENT.md
touch embodiments/packages/my_robot/embodiment.yaml
```

That is the entire layout. Do **not** create separate `registry/`, `graphs/`, `profiles/`, or `README.md` files; everything goes inline.

## 3. Write `embodiment.yaml`

Minimal context package (slim):

```yaml
schema: embodiment_package/v2
package_id: my_lab_context
name: My Lab Sensor-only Context
version: 0.1.0
kind: embodiment_context
license: Apache-2.0
summary: Agent-readable embodiment context for My Lab.
primary_agent_doc: EMBODIMENT.md

registry:
  schema: embodiment_node_registry/v1
  nodes:
    - id: my_camera
      name: My Camera
      node_type: sensor
      role: external_view
      safe_capabilities: [observe, perceive]
      limits: {sensor_only: true}

graphs:
  - schema: embodiment_graph/v2
    graph_id: sensor_only_observation
    name: Sensor-only Observation
    intent: Describe the workspace using my_camera, without moving any robot.
    safety_level: sensor_only
    roles: [...]
    nodes: [...]
    constraints:
      forbidden_actions: [navigate, walk, grasp, ...]
    readiness_checks: [...]
    failure_modes: [...]
    recovery: {...}
    outputs: [...]

safety:
  default_policy: sensor_only
  install_must_not_actuate: true
  forbidden_actions: [navigate, walk, grasp, pick, carry, audio_output, ...]

integration:
  exposes_agent_context: true
  compatible_with: [auwomo_physclaw, openclaw_like_runtime]
```

See `specs/EMBODIMENT_PACKAGE_SPEC.md` for the full field reference.

## 4. Write `EMBODIMENT.md`

Use YAML frontmatter on top, then 8 concrete sections:

```markdown
---
name: my_lab_context
description: One-line, very concrete; the agent reads this to decide whether to use the package.
version: 0.1.0
kind: embodiment_context
primary_agent_doc: EMBODIMENT.md
---

# My Lab Sensor-only Context

## When to use
...

## When not to use
...

## Available nodes
...

## How to plan
- *User*: "..."  *Plan*: ... use `my_camera` ...
- *User*: "..."  *Plan*: refuse, this asks for a forbidden action.

## Forbidden actions
```text
navigate
walk
grasp
...
```

## Failure modes
...

## Recovery
...

## Runtime integration
...
```

The validator enforces these section headings for `kind: embodiment_context`. See `specs/AGENT_READABLE_CONTEXT_PACKAGE.md`.

## 5. Validate

```bash
python embodiments/builder/build_embodiment.py validate embodiments/packages/my_lab_context
```

This is offline. It checks fields, schema, kind, layout, safety, and EMBODIMENT.md sections.

## 6. Build

```bash
python embodiments/builder/build_embodiment.py build embodiments/packages/my_lab_context \
  --out embodiments/dist
```

## 7. Generate from a topology snapshot

If you have a topology snapshot, you can ask the composer to draft the whole 2-file package:

```bash
python embodiments/composer/compose_context.py generate \
  --topology hub/topology_snapshot.json \
  --package-id my_lab_context \
  --out embodiments/generated
```

The composer defaults to `--mode auto`: it calls the configured LLM if `hub/copaw_config.json` is present, else falls back to deterministic generation. Use `--mode llm` to require LLM, `--mode deterministic` to disable.

The composer always writes exactly **two files**: `EMBODIMENT.md` and `embodiment.yaml`. Validate and build it like a hand-written package.

## Safety rules

- The build script must remain offline. Do not import or call any device adapter from the builder.
- A `sensor_only: true` package must not declare motion/manipulation in `default_capabilities`. The validator rejects it.
- A context package must declare a non-empty `safety.forbidden_actions`.
- Hardware probing belongs in `probes/passive_probe.py` or `probes/sensor_probe.py`, run separately during onboarding, never during build.
- Do not commit API keys, SSH keys, or per-deployment IPs to `embodiment.yaml` unless they are intentional shareable artifacts.

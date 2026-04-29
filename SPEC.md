# Embodiments — Top-level Spec

This is the entry document for the `embodiments/` module. It is intentionally short. Authoritative details are in the six sub-specs under `specs/`.

```text
specs/EMBODIMENT_PACKAGE_SPEC.md             package on-disk format and embodiment.yaml fields
specs/AGENT_READABLE_CONTEXT_PACKAGE.md      what EMBODIMENT.md must contain (SKILL.md-style)
specs/EMBODIMENT_GRAPH_SPEC.md               task/role-oriented graph schema (v2)
specs/NODE_REGISTRY_SPEC.md                  registry schema (inline in embodiment.yaml > registry)
specs/SAFETY_POLICY_SPEC.md                  install/runtime/LLM safety invariants
specs/COMPOSER_SPEC.md                       composer behavior contract
```

## What an embodiment package is

```text
Skill        = software procedure / tool capability        (SKILL.md tells the agent how)
MCP server   = external tool / context server
Embodiment   = physical entity, sensor, actuator, robot,    (EMBODIMENT.md tells the agent
               or physical collaboration graph               which nodes are real and safe)
```

## Slim layout (2 required files)

```text
<package>/
  EMBODIMENT.md       agent-readable, SKILL.md-style, YAML frontmatter at top
  embodiment.yaml     runtime metadata; `registry` and `graphs` inlined
  evidence/*.json     optional, verified probe results
  probes/*.py         optional, passive only
  adapters/*          optional adapter contract / templates
```

No separate `registry/`, `graphs/`, `profiles/`, or `README.md` directories. The registry is one block inside `embodiment.yaml`. The primary graph is another block inside `embodiment.yaml`. Profile and README content lives in `EMBODIMENT.md`.

## Package kinds

```text
robot                   single robot model
sensor                  single sensor type
actuator                gripper, base, arm, ...
hardware_rig            fixed multi-device setup
embodiment_graph        a single collaboration graph
collaboration           a higher-level coordination pattern
embodiment_context      recommended top-level kind (see AGENT_READABLE_CONTEXT_PACKAGE.md)
```

For most lab deployments, you publish *one* `embodiment_context` package. The composer at `composer/compose_context.py` does this from a topology snapshot, with LLM-first default.

## Three things to remember

1. **Build is offline.** The validator/zipper never contacts hardware.
2. **Sensor-only is the default.** A `sensor_only: true` package cannot declare motion as safe.
3. **The agent reads `EMBODIMENT.md`.** Treat it the way a skill treats `SKILL.md` — frontmatter + concrete sections + worked examples.

## Build artifact

```text
embodiments/dist/<package_id>-<version>.embodiment.zip
embodiments/dist/<package_id>-<version>.manifest.json
```

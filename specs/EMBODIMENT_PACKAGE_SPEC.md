# Embodiment Package Spec v0.3

An embodiment package is an installable, shareable bundle that describes a physical entity or a physical collaboration pattern (a robot, sensor, actuator, hardware rig, or graph of those).

```text
skills/       software procedures
tools/        callable tools
mcp/          external tool/context servers
embodiments/  physical entities and physical collaboration graphs
```

This document defines what is on disk and how it is identified. Other specs cover content:

- `AGENT_READABLE_CONTEXT_PACKAGE.md` — what `EMBODIMENT.md` must contain.
- `EMBODIMENT_GRAPH_SPEC.md` — task-oriented graph schema.
- `NODE_REGISTRY_SPEC.md` — `registry` schema (inlined inside `embodiment.yaml`).
- `SAFETY_POLICY_SPEC.md` — runtime/install safety invariants.
- `COMPOSER_SPEC.md` — composer behavior contract.

## Package kinds

```text
robot
sensor
actuator
hardware_rig
embodiment_graph
collaboration
embodiment_context        # recommended top-level kind
```

A real deployment should usually publish **one** `embodiment_context` package, not many graph packages.

## Slim layout (recommended)

```text
<package_id>/
  EMBODIMENT.md           required for agent runtimes; SKILL.md-style
  embodiment.yaml         required; `registry` and `graphs` inlined
  evidence/*.json         optional, verified probe results
  probes/*.py             optional, passive only
  adapters/*              optional adapter contract or templates
```

Backward-compatible (also accepted by the validator):

```text
<package_id>/
  embodiment.yaml
  README.md
  registry/nodes.yaml
  graphs/*.yaml
  profiles/*.md
```

Either layout validates. New packages should prefer the slim layout.

## `embodiment.yaml`

Required fields (both schemas):

```yaml
schema: embodiment_package/v1   # or embodiment_package/v2 for context packages
package_id: example
name: Example
version: 0.1.0
kind: robot                      # see kinds above
license: Apache-2.0
summary: One short sentence.
```

Slim form (recommended) — registry and graphs inlined:

```yaml
schema: embodiment_package/v2
package_id: my_lab_context
name: My Lab Context
version: 0.3.0
kind: embodiment_context
license: Apache-2.0
summary: ...
primary_agent_doc: EMBODIMENT.md

registry:
  schema: embodiment_node_registry/v1
  nodes:
    - id: my_camera
      node_type: sensor
      role: external_view
      safe_capabilities: [observe, perceive]
      limits: {sensor_only: true}

graphs:
  - schema: embodiment_graph/v2
    graph_id: sensor_only_observation
    intent: ...
    roles: [...]
    nodes: [...]
    constraints: {forbidden_actions: [...]}
    readiness_checks: [...]
    failure_modes: [...]
    recovery: {...}
    outputs: [...]

safety:
  default_policy: sensor_only
  install_must_not_actuate: true
  forbidden_actions: [...]        # required, non-empty for embodiment_context

integration:
  exposes_agent_context: true
  compatible_with: [auwomo_physclaw, openclaw_like_runtime]
```

### Backward-compatible `registry` and `graphs`

`registry` may be either:

- inlined dict (recommended): `registry: {schema: ..., nodes: [...]}`
- or a path string: `registry: registry/nodes.yaml`

`graphs` may be either:

- inlined list of graph dicts (recommended): `graphs: [{graph_id: ..., ...}]`
- or a list of paths: `graphs: [graphs/sensor_only_observation.yaml]`

The builder resolves whichever form the package uses.

## Build artifact

```text
embodiments/dist/<package_id>-<version>.embodiment.zip
embodiments/dist/<package_id>-<version>.manifest.json
```

The manifest contains normalized metadata, file SHA-256 hashes, and a safety summary. The zip embeds a copy of the manifest at `<package_id>/MANIFEST.json` for offline distribution.

## Submission checklist

- `embodiment.yaml` valid against the spec.
- `EMBODIMENT.md` with YAML frontmatter and the 8 required sections (see `AGENT_READABLE_CONTEXT_PACKAGE.md`).
- A registry inlined in `embodiment.yaml > registry` (or under `registry/nodes.yaml` for back-compat).
- For `embodiment_context`: a primary graph inlined in `embodiment.yaml > graphs[0]`.
- Probe scripts if the package introduces hardware; passive only.
- No credentials, secrets, or per-deployment keys.
- Build/install must not actuate hardware.

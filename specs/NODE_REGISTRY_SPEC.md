# Node Registry Spec v0.2

The registry is the normalized list of physical/topology nodes a package introduces or references.

In the slim layout, the registry is a block **inlined inside `embodiment.yaml`**:

```yaml
registry:
  schema: embodiment_node_registry/v1
  nodes: [...]
```

For backward compatibility, packages may also keep the registry in a separate file at `registry/nodes.yaml`. The builder resolves either form.

Topology runtimes load the registry to know what nodes the package wants to register. The agent reads the same data via `EMBODIMENT.md > ## Available nodes`, which mirrors the registry verbatim.

## Schema

```yaml
schema: embodiment_node_registry/v1
generated_at: 1714377600.0          # optional epoch timestamp
nodes:
  - id: <node_id>
    name: Human-readable Name
    node_type: physical_robot | sensor | actuator | perception_model | ...
    role: robot_local_view | external_view | audio_input | scene_describer | support_node
    safe_capabilities: [observe, perceive, listen, ...]
    sensors: [rgb_camera, depth_camera, ...]      # optional
    limits:
      sensor_only: true
      movement_allowed: false
      manipulation_allowed: false
    standalone_only: false
    endpoint_configured: false                    # whether the package can talk to it directly
    agent_ref: null                               # optional planner-side handle
    parent_robot: <node_id>                       # optional, for sensors owned by a robot
    metadata: {}                                  # optional, arbitrary
```

## Required fields per node

- `id` — unique within the registry; should match topology snapshot when possible.
- `node_type`.
- `safe_capabilities` — never copy raw `capabilities` blindly; intersect with the safe list.
- `limits.sensor_only` if applicable.

## Safety rule

A node entry must not declare `safe_capabilities` that include any forbidden action under the package's safety policy. The builder rejects such packages.

If `limits.sensor_only: true` then `safe_capabilities` must be a subset of:

```text
observe, inspect, listen, perceive, wait, standby, health_check
```

## Standalone-only nodes

If `standalone_only: true`, the composer must not include this node in any auto-generated collaboration graph. The package may still describe the node so the agent knows about it.

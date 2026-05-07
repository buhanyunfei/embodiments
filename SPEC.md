# Embodiments — Top-level Spec

This is the entry document for the `embodiments/` module. Authoritative details are in the sub-specs under `specs/`.

```text
specs/EMBODIMENT_PACKAGE_SPEC.md             package on-disk format and embodiment.yaml fields
specs/AGENT_READABLE_CONTEXT_PACKAGE.md      what EMBODIMENT.md must contain (SKILL.md-style)
specs/EMBODIMENT_GRAPH_SPEC.md               two-layer graph schema (v3: cooperation + execution)
specs/NODE_REGISTRY_SPEC.md                  registry schema with agent nodes and tool interfaces (v2)
specs/SAFETY_POLICY_SPEC.md                  install/runtime/LLM safety invariants
specs/COOPERATION_NETWORK_SPEC.md            cooperation network: human approval, dormant edges, rollback
specs/INTEGRATION_SPEC.md                    Context + Tools integration with Codex/OpenClaw
specs/COMPOSER_SPEC.md                       composer behavior contract
```

## What an embodiment package is

Embodiments is a **peer-level system component** alongside MCP servers, Skills, and Tools:

```text
Agent System (Codex / OpenClaw / custom)
├── MCP Servers       — external data and API access
├── Skills            — reusable task capabilities (SKILL.md)
├── Tools             — single-call function interfaces
└── Embodiments       — physical world: device control + multi-node collaboration (EMBODIMENT.md)
```

Each layer is independently discoverable, activatable, and hot-swappable.

## Two-Layer Graph Architecture (v3)

```text
┌────────────────────────────────────────────────────────────┐
│ Cooperation Network (upper layer)                          │
│   Controls WHICH nodes can collaborate                     │
│   Human approval → approved / denied / pending             │
│   Rollback → reset to policy file defaults                 │
├────────────────────────────────────────────────────────────┤
│ Execution Network (lower layer)                            │
│   Controls HOW approved nodes collaborate                  │
│   Edges: ordering (serial/parallel/conditional)            │
│          protocol_hint (http/ros/grpc/local)               │
│          dormant (true if cooperation revoked)             │
└────────────────────────────────────────────────────────────┘
```

## Slim layout (2 required files)

```text
<package>/
  EMBODIMENT.md       agent-readable, SKILL.md-style, with tool interfaces + workflows
  embodiment.yaml     runtime metadata; registry, graphs, cooperation_network inlined
  evidence/*.json     optional, verified probe results
  probes/*.py         optional, passive only
  adapters/*          optional adapter contract / templates
```

## Node Types (v3)

```text
robot_node          physical robot (Unitree G1, etc.)
sensor_node         standalone sensor (camera, microphone)
agent_node          LLM agent (llm_agent) or human operator (human_operator)
```

## Package kinds

```text
robot                   single robot model
sensor                  single sensor type
actuator                gripper, base, arm
hardware_rig            fixed multi-device setup
embodiment_context      recommended top-level kind (multi-node + graphs + cooperation)
```

For most deployments, publish *one* `embodiment_context` package. The composer at `composer/compose_context.py` generates this from a topology snapshot (deterministic-first).

## Four things to remember

1. **Build is offline.** The validator/zipper never contacts hardware.
2. **Sensor-only is the default.** A `sensor_only: true` package cannot declare motion as safe.
3. **Cooperation defaults to approved.** Human can revoke at runtime; rollback resets atomically.
4. **The agent reads `EMBODIMENT.md`.** It provides planning context AND tool interfaces for execution.

## Build artifact

```text
embodiments/dist/<package_id>-<version>.embodiment.zip
embodiments/dist/<package_id>-<version>.manifest.json
```

# Integration Spec v0.1

Embodiments is a **peer-level system component** alongside MCP servers, Skills, and Tools — not subordinate to any of them. Agent systems mount embodiment packages natively, the same way they mount MCP servers or register skills.

```
Agent System (Codex / OpenClaw / custom)
├── MCP Servers       — external data and API access
├── Skills            — reusable task capabilities
├── Tools             — single-call function interfaces
└── Embodiments       — physical world: device control + multi-node collaboration
```

Each layer is independently discoverable, activatable, and hot-swappable.

## Embodiment Loader

Agent systems implement an **embodiment loader** that handles package lifecycle:

```
┌─────────────────────────────────────────────────────────────────┐
│ Agent System                                                     │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ Embodiment Loader                                         │   │
│  │                                                          │   │
│  │  discover() → list available .embodiment.zip packages    │   │
│  │  activate(package_id) → inject context + register tools  │   │
│  │  deactivate(package_id) → remove context + unregister    │   │
│  │  swap(old_id, new_id) → atomic switch                    │   │
│  │  hot_plug(path) → load new package without restart       │   │
│  └──────────────────────────────────────────────────────────┘   │
│         │                          │                            │
│         ▼                          ▼                            │
│  ┌──────────────┐     ┌────────────────────────────────────┐   │
│  │ Agent Context │     │ Tool Registry                      │   │
│  │ (planning)    │     │ (node operations as callable tools)│   │
│  └──────┬───────┘     └──────────┬─────────────────────────┘   │
│         │                        │                             │
│         ▼                        ▼                             │
│  EMBODIMENT.md            tool_interface.operations             │
└─────────────────────────────────────────────────────────────────┘
                        │
                        ▼
         ┌──────────────────────────────────┐
         │ Embodiment Runtime                │
         │ - Cooperation network enforcer    │
         │ - Safety profile gate             │
         │ - Execution dispatcher            │
         │ - Graph selector (intent match)   │
         └──────────────────────────────────┘
```

### Loader Lifecycle

| Operation | When | Effect |
|-----------|------|--------|
| `discover()` | Agent startup | Scan configured paths for `.embodiment.zip` or package dirs |
| `activate(id)` | Task requires physical interaction | Inject EMBODIMENT.md to context, register node tools, init cooperation state |
| `deactivate(id)` | Scene change or shutdown | Remove context, unregister tools, clear cooperation overrides |
| `swap(old, new)` | Different hardware config needed | Atomic: deactivate old → activate new (no gap) |
| `hot_plug(path)` | New hardware onboarded mid-session | Load package, merge into active context without restart |

### Configuration

Agent systems declare available embodiments in their config (analogous to MCP server config):

```yaml
# agent_config.yaml (Codex-style)
embodiments:
  packages:
    - path: ./embodiments/dist/g1_usb_dual_view-0.3.0.embodiment.zip
      auto_activate: true
    - path: ./embodiments/dist/unitree_g1_sensor_only-0.2.0.embodiment.zip
      auto_activate: false
  loader:
    scan_dir: ./embodiments/dist/
    hot_plug: true
    default_cooperation_policy: ./embodiments/policies/default_cooperation_policy.yaml
```

## Graph Selection (Intent Matching)

When a package contains multiple graphs (same nodes, different scenarios), the agent selects the appropriate graph via intent matching:

Each graph declares:
```yaml
graph_id: cooperative_dual_view_observation
intent: "Describe the workspace using both ego and third-person views"
trigger_keywords: [describe, observe, see, look, view, scene, workspace]
safety_level: sensor_only
```

The selection algorithm:
1. Agent receives user task
2. Agent reads all available graph intents + trigger_keywords from EMBODIMENT.md
3. Agent matches task to the best graph by semantic similarity to `intent` + keyword overlap with `trigger_keywords`
4. If ambiguous, agent presents options or asks user
5. Selected graph determines which edges are active and which workflows apply

This is analogous to how skills use "When to use" sections for activation matching.

## Context Integration

EMBODIMENT.md is injected into the agent's system/grounding prompt. The agent reads it to understand:

1. **What hardware is available** — node list with capabilities and limits
2. **What is safe to do** — active safety profile and forbidden actions
3. **How to plan workflows** — execution workflows with step-by-step ordering
4. **What tools to call** — tool interface table with operations, inputs, outputs
5. **Who must approve** — cooperation boundaries and human-in-loop requirements

### What the agent extracts from EMBODIMENT.md:

| Section | Agent Decision |
|---------|---------------|
| When to use / not to use | Whether this embodiment applies to the current task |
| Active safety profile | Which action classes are available |
| Tool interfaces | Which tool calls to generate |
| Execution workflows | Concrete step sequences to follow |
| Cooperation boundaries | Which paths are active vs dormant |
| Forbidden actions | Hard refusal triggers |
| Failure modes | How to attribute and recover from errors |

## Tool Integration

Each node in the registry MAY expose a `tool_interface` with callable `operations`. The runtime converts these into tool-call definitions compatible with the agent system.

### Tool Generation Rules

1. **Only expose safe operations as immediately callable tools**
   - `safety_class: safe` → tool is callable without gates
   - `safety_class: confirmation` → tool includes a pre-execution confirmation step
   - `safety_class: supervisor` → tool requires confirmation + supervisor signoff
   - `safety_class: forbidden` → tool is NOT registered (invisible to agent)

2. **Dormant cooperation edges hide associated tools**
   - If node A's cooperation with the planner is dormant, A's tools are not registered
   - Re-approval immediately re-registers the tools

3. **Tool naming convention**
   ```
   {node_id}.{operation_id}
   ```
   Examples: `g1_realsense_color_sensor.capture_frame`, `human_operator.request_approval`

### Tool Definition Format (OpenAI-compatible)

The runtime generates tool definitions from `tool_interface.operations`:

```json
{
  "type": "function",
  "function": {
    "name": "g1_realsense_color_sensor.capture_frame",
    "description": "Capture a single RGB frame from the G1 RealSense color sensor",
    "parameters": {
      "type": "object",
      "properties": {
        "resolution": {"type": "string", "enum": ["720p", "1080p"], "default": "1080p"},
        "format": {"type": "string", "enum": ["jpg", "png"], "default": "jpg"}
      }
    }
  }
}
```

### Confirmation-Gated Tools

For `safety_class: confirmation` operations, the runtime wraps the tool call:

```json
{
  "type": "function",
  "function": {
    "name": "g1_real_sensor_only.walk_forward",
    "description": "[REQUIRES CONFIRMATION] Command G1 to walk forward. Will prompt human operator for approval before execution.",
    "parameters": {
      "type": "object",
      "properties": {
        "distance_m": {"type": "number"},
        "speed": {"type": "string", "enum": ["slow", "normal"]}
      },
      "required": ["distance_m"]
    }
  }
}
```

The runtime intercepts the tool call, routes an `approval_request` to the `human_operator` node, and only dispatches if approved.

## Cooperation Enforcement at Runtime

The runtime enforces cooperation boundaries before tool dispatch:

```
Agent calls tool → Runtime checks:
  1. Is the target node registered? (fail: node_missing)
  2. Is the cooperation between planner and target node approved? (fail: cooperation_denied)
  3. Is the operation's safety_class allowed under active profile? (fail: forbidden_action_requested)
  4. If confirmation required: route approval_request to human_operator (fail: approval_timeout)
  5. Dispatch to node endpoint
```

## Package `integration` Field

Every v3 package declares its integration capabilities:

```yaml
integration:
  capabilities:
    - context_v3        # EMBODIMENT.md with v3 sections (tool interfaces, workflows, cooperation)
    - tools_v1          # tool_interface operations exposed as callable tools
    - cooperation_v1    # cooperation policy enforcement
  compatible_runtimes:
    - codex>=0.4
    - openclaw>=1.0
    - auwomo_physclaw>=0.4
  context_injection:
    target: system_prompt     # or "grounding_context" or "tool_preamble"
    max_tokens: null          # no limit; runtime may truncate
  tool_registration:
    format: openai_function   # or "anthropic_tool" or "custom"
    auto_register: true       # runtime auto-registers tools on package load
    respect_dormant: true     # dormant cooperation hides tools
```

## Codex Integration Pattern

For Codex-like agent systems:

1. **Package mount**: Load embodiment package at session start
2. **Context injection**: Inject `EMBODIMENT.md` into system prompt
3. **Tool registration**: Convert all `tool_interface.operations` (non-forbidden, non-dormant) to Codex tool definitions
4. **Pre-execution hook**: Before dispatching any tool call, check cooperation state and safety profile
5. **Cooperation commands**: Expose `cooperation.approve/revoke/rollback/list` as meta-tools for human operators
6. **Episode trace**: Log all tool calls, approvals, and failures as structured episode trace

## OpenClaw Integration Pattern

For OpenClaw-like task primitive systems:

1. **Task mapping**: Each `execution_workflow` in EMBODIMENT.md maps to an OpenClaw task primitive
2. **Node binding**: Registry nodes map to OpenClaw actors
3. **Safety overlay**: Cooperation + safety profile maps to OpenClaw permission gates
4. **Rollback**: Cooperation rollback maps to OpenClaw's policy reset primitive

## Version Negotiation

When a runtime loads a package, it checks `integration.capabilities`:

```python
required = {"context_v3", "tools_v1"}
package_caps = set(package["integration"]["capabilities"])
if not required.issubset(package_caps):
    raise IncompatiblePackageError(missing=required - package_caps)
```

Older runtimes that only support `context_v2` can still load v3 packages by reading only `EMBODIMENT.md` (which is backward-compatible in structure), but they won't get tool registration or cooperation enforcement.

## Package Portability (Hardware Bindings)

Embodiment packages are **hardware-portable**: they declare WHAT hardware they need, not WHERE that hardware is. This allows packages to be shared, reused, and remounted on any deployment that has compatible devices — exactly like Skills.

### The Problem Without Portability

Without portability, every package embeds deployment-specific connection details:

```yaml
# NOT portable — IP hardcoded in the package
tool_interface:
  endpoint: "http://192.168.1.100:8080"   # only works in one lab
```

### Hardware Requirements Declaration

Portable packages declare hardware requirements as roles (not instances):

```yaml
# embodiment.yaml — portable, no IPs
hardware_requirements:
  - role: robot_local_view
    description: "Ego-view robot with RealSense color camera and HTTP sensor API"
    device_type: robot_node
    sensors_required:
      - realsense_color_camera
    min_safe_capabilities:
      - observe
      - perceive
    connection:
      protocol: http
      default_port: 8080
      required_paths:
        - GET /health
        - POST /sensors/capture
    hint: "Tested with Unitree G1. Any robot with RealSense RGB + HTTP API works."

  - role: external_view
    description: "Third-person view camera with HTTP capture API"
    device_type: sensor_node
    sensor_type: [usb_camera, ip_camera]
    min_safe_capabilities:
      - observe
    connection:
      protocol: http
      default_port: 8081
      required_paths:
        - GET /health
        - POST /sensors/capture
```

### Parameterized Endpoints

Tool interfaces use `@role:xxx` placeholders instead of hardcoded URLs:

```yaml
tool_interface:
  protocol: http
  endpoint: "@role:robot_local_view"   # resolved at mount time
  operations:
    - operation_id: capture_frame
      path: /sensors/capture
```

### Bindings at Mount Time

The deployer provides a **bindings file** (local, never committed to the package repo):

```yaml
# my_lab_bindings.yaml  (deployment-specific, .gitignored)
bindings:
  robot_local_view: http://192.168.1.100:8080
  external_view:    http://192.168.1.101:8081
```

Or inline in the agent system config (`embodiments.yaml`):

```yaml
bindings:
  g1_usb_dual_view:
    robot_local_view: http://192.168.1.100:8080
    external_view:    http://192.168.1.101:8081
```

### Loader API

```python
from embodiments.runtime.loader import EmbodimentLoader

loader = EmbodimentLoader(config_path="./embodiments.yaml")
loader.discover()

# Check what hardware a package needs before binding
reqs = loader.hardware_requirements("g1_usb_dual_view")
for req in reqs:
    print(req["role"], "—", req["description"])
    # robot_local_view — Ego-view robot with RealSense...
    # external_view    — Third-person view camera...

# Mount with inline bindings
loader.activate("g1_usb_dual_view", bindings={
    "robot_local_view": "http://192.168.1.100:8080",
    "external_view":    "http://192.168.1.101:8081",
})

# Or mount from a bindings file
loader.activate("g1_usb_dual_view", bindings_path="./my_lab_bindings.yaml")

# All @role:xxx placeholders are now resolved → tools have real endpoints
tools = loader.get_tools()
# tools[0]["metadata"]["endpoint"] == "http://192.168.1.100:8080"
```

If required roles are missing from bindings, `activate()` raises `ValueError` with a descriptive message before activating.

### What to Share vs. What to Keep Local

| File | Share? | Contains |
|------|--------|---------|
| `*.embodiment.zip` | Yes — publish openly | Hardware requirements, graphs, tool schemas, safety policies |
| `embodiments.yaml` (bindings section) | No — keep local | Actual IPs and ports for your deployment |
| `my_lab_bindings.yaml` | No — keep local | Same |

This mirrors how Docker images are portable but `docker-compose.yml` with local paths/secrets stays local.

### Capability Matching (Future)

Future versions may extend `check_requirements()` to probe the bound endpoint and verify that it actually satisfies the declared `required_paths` and `sensors_required` — providing a pre-flight check before activating.


To support Context + Tools, EMBODIMENT.md must include these sections:

1. `## When to use` — task applicability
2. `## When not to use` — explicit refusals
3. `## Active safety profile` — current profile with capability class table
4. `## Available nodes` — all nodes including agent nodes
5. `## Tool interfaces` — per-node operation tables (operation, protocol, endpoint, latency, safety_class)
6. `## Cooperation boundaries` — active/dormant/pending pairs
7. `## Execution workflows` — numbered step sequences with ordering annotations
8. `## How to plan` — worked examples showing tool call sequences
9. `## Forbidden actions` — verbatim list
10. `## Failure modes` — code/when/attribution table
11. `## Recovery` — auto/confirmation/not-recoverable
12. `## Runtime integration` — how to mount this package

# Embodiments

**Shareable, portable packages that let LLM agent systems safely interact with physical robots and sensors.**

> [中文文档 / Chinese Documentation](./README_CN.md)

---

## Overview

Embodiments is an open standard for packaging physical hardware interfaces — robots, sensors, actuators — so that any LLM agent system can discover, mount, and use them like Skills or MCP servers.

```
Agent System (Codex / OpenClaw / LangGraph / custom)
├── MCP Servers    — external data & API access
├── Skills         — reusable task procedures (SKILL.md)
├── Tools          — single-call function interfaces
└── Embodiments    — physical world: device interfaces + collaboration (EMBODIMENT.md)
```

One package, two files. Download it, bind your hardware IPs, and your agent can see and control the physical world.

## Key Features

- **Plug-and-play** — `discover() → activate() → get_tools()` in 3 lines of Python
- **Hardware-portable** — packages declare WHAT hardware they need, not WHERE it is. Bind endpoints at mount time.
- **Safety-first** — sensor-only by default, forbidden actions enforced, human approval gates for dangerous operations
- **Shareable** — publish your robot's embodiment package; anyone with the same hardware can use it
- **Hot-swappable** — add/remove/swap packages at runtime without restart
- **Agent-readable** — `EMBODIMENT.md` tells the agent everything: available tools, safety rules, workflows, failure modes

## Quick Start

### Install

```bash
pip install pyyaml  # only dependency
```

### Use in your agent system

```python
from embodiments.runtime.loader import EmbodimentLoader

loader = EmbodimentLoader(config_path="./embodiments.yaml")
loader.discover()
loader.activate("g1_usb_dual_view", bindings={
    "robot_local_view": "http://192.168.1.100:8080",
    "external_view":    "http://192.168.1.101:8081",
})

# Inject into agent
context = loader.get_context()    # EMBODIMENT.md → system prompt
tools = loader.get_tools()        # OpenAI-format tool definitions

# Agent calls tools as needed
result = loader.dispatch_tool("g1_realsense_color_sensor.capture_frame", {
    "resolution": "1080p"
})
```

### Validate & build packages

```bash
# Validate
python builder/build_embodiment.py validate packages/g1_usb_dual_view

# Build distributable zip
python builder/build_embodiment.py build packages/g1_usb_dual_view --out dist

# Generate from topology
python composer/compose_context.py generate \
  --topology hub/topology_snapshot.json \
  --package-id my_lab_context \
  --out generated
```

## Package Format

Two required files:

```
<package>/
  EMBODIMENT.md       # agent reads this (like SKILL.md)
  embodiment.yaml     # runtime reads this (registry + tools + safety)
```

### Package kinds

| Kind | Description | Example |
|------|-------------|---------|
| `robot` | Single robot device | `unitree_g1_sensor_only` |
| `sensor` | Single sensor device | `usb_1080p_camera` |
| `embodiment_context` | Multi-device collaboration scene | `g1_usb_dual_view` |

Device packages are shareable atoms. Context packages compose them into collaboration scenes.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Runtime Loader (runtime/loader.py)                           │
│                                                             │
│  discover() → activate(bindings) → get_context/get_tools    │
│  dispatch_tool() → safety gate → cooperation check → go     │
│  cooperation: approve / revoke / rollback                    │
│  hot_plug() → add packages without restart                  │
└─────────────────────────────────────────────────────────────┘
         │                         │
         ▼                         ▼
  ┌──────────────┐      ┌─────────────────────────┐
  │ EMBODIMENT.md │      │ embodiment.yaml          │
  │ (agent context)│      │ (registry + tools +     │
  │               │      │  cooperation + safety)   │
  └──────────────┘      └─────────────────────────┘
```

### Cooperation Network

Human-gated permission layer. Controls which nodes can collaborate:

- **approve** — node pair can exchange data (default)
- **revoke** — edge becomes dormant, tools hidden from agent
- **rollback** — reset all runtime overrides to policy file defaults

### Safety Model

| Class | Behavior |
|-------|----------|
| `safe` | Agent calls freely |
| `confirmation` | Requires human approval before dispatch |
| `supervisor` | Requires supervisor + human approval |
| `forbidden` | Tool not registered, invisible to agent |

## Project Layout

```
runtime/                    Runtime loader (agent systems import this)
  loader.py                   EmbodimentLoader + EmbodimentPackage
builder/                    Offline validator + zip packager
  build_embodiment.py         validate / build / build-all
composer/                   Deterministic-first package generator
  compose_context.py          topology → context package
packages/                   Reference packages
  g1_usb_dual_view/           v3 multi-device context (reference)
  unitree_g1_sensor_only/     v2 single-robot device package
  usb_1080p_camera/           v2 single-sensor device package
policies/                   Safety + cooperation policy files
specs/                      8 authoritative specification files
skills/onboard-embodiment/  Plug-and-play device onboarding skill
templates/                  Configuration templates
```

## Safety Guarantees

1. **Build is offline** — validator never contacts hardware
2. **Install does not move** — no motor commands during package install
3. **Sensor-only default** — motion/manipulation/audio forbidden until explicitly promoted
4. **No mock substitution** — real devices must exist or fail fast
5. **Cooperation defaults approved** — revocation creates dormant edges, not deletions

## Changelog

### v0.4.0 (2025-05)

**Runtime Loader** — new pluggable adapter for agent systems
- `EmbodimentLoader` class: discover → activate → get_context/get_tools → dispatch_tool
- Hardware portability: `@role:xxx` placeholders + bindings at mount time
- Cooperation management: approve/revoke/rollback with dormant edge semantics
- Safety-gated dispatch: forbidden ops hidden, confirmation ops wrapped
- Hot-plug: add packages at runtime without restart

**Simplified Architecture** — removed execution engine
- Removed graph execution engine (agent systems like LangGraph/OpenClaw handle orchestration)
- Replaced 265-line rigid `graphs:` YAML schema with 10-line `workflows:` index
- Collaboration workflows described in EMBODIMENT.md as readable markdown steps
- Loader provides context + tools + safety gates only — no workflow orchestration

**Package Portability** — shareable like npm packages
- `hardware_requirements` block declares needed hardware roles
- `@role:xxx` parameterized endpoints (no IPs in packages)
- Bindings file pattern (local, never committed)
- `check_requirements()` validates before activation

**Device Packages Upgraded**
- `unitree_g1_sensor_only` and `usb_1080p_camera` now have `tool_interface`
- Both packages expose tools via the loader (health_check, capture_frame, get_state, record_audio)
- Added `hardware_requirements` for portability
- Registry upgraded to v2 with `participant_type`

**Composer Simplified**
- Outputs minimal `workflows:` index instead of verbose graph definitions
- Always includes standard forbidden actions for restrictive profiles
- Full workflow steps live in EMBODIMENT.md, not YAML

**Builder Updated**
- Accepts `workflows:` as alternative to `graphs:` for context packages
- New `_validate_workflows()` checks workflow entries reference valid nodes
- Backward compatible: old `graphs:` packages still validate

### v0.3.0 (2025-04)

- Two-layer graph architecture (cooperation + execution networks)
- Agent nodes as first-class participants (llm_agent, human_operator)
- Tool interfaces per node with safety_class
- Multiple graphs per package (intent-matched via trigger_keywords)
- Cooperation network spec with human-gated approval
- Integration spec for Codex/OpenClaw
- Deterministic-first composer (LLM optional, prose-only)

### v0.2.0 (2025-03)

- Slim 2-file package format (EMBODIMENT.md + embodiment.yaml)
- Builder: offline validate + zip packager
- Composer: topology → context package generation
- Onboarding skill: probe → compose → validate → build
- Reference packages: unitree_g1_sensor_only, usb_1080p_camera, g1_usb_dual_view

### v0.1.0 (2025-02)

- Initial spec: package format, node registry, safety policy
- EMBODIMENT.md as SKILL.md-style agent entry document

## License

Apache-2.0

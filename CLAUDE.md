# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

Embodiments is an **open standard for packaging physical hardware interfaces** (robots, sensors, actuators) so that LLM agent systems can discover, mount, and use them — the same way they use Skills, Tools, or MCP servers.

```
Agent System (Codex / OpenClaw / LangGraph / custom)
├── MCP Servers    — external data/API access
├── Skills         — reusable task procedures (SKILL.md)
├── Tools          — single-call function interfaces
└── Embodiments    — physical world: device interfaces + collaboration (EMBODIMENT.md)
```

**The core deliverable**: a shareable, portable package (2 files) that anyone can download, bind their hardware IPs, and use immediately.

**Only dependency**: `pyyaml`

## Main Thread / Mission

The project solves one problem: **LLM agents don't know how to talk to physical hardware safely.**

We provide:
1. A **package format** that describes devices (what exists, what's safe, what's forbidden)
2. A **runtime loader** that agent systems import to get context + callable tools
3. A **safety layer** that enforces rules before any tool dispatch

We do NOT provide:
- An execution engine (LangGraph/OpenClaw do this)
- Workflow orchestration (the agent system decides order)
- A framework to replace existing agent systems

## Key Commands

```bash
# Validate a package (offline, never contacts hardware)
python builder/build_embodiment.py validate packages/g1_usb_dual_view

# Build → dist/<id>-<version>.embodiment.zip
python builder/build_embodiment.py build packages/g1_usb_dual_view --out dist

# Generate context package from topology (deterministic-first)
python composer/compose_context.py generate \
  --topology hub/topology_snapshot.json \
  --package-id my_lab_context \
  --out generated

# Onboard a new device
python skills/onboard-embodiment/onboard.py \
  --device-id new_robot_01 --device-kind robot --ip 192.168.5.20 \
  --package-id current_lab_sensor_context
```

## Architecture (4 layers)

```
specs/              ← authoritative rules (read before changing code)
builder/            ← offline validator + zip packager
composer/           ← topology → package generator (deterministic-first)
runtime/            ← EmbodimentLoader (what agent systems actually import)
```

### Runtime Loader — the main interface

```python
from embodiments.runtime.loader import EmbodimentLoader

loader = EmbodimentLoader(config_path="./embodiments.yaml")
loader.discover()
loader.activate("g1_usb_dual_view", bindings={
    "robot_local_view": "http://192.168.1.100:8080",
    "external_view":    "http://192.168.1.101:8081",
})

context = loader.get_context()    # EMBODIMENT.md → inject into system prompt
tools = loader.get_tools()        # OpenAI-format tool definitions
result = loader.dispatch_tool("g1_realsense_color_sensor.capture_frame", {})

# Cooperation management
loader.cooperation_revoke("pkg", "node_a", "node_b", "operator_id")
loader.cooperation_rollback("pkg")

# Hot-plug
loader.hot_plug("./dist/new-0.1.0.embodiment.zip", bindings={...})
```

### Package Format (2 files)

```
<package>/
  EMBODIMENT.md       ← agent reads this (like SKILL.md)
  embodiment.yaml     ← runtime reads this (registry + tools + safety + workflows)
```

### Package Kinds

| Kind | What it is | Shareable? |
|------|-----------|-----------|
| `robot` | Single robot device interface | Yes — "I have a G1, here's its tools" |
| `sensor` | Single sensor device interface | Yes — "Here's my USB camera's API" |
| `embodiment_context` | Multi-device collaboration scene | Yes — "Here's how G1 + camera work together" |

## Core Concepts

- **Node**: Physical device or software agent. Types: `robot_node`, `sensor_node`, `agent_node` (subtypes: `llm_agent`, `human_operator`)
- **Tool Interface**: Per-node operations the agent can call (protocol, endpoint, input/output schema, safety_class)
- **Hardware Portability**: Packages use `@role:xxx` placeholders; actual IPs filled in via `bindings` at mount time
- **Cooperation Network**: Human-gated permission layer. Revoke hides tools (dormant). Rollback resets.
- **Workflow**: Described in EMBODIMENT.md as numbered markdown steps. `workflows:` in YAML is just an index for discovery.
- **Safety Class**: `safe` (free), `confirmation` (needs human), `supervisor` (needs supervisor + human), `forbidden` (invisible)

## Safety Invariants (NEVER violate these)

1. **Build is offline** — builder/validator NEVER contacts hardware
2. **Install does not move** — no motor commands during package install
3. **Sensor-only by default** — motion/manipulation/audio forbidden unless explicitly promoted
4. **No mock substitution** — real devices must exist or fail fast
5. **Cooperation defaults approved** — revocation creates dormant edges, not deletions

## What to AVOID

- **DO NOT add an execution engine** — we intentionally removed it. The loader provides context + tools + safety, not orchestration. Agent systems (LangGraph, OpenClaw, etc.) handle workflow execution.
- **DO NOT put IPs or secrets in package files** — packages are meant to be shared. Use `@role:xxx` + bindings.
- **DO NOT generate structure with LLM** — the composer is deterministic-first. LLM is only for optional prose enhancement.
- **DO NOT make the builder contact hardware** — it must remain offline.
- **DO NOT add complex graph YAML schemas** — we deliberately simplified from 265-line graph definitions to 10-line workflow indexes. Collaboration flows belong in EMBODIMENT.md as markdown.
- **DO NOT duplicate what agent systems already do** — we are a peer component, not a replacement for Skills/MCP/Tools.

## What Needs Optimization / TODO

### High Priority

1. **specs/ are stale** — specs still reference the old execution engine and verbose graph schema. Need updating to match current simplified architecture.
2. **generated/ outputs are outdated** — old composer outputs from before the workflows refactor. Should regenerate or delete.
3. **EMBODIMENT.md for device packages** — `unitree_g1_sensor_only` and `usb_1080p_camera` have minimal EMBODIMENT.md files that don't follow the v3 section format. Could be improved.
4. **End-to-end onboarding test** — the `skills/onboard-embodiment/onboard.py` references the old graph format in places. Needs sync with current architecture.

### Medium Priority

5. **Composer still has dead code** — `SCHEMA_GRAPH` constant, some old v2-related helpers that are no longer called.
6. **Anthropic tool format** — currently only generates OpenAI function-call format. Adding Anthropic tool format would expand compatibility.
7. **Capability matching** — `activate()` could optionally probe bound endpoints to verify they satisfy `hardware_requirements.required_paths`.
8. **Templates outdated** — `templates/context_package/` still has old-format templates.

### Low Priority / Future

9. **Package registry** — npm-style index for discovering community packages.
10. **ROS/gRPC adapters** — currently only HTTP dispatch metadata; extending to ROS topics or gRPC services.
11. **Multi-agent cooperation policies** — more granular permission models beyond approve/deny per pair.
12. **CI/testing** — no automated tests exist yet. The validation chain works (`python -c "from runtime import EmbodimentLoader"`) but needs proper test files.

## File Map (what's what)

| File | Lines | Role |
|------|-------|------|
| `runtime/loader.py` | ~440 | **Main interface** — agent systems import this |
| `builder/build_embodiment.py` | ~530 | Offline validator + zip packager |
| `composer/compose_context.py` | ~1070 | Topology → package generator |
| `skills/onboard-embodiment/onboard.py` | ~370 | Device onboarding orchestrator |
| `packages/g1_usb_dual_view/` | | **v3 reference package** — study this first |
| `packages/unitree_g1_sensor_only/` | | v2 single-robot device package |
| `packages/usb_1080p_camera/` | | v2 single-sensor device package |
| `policies/` | | Safety + cooperation policy files |
| `specs/` | | 8 spec files (some stale — see TODO #1) |
| `templates/embodiments.yaml` | | Config template showing bindings pattern |

## Verified Working Chain

This has been tested end-to-end:

```
composer generates package
  → builder validates (all 4 packages pass)
    → loader imports + activates with bindings
      → get_tools() returns OpenAI-format tool definitions
        → dispatch_tool() enforces safety + returns dispatch metadata
          → cooperation revoke hides tools / rollback restores
            → hot_plug adds packages at runtime
```

## Design Decisions (context for why things are this way)

| Decision | Why |
|----------|-----|
| No execution engine | Agent systems already have this (LangGraph, etc). We were duplicating. |
| Workflows in MD, not YAML | Strict graph YAML was hard to share and understand. MD is readable by both humans and agents. |
| `@role:xxx` portability | Packages must be shareable without leaking deployment details. |
| Cooperation defaults approved | Safer to assume collaboration works, then let humans revoke specific pairs. |
| Builder offline | Safety invariant. A build step that touches hardware could cause accidents. |
| Deterministic-first composer | LLM output is unreliable for structural correctness. Generate structure deterministically, LLM only polishes prose. |

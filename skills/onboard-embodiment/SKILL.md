---
name: onboard-embodiment
description: Plug-and-play onboarding of a new robot, sensor, or hardware device into the embodiment ecosystem (v3). Discovers the device passively (no motion), auto-discovers tool interfaces, generates cooperation policy and multi-graph context, validates, builds, and hot-plugs into the runtime loader. Honors `standalone_only`. Use this whenever a new physical node appears or the user says "onboard / plug in / connect / register / add" a device.
---

# Onboard a new embodiment (v3)

This skill is the embodiment-side counterpart of the device-level `robot_node_onboarding` kit. Use it whenever **new physical hardware** has been (or is being) connected to the host running the topology runtime. The skill walks through discovery, tool interface auto-discovery, cooperation policy generation, multi-graph composition, validation, build, and hot-plug — all sensor-only by default.

## When to use

- The user says any of: "onboard a robot", "plug in a camera", "connect a new sensor", "register this device", "add G2 to the lab", "extend the embodiment context", "regenerate after adding hardware".
- A new node appeared in `hub/topology_snapshot.json` and the deployment context package needs to reflect it.
- The user wants a robot/sensor to participate in collaborative graphs alongside already-onboarded devices.
- The user wants to mark a device **standalone** (do not include it in any auto-generated collaborative embodiment).
- The user wants the new device immediately available via the runtime loader (hot-plug).

## When NOT to use

- The user wants to test motion or manipulation (this skill is sensor-only; refer them to a dedicated motion-verification skill that requires explicit confirmation).
- The user wants to teleoperate a robot (this skill produces topology + embodiment artifacts, not control loops).
- The device cannot be reached passively (cable unplugged, IP wrong, host offline). Probe must succeed before composing.
- The user wants to fabricate fake nodes for demos. Do not generate embodiments for nodes that do not exist; mock substitution is forbidden.

## Inputs

The agent collects:

- `device_id` — required. A short slug, e.g. `g2_real_sensor_only`, `usb_camera_2`, `realsense_d435i_left`.
- `device_kind` — one of `robot | sensor | actuator | hardware_rig`. Default to `sensor` if unsure.
- `connection_hints` — optional: IP, HTTP base, or `--usb` for local USB devices.
- `package_id` — the deployment context package to extend. Default `current_lab_sensor_context`.
- `standalone` — boolean. If true, the device is added to the registry but excluded from collaborative graphs.
- `cooperation_policy` — optional path to a cooperation policy file. Default: `policies/default_cooperation_policy.yaml`.
- `schema_version` — `v2` or `v3` (default `v3`).

If the user did not supply enough information, ask one targeted question; do not guess.

## Workflow

Run these steps in order. Stop and report on any failure.

### Step 1 — passive discovery + tool interface auto-discovery

```bash
python -m robot_node_onboarding.cli init --robot-id <device_id> [--ip <ip>] [--http-base <url>] [--usb]
python -m robot_node_onboarding.cli discover --robot-id <device_id>
python -m robot_node_onboarding.cli render-profile --robot-id <device_id>
python -m robot_node_onboarding.cli validate-profile robot_profiles/<device_id>/ROBOT_NODE_PROFILE.md
```

These commands ping, HTTP-probe `/health` `/state` `/sensors`, and enumerate USB. **They never command motion.** If discovery fails, surface the error and stop.

**Tool interface auto-discovery (v3)**: During HTTP probing, the onboarder also discovers callable endpoints and generates a `tool_interface` block for the device:

```bash
python -m robot_node_onboarding.cli discover-tools --robot-id <device_id> [--ip <ip>] [--http-base <url>]
```

This probes known patterns (`GET /health`, `GET /state`, `POST /sensors/capture`, etc.), measures latency, and writes `robot_profiles/<device_id>/tool_interface.json`:

```json
{
  "protocol": "http",
  "endpoint": "http://<ip>:<port>",
  "operations": [
    {
      "operation_id": "capture_frame",
      "method": "POST",
      "path": "/sensors/capture",
      "input_schema": {"type": "object", "properties": {}},
      "output_schema": {"type": "object", "properties": {"frame_path": {"type": "string"}}},
      "latency_estimate_ms": 200,
      "safety_class": "safe"
    }
  ]
}
```

If the device is USB-only (no HTTP), `tool_interface` will use `protocol: local` with operation stubs that the agent system fills in.

### Step 2 — register the profile card with the topology runtime

```bash
curl -X POST http://localhost:8765/topology/robot_profiles/register_card \
  -H "Content-Type: application/json" \
  -d @robot_profiles/<device_id>/profile_card_payload.json
```

Then refresh the topology snapshot:

```bash
curl -X POST http://localhost:8765/topology/snapshot/save -o hub/topology_snapshot.json
```

Verify the new node appears in the snapshot before composing. If it does not, do not proceed; ask the user to inspect the runtime.

### Step 3 — (optional) mark the device standalone

If the user said "this device should not collaborate with others," do **not** modify the topology in place. Use the composer's `--mark-standalone` flag in step 4 instead:

```bash
--mark-standalone <device_id>
```

The flag is repeatable. The composer will keep the node in `registry.nodes` (so the agent knows it exists) but skip it from any collaborative graph and report it under `skipped_standalone_nodes`.

### Step 4 — generate or extend the embodiment context (v3)

The composer is **idempotent** and **deterministic-first**. Re-running with an updated topology reflects the new node automatically.

```bash
python embodiments/composer/compose_context.py generate \
  --topology hub/topology_snapshot.json \
  --package-id <package_id> \
  --mode auto \
  --out embodiments/generated \
  --schema-version v3 \
  --cooperation-policy embodiments/policies/default_cooperation_policy.yaml \
  --include-agent-nodes \
  [--mark-standalone <device_id> ...]
```

Key v3 flags:
- `--schema-version v3` — enables two-layer graph architecture, tool interfaces in output, multi-graph generation
- `--cooperation-policy <path>` — loads the cooperation policy file; computes approved/denied pairs; marks dormant edges
- `--include-agent-nodes` — auto-injects `llm_planner` and `human_operator` agent nodes into the registry and graphs

The output is always two files:

```text
embodiments/generated/<package_id>/
  EMBODIMENT.md          (v3: includes Tool interfaces, Execution workflows, Cooperation boundaries)
  embodiment.yaml        (v3: registry with tool_interface, cooperation_network, multi-graph)
```

**Multi-graph output** (v3): The composer generates multiple graphs per package based on device capabilities:
- `cooperative_*_observation` — sensor collaboration graph (always generated)
- `sensor_health_audit` — health check workflow (always generated)
- `motion_supervised` — motion with human approval (only if device has motion capability)

If `LLM_REJECTED.json` appears next to the package, the LLM violated a safety rule and the deterministic doc was kept. Read the rejection reasons and tell the user.

### Step 5 — validate

```bash
python embodiments/builder/build_embodiment.py validate embodiments/generated/<package_id>
```

Stop if validation fails. Surface every error from the validator. Common errors (v3):

- `kind=embodiment_context requires non-empty safety.forbidden_actions` → policy file is broken.
- `registry node 'X' has safe_capabilities containing forbidden actions: [...]` → the new device profile is too permissive; tighten it.
- `EMBODIMENT.md does not mention forbidden action: 'walk'` → the LLM dropped a forbidden action; rerun with `--mode deterministic` and report.
- `agent_node 'X' missing agent_subtype` → agent node definition incomplete (v3).
- `tool_interface operation missing safety_class` → tool interface auto-discovery incomplete; re-run step 1.
- `cooperation_network references unknown node 'X'` → topology stale; refresh snapshot.
- `graph edge with ordering=conditional missing condition field` → composer bug; report.

### Step 6 — build

```bash
python embodiments/builder/build_embodiment.py build embodiments/generated/<package_id> \
  --out embodiments/dist
```

Output: `<package_id>-<version>.embodiment.zip` and `.manifest.json` under `embodiments/dist/`.

### Step 7 — hot-plug into runtime loader

After a successful build, hot-plug the new package into the running agent system's embodiment loader:

```python
from embodiments.runtime.loader import EmbodimentLoader

loader = EmbodimentLoader(config_path="./embodiments.yaml")
loader.discover()
package_id = loader.hot_plug("embodiments/dist/<package_id>-<version>.embodiment.zip")
```

Or via CLI if the agent system exposes a hot-plug endpoint:

```bash
curl -X POST http://localhost:<agent_port>/embodiments/hot_plug \
  -H "Content-Type: application/json" \
  -d '{"path": "embodiments/dist/<package_id>-<version>.embodiment.zip"}'
```

After hot-plug:
- The package's `EMBODIMENT.md` is injected into the agent's system prompt context.
- The package's `tool_interface` operations are registered as callable tools.
- The cooperation network state is initialized from the policy file.
- All graphs become available for intent-matching selection.

### Step 8 — report

Summarize for the user:

- node ids included in the new graphs (list per graph);
- node ids skipped as standalone;
- tool interfaces discovered (operation count per node);
- cooperation policy applied (source of policy, any overrides);
- graphs generated (list graph IDs and trigger keywords);
- LLM mode resolved (`accepted | rejected | skipped`);
- hot-plug status (`success | skipped | failed`);
- artifact paths.

## Forbidden actions during onboarding

This skill must not, under any circumstance:

- send any motion command to any device (`navigate`, `walk`, `move`, `turn`, `grasp`, `pick`, `place`, `carry`, `hand_over`, `open_door`, whole-body / arm / hand motion);
- produce audio output;
- substitute a missing real device with a mock node;
- skip the topology snapshot refresh in step 2;
- write `api_key`, SSH keys, or per-deployment credentials into `embodiment.yaml` or `EMBODIMENT.md`;
- approve cooperation pairs that bypass the policy file (runtime overrides require explicit human action at the agent system level, not during onboarding);
- proceed past a failed step.

## Failure modes

| Code | When it fires | What to do |
|---|---|---|
| `probe_failed` | passive probe could not reach the device | ask the user to verify cable / IP / power; do not synthesize a fake node |
| `tool_discovery_failed` | tool interface auto-discovery returned empty | device may not expose HTTP endpoints; fall back to `protocol: local` stubs |
| `topology_stale` | new profile registered but snapshot does not show the node | refresh snapshot, re-run from step 4 |
| `llm_rejected` | composer wrote `LLM_REJECTED.json` | read the reasons; re-run with `--mode deterministic` if needed |
| `validate_failed` | builder rejected the package | surface every validator error; fix profile or registry; do not silently relax `safety.forbidden_actions` |
| `standalone_violation` | a node marked standalone appeared in the graph | bug in the composer; report exact node id and skip step 6 |
| `cooperation_conflict` | policy file conflicts with discovered topology | surface the conflict; suggest updating the policy file |
| `hot_plug_failed` | runtime loader rejected the package | validate zip integrity; check config `scan_dirs` includes the dist path |

## Examples

- *User*: "Onboard a new RealSense at `192.168.5.20`, add it to the lab context."
  *Plan*: step 1 with `--ip 192.168.5.20` (discovers `capture_frame` tool at ~200ms latency); steps 2–7 with default `package_id`. Tell the user the new node appears with tool interfaces in the regenerated multi-graph context, hot-plugged and ready.

- *User*: "I plugged in another USB camera. Update the embodiment."
  *Plan*: step 1 with `--usb` (tool discovery uses `protocol: local`); steps 2–7. Note the camera takes the `external_view` role with `capture_frame` tool registered.

- *User*: "Add this G2 robot, but it should stay standalone."
  *Plan*: steps 1–2 normally; step 4 with `--mark-standalone g2_real_sensor_only`; finish steps 5–7. Tell the user G2 is registered with tool interfaces but excluded from collaborative graphs.

- *User*: "Quickly verify the existing context still validates after I unplugged the mic."
  *Plan*: skip step 1; refresh snapshot in step 2; re-run step 4 (composer will drop the mic from the registry and recalculate cooperation pairs); steps 5–7.

- *User*: "Have G1 walk over and check the new camera."
  *Plan*: refuse. `walk` is forbidden by this skill. Offer instead to onboard the camera with G1 staying as observer.

- *User*: "Onboard the camera and immediately make it available for dual-view."
  *Plan*: steps 1–7. After hot-plug, confirm that `select_graph("describe workspace")` returns the dual-view observation graph including the new camera.

## Outputs

After a clean run:

```text
robot_profiles/<device_id>/ROBOT_NODE_PROFILE.md         device profile (from step 1)
robot_profiles/<device_id>/onboarding_session.json       probe evidence
robot_profiles/<device_id>/tool_interface.json           auto-discovered tool interface (v3)
hub/topology_snapshot.json                               updated by step 2
embodiments/generated/<package_id>/EMBODIMENT.md         agent-readable context (v3 format)
embodiments/generated/<package_id>/embodiment.yaml       runtime registry + multi-graph + cooperation
embodiments/dist/<package_id>-<version>.embodiment.zip
embodiments/dist/<package_id>-<version>.manifest.json
```

## How this skill relates to other components

```text
robot_node_onboarding/             device-level: probe + profile card + tool discovery + topology registration
embodiments/composer/              deployment-level: registry + multi-graph + cooperation resolver
embodiments/builder/               offline validation + zip packaging
embodiments/runtime/               runtime loader: discover + activate + hot-plug + get_tools
embodiments/policies/              cooperation policies (default + custom)
embodiments/skills/                ← THIS skill orchestrates all of the above
```

The skill is intentionally a thin orchestrator. All real work lives in the named tools so the contract stays auditable. If you find yourself wanting to extend the skill with custom behavior, prefer extending the underlying tool — not the skill.

## Integration after onboarding

Once a device is onboarded and hot-plugged, the agent system can immediately:

```python
from embodiments.runtime.loader import EmbodimentLoader

loader = EmbodimentLoader(config_path="./embodiments.yaml")
loader.discover()

# Context for system prompt
context = loader.get_context()

# Tool definitions for the agent
tools = loader.get_tools()

# Select a workflow by user intent
graph = loader.select_graph("describe workspace from both cameras")

# Dispatch a tool call
result = loader.dispatch_tool("usb_camera_2.capture_frame", {})

# Cooperation management
loader.cooperation_revoke("g1_usb_dual_view", "usb_camera_2", "llm_planner",
                          operator_id="human_01", reason="camera offline")
loader.cooperation_rollback("g1_usb_dual_view")
```

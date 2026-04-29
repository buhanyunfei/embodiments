---
name: onboard-embodiment
description: Plug-and-play onboarding of a new robot, sensor, or hardware device into the embodiment ecosystem. Discovers the device passively (no motion), generates or extends the deployment's embodiment context, and validates and builds the result. Honors `standalone_only`. Use this whenever a new physical node appears or the user says "onboard / plug in / connect / register / add" a device.
---

# Onboard a new embodiment

This skill is the embodiment-side counterpart of the device-level `robot_node_onboarding` kit. Use it whenever **new physical hardware** has been (or is being) connected to the host running the topology runtime. The skill walks through discovery, profile generation, topology refresh, embodiment composition, validation, and build — all sensor-only by default.

## When to use

- The user says any of: "onboard a robot", "plug in a camera", "connect a new sensor", "register this device", "add G2 to the lab", "extend the embodiment context", "regenerate after adding hardware".
- A new node appeared in `hub/topology_snapshot.json` and the deployment context package needs to reflect it.
- The user wants a robot/sensor to participate in collaborative graphs alongside already-onboarded devices.
- The user wants to mark a device **standalone** (do not include it in any auto-generated collaborative embodiment).

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

If the user did not supply enough information, ask one targeted question; do not guess.

## Workflow

Run these steps in order. Stop and report on any failure.

### Step 1 — passive discovery

```bash
python -m robot_node_onboarding.cli init --robot-id <device_id> [--ip <ip>] [--http-base <url>] [--usb]
python -m robot_node_onboarding.cli discover --robot-id <device_id>
python -m robot_node_onboarding.cli render-profile --robot-id <device_id>
python -m robot_node_onboarding.cli validate-profile robot_profiles/<device_id>/ROBOT_NODE_PROFILE.md
```

These commands ping, HTTP-probe `/health` `/state` `/sensors`, and enumerate USB. **They never command motion.** If discovery fails, surface the error and stop.

For non-robot hardware (a USB camera, a microphone), a lightweight probe is enough — point `--usb` at it; the kit enumerates `/dev/video*` and `arecord -l`.

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

### Step 4 — generate or extend the embodiment context

The composer is **idempotent**. Re-running with an updated topology reflects the new node automatically.

```bash
python embodiments/composer/compose_context.py generate \
  --topology hub/topology_snapshot.json \
  --package-id <package_id> \
  --mode auto \
  --out embodiments/generated \
  [--mark-standalone <device_id> ...]
```

`--mode auto` (default) calls the configured LLM at `hub/copaw_config.json` if available, else falls back to deterministic generation. The output is always two files:

```text
embodiments/generated/<package_id>/
  EMBODIMENT.md
  embodiment.yaml
```

If `LLM_REJECTED.json` appears next to the package, the LLM violated a safety rule and the deterministic doc was kept. Read the rejection reasons and tell the user.

### Step 5 — validate

```bash
python embodiments/builder/build_embodiment.py validate embodiments/generated/<package_id>
```

Stop if validation fails. Surface every error from the validator. Common errors:

- `kind=embodiment_context requires non-empty safety.forbidden_actions` → policy file is broken.
- `registry node 'X' has safe_capabilities containing forbidden actions: [...]` → the new device profile is too permissive; tighten it.
- `EMBODIMENT.md does not mention forbidden action: 'walk'` → the LLM dropped a forbidden action; rerun with `--mode deterministic` and report.

### Step 6 — build

```bash
python embodiments/builder/build_embodiment.py build embodiments/generated/<package_id> \
  --out embodiments/dist
```

Output: `<package_id>-<version>.embodiment.zip` and `.manifest.json` under `embodiments/dist/`.

### Step 7 — report

Summarize for the user:

- node ids included in the new graph;
- node ids skipped as standalone;
- LLM mode resolved (`accepted | rejected | skipped`);
- artifact paths.

## Forbidden actions during onboarding

This skill must not, under any circumstance:

- send any motion command to any device (`navigate`, `walk`, `move`, `turn`, `grasp`, `pick`, `place`, `carry`, `hand_over`, `open_door`, whole-body / arm / hand motion);
- produce audio output;
- substitute a missing real device with a mock node;
- skip the topology snapshot refresh in step 2;
- write `api_key`, SSH keys, or per-deployment credentials into `embodiment.yaml` or `EMBODIMENT.md`;
- proceed past a failed step.

## Failure modes

| Code | When it fires | What to do |
|---|---|---|
| `probe_failed` | passive probe could not reach the device | ask the user to verify cable / IP / power; do not synthesize a fake node |
| `topology_stale` | new profile registered but snapshot does not show the node | refresh snapshot, re-run from step 4 |
| `llm_rejected` | composer wrote `LLM_REJECTED.json` | read the reasons; re-run with `--mode deterministic` if needed |
| `validate_failed` | builder rejected the package | surface every validator error; fix profile or registry; do not silently relax `safety.forbidden_actions` |
| `standalone_violation` | a node marked standalone appeared in the graph | bug in the composer; report exact node id and skip step 6 |

## Examples

- *User*: "Onboard a new RealSense at `192.168.5.20`, add it to the lab context."
  *Plan*: step 1 with `--ip 192.168.5.20`; steps 2–6 with default `package_id`. Tell the user the new node appears as ego/local view in the regenerated graph.
- *User*: "I plugged in another USB camera. Update the embodiment."
  *Plan*: step 1 with `--usb`; steps 2–6. Note the camera takes the `external_view` role.
- *User*: "Add this G2 robot, but it should stay standalone."
  *Plan*: steps 1–2 normally; step 4 with `--mark-standalone g2_real_sensor_only`; finish steps 5–6. Tell the user G2 is registered but excluded from graphs.
- *User*: "Quickly verify the existing context still validates after I unplugged the mic."
  *Plan*: skip step 1; refresh snapshot in step 2; re-run step 4 (composer will drop the mic from the registry); steps 5–6.
- *User*: "Have G1 walk over and check the new camera."
  *Plan*: refuse. `walk` is forbidden by this skill. Offer instead to onboard the camera with G1 staying as observer.

## Outputs

After a clean run:

```text
robot_profiles/<device_id>/ROBOT_NODE_PROFILE.md     device profile (from step 1)
robot_profiles/<device_id>/onboarding_session.json   probe evidence
hub/topology_snapshot.json                            updated by step 2
embodiments/generated/<package_id>/EMBODIMENT.md     agent-readable context
embodiments/generated/<package_id>/embodiment.yaml   runtime registry + 1 graph inlined
embodiments/dist/<package_id>-<version>.embodiment.zip
embodiments/dist/<package_id>-<version>.manifest.json
```

## How this skill relates to other components

```text
robot_node_onboarding/         device-level: probe + profile card + topology registration
embodiments/composer/          deployment-level: registry + collaborative graph
embodiments/builder/           offline validation + zip packaging
embodiments/skills/            ← THIS skill orchestrates the three above
```

The skill is intentionally a thin orchestrator. All real work lives in the named tools so the contract stays auditable. If you find yourself wanting to extend the skill with custom behavior, prefer extending the underlying tool — not the skill.

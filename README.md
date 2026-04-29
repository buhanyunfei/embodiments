# Embodiments

> Agents need skills, tools, memory — and embodiments.

Embodiments are installable, shareable packages for the physical side of an agent runtime: robots, sensors, actuators, hardware rigs, and physical collaboration patterns.

They sit beside skills, tools, and MCP servers:

```text
skills/       software procedures      (SKILL.md is the agent entry)
tools/        callable tools
mcp/          external tool/context servers
embodiments/  physical entities + collaboration graphs   (EMBODIMENT.md is the agent entry)
```

A skill is useful because `SKILL.md` tells the agent *when* and *how* to use it. An embodiment is useful because `EMBODIMENT.md` tells the agent which physical nodes exist, which actions are safe, what to check before execution, and what to never do.

## Slim package layout (2 required files)

The recommended layout is intentionally small:

```text
<package>/
  EMBODIMENT.md       # agent reads this; SKILL.md-style with YAML frontmatter
  embodiment.yaml     # runtime reads this; registry + graphs inlined
  evidence/*.json     # optional; verified probe results
  probes/*.py         # optional; passive only
  adapters/*          # optional; adapter contract or templates
```

That is it. There is no separate `registry/`, `graphs/`, `profiles/`, or `README.md` directory by default. The registry is `embodiment.yaml > registry.nodes`. The graph is `embodiment.yaml > graphs[0]`. The profile/readme content lives inside `EMBODIMENT.md`.

## Layout

```text
SPEC.md                                     short entry doc, points to specs/
BUILDING.md                                 contributor build workflow
specs/
  EMBODIMENT_PACKAGE_SPEC.md                package on-disk format
  AGENT_READABLE_CONTEXT_PACKAGE.md         what EMBODIMENT.md must contain
  EMBODIMENT_GRAPH_SPEC.md                  task/role graph schema (v2)
  NODE_REGISTRY_SPEC.md                     registry schema
  SAFETY_POLICY_SPEC.md                     install/runtime/LLM invariants
  COMPOSER_SPEC.md                          composer behavior
builder/build_embodiment.py                 offline validator + zip packager
composer/compose_context.py                 main composer (LLM-first, 2-file output)
composer_legacy/                            deprecated pairwise composer
templates/context_package/                  EMBODIMENT.md / yaml templates
policies/default_sensor_only_policy.yaml    composer filter+safety policy
skills/
  onboard-embodiment/                       plug-and-play skill: probe → compose → validate → build
    SKILL.md                                  agent-readable instructions
    onboard.py                                thin orchestrator script
packages/
  unitree_g1_sensor_only/                   single-robot package
  usb_1080p_camera/                         single-sensor package
  g1_usb_dual_view/                         dual-view context package
generated/                                  composer outputs
dist/                                       built .embodiment.zip + .manifest.json
```

## Two pieces, peer to skills/MCP/tools

The embodiments module ships **two complementary pieces**, just as the skill ecosystem ships SKILL.md plus the runtime that reads it.

1. **The spec + reference packages** (this directory). What an embodiment package looks like, what makes it agent-readable, how it gets validated and built.
2. **The onboarding skill** at `embodiments/skills/onboard-embodiment/`. When a new robot, sensor, or hardware is plugged in, this skill:
   - probes the device passively (no motion);
   - generates a profile card via `robot_node_onboarding`;
   - extends the deployment's context package automatically — adds the new node to the registry, regenerates the collaborative graph so the new device participates with already-onboarded ones;
   - honors `standalone_only` (a node opted out via topology metadata or `--mark-standalone` is registered but excluded from auto-collaboration);
   - validates and builds the result.

   An LLM agent reads `SKILL.md` to know when to invoke and what each step does; the orchestrator at `onboard.py` runs the underlying tools end-to-end so the user gets one command:

   ```bash
   python embodiments/skills/onboard-embodiment/onboard.py \
     --device-id new_robot_01 --device-kind robot --ip 192.168.5.20 \
     --package-id current_lab_sensor_context
   ```

## Quick start

### Validate a package

```bash
python embodiments/builder/build_embodiment.py validate embodiments/packages/unitree_g1_sensor_only
```

### Build a package

```bash
python embodiments/builder/build_embodiment.py build embodiments/packages/unitree_g1_sensor_only \
  --out embodiments/dist
```

### Generate a context package from current topology (LLM-first)

```bash
# Default: --mode auto. Uses LLM if hub/copaw_config.json is configured.
python embodiments/composer/compose_context.py generate \
  --topology hub/topology_snapshot.json \
  --package-id current_lab_sensor_context \
  --out embodiments/generated

# Force deterministic (no LLM call):
python embodiments/composer/compose_context.py generate \
  --topology hub/topology_snapshot.json --mode deterministic ...

# Require LLM (fail if no config):
python embodiments/composer/compose_context.py generate \
  --topology hub/topology_snapshot.json --mode llm ...
```

The composer always produces exactly two files: `EMBODIMENT.md` (agent-readable) and `embodiment.yaml` (registry + 1 primary graph inlined).

## How an agent runtime plugs in

```text
1. parse EMBODIMENT.md   (planner-grounding context, SKILL.md-style)
2. read  embodiment.yaml (registry.nodes, graphs[0], safety.forbidden_actions)
3. register nodes        (only with user authorization)
4. plan via graphs[0]    (roles + nodes + readiness + recovery)
5. enforce safety        (block forbidden_actions at the executor, not just the planner)
```

That is the full contract.

## Safety guarantees

- Build is offline — never contacts hardware.
- Install does not move — filesystem-only.
- Sensor-only is the default — `sensor_only: true` cannot declare motion or manipulation as safe.
- No mock substitution — if a referenced real-device node is missing, the runtime fails fast.
- LLM cannot expand safety — composer rejects LLM output that drops a forbidden action, drops a section, or contains promotion language.

See `specs/SAFETY_POLICY_SPEC.md` for the full list of invariants.

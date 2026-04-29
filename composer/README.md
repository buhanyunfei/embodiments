# Embodiment Context Composer

This is the main composer. It generates **one** agent-readable embodiment context package from a topology snapshot.

```text
embodiments/composer/compose_context.py
```

For the contract this composer follows, see `embodiments/specs/COMPOSER_SPEC.md`.

## Why one package, not many

The legacy composer at `embodiments/composer_legacy/` generated one package per node and one package per pair of compatible observers. With *N* observers that produced *N + N·(N−1)/2* packages.

The main composer instead emits a single context package with task-oriented graphs:

```text
sensor_only_multiview_observation     when 2+ observers exist
single_view_fallback_observation      when 1+ observer exists
audio_readiness_check                 when 1+ audio listener exists
```

## Output layout

```text
<out>/<package_id>/
  EMBODIMENT.md
  embodiment.yaml
  README.md
  registry/nodes.yaml
  graphs/<task>.yaml
```

## Modes

- `--mode deterministic` (default) — pure local generation. No external calls.
- `--mode llm-assisted` — optionally rewrites `EMBODIMENT.md` via a configured OpenAI-compatible endpoint. The output is validated against the forbidden-actions and required-sections lists. On any violation, the deterministic doc is kept and a `LLM_REJECTED.json` is written next to the package for review.

## Usage

Preview (no files written):

```bash
python embodiments/composer/compose_context.py preview \
  --topology hub/topology_snapshot.json
```

Generate:

```bash
python embodiments/composer/compose_context.py generate \
  --topology hub/topology_snapshot.json \
  --package-id current_lab_sensor_context \
  --out embodiments/generated
```

LLM-assisted (requires `hub/copaw_config.json` with `api_base`, `api_key`, `model`):

```bash
python embodiments/composer/compose_context.py generate \
  --topology hub/topology_snapshot.json \
  --mode llm-assisted \
  --llm-config hub/copaw_config.json
```

Build the generated package:

```bash
python embodiments/builder/build_embodiment.py build \
  embodiments/generated/current_lab_sensor_context \
  --out embodiments/dist
```

## Safety

- The composer never invents capabilities not present in `registry/nodes.yaml`.
- The composer never copies forbidden actions into a node's safe list.
- LLM output that drops a required heading, drops a forbidden action, or contains language like "can navigate / can grasp" is rejected; the deterministic doc is kept.
- API keys are masked in any composer-written file (`sk-***...***`) and never logged.

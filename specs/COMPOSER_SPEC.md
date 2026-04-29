# Embodiment Composer Spec v0.3

The composer is a tool, not a package. It reads a topology snapshot and a policy file, and writes one agent-readable embodiment context package consisting of exactly **two files**:

```text
<out>/<package_id>/
  EMBODIMENT.md       agent-readable, SKILL.md-style
  embodiment.yaml     runtime-readable, with `registry` and a single primary `graphs[0]` inlined
```

The main composer lives at:

```text
embodiments/composer/compose_context.py
```

The legacy pairwise composer (deprecated) lives at:

```text
embodiments/composer_legacy/compose_embodiments.py
```

## Goal

Given:

- `hub/topology_snapshot.json` (or any compatible snapshot);
- `embodiments/policies/default_sensor_only_policy.yaml`;
- optional `hub/copaw_config.json` for LLM-assisted mode;

produce **one** package with the slim layout above.

## Modes

```text
--mode auto            (default) use LLM if hub/copaw_config.json is configured, else deterministic.
--mode llm             require LLM; fail if config is missing.
--mode deterministic   never call LLM; emit deterministic SKILL.md-style doc.
```

The default is `auto` because the LLM produces dramatically more concrete output than templated text — but it must remain optional so the composer can run in air-gapped or no-budget environments.

## Filtering rules

The composer:

- includes only nodes whose `node_type` is in the policy's `observer_node_types`;
- excludes nodes with `collaboration_policy.standalone_only: true`;
- intersects each node's `capabilities` with the policy's `safe_collaboration_capabilities` to compute `safe_capabilities`;
- never copies forbidden actions into a node's safe list.

## Graph emission

The composer emits **at most one** primary graph: `sensor_only_observation`. Fallbacks (single-view) and audio-readiness behavior live inside this graph as `readiness_checks` and `recovery.auto_allowed` entries — they are *not* separate graph YAMLs.

The graph follows `embodiment_graph/v2`. See `EMBODIMENT_GRAPH_SPEC.md`.

If the topology has no observer and no audio listener, the composer emits no graph and tags the package as observation-incapable.

## LLM contract

When the composer calls the LLM, it sends:

- a structured facts payload (real node ids, sensors, limits, evidence excerpts, image paths, last RMS, forbidden_actions list);
- a strict system prompt forbidding capability invention, forbidden-action removal, and sensor-only promotion;
- the required section headings and the `frontmatter_to_emit_verbatim` block.

After the LLM returns, the composer runs a deterministic validator:

- all required section headings present;
- all forbidden actions appear verbatim;
- all registry node ids appear in the doc;
- no promotion phrases ("can navigate / can grasp / can pick / may walk / is able to walk", etc.);
- YAML frontmatter present at the top.

On any failure, the deterministic doc is kept and `LLM_REJECTED.json` is written next to the package, with the reason list and the masked api_key.

## Outputs

The composer prints:

```json
{
  "ok": true,
  "package_id": "current_lab_sensor_context",
  "mode_requested": "auto",
  "mode_resolved": "llm",
  "llm_status": "accepted",
  "included_nodes": [...],
  "skipped_standalone_nodes": [...],
  "graph_id": "sensor_only_observation",
  "files": ["EMBODIMENT.md", "embodiment.yaml"],
  "written": "<path>"
}
```

`mode_resolved` shows what was actually attempted; `llm_status` is one of `skipped | accepted | rejected | error:<Type>`.

## Logging and credentials

- The composer must never print full `api_key` values. Only `sk-***...***` masking is allowed.
- The composer must never write the api_key to `embodiment.yaml`, the manifest, or any generated file.
- The composer's network call uses an explicit `urllib.request` opener with `ProxyHandler({})` to avoid leaking the topology to misconfigured proxies.

## Re-running

Re-running with the same inputs is idempotent: it overwrites `EMBODIMENT.md` and `embodiment.yaml` deterministically. Files placed manually in `evidence/`, `policies/`, or `adapters/` are not touched.

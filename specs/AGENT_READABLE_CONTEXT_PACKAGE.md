# Agent-readable Embodiment Context Package v0.3

This is the recommended package format for making embodiments usable by LLM agents, OpenClaw-like systems, and topology runtimes.

It follows the same design spirit as skills:

```text
A skill is useful because SKILL.md tells the agent when to use it, how to use it, and what not to do.
An embodiment is useful because EMBODIMENT.md tells the agent which physical nodes are real,
which actions are safe, what to check before execution, and what to never do.
```

## Slim, 2-file layout

A real deployment publishes **one** package with **two** required files:

```text
<package_id>/
  EMBODIMENT.md       # primary agent-readable instruction file (with YAML frontmatter)
  embodiment.yaml     # runtime metadata, with `registry` and `graphs` inlined
  evidence/*.json     # optional verified probe results
```

Do not create separate `registry/`, `graphs/`, `profiles/`, or `README.md` files. The point is that an agent can plan from a single doc plus one small yaml — no archaeology.

## Required `EMBODIMENT.md` shape

The doc must start with YAML frontmatter and contain 8 sections, in order. The validator enforces this for `kind: embodiment_context`.

```markdown
---
name: <package_id>
description: One concrete sentence the agent reads to decide whether to use this.
version: 0.3.0
kind: embodiment_context
primary_agent_doc: EMBODIMENT.md
---

# <Title>

## When to use
## When not to use
## Available nodes
## How to plan
## Forbidden actions
## Failure modes
## Recovery
## Runtime integration
```

### Concrete content rules

- `## Available nodes` lists every registry node by id, with role, safe capabilities, and any concrete evidence (image paths, RMS values, IPs, serials). Generic descriptions ("a camera") are not sufficient.
- `## How to plan` contains 3–5 worked examples mapping real user requests to plans that name real node ids. At least one example must show a refusal of a forbidden action.
- `## Forbidden actions` lists every action from `safety.forbidden_actions` verbatim in a fenced `text` block.
- `## Failure modes` is a table with `Code | When it fires | Attribution`.
- `## Recovery` separates *auto-recovery*, *requires confirmation*, and *not recoverable* explicitly.
- `## Runtime integration` is 4–6 lines, no fluff, telling an agent runtime what to load and what to enforce.

## Agent contract

A planner reading `EMBODIMENT.md` should answer in one pass:

- Can I use this for navigation? (often: no, sensor-only)
- Can I use this for grasping? (often: no)
- Which node is the ego/local view?
- Which node is the third-person view?
- What must I check before execution?
- What graph_id should I run for sensor-only observation?
- What do I do when a node is offline?
- What must I never do?

If reading the doc does not answer all of these, the doc is not finished.

## Graph rule

Emit at most **one primary graph** per context package. Fallbacks (single-view, audio-only) and recovery options live inside the same graph as `recovery.auto_allowed` entries, not as separate graph YAMLs. Pairwise graph explosion is forbidden.

A graph must follow `embodiment_graph/v2`. See `EMBODIMENT_GRAPH_SPEC.md`.

## LLM generation

The composer is LLM-first by default (`--mode auto`): if `hub/copaw_config.json` is configured, it calls the LLM with a structured facts payload (real node ids, real evidence, real forbidden list) and asks it to compose the doc.

LLM constraints (deterministic post-validation):

- All required section headings must be present.
- All forbidden actions must appear verbatim.
- All registry node ids must be referenced in the doc.
- No "can navigate / can grasp / can pick / may walk" promotion phrases.
- YAML frontmatter must be present at the top.

If the LLM output fails any of these, the deterministic doc is kept and a `LLM_REJECTED.json` is written next to the package for review. See `COMPOSER_SPEC.md` and `SAFETY_POLICY_SPEC.md`.

## Safety rule

Generated context packages must default to sensor-only unless explicitly promoted by:

- verified evidence under `evidence/`, AND
- explicit user policy under `policies/safety.yaml`, AND
- a graph that names motion/manipulation as required and lists the readiness checks for it.

If any of these is missing, the package must remain sensor-only.

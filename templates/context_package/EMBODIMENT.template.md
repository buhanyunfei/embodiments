---
name: example_context
description: One concrete sentence the agent reads to decide whether to use this. Mention the kind of nodes, the safe actions, and the forbidden actions.
version: 0.1.0
kind: embodiment_context
primary_agent_doc: EMBODIMENT.md
---

# {{ title }}

This file is the agent's primary instruction for the **{{ package_id }}** embodiment context. It plays the same role for physical embodiment that `SKILL.md` plays for software skills.

## When to use

Replace this with concrete conditions. Examples:

- The task needs a third-person view of the workspace.
- The task needs a microphone capture-readiness check.
- ...

## When not to use

Replace this with concrete refusals. Examples:

- The user asks for any motion or manipulation.
- The user asks for audio output.
- ...

## Available nodes

For each node introduced by this package, list:

- id and name (verbatim, no inventions)
- type and role
- safe capabilities
- concrete evidence (image paths, RMS values, IPs, serials) where available

## How to plan

Map 3–5 real user requests to plans that name real node ids. At least one example must show a refusal of a forbidden action.

- *User*: "..."  *Plan*: ...
- *User*: "..."  *Plan*: refuse, this asks for `<forbidden_action>`.

## Forbidden actions

```text
{{ forbidden_actions }}
```

If the user explicitly asks for one of these, refuse and explain why. Do not silently downgrade.

## Failure modes

| Code | When it fires | Attribution |
|---|---|---|
| `node_missing` | A required node id is not present in topology | topology |
| `node_offline` | Node exists but adapter/endpoint is unreachable | hardware |
| `capability_missing` | Node does not declare a required safe capability | configuration |
| `forbidden_action_requested` | Task asks for an action in the forbidden list | planner |
| `sensor_artifact_missing` | Capture script ran but no frame/audio file was produced | sensor |

## Recovery

Auto-recovery (no confirmation needed):

- ...

Requires explicit user confirmation:

- any motion, any manipulation, any audio output;
- promoting the embodiment out of `sensor_only`.

Not recoverable here:

- ...

## Runtime integration

A topology runtime should:

1. parse this `EMBODIMENT.md` as planner-grounding context;
2. read `embodiment.yaml > registry.nodes` and `embodiment.yaml > graphs[0]`;
3. register the listed nodes only with user authorization;
4. enforce `safety.forbidden_actions` at the executor;
5. surface failure-mode codes verbatim in the episode trace.

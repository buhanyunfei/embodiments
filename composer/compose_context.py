#!/usr/bin/env python3
"""Embodiment context composer (main).

Generates ONE agent-readable embodiment context package from a topology snapshot.

Output (slim layout, 2 required files):

    <out>/<package_id>/
      EMBODIMENT.md       agent-readable, SKILL.md-style, capability-complete
      embodiment.yaml     runtime-readable, registry + 1 graph inlined

Safety profiles (--safety-profile):
  sensor_only         safe-class only; motion/manipulation/audio_output forbidden  [default]
  motion_supervised   locomotion enabled with confirmation; manipulation gated
  full_humanoid       all capabilities available; high-risk requires confirmation/supervisor

Modes (--mode):
  auto          use LLM if hub/copaw_config.json configured, else deterministic  [default]
  llm           require LLM; fail if not configured
  deterministic never call LLM
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

# ── Defaults ─────────────────────────────────────────────────────────────────

SAFE_DEFAULT = ["observe", "inspect", "listen", "perceive", "wait", "standby", "health_check"]
MOTION_DEFAULT = ["walk", "turn", "navigate", "move", "whole_body_motion", "follow", "patrol"]
MANIPULATION_DEFAULT = ["reach", "grasp", "pick", "place", "carry", "hand_over", "open_door",
                        "arm_motion", "hand_motion", "push", "pull"]
AUDIO_OUTPUT_DEFAULT = ["audio_output", "speak", "play_sound"]

OBSERVER_NODE_TYPES_DEFAULT = ["physical_robot", "sensor", "camera", "microphone"]
SCHEMA_PACKAGE = "embodiment_package/v2"
SCHEMA_GRAPH = "embodiment_graph/v2"
SCHEMA_REGISTRY = "embodiment_node_registry/v1"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _slug(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-]+", "_", s or "").strip("_").lower() or "embodiment_context"


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _load_topology(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"topology not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _mask_key(k: Optional[str]) -> str:
    if not k or len(k) <= 8:
        return "****"
    return f"{k[:4]}...{k[-4:]}"


# ── Capability classification ─────────────────────────────────────────────────

def _build_class_map(policy: Dict[str, Any]) -> Dict[str, str]:
    """Return {action_id -> class_name} from policy."""
    raw = policy.get("capability_classes") or {}
    # Policy yaml may store as dict of dicts or flat key:value
    m: Dict[str, str] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            m[k] = str(v) if not isinstance(v, dict) else v.get("class", "unknown")
    for action in SAFE_DEFAULT:
        m.setdefault(action, "safe")
    for action in MOTION_DEFAULT:
        m.setdefault(action, "motion")
    for action in MANIPULATION_DEFAULT:
        m.setdefault(action, "manipulation")
    for action in AUDIO_OUTPUT_DEFAULT:
        m.setdefault(action, "audio_output")
    return m


def _build_profile(policy: Dict[str, Any], profile_name: str) -> Dict[str, Any]:
    """Resolve a named safety profile to a dict with forbidden_classes, confirmation_classes, etc."""
    profiles = policy.get("safety_profiles") or {}
    p = profiles.get(profile_name) or {}
    return {
        "name": profile_name,
        "description": p.get("description", ""),
        "allowed_classes": set(p.get("allowed_classes") or ["safe"]),
        "confirmation_classes": set(p.get("confirmation_classes") or []),
        "supervisor_classes": set(p.get("supervisor_classes") or []),
        "forbidden_classes": set(p.get("forbidden_classes") or []),
    }


def _capability_status(action: str, class_map: Dict[str, str], profile: Dict[str, Any]) -> str:
    """Return 'safe' | 'confirmation' | 'supervisor' | 'forbidden' for an action+profile."""
    cls = class_map.get(action, "unknown")
    if cls in profile["forbidden_classes"]:
        return "forbidden"
    if cls in profile["supervisor_classes"]:
        return "supervisor"
    if cls in profile["confirmation_classes"]:
        return "confirmation"
    if cls in profile["allowed_classes"]:
        return "safe"
    # unknown class -> conservative: treat as confirmation
    return "confirmation"


def _forbidden_actions(all_caps: List[str], class_map: Dict[str, str], profile: Dict[str, Any]) -> List[str]:
    return sorted(a for a in all_caps if _capability_status(a, class_map, profile) == "forbidden")


def _safe_actions(all_caps: List[str], class_map: Dict[str, str], profile: Dict[str, Any]) -> List[str]:
    return sorted(a for a in all_caps if _capability_status(a, class_map, profile) == "safe")


# ── Node normalization ────────────────────────────────────────────────────────

def _normalize_nodes(snapshot: Dict[str, Any], policy: Dict[str, Any],
                     standalone_overrides: Optional[Set[str]] = None) -> List[Dict[str, Any]]:
    raw = snapshot.get("nodes") or []
    if isinstance(raw, dict):
        raw = list(raw.values())
    safe_collab_set = set(policy.get("safe_collaboration_capabilities") or SAFE_DEFAULT)
    standalone_overrides = standalone_overrides or set()
    out: List[Dict[str, Any]] = []
    for n in raw:
        meta = n.get("metadata") or {}
        profile = meta.get("robot_profile") or meta.get("embodiment_profile") or {}
        # Collect all declared capabilities (topology + profile card)
        all_caps = list(dict.fromkeys(
            (n.get("capabilities") or [])
            + (profile.get("capabilities") or [])
            + (profile.get("action_space") or [])
        ))
        sensors = profile.get("sensors") or meta.get("sensors") or []
        if sensors:
            all_caps.append("observe")
        all_caps = list(dict.fromkeys(all_caps))
        # Safe for collaboration = intersection with safe_collab_set
        safe_collab = sorted(c for c in all_caps if c in safe_collab_set)
        limits = profile.get("limits") or meta.get("limits") or {}
        coll = meta.get("collaboration_policy") or profile.get("collaboration_policy") or {}
        nid = n.get("id") or n.get("node_id")
        forced_standalone = nid in standalone_overrides
        node = {
            "id": nid,
            "name": n.get("name") or nid,
            "node_type": n.get("node_type") or meta.get("node_type") or "unknown",
            "all_capabilities": all_caps,
            "safe_capabilities": safe_collab,
            "sensors": sensors,
            "limits": limits,
            "endpoint": n.get("endpoint") or meta.get("endpoint"),
            "agent_ref": n.get("agent_ref") or meta.get("agent_ref"),
            "parent_robot": meta.get("parent_robot"),
            "standalone_only": bool(coll.get("standalone_only") or forced_standalone),
            "standalone_reason": "user_marked" if forced_standalone else (coll.get("reason") if coll.get("standalone_only") else None),
            "evidence_excerpt": (meta.get("robot_profile_card_body") or "")[:1200],
            "image_path": meta.get("image_path"),
            "last_rms": meta.get("last_rms"),
            "real_device": bool(meta.get("real_device")),
        }
        if node["id"]:
            out.append(node)
    return out


def _select_nodes(nodes: List[Dict[str, Any]], policy: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    allowed = set(policy.get("observer_node_types") or OBSERVER_NODE_TYPES_DEFAULT)
    included, skipped = [], []
    for n in nodes:
        if n["standalone_only"]:
            skipped.append({"id": n["id"], "reason": n.get("standalone_reason") or "standalone_only"})
            continue
        if n["node_type"] not in allowed:
            continue
        if not n["all_capabilities"] and not n["safe_capabilities"]:
            continue
        included.append(n)
    return included, skipped


def _node_role(n: Dict[str, Any]) -> str:
    nid = (n.get("id") or "").lower()
    node_type = (n.get("node_type") or "").lower()
    caps = set(n.get("all_capabilities") or [])
    sensors = set(s.lower() for s in (n.get("sensors") or []))
    if node_type == "physical_robot":
        return "robot_local_view"
    if "mic" in nid or sensors == {"microphone"} or caps == {"listen"}:
        return "audio_input"
    if "realsense" in nid or n.get("parent_robot"):
        return "robot_local_view"
    if "camera" in nid or "perceive" in caps or "observe" in caps:
        return "external_view"
    return "support_node"


# ── Facts ─────────────────────────────────────────────────────────────────────

def _facts(snapshot: Dict[str, Any], policy: Dict[str, Any], package_id: str, title: str,
           active_profile: Dict[str, Any], class_map: Dict[str, str],
           standalone_overrides: Optional[Set[str]] = None) -> Dict[str, Any]:
    nodes_all = _normalize_nodes(snapshot, policy, standalone_overrides=standalone_overrides)
    included, skipped = _select_nodes(nodes_all, policy)

    # Enrich each included node with per-capability status under active profile
    for n in included:
        n["capability_table"] = {
            cap: {
                "class": class_map.get(cap, "unknown"),
                "status": _capability_status(cap, class_map, active_profile),
            }
            for cap in n["all_capabilities"]
        }

    all_node_caps = list(dict.fromkeys(c for n in included for c in n["all_capabilities"]))
    observers = [n for n in included if "observe" in n.get("all_capabilities", []) or "perceive" in n.get("all_capabilities", [])]
    audio = [n for n in included if "listen" in n.get("all_capabilities", [])]
    robots = [n for n in included if n.get("node_type") == "physical_robot"]

    forbidden = _forbidden_actions(all_node_caps, class_map, active_profile)
    safe = _safe_actions(all_node_caps, class_map, active_profile)

    return {
        "package_id": package_id,
        "title": title,
        "active_profile": active_profile,
        "class_map": class_map,
        "forbidden_actions": forbidden,
        "safe_actions": safe,
        "included_nodes": included,
        "skipped_standalone": skipped,
        "observers": observers,
        "audio_listeners": audio,
        "robots": robots,
        "all_node_capabilities": all_node_caps,
        "snapshot_meta": {"saved_at": snapshot.get("saved_at")},
    }


# ── Graph ─────────────────────────────────────────────────────────────────────

def _primary_graph(facts: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    observers = facts["observers"]
    audio = facts["audio_listeners"]
    if not observers and not audio:
        return None

    profile = facts["active_profile"]
    forbidden = facts["forbidden_actions"]

    roles: List[Dict[str, Any]] = []
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    locals_ = [n for n in observers if _node_role(n) == "robot_local_view"]
    externals = [n for n in observers if _node_role(n) == "external_view"]

    if locals_:
        roles.append({"role_id": "robot_local_view",
                      "description": "Ego/first-person view from a robot-mounted sensor.",
                      "required_capabilities": ["observe"],
                      "preferred_nodes": [n["id"] for n in locals_],
                      "minimum": 0, "maximum": 9999})
    if externals:
        roles.append({"role_id": "external_view",
                      "description": "Third-person view from an external camera.",
                      "required_capabilities": ["observe"],
                      "preferred_nodes": [n["id"] for n in externals],
                      "minimum": 0, "maximum": 9999})
    if audio:
        roles.append({"role_id": "audio_input",
                      "description": "Microphone for audio capture (capture only, never output).",
                      "required_capabilities": ["listen"],
                      "preferred_nodes": [n["id"] for n in audio],
                      "minimum": 0, "maximum": 9999})
    roles.append({"role_id": "perception_model",
                  "description": "Runtime-provided VLM/perception model.",
                  "required_capabilities": ["image_understanding"],
                  "minimum": 1, "maximum": 1})

    for n in observers:
        nodes.append({"id": n["id"], "role": _node_role(n), "node_type": n["node_type"],
                      "required_capabilities": ["observe"]})
        edges.append({"source": n["id"], "target": "perception_vision", "edge_type": "observation_stream"})
    for n in audio:
        if not any(x["id"] == n["id"] for x in nodes):
            nodes.append({"id": n["id"], "role": "audio_input", "node_type": n["node_type"],
                          "required_capabilities": ["listen"]})
    nodes.append({"id": "perception_vision", "role": "perception_model",
                  "node_type": "perception_model", "required_capabilities": ["image_understanding"]})

    # Readiness checks depend on profile
    readiness = ["all_required_nodes_exist", "required_capabilities_are_safe",
                 "sensor_artifacts_available_or_capture_allowed", "no_forbidden_action_in_task"]
    if "motion" in profile["confirmation_classes"] or "motion" in profile["supervisor_classes"]:
        readiness.append("user_confirmed_motion_in_scope")
    if "manipulation" in profile["supervisor_classes"]:
        readiness.append("supervisor_signoff_obtained")
    if audio:
        readiness.append("audio_rms_non_zero_or_explicitly_unverified")

    return {
        "schema": SCHEMA_GRAPH,
        "graph_id": "observation",
        "name": f"Observation Graph ({profile['name']} profile)",
        "intent": "Observe and describe the environment using available sensors and actuators, within the active safety profile.",
        "safety_level": profile["name"],
        "active_safety_profile": profile["name"],
        "roles": roles,
        "nodes": nodes,
        "edges": edges,
        "constraints": {
            "allow_motion": "motion" not in profile["forbidden_classes"],
            "allow_manipulation": "manipulation" not in profile["forbidden_classes"],
            "allow_audio_output": "audio_output" not in profile["forbidden_classes"],
            "forbidden_actions": forbidden,
        },
        "readiness_checks": readiness,
        "failure_modes": [
            {"id": "node_missing", "when": "required node id not in topology", "attribution": "topology"},
            {"id": "node_offline", "when": "adapter/endpoint unreachable", "attribution": "hardware"},
            {"id": "capability_missing", "when": "node lacks a required capability", "attribution": "configuration"},
            {"id": "forbidden_action_requested", "when": "task action is in forbidden_actions for active profile", "attribution": "planner"},
            {"id": "sensor_artifact_missing", "when": "frame/audio file not produced", "attribution": "sensor"},
            {"id": "missing_confirmation", "when": "motion/manipulation planned without prior user confirmation", "attribution": "planner"},
            {"id": "unverified_audio_pickup", "when": "audio captured but RMS=0 or speech absent", "attribution": "sensor"},
        ],
        "recovery": {
            "auto_allowed": ["retry_passive_health_check", "choose_alternate_observer", "downgrade_multiview_to_single_view"],
            "requires_confirmation": sorted((profile["confirmation_classes"] | profile["supervisor_classes"]) or {"any_motion"}),
            "not_recoverable": ["missing_capable_executor"],
        },
        "outputs": ["scene_description"]
                    + (["motion_trace"] if "motion" in (profile["confirmation_classes"] | profile["supervisor_classes"]) else [])
                    + (["manipulation_trace"] if "manipulation" in (profile["supervisor_classes"]) else [])
                    + (["audio_pickup_status"] if audio else [])
                    + ["sensor_readiness_report", "failure_attribution", "episode_trace"],
    }


def _registry_inline(included: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "schema": SCHEMA_REGISTRY,
        "nodes": [
            {
                "id": n["id"],
                "name": n.get("name"),
                "node_type": n["node_type"],
                "role": _node_role(n),
                "all_capabilities": n.get("all_capabilities") or [],
                "safe_capabilities": n.get("safe_capabilities") or [],
                "sensors": n.get("sensors") or [],
                "limits": n.get("limits") or {},
                "standalone_only": n.get("standalone_only", False),
                "endpoint_configured": bool(n.get("endpoint")),
                "real_device": n.get("real_device", False),
                "parent_robot": n.get("parent_robot"),
            }
            for n in included
        ],
    }


# ── Deterministic EMBODIMENT.md ───────────────────────────────────────────────

def _cap_table_md(n: Dict[str, Any]) -> str:
    table = n.get("capability_table") or {}
    if not table:
        return "  _(no capabilities declared)_"
    rows = ["  | capability | class | active profile status |",
            "  |---|---|---|"]
    for cap, info in sorted(table.items()):
        rows.append(f"  | `{cap}` | `{info['class']}` | `{info['status']}` |")
    return "\n".join(rows)


def _node_block(n: Dict[str, Any]) -> str:
    role = _node_role(n)
    lines = [
        f"### `{n['id']}` — {n.get('name') or n['id']}",
        f"- Type: `{n['node_type']}` · Role: `{role}`",
    ]
    if n.get("sensors"):
        lines.append(f"- Sensors: `{', '.join(n['sensors'])}`")
    if n.get("limits"):
        lines.append(f"- Limits: `{json.dumps(n['limits'], ensure_ascii=False)}`")
    if n.get("image_path"):
        lines.append(f"- Last sensor artifact: `{n['image_path']}`")
    if n.get("last_rms") is not None:
        rms = n["last_rms"]
        tag = "verified" if rms not in (0, None) else "unverified (RMS=0)"
        lines.append(f"- Last audio RMS: `{rms}` ({tag})")
    if n.get("evidence_excerpt"):
        first = n["evidence_excerpt"].splitlines()[0].strip() if n["evidence_excerpt"].splitlines() else ""
        if first:
            lines.append(f"- Profile note: {first}")
    lines.append("\n  Capability status under active profile:\n")
    lines.append(_cap_table_md(n))
    return "\n".join(lines)


def _profile_summary_md(facts: Dict[str, Any]) -> str:
    p = facts["active_profile"]
    forbidden = facts["forbidden_actions"]
    lines = [
        f"Active profile: **`{p['name']}`** — {p['description'].strip()}",
        "",
        "| class | behavior under this profile |",
        "|---|---|",
    ]
    for cls, behavior in [
        ("safe", "plan freely"),
        ("motion", "requires confirmation" if "motion" in p["confirmation_classes"] else ("requires supervisor" if "motion" in p["supervisor_classes"] else "**forbidden**")),
        ("manipulation", "requires confirmation" if "manipulation" in p["confirmation_classes"] else ("requires supervisor" if "manipulation" in p["supervisor_classes"] else "**forbidden**")),
        ("audio_output", "requires confirmation" if "audio_output" in p["confirmation_classes"] else ("requires supervisor" if "audio_output" in p["supervisor_classes"] else "**forbidden**")),
    ]:
        lines.append(f"| `{cls}` | {behavior} |")
    if forbidden:
        lines += ["", "Forbidden actions under this profile:",
                  "```text", *forbidden, "```"]
    return "\n".join(lines)


def _profile_override_md(facts: Dict[str, Any]) -> str:
    profile_name = facts["active_profile"]["name"]
    lines = ["The user can change the safety profile at prompt time. Available profiles:",
             ""]
    # Add info about other profiles
    profile_to_rules = {
        "sensor_only": "Locomotion + manipulation + audio_output forbidden. Read-only.",
        "motion_supervised": "Locomotion enabled with confirmation. Manipulation forbidden. Good for mobile inspection.",
        "full_humanoid": "All capabilities available. Motion requires confirmation. Manipulation requires confirmation + supervisor.",
    }
    for pname, desc in profile_to_rules.items():
        marker = " ← current" if pname == profile_name else ""
        lines.append(f"- **`{pname}`**: {desc}{marker}")
    return "\n".join(lines)


def _worked_examples_md(facts: Dict[str, Any]) -> str:
    profile = facts["active_profile"]
    included = facts["included_nodes"]
    observers = facts["observers"]
    audio = facts["audio_listeners"]
    robots = facts["robots"]

    locals_ = [n for n in observers if _node_role(n) == "robot_local_view"]
    externals = [n for n in observers if _node_role(n) == "external_view"]

    examples: List[str] = []

    # Always: describe workspace
    if locals_ and externals:
        examples.append(
            f'- *User*: "Describe the workspace."\n'
            f'  *Plan*: capture frames from `{locals_[0]["id"]}` (ego) and `{externals[0]["id"]}` (third-person); send to `perception_vision`; return dual-view description. No motion required.'
        )
    elif observers:
        examples.append(
            f'- *User*: "What do you see?"\n'
            f'  *Plan*: capture one frame from `{observers[0]["id"]}`; describe to user.'
        )

    # Audio check
    if audio:
        rms = audio[0].get("last_rms")
        rms_note = ""
        if rms in (0, None):
            rms_note = " Tag `unverified_audio_pickup` if RMS stays zero."
        examples.append(
            f'- *User*: "Is the microphone working?"\n'
            f'  *Plan*: record 1–2 s on `{audio[0]["id"]}`; report RMS.{rms_note}'
        )

    # Motion example
    if robots:
        if "motion" in profile["forbidden_classes"]:
            examples.append(
                f'- *User*: "Walk forward 1 meter."\n'
                f'  *Plan*: **refuse** — `walk` is forbidden under the `{profile["name"]}` profile. '
                f'Tell the user to switch to `motion_supervised` profile and try again.'
            )
        elif "motion" in profile["confirmation_classes"]:
            examples.append(
                f'- *User*: "Walk forward 1 meter."\n'
                f'  *Plan*: ask user to confirm ("Confirm: G1 will walk 1 m forward. Proceed?"). '
                f'If confirmed, plan `walk` with `{robots[0]["id"]}`; run obstacle_check and floor_clear readiness first.'
            )

    # Manipulation example
    if robots:
        if "manipulation" in profile["forbidden_classes"]:
            examples.append(
                f'- *User*: "Pick up the cup."\n'
                f'  *Plan*: **refuse** — `pick` is forbidden under the `{profile["name"]}` profile. '
                f'Tell the user to switch to `full_humanoid` profile (which requires supervisor signoff) and try again.'
            )
        elif "manipulation" in profile["supervisor_classes"]:
            examples.append(
                f'- *User*: "Pick up the cup."\n'
                f'  *Plan*: require user confirmation AND supervisor signoff. State: "This requires supervisor sign-off in addition to your confirmation." '
                f'If both obtained, plan `grasp`+`pick` with `{robots[0]["id"]}` after object_identified and grasp_plan_verified readiness checks.'
            )

    # G1 + camera collaboration
    if locals_ and externals:
        examples.append(
            f'- *User*: "Describe what the robot sees compared to the external camera."\n'
            f'  *Plan*: run `observation` graph; assign `{locals_[0]["id"]}` to `robot_local_view` role, `{externals[0]["id"]}` to `external_view`, `perception_vision` to `perception_model`. Return fused dual-view description.'
        )

    return "\n\n".join(examples)


def _frontmatter(facts: Dict[str, Any], graph_id: Optional[str]) -> str:
    fm = {
        "name": facts["package_id"],
        "description": (
            f"Embodiment context for {len(facts['included_nodes'])} device(s). "
            f"Active profile: {facts['active_profile']['name']}. "
            "Switch profile or constrain via prompt to change allowed actions."
        ),
        "version": "0.3.0",
        "kind": "embodiment_context",
        "active_safety_profile": facts["active_profile"]["name"],
        "primary_graph": graph_id or "none",
    }
    return "---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).rstrip() + "\n---\n"


def _deterministic_md(facts: Dict[str, Any], graph: Optional[Dict[str, Any]]) -> str:
    graph_id = graph["graph_id"] if graph else None
    nodes_block = "\n\n".join(_node_block(n) for n in facts["included_nodes"]) or "_No eligible nodes._"

    return (
        _frontmatter(facts, graph_id)
        + f"\n# {facts['title']}\n\n"
        "This file is the agent's primary instruction for this embodiment context. "
        "Read it the way you would read a `SKILL.md`. "
        "It describes the **full capability set** of available hardware and how to plan with it safely.\n\n"

        "## When to use this embodiment\n\n"
        f"Use this when the task involves {len(facts['included_nodes'])} real device(s) listed below. "
        "This is real hardware — never substitute a mock node for a missing real one.\n\n"

        "## When not to use this embodiment\n\n"
        "Do not use this embodiment for tasks that require capabilities not present in the device registry, "
        "or when a device is offline and no valid fallback exists.\n\n"

        "## Active safety profile\n\n"
        f"{_profile_summary_md(facts)}\n\n"

        "## Changing the safety profile\n\n"
        f"{_profile_override_md(facts)}\n\n"

        "## Available nodes\n\n"
        f"{nodes_block}\n\n"

        "## How to plan\n\n"
        + (f"The primary graph is `{graph_id}` (inlined in `embodiment.yaml > graphs[0]`).\n\n" if graph_id else "")
        + "Worked examples mapping user requests to plans:\n\n"
        f"{_worked_examples_md(facts)}\n\n"
        "Planning rules:\n\n"
        "1. Check the active safety profile before planning any non-safe-class action.\n"
        "2. For motion-class actions: obtain explicit user confirmation in the current conversation scope.\n"
        "3. For manipulation-class actions: obtain confirmation + supervisor signoff before proceeding.\n"
        "4. Do not invent capabilities not in the node registry.\n"
        "5. Do not proceed past a failed readiness check.\n"
        "6. Report results tagged with any `unverified_*` codes where evidence is absent.\n\n"

        "## Forbidden actions\n\n"
        "Under the **active profile**, these actions must not be planned or executed:\n\n"
        + ("```text\n" + "\n".join(facts["forbidden_actions"]) + "\n```\n" if facts["forbidden_actions"] else "_None forbidden under this profile. Confirm + supervisor rules still apply to motion/manipulation._")
        + "\n\nIf the user requests a forbidden action, refuse and explain which profile would allow it.\n\n"

        "## Failure modes\n\n"
        "| Code | When it fires | Attribution |\n"
        "|---|---|---|\n"
        "| `node_missing` | Required node not in topology | topology |\n"
        "| `node_offline` | Node unreachable | hardware |\n"
        "| `capability_missing` | Node lacks required capability | configuration |\n"
        "| `forbidden_action_requested` | Task action is forbidden under active profile | planner |\n"
        "| `missing_confirmation` | Motion/manipulation planned without prior confirmation | planner |\n"
        "| `sensor_artifact_missing` | Frame/audio file not produced | sensor |\n"
        "| `unverified_audio_pickup` | Audio captured but RMS=0 | sensor |\n\n"

        "## Recovery\n\n"
        "Auto-recovery:\n\n"
        "- retry passive health check;\n"
        "- choose alternate observer;\n"
        "- downgrade multi-view to single-view.\n\n"
        "Requires explicit confirmation:\n\n"
        + "".join(f"- `{cls}`;\n" for cls in sorted(facts["active_profile"]["confirmation_classes"] | facts["active_profile"]["supervisor_classes"]))
        + (f"- any motion, any manipulation, audio output (default if no profile specified).\n" if not (facts["active_profile"]["confirmation_classes"] | facts["active_profile"]["supervisor_classes"]) else "")
        + "\nNot recoverable:\n\n"
        "- requests for a capability class that is forbidden under the active profile and the user refuses to switch profiles.\n\n"

        "## Runtime integration\n\n"
        "1. Parse this `EMBODIMENT.md` as planner-grounding context.\n"
        "2. Read `embodiment.yaml > registry.nodes` for the full device registry.\n"
        "3. Read `embodiment.yaml > graphs[0]` for the primary observation graph.\n"
        "4. Read `embodiment.yaml > safety.active_safety_profile` to confirm the active profile.\n"
        "5. Enforce the profile at the executor — check `forbidden_actions` + `requires_confirmation` before dispatch.\n"
        "6. Surface all failure codes verbatim in episode traces.\n"
    )


# ── LLM compose ───────────────────────────────────────────────────────────────

LLM_SYSTEM = (
    "You write SKILL.md-style embodiment context documents for a topology-based robot agent runtime.\n"
    "You MUST stay grounded in the structured facts provided. You MUST NOT:\n"
    " - invent capabilities not listed per node;\n"
    " - remove or rephrase any forbidden_action entry;\n"
    " - claim verified evidence absent from the facts;\n"
    " - turn a forbidden-class action into a safe action.\n"
    "Describe the FULL capability set of each node, including motion and manipulation, "
    "but clearly indicate which safety class each belongs to and what the active profile requires.\n"
    "Be concrete. Use real node ids. Show worked examples for sensor-only tasks AND motion/manipulation tasks.\n"
    "Output: one Markdown document with YAML frontmatter."
)

REQUIRED_SECTIONS = [
    "When to use",
    "When not to use",
    "Active safety profile",
    "Available nodes",
    "How to plan",
    "Forbidden actions",
    "Failure modes",
    "Recovery",
    "Runtime integration",
]

PROMOTION_PHRASES = [
    "can navigate freely", "can walk freely", "can grasp freely",
    "is safe to move without", "may walk without confirmation", "may grasp without confirmation",
    "manipulation is unrestricted",
]


def _llm_user_prompt(facts: Dict[str, Any], graph: Optional[Dict[str, Any]]) -> str:
    fm = {
        "name": facts["package_id"],
        "description": f"Embodiment context for {len(facts['included_nodes'])} device(s). Active profile: {facts['active_profile']['name']}.",
        "version": "0.3.0",
        "kind": "embodiment_context",
        "active_safety_profile": facts["active_profile"]["name"],
        "primary_graph": graph["graph_id"] if graph else "none",
    }
    nodes_for_llm = [
        {
            "id": n["id"],
            "name": n.get("name"),
            "node_type": n["node_type"],
            "role": _node_role(n),
            "all_capabilities": n.get("all_capabilities") or [],
            "safe_capabilities": n.get("safe_capabilities") or [],
            "capability_table": n.get("capability_table") or {},
            "sensors": n.get("sensors") or [],
            "limits": n.get("limits") or {},
            "real_device": n.get("real_device"),
            "image_path": n.get("image_path"),
            "last_rms": n.get("last_rms"),
            "evidence_excerpt": (n.get("evidence_excerpt") or "")[:600],
        }
        for n in facts["included_nodes"]
    ]
    facts_block = {
        "frontmatter_to_emit_verbatim": fm,
        "title": facts["title"],
        "active_profile": {
            "name": facts["active_profile"]["name"],
            "description": facts["active_profile"]["description"],
            "forbidden_classes": sorted(facts["active_profile"]["forbidden_classes"]),
            "confirmation_classes": sorted(facts["active_profile"]["confirmation_classes"]),
            "supervisor_classes": sorted(facts["active_profile"]["supervisor_classes"]),
        },
        "forbidden_actions_verbatim": facts["forbidden_actions"],
        "nodes": nodes_for_llm,
        "primary_graph": {"graph_id": graph["graph_id"], "intent": graph["intent"]} if graph else None,
        "required_sections_in_order": REQUIRED_SECTIONS,
        "required_examples": [
            "describe workspace (sensor/observe task)",
            "walk/navigate task (show confirmation requirement OR refusal with profile switch suggestion)",
            "pick/grasp task (show supervisor requirement OR refusal with profile switch suggestion)",
            "G1 + external camera collaboration (if both exist)",
        ],
    }
    return (
        "Compose EMBODIMENT.md from the structured facts below. "
        "Emit frontmatter exactly as `frontmatter_to_emit_verbatim`. "
        "Describe the FULL capability space of each node — including motion and manipulation — "
        "clearly tagged with their safety class and active profile status. "
        "Show how the user can change the profile at prompt time. "
        f"In `## Forbidden actions`, list every entry from `forbidden_actions_verbatim` verbatim in a fenced ```text``` block.\n\n"
        f"FACTS:\n```json\n{json.dumps(facts_block, ensure_ascii=False, indent=2)}\n```\n"
    )


def _load_llm_config(path: Path) -> Dict[str, Any]:
    cfg: Dict[str, Any] = {}
    if path.exists():
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            cfg = _load_yaml(path) or {}
    return {
        "api_base": os.getenv("OPENAI_API_BASE") or cfg.get("api_base"),
        "api_key": os.getenv("OPENAI_API_KEY") or cfg.get("api_key"),
        "model": os.getenv("OPENAI_MODEL") or cfg.get("model"),
    }


def _llm_call(cfg: Dict[str, Any], system: str, user: str, timeout: int = 120) -> str:
    body = json.dumps({"model": cfg["model"], "messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], "temperature": 0.2}).encode("utf-8")
    url = cfg["api_base"].rstrip("/") + "/chat/completions"
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + cfg["api_key"]},
                                 method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""


def _validate_md(text: str, facts: Dict[str, Any]) -> List[str]:
    reasons: List[str] = []
    for sec in REQUIRED_SECTIONS:
        if sec not in text:
            reasons.append(f"missing_section:{sec}")
    for action in facts["forbidden_actions"]:
        if not re.search(rf"\b{re.escape(action)}\b", text):
            reasons.append(f"forbidden_action_dropped:{action}")
    lower = text.lower()
    for phrase in PROMOTION_PHRASES:
        if phrase in lower:
            reasons.append(f"unsafe_promotion:{phrase}")
    if not text.lstrip().startswith("---"):
        reasons.append("missing_yaml_frontmatter")
    for n in facts["included_nodes"]:
        if n["id"] not in text:
            reasons.append(f"missing_node_id:{n['id']}")
    return reasons


# ── Package assembly ──────────────────────────────────────────────────────────

def _embodiment_yaml(facts: Dict[str, Any], graph: Optional[Dict[str, Any]],
                     registry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema": SCHEMA_PACKAGE,
        "package_id": facts["package_id"],
        "name": facts["title"],
        "version": "0.3.0",
        "kind": "embodiment_context",
        "license": "Apache-2.0",
        "summary": f"Embodiment context. Active safety profile: {facts['active_profile']['name']}.",
        "primary_agent_doc": "EMBODIMENT.md",
        "active_safety_profile": facts["active_profile"]["name"],
        "registry": registry,
        "graphs": [graph] if graph else [],
        "safety": {
            "active_safety_profile": facts["active_profile"]["name"],
            "default_policy": "sensor_only",
            "install_must_not_actuate": True,
            "requires_confirmation_for": sorted(facts["active_profile"]["confirmation_classes"] | facts["active_profile"]["supervisor_classes"]) or ["any_motion", "any_manipulation", "audio_output"],
            "forbidden_actions": facts["forbidden_actions"],
        },
        "integration": {
            "exposes_agent_context": True,
            "compatible_with": ["auwomo_physclaw", "openclaw_like_runtime"],
        },
        "generated": {
            "by": "embodiment_context_composer",
            "at": time.time(),
            "safety_profile_used": facts["active_profile"]["name"],
            "skipped_standalone_nodes": [s["id"] for s in facts["skipped_standalone"]],
        },
    }


def _resolve_mode(mode: str, llm_config: Path) -> Tuple[str, Dict[str, Any]]:
    cfg = _load_llm_config(llm_config) if llm_config.exists() else {}
    has_cfg = bool(cfg.get("api_base") and cfg.get("api_key") and cfg.get("model"))
    if mode == "deterministic":
        return "deterministic", {}
    if mode == "llm":
        if not has_cfg:
            raise SystemExit(f"--mode llm requires {llm_config} with api_base, api_key, and model")
        return "llm", cfg
    return ("llm", cfg) if has_cfg else ("deterministic", {})


def compose_and_write(snapshot: Dict[str, Any], policy: Dict[str, Any],
                      package_id: str, title: str, out_root: Path,
                      mode: str, llm_config: Path,
                      standalone_overrides: Optional[Set[str]] = None,
                      safety_profile_name: Optional[str] = None) -> Dict[str, Any]:
    class_map = _build_class_map(policy)
    profile_name = safety_profile_name or policy.get("default_safety_profile") or "sensor_only"
    active_profile = _build_profile(policy, profile_name)
    facts = _facts(snapshot, policy, package_id, title, active_profile, class_map,
                   standalone_overrides=standalone_overrides)
    graph = _primary_graph(facts)
    registry = _registry_inline(facts["included_nodes"])
    resolved_mode, cfg = _resolve_mode(mode, llm_config)
    deterministic_md = _deterministic_md(facts, graph)
    md = deterministic_md
    llm_status = "skipped"
    llm_rejection: List[str] = []
    if resolved_mode == "llm":
        try:
            candidate = _llm_call(cfg, LLM_SYSTEM, _llm_user_prompt(facts, graph))
            reasons = _validate_md(candidate, facts)
            if not reasons:
                md = candidate
                llm_status = "accepted"
            else:
                llm_status = "rejected"
                llm_rejection = reasons
        except Exception as exc:
            llm_status = f"error:{type(exc).__name__}"
            llm_rejection = [str(exc)]
    pkg_dir = out_root / package_id
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "EMBODIMENT.md").write_text(md, encoding="utf-8")
    (pkg_dir / "embodiment.yaml").write_text(
        yaml.safe_dump(_embodiment_yaml(facts, graph, registry), sort_keys=False, allow_unicode=True),
        encoding="utf-8")
    if llm_status not in {"accepted", "skipped"}:
        (pkg_dir / "LLM_REJECTED.json").write_text(
            json.dumps({"status": llm_status, "reasons": llm_rejection,
                        "model": cfg.get("model"),
                        "api_key_masked": _mask_key(cfg.get("api_key"))},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
    return {
        "ok": True,
        "package_id": package_id,
        "title": title,
        "mode_requested": mode,
        "mode_resolved": resolved_mode,
        "llm_status": llm_status,
        "safety_profile": profile_name,
        "included_nodes": [n["id"] for n in facts["included_nodes"]],
        "skipped_standalone_nodes": [s["id"] for s in facts["skipped_standalone"]],
        "graph_id": graph["graph_id"] if graph else None,
        "files": ["EMBODIMENT.md", "embodiment.yaml"]
                 + (["LLM_REJECTED.json"] if llm_status not in {"accepted", "skipped"} else []),
        "written": str(pkg_dir),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate one agent-readable embodiment context package from topology.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("preview", "generate"):
        p = sub.add_parser(name)
        p.add_argument("--topology", required=True)
        p.add_argument("--policy", default="embodiments/policies/default_safety_policy.yaml")
        p.add_argument("--package-id", default="current_lab_sensor_context")
        p.add_argument("--title", default=None)
        p.add_argument("--out", default="embodiments/generated")
        p.add_argument("--mode", choices=["auto", "deterministic", "llm"], default="auto")
        p.add_argument("--llm-config", default="hub/copaw_config.json")
        p.add_argument("--safety-profile",
                       choices=["sensor_only", "motion_supervised", "full_humanoid"],
                       default=None,
                       help="Safety profile to apply. Default: policy's default_safety_profile (sensor_only).")
        p.add_argument("--mark-standalone", action="append", default=[], metavar="NODE_ID",
                       help="Mark a node as standalone_only at compose time (repeatable).")
    args = ap.parse_args(argv)
    snapshot = _load_topology(Path(args.topology))
    policy = _load_yaml(Path(args.policy))
    title = args.title or args.package_id.replace("_", " ").title()
    pid = _slug(args.package_id)
    standalone_overrides = set(args.mark_standalone or [])
    class_map = _build_class_map(policy)
    profile_name = args.safety_profile or policy.get("default_safety_profile") or "sensor_only"
    active_profile = _build_profile(policy, profile_name)

    if args.cmd == "preview":
        facts = _facts(snapshot, policy, pid, title, active_profile, class_map, standalone_overrides=standalone_overrides)
        graph = _primary_graph(facts)
        resolved_mode, _ = _resolve_mode(args.mode, Path(args.llm_config))
        print(json.dumps({
            "ok": True, "package_id": pid, "title": title,
            "safety_profile": profile_name,
            "mode_requested": args.mode, "mode_resolved": resolved_mode,
            "included_nodes": [n["id"] for n in facts["included_nodes"]],
            "skipped_standalone_nodes": [s["id"] for s in facts["skipped_standalone"]],
            "user_marked_standalone": sorted(standalone_overrides),
            "graph_id": graph["graph_id"] if graph else None,
            "forbidden_actions": facts["forbidden_actions"],
        }, ensure_ascii=False, indent=2))
        return 0

    result = compose_and_write(snapshot, policy, pid, title, Path(args.out),
                               mode=args.mode, llm_config=Path(args.llm_config),
                               standalone_overrides=standalone_overrides,
                               safety_profile_name=profile_name)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

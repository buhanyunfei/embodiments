#!/usr/bin/env python3
"""Embodiment context composer v3.

Generates agent-readable embodiment context packages from a topology snapshot.
Deterministic-first: all structural output (graphs, tool interfaces, cooperation)
is generated deterministically. LLM is optional prose-enhancement only.

Output (slim layout):
    <out>/<package_id>/
      EMBODIMENT.md       agent-readable context (SKILL.md-style)
      embodiment.yaml     runtime-readable (registry + graphs + cooperation)

New in v3:
  - Two-layer graph architecture (cooperation network + execution network)
  - Agent nodes (llm_agent, human_operator) as first-class participants
  - Tool interfaces per node
  - Multiple graphs per package (intent-matched)
  - Execution workflows with ordering semantics
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

# ── Constants ────────────────────────────────────────────────────────────────

SAFE_DEFAULT = ["observe", "inspect", "listen", "perceive", "wait", "standby", "health_check"]
MOTION_DEFAULT = ["walk", "turn", "navigate", "move", "whole_body_motion", "follow", "patrol"]
MANIPULATION_DEFAULT = ["reach", "grasp", "pick", "place", "carry", "hand_over", "open_door",
                        "arm_motion", "hand_motion", "push", "pull"]
AUDIO_OUTPUT_DEFAULT = ["audio_output", "speak", "play_sound"]
AGENT_SAFE_DEFAULT = ["plan", "reason", "describe", "approve", "supervise", "override", "rollback"]

OBSERVER_NODE_TYPES_DEFAULT = ["physical_robot", "sensor", "camera", "microphone", "agent_node"]
SCHEMA_PACKAGE = "embodiment_package/v3"
SCHEMA_PACKAGE_V2 = "embodiment_package/v2"
SCHEMA_GRAPH = "embodiment_graph/v3"
SCHEMA_REGISTRY = "embodiment_node_registry/v2"


# ── Helpers ──────────────────────────────────────────────────────────────────

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


# ── Capability Classification ────────────────────────────────────────────────

def _build_class_map(policy: Dict[str, Any]) -> Dict[str, str]:
    raw = policy.get("capability_classes") or {}
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
    for action in AGENT_SAFE_DEFAULT:
        m.setdefault(action, "safe")
    return m


def _build_profile(policy: Dict[str, Any], profile_name: str) -> Dict[str, Any]:
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
    cls = class_map.get(action, "unknown")
    if cls in profile["forbidden_classes"]:
        return "forbidden"
    if cls in profile["supervisor_classes"]:
        return "supervisor"
    if cls in profile["confirmation_classes"]:
        return "confirmation"
    if cls in profile["allowed_classes"]:
        return "safe"
    return "confirmation"


def _forbidden_actions(all_caps: List[str], class_map: Dict[str, str], profile: Dict[str, Any]) -> List[str]:
    return sorted(a for a in all_caps if _capability_status(a, class_map, profile) == "forbidden")


def _safe_actions(all_caps: List[str], class_map: Dict[str, str], profile: Dict[str, Any]) -> List[str]:
    return sorted(a for a in all_caps if _capability_status(a, class_map, profile) == "safe")


# ── Node Normalization ───────────────────────────────────────────────────────

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
        all_caps = list(dict.fromkeys(
            (n.get("capabilities") or [])
            + (profile.get("capabilities") or [])
            + (profile.get("action_space") or [])
        ))
        sensors = profile.get("sensors") or meta.get("sensors") or []
        if sensors:
            all_caps.append("observe")
        all_caps = list(dict.fromkeys(all_caps))
        safe_collab = sorted(c for c in all_caps if c in safe_collab_set)
        limits = profile.get("limits") or meta.get("limits") or {}
        coll = meta.get("collaboration_policy") or profile.get("collaboration_policy") or {}
        nid = n.get("id") or n.get("node_id")
        forced_standalone = nid in standalone_overrides
        node_type = n.get("node_type") or meta.get("node_type") or "unknown"

        node = {
            "id": nid,
            "name": n.get("name") or nid,
            "node_type": node_type,
            "participant_type": _infer_participant_type(node_type),
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
            "tool_interface": meta.get("tool_interface") or profile.get("tool_interface"),
        }
        if node["id"]:
            out.append(node)
    return out


def _infer_participant_type(node_type: str) -> str:
    if node_type in ("physical_robot", "actuator"):
        return "robot_node"
    if node_type in ("sensor", "camera", "microphone"):
        return "sensor_node"
    if node_type in ("perception_model", "agent_node", "llm_agent", "human_operator"):
        return "agent_node"
    return "sensor_node"


def _node_role(n: Dict[str, Any]) -> str:
    nid = (n.get("id") or "").lower()
    node_type = (n.get("node_type") or "").lower()
    caps = set(n.get("all_capabilities") or [])
    sensors = set(s.lower() for s in (n.get("sensors") or []))
    if node_type in ("llm_agent", "agent_node") or n.get("participant_type") == "agent_node":
        if "approve" in caps or "supervise" in caps:
            return "supervisor"
        return "planner"
    if node_type == "physical_robot":
        return "robot_local_view"
    if "mic" in nid or sensors == {"microphone"} or caps == {"listen"}:
        return "audio_input"
    if "realsense" in nid or n.get("parent_robot"):
        return "robot_local_view"
    if "camera" in nid or "perceive" in caps or "observe" in caps:
        return "external_view"
    return "support_node"


def _select_nodes(nodes: List[Dict[str, Any]], policy: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    allowed = set(policy.get("observer_node_types") or OBSERVER_NODE_TYPES_DEFAULT)
    included, skipped = [], []
    for n in nodes:
        if n["standalone_only"]:
            skipped.append({"id": n["id"], "reason": n.get("standalone_reason") or "standalone_only"})
            continue
        if n["node_type"] not in allowed and n["participant_type"] != "agent_node":
            continue
        if not n["all_capabilities"] and not n["safe_capabilities"]:
            continue
        included.append(n)
    return included, skipped


# ── Agent Node Injection ─────────────────────────────────────────────────────

def _inject_agent_nodes(nodes: List[Dict[str, Any]], profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Add standard llm_planner and human_operator nodes if not already present."""
    ids = {n["id"] for n in nodes}

    if "llm_planner" not in ids:
        nodes.append({
            "id": "llm_planner",
            "name": "LLM Planning Agent",
            "node_type": "agent_node",
            "participant_type": "agent_node",
            "agent_subtype": "llm_agent",
            "all_capabilities": ["plan", "reason", "describe"],
            "safe_capabilities": ["plan", "reason", "describe"],
            "sensors": [],
            "limits": {},
            "endpoint": None,
            "agent_ref": None,
            "parent_robot": None,
            "standalone_only": False,
            "standalone_reason": None,
            "evidence_excerpt": "",
            "image_path": None,
            "last_rms": None,
            "real_device": False,
            "tool_interface": {
                "protocol": "tool_call",
                "endpoint": None,
                "operations": [
                    {
                        "operation_id": "generate_plan",
                        "description": "Generate an execution plan for a physical task",
                        "input_schema": {"type": "object", "properties": {"task": {"type": "string"}, "constraints": {"type": "object"}}, "required": ["task"]},
                        "output_schema": {"type": "object", "properties": {"plan_steps": {"type": "array"}, "confidence": {"type": "number"}}},
                        "latency_estimate_ms": 3000,
                        "safety_class": "safe",
                    },
                    {
                        "operation_id": "describe_scene",
                        "description": "Describe the current scene from provided frames",
                        "input_schema": {"type": "object", "properties": {"frame_paths": {"type": "array", "items": {"type": "string"}}}, "required": ["frame_paths"]},
                        "output_schema": {"type": "object", "properties": {"description": {"type": "string"}}},
                        "latency_estimate_ms": 2000,
                        "safety_class": "safe",
                    },
                ],
            },
        })

    if "human_operator" not in ids:
        nodes.append({
            "id": "human_operator",
            "name": "Human Operator",
            "node_type": "agent_node",
            "participant_type": "agent_node",
            "agent_subtype": "human_operator",
            "all_capabilities": ["approve", "supervise", "override", "rollback"],
            "safe_capabilities": ["approve", "supervise", "override", "rollback"],
            "sensors": [],
            "limits": {},
            "endpoint": None,
            "agent_ref": None,
            "parent_robot": None,
            "standalone_only": False,
            "standalone_reason": None,
            "evidence_excerpt": "",
            "image_path": None,
            "last_rms": None,
            "real_device": False,
            "tool_interface": {
                "protocol": "tool_call",
                "endpoint": None,
                "operations": [
                    {
                        "operation_id": "request_approval",
                        "description": "Request human approval for a gated action",
                        "input_schema": {"type": "object", "properties": {"action": {"type": "string"}, "context": {"type": "string"}, "risk_level": {"type": "string", "enum": ["low", "medium", "high"]}}, "required": ["action", "context"]},
                        "output_schema": {"type": "object", "properties": {"approved": {"type": "boolean"}, "reason": {"type": "string"}}},
                        "latency_estimate_ms": None,
                        "safety_class": "safe",
                    },
                    {
                        "operation_id": "provide_feedback",
                        "description": "Human provides feedback or correction to the system",
                        "input_schema": {"type": "object", "properties": {"feedback": {"type": "string"}, "target_node": {"type": "string"}}},
                        "output_schema": {"type": "object", "properties": {"acknowledged": {"type": "boolean"}}},
                        "latency_estimate_ms": None,
                        "safety_class": "safe",
                    },
                ],
            },
        })

    return nodes


# ── Cooperation Network ──────────────────────────────────────────────────────

def _load_cooperation_policy(path: Optional[Path]) -> Dict[str, Any]:
    if path and path.exists():
        return _load_yaml(path)
    return {"schema": "cooperation_policy/v1", "default_approval": "approved", "pairs": []}


def _resolve_cooperation(nodes: List[Dict[str, Any]], coop_policy: Dict[str, Any]) -> Dict[str, Any]:
    """Compute effective cooperation state for all node pairs."""
    default = coop_policy.get("default_approval", "approved")
    pairs = coop_policy.get("pairs") or []
    pair_map: Dict[Tuple[str, str], str] = {}
    for p in pairs:
        pair_map[(p["source"], p["target"])] = p.get("approval", default)
        pair_map[(p["target"], p["source"])] = p.get("approval", default)

    node_ids = [n["id"] for n in nodes]
    computed = []
    for i, a in enumerate(node_ids):
        for b in node_ids[i + 1:]:
            key = (a, b)
            rev_key = (b, a)
            if key in pair_map:
                approval = pair_map[key]
                source_is = "policy_override"
            elif rev_key in pair_map:
                approval = pair_map[rev_key]
                source_is = "policy_override"
            else:
                approval = default
                source_is = "policy_default"
            computed.append({"source": a, "target": b, "approval": approval, "source_is": source_is})

    return {
        "policy_ref": "cooperation_policy.yaml",
        "default_approval": default,
        "runtime_override_enabled": True,
        "rollback_target": "policy_file",
        "computed_pairs": computed,
    }


def _is_cooperation_approved(source: str, target: str, coop_state: Dict[str, Any]) -> bool:
    for p in coop_state.get("computed_pairs", []):
        if (p["source"] == source and p["target"] == target) or \
           (p["source"] == target and p["target"] == source):
            return p["approval"] == "approved"
    return coop_state.get("default_approval", "approved") == "approved"


# ── Graph Generation (Multi-Graph, Two-Layer) ────────────────────────────────

def _build_workflows(facts: Dict[str, Any], coop_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate lightweight workflow index entries based on available nodes and safety profile."""
    workflows = []

    observers = facts["observers"]
    audio = facts["audio_listeners"]
    robots = facts["robots"]
    profile = facts["active_profile"]
    included = facts["included_nodes"]

    if observers or audio:
        primary = [n["id"] for n in observers[:4]]
        primary += ["llm_planner", "human_operator"]
        workflows.append({
            "id": "scene_observation",
            "description": "Observe and describe the environment using available sensors with human-gated cooperation.",
            "trigger_keywords": ["describe", "observe", "see", "look", "view", "scene", "workspace", "what"],
            "safety_level": profile["name"],
            "primary_nodes": primary,
        })

    if robots and "motion" not in profile["forbidden_classes"]:
        workflows.append({
            "id": "motion_with_confirmation",
            "description": "Execute robot locomotion with explicit human confirmation before each motion command.",
            "trigger_keywords": ["walk", "move", "go", "navigate", "patrol", "forward", "backward", "turn"],
            "safety_level": profile["name"],
            "primary_nodes": [robots[0]["id"], "llm_planner", "human_operator"],
        })

    if included:
        hardware = [n["id"] for n in included if n["participant_type"] != "agent_node"]
        workflows.append({
            "id": "sensor_health_audit",
            "description": "Check connectivity and readiness of all hardware nodes.",
            "trigger_keywords": ["health", "status", "check", "ready", "online", "connectivity", "audit"],
            "safety_level": "sensor_only",
            "primary_nodes": hardware + ["llm_planner"],
        })

    return workflows



# ── Registry Assembly ────────────────────────────────────────────────────────

def _registry_inline(included: List[Dict[str, Any]]) -> Dict[str, Any]:
    nodes = []
    for n in included:
        entry: Dict[str, Any] = {
            "id": n["id"],
            "name": n.get("name"),
            "node_type": n["node_type"],
            "participant_type": n.get("participant_type", _infer_participant_type(n["node_type"])),
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
        if n.get("participant_type") == "agent_node":
            entry["agent_subtype"] = n.get("agent_subtype", "llm_agent")
        if n.get("tool_interface"):
            entry["tool_interface"] = n["tool_interface"]
        nodes.append(entry)
    return {"schema": SCHEMA_REGISTRY, "nodes": nodes}


# ── Facts ────────────────────────────────────────────────────────────────────

def _facts(snapshot: Dict[str, Any], policy: Dict[str, Any], package_id: str, title: str,
           active_profile: Dict[str, Any], class_map: Dict[str, str],
           standalone_overrides: Optional[Set[str]] = None,
           include_agent_nodes: bool = True) -> Dict[str, Any]:
    nodes_all = _normalize_nodes(snapshot, policy, standalone_overrides=standalone_overrides)
    included, skipped = _select_nodes(nodes_all, policy)

    if include_agent_nodes:
        included = _inject_agent_nodes(included, active_profile)

    for n in included:
        n["capability_table"] = {
            cap: {"class": class_map.get(cap, "unknown"), "status": _capability_status(cap, class_map, active_profile)}
            for cap in n["all_capabilities"]
        }

    all_node_caps = list(dict.fromkeys(c for n in included for c in n["all_capabilities"]))
    observers = [n for n in included if "observe" in n.get("all_capabilities", []) or "perceive" in n.get("all_capabilities", [])]
    audio = [n for n in included if "listen" in n.get("all_capabilities", [])]
    robots = [n for n in included if n.get("node_type") == "physical_robot"]

    forbidden = _forbidden_actions(all_node_caps, class_map, active_profile)
    # Ensure standard forbidden actions are always listed for restrictive profiles
    if "motion" in active_profile["forbidden_classes"]:
        forbidden = sorted(set(forbidden) | set(MOTION_DEFAULT))
    if "manipulation" in active_profile["forbidden_classes"]:
        forbidden = sorted(set(forbidden) | set(MANIPULATION_DEFAULT))
    if "audio_output" in active_profile["forbidden_classes"]:
        forbidden = sorted(set(forbidden) | set(AUDIO_OUTPUT_DEFAULT))
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


# ── EMBODIMENT.md Generation (Deterministic, v3) ─────────────────────────────

def _tool_interface_md(nodes: List[Dict[str, Any]]) -> str:
    lines = []
    for n in nodes:
        ti = n.get("tool_interface")
        if not ti or not ti.get("operations"):
            continue
        lines.append(f"### `{n['id']}` tools")
        lines.append("")
        lines.append("| Operation | Protocol | Endpoint | Latency | Safety Class |")
        lines.append("|-----------|----------|----------|---------|--------------|")
        for op in ti["operations"]:
            endpoint = ""
            if ti.get("protocol") == "http" and op.get("method") and op.get("path"):
                endpoint = f"{op['method']} {op['path']}"
            elif ti.get("protocol") == "tool_call":
                endpoint = "tool_call"
            latency = f"~{op['latency_estimate_ms']}ms" if op.get("latency_estimate_ms") else "variable"
            lines.append(f"| `{op['operation_id']}` | {ti['protocol']} | {endpoint} | {latency} | {op.get('safety_class', 'safe')} |")
        lines.append("")
    return "\n".join(lines) if lines else "_No tool interfaces declared._"


def _cooperation_boundaries_md(coop_state: Dict[str, Any]) -> str:
    active = [p for p in coop_state.get("computed_pairs", []) if p["approval"] == "approved"]
    dormant = [p for p in coop_state.get("computed_pairs", []) if p["approval"] != "approved"]

    lines = ["### Active cooperation"]
    if active:
        lines += ["", "| Source | Target | Approved By |", "|--------|--------|-------------|"]
        for p in active[:20]:
            lines.append(f"| `{p['source']}` | `{p['target']}` | {p['source_is']} |")
    else:
        lines.append("\n_No active cooperation pairs._")

    lines += ["", "### Dormant cooperation (revoked or pending)"]
    if dormant:
        lines += ["", "| Source | Target | Status | Reason |", "|--------|--------|--------|--------|"]
        for p in dormant:
            lines.append(f"| `{p['source']}` | `{p['target']}` | {p['approval']} | — |")
    else:
        lines.append("\n_None — all pairs are active._")

    lines += ["", "### Rollback", "", "To reset all runtime overrides: call `cooperation.rollback()`. Restores policy file defaults atomically."]
    return "\n".join(lines)


def _execution_workflows_md(facts: Dict[str, Any]) -> str:
    lines = []
    observers = facts["observers"]
    robots = facts["robots"]
    profile = facts["active_profile"]

    locals_ = [n for n in observers if _node_role(n) == "robot_local_view"]
    externals = [n for n in observers if _node_role(n) == "external_view"]

    # Workflow 1: Observation
    if observers:
        lines.append("### Workflow: Scene observation")
        step = 1
        if locals_ and externals:
            lines.append(f"{step}. [parallel] `capture_frame` → `{locals_[0]['id']}` ({_proto(locals_[0])}, ~200ms)")
            step += 1
            lines.append(f"{step}. [parallel] `capture_frame` → `{externals[0]['id']}` ({_proto(externals[0])}, ~100ms)")
            step += 1
        elif observers:
            lines.append(f"{step}. [serial] `capture_frame` → `{observers[0]['id']}` ({_proto(observers[0])}, ~200ms)")
            step += 1
        lines.append(f"{step}. [serial] send frames → `perception_vision` (local, ~2000ms)")
        step += 1
        lines.append(f"{step}. [serial] return description → `llm_planner`")
        lines.append("")

    # Workflow 2: Motion (if not forbidden)
    if robots and "motion" not in profile["forbidden_classes"]:
        lines.append("### Workflow: Motion with confirmation")
        lines.append("1. [serial] `llm_planner` → `request_approval` → `human_operator`")
        lines.append("2. [conditional: approved] send `motion_command` → `" + robots[0]["id"] + "` (http, ~50ms)")
        lines.append("3. [conditional: denied] report denial, suggest alternative")
        lines.append("4. [serial] monitor via observers during motion")
        lines.append("")

    # Workflow 3: Health check
    hardware = [n for n in facts["included_nodes"] if n["participant_type"] != "agent_node"]
    if hardware:
        lines.append("### Workflow: Health audit")
        lines.append(f"1. [parallel] `health_check` → all {len(hardware)} hardware nodes (~100ms each)")
        lines.append("2. [serial] aggregate results → `llm_planner`")
        lines.append("3. [serial] report status to user")
        lines.append("")

    return "\n".join(lines) if lines else "_No workflows available._"


def _proto(n: Dict[str, Any]) -> str:
    return "http" if n.get("endpoint") else "local"


def _frontmatter(facts: Dict[str, Any], workflows: List[Dict[str, Any]]) -> str:
    fm = {
        "name": facts["package_id"],
        "description": (
            f"Embodiment context for {len(facts['included_nodes'])} node(s). "
            f"Active profile: {facts['active_profile']['name']}."
        ),
        "version": "0.4.0",
        "kind": "embodiment_context",
        "active_safety_profile": facts["active_profile"]["name"],
        "workflows": [w["id"] for w in workflows],
    }
    return "---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).rstrip() + "\n---\n"


def _node_block_v3(n: Dict[str, Any]) -> str:
    role = _node_role(n)
    lines = [f"### `{n['id']}` — {n.get('name') or n['id']}"]
    lines.append(f"- Type: `{n['node_type']}` · Participant: `{n.get('participant_type', 'unknown')}` · Role: `{role}`")
    if n.get("agent_subtype"):
        lines.append(f"- Agent subtype: `{n['agent_subtype']}`")
    if n.get("sensors"):
        lines.append(f"- Sensors: `{', '.join(n['sensors'])}`")
    if n.get("limits") and any(v for v in n["limits"].values()):
        lines.append(f"- Limits: `{json.dumps(n['limits'], ensure_ascii=False)}`")
    if n.get("image_path"):
        lines.append(f"- Last sensor artifact: `{n['image_path']}`")
    if n.get("last_rms") is not None:
        rms = n["last_rms"]
        tag = "verified" if rms not in (0, None) else "unverified (RMS=0)"
        lines.append(f"- Last audio RMS: `{rms}` ({tag})")
    safe = n.get("safe_capabilities") or []
    if safe:
        lines.append(f"- Safe capabilities: `{', '.join(safe)}`")
    return "\n".join(lines)


def _profile_summary_md(facts: Dict[str, Any]) -> str:
    p = facts["active_profile"]
    lines = [
        f"Active profile: **`{p['name']}`** — {p['description'].strip()}",
        "",
        "| class | behavior under this profile |",
        "|---|---|",
    ]
    for cls in ["safe", "motion", "manipulation", "audio_output"]:
        if cls in p["forbidden_classes"]:
            behavior = "**forbidden**"
        elif cls in p["supervisor_classes"]:
            behavior = "requires supervisor + confirmation"
        elif cls in p["confirmation_classes"]:
            behavior = "requires confirmation"
        elif cls in p["allowed_classes"]:
            behavior = "plan freely"
        else:
            behavior = "requires confirmation"
        lines.append(f"| `{cls}` | {behavior} |")
    return "\n".join(lines)


def _workflow_selection_md(workflows: List[Dict[str, Any]]) -> str:
    lines = ["The agent selects the appropriate workflow by matching user intent to trigger keywords:", ""]
    lines.append("| Workflow ID | Intent | Trigger Keywords |")
    lines.append("|-------------|--------|------------------|")
    for w in workflows:
        kw = ", ".join(w.get("trigger_keywords", [])[:5])
        lines.append(f"| `{w['id']}` | {w['description'][:80]} | {kw} |")
    return "\n".join(lines)


def _deterministic_md_v3(facts: Dict[str, Any], workflows: List[Dict[str, Any]], coop_state: Dict[str, Any]) -> str:
    nodes_block = "\n\n".join(_node_block_v3(n) for n in facts["included_nodes"]) or "_No eligible nodes._"
    profile = facts["active_profile"]
    observers = facts["observers"]
    robots = facts["robots"]
    locals_ = [n for n in observers if _node_role(n) == "robot_local_view"]
    externals = [n for n in observers if _node_role(n) == "external_view"]

    # Worked examples
    examples = []
    if locals_ and externals:
        examples.append(
            f'1. "Describe the workspace from both angles."\n'
            f'   → Select workflow `scene_observation`. Call `{locals_[0]["id"]}.capture_frame` and '
            f'`{externals[0]["id"]}.capture_frame` in parallel. Send both to `perception_vision.describe_scene`. Return fused description.'
        )
    elif observers:
        examples.append(
            f'1. "What do you see?"\n'
            f'   → Select workflow `scene_observation`. Call `{observers[0]["id"]}.capture_frame`. Describe result.'
        )
    if robots and "motion" not in profile["forbidden_classes"]:
        examples.append(
            f'{len(examples)+1}. "Walk forward 1 meter."\n'
            f'   → Select workflow `motion_with_confirmation`. Call `human_operator.request_approval(action="walk 1m forward")`. '
            f'If approved, dispatch motion command to `{robots[0]["id"]}`. Monitor via observers.'
        )
    elif robots:
        examples.append(
            f'{len(examples)+1}. "Walk forward 1 meter."\n'
            f'   → **REFUSE** — `walk` is forbidden under `{profile["name"]}`. Suggest switching to `motion_supervised` profile.'
        )
    examples.append(
        f'{len(examples)+1}. "Check if all sensors are online."\n'
        f'   → Select workflow `sensor_health_audit`. Call `health_check` on all hardware nodes in parallel. Report status.'
    )

    md = (
        _frontmatter(facts, workflows)
        + f"\n# {facts['title']}\n\n"
        "This is the agent's primary instruction for this embodiment context. "
        "Read it like a `SKILL.md`. It describes available hardware, software agents, "
        "their tool interfaces, cooperation boundaries, and execution workflows.\n\n"

        "## When to use\n\n"
        f"Use when the task involves the {len(facts['included_nodes'])} node(s) listed below. "
        "This is real hardware and real agent infrastructure — never substitute mocks.\n\n"

        "## When not to use\n\n"
        "Do not use for tasks requiring capabilities absent from the registry, "
        "when critical nodes are offline with no fallback, or when all cooperation paths to a target are dormant.\n\n"

        "## Active safety profile\n\n"
        f"{_profile_summary_md(facts)}\n\n"

        "## Available nodes\n\n"
        f"{nodes_block}\n\n"

        "## Tool interfaces\n\n"
        f"{_tool_interface_md(facts['included_nodes'])}\n\n"

        "## Cooperation boundaries\n\n"
        f"{_cooperation_boundaries_md(coop_state)}\n\n"

        "## Execution workflows\n\n"
        f"{_execution_workflows_md(facts)}\n\n"

        "## How to plan\n\n"
        f"{_workflow_selection_md(workflows)}\n\n"
        "### Worked examples\n\n"
        + "\n\n".join(examples) + "\n\n"
        "### Planning rules\n\n"
        "1. Match user intent to workflow via `trigger_keywords`.\n"
        "2. Check cooperation boundaries — do not plan through dormant edges.\n"
        "3. Check safety profile before any non-safe action.\n"
        "4. For confirmation-class actions: route through `human_operator.request_approval`.\n"
        "5. Do not invent capabilities not in the registry.\n"
        "6. Use tool interfaces for concrete execution — generate actual tool calls.\n\n"

        "## Forbidden actions\n\n"
        + ("```text\n" + "\n".join(facts["forbidden_actions"]) + "\n```\n" if facts["forbidden_actions"] else "_None forbidden under this profile._")
        + "\n\n"

        "## Failure modes\n\n"
        "| Code | When it fires | Attribution |\n"
        "|---|---|---|\n"
        "| `node_missing` | Required node not in topology | topology |\n"
        "| `node_offline` | Node unreachable | hardware |\n"
        "| `cooperation_denied` | Edge is dormant (cooperation revoked) | cooperation_policy |\n"
        "| `forbidden_action_requested` | Action forbidden under active profile | planner |\n"
        "| `approval_timeout` | Human did not respond | human_operator |\n"
        "| `sensor_artifact_missing` | Frame/audio not produced | sensor |\n\n"

        "## Recovery\n\n"
        "**Auto-recovery**: retry health check, choose alternate observer, downgrade multi-view, use alternate non-dormant path.\n\n"
        "**Requires confirmation**: " + ", ".join(sorted(profile["confirmation_classes"] | profile["supervisor_classes"]) or ["motion", "manipulation"]) + ".\n\n"
        "**Not recoverable**: missing executor, all cooperation paths dormant.\n\n"

        "## Runtime integration\n\n"
        "1. Mount this package via the agent system's embodiment loader.\n"
        "2. Context: inject this `EMBODIMENT.md` into the agent's planning context.\n"
        "3. Tools: register all `tool_interface.operations` (non-forbidden) as callable tools.\n"
        "4. Cooperation: enforce cooperation boundaries before tool dispatch.\n"
        "5. Safety: check `forbidden_actions` + `requires_confirmation` at the executor.\n"
        "6. Rollback: `cooperation.rollback()` resets to policy file defaults.\n"
    )
    return md


# ── LLM Enhancement (Optional, Prose-Only) ──────────────────────────────────

LLM_SYSTEM = (
    "You enhance the prose quality of an embodiment context document. "
    "You receive a complete, structurally correct EMBODIMENT.md and improve its readability. "
    "You MUST NOT:\n"
    " - add, remove, or reorder sections;\n"
    " - invent capabilities not in the tool interfaces;\n"
    " - remove or rephrase any forbidden_action entry;\n"
    " - alter cooperation boundaries or workflow steps;\n"
    " - change YAML frontmatter.\n"
    "Only improve descriptions, add helpful context to worked examples, "
    "and make the language clearer for an LLM agent reader."
)

REQUIRED_SECTIONS_V3 = [
    "When to use", "When not to use", "Active safety profile",
    "Available nodes", "Tool interfaces", "Cooperation boundaries",
    "Execution workflows", "How to plan", "Forbidden actions",
    "Failure modes", "Recovery", "Runtime integration",
]


def _validate_md_v3(text: str, facts: Dict[str, Any]) -> List[str]:
    reasons: List[str] = []
    for sec in REQUIRED_SECTIONS_V3:
        if sec not in text:
            reasons.append(f"missing_section:{sec}")
    for action in facts["forbidden_actions"]:
        if not re.search(rf"\b{re.escape(action)}\b", text):
            reasons.append(f"forbidden_action_dropped:{action}")
    if not text.lstrip().startswith("---"):
        reasons.append("missing_yaml_frontmatter")
    for n in facts["included_nodes"]:
        if n["id"] not in text:
            reasons.append(f"missing_node_id:{n['id']}")
    return reasons


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


# ── Package Assembly ─────────────────────────────────────────────────────────

def _embodiment_yaml(facts: Dict[str, Any], workflows: List[Dict[str, Any]],
                     registry: Dict[str, Any], coop_state: Dict[str, Any],
                     schema_version: str = "v3") -> Dict[str, Any]:
    profile = facts["active_profile"]
    schema = SCHEMA_PACKAGE if schema_version == "v3" else SCHEMA_PACKAGE_V2

    pkg: Dict[str, Any] = {
        "schema": schema,
        "package_id": facts["package_id"],
        "name": facts["title"],
        "version": "0.4.0",
        "kind": "embodiment_context",
        "license": "Apache-2.0",
        "summary": f"Embodiment context. Profile: {profile['name']}.",
        "primary_agent_doc": "EMBODIMENT.md",
        "active_safety_profile": profile["name"],
        "registry": registry,
        "cooperation_network": {
            "policy_ref": coop_state.get("policy_ref", "policies/default_cooperation_policy.yaml"),
            "default_approval": coop_state.get("default_approval", "approved"),
            "runtime_override_enabled": True,
            "rollback_target": "policy_file",
        },
        "workflows": workflows,
        "safety": {
            "active_safety_profile": profile["name"],
            "default_policy": "sensor_only",
            "install_must_not_actuate": True,
            "requires_confirmation_for": sorted(profile["confirmation_classes"] | profile["supervisor_classes"]) or ["any_motion", "any_manipulation", "audio_output"],
            "forbidden_actions": facts["forbidden_actions"],
        },
        "integration": {
            "capabilities": ["context_v3", "tools_v1", "cooperation_v1"],
            "compatible_runtimes": ["codex>=0.4", "openclaw>=1.0", "auwomo_physclaw>=0.4"],
            "context_injection": {"target": "system_prompt"},
            "tool_registration": {"format": "openai_function", "auto_register": True, "respect_dormant": True},
        },
        "generated": {
            "by": "embodiment_context_composer",
            "version": "0.4.0",
            "at": time.time(),
            "safety_profile_used": profile["name"],
            "schema_version": schema_version,
            "skipped_standalone_nodes": [s["id"] for s in facts["skipped_standalone"]],
        },
    }
    return pkg


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


# ── Main Compose Function ────────────────────────────────────────────────────

def compose_and_write(snapshot: Dict[str, Any], policy: Dict[str, Any],
                      package_id: str, title: str, out_root: Path,
                      mode: str, llm_config: Path,
                      cooperation_policy_path: Optional[Path] = None,
                      standalone_overrides: Optional[Set[str]] = None,
                      safety_profile_name: Optional[str] = None,
                      include_agent_nodes: bool = True,
                      schema_version: str = "v3") -> Dict[str, Any]:
    class_map = _build_class_map(policy)
    profile_name = safety_profile_name or policy.get("default_safety_profile") or "sensor_only"
    active_profile = _build_profile(policy, profile_name)

    facts = _facts(snapshot, policy, package_id, title, active_profile, class_map,
                   standalone_overrides=standalone_overrides,
                   include_agent_nodes=include_agent_nodes)

    coop_policy = _load_cooperation_policy(cooperation_policy_path)
    coop_state = _resolve_cooperation(facts["included_nodes"], coop_policy)

    workflows = _build_workflows(facts, coop_state)
    registry = _registry_inline(facts["included_nodes"])

    resolved_mode, cfg = _resolve_mode(mode, llm_config)
    deterministic_md = _deterministic_md_v3(facts, workflows, coop_state)
    md = deterministic_md
    llm_status = "skipped"
    llm_rejection: List[str] = []

    if resolved_mode == "llm":
        try:
            candidate = _llm_call(cfg, LLM_SYSTEM, f"Enhance this document:\n\n{deterministic_md}")
            reasons = _validate_md_v3(candidate, facts)
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
        yaml.safe_dump(_embodiment_yaml(facts, workflows, registry, coop_state, schema_version),
                       sort_keys=False, allow_unicode=True),
        encoding="utf-8")

    if cooperation_policy_path and cooperation_policy_path.exists():
        import shutil
        shutil.copy2(cooperation_policy_path, pkg_dir / "cooperation_policy.yaml")

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
        "schema_version": schema_version,
        "included_nodes": [n["id"] for n in facts["included_nodes"]],
        "skipped_standalone_nodes": [s["id"] for s in facts["skipped_standalone"]],
        "workflows": [w["id"] for w in workflows],
        "cooperation_default": coop_state.get("default_approval"),
        "files": ["EMBODIMENT.md", "embodiment.yaml"]
                 + (["cooperation_policy.yaml"] if cooperation_policy_path else [])
                 + (["LLM_REJECTED.json"] if llm_status not in {"accepted", "skipped"} else []),
        "written": str(pkg_dir),
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate agent-readable embodiment context packages from topology (v3).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("preview", "generate"):
        p = sub.add_parser(name)
        p.add_argument("--topology", required=True)
        p.add_argument("--policy", default="embodiments/policies/default_safety_policy.yaml")
        p.add_argument("--cooperation-policy", default=None,
                       help="Path to cooperation policy YAML. Default: all pairs approved.")
        p.add_argument("--package-id", default="current_lab_sensor_context")
        p.add_argument("--title", default=None)
        p.add_argument("--out", default="embodiments/generated")
        p.add_argument("--mode", choices=["auto", "deterministic", "llm"], default="auto")
        p.add_argument("--llm-config", default="hub/copaw_config.json")
        p.add_argument("--safety-profile",
                       choices=["sensor_only", "motion_supervised", "full_humanoid"],
                       default=None)
        p.add_argument("--schema-version", choices=["v2", "v3"], default="v3",
                       help="Output schema version. v2 for backward compat, v3 for full two-layer graph.")
        p.add_argument("--include-agent-nodes", action="store_true", default=True,
                       help="Auto-inject llm_planner and human_operator agent nodes.")
        p.add_argument("--no-agent-nodes", action="store_true", default=False,
                       help="Do not inject agent nodes.")
        p.add_argument("--mark-standalone", action="append", default=[], metavar="NODE_ID")

    args = ap.parse_args(argv)
    snapshot = _load_topology(Path(args.topology))
    policy = _load_yaml(Path(args.policy))
    title = args.title or args.package_id.replace("_", " ").title()
    pid = _slug(args.package_id)
    standalone_overrides = set(args.mark_standalone or [])
    include_agents = not args.no_agent_nodes
    coop_path = Path(args.cooperation_policy) if args.cooperation_policy else None

    if args.cmd == "preview":
        class_map = _build_class_map(policy)
        profile_name = args.safety_profile or policy.get("default_safety_profile") or "sensor_only"
        active_profile = _build_profile(policy, profile_name)
        facts = _facts(snapshot, policy, pid, title, active_profile, class_map,
                       standalone_overrides=standalone_overrides, include_agent_nodes=include_agents)
        coop_policy = _load_cooperation_policy(coop_path)
        coop_state = _resolve_cooperation(facts["included_nodes"], coop_policy)
        workflows = _build_workflows(facts, coop_state)
        resolved_mode, _ = _resolve_mode(args.mode, Path(args.llm_config))
        print(json.dumps({
            "ok": True, "package_id": pid, "title": title,
            "safety_profile": profile_name,
            "schema_version": args.schema_version,
            "mode_requested": args.mode, "mode_resolved": resolved_mode,
            "included_nodes": [n["id"] for n in facts["included_nodes"]],
            "skipped_standalone_nodes": [s["id"] for s in facts["skipped_standalone"]],
            "workflows": [w["id"] for w in workflows],
            "cooperation_default": coop_state.get("default_approval"),
            "forbidden_actions": facts["forbidden_actions"],
        }, ensure_ascii=False, indent=2))
        return 0

    result = compose_and_write(
        snapshot, policy, pid, title, Path(args.out),
        mode=args.mode, llm_config=Path(args.llm_config),
        cooperation_policy_path=coop_path,
        standalone_overrides=standalone_overrides,
        safety_profile_name=args.safety_profile,
        include_agent_nodes=include_agents,
        schema_version=args.schema_version,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

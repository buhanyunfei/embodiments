#!/usr/bin/env python3
from __future__ import annotations

import argparse
import itertools
import json
import re
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

import yaml


def slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_\-]+", "_", s.strip())
    s = re.sub(r"_+", "_", s).strip("_")
    return s.lower() or "unnamed"


def load_yaml(path: Path) -> Dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_topology(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"topology not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_nodes(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    nodes = snapshot.get("nodes") or []
    if isinstance(nodes, dict):
        nodes = list(nodes.values())
    normalized = []
    for n in nodes:
        meta = n.get("metadata") or n.get("meta") or {}
        profile = meta.get("robot_profile") or meta.get("embodiment_profile") or {}
        caps = n.get("capabilities") or profile.get("capabilities") or []
        normalized.append({
            "id": n.get("id") or n.get("node_id"),
            "name": n.get("name") or n.get("id") or n.get("node_id"),
            "node_type": n.get("node_type") or n.get("type") or meta.get("node_type") or "unknown",
            "capabilities": list(dict.fromkeys(caps)),
            "metadata": meta,
            "profile": profile,
            "endpoint": n.get("endpoint") or meta.get("endpoint"),
            "agent_ref": n.get("agent_ref") or meta.get("agent_ref"),
        })
    return [n for n in normalized if n.get("id")]


def node_collaboration_policy(node: Dict[str, Any]) -> Dict[str, Any]:
    meta = node.get("metadata") or {}
    profile = node.get("profile") or {}
    return meta.get("collaboration_policy") or profile.get("collaboration_policy") or {}


def is_standalone_only(node: Dict[str, Any]) -> bool:
    return bool(node_collaboration_policy(node).get("standalone_only"))


def node_safe_caps(node: Dict[str, Any], policy: Dict[str, Any]) -> List[str]:
    safe = set(policy.get("safe_collaboration_capabilities") or [])
    caps = set(node.get("capabilities") or [])
    # Also inspect action_space/sensors from profile to infer observation role.
    profile = node.get("profile") or {}
    caps.update(profile.get("action_space") or [])
    if profile.get("sensors"):
        caps.add("observe")
    return sorted(caps & safe)


def eligible_observers(nodes: List[Dict[str, Any]], policy: Dict[str, Any]) -> List[Dict[str, Any]]:
    allowed_types = set(policy.get("observer_node_types") or [])
    out = []
    for n in nodes:
        if policy.get("respect_standalone_only", True) and is_standalone_only(n):
            continue
        nt = n.get("node_type")
        if nt not in allowed_types:
            continue
        caps = node_safe_caps(n, policy)
        if not caps:
            continue
        nn = dict(n)
        nn["safe_collaboration_capabilities"] = caps
        out.append(nn)
    return out


def package_for_instance(node: Dict[str, Any], policy: Dict[str, Any]) -> Dict[str, Any]:
    node_id = slug(node["id"])
    caps = node_safe_caps(node, policy)
    kind = "robot" if node.get("node_type") == "physical_robot" else "sensor"
    if node.get("node_type") in {"actuator", "gripper"}:
        kind = "actuator"
    model_id = slug((node.get("profile") or {}).get("profile_id") or node.get("name") or node_id)
    forbidden = policy.get("forbidden_actions") or []
    return {
        "package_id": f"{node_id}_instance",
        "name": f"{node.get('name') or node_id} Instance Embodiment",
        "kind": kind,
        "node": node,
        "embodiment_yaml": {
            "schema": "embodiment_package/v1",
            "package_id": f"{node_id}_instance",
            "name": f"{node.get('name') or node_id} Instance Embodiment",
            "version": "0.1.0",
            "kind": kind,
            "license": "Apache-2.0",
            "summary": f"Auto-generated instance embodiment package for topology node {node['id']}.",
            "tags": ["auto-generated", "instance", kind],
            "models": [{
                "model_id": model_id,
                "display_name": node.get("name") or node_id,
                "embodiment": (node.get("profile") or {}).get("embodiment") or node.get("node_type"),
                "default_safety_level": "sensor_only",
                "default_capabilities": caps,
                "forbidden_by_default": forbidden,
            }],
            "safety": {
                "default_policy": policy.get("default_graph_safety_level") or "sensor_only",
                "requires_confirmation_for": ["any_motion", "any_manipulation", "audio_output"],
            },
            "generated": {
                "by": "embodiment_composer",
                "at": time.time(),
                "source_node_id": node["id"],
            },
        },
    }


def graph_package(pair: List[Dict[str, Any]], policy: Dict[str, Any]) -> Dict[str, Any]:
    ids = [slug(n["id"]) for n in pair]
    pkg_id = f"{'__'.join(ids)}__dual_view_graph"
    forbidden = policy.get("forbidden_actions") or []
    graph_id = f"{'__'.join(ids)}__dual_view_observation"
    graph = {
        "schema": "embodiment_graph/v1",
        "graph_id": graph_id,
        "name": " + ".join(n.get("name") or n["id"] for n in pair) + " Dual-view Observation",
        "safety_level": policy.get("default_graph_safety_level") or "sensor_only",
        "nodes": [
            {
                "id": n["id"],
                "node_type": n.get("node_type"),
                "role": f"observer_{i+1}",
                "required_capabilities": n.get("safe_collaboration_capabilities") or node_safe_caps(n, policy),
                "forbidden_actions": forbidden,
            }
            for i, n in enumerate(pair)
        ] + [{
            "id": "perception_vision",
            "node_type": "perception_model",
            "role": "multi_view_describer",
            "required_capabilities": ["image_understanding"],
        }],
        "edges": [
            {"source": n["id"], "target": "perception_vision", "edge_type": "observation_stream"}
            for n in pair
        ],
        "task_template": {
            "task_type": "observation",
            "instruction": "Use the observer nodes to produce a multi-view scene description without moving any robot or hardware.",
            "constraints": {"allow_motion": False, "allow_manipulation": False, "allow_audio_output": False},
        },
        "outputs": ["multi_view_scene_description", "sensor_readiness_report", "episode_trace"],
    }
    return {
        "package_id": pkg_id,
        "name": graph["name"],
        "kind": "embodiment_graph",
        "graph": graph,
        "embodiment_yaml": {
            "schema": "embodiment_package/v1",
            "package_id": pkg_id,
            "name": graph["name"],
            "version": "0.1.0",
            "kind": "embodiment_graph",
            "license": "Apache-2.0",
            "summary": "Auto-generated sensor-only collaboration graph package.",
            "tags": ["auto-generated", "collaboration", "dual-view", "sensor-only"],
            "graphs": [f"graphs/{graph_id}.yaml"],
            "safety": {
                "default_policy": policy.get("default_graph_safety_level") or "sensor_only",
                "requires_confirmation_for": ["any_motion", "any_manipulation", "audio_output"],
            },
            "generated": {"by": "embodiment_composer", "at": time.time(), "source_node_ids": [n["id"] for n in pair]},
        },
    }


def compose(snapshot: Dict[str, Any], policy: Dict[str, Any]) -> Dict[str, Any]:
    nodes = normalize_nodes(snapshot)
    observers = eligible_observers(nodes, policy)
    instance_packages = [package_for_instance(n, policy) for n in observers]
    graph_packages = []
    tmpl = (policy.get("graph_templates") or {}).get("dual_view_observation") or {}
    if tmpl.get("enabled", True):
        for pair in itertools.combinations(observers, 2):
            graph_packages.append(graph_package(list(pair), policy))
    skipped = [{"id": n["id"], "reason": "standalone_only"} for n in nodes if is_standalone_only(n)]
    return {
        "ok": True,
        "nodes_seen": len(nodes),
        "eligible_observers": [{"id": n["id"], "node_type": n.get("node_type"), "safe_caps": n.get("safe_collaboration_capabilities")} for n in observers],
        "skipped": skipped,
        "instance_packages": instance_packages,
        "graph_packages": graph_packages,
    }


def write_package(pkg: Dict[str, Any], out_root: Path) -> Path:
    pkg_dir = out_root / pkg["package_id"]
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "embodiment.yaml").write_text(yaml.safe_dump(pkg["embodiment_yaml"], sort_keys=False, allow_unicode=True), encoding="utf-8")
    readme = f"# {pkg['name']}\n\nAuto-generated by Embodiment Composer.\n\nKind: `{pkg['kind']}`.\n\nSafety: sensor-only by default. Generated packages must not actuate hardware on install/build.\n"
    (pkg_dir / "README.md").write_text(readme, encoding="utf-8")
    if pkg.get("graph"):
        graph_dir = pkg_dir / "graphs"
        graph_dir.mkdir(exist_ok=True)
        graph_id = pkg["graph"]["graph_id"]
        (graph_dir / f"{graph_id}.yaml").write_text(yaml.safe_dump(pkg["graph"], sort_keys=False, allow_unicode=True), encoding="utf-8")
    else:
        prof_dir = pkg_dir / "profiles"
        prof_dir.mkdir(exist_ok=True)
        node = pkg.get("node") or {}
        profile_md = f"---\nschema: embodiment_profile_card/v1\nprofile_id: {pkg['package_id']}\nnode_type: {node.get('node_type')}\ncapabilities: {json.dumps(node_safe_caps(node, {'safe_collaboration_capabilities':['observe','inspect','perceive','listen','health_check']}), ensure_ascii=False)}\nlimits:\n  sensor_only: true\n  movement_allowed: false\n  manipulation_allowed: false\n---\n\n# {pkg['name']} Profile\n\nAuto-generated from topology node `{node.get('id')}`.\n"
        (prof_dir / "PROFILE.md").write_text(profile_md, encoding="utf-8")
    return pkg_dir


def main(argv=None):
    ap = argparse.ArgumentParser(description="Compose embodiment packages from topology")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ["preview", "generate"]:
        p = sub.add_parser(name)
        p.add_argument("--topology", required=True)
        p.add_argument("--packages", default="embodiments/packages")
        p.add_argument("--policy", default="embodiments/policies/default_composition_policy.yaml")
        p.add_argument("--out", default="embodiments/generated")
        p.add_argument("--max-graphs", type=int, default=20)
    args = ap.parse_args(argv)
    snapshot = load_topology(Path(args.topology))
    policy = load_yaml(Path(args.policy))
    result = compose(snapshot, policy)
    # Avoid huge output from many generated packages.
    preview = {
        "ok": True,
        "nodes_seen": result["nodes_seen"],
        "eligible_observers": result["eligible_observers"],
        "skipped": result["skipped"],
        "instance_package_ids": [p["package_id"] for p in result["instance_packages"]],
        "graph_package_ids": [p["package_id"] for p in result["graph_packages"][: args.max_graphs]],
        "graph_package_count": len(result["graph_packages"]),
    }
    if args.cmd == "generate":
        out = Path(args.out)
        written = []
        for pkg in result["instance_packages"]:
            written.append(str(write_package(pkg, out)))
        for pkg in result["graph_packages"][: args.max_graphs]:
            written.append(str(write_package(pkg, out)))
        preview["written"] = written
    print(json.dumps(preview, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

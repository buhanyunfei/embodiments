#!/usr/bin/env python3
"""Embodiment package builder.

Offline validator + zip packager.

Slim layout (recommended):

    <package>/
      EMBODIMENT.md       agent-readable, SKILL.md-style
      embodiment.yaml     runtime-readable, may inline `registry` and `graphs`
      evidence/*.json     optional verified probe results
      probes/*.py         optional, must remain passive
      adapters/*          optional adapter contract/templates

Backward-compatible layout:

    <package>/
      embodiment.yaml     pointing to registry/nodes.yaml and graphs/*.yaml on disk
      registry/nodes.yaml
      graphs/*.yaml

This script is offline. It must not contact hardware or actuate any robot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    import yaml
except Exception:
    print("Missing dependency: pyyaml. Install with `pip install pyyaml`.", file=sys.stderr)
    raise

VALID_KINDS = {"robot", "sensor", "actuator", "hardware_rig",
               "embodiment_graph", "collaboration", "embodiment_context"}
VALID_SCHEMAS = {"embodiment_package/v1", "embodiment_package/v2", "embodiment_package/v3"}
VALID_GRAPH_SCHEMAS = {"embodiment_graph/v1", "embodiment_graph/v2", "embodiment_graph/v3"}
VALID_REGISTRY_SCHEMAS = {"embodiment_node_registry/v1", "embodiment_node_registry/v2"}
REQUIRED_TOP_LEVEL = ["schema", "package_id", "name", "version", "kind", "license", "summary"]

DEFAULT_FORBIDDEN = {
    "navigate", "walk", "move", "turn",
    "grasp", "pick", "place", "carry", "hand_over", "open_door",
    "whole_body_motion", "arm_motion", "hand_motion",
    "audio_output",
}
SENSOR_ONLY_SAFE = {"observe", "inspect", "listen", "perceive", "wait", "standby", "health_check"}

# Required EMBODIMENT.md sections (slim, SKILL.md-shaped). Builder errors on missing
# for context packages; warns for v1 single-device packages.
EMBODIMENT_MD_SECTIONS = [
    "When to use",
    "When not to use",
    "Available nodes",
    "How to plan",
    "Forbidden actions",
    "Failure modes",
    "Recovery",
    "Runtime integration",
]

# Additional sections required for v3 context packages
EMBODIMENT_MD_SECTIONS_V3 = EMBODIMENT_MD_SECTIONS + [
    "Tool interfaces",
    "Execution workflows",
    "Cooperation boundaries",
]

# Packages using the capability-class model may leave forbidden_actions empty in the
# top-level safety block (profile governs what's forbidden). The validator accepts
# either: a non-empty forbidden_actions, OR a non-empty safety_profiles block.
CAPABILITY_CLASSES = {"safe", "motion", "manipulation", "audio_output", "unknown"}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _list_files(package_dir: Path) -> List[Path]:
    files = []
    for p in package_dir.rglob("*"):
        if not p.is_file():
            continue
        if ".git" in p.parts or "__pycache__" in p.parts:
            continue
        files.append(p)
    return sorted(files)


def _load_yaml_optional(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _is_context(data: Dict[str, Any]) -> bool:
    return data.get("kind") == "embodiment_context"


def _resolve_registry(package_dir: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    """Return the registry dict, whether inline or pointed-at via path."""
    reg = data.get("registry")
    if isinstance(reg, dict):
        return reg
    if isinstance(reg, str):
        return _load_yaml_optional(package_dir / reg)
    # Conventional fallback path.
    fallback = package_dir / "registry" / "nodes.yaml"
    if fallback.exists():
        return _load_yaml_optional(fallback)
    return {}


def _resolve_graphs(package_dir: Path, data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return graph dicts, whether inline or referenced as paths."""
    out: List[Dict[str, Any]] = []
    graphs_field = data.get("graphs")
    if isinstance(graphs_field, list):
        for entry in graphs_field:
            if isinstance(entry, dict):
                out.append(entry)
            elif isinstance(entry, str):
                g = _load_yaml_optional(package_dir / entry)
                if g:
                    out.append(g)
    graphs_dir = package_dir / "graphs"
    if graphs_dir.exists():
        for gpath in sorted(graphs_dir.glob("*.yaml")):
            g = _load_yaml_optional(gpath)
            if g and not any(g.get("graph_id") == ex.get("graph_id") for ex in out):
                out.append(g)
    return out


def _resolve_workflows(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return workflow index entries (lightweight alternative to full graphs)."""
    wf = data.get("workflows")
    if isinstance(wf, list):
        return [w for w in wf if isinstance(w, dict)]
    return []


# --------------------------------------------------------------------------- #
# Validation pieces
# --------------------------------------------------------------------------- #

def _validate_top_level(data: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    missing = [k for k in REQUIRED_TOP_LEVEL if not data.get(k)]
    if missing:
        errors.append(f"missing required fields: {missing}")
    if data.get("schema") and data["schema"] not in VALID_SCHEMAS:
        errors.append(f"invalid schema: {data['schema']}; expected one of {sorted(VALID_SCHEMAS)}")
    if data.get("kind") and data["kind"] not in VALID_KINDS:
        errors.append(f"invalid kind: {data['kind']}; expected one of {sorted(VALID_KINDS)}")
    return errors


def _validate_safety(data: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    safety = data.get("safety") or {}
    forbidden = list(safety.get("forbidden_actions") or [])
    has_profiles = bool(data.get("safety_profiles"))

    for m in data.get("models") or []:
        defaults = set(m.get("default_capabilities") or [])
        forbidden_by_default = set(m.get("forbidden_by_default") or [])
        is_sensor_only = (m.get("default_safety_level") == "sensor_only")
        leaked = defaults & DEFAULT_FORBIDDEN
        if is_sensor_only and leaked:
            errors.append(
                f"model '{m.get('model_id')}' is sensor_only but lists forbidden actions in default_capabilities: {sorted(leaked)}"
            )
        if is_sensor_only:
            missing = sorted(DEFAULT_FORBIDDEN - forbidden_by_default - set(forbidden))
            if missing:
                warnings.append(
                    f"sensor_only model '{m.get('model_id')}' missing forbidden_by_default entries: "
                    f"{missing[:6]}{'...' if len(missing) > 6 else ''}"
                )

    # Context packages: require either non-empty forbidden_actions OR a safety_profiles block.
    if _is_context(data) and not forbidden and not has_profiles:
        errors.append(
            "kind=embodiment_context (or schema v2) requires either non-empty safety.forbidden_actions "
            "or a top-level safety_profiles block"
        )

    # Validate capability list if present
    for cap in data.get("capabilities") or []:
        if isinstance(cap, dict):
            if "id" not in cap:
                errors.append(f"capability entry missing 'id': {cap}")
            cls = cap.get("class")
            if cls and cls not in CAPABILITY_CLASSES:
                warnings.append(f"capability '{cap.get('id')}' has unknown class '{cls}'")

    # Validate safety_profiles if present
    for pname, pdata in (data.get("safety_profiles") or {}).items():
        if not isinstance(pdata, dict):
            errors.append(f"safety_profiles.{pname} must be a mapping")
            continue
        if "description" not in pdata:
            warnings.append(f"safety_profiles.{pname} missing description")

    # default_safety_profile must be declared if safety_profiles exist
    if has_profiles and "default_safety_profile" in data:
        dsp = data["default_safety_profile"]
        if dsp not in (data.get("safety_profiles") or {}):
            errors.append(f"default_safety_profile '{dsp}' is not in safety_profiles")

    if _is_context(data) and safety.get("install_must_not_actuate") is None:
        warnings.append("safety.install_must_not_actuate not set; defaulting to true")
    return errors, warnings


def _validate_layout(package_dir: Path, data: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    if _is_context(data):
        if not (package_dir / "EMBODIMENT.md").exists():
            errors.append("kind=embodiment_context requires EMBODIMENT.md")
        reg = _resolve_registry(package_dir, data)
        if not reg.get("nodes"):
            errors.append("kind=embodiment_context requires a non-empty registry (inline `registry: {nodes: [...]}` or registry/nodes.yaml)")
        graphs = _resolve_graphs(package_dir, data)
        workflows = _resolve_workflows(data)
        if not graphs and not workflows:
            errors.append("kind=embodiment_context requires at least one graph (in `graphs:`) or workflow (in `workflows:`)")
    else:
        if not (package_dir / "EMBODIMENT.md").exists():
            warnings.append("EMBODIMENT.md not found; agent runtimes will have less context to plan with")
    return errors, warnings


def _validate_embodiment_md(package_dir: Path, data: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    md_path = package_dir / "EMBODIMENT.md"
    if not md_path.exists():
        return [], []
    errors: List[str] = []
    warnings: List[str] = []
    text = md_path.read_text(encoding="utf-8")
    required_for_context = _is_context(data)
    is_v3 = data.get("schema") == "embodiment_package/v3"
    sections = EMBODIMENT_MD_SECTIONS_V3 if is_v3 else EMBODIMENT_MD_SECTIONS
    for sec in sections:
        if sec not in text:
            msg = f"EMBODIMENT.md is missing section containing: '{sec}'"
            (errors if required_for_context else warnings).append(msg)
    if required_for_context:
        forbidden = (data.get("safety") or {}).get("forbidden_actions") or []
        for action in forbidden:
            if not re.search(rf"\b{re.escape(action)}\b", text):
                errors.append(f"EMBODIMENT.md does not mention forbidden action: '{action}'")
    return errors, warnings


def _validate_registry(package_dir: Path, data: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    reg = _resolve_registry(package_dir, data)
    if not reg:
        return [], []
    errors: List[str] = []
    warnings: List[str] = []
    reg_schema = reg.get("schema", "")
    if reg_schema and reg_schema not in VALID_REGISTRY_SCHEMAS:
        errors.append(f"registry has invalid schema: {reg_schema}")
    if reg_schema == "embodiment_node_registry/v1" and data.get("schema") == "embodiment_package/v3":
        warnings.append("v3 package uses registry v1; consider upgrading to embodiment_node_registry/v2")
    forbidden = set((data.get("safety") or {}).get("forbidden_actions") or [])
    for n in reg.get("nodes") or []:
        nid = n.get("id") or "<unnamed>"
        safe = set(n.get("safe_capabilities") or [])
        if forbidden:
            leaked = safe & forbidden
            if leaked:
                errors.append(f"registry node '{nid}' has safe_capabilities containing forbidden actions: {sorted(leaked)}")
        limits = n.get("limits") or {}
        if limits.get("sensor_only") is True:
            beyond = safe - SENSOR_ONLY_SAFE
            if beyond:
                errors.append(f"registry node '{nid}' is sensor_only but lists non-safe capabilities: {sorted(beyond)}")
        # v2 registry: validate agent_node requirements
        if reg_schema == "embodiment_node_registry/v2":
            participant_type = n.get("participant_type")
            if participant_type == "agent_node" and not n.get("agent_subtype"):
                errors.append(f"registry node '{nid}': participant_type=agent_node requires 'agent_subtype' field")
            ti = n.get("tool_interface")
            if ti:
                if not ti.get("protocol"):
                    errors.append(f"registry node '{nid}': tool_interface missing 'protocol'")
                for op in ti.get("operations") or []:
                    if not op.get("operation_id"):
                        errors.append(f"registry node '{nid}': tool_interface operation missing 'operation_id'")
    return errors, warnings


def _validate_graphs(package_dir: Path, data: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    graphs = _resolve_graphs(package_dir, data)
    if not graphs:
        return [], []
    errors: List[str] = []
    warnings: List[str] = []
    for g in graphs:
        gid = g.get("graph_id") or "<unnamed>"
        schema = g.get("schema")
        if schema not in VALID_GRAPH_SCHEMAS:
            errors.append(f"graph '{gid}': invalid schema: {schema}")
            continue
        if schema == "embodiment_graph/v1":
            warnings.append(f"graph '{gid}': using deprecated v1 schema")
            continue
        # Common v2/v3 validation
        v2_keys = ("name", "intent", "safety_level", "roles", "nodes", "constraints",
                   "readiness_checks", "failure_modes", "recovery", "outputs")
        for k in v2_keys:
            if not g.get(k):
                errors.append(f"graph '{gid}': missing required key: '{k}'")
        if (g.get("safety_level") == "sensor_only"
            and not (g.get("constraints") or {}).get("forbidden_actions")):
            errors.append(f"graph '{gid}': sensor_only graph requires non-empty constraints.forbidden_actions")
        # v3-specific validation
        if schema == "embodiment_graph/v3":
            if not g.get("trigger_keywords"):
                errors.append(f"graph '{gid}': v3 graph requires non-empty 'trigger_keywords'")
            if not g.get("cooperation_network"):
                errors.append(f"graph '{gid}': v3 graph requires 'cooperation_network'")
            for edge in g.get("edges") or []:
                if not edge.get("ordering"):
                    errors.append(f"graph '{gid}': edge {edge.get('source')}→{edge.get('target')} missing 'ordering'")
                if not edge.get("protocol_hint"):
                    errors.append(f"graph '{gid}': edge {edge.get('source')}→{edge.get('target')} missing 'protocol_hint'")
                if edge.get("ordering") == "conditional" and not edge.get("condition"):
                    errors.append(f"graph '{gid}': conditional edge {edge.get('source')}→{edge.get('target')} missing 'condition'")
            # Check at least one agent_node participant
            has_agent = any(n.get("participant_type") == "agent_node" or n.get("agent_subtype")
                          for n in g.get("nodes") or [])
            if not has_agent:
                warnings.append(f"graph '{gid}': v3 graph has no agent_node participant")
        elif schema == "embodiment_graph/v2":
            warnings.append(f"graph '{gid}': using v2 schema; consider upgrading to v3 for cooperation+execution support")
    return errors, warnings


def _validate_workflows(data: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """Validate lightweight workflow index entries."""
    workflows = _resolve_workflows(data)
    if not workflows:
        return [], []
    errors: List[str] = []
    warnings: List[str] = []
    registry = data.get("registry") or {}
    node_ids = {n.get("id") for n in registry.get("nodes") or []}
    for wf in workflows:
        wid = wf.get("id") or "<unnamed>"
        if not wf.get("id"):
            errors.append(f"workflow entry missing 'id'")
        if not wf.get("trigger_keywords"):
            errors.append(f"workflow '{wid}': missing 'trigger_keywords'")
        if not wf.get("safety_level"):
            warnings.append(f"workflow '{wid}': missing 'safety_level'")
        for nid in wf.get("primary_nodes") or []:
            if node_ids and nid not in node_ids:
                errors.append(f"workflow '{wid}': primary_node '{nid}' not found in registry")
    return errors, warnings


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def load_package(package_dir: Path) -> Dict[str, Any]:
    yml = package_dir / "embodiment.yaml"
    if not yml.exists():
        raise ValueError(f"missing embodiment.yaml: {yml}")
    return yaml.safe_load(yml.read_text(encoding="utf-8")) or {}


def validate_package(package_dir: Path, strict: bool = False) -> Dict[str, Any]:
    data = load_package(package_dir)
    errors: List[str] = []
    warnings: List[str] = []
    errors += _validate_top_level(data)
    e, w = _validate_safety(data); errors += e; warnings += w
    e, w = _validate_layout(package_dir, data); errors += e; warnings += w
    e, w = _validate_embodiment_md(package_dir, data); errors += e; warnings += w
    e, w = _validate_registry(package_dir, data); errors += e; warnings += w
    e, w = _validate_graphs(package_dir, data); errors += e; warnings += w
    e, w = _validate_workflows(data); errors += e; warnings += w
    if strict:
        errors += [f"warning_as_error: {w}" for w in warnings]
        warnings = []
    if errors:
        raise ValueError("validation failed:\n  - " + "\n  - ".join(errors))
    return {
        "package_id": data.get("package_id"),
        "version": data.get("version"),
        "kind": data.get("kind"),
        "schema": data.get("schema"),
        "warnings": warnings,
    }


def safety_summary(data: Dict[str, Any]) -> Dict[str, Any]:
    forbidden = list((data.get("safety") or {}).get("forbidden_actions") or [])
    for m in data.get("models") or []:
        forbidden.extend(m.get("forbidden_by_default") or [])
    forbidden = sorted(set(forbidden))
    safety = data.get("safety") or {}
    return {
        "default_policy": safety.get("default_policy"),
        "requires_confirmation_for": safety.get("requires_confirmation_for") or [],
        "forbidden_by_default": forbidden,
        "build_is_offline": True,
        "install_must_not_actuate": safety.get("install_must_not_actuate", True),
    }


def build_manifest(package_dir: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    files = _list_files(package_dir)
    rel_files = []
    for p in files:
        rel_files.append({"path": str(p.relative_to(package_dir)), "sha256": _sha256(p), "bytes": p.stat().st_size})
    return {
        "schema": "embodiment_manifest/v1",
        "built_at": time.time(),
        "package": data,
        "package_dir": str(package_dir),
        "files": rel_files,
        "safety_summary": safety_summary(data),
    }


def validate(package_dir: Path, strict: bool = False) -> Dict[str, Any]:
    info = validate_package(package_dir, strict=strict)
    data = load_package(package_dir)
    return {
        "ok": True,
        "package_id": info["package_id"],
        "version": info["version"],
        "kind": info["kind"],
        "schema": info["schema"],
        "files": len(_list_files(package_dir)),
        "safety_summary": safety_summary(data),
        "warnings": info["warnings"],
    }


def build(package_dir: Path, out_dir: Path, strict: bool = False) -> Dict[str, Any]:
    info = validate_package(package_dir, strict=strict)
    data = load_package(package_dir)
    manifest = build_manifest(package_dir, data)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{data['package_id']}-{data['version']}"
    manifest_path = out_dir / f"{stem}.manifest.json"
    zip_path = out_dir / f"{stem}.embodiment.zip"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in _list_files(package_dir):
            z.write(p, arcname=str(Path(data["package_id"]) / p.relative_to(package_dir)))
        z.writestr(str(Path(data["package_id"]) / "MANIFEST.json"),
                   json.dumps(manifest, ensure_ascii=False, indent=2))
    return {
        "ok": True,
        "package_id": data["package_id"],
        "version": data["version"],
        "kind": data["kind"],
        "zip": str(zip_path),
        "manifest": str(manifest_path),
        "files": len(manifest["files"]),
        "warnings": info["warnings"],
    }


def build_all(packages_root: Path, out_dir: Path, strict: bool = False) -> Dict[str, Any]:
    results = []
    for child in sorted(packages_root.iterdir()):
        if child.is_dir() and (child / "embodiment.yaml").exists():
            try:
                results.append(build(child, out_dir, strict=strict))
            except Exception as exc:
                results.append({"ok": False, "package_dir": str(child), "error": str(exc)})
    return {"ok": all(r.get("ok") for r in results), "results": results}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate and build embodiment packages (offline).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("validate")
    p.add_argument("package_dir")
    p.add_argument("--strict", action="store_true")
    p = sub.add_parser("build")
    p.add_argument("package_dir")
    p.add_argument("--out", default="embodiments/dist")
    p.add_argument("--strict", action="store_true")
    p = sub.add_parser("build-all")
    p.add_argument("packages_root")
    p.add_argument("--out", default="embodiments/dist")
    p.add_argument("--strict", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "validate":
        result = validate(Path(args.package_dir), strict=args.strict)
    elif args.cmd == "build":
        result = build(Path(args.package_dir), Path(args.out), strict=args.strict)
    else:
        result = build_all(Path(args.packages_root), Path(args.out), strict=args.strict)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

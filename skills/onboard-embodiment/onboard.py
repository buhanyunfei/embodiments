#!/usr/bin/env python3
"""End-to-end onboarding orchestrator for embodiments (v3).

This is a thin wrapper around four already-existing tools:

  1. robot_node_onboarding.cli   - passive device discovery + tool interface auto-discovery
  2. embodiments/composer        - deployment-level context composition (v3: multi-graph, cooperation)
  3. embodiments/builder         - validate + zip
  4. embodiments/runtime/loader  - hot-plug into running agent system

It does not invent any new safety semantics. It just executes the SKILL.md
workflow in order, stops at the first failure, and prints a structured summary
the agent can read.

Usage:

  # Onboard a new robot at a known IP and add it to the existing context (v3).
  python embodiments/skills/onboard-embodiment/onboard.py \
    --device-id g2_real_sensor_only \
    --device-kind robot \
    --ip 192.168.5.20 \
    --package-id current_lab_sensor_context

  # Onboard a USB camera and keep it standalone.
  python embodiments/skills/onboard-embodiment/onboard.py \
    --device-id usb_camera_2 \
    --device-kind sensor \
    --usb \
    --standalone

  # Re-compose only (skip device discovery; useful when topology already updated).
  python embodiments/skills/onboard-embodiment/onboard.py \
    --skip-discover \
    --package-id current_lab_sensor_context

  # Use v2 schema (backward compatible).
  python embodiments/skills/onboard-embodiment/onboard.py \
    --device-id usb_camera_3 \
    --schema-version v2

This script is sensor-only. It never sends motion commands.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON = sys.executable

DEFAULT_TOPOLOGY = REPO_ROOT / "hub" / "topology_snapshot.json"
DEFAULT_OUT = REPO_ROOT / "embodiments" / "generated"
DEFAULT_DIST = REPO_ROOT / "embodiments" / "dist"
DEFAULT_LLM_CONFIG = REPO_ROOT / "hub" / "copaw_config.json"
DEFAULT_COOPERATION_POLICY = REPO_ROOT / "embodiments" / "policies" / "default_cooperation_policy.yaml"
COMPOSER = REPO_ROOT / "embodiments" / "composer" / "compose_context.py"
BUILDER = REPO_ROOT / "embodiments" / "builder" / "build_embodiment.py"


def _run(cmd: List[str], step: str) -> Dict[str, Any]:
    """Run a subprocess and capture the structured outcome."""
    print(f"[{step}] {' '.join(shlex.quote(c) for c in cmd)}", file=sys.stderr)
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    parsed: Optional[Any] = None
    try:
        parsed = json.loads(out) if out else None
    except Exception:
        parsed = None
    return {
        "step": step,
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": parsed if parsed is not None else out,
        "stderr": err,
    }


def discover(device_id: str, ip: Optional[str], http_base: Optional[str], usb: bool) -> List[Dict[str, Any]]:
    """Run the robot_node_onboarding kit's passive discovery + profile render."""
    init_cmd = [PYTHON, "-m", "robot_node_onboarding.cli", "init",
                "--robot-id", device_id, "--name", device_id]
    if ip:
        init_cmd += ["--ip", ip]
    if http_base:
        init_cmd += ["--http-base", http_base]
    if usb:
        init_cmd += ["--usb"]

    steps = [_run(init_cmd, step="onboard.init")]
    if not steps[-1]["ok"]:
        return steps

    discover_cmd = [PYTHON, "-m", "robot_node_onboarding.cli", "discover",
                    "--robot-id", device_id]
    if ip:
        discover_cmd += ["--ip", ip]
    if http_base:
        discover_cmd += ["--http-base", http_base]
    if usb:
        discover_cmd += ["--usb"]
    steps.append(_run(discover_cmd, step="onboard.discover"))
    if not steps[-1]["ok"]:
        return steps

    render_cmd = [PYTHON, "-m", "robot_node_onboarding.cli", "render-profile",
                  "--robot-id", device_id]
    steps.append(_run(render_cmd, step="onboard.render_profile"))
    if not steps[-1]["ok"]:
        return steps

    profile_path = REPO_ROOT / "robot_profiles" / device_id / "ROBOT_NODE_PROFILE.md"
    if profile_path.exists():
        validate_cmd = [PYTHON, "-m", "robot_node_onboarding.cli", "validate-profile",
                        str(profile_path)]
        steps.append(_run(validate_cmd, step="onboard.validate_profile"))
    return steps


def discover_tools(device_id: str, ip: Optional[str], http_base: Optional[str]) -> Dict[str, Any]:
    """Run tool interface auto-discovery for the device (v3)."""
    cmd = [PYTHON, "-m", "robot_node_onboarding.cli", "discover-tools",
           "--robot-id", device_id]
    if ip:
        cmd += ["--ip", ip]
    if http_base:
        cmd += ["--http-base", http_base]
    return _run(cmd, step="onboard.discover_tools")


def compose(topology: Path, package_id: str, out: Path,
            mode: str, llm_config: Path, standalone: List[str],
            schema_version: str = "v3",
            cooperation_policy: Optional[Path] = None,
            include_agent_nodes: bool = True,
            title: Optional[str] = None) -> Dict[str, Any]:
    cmd = [PYTHON, str(COMPOSER), "generate",
           "--topology", str(topology),
           "--package-id", package_id,
           "--out", str(out),
           "--mode", mode,
           "--llm-config", str(llm_config),
           "--schema-version", schema_version]
    if cooperation_policy and cooperation_policy.exists():
        cmd += ["--cooperation-policy", str(cooperation_policy)]
    if include_agent_nodes and schema_version == "v3":
        cmd += ["--include-agent-nodes"]
    if title:
        cmd += ["--title", title]
    for s in standalone:
        cmd += ["--mark-standalone", s]
    return _run(cmd, step="compose")


def validate(package_dir: Path, strict: bool = False) -> Dict[str, Any]:
    cmd = [PYTHON, str(BUILDER), "validate", str(package_dir)]
    if strict:
        cmd.append("--strict")
    return _run(cmd, step="validate")


def build(package_dir: Path, out: Path, strict: bool = False) -> Dict[str, Any]:
    cmd = [PYTHON, str(BUILDER), "build", str(package_dir), "--out", str(out)]
    if strict:
        cmd.append("--strict")
    return _run(cmd, step="build")


def hot_plug(zip_path: Path, config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Hot-plug the built package into the runtime loader."""
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from embodiments.runtime.loader import EmbodimentLoader

        loader_config = str(config_path) if config_path else None
        loader = EmbodimentLoader(config_path=loader_config)
        loader.discover()
        package_id = loader.hot_plug(str(zip_path))
        if package_id:
            status = loader.status()
            return {
                "step": "hot_plug",
                "ok": True,
                "package_id": package_id,
                "active_packages": status["active"],
                "total_tools": status["total_tools"],
            }
        return {
            "step": "hot_plug",
            "ok": False,
            "error": f"hot_plug returned None for {zip_path}",
        }
    except ImportError as e:
        return {
            "step": "hot_plug",
            "ok": False,
            "error": f"runtime loader not available: {e}",
            "hint": "Install embodiments.runtime or check sys.path",
        }
    except Exception as e:
        return {
            "step": "hot_plug",
            "ok": False,
            "error": str(e),
        }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Onboard a new embodiment end-to-end (v3).")
    ap.add_argument("--device-id", help="device slug, e.g. g2_real_sensor_only")
    ap.add_argument("--device-kind", choices=["robot", "sensor", "actuator", "hardware_rig"], default="sensor")
    ap.add_argument("--ip")
    ap.add_argument("--http-base")
    ap.add_argument("--usb", action="store_true")
    ap.add_argument("--package-id", default="current_lab_sensor_context")
    ap.add_argument("--title", default=None)
    ap.add_argument("--standalone", action="store_true",
                    help="Mark THIS device as standalone_only (skip from collaborative graphs).")
    ap.add_argument("--mark-standalone", action="append", default=[], metavar="NODE_ID",
                    help="Mark an additional node id as standalone (repeatable).")
    ap.add_argument("--topology", default=str(DEFAULT_TOPOLOGY))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--dist", default=str(DEFAULT_DIST))
    ap.add_argument("--mode", choices=["auto", "deterministic", "llm"], default="auto")
    ap.add_argument("--llm-config", default=str(DEFAULT_LLM_CONFIG))
    ap.add_argument("--schema-version", choices=["v2", "v3"], default="v3",
                    help="Schema version for output (default: v3).")
    ap.add_argument("--cooperation-policy", default=str(DEFAULT_COOPERATION_POLICY),
                    help="Path to cooperation policy YAML (v3 only).")
    ap.add_argument("--no-agent-nodes", action="store_true",
                    help="Do not inject llm_planner and human_operator agent nodes.")
    ap.add_argument("--skip-discover", action="store_true",
                    help="Skip device discovery; only re-compose, validate, and build.")
    ap.add_argument("--skip-build", action="store_true",
                    help="Validate only; do not produce zip artifacts.")
    ap.add_argument("--skip-hot-plug", action="store_true",
                    help="Do not hot-plug into runtime loader after build.")
    ap.add_argument("--loader-config", default=None,
                    help="Path to embodiments.yaml for the runtime loader (hot-plug).")
    ap.add_argument("--strict", action="store_true",
                    help="Fail on builder warnings.")
    args = ap.parse_args(argv)

    summary: Dict[str, Any] = {"ok": True, "steps": [], "schema_version": args.schema_version}

    # Step 1 — discover (optional)
    if not args.skip_discover:
        if not args.device_id:
            print("error: --device-id is required unless --skip-discover is set", file=sys.stderr)
            return 2
        discover_steps = discover(args.device_id, args.ip, args.http_base, args.usb)
        summary["steps"].extend(discover_steps)
        if not all(s["ok"] for s in discover_steps):
            summary["ok"] = False
            summary["failed_at"] = "discover"
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 1

        # Tool interface auto-discovery (v3)
        if args.schema_version == "v3" and not args.usb:
            tool_step = discover_tools(args.device_id, args.ip, args.http_base)
            summary["steps"].append(tool_step)
            if not tool_step["ok"]:
                print(f"[warn] tool interface discovery failed for {args.device_id}; "
                      "will use protocol:local stubs", file=sys.stderr)

        print("[onboard] device probed; remember to register the profile card with the topology runtime "
              "and refresh hub/topology_snapshot.json before composing.", file=sys.stderr)

    if not Path(args.topology).exists():
        summary["ok"] = False
        summary["failed_at"] = "topology_missing"
        summary["hint"] = f"topology snapshot not found at {args.topology}; refresh from the runtime first."
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 1

    # Step 2 — compose
    standalone = list(args.mark_standalone)
    if args.standalone and args.device_id and args.device_id not in standalone:
        standalone.append(args.device_id)

    cooperation_policy_path = Path(args.cooperation_policy) if args.schema_version == "v3" else None
    include_agent_nodes = (args.schema_version == "v3") and (not args.no_agent_nodes)

    compose_step = compose(
        Path(args.topology), args.package_id, Path(args.out),
        args.mode, Path(args.llm_config), standalone,
        schema_version=args.schema_version,
        cooperation_policy=cooperation_policy_path,
        include_agent_nodes=include_agent_nodes,
        title=args.title,
    )
    summary["steps"].append(compose_step)
    if not compose_step["ok"]:
        summary["ok"] = False
        summary["failed_at"] = "compose"
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 1

    package_dir = Path(args.out) / args.package_id

    # Step 3 — validate
    validate_step = validate(package_dir, strict=args.strict)
    summary["steps"].append(validate_step)
    if not validate_step["ok"]:
        summary["ok"] = False
        summary["failed_at"] = "validate"
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 1

    # Step 4 — build (optional)
    zip_path = None
    if not args.skip_build:
        build_step = build(package_dir, Path(args.dist), strict=args.strict)
        summary["steps"].append(build_step)
        if not build_step["ok"]:
            summary["ok"] = False
            summary["failed_at"] = "build"
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 1
        # Find the built zip
        for f in Path(args.dist).glob(f"{args.package_id}-*.embodiment.zip"):
            zip_path = f
            break

    # Step 5 — hot-plug (v3, optional)
    if args.schema_version == "v3" and not args.skip_hot_plug and not args.skip_build and zip_path:
        loader_config = Path(args.loader_config) if args.loader_config else None
        hp_step = hot_plug(zip_path, config_path=loader_config)
        summary["steps"].append(hp_step)
        if not hp_step["ok"]:
            print(f"[warn] hot-plug failed: {hp_step.get('error', 'unknown')}; "
                  "package is built but not live", file=sys.stderr)

    # Final report
    compose_out = compose_step["stdout"] if isinstance(compose_step["stdout"], dict) else {}
    final: Dict[str, Any] = {
        "ok": True,
        "schema_version": args.schema_version,
        "package_id": args.package_id,
        "package_dir": str(package_dir),
        "user_marked_standalone": standalone,
        "mode_resolved": compose_out.get("mode_resolved"),
        "llm_status": compose_out.get("llm_status"),
        "included_nodes": compose_out.get("included_nodes"),
        "skipped_standalone_nodes": compose_out.get("skipped_standalone_nodes"),
        "graphs": compose_out.get("graphs") or compose_out.get("graph_id"),
        "tool_interfaces_discovered": compose_out.get("tool_interfaces_discovered"),
        "cooperation_policy": str(args.cooperation_policy) if args.schema_version == "v3" else None,
        "hot_plug_status": next(
            (s for s in summary["steps"] if s["step"] == "hot_plug"),
            {"ok": False, "skipped": True}
        ),
        "artifacts": {
            "package_dir": str(package_dir),
            "zip": str(zip_path) if zip_path else None,
        },
    }
    print(json.dumps(final, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""End-to-end onboarding orchestrator for embodiments.

This is a thin wrapper around three already-existing tools:

  1. robot_node_onboarding.cli   - passive device discovery + profile card
  2. embodiments/composer        - deployment-level context composition
  3. embodiments/builder         - validate + zip

It does not invent any new safety semantics. It just executes the SKILL.md
workflow in order, stops at the first failure, and prints a structured summary
the agent can read.

Usage:

  # Onboard a new robot at a known IP and add it to the existing context.
  python embodiments/skills/onboard-embodiment/onboard.py \\
    --device-id g2_real_sensor_only \\
    --device-kind robot \\
    --ip 192.168.5.20 \\
    --package-id current_lab_sensor_context

  # Onboard a USB camera and keep it standalone.
  python embodiments/skills/onboard-embodiment/onboard.py \\
    --device-id usb_camera_2 \\
    --device-kind sensor \\
    --usb \\
    --standalone

  # Re-compose only (skip device discovery; useful when topology already updated).
  python embodiments/skills/onboard-embodiment/onboard.py \\
    --skip-discover \\
    --package-id current_lab_sensor_context

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


def compose(topology: Path, package_id: str, out: Path,
            mode: str, llm_config: Path, standalone: List[str],
            title: Optional[str] = None) -> Dict[str, Any]:
    cmd = [PYTHON, str(COMPOSER), "generate",
           "--topology", str(topology),
           "--package-id", package_id,
           "--out", str(out),
           "--mode", mode,
           "--llm-config", str(llm_config)]
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


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Onboard a new embodiment end-to-end.")
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
    ap.add_argument("--skip-discover", action="store_true",
                    help="Skip device discovery; only re-compose, validate, and build.")
    ap.add_argument("--skip-build", action="store_true",
                    help="Validate only; do not produce zip artifacts.")
    ap.add_argument("--strict", action="store_true",
                    help="Fail on builder warnings.")
    args = ap.parse_args(argv)

    summary: Dict[str, Any] = {"ok": True, "steps": []}

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
    compose_step = compose(Path(args.topology), args.package_id, Path(args.out),
                           args.mode, Path(args.llm_config), standalone, title=args.title)
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
    if not args.skip_build:
        build_step = build(package_dir, Path(args.dist), strict=args.strict)
        summary["steps"].append(build_step)
        if not build_step["ok"]:
            summary["ok"] = False
            summary["failed_at"] = "build"
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 1

    # Final report
    final: Dict[str, Any] = {
        "ok": True,
        "package_id": args.package_id,
        "package_dir": str(package_dir),
        "user_marked_standalone": standalone,
        "mode_resolved": (compose_step["stdout"] or {}).get("mode_resolved")
                         if isinstance(compose_step["stdout"], dict) else None,
        "llm_status": (compose_step["stdout"] or {}).get("llm_status")
                       if isinstance(compose_step["stdout"], dict) else None,
        "included_nodes": (compose_step["stdout"] or {}).get("included_nodes")
                           if isinstance(compose_step["stdout"], dict) else None,
        "skipped_standalone_nodes": (compose_step["stdout"] or {}).get("skipped_standalone_nodes")
                                     if isinstance(compose_step["stdout"], dict) else None,
        "graph_id": (compose_step["stdout"] or {}).get("graph_id")
                     if isinstance(compose_step["stdout"], dict) else None,
        "artifacts": [s["stdout"] for s in summary["steps"] if isinstance(s["stdout"], dict)],
    }
    print(json.dumps(final, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Embodiment Runtime Loader.

Provides a pluggable adapter that agent systems (Codex, OpenClaw, etc.) can
directly import and use — the same way they use MCP servers, skills, or tools.

This loader does NOT orchestrate workflows — that's the agent system's job.
It provides: context (what exists), tools (how to call it), and safety gates
(what's forbidden or needs approval).

Usage:
    from embodiments.runtime.loader import EmbodimentLoader

    loader = EmbodimentLoader(config_path="./embodiments.yaml")
    loader.discover()
    loader.activate("g1_usb_dual_view", bindings={
        "robot_local_view": "http://192.168.1.100:8080",
        "external_view":    "http://192.168.1.101:8081",
    })

    # Inject into agent system
    context = loader.get_context()          # EMBODIMENT.md for system prompt
    tools = loader.get_tools()              # OpenAI-format tool definitions

    # Agent system calls tools as needed — it decides the order
    result = loader.dispatch_tool("g1_realsense_color_sensor.capture_frame", {})

    # Cooperation management (human-gated)
    loader.cooperation_revoke("pkg", "node_a", "node_b", "human_01")
    loader.cooperation_rollback("pkg")
"""
from __future__ import annotations

import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


class EmbodimentPackage:
    """A loaded embodiment package: context, tools, cooperation state."""

    def __init__(self, package_dir: Path):
        self.package_dir = package_dir
        self.embodiment_md = ""
        self.embodiment_yaml: Dict[str, Any] = {}
        self.package_id = ""
        self.version = ""
        self.active = False
        self._cooperation_overrides: List[Dict[str, Any]] = []
        self._bindings: Dict[str, str] = {}
        self._load()

    def _load(self):
        md_path = self.package_dir / "EMBODIMENT.md"
        yaml_path = self.package_dir / "embodiment.yaml"
        if md_path.exists():
            self.embodiment_md = md_path.read_text(encoding="utf-8")
        if yaml_path.exists():
            self.embodiment_yaml = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        self.package_id = self.embodiment_yaml.get("package_id", self.package_dir.name)
        self.version = self.embodiment_yaml.get("version", "0.0.0")

    # ── Portability ──────────────────────────────────────────────────────────

    def bind(self, bindings: Dict[str, str]):
        """Set role→endpoint bindings. Resolves @role:xxx in tool_interface."""
        self._bindings = dict(bindings)

    def check_requirements(self, bindings: Dict[str, str]) -> List[str]:
        """Validate bindings against hardware_requirements. Returns unmet list."""
        reqs = self.embodiment_yaml.get("hardware_requirements") or []
        if not reqs:
            return []
        errors = []
        for req in reqs:
            role = req.get("role", "")
            if role not in bindings:
                desc = req.get("description", "")
                hint = req.get("hint", "see hardware_requirements")
                errors.append(f"Missing binding for role '{role}'"
                              + (f" ({desc})" if desc else "")
                              + f". Hint: {hint}")
        return errors

    def _resolve_endpoint(self, endpoint: Optional[str]) -> Optional[str]:
        if endpoint and endpoint.startswith("@role:"):
            role = endpoint[len("@role:"):]
            return self._bindings.get(role) or endpoint
        return endpoint

    # ── Context & Tools ──────────────────────────────────────────────────────

    def get_context(self) -> str:
        """EMBODIMENT.md content — inject into agent's system prompt."""
        return self.embodiment_md

    def get_tools(self) -> List[Dict[str, Any]]:
        """OpenAI function-call format tool definitions from node tool_interfaces."""
        tools = []
        registry = self.embodiment_yaml.get("registry") or {}
        nodes = registry.get("nodes") or []
        forbidden = set((self.embodiment_yaml.get("safety") or {}).get("forbidden_actions") or [])

        for node in nodes:
            ti = node.get("tool_interface")
            if not ti or not ti.get("operations"):
                continue
            node_id = node.get("id", "unknown")

            if self._is_node_dormant(node_id):
                continue

            for op in ti["operations"]:
                safety_class = op.get("safety_class", "safe")
                if safety_class == "forbidden":
                    continue

                tool_name = f"{node_id}.{op['operation_id']}"
                description = op.get("description", "")
                if safety_class == "confirmation":
                    description = f"[REQUIRES CONFIRMATION] {description}"
                elif safety_class == "supervisor":
                    description = f"[REQUIRES SUPERVISOR] {description}"

                tools.append({
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": description,
                        "parameters": op.get("input_schema") or {"type": "object", "properties": {}},
                    },
                    "metadata": {
                        "node_id": node_id,
                        "operation_id": op["operation_id"],
                        "protocol": ti.get("protocol"),
                        "endpoint": self._resolve_endpoint(ti.get("endpoint")),
                        "method": op.get("method"),
                        "path": op.get("path"),
                        "safety_class": safety_class,
                        "latency_estimate_ms": op.get("latency_estimate_ms"),
                    },
                })
        return tools

    # ── Cooperation ──────────────────────────────────────────────────────────

    def get_cooperation_state(self) -> Dict[str, Any]:
        coop = self.embodiment_yaml.get("cooperation_network") or {}
        default_approval = coop.get("default_approval", "approved")
        policy_pairs: List[Dict] = []

        policy_path = self.package_dir / "cooperation_policy.yaml"
        if policy_path.exists():
            policy = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
            policy_pairs = policy.get("pairs") or []
            default_approval = policy.get("default_approval", default_approval)

        effective_pairs = list(policy_pairs)
        for override in self._cooperation_overrides:
            found = False
            for p in effective_pairs:
                if p["source"] == override["source"] and p["target"] == override["target"]:
                    p["approval"] = override["approval"]
                    p["approved_by"] = override.get("operator_id")
                    found = True
                    break
            if not found:
                effective_pairs.append(override)

        return {
            "default_approval": default_approval,
            "effective_pairs": effective_pairs,
            "override_count": len(self._cooperation_overrides),
        }

    def cooperation_approve(self, source: str, target: str, operator_id: str):
        self._cooperation_overrides.append({
            "source": source, "target": target,
            "approval": "approved", "operator_id": operator_id,
            "timestamp": time.time(),
        })

    def cooperation_revoke(self, source: str, target: str, operator_id: str, reason: str = ""):
        self._cooperation_overrides.append({
            "source": source, "target": target,
            "approval": "denied", "operator_id": operator_id,
            "reason": reason, "timestamp": time.time(),
        })

    def cooperation_rollback(self):
        self._cooperation_overrides.clear()

    def _is_node_dormant(self, node_id: str) -> bool:
        state = self.get_cooperation_state()
        if state["default_approval"] == "denied":
            return True
        for p in state["effective_pairs"]:
            if (p["source"] == node_id or p["target"] == node_id) and p.get("approval") == "denied":
                return True
        return False


class EmbodimentLoader:
    """Main loader that agent systems instantiate to use embodiments.

    Responsibilities:
      - Discover and activate packages
      - Provide context (EMBODIMENT.md) and tools (tool_interface)
      - Enforce safety gates on tool dispatch
      - Manage cooperation state (approve/revoke/rollback)
      - Hardware portability via bindings

    NOT responsible for:
      - Workflow orchestration (agent system does this)
      - Deciding execution order (agent system reads EMBODIMENT.md and plans)
      - Routing data between nodes (agent system decides)
    """

    def __init__(self, config_path: Optional[str] = None, config: Optional[Dict[str, Any]] = None):
        self._config = config or {}
        if config_path:
            p = Path(config_path)
            if p.exists():
                self._config = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        self._available: Dict[str, EmbodimentPackage] = {}
        self._active: Dict[str, EmbodimentPackage] = {}

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def discover(self) -> List[str]:
        """Scan configured directories for packages. Auto-activates configured ones."""
        scan_dirs = self._config.get("scan_dirs") or []
        discovered = []
        for d in scan_dirs:
            dp = Path(d)
            if not dp.exists():
                continue
            for zf in dp.glob("*.embodiment.zip"):
                pkg = self._load_from_zip(zf)
                if pkg:
                    self._available[pkg.package_id] = pkg
                    discovered.append(pkg.package_id)
            for child in dp.iterdir():
                if child.is_dir() and (child / "embodiment.yaml").exists():
                    pkg = EmbodimentPackage(child)
                    self._available[pkg.package_id] = pkg
                    discovered.append(pkg.package_id)

        for pid in self._config.get("auto_activate") or []:
            if pid in self._available:
                self.activate(pid)
        return discovered

    def activate(self, package_id: str,
                 bindings: Optional[Dict[str, str]] = None,
                 bindings_path: Optional[str] = None) -> bool:
        """Activate a package with optional hardware bindings."""
        if package_id not in self._available:
            return False
        pkg = self._available[package_id]

        resolved_bindings: Dict[str, str] = {}
        if bindings_path:
            p = Path(bindings_path)
            if p.exists():
                data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                resolved_bindings = data.get("bindings", data) or {}
        if bindings:
            resolved_bindings.update(bindings)

        if resolved_bindings or pkg.embodiment_yaml.get("hardware_requirements"):
            errors = pkg.check_requirements(resolved_bindings)
            if errors:
                raise ValueError(
                    f"Cannot activate '{package_id}': hardware requirements not met:\n"
                    + "\n".join(f"  - {e}" for e in errors)
                )

        if resolved_bindings:
            pkg.bind(resolved_bindings)

        pkg.active = True
        self._active[package_id] = pkg
        return True

    def deactivate(self, package_id: str) -> bool:
        if package_id not in self._active:
            return False
        self._active[package_id].active = False
        del self._active[package_id]
        return True

    def swap(self, old_id: str, new_id: str) -> bool:
        """Atomically swap one active package for another."""
        if new_id not in self._available:
            return False
        self.deactivate(old_id)
        return self.activate(new_id)

    def hot_plug(self, path: str, bindings: Optional[Dict[str, str]] = None) -> Optional[str]:
        """Load and activate a new package from zip or directory."""
        p = Path(path)
        if p.suffix == ".zip" or p.name.endswith(".embodiment.zip"):
            pkg = self._load_from_zip(p)
        elif p.is_dir() and (p / "embodiment.yaml").exists():
            pkg = EmbodimentPackage(p)
        else:
            return None
        if pkg:
            self._available[pkg.package_id] = pkg
            if pkg.embodiment_yaml.get("hardware_requirements") and not bindings:
                return pkg.package_id
            self.activate(pkg.package_id, bindings=bindings)
            return pkg.package_id
        return None

    # ── Agent System Interface ───────────────────────────────────────────────

    def get_context(self) -> str:
        """Combined EMBODIMENT.md from all active packages → system prompt."""
        parts = []
        for pkg in self._active.values():
            parts.append(f"<!-- embodiment: {pkg.package_id} v{pkg.version} -->\n")
            parts.append(pkg.get_context())
            parts.append("\n")
        return "\n".join(parts)

    def get_tools(self) -> List[Dict[str, Any]]:
        """All tool definitions from active packages → register as callable tools."""
        tools = []
        for pkg in self._active.values():
            tools.extend(pkg.get_tools())
        return tools

    def dispatch_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch a tool call with safety gates.

        The agent system calls this after its LLM generates a tool call.
        Returns dispatch metadata; actual HTTP execution is runtime-specific.
        """
        parts = tool_name.split(".", 1)
        if len(parts) != 2:
            return {"success": False, "error": f"Invalid tool name format: {tool_name}"}
        node_id, operation_id = parts

        for pkg in self._active.values():
            for tool in pkg.get_tools():
                if tool["function"]["name"] == tool_name:
                    meta = tool.get("metadata", {})
                    safety_class = meta.get("safety_class", "safe")

                    if safety_class == "forbidden":
                        return {"success": False, "error": "Operation is forbidden"}

                    if safety_class in ("confirmation", "supervisor"):
                        return {
                            "success": False,
                            "requires_approval": True,
                            "safety_class": safety_class,
                            "action": tool_name,
                        }

                    if pkg._is_node_dormant(node_id):
                        return {"success": False, "error": f"Node '{node_id}' is dormant (cooperation denied)"}

                    return {
                        "success": True,
                        "node_id": node_id,
                        "operation_id": operation_id,
                        "protocol": meta.get("protocol"),
                        "endpoint": meta.get("endpoint"),
                        "method": meta.get("method"),
                        "path": meta.get("path"),
                        "arguments": arguments,
                    }

        return {"success": False, "error": f"Tool not found: {tool_name}"}

    # ── Cooperation ──────────────────────────────────────────────────────────

    def get_cooperation_state(self) -> Dict[str, Dict[str, Any]]:
        return {pid: pkg.get_cooperation_state() for pid, pkg in self._active.items()}

    def cooperation_approve(self, package_id: str, source: str, target: str, operator_id: str):
        if package_id in self._active:
            self._active[package_id].cooperation_approve(source, target, operator_id)

    def cooperation_revoke(self, package_id: str, source: str, target: str, operator_id: str, reason: str = ""):
        if package_id in self._active:
            self._active[package_id].cooperation_revoke(source, target, operator_id, reason)

    def cooperation_rollback(self, package_id: str):
        if package_id in self._active:
            self._active[package_id].cooperation_rollback()

    # ── Query ────────────────────────────────────────────────────────────────

    def hardware_requirements(self, package_id: str) -> List[Dict[str, Any]]:
        """What hardware bindings does a package need?"""
        pkg = self._available.get(package_id) or self._active.get(package_id)
        if not pkg:
            return []
        return pkg.embodiment_yaml.get("hardware_requirements") or []

    @property
    def available_packages(self) -> List[str]:
        return list(self._available.keys())

    @property
    def active_packages(self) -> List[str]:
        return list(self._active.keys())

    def status(self) -> Dict[str, Any]:
        return {
            "available": self.available_packages,
            "active": self.active_packages,
            "total_tools": len(self.get_tools()),
        }

    # ── Internal ─────────────────────────────────────────────────────────────

    def _load_from_zip(self, zip_path: Path) -> Optional[EmbodimentPackage]:
        import tempfile
        extract_dir = Path(tempfile.mkdtemp(prefix="embodiment_"))
        try:
            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(extract_dir)
            subdirs = [d for d in extract_dir.iterdir() if d.is_dir()]
            if subdirs and (subdirs[0] / "embodiment.yaml").exists():
                return EmbodimentPackage(subdirs[0])
            if (extract_dir / "embodiment.yaml").exists():
                return EmbodimentPackage(extract_dir)
        except Exception:
            pass
        return None

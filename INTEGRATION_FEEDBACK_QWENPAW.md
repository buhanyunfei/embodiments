# Embodiments Integration Feedback — from QwenPaw Agent System

> Date: 2026-05-09
> Integrator: QwenPaw (Python/FastAPI agent system with React console)
> Packages tested: usb_1080p_camera, g1_usb_dual_view, unitree_g1_sensor_only, unitree_g1
> Hardware available: USB camera at /dev/video0, /dev/video1

---

## Executive Summary

We integrated embodiments into QwenPaw as a peer-level component alongside MCP and Skills. The package format, loader API design, and safety model are solid. However, we found that **the "plug-and-play" promise breaks at the execution boundary** — packages describe interfaces completely but cannot independently execute tool calls. The loader routes but does not dispatch. Adapters are declared but not present. The result: every agent system must build significant custom infrastructure on top of the loader to achieve working hardware interaction.

---

## What Worked Well

1. **Package format is clean** — `embodiment.yaml` + `EMBODIMENT.md` is a good split between machine-readable and agent-readable.
2. **Loader API is well-designed** — `discover() → activate() → get_tools() → get_context()` is the right abstraction.
3. **Safety model is correct** — `safe/confirmation/supervisor/forbidden` classes + cooperation network is the right level of granularity.
4. **Hardware portability** — `@role:xxx` + bindings is elegant. Separating "what hardware I need" from "where that hardware is" is the right design.
5. **`passive_probe.py`** — correctly detected `/dev/video0` and `/dev/video1` on the test machine.
6. **`get_tools()` output** — OpenAI function-call format was directly usable for tool registration.

---

## Problems Found

### Problem 1: Runtime cannot be cleanly imported

**Symptom**: `from embodiments.runtime.loader import EmbodimentLoader` fails in any Python environment that hasn't manually configured `sys.path`.

**Root cause**: The `embodiments/` directory has no `pyproject.toml` or `setup.py`. It is not installable via pip.

**Workaround we used**: Created a `.pth` file in the conda environment's site-packages:
```
echo "/path/to/physclaw_code" > .../site-packages/embodiments_physclaw.pth
```

**Impact**: Every new agent system will hit this on day one. It's the first friction point and it signals "this isn't a real package."

---

### Problem 2: `discover()` has no default scan paths

**Symptom**: `EmbodimentLoader().discover()` returns `[]` unless you explicitly configure `scan_dirs`.

**Root cause**: The loader requires config to know where to look. There is no convention for "where embodiment packages live by default."

**What we expected**: Something like `~/.embodiments/packages/` as a well-known default, similar to how pip uses `site-packages/` or MCP uses `~/.config/`.

**What we had to do**: Hardcode scan paths in our router:
```python
def _get_scan_dirs():
    dirs = []
    dirs.append(Path.home() / ".qwenpaw" / "embodiments")
    dirs.append(Path("/home/sun/wangxin/physclaw_code/embodiments/packages"))
    # ... more fallbacks
    return dirs
```

---

### Problem 3: `dispatch_tool()` does not execute — only returns routing metadata

**Symptom**: After calling `dispatch_tool()`, you get:
```python
{
    "success": True,
    "endpoint": "http://192.168.1.101:8081",
    "method": "POST",
    "path": "/sensors/capture",
    "arguments": {"resolution": "1080p"},
}
```

But nothing actually happens. The HTTP call is not made. Every agent system must build its own HTTP dispatcher.

**Why this matters**: The README promises "3 lines of code" integration. In reality, you also need:
- An HTTP client layer that reads dispatch metadata and executes requests
- Error handling for network failures
- Response parsing back to agent-readable format
- Timeout and retry logic

**Suggestion**: Add an optional `execute_tool()` method that completes the HTTP call:
```python
# For systems that want full control:
meta = loader.dispatch_tool(name, args)  # existing, metadata only

# For systems that want batteries-included:
result = loader.execute_tool(name, args)  # NEW, actually executes
# result = {"success": True, "data": {"frame_path": "/tmp/f.jpg", ...}}
```

This does not make the loader an "execution engine" (no workflow orchestration). It just completes the single tool-call lifecycle that the loader already partially handles.

---

### Problem 4: Packages do not contain working adapters

**Symptom**: `usb_1080p_camera/embodiment.yaml` declares:
```yaml
adapters:
  - entrypoint: adapters/usb_camera_adapter.py
```

But the package directory contains only `adapters/README.md` — a placeholder pointing to Auwomo's external code.

**Impact**: After discover + activate, the agent has tool definitions pointing to an endpoint that doesn't exist. No one is listening on `http://localhost:8081`. The package is a spec without an implementation.

**The deeper issue**: The `adapters/README.md` says:
```
Existing runtime references:
  hub/usb_camera_adapter.py
  hub/usb_camera_frame_adapter.py
```

This means the actual implementation lives in Auwomo PhysClaw (a different project). The embodiment package cannot function independently.

**Assessment**: A "shareable, portable package" that requires code from an external project to function is not truly shareable. If someone git-clones this package on a fresh machine with the same USB camera, they cannot capture a frame.

---

### Problem 5: Probe output format is inconsistent

**Symptom**: 
- `usb_1080p_camera/probes/passive_probe.py` outputs valid JSON: `{"ok": true, "video_devices": ["/dev/video0"]}`
- `unitree_g1/probes/passive_probe.py` outputs Python dict literal: `{'ok': False, 'error': '...'}`

**Impact**: Our integration code needed `ast.literal_eval()` as a fallback after `json.loads()` failed.

**Suggestion**: Spec should mandate: all probes output valid JSON to stdout. No exceptions.

---

### Problem 6: `sensor_probe.py` is a placeholder

**Symptom**: `usb_1080p_camera/probes/sensor_probe.py` contains:
```
use_runtime_usb_camera_adapter_for_frame_capture
```

It does not actually capture a frame. It delegates to the external runtime that doesn't ship with the package.

**Impact**: There is no way to validate "can this package actually talk to hardware" using only the package's own code.

---

### Problem 7: `onboard-embodiment` skill depends on Auwomo infrastructure

**Symptom**: The skill's Step 1 requires:
```bash
python -m robot_node_onboarding.cli discover --robot-id <id>
```

And Step 2 requires:
```bash
curl -X POST http://localhost:8765/topology/robot_profiles/register_card
```

Both are Auwomo-specific. The skill cannot run in QwenPaw or any other agent system without Auwomo's topology runtime.

**Impact**: The onboarding skill — which should be the universal "plug in new hardware" workflow — is locked to one ecosystem.

---

### Problem 8: No mechanism to detect "adapter missing" and trigger generation

**Symptom**: After `discover()`, you know hardware is present (probe says `ok: true`) and tools are defined (yaml has `tool_interface`). But there's no signal that says "this package needs an adapter written before it can be used."

**What we needed**: A readiness check that returns:
```python
{
    "hardware_detected": True,
    "adapter_available": False,  # entrypoint file doesn't exist
    "status": "needs_adapter",
    "adapter_contract": { ... }  # everything needed to generate one
}
```

This would allow an agent system to automatically generate the missing adapter using its own code-writing capabilities.

---

## Architectural Observations

### The "description layer" vs "execution layer" boundary

Current architecture:
```
Package = pure description (yaml + md + probe placeholders)
Execution = external runtime (Auwomo hub/*)
Loader = routing only (safety gate → metadata, no HTTP call)
```

This means the loader provides **everything except the last 10%** — the actual `httpx.post()` to the hardware endpoint. Every agent system must build that last 10% independently.

### The adapter lifecycle gap

```
1. Package declares adapter entrypoint        ✓ (embodiment.yaml)
2. Package ships adapter code                 ✗ (only README placeholder)
3. Loader can start/stop adapter              ✗ (not implemented)
4. Loader can verify adapter is running       ✗ (not implemented)
5. Loader can execute tool calls via adapter  ✗ (dispatch_tool returns metadata only)
```

Steps 2-5 are all left to the integrating agent system. This is a lot of custom code.

### The "shareable" test

**Test**: Can someone with the same hardware (USB camera) use this package in 5 minutes without code from any external project?

**Current answer**: No. They need Auwomo's adapter code or must write their own from the spec.

---

## Optimization Suggestions

### Suggestion 1: Add `pyproject.toml` to `runtime/`

Minimal change, maximum impact:
```toml
[project]
name = "embodiments-runtime"
version = "0.4.0"
dependencies = ["pyyaml"]

[tool.setuptools.packages.find]
where = ["."]
```

Agent systems then: `pip install embodiments-runtime` (or `pip install -e ./embodiments/runtime`).

### Suggestion 2: Define default discovery paths

In `EmbodimentLoader.discover()`, when no `scan_dirs` configured, auto-scan:
```
~/.embodiments/packages/
~/.embodiments/dist/
./embodiments/packages/    (project-local)
```

Convention over configuration.

### Suggestion 3: Packages should ship minimal working adapters

The adapter doesn't need to be complex. For `usb_1080p_camera`, a 50-line stdlib script would suffice:

```python
# adapters/usb_camera_adapter.py
# Minimal HTTP adapter for USB camera — uses ffmpeg for capture
from http.server import HTTPServer, BaseHTTPRequestHandler
import subprocess, json, tempfile

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.respond(200, {"status": "ok"})
    
    def do_POST(self):
        if self.path == "/sensors/capture":
            frame = capture_frame()  # ffmpeg -f v4l2 ...
            self.respond(200, {"frame_path": frame})
    ...

if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8081), Handler).serve_forever()
```

This makes the package self-contained and testable without external dependencies.

### Suggestion 4: Add `execute_tool()` to the loader

```python
def execute_tool(self, tool_name: str, arguments: Dict) -> Dict:
    """Safety-gated dispatch + actual HTTP execution."""
    meta = self.dispatch_tool(tool_name, arguments)
    if not meta.get("success"):
        return meta
    
    import httpx
    endpoint = meta["endpoint"]
    method = meta["method"].upper()
    path = meta["path"]
    url = f"{endpoint}{path}"
    
    resp = httpx.request(method, url, json=arguments, timeout=30)
    return {"success": True, "status_code": resp.status_code, "data": resp.json()}
```

`dispatch_tool()` stays for systems that want full control. `execute_tool()` is for systems that want it to just work.

### Suggestion 5: Add readiness check + adapter contract extraction

```python
def check_readiness(self, package_id: str) -> Dict:
    """Is this package ready to use? Hardware present? Adapter available?"""
    
def get_adapter_contract(self, package_id: str) -> Dict:
    """Extract structured contract for adapter generation by an LLM agent."""
    # Combines: required_paths, operations schemas, probe results, port info
    # Output is directly usable as a code-generation prompt
```

This enables the agentic flow:
```
discover → check_readiness → "needs_adapter" → 
agent reads contract → agent writes adapter → 
validate_adapter → activate
```

### Suggestion 6: Add `validate_adapter()`

```python
def validate_adapter(self, package_id: str, endpoint: str) -> Dict:
    """Hit required_paths on the given endpoint, return pass/fail per route."""
    reqs = self.hardware_requirements(package_id)
    results = {}
    for req in reqs:
        for path_spec in req.get("connection", {}).get("required_paths", []):
            method, path = path_spec.split(" ", 1)
            # ... try request, record pass/fail
    return results
```

### Suggestion 7: Standardize probe output

Add to spec:
- All `passive_probe.py` MUST output valid JSON to stdout
- Required schema: `{"ok": bool, "devices": [...], "error": "..."}`
- Fix existing packages that output Python dict literals

### Suggestion 8: Decouple `onboard-embodiment` from Auwomo

The skill should have two modes:
1. **Full mode** (with Auwomo topology runtime) — current behavior
2. **Standalone mode** (without external runtime) — just: probe → generate adapter contract → validate → activate

Standalone mode would work in ANY agent system.

---

## Priority Ranking

| # | Change | Effort | Impact |
|---|--------|--------|--------|
| 1 | Ship working adapter in `usb_1080p_camera` | Small (50 lines) | Proves the "5-min test" |
| 2 | Add `execute_tool()` to loader | Small (20 lines + httpx) | Closes the execution loop |
| 3 | Add `check_readiness()` + `get_adapter_contract()` | Medium | Enables agentic adapter generation |
| 4 | Add `pyproject.toml` to runtime | Tiny | Clean install path |
| 5 | Default discovery paths | Tiny | Zero-config discovery |
| 6 | Fix probe output formats | Tiny | Spec compliance |
| 7 | Add `validate_adapter()` | Small | Test-before-activate |
| 8 | Decouple onboard skill | Medium | Universal onboarding |

---

## The Agentic Vision

With suggestions 1-7 implemented, the ideal integration flow becomes:

```
Agent System starts
  → loader = EmbodimentLoader()
  → loader.discover()                          # finds usb_1080p_camera
  → loader.check_readiness("usb_1080p_camera")
      → hardware_detected: true
      → adapter_available: false
      → status: "needs_adapter"
  → contract = loader.get_adapter_contract("usb_1080p_camera")
      → {routes, schemas, port, device_paths, constraints}
  → Agent uses its own code-generation skill to write adapter from contract
  → Agent starts adapter subprocess
  → loader.validate_adapter("usb_1080p_camera", "http://localhost:8081")
      → all required_paths pass
  → loader.activate("usb_1080p_camera", bindings={"external_view": "http://localhost:8081"})
  → tools = loader.get_tools()                 # registered, ready to call
  → result = loader.execute_tool("usb_camera_real.capture_frame", {"resolution": "1080p"})
      → {"success": true, "data": {"frame_path": "/tmp/frame.jpg"}}
```

The package provides the **contract**. The agent system provides the **implementation capability**. The loader provides the **lifecycle management**. Each component does what it's best at. None is subordinate to any other.

---

## Conclusion

Embodiments has the right architecture and the right philosophy. The gap is between what's promised ("plug-and-play") and what's delivered ("plug-and-build-your-own-adapter-and-dispatcher"). Closing this gap requires:

1. Packages that are self-contained (ship adapters, not placeholders)
2. A loader that can optionally execute (not just route)
3. A readiness/contract API that enables agentic self-bootstrapping

These changes preserve the identity of embodiments as a peer-level standard while making the "3-line integration" promise real.

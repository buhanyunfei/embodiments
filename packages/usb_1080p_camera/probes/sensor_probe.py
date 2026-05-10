#!/usr/bin/env python3
"""Local USB camera sensor probe placeholder.

Real frame capture should be performed by the runtime adapter to avoid hardcoding devices here.
"""
import json
print(json.dumps({"ok": False, "devices": [], "error": "use_runtime_usb_camera_adapter_for_frame_capture"}))

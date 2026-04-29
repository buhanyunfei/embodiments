#!/usr/bin/env python3
"""Local USB camera passive probe placeholder."""
import glob, json
print(json.dumps({"ok": True, "video_devices": glob.glob('/dev/video*')}))

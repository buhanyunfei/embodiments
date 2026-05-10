#!/usr/bin/env python3
"""Placeholder G1 passive probe.

This script is intentionally read-only. Fill connection details during runtime onboarding.
"""
import json
print(json.dumps({"ok": False, "devices": [], "error": "template_probe_requires_runtime_connection_hints"}))

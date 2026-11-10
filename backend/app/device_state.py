"""Development-only link between the desktop prototype and the local service."""
from __future__ import annotations

import json
import time
from pathlib import Path

HEARTBEAT_MAX_AGE = 8.0


def read_device_state(path: Path | None) -> dict:
    if path is None:
        return {"managed": False, "connected": True, "mode": "unmanaged"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        timestamp = float(data["heartbeat"])
        connected = data.get("connected") is True and 0 <= time.time() - timestamp <= HEARTBEAT_MAX_AGE
        mode = data.get("mode") if data.get("mode") in ("usb-detection", "identity-prototype") else "unknown"
    except (OSError, ValueError, TypeError, KeyError):
        connected, mode = False, "unknown"
    return {"managed": True, "connected": connected, "mode": mode}

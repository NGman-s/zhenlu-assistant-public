"""Run the local service until the desktop prototype reports a disconnect."""
from __future__ import annotations

import asyncio
import os
import time
from contextlib import suppress

import uvicorn

from app.config import Settings
from app.device_state import read_device_state


async def main() -> None:
    settings = Settings()
    if settings.device_state_file is None:
        raise RuntimeError("Managed server requires ZHENLU_DEVICE_STATE_FILE")
    port = int(os.environ.get("ZHENLU_MANAGED_PORT", "8765"))
    grace = float(os.environ.get("ZHENLU_DISCONNECT_GRACE", "30"))
    server = uvicorn.Server(uvicorn.Config("app.main:app", host="127.0.0.1", port=port, log_level="info"))

    async def watch() -> None:
        disconnected_at: float | None = None
        while not server.should_exit:
            if read_device_state(settings.device_state_file)["connected"]:
                disconnected_at = None
            elif disconnected_at is None:
                disconnected_at = time.monotonic()
            elif time.monotonic() - disconnected_at >= grace:
                # Uvicorn 停止接收请求并等待正在处理的请求完成。
                server.should_exit = True
                return
            await asyncio.sleep(0.5)

    watcher = asyncio.create_task(watch())
    try:
        await server.serve()
    finally:
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher


if __name__ == "__main__":
    asyncio.run(main())

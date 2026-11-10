"""Windows USB lifecycle prototype. USB presence is NOT authentication."""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def parse_hex_id(value: str) -> str:
    value = value.removeprefix("0x").removeprefix("0X")
    if not re.fullmatch(r"[0-9a-fA-F]{4}", value):
        raise argparse.ArgumentTypeError("USB VID/PID 必须是四位十六进制数")
    return value.upper()


def usb_present(vid: str, pid: str) -> bool:
    # VID/PID 已严格限制为四位十六进制；仅用于存在性检测，不能证明设备真伪。
    pattern = rf"(?i)VID_{vid}&PID_{pid}(?:&|\\|$)"
    script = ("$ErrorActionPreference='Stop'; "
              "@(Get-PnpDevice -PresentOnly | Where-Object { $_.Status -eq 'OK' -and "
              f"$_.InstanceId -match '{pattern}' }}).Count")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=10,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=True,
    )
    return int(result.stdout.strip()) > 0


def port_is_free(port: int) -> bool:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def health_ready(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/device/status", timeout=0.5) as response:
            return json.load(response).get("managed") is True
    except (OSError, ValueError, urllib.error.URLError):
        return False


def write_state(path: Path, connected: bool, mode: str) -> None:
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps({"connected": connected, "mode": mode, "heartbeat": time.time()}), encoding="utf-8")
    # Windows 有时会在读取状态文件时暂时拒绝替换；等待短暂读取结束。
    for attempt in range(30):
        try:
            os.replace(temp_path, path)
            return
        except PermissionError:
            if attempt == 29:
                raise
            time.sleep(0.01)


def run(args: argparse.Namespace) -> int:
    python = BACKEND / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        print("未找到后端虚拟环境，请先按照 README 安装后端依赖。", flush=True)
        return 1
    if not (ROOT / "frontend" / "dist" / "index.html").is_file():
        print("未找到前端构建文件，请先在 frontend 运行 npm run build。", flush=True)
        return 1
    if not port_is_free(args.port):
        print(f"端口 {args.port} 已被占用；不会接管或关闭已有程序。", flush=True)
        return 1

    detection_errors: tuple[type[Exception], ...] = (OSError, ValueError, subprocess.SubprocessError)
    if args.usb:
        print(f"USB 检测模式：VID={args.vid} PID={args.pid}。仅检测存在，不验证设备身份。按 Ctrl+C 退出。", flush=True)
    else:
        from device_identity import DeviceError, load_public
        detection_errors += (DeviceError,)
        try:
            public_key = args.public_key.read_bytes()
            load_public(public_key)
        except (DeviceError, OSError) as exc:
            print(f"无法加载已登记设备公钥：{exc}", flush=True)
            return 1
        print("开发验证模式：使用已登记公钥检查设备签名；这不是正式授权系统。", flush=True)
    mode = "usb-detection" if args.usb else "identity-prototype"
    connected = False
    previous = False
    process: subprocess.Popen | None = None
    opened = False
    failed = False
    disconnect_seen = False
    last_poll = 0.0
    with tempfile.TemporaryDirectory(prefix="zhenlu-device-") as temp_dir:
        state_path = Path(temp_dir) / "state.json"
        try:
            while True:
                if time.monotonic() - last_poll >= 2:
                    last_poll = time.monotonic()
                    try:
                        if args.identity:
                            from device_identity import verify_device
                            connected = verify_device(public_key, args.com)
                        else:
                            connected = usb_present(args.vid, args.pid)
                    except detection_errors as exc:
                        if connected:
                            print(f"设备检测失败：{exc}", flush=True)
                        connected = False
                write_state(state_path, connected, mode)
                if connected != previous:
                    print("设备已连接。" if connected else "设备已断开；停止新操作，服务将等待后安全关闭。", flush=True)
                    if not connected:
                        failed = False
                        disconnect_seen = process is not None
                    previous = connected
                if process is not None and process.poll() is not None:
                    if connected and not disconnect_seen:
                        print(f"本地服务已退出（{process.returncode}），请检查端口和服务日志；重新连接设备后重试。", flush=True)
                        failed = True
                    process, opened = None, False
                    disconnect_seen = False
                if connected and process is None and not failed:
                    if not port_is_free(args.port):
                        print(f"端口 {args.port} 已被占用；请释放端口后重新连接设备。", flush=True)
                        failed = True
                    else:
                        env = os.environ.copy()
                        env["ZHENLU_DEVICE_STATE_FILE"] = str(state_path)
                        env["ZHENLU_MANAGED_PORT"] = str(args.port)
                        env["ZHENLU_DISCONNECT_GRACE"] = str(args.grace)
                        process = subprocess.Popen([str(python), "-m", "app.managed_server"], cwd=BACKEND, env=env)
                        opened = False
                        print("正在启动本地服务…", flush=True)
                if connected and process is not None and not opened and process.poll() is None and health_ready(args.port):
                    opened = True
                    print(f"本地工作台已就绪：http://127.0.0.1:{args.port}/", flush=True)
                    if not args.no_browser:
                        webbrowser.open(f"http://127.0.0.1:{args.port}/")
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("正在退出连接程序。", flush=True)
        finally:
            # 避免强杀正在写入的请求。服务在心跳消失后自行优雅关闭。
            write_state(state_path, False, mode)
            if process is not None and process.poll() is None:
                print("本地服务将在宽限期后安全关闭。", flush=True)
                try:
                    process.wait(timeout=args.grace + 12)
                except subprocess.TimeoutExpired:
                    print("本地服务仍在完成处理，连接程序不会强制终止它。", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="诊录助手 USB 连接程序（开发原型，非授权系统）")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--usb", action="store_true", help="按 VID/PID 检测 Windows USB 设备")
    mode.add_argument("--identity", action="store_true", help="使用登记公钥验证 ESP32 开发固件")
    parser.add_argument("--vid", type=parse_hex_id)
    parser.add_argument("--pid", type=parse_hex_id)
    parser.add_argument("--com", help="指定设备串口，例如 COM4（仅开发验证模式）")
    parser.add_argument("--public-key", type=Path, default=Path(__file__).resolve().parent / "device-public.der")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--grace", type=float, default=30)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.usb and (not args.vid or not args.pid):
        parser.error("--usb 必须同时提供 --vid 和 --pid")
    if not 1 <= args.port <= 65535 or not 1 <= args.grace <= 300:
        parser.error("端口或宽限时间无效")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())

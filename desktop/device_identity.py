"""Development device proof-of-possession protocol, not a licensing system."""
from __future__ import annotations

import argparse
import hashlib
import os
import time
from pathlib import Path

import serial
from serial.tools import list_ports
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

DOMAIN = b"ZHENLU-DEVICE-AUTH-V1:"
VID = 0x303A
PID = 0x1001


class DeviceError(Exception):
    pass


def locate_port(selected: str | None = None) -> str:
    matches = [port.device for port in list_ports.comports() if port.vid == VID and port.pid == PID]
    if selected:
        matches = [port for port in matches if port.casefold() == selected.casefold()]
    if len(matches) != 1:
        raise DeviceError("未找到唯一的 ESP32-S3 串口，请检查连接并指定 --com。")
    return matches[0]


def exchange(port_name: str, command: bytes, expected_prefix: bytes) -> bytes:
    # 每次只接受完整且有长度上限的协议行；其他启动日志不视作回答。
    try:
        port = serial.Serial(port=None, baudrate=115200, timeout=0.25, write_timeout=1)
        port.dtr = False
        port.rts = False
        port.port = port_name
        with port:
            port.reset_input_buffer()
            port.write(command + b"\n")
            port.flush()
            end = time.monotonic() + 3.0
            pending = b""
            while time.monotonic() < end:
                pending += port.read(256)
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    line = line.strip()
                    if len(line) > 512:
                        raise DeviceError("设备返回的数据过长。")
                    if line.startswith(expected_prefix):
                        try:
                            return bytes.fromhex(line[len(expected_prefix):].decode("ascii"))
                        except (UnicodeDecodeError, ValueError) as exc:
                            raise DeviceError("设备返回了无效数据。") from exc
                    if line.startswith(b"ZL1 ERR "):
                        raise DeviceError("设备报告验证失败。")
                if len(pending) > 512:
                    raise DeviceError("设备返回的数据过长。")
    except (OSError, serial.SerialException) as exc:
        raise DeviceError("无法连接设备串口。") from exc
    raise DeviceError("设备未响应验证请求；请检查固件与串口。")


def load_public(data: bytes) -> ec.EllipticCurvePublicKey:
    try:
        key = serialization.load_der_public_key(data)
    except (ValueError, TypeError) as exc:
        raise DeviceError("设备公钥无效。") from exc
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
        raise DeviceError("设备公钥类型不受支持。")
    return key


def fingerprint(public_der: bytes) -> str:
    return hashlib.sha256(public_der).hexdigest()


def read_public(port: str | None) -> bytes:
    data = exchange(locate_port(port), b"ZL1 PUB", b"ZL1 PUB ")
    load_public(data)
    return data


def verify_response(public_der: bytes, nonce: bytes, signature: bytes) -> bool:
    if len(nonce) != 32:
        return False
    key = load_public(public_der)
    try:
        key.verify(signature, DOMAIN + nonce, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError):
        return False


def verify_device(public_der: bytes, selected: str | None = None) -> bool:
    nonce = os.urandom(32)
    signature = exchange(locate_port(selected), b"ZL1 SIGN " + nonce.hex().encode("ascii"), b"ZL1 SIG ")
    return verify_response(public_der, nonce, signature)


def main() -> int:
    parser = argparse.ArgumentParser(description="ESP32-S3 开发验证：公钥登记与动态挑战")
    parser.add_argument("action", choices=("fingerprint", "enroll", "verify"))
    parser.add_argument("--com", help="指定当前 ESP32 串口，例如 COM4")
    parser.add_argument("--public-key", type=Path, default=Path(__file__).resolve().parent / "device-public.der")
    parser.add_argument("--confirm", help="登记时输入已核对的完整 SHA-256 指纹")
    args = parser.parse_args()
    try:
        if args.action in ("fingerprint", "enroll"):
            public = read_public(args.com)
            digest = fingerprint(public)
            if args.action == "fingerprint":
                print(f"设备公钥 SHA-256：{digest}")
                print("该指纹仅供人工登记确认；目前没有可信生产登记系统。")
                return 0
            if args.confirm is None or args.confirm.lower() != digest:
                raise DeviceError("公钥指纹不匹配；先运行 fingerprint 核对完整指纹。")
            with args.public_key.open("xb") as output:
                output.write(public)
            print(f"已登记公钥：{args.public_key}。如需更换设备，请先安全移除旧的登记文件。")
            return 0
        public = args.public_key.read_bytes()
        if not verify_device(public, args.com):
            raise DeviceError("设备签名与登记公钥不匹配。")
        print("开发验证通过：设备持有登记公钥对应的私钥。")
        return 0
    except (DeviceError, OSError) as exc:
        print(f"验证未完成：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

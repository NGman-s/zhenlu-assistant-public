#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""设备录音代理：串口收流 → 写 WAV → 一次上传整场对话。

配合固件 `firmware/`（Kconfig: 诊录助手-音频回传 → 连续流模式）使用。

固件在串口上输出这些行（921600，16 kHz / 16-bit / 单声道）：

    SESSION_START <起始采样>        检测到说话，可能多次出现
    CHK <绝对采样> <base64>         每 100 ms 一块音频，绝对采样位置
    TURN <起> <止> <段号>           VAD 话轮边界（仅标记）
    SESSION_END <总采样>            静音 8 秒（固件判定），**不在这里上传**
    DROP <跳过到的采样>             环形缓冲被覆盖，音频有缺口

三个关键设计：

1. **一次问诊只传一次**：固件的 8 秒静音只是"这一句说完了"，医生中途
   停顿十几秒很常见。录音代理把连续多个 SESSION 合并成一个文件，
   直到「15 秒没有新音频」才收尾上传。
2. **前导回填**：说话开头的那几块音频可能早于 SESSION_START 到达，
   代理保留最近 3 秒的滚动缓冲，收到 SESSION_START 时回填，
   避免吃掉第一个字。
3. **上传异步**：转写耗时约等于录音时长，绝不能阻塞串口读取，
   否则后续对话会被丢。上传/转写放在后台线程。

用法：

    python recorder.py --port COM5
    python recorder.py --port COM5 --no-upload
    python recorder.py --port COM5 --transcribe
    python recorder.py --replay capture.txt --no-upload   # 离线回放
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import queue
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
import wave
from collections import deque
from datetime import datetime
from pathlib import Path

SAMPLE_RATE = 16000
SAMPLE_BYTES = 2
PRE_ROLL_SAMPLES = SAMPLE_RATE * 3 // 10   # 会话起点前留 300 ms
BACKFILL_SAMPLES = SAMPLE_RATE * 3         # 滚动保留最近 3 秒，用于回填开头


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


class SessionAssembler:
    """把串口行拼成一段会话的 WAV（与硬件无关，便于单元测试）。"""

    def __init__(self, out_dir: Path, sample_rate: int = SAMPLE_RATE,
                 pre_roll_samples: int = PRE_ROLL_SAMPLES) -> None:
        self.out_dir = Path(out_dir)
        self.sample_rate = sample_rate
        self.pre_roll = pre_roll_samples
        self.wav_path: Path | None = None
        self._pcm_path: Path | None = None
        self._handle = None
        self.base = 0
        self.end = 0
        self.chunks = 0
        self.dropped = 0
        self.skipped_before_start = 0
        self.turns: list[tuple[int, int]] = []

    @property
    def active(self) -> bool:
        return self._handle is not None

    def start(self, start_sample: int, stamp: datetime | None = None) -> None:
        self.close()
        self.base = max(start_sample - self.pre_roll, 0)
        self.end = self.base
        self.chunks = 0
        self.dropped = 0
        self.skipped_before_start = 0
        self.turns = []
        stamp = stamp or datetime.now()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        stem = f"session-{stamp.strftime('%Y%m%d-%H%M%S')}"
        candidate = stem
        index = 1
        while (self.out_dir / f"{candidate}.wav").exists() or (self.out_dir / f"{candidate}.pcm").exists():
            index += 1
            candidate = f"{stem}-{index}"
        self._pcm_path = self.out_dir / f"{candidate}.pcm"
        self.wav_path = self.out_dir / f"{candidate}.wav"
        self._handle = self._pcm_path.open("wb")

    def write(self, absolute_sample: int, pcm: bytes) -> None:
        if self._handle is None or not pcm:
            return
        offset = absolute_sample - self.base
        if offset < 0:
            self.skipped_before_start += 1
            return
        self._handle.seek(offset * SAMPLE_BYTES)
        self._handle.write(pcm)
        self.chunks += 1
        end = absolute_sample + len(pcm) // SAMPLE_BYTES
        if end > self.end:
            self.end = end

    def feed(self, line: str) -> str | None:
        line = line.strip()
        if not line:
            return None
        if line.startswith("SESSION_START"):
            parts = line.split()
            if len(parts) < 2:
                return None
            try:
                start = int(parts[1])
            except ValueError:
                return None
            if self.active:
                # 同一场问诊里的下一句：继续写同一个文件，保持时间轴
                return "continue"
            self.start(start)
            return "start"
        if line.startswith("CHK "):
            parts = line.split(" ", 2)
            if len(parts) != 3 or self._handle is None:
                return None
            try:
                self.write(int(parts[1]), base64.b64decode(parts[2], validate=False))
            except (ValueError, binascii.Error):
                return "bad-chunk"
            return "chunk"
        if line.startswith("TURN "):
            parts = line.split()
            if len(parts) >= 3:
                try:
                    self.turns.append((int(parts[1]), int(parts[2])))
                except ValueError:
                    return None
                return "turn"
            return None
        if line.startswith("DROP "):
            self.dropped += 1
            return "drop"
        if line.startswith("SESSION_END"):
            # 只是"这一句说完了"，不结束整场；收尾由调用方在空闲时决定。
            return "sentence-end"
        return None

    def duration_s(self) -> float:
        return max(self.end - self.base, 0) / self.sample_rate

    def close(self) -> Path | None:
        """收尾：补 WAV 头，删掉中间 PCM，返回 WAV 路径。"""
        if self._handle is None:
            return None
        self._handle.flush()
        self._handle.close()
        self._handle = None

        # 最后一句之后的静音不该传上去（按秒计费），只裁尾巴
        end = self.end
        if self.turns:
            last_voice = max(stop for _, stop in self.turns)
            if last_voice > self.base and (end - last_voice) > self.sample_rate:
                end = last_voice + self.sample_rate // 2
        total = max(end - self.base, 0)
        self.end = self.base + total

        assert self._pcm_path is not None and self.wav_path is not None
        with self._pcm_path.open("rb") as source, wave.open(str(self.wav_path), "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(SAMPLE_BYTES)
            target.setframerate(self.sample_rate)
            remaining = total * SAMPLE_BYTES
            while remaining > 0:
                block = source.read(min(1024 * 1024, remaining))
                if not block:
                    block = b"\x00" * min(1024 * 1024, remaining)
                target.writeframes(block)
                remaining -= len(block)
        self._pcm_path.unlink(missing_ok=True)
        return self.wav_path


# ---------------- 后端交互 ----------------

def api_post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
    return json.loads(body) if body else {}


def api_post_file(url: str, wav_path: Path, sha256: str) -> dict:
    boundary = uuid.uuid4().hex
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{wav_path.name}"\r\n'
        f"Content-Type: audio/wav\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")

    body = bytearray()
    body.extend(head)
    with wav_path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            body.extend(block)
    body.extend(tail)

    request = urllib.request.Request(
        url, data=bytes(body), method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "X-Audio-SHA256": sha256,
            "Content-Length": str(len(body)),
        },
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        payload = response.read()
    return json.loads(payload) if payload else {}


def upload(wav_path: Path, api: str, patient_name: str, transcribe: bool = False) -> str | None:
    digest = sha256_of(wav_path)
    try:
        created = api_post_json(f"{api}/api/sessions", {"patient_name": patient_name})
        session_id = created["id"]
        api_post_file(f"{api}/api/sessions/{session_id}/audio", wav_path, digest)
        print(f"  已上传会话 {session_id}", flush=True)
        if transcribe:
            print("  开始转写（耗时约等于录音时长，可继续说下一场）…", flush=True)
            api_post_json(f"{api}/api/sessions/{session_id}/transcript", {})
            print("  转写完成", flush=True)
        print(f"  工作台：{api}/（会话列表里打开“{patient_name}”）", flush=True)
        return session_id
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")[:300]
        print(f"  上传失败 HTTP {exc.code}：{detail}", flush=True)
    except (OSError, ValueError) as exc:
        print(f"  上传失败：{exc}（后端是否已启动？）", flush=True)
    return None


# ---------------- 主流程 ----------------

class DeviceStateWriter:
    """把"设备已连接"心跳写给后端（配合 ZHENLU_DEVICE_STATE_FILE 的受管模式）。

    后端要求心跳不超过 8 秒，这里每 3 秒写一次；进程退出时写一次 connected=false，
    界面就会切成"设备已断开、写操作暂停"。
    """

    def __init__(self, path: Path, interval: float = 3.0, mode: str = "usb-detection") -> None:
        self.path = Path(path)
        self.interval = interval
        self.mode = mode
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _write(self, connected: bool) -> None:
        payload = {"connected": connected, "mode": self.mode, "heartbeat": time.time()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(temp, self.path)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self._write(True)
            except OSError:
                pass

    def start(self) -> None:
        self._write(True)
        self._thread = threading.Thread(target=self._loop, name="device-state", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        try:
            self._write(False)
        except OSError:
            pass


class SerialLineReader:
    """把串口字节流切成完整的行；空闲超过 idle_timeout 秒就结束迭代。

    一条 CHK 行约 4.3 KB，比单次 read 的块大，必须跨读缓存。
    """

    def __init__(self, read, buffer_size: int = 8192, idle_timeout: float = 15.0) -> None:
        self._read = read
        self._buffer_size = buffer_size
        self._idle_timeout = idle_timeout
        self._buf = bytearray()
        self._last_data = time.monotonic()

    def __iter__(self):
        return self

    def __next__(self) -> str:
        while True:
            newline = self._buf.find(b"\n")
            if newline >= 0:
                raw = bytes(self._buf[:newline])
                del self._buf[: newline + 1]
                text = raw.decode("ascii", "ignore").strip()
                if text:
                    return text
                continue
            if time.monotonic() - self._last_data > self._idle_timeout:
                raise StopIteration
            data = self._read(self._buffer_size)
            if data:
                self._buf.extend(data)
                self._last_data = time.monotonic()


# ---------------- 主流程 ----------------

def _guarded_lines(lines):
    """Ctrl+C 时正常结束迭代，让后面的 finalize 仍能把已录内容上传。"""
    try:
        yield from lines
    except KeyboardInterrupt:
        print("  用户中断，立即收尾上传…", flush=True)


def run_lines(lines, args, out_dir: Path) -> list[str]:
    assembler = SessionAssembler(out_dir)
    uploaded: list[str] = []
    chunk_count = 0
    recent: deque[tuple[int, bytes]] = deque()
    recent_samples = 0
    captured = False
    pending_since: float | None = None      # 最后一句结束后开始计时
    grace = float(getattr(args, "idle_timeout", 5.0))

    uploads: queue.Queue = queue.Queue()
    sentinel = object()
    upload_error: list[BaseException] = []

    def worker() -> None:
        while True:
            item = uploads.get()
            try:
                if item is sentinel:
                    return
                session_id = upload(item, args.api, args.patient, args.transcribe)
                if session_id:
                    uploaded.append(session_id)
            except BaseException as exc:  # noqa: BLE001 - 后台线异常要带回主线程
                upload_error.append(exc)
            finally:
                uploads.task_done()

    thread = None
    if not args.no_upload:
        thread = threading.Thread(target=worker, name="upload", daemon=True)
        thread.start()

    def finalize() -> None:
        path = assembler.close()
        if path is None:
            return
        print(f"  会话结束：{assembler.duration_s():.1f} s，"
              f"{path.stat().st_size / 1024 / 1024:.1f} MB，"
              f"话轮 {len(assembler.turns)} 个，丢块 {assembler.dropped}", flush=True)
        if not args.no_upload:
            uploads.put(path)

    for raw in _guarded_lines(lines):
        if raw.startswith("CHK ") and not raw.startswith("CHK #"):
            chunk_count += 1
            if chunk_count == 1:
                print("  已开始接收音频，正在等待说话…（说完停一会儿自动收尾）", flush=True)
            elif chunk_count % 20 == 0 and not assembler.active and not captured:
                print(f"  已接收 {chunk_count / 10:.0f} s 音频，仍未检测到说话"
                      f"（说句话试试；一直没反应就查麦克风接线）", flush=True)

        event = assembler.feed(raw)

        if raw.startswith("CHK "):
            parts = raw.split(" ", 2)
            if len(parts) == 3:
                try:
                    absolute = int(parts[1])
                    pcm = base64.b64decode(parts[2], validate=False)
                except (ValueError, binascii.Error):
                    pcm = b""
                if pcm:
                    recent.append((absolute, pcm))
                    recent_samples += len(pcm) // SAMPLE_BYTES
                    while recent_samples > BACKFILL_SAMPLES and recent:
                        _, old = recent.popleft()
                        recent_samples -= len(old) // SAMPLE_BYTES

        if event == "start":
            captured = True
            print(f"  会话开始（采样 {assembler.base + assembler.pre_roll}，含 300 ms 前导）", flush=True)
            pending_since = None
            # 回填：把 SESSION_START 之前已经流过去的开头补进来
            for absolute, pcm in list(recent):
                if absolute >= assembler.base:
                    assembler.write(absolute, pcm)
        elif event == "continue":
            pending_since = None
        elif event == "turn":
            pending_since = None
        elif event == "sentence-end":
            # 固件静音 8 秒后才发这个；再等 grace 秒没有新内容就收尾
            if assembler.active:
                pending_since = time.monotonic()
        elif event == "drop":
            print("  警告：设备缓冲被覆盖，音频有缺口", flush=True)

        if pending_since is not None and time.monotonic() - pending_since > grace:
            print(f"  最后一句后已静音 {grace:.0f} 秒，收尾。", flush=True)
            finalize()
            pending_since = None
            print("  已收尾，可以继续说下一场；Ctrl+C 退出。", flush=True)

    finalize()

    if thread is not None:
        uploads.put(sentinel)
        thread.join(timeout=600)
        uploads.join()
    if upload_error:
        print(f"  后台上传出错：{upload_error[0]}", flush=True)
    return uploaded


def main() -> int:
    parser = argparse.ArgumentParser(description="ESP32 问诊录音代理")
    parser.add_argument("--port", default="COM5")
    parser.add_argument("--baud", type=int, default=921600)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--out", default=str(Path(__file__).resolve().parent / "recordings"))
    parser.add_argument("--patient", default="设备录音")
    parser.add_argument("--no-upload", action="store_true")
    parser.add_argument("--transcribe", action="store_true", help="上传后立刻触发转写（后台进行，不挡录音）")
    parser.add_argument("--idle-timeout", type=float, default=10.0,
                        help="最后一句结束后再等几秒收尾（固件已先等 8 秒静音，合计约 18 秒）")
    parser.add_argument("--replay", help="回放离线抓包文件，不打开串口")
    parser.add_argument("--state-file",
                        help="把设备心跳写到该文件，配合后端 ZHENLU_DEVICE_STATE_FILE 使用")
    args = parser.parse_args()

    out_dir = Path(args.out)

    writer = None
    if args.state_file:
        writer = DeviceStateWriter(Path(args.state_file))
        writer.start()
        print(f"  设备心跳 → {args.state_file}（后端据此判断“设备已连接”）", flush=True)

    if args.replay:
        print(f"回放 {args.replay}", flush=True)
        with open(args.replay, "r", encoding="utf-8", errors="ignore") as handle:
            uploaded = run_lines(handle, args, out_dir)
        if writer is not None:
            writer.stop()
    else:
        try:
            import serial
        except ImportError:
            sys.stderr.write("缺少 pyserial，先运行：python -m pip install pyserial\n")
            return 2
        print(f"打开 {args.port} @ {args.baud} …", flush=True)
        port = serial.Serial(args.port, args.baud, timeout=0.2)
        port.reset_input_buffer()
        print("就绪：开始问诊即可；停顿不要紧，说完后静音约 18 秒会自动收尾上传"
              "（Ctrl+C 立即收尾）", flush=True)

        uploaded = []
        try:
            # 串口本身不会空闲（固件一直在发流），这里的 idle 只是拔线兜底
            reader = SerialLineReader(port.read, idle_timeout=300)
            uploaded = run_lines(reader, args, out_dir)
        except KeyboardInterrupt:
            print("用户中断", flush=True)
        finally:
            port.close()
            if writer is not None:
                writer.stop()

    if uploaded:
        print(f"本次共上传 {len(uploaded)} 场会话。", flush=True)
    elif not args.no_upload:
        print("没有上传任何会话（没检测到说话，或后端未启动）。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import base64
import importlib.util
import wave
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "recorder.py"
spec = importlib.util.spec_from_file_location("recorder", MODULE_PATH)
recorder = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(recorder)

SR = recorder.SAMPLE_RATE


def chunk_line(absolute_sample: int, samples: int, value: int = 1) -> str:
    pcm = value.to_bytes(2, "little", signed=True) * samples
    return f"CHK {absolute_sample} {base64.b64encode(pcm).decode('ascii')}"


def read_wav(path: Path):
    with wave.open(str(path), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == SR
        return handle.readframes(handle.getnframes())


def test_session_starts_with_pre_roll_and_keeps_timeline(tmp_path):
    assembler = recorder.SessionAssembler(tmp_path)
    assert assembler.feed("SESSION_START 16000") == "start"
    assert assembler.base == 16000 - recorder.PRE_ROLL_SAMPLES

    assert assembler.feed(chunk_line(16000, 1600)) == "chunk"
    path = assembler.close()
    assert path is not None

    data = read_wav(path)
    frames = len(data) // 2
    # 起点回退 300 ms + 100 ms 音频
    assert frames == recorder.PRE_ROLL_SAMPLES + 1600
    # 前导是静音，之后才是音频
    assert data[: recorder.PRE_ROLL_SAMPLES * 2] == b"\x00" * recorder.PRE_ROLL_SAMPLES * 2
    assert data[recorder.PRE_ROLL_SAMPLES * 2 + 2: recorder.PRE_ROLL_SAMPLES * 2 + 4] == b"\x01\x00"


def test_gap_between_chunks_is_filled_with_silence(tmp_path):
    assembler = recorder.SessionAssembler(tmp_path, pre_roll_samples=0)
    assembler.feed("SESSION_START 0")
    assembler.feed(chunk_line(0, 100))
    assembler.feed(chunk_line(4000, 100))
    path = assembler.close()

    data = read_wav(path)
    assert len(data) // 2 == 4100
    assert data[200:4000 * 2] == b"\x00" * (4000 * 2 - 200)
    assert data[4000 * 2: 4000 * 2 + 2] == b"\x01\x00"


def test_audio_before_session_start_is_ignored(tmp_path):
    assembler = recorder.SessionAssembler(tmp_path)
    assembler.start(8000)
    base = assembler.base
    assembler.feed(chunk_line(0, 100))          # 早于起点
    assembler.feed(chunk_line(base + 10, 100))  # 起点之后
    assert assembler.skipped_before_start == 1
    assert assembler.chunks == 1
    assembler.close()


def test_consecutive_sessions_merge_into_one_file(tmp_path):
    """医生的停顿不该把一次问诊拆成多次上传。"""
    assembler = recorder.SessionAssembler(tmp_path, pre_roll_samples=0)
    assert assembler.feed("SESSION_START 0") == "start"
    assembler.feed(chunk_line(0, 100))
    assert assembler.feed("SESSION_END 0") == "sentence-end"   # 只是一句说完
    assert assembler.feed("SESSION_START 16000") == "continue" # 下一句，仍写同一文件
    assembler.feed(chunk_line(16000, 100))
    path = assembler.close()

    data = read_wav(path)
    assert len(data) // 2 == 16100          # 时间轴连续，中间补零
    assert data[100 * 2: 16000 * 2] == b"\x00" * (16000 - 100) * 2


def test_backfill_includes_audio_sent_before_session_start(tmp_path):
    """说话开头那几块可能早于 SESSION_START 到达，必须回填，否则吃掉第一个字。"""
    lines = [
        chunk_line(0, 100),          # 早于 SESSION_START
        chunk_line(100, 100),
        "SESSION_START 200",
        chunk_line(200, 100),
        "SESSION_END 0",
    ]
    args = type("Args", (), {"no_upload": True, "api": "http://x",
                             "patient": "t", "transcribe": False})()
    recorder.run_lines(iter(lines), args, tmp_path)

    files = list(tmp_path.glob("session-*.wav"))
    assert len(files) == 1
    data = read_wav(files[0])
    assert len(data) // 2 == 300     # 起点回退到 0，三块都在
    assert data[0:2] == b"\x01\x00"  # 开头没有被吃掉


def test_drop_and_broken_base64_are_tolerated(tmp_path):
    assembler = recorder.SessionAssembler(tmp_path)
    assembler.feed("SESSION_START 0")
    assert assembler.feed("DROP 123456") == "drop"
    assert assembler.feed("CHK 0 not-base64!!!") == "bad-chunk"
    assert assembler.dropped == 1
    assembler.feed(chunk_line(0, 10))
    assert assembler.chunks == 1
    assembler.close()


def test_unknown_lines_are_ignored(tmp_path):
    assembler = recorder.SessionAssembler(tmp_path)
    assembler.feed("SESSION_START 0")
    assert assembler.feed("I (1234) app: 统计: 帧 502") is None
    assert assembler.feed("TURN 0 100 0") == "turn"
    assert assembler.turns == [(0, 100)]
    assembler.close()


def test_replay_builds_wav_without_upload(tmp_path):
    lines = [
        "SESSION_START 16000",
        chunk_line(16000, 1600),
        "TURN 16000 17600 0",
        "SESSION_END 17600",
    ]
    args = type("Args", (), {"no_upload": True, "api": "http://127.0.0.1:9",
                             "patient": "t", "transcribe": False})()
    uploaded = recorder.run_lines(iter(lines), args, tmp_path)
    assert uploaded == []
    files = list(tmp_path.glob("session-*.wav"))
    assert len(files) == 1
    assert len(read_wav(files[0])) // 2 == recorder.PRE_ROLL_SAMPLES + 1600


def test_serial_reader_reassembles_split_lines(tmp_path):
    payload = (b"SESSION_START 16000\n"
               b"CHK 16000 " + b"A" * 4270 + b"\n"
               b"TURN 1 2 0\n")
    chunks = [payload[i:i + 1000] for i in range(0, len(payload), 1000)]

    def read(_size):
        return chunks.pop(0) if chunks else b""

    reader = iter(recorder.SerialLineReader(read))
    first = next(reader)
    second = next(reader)
    third = next(reader)
    assert first == "SESSION_START 16000"
    assert second.startswith("CHK 16000 AAAA")
    assert len(second) == len("CHK 16000 ") + 4270
    assert third == "TURN 1 2 0"


def test_session_end_triggers_upload(tmp_path):
    """SESSION_END 必须走到 finalize：打印并上传，而不是被静默关掉。"""
    calls = []

    def fake_upload(path, api, patient, transcribe=False):
        calls.append(path)
        return "SID"

    original = recorder.upload
    recorder.upload = fake_upload
    try:
        lines = [
            "SESSION_START 16000",
            chunk_line(16000, 1600),
            "SESSION_END 17600",
        ]
        args = type("Args", (), {"no_upload": False, "api": "http://x",
                                 "patient": "t", "transcribe": False})()
        uploaded = recorder.run_lines(iter(lines), args, tmp_path)
    finally:
        recorder.upload = original

    assert uploaded == ["SID"]
    assert len(calls) == 1 and calls[0].is_file()


def test_trailing_silence_is_trimmed(tmp_path):
    """等 8 秒静音才结束的会话，尾巴不该计入上传时长。"""
    assembler = recorder.SessionAssembler(tmp_path, pre_roll_samples=0)
    assembler.feed("SESSION_START 0")
    assembler.feed(chunk_line(0, 32000))            # 2 s 语音
    assembler.feed("TURN 0 32000 0")
    assembler.feed(chunk_line(32000, 128000))       # 之后 8 s 静音
    assert assembler.feed("SESSION_END 0") == "sentence-end"
    path = assembler.close()

    data = read_wav(path)
    duration = len(data) / 2 / SR
    assert 2.4 <= duration <= 2.6      # 2 s 语音 + 0.5 s 尾巴
    assert assembler.duration_s() == pytest.approx(duration)


def test_device_state_writer_heartbeat(tmp_path):
    """受管模式下，录音代理必须持续写心跳；退出时写 connected=false。"""
    import json
    import time

    path = tmp_path / "state.json"
    writer = recorder.DeviceStateWriter(path, interval=0.2)
    writer.start()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["connected"] is True
    assert data["mode"] == "usb-detection"
    assert abs(time.time() - data["heartbeat"]) < 5

    writer.stop()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["connected"] is False


if __name__ == "__main__":
    # 不依赖 pytest 的独立跑法：python test_recorder.py
    # 可用 REC_TEST_BASE 指定一个已存在、可写的目录（某些受限环境里
    # 进程自己新建的目录反而写不进去）。
    import os
    import shutil
    import traceback

    base = Path(os.environ.get("REC_TEST_BASE") or "recorder-test-cases")
    base.mkdir(parents=True, exist_ok=True)
    failures = 0
    total = 0
    for name in sorted(list(globals())):
        if not name.startswith("test_"):
            continue
        func = globals()[name]
        if not callable(func):
            continue
        total += 1
        case_dir = base / name
        case_dir.mkdir(parents=True, exist_ok=True)
        try:
            func(case_dir)
            print(f"PASS {name}")
        except Exception:  # noqa: BLE001 - 独立跑法需要打印完整堆栈
            failures += 1
            print(f"FAIL {name}")
            traceback.print_exc()
    shutil.rmtree(base, ignore_errors=True)
    print(f"\n{total} 个用例，失败 {failures} 个")
    raise SystemExit(1 if failures else 0)

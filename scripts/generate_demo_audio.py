"""使用 Windows 中文语音合成生成模拟问诊音频，并回写每句话的时间区间。

这是可选的开发脚本；仓库中已经提供生成好的 WAV 文件。运行要求：
- Windows + PowerShell + 已安装 Microsoft Huihui Desktop 中文语音
- 仅用于虚构演示对话，不接入真实患者数据
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = PROJECT_ROOT / "sample-data"
SYNTH_SCRIPT = PROJECT_ROOT / "scripts" / "synthesize_line.ps1"
VOICE = "Microsoft Huihui Desktop"
LEAD_MS = 300
GAP_MS = 450
TAIL_MS = 400


def synth_line(text: str, output: Path, rate: int, temp_dir: Path) -> None:
    text_file = temp_dir / f"{output.stem}.txt"
    text_file.write_text(text, encoding="utf-8")
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SYNTH_SCRIPT),
            "-TextFile",
            str(text_file),
            "-OutputFile",
            str(output),
            "-Rate",
            str(rate),
            "-Voice",
            VOICE,
        ],
        check=True,
        capture_output=True,
    )


def read_frames(path: Path) -> tuple[wave._Wave_params, bytes]:
    with wave.open(str(path), "rb") as handle:
        params = handle.getparams()
        frames = handle.readframes(handle.getnframes())
    return params, frames


def build_case(case_path: Path, temp_root: Path) -> None:
    case = json.loads(case_path.read_text(encoding="utf-8"))
    audio_name = case["audio_file"]
    temp_dir = temp_root / case["key"]
    temp_dir.mkdir(parents=True, exist_ok=True)

    line_files: list[Path] = []
    for index, line in enumerate(case["dialogue"]):
        output = temp_dir / f"line-{index:03d}.wav"
        rate = 1 if line["speaker"] == "医生" else 2
        print(f"  {case['key']} {index + 1}/{len(case['dialogue'])} {line['speaker']}")
        synth_line(line["text"], output, rate, temp_dir)
        line_files.append(output)

    base_params, _ = read_frames(line_files[0])
    sample_rate = base_params.framerate
    sample_width = base_params.sampwidth
    channels = base_params.nchannels
    silence_frame = b"\x00" * sample_width * channels
    lead_frames = int(sample_rate * LEAD_MS / 1000)
    gap_frames = int(sample_rate * GAP_MS / 1000)
    tail_frames = int(sample_rate * TAIL_MS / 1000)

    output_path = SAMPLE_DIR / audio_name
    total_frames = lead_frames
    cursor = lead_frames
    with wave.open(str(output_path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(sample_width)
        output.setframerate(sample_rate)
        output.writeframes(silence_frame * lead_frames)

        for line, line_file in zip(case["dialogue"], line_files, strict=True):
            params, frames = read_frames(line_file)
            if (
                params.framerate != sample_rate
                or params.sampwidth != sample_width
                or params.nchannels != channels
            ):
                raise RuntimeError(f"音频参数不一致：{line_file}")
            line_frames = params.nframes
            line["start_ms"] = round(cursor * 1000 / sample_rate)
            line["end_ms"] = round((cursor + line_frames) * 1000 / sample_rate)
            output.writeframes(frames)
            output.writeframes(silence_frame * gap_frames)
            cursor += line_frames + gap_frames
            total_frames = cursor

        output.writeframes(silence_frame * tail_frames)
        total_frames += tail_frames

    case_path.write_text(
        json.dumps(case, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"已生成 {output_path.name}: {total_frames / sample_rate:.1f}s, "
        f"{output_path.stat().st_size / 1024 / 1024:.2f} MiB"
    )


def main() -> None:
    if shutil.which("powershell") is None:
        raise SystemExit("需要 Windows PowerShell 才能重新生成模拟音频。")
    temp_root = Path(tempfile.mkdtemp(prefix="zhenlu-tts-"))
    try:
        for case_path in sorted(SAMPLE_DIR.glob("case-*.json")):
            print(f"生成 {case_path.name} ...")
            build_case(case_path, temp_root)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    main()

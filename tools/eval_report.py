#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""会话指标汇总：从本地数据库算延迟、字段填充率、来源覆盖率。

只读数据库和上传目录，不修改任何数据。

用法：

    python tools/eval_report.py
    python tools/eval_report.py --db backend/data/zhenlu.db --md report.md
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import wave
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "backend" / "data" / "zhenlu.db"
UPLOAD_DIR = PROJECT_ROOT / "backend" / "data" / "uploads"


def wav_duration_ms(path: Path) -> int | None:
    try:
        with wave.open(str(path), "rb") as handle:
            return round(handle.getnframes() * 1000 / handle.getframerate())
    except (wave.Error, OSError, EOFError):
        return None


def job_seconds(row) -> float | None:
    if not row or not row[0] or not row[1]:
        return None
    from datetime import datetime
    try:
        start = datetime.fromisoformat(str(row[0]))
        end = datetime.fromisoformat(str(row[1]))
    except ValueError:
        return None
    return round((end - start).total_seconds(), 2)


def collect(db_path: Path) -> list[dict]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    out: list[dict] = []
    sessions = con.execute(
        "select id, patient_name, status, created_at from consultation_sessions order by created_at"
    ).fetchall()

    for s in sessions:
        sid = s["id"]
        item: dict = {
            "id": sid,
            "name": s["patient_name"],
            "status": s["status"],
            "audio_s": None,
            "sentences": 0,
            "speech_s": 0.0,
            "fields_total": 0,
            "fields_filled": 0,
            "sources": 0,
            "transcribe_s": None,
            "draft_s": None,
            "billed_s": None,
        }

        audio = con.execute(
            "select stored_relpath, size_bytes, duration_ms from audio_files where session_id=?", (sid,)
        ).fetchone()
        if audio:
            ms = audio["duration_ms"]
            if not ms:
                path = UPLOAD_DIR / str(audio["stored_relpath"]).replace("/", "\\")
                ms = wav_duration_ms(path) if path.is_file() else None
            item["audio_s"] = round(ms / 1000, 2) if ms else None

        transcript = con.execute(
            "select id from transcripts where session_id=?", (sid,)
        ).fetchone()
        if transcript:
            rows = con.execute(
                "select start_ms, end_ms from transcript_segments where transcript_id=?",
                (transcript["id"],),
            ).fetchall()
            item["sentences"] = len(rows)
            item["speech_s"] = round(sum(max((r["end_ms"] or 0) - (r["start_ms"] or 0), 0)
                                         for r in rows) / 1000, 2)

        draft = con.execute(
            "select id from record_drafts where session_id=?", (sid,)
        ).fetchone()
        if draft:
            fields = con.execute(
                "select value, source_segment_ids from draft_fields where draft_id=?",
                (draft["id"],),
            ).fetchall()
            item["fields_total"] = len(fields)
            for f in fields:
                value = (f["value"] or "").strip()
                if value and value != "未提及":
                    item["fields_filled"] += 1
                ids = json.loads(f["source_segment_ids"]) if f["source_segment_ids"] else []
                item["sources"] += len(ids)

        for operation, key in (("transcribe", "transcribe_s"), ("generate", "draft_s")):
            job = con.execute(
                "select started_at, finished_at, metrics from processing_jobs "
                "where session_id=? and operation=? and status='succeeded' "
                "order by created_at desc limit 1",
                (sid, operation),
            ).fetchone()
            if job:
                item[key] = job_seconds((job["started_at"], job["finished_at"]))
                if operation == "transcribe" and job["metrics"]:
                    try:
                        item["billed_s"] = json.loads(job["metrics"]).get("billed_duration_seconds")
                    except ValueError:
                        pass

        out.append(item)
    con.close()
    return out


def render(rows: list[dict]) -> str:
    lines = [
        "| 会话 | 状态 | 音频(s) | 句数 | 语音(s) | 字段填充 | 来源 | 转写(s) | 草稿(s) | 实时率 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in rows:
        rtf = None
        if r["transcribe_s"] and r["audio_s"]:
            rtf = round(r["transcribe_s"] / r["audio_s"], 2)
        lines.append(
            f"| {r['name'][:12]} | {r['status']} | {r['audio_s'] or '-'} | {r['sentences']} | "
            f"{r['speech_s']} | {r['fields_filled']}/{r['fields_total']} | {r['sources']} | "
            f"{r['transcribe_s'] or '-'} | {r['draft_s'] or '-'} | {rtf if rtf is not None else '-'}× |"
        )

    done = [r for r in rows if r["audio_s"]]
    if done:
        avg_rtf = []
        for r in done:
            if r["transcribe_s"] and r["audio_s"]:
                avg_rtf.append(r["transcribe_s"] / r["audio_s"])
        filled = sum(r["fields_filled"] for r in done)
        total = sum(r["fields_total"] for r in done)
        lines.append("")
        lines.append(f"- 有音频的会话：**{len(done)}** 个")
        lines.append(f"- 字段填充率：**{filled}/{total}**"
                     f"（{100 * filled / total:.0f}%）" if total else "- 字段填充率：无数据")
        if avg_rtf:
            lines.append(f"- 转写实时率：平均 **{sum(avg_rtf) / len(avg_rtf):.2f}×**"
                         f"（最小 {min(avg_rtf):.2f}×，最大 {max(avg_rtf):.2f}×）")
        drafts = [r["draft_s"] for r in done if r["draft_s"]]
        if drafts:
            lines.append(f"- 草稿生成耗时：平均 **{sum(drafts) / len(drafts):.1f} s**")
        bills = [r["billed_s"] for r in done if r["billed_s"]]
        if bills:
            lines.append(f"- 供应商计费时长合计：**{sum(bills)} s**")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="会话指标汇总（只读）")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--md", type=Path, help="把报告写到该文件（markdown）")
    args = parser.parse_args()

    if not args.db.is_file():
        print(f"数据库不存在：{args.db}")
        return 1

    rows = collect(args.db)
    if not rows:
        print("没有会话数据。")
        return 0

    report = render(rows)
    print(report)
    if args.md:
        args.md.write_text(report + "\n", encoding="utf-8")
        print(f"\n已写入 {args.md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

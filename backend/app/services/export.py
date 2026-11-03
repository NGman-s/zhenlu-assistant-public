from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from app.models import ConsultationSession

SEPARATOR = "-" * 36


def build_record_text(
    session: ConsultationSession,
    fields: list[dict[str, Any]],
    is_mock: bool,
    confirmed_at: datetime,
    timezone_offset_hours: int,
) -> str:
    local_timezone = timezone(timedelta(hours=timezone_offset_hours))
    timestamp = (
        confirmed_at.replace(tzinfo=UTC)
        .astimezone(local_timezone)
        .strftime("%Y-%m-%d %H:%M")
    )
    patient = session.patient_name
    if session.patient_ref:
        patient += f"（{session.patient_ref}）"

    lines = [
        "诊录助手 · 问诊记录",
        f"患者：{patient}",
        f"会话编号：{session.id}",
        f"确认时间：{timestamp}（UTC+{timezone_offset_hours}）",
        SEPARATOR,
    ]
    for field in fields:
        lines.append(f"{field['label']}：{field['value']}")
    lines.append(SEPARATOR)
    if is_mock:
        lines.append("说明：本记录由诊录助手模拟流程生成，仅供演示，不作为真实医疗记录。")
    else:
        lines.append("说明：本记录由诊录助手辅助生成，已经医生审核确认。")
    return "\n".join(lines)

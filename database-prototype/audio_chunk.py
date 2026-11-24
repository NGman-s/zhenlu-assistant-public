
import sqlite3
from db import get_connection


VALID_UPLOAD_STATUSES = {
    "pending",
    "uploaded",
    "acknowledged",
    "failed"
}

# 允许的状态变化
ALLOWED_TRANSITIONS = {
    "pending": {"uploaded", "failed"},
    "uploaded": {"acknowledged", "failed"},
    "failed": {"uploaded"},
    "acknowledged": set()
}


def _validate_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}不能为空")


def _validate_integer(value, name, minimum=0):
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < minimum
    ):
        raise ValueError(
            f"{name}必须是大于等于{minimum}的整数"
        )


def _require_session(conn, org_id, session_id):
    """检查问诊是否存在并属于指定机构。"""

    row = conn.execute("""
        SELECT session_id
        FROM sessions
        WHERE org_id = ?
          AND session_id = ?
    """, (org_id, session_id)).fetchone()

    if row is None:
        raise ValueError("问诊不存在或不属于指定机构")


def save_audio_chunk(
    org_id,
    session_id,
    seq,
    sample_start,
    sample_count,
    sample_rate,
    codec,
    storage_path,
    payload_len,
    checksum,
    upload_status="pending"
):
    """
    保存音频分片元数据。

    注意：
    这里只保存音频文件路径和索引，
    不保存音频二进制内容。
    """

    _validate_text(org_id, "机构编号")
    _validate_text(session_id, "问诊编号")
    _validate_text(codec, "音频编码")
    _validate_text(storage_path, "音频文件路径")
    _validate_text(checksum, "校验信息")

    _validate_integer(seq, "分片编号", 1)
    _validate_integer(sample_start, "起始采样位置")
    _validate_integer(sample_count, "采样数量", 1)
    _validate_integer(sample_rate, "采样率", 1)
    _validate_integer(payload_len, "载荷长度", 1)

    if upload_status not in VALID_UPLOAD_STATUSES:
        raise ValueError("不支持的音频上传状态")

    conn = get_connection()

    try:
        with conn:

            # 1. 检查问诊所属机构
            _require_session(conn, org_id, session_id)

            # 2. 插入音频分片
            conn.execute("""
                INSERT INTO audio_chunks (
                    org_id,
                    session_id,
                    seq,
                    sample_start,
                    sample_count,
                    sample_rate,
                    codec,
                    storage_path,
                    payload_len,
                    checksum,
                    upload_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                org_id,
                session_id,
                seq,
                sample_start,
                sample_count,
                sample_rate,
                codec,
                storage_path,
                payload_len,
                checksum,
                upload_status
            ))

            # 3. 返回保存结果
            row = conn.execute("""
                SELECT *
                FROM audio_chunks
                WHERE org_id = ?
                  AND session_id = ?
                  AND seq = ?
            """, (
                org_id,
                session_id,
                seq
            )).fetchone()

            return dict(row)

    except sqlite3.IntegrityError as e:
        raise ValueError(
            "分片编号重复或违反数据库约束"
        ) from e

    finally:
        conn.close()


def get_audio_chunks(org_id, session_id):
    """查询指定机构、指定问诊的全部音频分片。"""

    _validate_text(org_id, "机构编号")
    _validate_text(session_id, "问诊编号")

    conn = get_connection()

    try:
        _require_session(conn, org_id, session_id)

        rows = conn.execute("""
            SELECT *
            FROM audio_chunks
            WHERE org_id = ?
              AND session_id = ?
            ORDER BY seq
        """, (org_id, session_id)).fetchall()

        return [dict(row) for row in rows]

    finally:
        conn.close()


def find_audio_chunk_at_time(
    org_id,
    session_id,
    time_ms
):
    """
    根据毫秒时间定位音频分片。

    使用原始采样位置计算，避免先进行浮点数换算。
    时间范围采用左闭右开区间。
    """

    _validate_text(org_id, "机构编号")
    _validate_text(session_id, "问诊编号")
    _validate_integer(time_ms, "录音时间")

    conn = get_connection()

    try:
        _require_session(conn, org_id, session_id)

        row = conn.execute("""
            SELECT *
            FROM audio_chunks

            WHERE org_id = ?
              AND session_id = ?

              AND sample_start * 1000
                    <= ? * sample_rate

              AND ? * sample_rate
                    < (sample_start + sample_count) * 1000

            ORDER BY seq
            LIMIT 1
        """, (
            org_id,
            session_id,
            time_ms,
            time_ms
        )).fetchone()

        if row is None:
            return None

        result = dict(row)

        result["start_ms"] = (
            result["sample_start"] * 1000
            / result["sample_rate"]
        )

        result["end_ms"] = (
            (
                result["sample_start"]
                + result["sample_count"]
            ) * 1000
            / result["sample_rate"]
        )

        return result

    finally:
        conn.close()


def update_audio_chunk_status(
    org_id,
    session_id,
    seq,
    new_status
):
    """更新音频分片上传状态。"""

    _validate_text(org_id, "机构编号")
    _validate_text(session_id, "问诊编号")
    _validate_integer(seq, "分片编号", 1)

    if new_status not in VALID_UPLOAD_STATUSES:
        raise ValueError("不支持的音频上传状态")

    conn = get_connection()

    try:
        with conn:

            # 查询现有分片
            row = conn.execute("""
                SELECT upload_status
                FROM audio_chunks
                WHERE org_id = ?
                  AND session_id = ?
                  AND seq = ?
            """, (
                org_id,
                session_id,
                seq
            )).fetchone()

            if row is None:
                raise ValueError("找不到对应的音频分片")

            current_status = row["upload_status"]

            # 相同状态重复请求视为幂等操作
            if current_status == new_status:
                return current_status

            # 检查状态转换是否合法
            if new_status not in ALLOWED_TRANSITIONS[current_status]:
                raise ValueError(
                    f"不允许从 {current_status} "
                    f"转换为 {new_status}"
                )

            conn.execute("""
                UPDATE audio_chunks
                SET upload_status = ?
                WHERE org_id = ?
                  AND session_id = ?
                  AND seq = ?
            """, (
                new_status,
                org_id,
                session_id,
                seq
            ))

        return new_status

    finally:
        conn.close()

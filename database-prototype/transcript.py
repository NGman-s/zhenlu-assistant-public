
import sqlite3
from db import get_connection


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
    """检查问诊是否存在且属于指定机构。"""

    row = conn.execute("""
        SELECT session_id
        FROM sessions
        WHERE org_id = ?
          AND session_id = ?
    """, (org_id, session_id)).fetchone()

    if row is None:
        raise ValueError("问诊不存在或不属于指定机构")


def save_transcripts(org_id, session_id, sentences):
    """
    批量保存语音转写句子。

    sentences 格式：

    [
        {
            "sentence_no": 1,
            "content": "我咳嗽三天了。",
            "start_ms": 0,
            "end_ms": 2500
        }
    ]
    """

    _validate_text(org_id, "机构编号")
    _validate_text(session_id, "问诊编号")

    if not isinstance(sentences, list) or not sentences:
        raise ValueError("转写数据不能为空")

    sentence_numbers = set()

    # 1. 检查输入数据
    for item in sentences:

        if not isinstance(item, dict):
            raise ValueError("每条转写数据必须是字典")

        number = item.get("sentence_no")
        content = item.get("content")
        start_ms = item.get("start_ms")
        end_ms = item.get("end_ms")

        _validate_integer(number, "句子编号", 1)

        if number in sentence_numbers:
            raise ValueError("本批次存在重复句子编号")

        sentence_numbers.add(number)

        _validate_text(content, "转写文本")

        # 起止时间必须同时存在或同时为空
        if (start_ms is None) != (end_ms is None):
            raise ValueError("起止时间必须同时提供")

        if start_ms is not None:
            _validate_integer(start_ms, "开始时间")
            _validate_integer(end_ms, "结束时间")

            if end_ms <= start_ms:
                raise ValueError("结束时间必须大于开始时间")

    conn = get_connection()

    try:
        with conn:

            # 2. 检查问诊归属
            _require_session(conn, org_id, session_id)

            # 3. 检查是否存在重复编号
            for number in sentence_numbers:

                existing = conn.execute("""
                    SELECT sentence_id
                    FROM transcript_sentences
                    WHERE org_id = ?
                      AND session_id = ?
                      AND sentence_no = ?
                """, (
                    org_id,
                    session_id,
                    number
                )).fetchone()

                if existing:
                    raise ValueError(
                        f"第 {number} 条转写已经存在"
                    )

            # 4. 准备批量数据
            data = [
                (
                    org_id,
                    session_id,
                    item["sentence_no"],
                    item["content"],
                    item.get("start_ms"),
                    item.get("end_ms")
                )
                for item in sentences
            ]

            # 5. 批量写入
            conn.executemany("""
                INSERT INTO transcript_sentences (
                    org_id,
                    session_id,
                    sentence_no,
                    content,
                    start_ms,
                    end_ms
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, data)

        return len(data)

    except sqlite3.IntegrityError as e:
        raise ValueError("转写数据违反数据库约束") from e

    finally:
        conn.close()


def get_transcripts(org_id, session_id):
    """查询指定机构、指定问诊的全部转写句子。"""

    _validate_text(org_id, "机构编号")
    _validate_text(session_id, "问诊编号")

    conn = get_connection()

    try:
        _require_session(conn, org_id, session_id)

        rows = conn.execute("""
            SELECT
                sentence_id,
                org_id,
                session_id,
                sentence_no,
                content,
                start_ms,
                end_ms,
                created_at
            FROM transcript_sentences
            WHERE org_id = ?
              AND session_id = ?
            ORDER BY sentence_no
        """, (org_id, session_id)).fetchall()

        return [dict(row) for row in rows]

    finally:
        conn.close()


def find_transcript_at_time(org_id, session_id, time_ms):
    """
    根据音频时间定位转写句子。

    使用左闭右开区间：
    start_ms <= time_ms < end_ms
    """

    _validate_text(org_id, "机构编号")
    _validate_text(session_id, "问诊编号")
    _validate_integer(time_ms, "录音时间")

    conn = get_connection()

    try:
        _require_session(conn, org_id, session_id)

        row = conn.execute("""
            SELECT
                sentence_id,
                sentence_no,
                content,
                start_ms,
                end_ms
            FROM transcript_sentences

            WHERE org_id = ?
              AND session_id = ?
              AND start_ms IS NOT NULL
              AND end_ms IS NOT NULL
              AND start_ms <= ?
              AND ? < end_ms

            ORDER BY sentence_no
            LIMIT 1
        """, (
            org_id,
            session_id,
            time_ms,
            time_ms
        )).fetchone()

        return dict(row) if row else None

    finally:
        conn.close()

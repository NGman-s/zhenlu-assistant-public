
import json
import sqlite3

from db import get_connection


VALID_VERSION_TYPES = {
    "AI草稿",
    "医生修改版",
    "医生确认版"
}

VALID_INFORMATION_STATUSES = {
    "recorded",
    "not_mentioned",
    "explicitly_denied"
}


def _validate_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}不能为空")


def _validate_version_fields(fields):

    if not isinstance(fields, list) or not fields:
        raise ValueError("病历字段不能为空")

    names = set()

    for item in fields:

        if not isinstance(item, dict):
            raise ValueError("病历字段必须使用字典表示")

        field_name = item.get("field_name")
        field_value = item.get("field_value")
        status = item.get("information_status")
        source_numbers = item.get("source_sentence_nos", [])

        _validate_text(field_name, "字段名称")

        if field_name in names:
            raise ValueError(f"病历字段重复：{field_name}")

        names.add(field_name)

        if status not in VALID_INFORMATION_STATUSES:
            raise ValueError("不支持的信息状态")

        if status == "not_mentioned":

            if field_value is not None:
                raise ValueError(
                    "未提及的信息必须使用 None 保存"
                )

            if source_numbers:
                raise ValueError(
                    "未提及的信息不能关联不存在的原始句子"
                )

        else:

            _validate_text(field_value, "病历字段内容")

        if not isinstance(source_numbers, list):
            raise ValueError("原始句子编号必须使用列表")

        seen = set()

        for number in source_numbers:

            if (
                not isinstance(number, int)
                or isinstance(number, bool)
                or number <= 0
            ):
                raise ValueError("原始句子编号必须是正整数")

            if number in seen:
                raise ValueError("同一个字段不能重复关联相同句子")

            seen.add(number)


def save_medical_record_version(
    org_id,
    session_id,
    version_no,
    version_type,
    created_by,
    fields
):
    """
    保存一份新的病历版本。

    AI草稿：created_by 必须为 None。
    医生修改版、医生确认版：必须提供有效医生账号。

    旧版本不会被覆盖。
    """

    _validate_text(org_id, "机构编号")
    _validate_text(session_id, "问诊编号")

    if (
        not isinstance(version_no, int)
        or isinstance(version_no, bool)
        or version_no <= 0
    ):
        raise ValueError("版本号必须是正整数")

    if version_type not in VALID_VERSION_TYPES:
        raise ValueError("不支持的病历版本类型")

    if version_type == "AI草稿":

        if created_by is not None:
            raise ValueError("AI草稿的创建者应为 None")

    else:
        _validate_text(created_by, "医生账号编号")

    _validate_version_fields(fields)

    conn = get_connection()

    try:

        with conn:

            # 1. 检查问诊
            session = conn.execute("""
                SELECT session_id
                FROM sessions
                WHERE org_id = ?
                  AND session_id = ?
            """, (org_id, session_id)).fetchone()

            if session is None:
                raise ValueError("问诊不存在或不属于指定机构")

            # 2. 检查医生账号
            if created_by is not None:

                doctor = conn.execute("""
                    SELECT user_id
                    FROM users
                    WHERE org_id = ?
                      AND user_id = ?
                      AND role = 'doctor'
                      AND is_active = 1
                """, (org_id, created_by)).fetchone()

                if doctor is None:
                    raise ValueError(
                        "创建者不是该机构的有效医生"
                    )

            # 3. 检查版本是否重复
            existing = conn.execute("""
                SELECT version_id
                FROM record_versions
                WHERE org_id = ?
                  AND session_id = ?
                  AND version_no = ?
            """, (
                org_id,
                session_id,
                version_no
            )).fetchone()

            if existing:
                raise ValueError("该病历版本已经存在")

            # 4. 创建病历版本
            cursor = conn.execute("""
                INSERT INTO record_versions (
                    org_id,
                    session_id,
                    version_no,
                    version_type,
                    created_by
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                org_id,
                session_id,
                version_no,
                version_type,
                created_by
            ))

            version_id = cursor.lastrowid

            # 5. 保存病历字段及原始来源
            for item in fields:

                cursor = conn.execute("""
                    INSERT INTO record_fields (
                        org_id,
                        session_id,
                        version_id,
                        field_name,
                        field_value,
                        information_status
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    org_id,
                    session_id,
                    version_id,
                    item["field_name"],
                    item["field_value"],
                    item["information_status"]
                ))

                field_id = cursor.lastrowid

                # 6. 关联对应的原始转写句子
                for sentence_no in item.get(
                    "source_sentence_nos", []
                ):

                    sentence = conn.execute("""
                        SELECT sentence_id
                        FROM transcript_sentences
                        WHERE org_id = ?
                          AND session_id = ?
                          AND sentence_no = ?
                    """, (
                        org_id,
                        session_id,
                        sentence_no
                    )).fetchone()

                    if sentence is None:
                        raise ValueError(
                            f"找不到第 {sentence_no} 条原始转写"
                        )

                    conn.execute("""
                        INSERT INTO field_sources (
                            org_id,
                            session_id,
                            field_id,
                            sentence_id
                        )
                        VALUES (?, ?, ?, ?)
                    """, (
                        org_id,
                        session_id,
                        field_id,
                        sentence["sentence_id"]
                    ))

            # 7. 写入关键操作日志
            action_map = {
                "AI草稿": "record_draft_created",
                "医生修改版": "record_edited",
                "医生确认版": "record_confirmed"
            }

            details = json.dumps({
                "version_no": version_no,
                "version_type": version_type,
                "field_count": len(fields)
            }, ensure_ascii=False)

            conn.execute("""
                INSERT INTO operation_logs (
                    org_id,
                    session_id,
                    user_id,
                    action,
                    target_type,
                    target_id,
                    details
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                org_id,
                session_id,
                created_by,
                action_map[version_type],
                "record_version",
                str(version_id),
                details
            ))

        return version_id

    except sqlite3.IntegrityError as e:
        raise ValueError(
            "病历数据违反数据库约束"
        ) from e

    finally:
        conn.close()

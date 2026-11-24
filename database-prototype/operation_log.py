
import json
import sqlite3

from db import get_connection


def _validate_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}不能为空")


def _format_details(details):
    """将字典或列表转换为JSON字符串。"""

    if details is None:
        return None

    if isinstance(details, (dict, list)):
        return json.dumps(
            details,
            ensure_ascii=False
        )

    if isinstance(details, str):
        return details

    raise ValueError("details必须是字符串、字典、列表或None")


def insert_operation_log(
    conn,
    org_id,
    action,
    target_type,
    target_id=None,
    session_id=None,
    user_id=None,
    details=None
):
    """
    在已有数据库连接和事务中写入日志。

    供其他业务模块复用。
    不单独提交事务。
    """

    _validate_text(org_id, "机构编号")
    _validate_text(action, "操作类型")
    _validate_text(target_type, "目标类型")

    if target_id is not None:
        _validate_text(target_id, "目标编号")

    if session_id is not None:
        _validate_text(session_id, "问诊编号")

        session = conn.execute("""
            SELECT session_id
            FROM sessions
            WHERE org_id = ?
              AND session_id = ?
        """, (org_id, session_id)).fetchone()

        if session is None:
            raise ValueError("问诊不存在或不属于指定机构")

    if user_id is not None:
        _validate_text(user_id, "用户编号")

        user = conn.execute("""
            SELECT user_id
            FROM users
            WHERE org_id = ?
              AND user_id = ?
        """, (org_id, user_id)).fetchone()

        if user is None:
            raise ValueError("用户不存在或不属于指定机构")

    details_text = _format_details(details)

    cursor = conn.execute("""
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
        user_id,
        action,
        target_type,
        target_id,
        details_text
    ))

    return cursor.lastrowid


def _row_to_dict(row):
    """将日志记录转换为字典，并尝试解析JSON详情。"""

    result = dict(row)

    if result["details"] is not None:
        try:
            result["details"] = json.loads(
                result["details"]
            )
        except (json.JSONDecodeError, TypeError):
            pass

    return result


def create_operation_log(
    org_id,
    action,
    target_type,
    target_id=None,
    session_id=None,
    user_id=None,
    details=None
):
    """独立创建一条操作日志。"""

    conn = get_connection()

    try:
        with conn:

            log_id = insert_operation_log(
                conn=conn,
                org_id=org_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                session_id=session_id,
                user_id=user_id,
                details=details
            )

            row = conn.execute("""
                SELECT *
                FROM operation_logs
                WHERE log_id = ?
            """, (log_id,)).fetchone()

            return _row_to_dict(row)

    except sqlite3.IntegrityError as e:
        raise ValueError("日志数据违反数据库约束") from e

    finally:
        conn.close()


def get_operation_log(org_id, log_id):
    """根据机构编号和日志编号查询日志。"""

    _validate_text(org_id, "机构编号")

    if (
        not isinstance(log_id, int)
        or isinstance(log_id, bool)
        or log_id <= 0
    ):
        raise ValueError("日志编号必须是正整数")

    conn = get_connection()

    try:
        row = conn.execute("""
            SELECT *
            FROM operation_logs
            WHERE org_id = ?
              AND log_id = ?
        """, (org_id, log_id)).fetchone()

        return _row_to_dict(row) if row else None

    finally:
        conn.close()


def list_operation_logs(
    org_id,
    session_id=None,
    user_id=None,
    action=None,
    limit=100
):
    """
    查询指定机构的操作日志。

    可以按问诊、用户、操作类型筛选。
    """

    _validate_text(org_id, "机构编号")

    if session_id is not None:
        _validate_text(session_id, "问诊编号")

    if user_id is not None:
        _validate_text(user_id, "用户编号")

    if action is not None:
        _validate_text(action, "操作类型")

    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or limit <= 0
    ):
        raise ValueError("查询数量必须是正整数")

    sql = """
        SELECT
            log_id,
            org_id,
            session_id,
            user_id,
            action,
            target_type,
            target_id,
            details,
            created_at

        FROM operation_logs

        WHERE org_id = ?
    """

    params = [org_id]

    if session_id is not None:
        sql += " AND session_id = ?"
        params.append(session_id)

    if user_id is not None:
        sql += " AND user_id = ?"
        params.append(user_id)

    if action is not None:
        sql += " AND action = ?"
        params.append(action)

    sql += " ORDER BY log_id DESC LIMIT ?"
    params.append(limit)

    conn = get_connection()

    try:
        rows = conn.execute(sql, params).fetchall()

        return [
            _row_to_dict(row)
            for row in rows
        ]

    finally:
        conn.close()

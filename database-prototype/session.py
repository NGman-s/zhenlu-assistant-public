
import sqlite3
from db import get_connection


# 必须与 schema.sql 中定义的状态一致
VALID_STATUSES = {
    "recording",
    "processing",
    "reviewing",
    "completed",
    "cancelled"
}


def _validate_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}不能为空")


def _validate_status(status):
    if status not in VALID_STATUSES:
        raise ValueError("不支持的问诊状态")


def _get_session_row(conn, org_id, session_id):
    """查询问诊及所属机构、医生信息。"""

    row = conn.execute("""
        SELECT
            s.session_id,
            s.org_id,
            o.org_name,
            s.doctor_id,
            u.username AS doctor_username,
            u.display_name AS doctor_name,
            s.status,
            s.started_at,
            s.ended_at,
            s.created_at

        FROM sessions s

        JOIN organizations o
            ON s.org_id = o.org_id

        JOIN users u
            ON s.org_id = u.org_id
           AND s.doctor_id = u.user_id

        WHERE s.org_id = ?
          AND s.session_id = ?

    """, (org_id, session_id)).fetchone()

    return dict(row) if row else None


def create_session(
    session_id,
    org_id,
    doctor_id,
    status="recording"
):
    """
    创建新的问诊会话。

    必须提供机构编号和医生账号编号。
    医生必须属于指定机构且处于启用状态。
    """

    _validate_text(session_id, "会话编号")
    _validate_text(org_id, "机构编号")
    _validate_text(doctor_id, "医生编号")
    _validate_status(status)

    conn = get_connection()

    try:
        with conn:

            # 检查机构
            org = conn.execute("""
                SELECT org_id
                FROM organizations
                WHERE org_id = ?
                  AND is_active = 1
            """, (org_id,)).fetchone()

            if org is None:
                raise ValueError("机构不存在或已经停用")

            # 检查医生及机构归属
            doctor = conn.execute("""
                SELECT user_id
                FROM users
                WHERE user_id = ?
                  AND org_id = ?
                  AND role = 'doctor'
                  AND is_active = 1
            """, (doctor_id, org_id)).fetchone()

            if doctor is None:
                raise ValueError(
                    "医生不存在、不属于该机构或已经停用"
                )

            # 创建问诊
            conn.execute("""
                INSERT INTO sessions (
                    session_id,
                    org_id,
                    doctor_id,
                    status,
                    started_at
                )
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                session_id,
                org_id,
                doctor_id,
                status
            ))

            return _get_session_row(
                conn,
                org_id,
                session_id
            )

    except sqlite3.IntegrityError as e:
        raise ValueError(
            "问诊编号重复或违反数据库约束"
        ) from e

    finally:
        conn.close()


def get_session(org_id, session_id):
    """
    根据机构编号和问诊编号查询会话。

    必须同时提供机构编号。
    """

    _validate_text(org_id, "机构编号")
    _validate_text(session_id, "会话编号")

    conn = get_connection()

    try:
        return _get_session_row(
            conn,
            org_id,
            session_id
        )

    finally:
        conn.close()


def update_session_status(
    org_id,
    session_id,
    status
):
    """修改指定机构中的问诊状态。"""

    _validate_text(org_id, "机构编号")
    _validate_text(session_id, "会话编号")
    _validate_status(status)

    conn = get_connection()

    try:
        with conn:

            cursor = conn.execute("""
                UPDATE sessions

                SET
                    status = ?,
                    ended_at = CASE
                        WHEN ? IN ('completed', 'cancelled')
                        THEN COALESCE(
                            ended_at,
                            CURRENT_TIMESTAMP
                        )
                        ELSE NULL
                    END

                WHERE org_id = ?
                  AND session_id = ?

            """, (
                status,
                status,
                org_id,
                session_id
            ))

            if cursor.rowcount == 0:
                raise ValueError("找不到对应的问诊会话")

            return _get_session_row(
                conn,
                org_id,
                session_id
            )

    finally:
        conn.close()


def list_sessions(
    org_id,
    doctor_id=None,
    status=None,
    limit=100
):
    """
    查询某家机构的问诊列表。

    可根据医生编号和问诊状态进一步筛选。
    """

    _validate_text(org_id, "机构编号")

    if doctor_id is not None:
        _validate_text(doctor_id, "医生编号")

    if status is not None:
        _validate_status(status)

    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or limit <= 0
    ):
        raise ValueError("查询数量必须是正整数")

    sql = """
        SELECT
            s.session_id,
            s.org_id,
            o.org_name,
            s.doctor_id,
            u.display_name AS doctor_name,
            s.status,
            s.started_at,
            s.ended_at,
            s.created_at

        FROM sessions s

        JOIN organizations o
            ON s.org_id = o.org_id

        JOIN users u
            ON s.org_id = u.org_id
           AND s.doctor_id = u.user_id

        WHERE s.org_id = ?
    """

    params = [org_id]

    if doctor_id is not None:
        sql += " AND s.doctor_id = ?"
        params.append(doctor_id)

    if status is not None:
        sql += " AND s.status = ?"
        params.append(status)

    sql += " ORDER BY s.created_at DESC LIMIT ?"
    params.append(limit)

    conn = get_connection()

    try:
        rows = conn.execute(sql, params).fetchall()

        return [dict(row) for row in rows]

    finally:
        conn.close()

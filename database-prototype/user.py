
import sqlite3
from db import get_connection


def create_user(
    user_id,
    org_id,
    username,
    display_name,
    role="doctor"
):
    """在指定机构中创建医生或管理员账号。"""

    values = {
        "user_id": user_id,
        "org_id": org_id,
        "username": username,
        "display_name": display_name
    }

    for name, value in values.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name}不能为空")

    if role not in ("admin", "doctor"):
        raise ValueError("角色只能是admin或doctor")

    conn = get_connection()

    try:
        with conn:

            # 检查所属机构是否存在且启用
            org = conn.execute("""
                SELECT org_id
                FROM organizations
                WHERE org_id = ?
                  AND is_active = 1
            """, (org_id,)).fetchone()

            if org is None:
                raise ValueError("机构不存在或已经停用")

            conn.execute("""
                INSERT INTO users (
                    user_id,
                    org_id,
                    username,
                    display_name,
                    role
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                user_id,
                org_id,
                username,
                display_name,
                role
            ))

            row = conn.execute("""
                SELECT
                    user_id,
                    org_id,
                    username,
                    display_name,
                    role,
                    is_active,
                    created_at
                FROM users
                WHERE user_id = ?
                  AND org_id = ?
            """, (user_id, org_id)).fetchone()

            return dict(row)

    except sqlite3.IntegrityError as e:
        raise ValueError(
            "用户编号或机构内用户名重复，或者数据不符合约束"
        ) from e

    finally:
        conn.close()


def get_user(user_id, org_id):
    """
    根据用户编号和机构编号查询用户。

    必须同时提供机构编号，避免跨机构查询。
    """

    conn = get_connection()

    try:
        row = conn.execute("""
            SELECT
                user_id,
                org_id,
                username,
                display_name,
                role,
                is_active,
                created_at
            FROM users
            WHERE user_id = ?
              AND org_id = ?
        """, (user_id, org_id)).fetchone()

        return dict(row) if row else None

    finally:
        conn.close()


def list_users(
    org_id,
    role=None,
    include_inactive=False
):
    """
    查询某家机构的用户。

    org_id为必填参数，不能跨机构查询。
    """

    if not isinstance(org_id, str) or not org_id.strip():
        raise ValueError("必须指定机构编号")

    if role is not None and role not in ("admin", "doctor"):
        raise ValueError("角色只能是admin或doctor")

    sql = """
        SELECT
            user_id,
            org_id,
            username,
            display_name,
            role,
            is_active,
            created_at
        FROM users
        WHERE org_id = ?
    """

    params = [org_id]

    if role is not None:
        sql += " AND role = ?"
        params.append(role)

    if not include_inactive:
        sql += " AND is_active = 1"

    sql += " ORDER BY user_id"

    conn = get_connection()

    try:
        rows = conn.execute(sql, params).fetchall()

        return [dict(row) for row in rows]

    finally:
        conn.close()


def set_user_status(user_id, org_id, is_active):
    """启用或停用指定机构中的用户。"""

    if is_active not in (0, 1, True, False):
        raise ValueError("用户状态必须是0或1")

    conn = get_connection()

    try:
        with conn:
            cursor = conn.execute("""
                UPDATE users
                SET is_active = ?
                WHERE user_id = ?
                  AND org_id = ?
            """, (int(is_active), user_id, org_id))

            if cursor.rowcount == 0:
                raise ValueError("找不到对应的用户")

            row = conn.execute("""
                SELECT
                    user_id,
                    org_id,
                    username,
                    display_name,
                    role,
                    is_active,
                    created_at
                FROM users
                WHERE user_id = ?
                  AND org_id = ?
            """, (user_id, org_id)).fetchone()

            return dict(row)

    finally:
        conn.close()

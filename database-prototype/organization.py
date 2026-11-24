
import sqlite3
from db import get_connection


def create_organization(org_id, org_name):
    """创建门诊机构。"""

    if not isinstance(org_id, str) or not org_id.strip():
        raise ValueError("机构编号不能为空")

    if not isinstance(org_name, str) or not org_name.strip():
        raise ValueError("机构名称不能为空")

    conn = get_connection()

    try:
        with conn:
            conn.execute("""
                INSERT INTO organizations (
                    org_id,
                    org_name
                )
                VALUES (?, ?)
            """, (org_id, org_name))

            row = conn.execute("""
                SELECT *
                FROM organizations
                WHERE org_id = ?
            """, (org_id,)).fetchone()

            return dict(row)

    except sqlite3.IntegrityError as e:
        raise ValueError("机构编号已经存在或数据不符合约束") from e

    finally:
        conn.close()


def get_organization(org_id):
    """查询指定机构。"""

    conn = get_connection()

    try:
        row = conn.execute("""
            SELECT *
            FROM organizations
            WHERE org_id = ?
        """, (org_id,)).fetchone()

        return dict(row) if row else None

    finally:
        conn.close()


def list_organizations(include_inactive=False):
    """查询机构列表。"""

    conn = get_connection()

    try:
        if include_inactive:
            rows = conn.execute("""
                SELECT *
                FROM organizations
                ORDER BY created_at
            """).fetchall()

        else:
            rows = conn.execute("""
                SELECT *
                FROM organizations
                WHERE is_active = 1
                ORDER BY created_at
            """).fetchall()

        return [dict(row) for row in rows]

    finally:
        conn.close()


def set_organization_status(org_id, is_active):
    """启用或停用机构。"""

    if is_active not in (0, 1, True, False):
        raise ValueError("机构状态必须是0或1")

    conn = get_connection()

    try:
        with conn:
            cursor = conn.execute("""
                UPDATE organizations
                SET is_active = ?
                WHERE org_id = ?
            """, (int(is_active), org_id))

            if cursor.rowcount == 0:
                raise ValueError("找不到对应的机构")

            row = conn.execute("""
                SELECT *
                FROM organizations
                WHERE org_id = ?
            """, (org_id,)).fetchone()

            return dict(row)

    finally:
        conn.close()

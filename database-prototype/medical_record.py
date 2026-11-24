
from db import get_connection


def _validate_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}不能为空")


def get_medical_record(org_id, session_id):
    """
    查询一场问诊的完整病历。

    返回机构、医生、病历版本、字段内容和原始转写来源。
    """

    _validate_text(org_id, "机构编号")
    _validate_text(session_id, "问诊编号")

    conn = get_connection()

    try:
        # 1. 查询问诊及所属机构、医生
        session = conn.execute("""
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
              AND s.session_id = ?

        """, (org_id, session_id)).fetchone()

        if session is None:
            return None

        # 2. 查询病历版本、字段和原始来源
        rows = conn.execute("""
            SELECT
                rv.version_id,
                rv.version_no,
                rv.version_type,
                rv.created_by,
                creator.display_name AS created_by_name,
                rv.created_at,

                rf.field_id,
                rf.field_name,
                rf.field_value,
                rf.information_status,

                ts.sentence_id,
                ts.sentence_no,
                ts.content,
                ts.start_ms,
                ts.end_ms

            FROM record_versions rv

            LEFT JOIN users creator
                ON rv.org_id = creator.org_id
               AND rv.created_by = creator.user_id

            LEFT JOIN record_fields rf
                ON rv.org_id = rf.org_id
               AND rv.session_id = rf.session_id
               AND rv.version_id = rf.version_id

            LEFT JOIN field_sources fs
                ON rf.org_id = fs.org_id
               AND rf.session_id = fs.session_id
               AND rf.field_id = fs.field_id

            LEFT JOIN transcript_sentences ts
                ON fs.org_id = ts.org_id
               AND fs.session_id = ts.session_id
               AND fs.sentence_id = ts.sentence_id

            WHERE rv.org_id = ?
              AND rv.session_id = ?

            ORDER BY
                rv.version_no,
                rf.field_id,
                ts.sentence_no

        """, (org_id, session_id)).fetchall()

        # 3. 创建返回结构
        result = {
            "session": dict(session),
            "versions": []
        }

        versions = {}

        for row in rows:

            version_id = row["version_id"]

            # 创建病历版本
            if version_id not in versions:
                versions[version_id] = {
                    "version_id": version_id,
                    "version_no": row["version_no"],
                    "version_type": row["version_type"],
                    "created_by": row["created_by"],
                    "created_by_name": row["created_by_name"],
                    "created_at": row["created_at"],
                    "fields": {}
                }

            # 没有病历字段时跳过
            if row["field_id"] is None:
                continue

            fields = versions[version_id]["fields"]

            field_id = row["field_id"]

            # 创建病历字段
            if field_id not in fields:
                fields[field_id] = {
                    "field_name": row["field_name"],
                    "field_value": row["field_value"],
                    "information_status": row["information_status"],
                    "sources": []
                }

            # 添加原始转写来源
            if row["sentence_id"] is not None:
                fields[field_id]["sources"].append({
                    "sentence_id": row["sentence_id"],
                    "sentence_no": row["sentence_no"],
                    "content": row["content"],
                    "start_ms": row["start_ms"],
                    "end_ms": row["end_ms"]
                })

        # 4. 转换为列表
        for version in versions.values():
            version["fields"] = list(
                version["fields"].values()
            )

            result["versions"].append(version)

        return result

    finally:
        conn.close()


def get_record_version(org_id, session_id, version_no):
    """查询指定问诊中的某一个病历版本。"""

    if (
        not isinstance(version_no, int)
        or isinstance(version_no, bool)
        or version_no <= 0
    ):
        raise ValueError("版本号必须是正整数")

    record = get_medical_record(org_id, session_id)

    if record is None:
        return None

    for version in record["versions"]:
        if version["version_no"] == version_no:
            return version

    return None

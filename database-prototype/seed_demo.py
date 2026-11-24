
import json
from db import get_connection


ORG_ID = "ORG_DEMO"


def insert_transcripts(conn, session_id, sentences):
    """批量插入指定问诊的转写句子。"""

    data = [
        (
            ORG_ID,
            session_id,
            item["sentence_no"],
            item["content"],
            item["start_ms"],
            item["end_ms"]
        )
        for item in sentences
    ]

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


def insert_record_version(
    conn,
    session_id,
    version_no,
    version_type,
    created_by,
    fields
):
    """插入病历版本、字段以及字段来源关联。"""

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
        ORG_ID,
        session_id,
        version_no,
        version_type,
        created_by
    ))

    version_id = cursor.lastrowid

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
            ORG_ID,
            session_id,
            version_id,
            item["field_name"],
            item["field_value"],
            item["information_status"]
        ))

        field_id = cursor.lastrowid

        for sentence_no in item["source_sentence_nos"]:

            sentence = conn.execute("""
                SELECT sentence_id
                FROM transcript_sentences
                WHERE org_id = ?
                  AND session_id = ?
                  AND sentence_no = ?
            """, (
                ORG_ID,
                session_id,
                sentence_no
            )).fetchone()

            if sentence is None:
                raise ValueError(
                    f"找不到转写句子：{session_id} / {sentence_no}"
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
                ORG_ID,
                session_id,
                field_id,
                sentence["sentence_id"]
            ))

    return version_id


def seed_demo():

    conn = get_connection()

    try:

        with conn:

            # 1. 检查数据库是否已经有业务数据
            tables = [
                "organizations",
                "users",
                "sessions",
                "audio_chunks",
                "transcript_sentences",
                "record_versions",
                "record_fields",
                "field_sources",
                "operation_logs"
            ]

            for table in tables:

                count = conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]

                if count > 0:
                    raise RuntimeError(
                        f"{table} 已经存在数据。"
                        "为防止重复写入，本次初始化已取消。"
                    )

            # 2. 创建模拟门诊机构
            conn.execute("""
                INSERT INTO organizations (
                    org_id,
                    org_name
                )
                VALUES (?, ?)
            """, (
                ORG_ID,
                "诊录助手示例门诊"
            ))

            # 3. 创建四名医生
            doctors = [
                ("U001", "doctor_zhang", "张医生"),
                ("U002", "doctor_li", "李医生"),
                ("U003", "doctor_wang", "王医生"),
                ("U004", "doctor_zhao", "赵医生")
            ]

            conn.executemany("""
                INSERT INTO users (
                    user_id,
                    org_id,
                    username,
                    display_name,
                    role
                )
                VALUES (?, ?, ?, ?, 'doctor')
            """, [
                (user_id, ORG_ID, username, name)
                for user_id, username, name in doctors
            ])

            # 4. 创建四场问诊
            sessions = [
                ("S001", "U001"),
                ("S002", "U002"),
                ("S003", "U003"),
                ("S004", "U004")
            ]

            conn.executemany("""
                INSERT INTO sessions (
                    session_id,
                    org_id,
                    doctor_id,
                    status
                )
                VALUES (?, ?, ?, 'completed')
            """, [
                (session_id, ORG_ID, doctor_id)
                for session_id, doctor_id in sessions
            ])

            # 5. 保存四场问诊的转写数据
            transcript_data = {

                "S001": [
                    (1, "我咳嗽三天了。", 0, 2500),
                    (2, "晚上咳得更明显。", 2500, 5000),
                    (3, "没有发热。", 5000, 7000)
                ],

                "S002": [
                    (1, "最近头痛两天。", 0, 2200),
                    (2, "没有恶心呕吐。", 2200, 4300)
                ],

                "S003": [
                    (1, "最近出现鼻塞。", 0, 2000),
                    (2, "早上比较明显。", 2000, 4000),
                    (3, "没有明显发热。", 4000, 6500)
                ],

                "S004": [
                    (1, "我最近有点咽痛。", 0, 2000),
                    (2, "吞咽的时候比较明显。", 2000, 4500),
                    (3, "已经持续两天了。", 4500, 7000)
                ]
            }

            for session_id, sentences in transcript_data.items():

                insert_transcripts(
                    conn,
                    session_id,
                    [
                        {
                            "sentence_no": no,
                            "content": content,
                            "start_ms": start_ms,
                            "end_ms": end_ms
                        }
                        for no, content, start_ms, end_ms in sentences
                    ]
                )

            # 6. 保存 S004 的三个音频分片索引
            for seq in range(1, 4):

                sample_start = (seq - 1) * 3200

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
                    ORG_ID,
                    "S004",
                    seq,
                    sample_start,
                    3200,
                    16000,
                    "PCM16LE",
                    f"audio/S004/chunk_{seq:04d}.pcm",
                    6400,
                    f"demo-checksum-{seq:03d}",
                    "acknowledged"
                ))

            # 7. 定义三份病历内容
            def make_fields(history_value):

                return [
                    {
                        "field_name": "主诉",
                        "field_value": "咳嗽三天。",
                        "information_status": "recorded",
                        "source_sentence_nos": [1]
                    },
                    {
                        "field_name": "现病史",
                        "field_value": history_value,
                        "information_status": "recorded",
                        "source_sentence_nos": [2]
                    },
                    {
                        "field_name": "发热情况",
                        "field_value": "否认发热。",
                        "information_status": "explicitly_denied",
                        "source_sentence_nos": [3]
                    },
                    {
                        "field_name": "既往史",
                        "field_value": None,
                        "information_status": "not_mentioned",
                        "source_sentence_nos": []
                    }
                ]

            # 8. 保存 AI 草稿
            insert_record_version(
                conn,
                "S001",
                1,
                "AI草稿",
                None,
                make_fields("晚上咳得更明显。")
            )

            # 9. 保存医生修改版
            insert_record_version(
                conn,
                "S001",
                2,
                "医生修改版",
                "U001",
                make_fields("夜间咳嗽较明显。")
            )

            # 10. 保存医生确认版
            insert_record_version(
                conn,
                "S001",
                3,
                "医生确认版",
                "U001",
                make_fields("夜间咳嗽较明显。")
            )

            # 11. 记录关键操作日志
            logs = [
                (
                    ORG_ID, "S001", "U001",
                    "record_version_created",
                    "record_version", "2",
                    json.dumps(
                        {"description": "医生修改病历"},
                        ensure_ascii=False
                    )
                ),
                (
                    ORG_ID, "S001", "U001",
                    "record_confirmed",
                    "record_version", "3",
                    json.dumps(
                        {"description": "医生确认病历"},
                        ensure_ascii=False
                    )
                ),
                (
                    ORG_ID, "S004", "U004",
                    "audio_chunks_indexed",
                    "audio_chunk", "1",
                    json.dumps(
                        {"description": "模拟音频分片索引"},
                        ensure_ascii=False
                    )
                )
            ]

            conn.executemany("""
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
            """, logs)

        # 12. 输出数据统计
        print("========== 模拟数据生成成功 ==========")

        for table in tables:

            count = conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]

            print(f"{table}: {count} 条")

        errors = conn.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        print(
            "\n外键完整性：",
            "正常" if not errors else errors
        )

        print("\n模拟机构：诊录助手示例门诊")
        print("模拟医生：4 名")
        print("模拟问诊：S001、S002、S003、S004")

    finally:
        conn.close()


if __name__ == "__main__":
    seed_demo()

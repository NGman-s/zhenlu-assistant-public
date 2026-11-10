
from db import DB_PATH, get_connection

from organization import create_organization
from user import create_user

from session import (
    create_session,
    get_session,
    update_session_status
)

from transcript import (
    save_transcripts,
    get_transcripts,
    find_transcript_at_time
)

from audio_chunk import (
    save_audio_chunk,
    get_audio_chunks,
    find_audio_chunk_at_time,
    update_audio_chunk_status
)

from record_writer import save_medical_record_version

from medical_record import (
    get_medical_record,
    get_record_version
)

from operation_log import (
    create_operation_log,
    list_operation_logs
)


# 1. 确保使用独立测试数据库
if DB_PATH.name != "diagnosis_integration_test.db":
    raise RuntimeError(
        "数据库路径不正确！请先切换到集成测试数据库。"
    )


ORG_ID = "ORG_IT"
USER_ID = "U_IT_DOCTOR"
SESSION_ID = "S_IT_001"


print("当前数据库：", DB_PATH)


# ==================================================
# 2. 创建机构和医生
# ==================================================

print("\n========== 1. 创建机构和医生 ==========")

organization = create_organization(
    ORG_ID,
    "集成测试门诊"
)

doctor = create_user(
    USER_ID,
    ORG_ID,
    "integration_doctor",
    "集成测试医生",
    "doctor"
)

print("机构：", organization)
print("医生：", doctor)


# ==================================================
# 3. 创建问诊
# ==================================================

print("\n========== 2. 创建问诊会话 ==========")

session = create_session(
    SESSION_ID,
    ORG_ID,
    USER_ID,
    "recording"
)

print(session)

assert session["org_id"] == ORG_ID
assert session["doctor_id"] == USER_ID


# ==================================================
# 4. 保存语音转写
# ==================================================

print("\n========== 3. 保存语音转写 ==========")

sentences = [
    {
        "sentence_no": 1,
        "content": "我咳嗽三天了。",
        "start_ms": 0,
        "end_ms": 2500
    },
    {
        "sentence_no": 2,
        "content": "晚上咳得更明显。",
        "start_ms": 2500,
        "end_ms": 5000
    },
    {
        "sentence_no": 3,
        "content": "没有发热。",
        "start_ms": 5000,
        "end_ms": 7000
    }
]

count = save_transcripts(
    ORG_ID,
    SESSION_ID,
    sentences
)

print("成功保存转写：", count)

assert count == 3



# ==================================================
# 5. 保存音频分片
# ==================================================

print("\n========== 4. 保存音频分片 ==========")

# 每个分片覆盖200ms
# 35个分片覆盖完整的7000ms问诊

for seq in range(1, 36):

    sample_start = (seq - 1) * 3200

    save_audio_chunk(
        org_id=ORG_ID,
        session_id=SESSION_ID,
        seq=seq,
        sample_start=sample_start,
        sample_count=3200,
        sample_rate=16000,
        codec="PCM16LE",
        storage_path=(
            f"audio/S_IT_001/chunk_{seq:04d}.pcm"
        ),
        payload_len=6400,
        checksum=f"integration-checksum-{seq}",
        upload_status="pending"
    )

chunks = get_audio_chunks(
    ORG_ID,
    SESSION_ID
)

print("成功保存音频分片：", len(chunks))

assert len(chunks) == 35

# ==================================================
# 6. 测试音频上传状态
# ==================================================

print("\n========== 5. 测试音频上传状态 ==========")

update_audio_chunk_status(
    ORG_ID,
    SESSION_ID,
    1,
    "uploaded"
)

update_audio_chunk_status(
    ORG_ID,
    SESSION_ID,
    1,
    "acknowledged"
)

chunks = get_audio_chunks(
    ORG_ID,
    SESSION_ID
)

print("分片1最终状态：", chunks[0]["upload_status"])

assert chunks[0]["upload_status"] == "acknowledged"



# ==================================================
# 7. 测试音频和转写定位
# ==================================================

print("\n========== 6. 测试时间定位 ==========")

query_time = 3000

transcript = find_transcript_at_time(
    ORG_ID,
    SESSION_ID,
    query_time
)

audio = find_audio_chunk_at_time(
    ORG_ID,
    SESSION_ID,
    query_time
)

print(
    f"{query_time}ms对应转写：",
    transcript["content"]
)

print(
    f"{query_time}ms对应音频分片：",
    audio["seq"]
)

assert transcript is not None
assert audio is not None

assert transcript["sentence_no"] == 2
assert audio["seq"] == 16

assert audio["start_ms"] == 3000.0
assert audio["end_ms"] == 3200.0

# ==================================================
# 8. 准备三种病历版本
# ==================================================

print("\n========== 7. 保存三个病历版本 ==========")


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


version_1 = save_medical_record_version(
    ORG_ID,
    SESSION_ID,
    1,
    "AI草稿",
    None,
    make_fields("晚上咳得更明显，无发热。")
)

version_2 = save_medical_record_version(
    ORG_ID,
    SESSION_ID,
    2,
    "医生修改版",
    USER_ID,
    make_fields("夜间咳嗽较明显，无发热。")
)

version_3 = save_medical_record_version(
    ORG_ID,
    SESSION_ID,
    3,
    "医生确认版",
    USER_ID,
    make_fields("夜间咳嗽较明显，无发热。")
)

print("AI草稿 ID：", version_1)
print("医生修改版 ID：", version_2)
print("医生确认版 ID：", version_3)


# ==================================================
# 9. 查询完整病历
# ==================================================

print("\n========== 8. 查询完整病历 ==========")

record = get_medical_record(
    ORG_ID,
    SESSION_ID
)

assert record is not None
assert len(record["versions"]) == 3

for version in record["versions"]:

    print(
        "\n版本",
        version["version_no"],
        version["version_type"]
    )

    for field in version["fields"]:

        print(
            field["field_name"],
            "：",
            field["field_value"]
        )

        for source in field["sources"]:
            print("原始来源：", source["content"])


# ==================================================
# 10. 测试操作日志
# ==================================================

print("\n========== 9. 检查操作日志 ==========")

create_operation_log(
    org_id=ORG_ID,
    session_id=SESSION_ID,
    user_id=USER_ID,
    action="integration_test_finished",
    target_type="session",
    target_id=SESSION_ID,
    details={
        "result": "success"
    }
)

logs = list_operation_logs(
    ORG_ID,
    session_id=SESSION_ID
)

print("操作日志数量：", len(logs))

for log in logs:
    print(log["action"])

# 三个病历版本自动产生三条日志，
# 另外手动创建了一条集成测试完成日志。
assert len(logs) == 4


# ==================================================
# 11. 完成问诊
# ==================================================

print("\n========== 10. 完成问诊 ==========")

session = update_session_status(
    ORG_ID,
    SESSION_ID,
    "completed"
)

print(session["status"])

assert session["status"] == "completed"


# ==================================================
# 12. 检查机构隔离
# ==================================================

print("\n========== 11. 检查机构隔离 ==========")

assert get_session(
    "ORG_DEMO",
    SESSION_ID
) is None

assert get_medical_record(
    "ORG_DEMO",
    SESSION_ID
) is None

try:
    get_transcripts("ORG_DEMO", SESSION_ID)

except ValueError:
    print("转写跨机构访问已阻止")

else:
    raise AssertionError("转写机构隔离失败")


# ==================================================
# 13. 检查数据库完整性
# ==================================================

print("\n========== 12. 数据库完整性检查 ==========")

conn = get_connection()

try:

    foreign_errors = conn.execute(
        "PRAGMA foreign_key_check"
    ).fetchall()

    integrity = conn.execute(
        "PRAGMA integrity_check"
    ).fetchone()[0]

    print("外键完整性：", "正常" if not foreign_errors else foreign_errors)
    print("数据库完整性：", integrity)

    assert not foreign_errors
    assert integrity == "ok"

    print("\n各表数据统计：")

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

        print(f"{table}: {count}")

finally:
    conn.close()


print("\n====================================")
print("诊录助手数据库全流程集成测试通过！")
print("====================================")


from db import DB_PATH, get_connection

from session import create_session, get_session
from transcript import save_transcripts, get_transcripts

from record_writer import save_medical_record_version

from medical_record import (
    get_medical_record,
    get_record_version
)


if DB_PATH.name != "diagnosis_final_test.db":
    raise RuntimeError("请先切换到测试数据库")


ORG_ID = "ORG_TEST"
SESSION_ID = "S008"
DOCTOR_ID = "U_TEST_DOCTOR"


print("当前测试数据库：", DB_PATH)


print("\n========== 1. 准备问诊 ==========")

session = get_session(ORG_ID, SESSION_ID)

if session is None:
    session = create_session(
        SESSION_ID,
        ORG_ID,
        DOCTOR_ID,
        "reviewing"
    )

print(session)


print("\n========== 2. 准备转写数据 ==========")

existing = get_transcripts(ORG_ID, SESSION_ID)

if not existing:

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

else:
    print("转写数据已经存在，跳过重复保存")


# 三个病历版本使用相同的字段结构
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
            "source_sentence_nos": [2, 3]
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


print("\n========== 3. 保存 AI 草稿 ==========")

if get_record_version(ORG_ID, SESSION_ID, 1) is None:

    version_id = save_medical_record_version(
        ORG_ID,
        SESSION_ID,
        1,
        "AI草稿",
        None,
        make_fields("晚上咳得更明显，无发热。")
    )

    print("AI草稿保存成功，ID：", version_id)

else:
    print("AI草稿已经存在，跳过")


print("\n========== 4. 保存医生修改版 ==========")

if get_record_version(ORG_ID, SESSION_ID, 2) is None:

    version_id = save_medical_record_version(
        ORG_ID,
        SESSION_ID,
        2,
        "医生修改版",
        DOCTOR_ID,
        make_fields("夜间咳嗽较明显，无发热。")
    )

    print("医生修改版保存成功，ID：", version_id)

else:
    print("医生修改版已经存在，跳过")


print("\n========== 5. 保存医生确认版 ==========")

if get_record_version(ORG_ID, SESSION_ID, 3) is None:

    version_id = save_medical_record_version(
        ORG_ID,
        SESSION_ID,
        3,
        "医生确认版",
        DOCTOR_ID,
        make_fields("夜间咳嗽较明显，无发热。")
    )

    print("医生确认版保存成功，ID：", version_id)

else:
    print("医生确认版已经存在，跳过")


print("\n========== 6. 查询完整病历 ==========")

record = get_medical_record(
    ORG_ID,
    SESSION_ID
)

assert record is not None
assert len(record["versions"]) == 3

for version in record["versions"]:

    print(
        f"\n版本 {version['version_no']}："
        f"{version['version_type']}"
    )

    for field in version["fields"]:

        print(
            f"{field['field_name']}："
            f"{field['field_value']}"
        )

        print(
            "信息状态：",
            field["information_status"]
        )

        for source in field["sources"]:
            print(
                "原始来源：",
                source["content"],
                source["start_ms"],
                "-",
                source["end_ms"],
                "ms"
            )


print("\n========== 7. 测试单独查询版本 ==========")

confirmed = get_record_version(
    ORG_ID,
    SESSION_ID,
    3
)

assert confirmed is not None
assert confirmed["version_type"] == "医生确认版"

print("单独查询版本3成功")


print("\n========== 8. 测试重复版本保护 ==========")

try:
    save_medical_record_version(
        ORG_ID,
        SESSION_ID,
        3,
        "医生确认版",
        DOCTOR_ID,
        make_fields("重复测试")
    )

except ValueError as e:
    print("重复版本保护正常：", e)

else:
    raise AssertionError("重复版本没有被阻止")


print("\n========== 9. 测试错误来源与事务回滚 ==========")

invalid_fields = [
    {
        "field_name": "测试字段",
        "field_value": "测试内容",
        "information_status": "recorded",
        "source_sentence_nos": [999]
    }
]

try:
    save_medical_record_version(
        ORG_ID,
        SESSION_ID,
        4,
        "医生修改版",
        DOCTOR_ID,
        invalid_fields
    )

except ValueError as e:
    print("错误来源检测正常：", e)

else:
    raise AssertionError("不存在的来源句子没有被阻止")

# 检查事务是否真正回滚
assert get_record_version(
    ORG_ID,
    SESSION_ID,
    4
) is None

print("事务回滚正常，版本4没有残留")


print("\n========== 10. 测试跨机构隔离 ==========")

other_record = get_medical_record(
    "ORG_DEMO",
    SESSION_ID
)

assert other_record is None

print("跨机构查询保护正常")


print("\n========== 11. 检查操作日志 ==========")

conn = get_connection()

try:
    logs = conn.execute("""
        SELECT action, target_type, target_id
        FROM operation_logs
        WHERE org_id = ?
          AND session_id = ?
        ORDER BY log_id
    """, (
        ORG_ID,
        SESSION_ID
    )).fetchall()

    for log in logs:
        print(dict(log))

    assert len(logs) == 3

finally:
    conn.close()


print("\n所有病历管理测试通过！")

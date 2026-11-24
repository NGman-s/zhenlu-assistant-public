
from db import DB_PATH

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


# 防止误操作正式数据库
if DB_PATH.name != "diagnosis_final_test.db":
    raise RuntimeError("请先切换到测试数据库")


ORG_ID = "ORG_TEST"
SESSION_ID = "S006"
DOCTOR_ID = "U_TEST_DOCTOR"


print("当前测试数据库：", DB_PATH)


print("\n========== 1. 准备问诊会话 ==========")

session = get_session(ORG_ID, SESSION_ID)

if session is None:

    session = create_session(
        SESSION_ID,
        ORG_ID,
        DOCTOR_ID,
        "processing"
    )

print(session)


print("\n========== 2. 保存转写数据 ==========")

existing = get_transcripts(ORG_ID, SESSION_ID)

if not existing:

    sentences = [
        {
            "sentence_no": 1,
            "content": "患者咳嗽三天。",
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

    print("成功保存：", count, "条")

else:
    print("测试数据已经存在，跳过重复保存")


print("\n========== 3. 查询全部转写 ==========")

results = get_transcripts(
    ORG_ID,
    SESSION_ID
)

for item in results:
    print(item)

assert len(results) == 3


print("\n========== 4. 根据时间定位原文 ==========")

result = find_transcript_at_time(
    ORG_ID,
    SESSION_ID,
    3000
)

print("查询时间：3000 ms")
print("定位结果：", result)

assert result is not None
assert result["sentence_no"] == 2
assert result["content"] == "晚上咳得更明显。"


print("\n========== 5. 测试重复保存保护 ==========")

try:
    save_transcripts(
        ORG_ID,
        SESSION_ID,
        [
            {
                "sentence_no": 1,
                "content": "重复测试",
                "start_ms": 0,
                "end_ms": 1000
            }
        ]
    )

except ValueError as e:
    print("重复保存保护正常：", e)

else:
    raise AssertionError("重复保存没有被阻止")


print("\n========== 6. 测试错误时间范围 ==========")

try:
    save_transcripts(
        ORG_ID,
        SESSION_ID,
        [
            {
                "sentence_no": 4,
                "content": "错误时间测试",
                "start_ms": 3000,
                "end_ms": 2000
            }
        ]
    )

except ValueError as e:
    print("错误时间检测正常：", e)

else:
    raise AssertionError("错误时间范围没有被阻止")


print("\n========== 7. 测试跨机构查询 ==========")

try:
    get_transcripts(
        "ORG_DEMO",
        SESSION_ID
    )

except ValueError as e:
    print("跨机构查询保护正常：", e)

else:
    raise AssertionError("跨机构查询保护失败")


print("\n========== 8. 完成问诊 ==========")

session = update_session_status(
    ORG_ID,
    SESSION_ID,
    "completed"
)

print(session)

assert session["status"] == "completed"


print("\n所有语音转写测试通过！")

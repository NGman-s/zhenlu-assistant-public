
from db import DB_PATH

from session import create_session, get_session
from audio_chunk import (
    save_audio_chunk,
    get_audio_chunks,
    find_audio_chunk_at_time,
    update_audio_chunk_status
)


if DB_PATH.name != "diagnosis_final_test.db":
    raise RuntimeError("请先切换到测试数据库")


ORG_ID = "ORG_TEST"
SESSION_ID = "S007"
DOCTOR_ID = "U_TEST_DOCTOR"


print("当前测试数据库：", DB_PATH)


print("\n========== 1. 准备问诊会话 ==========")

session = get_session(ORG_ID, SESSION_ID)

if session is None:
    session = create_session(
        SESSION_ID,
        ORG_ID,
        DOCTOR_ID,
        "recording"
    )

print(session)


print("\n========== 2. 保存音频分片 ==========")

existing = get_audio_chunks(ORG_ID, SESSION_ID)

if not existing:

    for seq in range(1, 4):

        sample_start = (seq - 1) * 3200

        result = save_audio_chunk(
            org_id=ORG_ID,
            session_id=SESSION_ID,
            seq=seq,
            sample_start=sample_start,
            sample_count=3200,
            sample_rate=16000,
            codec="PCM16LE",
            storage_path=(
                f"audio/S007/chunk_{seq:04d}.pcm"
            ),
            payload_len=6400,
            checksum=f"demo-checksum-{seq:03d}"
        )

        print("保存成功：", result)

else:
    print("测试分片已经存在，跳过重复保存")


print("\n========== 3. 查询全部音频分片 ==========")

chunks = get_audio_chunks(
    ORG_ID,
    SESSION_ID
)

for chunk in chunks:
    print(
        f"分片 {chunk['seq']}，"
        f"采样位置 {chunk['sample_start']}，"
        f"上传状态 {chunk['upload_status']}"
    )

assert len(chunks) == 3


print("\n========== 4. 根据时间定位音频分片 ==========")

result = find_audio_chunk_at_time(
    ORG_ID,
    SESSION_ID,
    250
)

print("250ms 对应分片：", result)

assert result is not None
assert result["seq"] == 2


print("\n========== 5. 测试分片边界 ==========")

# 200ms 正好是第二个分片的开始位置
result = find_audio_chunk_at_time(
    ORG_ID,
    SESSION_ID,
    200
)

print("200ms 对应分片：", result["seq"])

assert result["seq"] == 2

# 600ms 已经超出了三个分片的范围
result = find_audio_chunk_at_time(
    ORG_ID,
    SESSION_ID,
    600
)

print("600ms 定位结果：", result)

assert result is None


print("\n========== 6. 测试重复分片保护 ==========")

try:
    save_audio_chunk(
        ORG_ID,
        SESSION_ID,
        1,
        0,
        3200,
        16000,
        "PCM16LE",
        "audio/duplicate.pcm",
        6400,
        "duplicate-checksum"
    )

except ValueError as e:
    print("重复分片保护正常：", e)

else:
    raise AssertionError("重复分片没有被阻止")


print("\n========== 7. 测试机构隔离 ==========")

try:
    get_audio_chunks(
        "ORG_DEMO",
        SESSION_ID
    )

except ValueError as e:
    print("跨机构查询保护正常：", e)

else:
    raise AssertionError("跨机构查询保护失败")


print("\n========== 8. 测试上传状态管理 ==========")

status = update_audio_chunk_status(
    ORG_ID,
    SESSION_ID,
    1,
    "uploaded"
)

print("第一次更新：", status)

status = update_audio_chunk_status(
    ORG_ID,
    SESSION_ID,
    1,
    "acknowledged"
)

print("第二次更新：", status)

# 重复提交相同状态，应当保持幂等
status = update_audio_chunk_status(
    ORG_ID,
    SESSION_ID,
    1,
    "acknowledged"
)

print("重复确认：", status)

assert status == "acknowledged"


print("\n========== 9. 测试非法状态转换 ==========")

try:
    update_audio_chunk_status(
        ORG_ID,
        SESSION_ID,
        1,
        "failed"
    )

except ValueError as e:
    print("非法状态转换保护正常：", e)

else:
    raise AssertionError("非法状态转换没有被阻止")


print("\n========== 10. 测试失败重传状态 ==========")

update_audio_chunk_status(
    ORG_ID,
    SESSION_ID,
    2,
    "failed"
)

status = update_audio_chunk_status(
    ORG_ID,
    SESSION_ID,
    2,
    "uploaded"
)

print("失败后重新上传：", status)

assert status == "uploaded"


print("\n所有音频分片测试通过！")

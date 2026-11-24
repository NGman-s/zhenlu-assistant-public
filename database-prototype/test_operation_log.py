
from db import DB_PATH

from operation_log import (
    create_operation_log,
    get_operation_log,
    list_operation_logs
)


if DB_PATH.name != "diagnosis_final_test.db":
    raise RuntimeError("请先切换到测试数据库")


ORG_ID = "ORG_TEST"
SESSION_ID = "S008"
USER_ID = "U_TEST_DOCTOR"


print("当前测试数据库：", DB_PATH)


print("\n========== 1. 查询已有病历操作日志 ==========")

existing_logs = list_operation_logs(
    ORG_ID,
    session_id=SESSION_ID
)

for log in existing_logs:
    print(log)

assert len(existing_logs) >= 3


print("\n========== 2. 查询医生确认操作 ==========")

confirmed_logs = list_operation_logs(
    ORG_ID,
    session_id=SESSION_ID,
    action="record_confirmed"
)

print(confirmed_logs)

assert len(confirmed_logs) == 1


print("\n========== 3. 创建新的测试操作日志 ==========")

new_log = create_operation_log(
    org_id=ORG_ID,
    session_id=SESSION_ID,
    user_id=USER_ID,
    action="test_log_created",
    target_type="test",
    target_id="LOG_TEST_001",
    details={
        "description": "测试操作日志模块",
        "result": "success"
    }
)

print(new_log)

assert new_log["action"] == "test_log_created"


print("\n========== 4. 根据日志编号查询 ==========")

log = get_operation_log(
    ORG_ID,
    new_log["log_id"]
)

print(log)

assert log is not None
assert log["target_id"] == "LOG_TEST_001"


print("\n========== 5. 按用户查询 ==========")

user_logs = list_operation_logs(
    ORG_ID,
    user_id=USER_ID
)

for item in user_logs:
    print(item)

assert len(user_logs) >= 3


print("\n========== 6. 测试机构隔离 ==========")

other_logs = list_operation_logs(
    "ORG_DEMO",
    session_id=SESSION_ID
)

print("跨机构查询结果：", other_logs)

assert other_logs == []

print("机构隔离正常！")


print("\n========== 7. 测试不存在的问诊 ==========")

try:
    create_operation_log(
        org_id=ORG_ID,
        session_id="S999",
        user_id=USER_ID,
        action="test",
        target_type="test"
    )

except ValueError as e:
    print("错误问诊保护正常：", e)

else:
    raise AssertionError("不存在的问诊没有被阻止")


print("\n========== 8. 测试不存在的用户 ==========")

try:
    create_operation_log(
        org_id=ORG_ID,
        session_id=SESSION_ID,
        user_id="U999",
        action="test",
        target_type="test"
    )

except ValueError as e:
    print("错误用户保护正常：", e)

else:
    raise AssertionError("不存在的用户没有被阻止")


print("\n========== 9. 测试JSON详情解析 ==========")

assert isinstance(new_log["details"], dict)

print("JSON详情解析正常：", new_log["details"])


print("\n所有操作日志测试通过！")

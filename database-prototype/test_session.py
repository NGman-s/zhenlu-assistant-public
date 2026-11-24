
from db import DB_PATH

from session import (
    create_session,
    get_session,
    update_session_status,
    list_sessions
)


# 防止测试误操作正式数据库
if DB_PATH.name != "diagnosis_final_test.db":
    raise RuntimeError(
        "当前不是测试数据库！"
        "请先设置 DIAGNOSIS_DB_PATH。"
    )


print("当前测试数据库：", DB_PATH)


print("\n========== 1. 创建问诊 ==========")

session_id = "S005"

# 测试机构 ORG_TEST
# 测试医生 U_TEST_DOCTOR
session = get_session("ORG_TEST", session_id)

if session is None:

    session = create_session(
        session_id="S005",
        org_id="ORG_TEST",
        doctor_id="U_TEST_DOCTOR",
        status="recording"
    )

    print("创建成功：", session)

else:
    print("测试问诊已存在：", session)


print("\n========== 2. 查询问诊 ==========")

session = get_session(
    "ORG_TEST",
    "S005"
)

print(session)

assert session["doctor_id"] == "U_TEST_DOCTOR"
assert session["org_id"] == "ORG_TEST"


print("\n========== 3. 修改问诊状态 ==========")

session = update_session_status(
    "ORG_TEST",
    "S005",
    "reviewing"
)

print("修改成功：", session)

assert session["status"] == "reviewing"


print("\n========== 4. 测试重复创建保护 ==========")

try:
    create_session(
        session_id="S005",
        org_id="ORG_TEST",
        doctor_id="U_TEST_DOCTOR"
    )

except ValueError as e:
    print("重复创建保护正常：", e)

else:
    raise AssertionError("重复问诊没有被阻止")


print("\n========== 5. 测试跨机构查询 ==========")

wrong_org = get_session(
    "ORG_DEMO",
    "S005"
)

print("跨机构查询结果：", wrong_org)

assert wrong_org is None

print("机构隔离正常！")


print("\n========== 6. 测试跨机构医生绑定 ==========")

try:
    create_session(
        session_id="S006",
        org_id="ORG_TEST",
        doctor_id="U001"
    )

except ValueError as e:
    print("跨机构医生绑定保护正常：", e)

else:
    raise AssertionError("跨机构医生绑定未被阻止")


print("\n========== 7. 查询机构问诊列表 ==========")

sessions = list_sessions(
    org_id="ORG_TEST"
)

for item in sessions:
    print(item)

assert len(sessions) == 1


print("\n========== 8. 按医生筛选 ==========")

doctor_sessions = list_sessions(
    org_id="ORG_TEST",
    doctor_id="U_TEST_DOCTOR"
)

print("该医生的问诊数量：", len(doctor_sessions))

assert len(doctor_sessions) == 1


print("\n========== 9. 完成问诊 ==========")

session = update_session_status(
    "ORG_TEST",
    "S005",
    "completed"
)

print(session)

assert session["ended_at"] is not None


print("\n========== 10. 验证原有数据 ==========")

original_sessions = list_sessions(
    org_id="ORG_DEMO"
)

print("原有机构问诊数量：", len(original_sessions))

assert len(original_sessions) == 4

print("\n所有问诊会话测试通过！")

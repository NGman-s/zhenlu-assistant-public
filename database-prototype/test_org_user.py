from db import DB_PATH

from organization import (
    create_organization,
    get_organization,
    list_organizations
)

from user import (
    create_user,
    get_user,
    list_users,
    set_user_status
)
# 防止测试误操作正式数据库
if DB_PATH.name != "diagnosis_final_test.db":
    raise RuntimeError(
        "当前不是测试数据库！"
        "请先设置 DIAGNOSIS_DB_PATH。"
    )

print("当前测试数据库：", DB_PATH)

print("========== 1. 创建测试机构 ==========")

org = create_organization(
    "ORG_TEST",
    "第二示例门诊"
)

print(org)


print("\n========== 2. 创建机构管理员 ==========")

admin = create_user(
    "U_TEST_ADMIN",
    "ORG_TEST",
    "test_admin",
    "测试管理员",
    "admin"
)

print(admin)


print("\n========== 3. 创建医生 ==========")

# 注意：这个 username 与 ORG_DEMO 中的 doctor_zhang 相同。
# 因为属于不同机构，所以允许存在。
doctor = create_user(
    "U_TEST_DOCTOR",
    "ORG_TEST",
    "doctor_zhang",
    "测试张医生",
    "doctor"
)

print(doctor)


print("\n========== 4. 查询机构 ==========")

print(get_organization("ORG_TEST"))

print("机构总数：", len(list_organizations()))


print("\n========== 5. 查询不同机构的用户 ==========")

demo_users = list_users("ORG_DEMO")
test_users = list_users("ORG_TEST")

print("ORG_DEMO 用户数量：", len(demo_users))
print("ORG_TEST 用户数量：", len(test_users))

for item in test_users:
    print(item)


print("\n========== 6. 测试机构隔离 ==========")

# U001 属于 ORG_DEMO
# 使用 ORG_TEST 查询时不能返回该用户
cross_user = get_user("U001", "ORG_TEST")

print("跨机构查询结果：", cross_user)

assert cross_user is None

print("机构隔离查询正常！")


print("\n========== 7. 测试重复用户名保护 ==========")

try:
    create_user(
        "U_TEST_DUP",
        "ORG_TEST",
        "doctor_zhang",
        "重复用户名测试",
        "doctor"
    )

except ValueError as e:
    assert "重复" in str(e), (
        f"发生了非预期的错误：{e}"
    )
    print("重复用户名保护正常：", e)

else:
    raise AssertionError(
        "重复用户名未被拒绝，测试失败！"
    )

print("\n========== 8. 测试用户停用与恢复 ==========")

inactive_user = set_user_status(
    "U_TEST_DOCTOR",
    "ORG_TEST",
    False
)

print("停用后状态：", inactive_user["is_active"])

active_user = set_user_status(
    "U_TEST_DOCTOR",
    "ORG_TEST",
    True
)

print("恢复后状态：", active_user["is_active"])


print("\n========== 9. 测试机构内角色查询 ==========")

admins = list_users("ORG_TEST", role="admin")
doctors = list_users("ORG_TEST", role="doctor")

print("管理员数量：", len(admins))
print("医生数量：", len(doctors))


print("\n========== 10. 最终检查 ==========")

assert len(demo_users) == 4
assert len(test_users) == 2
assert len(admins) == 1
assert len(doctors) == 1
assert inactive_user["is_active"] == 0
assert active_user["is_active"] == 1

print("所有机构与用户测试通过！")

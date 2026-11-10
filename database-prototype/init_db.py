
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

SCHEMA_PATH = BASE_DIR / "schema.sql"
DB_PATH = BASE_DIR / "diagnosis_final.db"

# 临时数据库：初始化成功后才正式命名
TEMP_DB_PATH = BASE_DIR / "diagnosis_final.initializing.db"

EXPECTED_TABLES = {
    "organizations",
    "users",
    "sessions",
    "audio_chunks",
    "transcript_sentences",
    "record_versions",
    "record_fields",
    "field_sources",
    "operation_logs"
}


def initialize_database():

    # 1. 检查 SQL 文件
    if not SCHEMA_PATH.is_file():
        raise FileNotFoundError("找不到 schema.sql")

    # 2. 防止覆盖已有正式数据库
    if DB_PATH.exists():
        raise FileExistsError(
            "正式数据库已经存在，为保护数据，拒绝覆盖。"
        )

    # 清理上次异常退出留下的临时文件
    if TEMP_DB_PATH.exists():
        TEMP_DB_PATH.unlink()

    conn = sqlite3.connect(str(TEMP_DB_PATH))

    try:
        # 3. 开启外键约束
        conn.execute("PRAGMA foreign_keys = ON")

        # 4. 读取并执行完整 SQL 文件
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        conn.executescript(schema)

        # 5. 查询实际创建的数据表
        rows = conn.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
        """).fetchall()

        actual_tables = {row[0] for row in rows}

        missing_tables = EXPECTED_TABLES - actual_tables

        if missing_tables:
            raise RuntimeError(
                f"缺少数据表：{missing_tables}"
            )

        # 6. 检查触发器
        triggers = conn.execute("""
            SELECT name
            FROM sqlite_master
            WHERE type = 'trigger'
        """).fetchall()

        # 7. 检查外键约束
        foreign_keys = conn.execute(
            "PRAGMA foreign_keys"
        ).fetchone()[0]

        if foreign_keys != 1:
            raise RuntimeError("外键约束未开启")

        foreign_errors = conn.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        if foreign_errors:
            raise RuntimeError(
                f"外键检查失败：{foreign_errors}"
            )

        # 8. 检查数据库完整性
        integrity = conn.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        if integrity != "ok":
            raise RuntimeError(
                f"数据库完整性检查失败：{integrity}"
            )

    except Exception:
        conn.close()

        if TEMP_DB_PATH.exists():
            TEMP_DB_PATH.unlink()

        raise

    else:
        conn.close()

        # 9. 全部验证通过后，生成正式数据库
        TEMP_DB_PATH.replace(DB_PATH)

    print("========== 数据库初始化成功 ==========")
    print("数据库位置：", DB_PATH)

    print("\n创建的数据表：")

    for name in sorted(actual_tables):
        print("-", name)

    print("\n触发器数量：", len(triggers))
    print("外键约束：已开启")
    print("外键完整性：正常")
    print("数据库完整性：正常")


if __name__ == "__main__":
    initialize_database()

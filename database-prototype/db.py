
import os
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# 默认使用正式数据库
DEFAULT_DB_PATH = BASE_DIR / "diagnosis_final.db"

# 测试时可以通过环境变量指定其他数据库
DB_PATH = Path(
    os.environ.get(
        "DIAGNOSIS_DB_PATH",
        str(DEFAULT_DB_PATH)
    )
).resolve()


def get_connection():
    """
    获取统一的 SQLite 数据库连接。
    """

    if not DB_PATH.is_file():
        raise FileNotFoundError(
            f"找不到数据库：{DB_PATH}"
        )

    conn = sqlite3.connect(
        str(DB_PATH),
        timeout=10
    )

    conn.row_factory = sqlite3.Row

    # 每个连接都开启外键约束
    conn.execute("PRAGMA foreign_keys = ON")

    return conn


if __name__ == "__main__":
    conn = get_connection()

    print("数据库连接成功！")
    print("数据库位置：", DB_PATH)

    conn.close()

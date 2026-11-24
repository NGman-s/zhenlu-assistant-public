import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schema.sql"

DATABASES = [
    "diagnosis_final_test.db",
    "diagnosis_integration_test.db",
]

EXPECTED_TABLES = {
    "organizations",
    "users",
    "sessions",
    "audio_chunks",
    "transcript_sentences",
    "record_versions",
    "record_fields",
    "field_sources",
    "operation_logs",
}

def initialize_database(path: Path) -> None:
    conn = None
    try:
        conn = sqlite3.connect(str(path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))

        tables = {
            row[0]
            for row in conn.execute("""
                SELECT name FROM sqlite_master
                WHERE type = 'table'
                  AND name NOT LIKE 'sqlite_%'
            """)
        }
        assert tables == EXPECTED_TABLES, "数据表结构不匹配"

        for table, column in [
            ("organizations", "org_id"),
            ("users", "user_id"),
            ("sessions", "session_id"),
        ]:
            info = conn.execute(
                f"PRAGMA table_info({table})"
            ).fetchall()
            field = next(row for row in info if row[1] == column)
            assert field[3] == 1, f"{table}.{column} 缺少 NOT NULL"

        assert not conn.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        assert conn.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0] == "ok"

    finally:
        if conn is not None:
            conn.close()


def main() -> None:
    if not SCHEMA.is_file():
        raise FileNotFoundError(f"找不到 schema.sql：{SCHEMA}")

    paths = [ROOT / name for name in DATABASES]
    existing = [str(path.name) for path in paths if path.exists()]

    if existing:
        raise FileExistsError(
            "以下数据库已经存在，为避免覆盖已停止："
            + ", ".join(existing)
        )

    created = []

    try:
        for path in paths:
            initialize_database(path)
            created.append(path)
            print(f"创建成功：{path.name}")

    except Exception:
        for path in created:
            if path.exists():
                path.unlink()
        raise

    print("两个测试数据库均已通过结构和完整性检查。")


if __name__ == "__main__":
    main()

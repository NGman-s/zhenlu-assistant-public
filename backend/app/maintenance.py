"""Run from backend: python -m app.maintenance backup --output <new-file>"""
from __future__ import annotations

import argparse
from pathlib import Path

from app.config import Settings
from app.database import Database


def main() -> None:
    parser = argparse.ArgumentParser(description="诊录助手 SQLite 维护")
    parser.add_argument("action", choices=["backup", "check", "migrate"])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    database = Database(Settings().database_url)
    try:
        if args.action == "backup":
            if args.output is None:
                parser.error("backup 需要 --output 指定一个尚不存在的文件")
            print(database.backup(args.output))
        elif args.action == "migrate":
            database.create_all()
            print("数据库结构已更新；已有 SQLite 数据库升级前会自动备份。")
        else:
            if database.engine.dialect.name != "sqlite":
                parser.error("check 仅支持 SQLite")
            raw = database.engine.raw_connection()
            try:
                connection = raw.driver_connection
                integrity = connection.execute("PRAGMA integrity_check").fetchall()
                foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
                if integrity != [("ok",)] or foreign_keys:
                    raise SystemExit("数据库完整性或外键检查失败，请使用备份检查恢复。")
                print("数据库完整性与外键检查通过。")
            finally:
                raw.close()
    finally:
        database.dispose()


if __name__ == "__main__":
    main()

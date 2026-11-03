from __future__ import annotations

from collections.abc import Iterator
import re
from typing import Any

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base


class Database:
    def __init__(self, url: str) -> None:
        engine_kwargs: dict[str, Any] = {"future": True}
        if url.startswith("sqlite"):
            engine_kwargs["connect_args"] = {"check_same_thread": False}
            if url in {"sqlite://", "sqlite:///:memory:"}:
                engine_kwargs["poolclass"] = StaticPool
        self.engine = create_engine(url, **engine_kwargs)
        self.session_factory = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)
        self._allow_text_only_transcripts()

    def _allow_text_only_transcripts(self) -> None:
        """Upgrade the original SQLite schema atomically without losing records."""
        if self.engine.dialect.name != "sqlite":
            from sqlalchemy import inspect

            columns = inspect(self.engine).get_columns("transcripts")
            if any(c["name"] == "audio_file_id" and not c["nullable"] for c in columns):
                raise RuntimeError("请先将 transcripts.audio_file_id 迁移为可空，再启动服务。")
            return
        raw = self.engine.raw_connection()
        try:
            db = raw.driver_connection
            foreign_keys = db.execute("PRAGMA foreign_keys").fetchone()[0]
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("BEGIN IMMEDIATE")
            try:
                columns = db.execute("PRAGMA table_info(transcripts)").fetchall()
                column = next((item for item in columns if item[1] == "audio_file_id"), None)
                if column is None:
                    raise RuntimeError("转写数据表缺少 audio_file_id，无法迁移。")
                if column[3]:
                    ddl = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='transcripts'").fetchone()[0]
                    ddl, table_count = re.subn(r'(?i)^CREATE\s+TABLE\s+["`\[]?transcripts["`\]]?', 'CREATE TABLE transcripts_text_migration', ddl, count=1)
                    ddl, column_count = re.subn(r'(?i)(["`\[]?audio_file_id["`\]]?\s+VARCHAR\s*\(\s*32\s*\))\s+NOT\s+NULL\b', r'\1', ddl, count=1)
                    if table_count != 1 or column_count != 1:
                        raise RuntimeError("转写数据表结构与预期不符，未执行迁移。")
                    extra_sql = [r[0] for r in db.execute("SELECT sql FROM sqlite_master WHERE tbl_name='transcripts' AND type IN ('index', 'trigger') AND sql IS NOT NULL")]
                    db.execute(ddl)
                    db.execute("INSERT INTO transcripts_text_migration SELECT * FROM transcripts")
                    db.execute("DROP TABLE transcripts")
                    db.execute("ALTER TABLE transcripts_text_migration RENAME TO transcripts")
                    for statement in extra_sql:
                        db.execute(statement)
                    if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                        raise RuntimeError("数据库外键校验未通过，迁移已回滚。")
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.execute(f"PRAGMA foreign_keys={'ON' if foreign_keys else 'OFF'}")
        finally:
            raw.close()

    def dispose(self) -> None:
        self.engine.dispose()


def get_db(request: Request) -> Iterator[Session]:
    db: Session = request.app.state.db.session_factory()
    try:
        yield db
    finally:
        db.close()

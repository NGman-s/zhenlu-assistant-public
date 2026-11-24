
-- =====================================================
-- 诊录助手 SQLite 数据库
-- 正式版本 V1.0
-- 共九张核心业务表
-- =====================================================

PRAGMA foreign_keys = ON;


-- =====================================================
-- 1. 机构表
-- =====================================================

CREATE TABLE organizations (
    org_id TEXT NOT NULL PRIMARY KEY,
    org_name TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
        CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CHECK (length(trim(org_id)) > 0),
    CHECK (length(trim(org_name)) > 0)
);


-- =====================================================
-- 2. 用户表
-- =====================================================

CREATE TABLE users (
    user_id TEXT NOT NULL PRIMARY KEY,
    org_id TEXT NOT NULL,
    username TEXT NOT NULL,
    display_name TEXT NOT NULL,

    role TEXT NOT NULL
        CHECK (role IN ('admin', 'doctor')),

    is_active INTEGER NOT NULL DEFAULT 1
        CHECK (is_active IN (0, 1)),

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (org_id)
        REFERENCES organizations(org_id),

    UNIQUE (org_id, username),
    UNIQUE (org_id, user_id),

    CHECK (length(trim(username)) > 0),
    CHECK (length(trim(display_name)) > 0)
);


-- =====================================================
-- 3. 问诊会话表
-- =====================================================

CREATE TABLE sessions (
    session_id TEXT NOT NULL PRIMARY KEY,
    org_id TEXT NOT NULL,
    doctor_id TEXT NOT NULL,

    status TEXT NOT NULL
        CHECK (
            status IN (
                'recording',
                'processing',
                'reviewing',
                'completed',
                'cancelled'
            )
        ),

    started_at TEXT,
    ended_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (org_id)
        REFERENCES organizations(org_id),

    FOREIGN KEY (org_id, doctor_id)
        REFERENCES users(org_id, user_id),

    UNIQUE (org_id, session_id),

    CHECK (length(trim(session_id)) > 0)
);


-- 确保问诊只能分配给所属机构内有效的医生
CREATE TRIGGER validate_session_doctor_insert
BEFORE INSERT ON sessions
BEGIN
    SELECT CASE
        WHEN NOT EXISTS (
            SELECT 1
            FROM users u
            JOIN organizations o
                ON o.org_id = u.org_id
            WHERE u.user_id = NEW.doctor_id
              AND u.org_id = NEW.org_id
              AND u.role = 'doctor'
              AND u.is_active = 1
              AND o.is_active = 1
        )
        THEN RAISE(
            ABORT,
            '问诊必须关联同一机构内的有效医生'
        )
    END;
END;


CREATE TRIGGER validate_session_doctor_update
BEFORE UPDATE OF org_id, doctor_id ON sessions
BEGIN
    SELECT CASE
        WHEN NOT EXISTS (
            SELECT 1
            FROM users u
            JOIN organizations o
                ON o.org_id = u.org_id
            WHERE u.user_id = NEW.doctor_id
              AND u.org_id = NEW.org_id
              AND u.role = 'doctor'
              AND u.is_active = 1
              AND o.is_active = 1
        )
        THEN RAISE(
            ABORT,
            '问诊必须关联同一机构内的有效医生'
        )
    END;
END;


-- =====================================================
-- 4. 音频分片索引表
-- =====================================================

CREATE TABLE audio_chunks (
    chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,

    org_id TEXT NOT NULL,
    session_id TEXT NOT NULL,

    seq INTEGER NOT NULL CHECK (seq >= 1),

    sample_start INTEGER NOT NULL
        CHECK (sample_start >= 0),

    sample_count INTEGER NOT NULL
        CHECK (sample_count > 0),

    sample_rate INTEGER NOT NULL
        CHECK (sample_rate > 0),

    codec TEXT NOT NULL,
    storage_path TEXT NOT NULL,

    payload_len INTEGER NOT NULL
        CHECK (payload_len > 0),

    checksum TEXT NOT NULL,

    upload_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (
            upload_status IN (
                'pending',
                'uploaded',
                'acknowledged',
                'failed'
            )
        ),

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (org_id, session_id)
        REFERENCES sessions(org_id, session_id),

    UNIQUE (org_id, session_id, seq),

    CHECK (length(trim(codec)) > 0),
    CHECK (length(trim(storage_path)) > 0),
    CHECK (length(trim(checksum)) > 0)
);


-- =====================================================
-- 5. 语音转写句子表
-- =====================================================

CREATE TABLE transcript_sentences (
    sentence_id INTEGER PRIMARY KEY AUTOINCREMENT,

    org_id TEXT NOT NULL,
    session_id TEXT NOT NULL,

    sentence_no INTEGER NOT NULL
        CHECK (sentence_no >= 1),

    content TEXT NOT NULL,

    start_ms INTEGER,
    end_ms INTEGER,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (org_id, session_id)
        REFERENCES sessions(org_id, session_id),

    UNIQUE (org_id, session_id, sentence_no),
    UNIQUE (org_id, session_id, sentence_id),

    CHECK (length(trim(content)) > 0),

    CHECK (
        (start_ms IS NULL AND end_ms IS NULL)
        OR
        (
            start_ms IS NOT NULL
            AND end_ms IS NOT NULL
            AND start_ms >= 0
            AND end_ms > start_ms
        )
    )
);


-- =====================================================
-- 6. 病历版本表
-- =====================================================

CREATE TABLE record_versions (
    version_id INTEGER PRIMARY KEY AUTOINCREMENT,

    org_id TEXT NOT NULL,
    session_id TEXT NOT NULL,

    version_no INTEGER NOT NULL
        CHECK (version_no >= 1),

    version_type TEXT NOT NULL
        CHECK (
            version_type IN (
                'AI草稿',
                '医生修改版',
                '医生确认版'
            )
        ),

    created_by TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (org_id, session_id)
        REFERENCES sessions(org_id, session_id),

    FOREIGN KEY (org_id, created_by)
        REFERENCES users(org_id, user_id),

    UNIQUE (org_id, session_id, version_no),
    UNIQUE (org_id, session_id, version_id)
);


-- =====================================================
-- 7. 病历字段表
-- =====================================================

CREATE TABLE record_fields (
    field_id INTEGER PRIMARY KEY AUTOINCREMENT,

    org_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    version_id INTEGER NOT NULL,

    field_name TEXT NOT NULL,
    field_value TEXT,

    information_status TEXT NOT NULL DEFAULT 'recorded'
        CHECK (
            information_status IN (
                'recorded',
                'not_mentioned',
                'explicitly_denied'
            )
        ),

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (org_id, session_id, version_id)
        REFERENCES record_versions(
            org_id,
            session_id,
            version_id
        ),

    UNIQUE (org_id, session_id, field_id),

    UNIQUE (version_id, field_name),

    CHECK (length(trim(field_name)) > 0),

    CHECK (
        (
            information_status = 'not_mentioned'
            AND field_value IS NULL
        )
        OR
        (
            information_status IN (
                'recorded',
                'explicitly_denied'
            )
            AND field_value IS NOT NULL
            AND length(trim(field_value)) > 0
        )
    )
);


-- =====================================================
-- 8. 病历字段来源关联表
-- =====================================================

CREATE TABLE field_sources (
    org_id TEXT NOT NULL,
    session_id TEXT NOT NULL,

    field_id INTEGER NOT NULL,
    sentence_id INTEGER NOT NULL,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (
        org_id,
        session_id,
        field_id,
        sentence_id
    ),

    FOREIGN KEY (org_id, session_id, field_id)
        REFERENCES record_fields(
            org_id,
            session_id,
            field_id
        ),

    FOREIGN KEY (org_id, session_id, sentence_id)
        REFERENCES transcript_sentences(
            org_id,
            session_id,
            sentence_id
        )
);


-- =====================================================
-- 9. 操作日志表
-- =====================================================

CREATE TABLE operation_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,

    org_id TEXT NOT NULL,
    session_id TEXT,
    user_id TEXT,

    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT,

    details TEXT,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (org_id)
        REFERENCES organizations(org_id),

    FOREIGN KEY (org_id, session_id)
        REFERENCES sessions(org_id, session_id),

    FOREIGN KEY (org_id, user_id)
        REFERENCES users(org_id, user_id),

    CHECK (length(trim(action)) > 0),
    CHECK (length(trim(target_type)) > 0)
);


-- =====================================================
-- 10. 查询索引
-- =====================================================

CREATE INDEX idx_users_org
ON users(org_id);

CREATE INDEX idx_sessions_org
ON sessions(org_id);

CREATE INDEX idx_sessions_doctor
ON sessions(org_id, doctor_id);

CREATE INDEX idx_audio_chunks_session
ON audio_chunks(org_id, session_id, seq);

CREATE INDEX idx_audio_chunks_sample
ON audio_chunks(org_id, session_id, sample_start);

CREATE INDEX idx_transcript_session
ON transcript_sentences(
    org_id,
    session_id,
    sentence_no
);

CREATE INDEX idx_versions_session
ON record_versions(
    org_id,
    session_id,
    version_no
);

CREATE INDEX idx_fields_version
ON record_fields(
    org_id,
    session_id,
    version_id
);

CREATE INDEX idx_sources_sentence
ON field_sources(
    org_id,
    session_id,
    sentence_id
);

CREATE INDEX idx_logs_org_time
ON operation_logs(org_id, created_at);

CREATE INDEX idx_logs_session
ON operation_logs(org_id, session_id);

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app


def test_existing_sqlite_records_survive_text_input_migration(settings: Settings) -> None:
    app = create_app(settings)
    with TestClient(app) as client:
        sid = client.post('/api/sessions', json={'patient_name': '虚构病例'}).json()['id']
        audio = Path(__file__).resolve().parents[2] / 'sample-data' / 'mock-consultation-case-01.wav'
        with audio.open('rb') as f:
            assert client.post(f'/api/sessions/{sid}/audio', files={'file': (audio.name, f, 'audio/wav')}).status_code == 201
        assert client.post(f'/api/sessions/{sid}/transcript').status_code == 200
        draft = client.post(f'/api/sessions/{sid}/draft').json()['draft']
        assert client.post(f'/api/sessions/{sid}/confirm', json={'expected_revision': draft['revision']}).status_code == 200
        before = client.get(f'/api/sessions/{sid}').json()
    dbpath = settings.database_url.removeprefix('sqlite:///')
    with sqlite3.connect(dbpath) as db:
        db.execute('PRAGMA foreign_keys=OFF')
        ddl = db.execute("SELECT sql FROM sqlite_master WHERE name='transcripts' AND type='table'").fetchone()[0]
        ddl = ddl.replace('CREATE TABLE transcripts', 'CREATE TABLE transcripts_old').replace('audio_file_id VARCHAR(32)', 'audio_file_id VARCHAR(32) NOT NULL')
        db.execute(ddl)
        db.execute('INSERT INTO transcripts_old SELECT * FROM transcripts')
        db.execute('DROP TABLE transcripts')
        db.execute('ALTER TABLE transcripts_old RENAME TO transcripts')
        db.commit()
    with TestClient(create_app(settings)) as client:
        after = client.get(f'/api/sessions/{sid}').json()
        assert after['transcript'] == before['transcript']
        assert after['latest_record'] == before['latest_record']
        text_sid = client.post('/api/sessions', json={'patient_name': '文字虚构病例'}).json()['id']
        response = client.post(f'/api/sessions/{text_sid}/transcript/manual', json={'text': '患者：咳嗽三天。'})
        assert response.status_code == 200 and response.json()['audio'] is None
    with sqlite3.connect(dbpath) as db:
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert next(x for x in db.execute('PRAGMA table_info(transcripts)') if x[1] == 'audio_file_id')[3] == 0
    with TestClient(create_app(settings)) as client:
        assert client.get(f'/api/sessions/{sid}').json()['latest_record'] == before['latest_record']

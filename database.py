import sqlite3
from config import DB_PATH


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS risks (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            risk_id          TEXT,
            level            TEXT,          -- enterprise | affiliate | department | event
            entity_name      TEXT,
            category         TEXT,
            title            TEXT,
            description      TEXT,
            ai_correlation   TEXT,
            likelihood       INTEGER,
            impact           INTEGER,
            risk_score       INTEGER,
            velocity         TEXT,          -- Immediate | Short-term | Long-term
            mitigation       TEXT,
            contingency      TEXT,
            owner            TEXT,
            reviewer         TEXT,
            kri              TEXT,
            kri_threshold    TEXT,
            status           TEXT DEFAULT 'Open',
            source           TEXT DEFAULT 'Manual',
            parent_risk_id   TEXT,
            created_date     TEXT,
            updated_date     TEXT,
            event_context    TEXT           -- JSON blob
        );

        CREATE TABLE IF NOT EXISTS ingested_documents (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            filename               TEXT,
            doc_type               TEXT,
            upload_date            TEXT,
            processed              INTEGER DEFAULT 0,
            extracted_risks_count  INTEGER DEFAULT 0,
            extracted_text         TEXT,
            summary                TEXT
        );

        CREATE TABLE IF NOT EXISTS news_items (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            headline               TEXT,
            source                 TEXT,
            url                    TEXT,
            published_date         TEXT,
            fetched_date           TEXT,
            relevance_score        INTEGER,
            mapped_risk_categories TEXT,   -- JSON array
            ai_analysis            TEXT,
            triggered_risk_id      TEXT
        );

        CREATE TABLE IF NOT EXISTS arc_packs (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            title          TEXT,
            period         TEXT,
            generated_date TEXT,
            generated_by   TEXT,
            status         TEXT DEFAULT 'Draft',
            content_json   TEXT,
            html_output    TEXT
        );

        CREATE TABLE IF NOT EXISTS agencies (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            name               TEXT,
            type               TEXT,
            contact_name       TEXT,
            contact_email      TEXT,
            risk_sharing_level TEXT DEFAULT 'Summary'
        );

        CREATE TABLE IF NOT EXISTS lessons_learned (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            event_name         TEXT,
            event_date         TEXT,
            category           TEXT,
            lesson_title       TEXT,
            what_happened      TEXT,
            root_cause         TEXT,
            corrective_action  TEXT,
            preventive_action  TEXT,
            linked_risk_id     TEXT,
            source_doc_id      INTEGER
        );
    """)
    conn.commit()
    conn.close()

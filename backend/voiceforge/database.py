import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "backend" / "config" / "voiceforge.yaml"
_lock = threading.Lock()


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def storage_root():
    return ROOT / load_config().get("storage_root", "voiceforge_data")


def database_path():
    return storage_root() / load_config().get("database_name", "voiceforge.db")


def connect():
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def session():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS vf_projects (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
    source_language TEXT NOT NULL DEFAULT 'zh-CN', target_language TEXT NOT NULL DEFAULT 'zh-CN',
    status TEXT NOT NULL DEFAULT 'draft', default_interface_id TEXT, default_voice_id TEXT,
    default_speed REAL NOT NULL DEFAULT 1.0, version INTEGER NOT NULL DEFAULT 1,
    legacy_source_id TEXT, legacy_import_batch_id TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS vf_chapters (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES vf_projects(id) ON DELETE CASCADE,
    order_index INTEGER NOT NULL, title TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
    legacy_source_id TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(project_id, order_index)
);
CREATE TABLE IF NOT EXISTS vf_voices (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, display_name TEXT NOT NULL, interface_id TEXT,
    voice_id TEXT, mode TEXT NOT NULL DEFAULT 'preset_voice', language TEXT NOT NULL DEFAULT 'zh-CN',
    tags_json TEXT NOT NULL DEFAULT '[]', description TEXT NOT NULL DEFAULT '', reference_storage_key TEXT,
    preview_storage_key TEXT, preview_text TEXT NOT NULL DEFAULT '', params_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'ready',
    legacy_engine TEXT, legacy_voice_key TEXT, gender TEXT, voice_age TEXT, voice_pitch TEXT, dialect TEXT,
    is_cloned INTEGER NOT NULL DEFAULT 0, is_builtin INTEGER NOT NULL DEFAULT 0, design_text TEXT,
    emotions_json TEXT NOT NULL DEFAULT '[]', voice_group TEXT, sample_storage_key TEXT,
    embedding_storage_key TEXT, legacy_params_json TEXT NOT NULL DEFAULT '{}',
    legacy_source_id TEXT, legacy_import_batch_id TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS vf_characters (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES vf_projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL, character_type TEXT NOT NULL DEFAULT 'narrator',
    sort_order INTEGER NOT NULL DEFAULT 0,
    voice_profile_id TEXT REFERENCES vf_voices(id) ON DELETE SET NULL,
    gender TEXT, age_range TEXT, personality TEXT, voice_design_desc TEXT,
    language TEXT NOT NULL DEFAULT 'zh-CN', note TEXT NOT NULL DEFAULT '', legacy_source_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS vf_sentences (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES vf_projects(id) ON DELETE CASCADE,
    chapter_id TEXT REFERENCES vf_chapters(id) ON DELETE SET NULL, character_id TEXT REFERENCES vf_characters(id) ON DELETE SET NULL,
    order_index INTEGER NOT NULL, text TEXT NOT NULL, edited_text TEXT, voice_profile_id TEXT REFERENCES vf_voices(id) ON DELETE SET NULL,
    interface_id TEXT, voice_id TEXT, speed REAL NOT NULL DEFAULT 1.0, pitch REAL NOT NULL DEFAULT 0.0,
    volume REAL NOT NULL DEFAULT 1.0, emotion TEXT NOT NULL DEFAULT 'neutral', tone_description TEXT NOT NULL DEFAULT '', pause_after REAL NOT NULL DEFAULT 0,
    source_start REAL, source_end REAL, status TEXT NOT NULL DEFAULT 'pending',
    audio_storage_key TEXT, audio_duration REAL, error_message TEXT, task_id TEXT, version INTEGER NOT NULL DEFAULT 1,
    legacy_source_id TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(project_id, order_index)
);
CREATE TABLE IF NOT EXISTS vf_assets (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, asset_type TEXT NOT NULL, category TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]', storage_key TEXT NOT NULL UNIQUE, file_name TEXT NOT NULL,
    file_size INTEGER NOT NULL DEFAULT 0, mime_type TEXT, duration REAL, description TEXT NOT NULL DEFAULT '',
    external_path TEXT NOT NULL DEFAULT '', path_key TEXT NOT NULL DEFAULT '', sample_rate INTEGER,
    channels INTEGER, format TEXT, is_favorite INTEGER NOT NULL DEFAULT 0, legacy_source_id TEXT,
    legacy_import_batch_id TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS vf_asset_categories (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, label TEXT NOT NULL, asset_type TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(name, asset_type)
);
CREATE TABLE IF NOT EXISTS vf_asset_tags (
    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, usage_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS vf_emotion_tags (
    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT NOT NULL DEFAULT '', color TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0, legacy_source_id TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS vf_tasks (
    id TEXT PRIMARY KEY, project_id TEXT REFERENCES vf_projects(id) ON DELETE CASCADE,
    voice_id TEXT REFERENCES vf_voices(id) ON DELETE SET NULL, task_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
    progress REAL NOT NULL DEFAULT 0, celery_task_id TEXT, idempotency_key TEXT UNIQUE, input_json TEXT NOT NULL DEFAULT '{}',
    output_json TEXT NOT NULL DEFAULT '{}', error_message TEXT, retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, started_at TEXT, finished_at TEXT,
    cancel_reason TEXT, error_class TEXT, resource_class TEXT NOT NULL DEFAULT 'io', queue TEXT NOT NULL DEFAULT 'voiceforge_export',
    timeout_seconds INTEGER, max_retries INTEGER NOT NULL DEFAULT 3, checkpoint_json TEXT NOT NULL DEFAULT '{}', deletion_requested INTEGER NOT NULL DEFAULT 0,
    UNIQUE(idempotency_key)
);
CREATE TABLE IF NOT EXISTS vf_exports (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES vf_projects(id) ON DELETE CASCADE,
    export_type TEXT NOT NULL, storage_key TEXT NOT NULL, file_name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'succeeded',
    task_id TEXT, error_message TEXT, format TEXT, metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_vf_sentences_project_order ON vf_sentences(project_id, order_index);
CREATE INDEX IF NOT EXISTS idx_vf_sentences_status ON vf_sentences(status);
CREATE INDEX IF NOT EXISTS idx_vf_tasks_project_status ON vf_tasks(project_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS uq_vf_projects_legacy_source ON vf_projects(legacy_source_id) WHERE legacy_source_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_vf_chapters_legacy_source ON vf_chapters(legacy_source_id) WHERE legacy_source_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_vf_voices_legacy_source ON vf_voices(legacy_source_id) WHERE legacy_source_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_vf_characters_legacy_source ON vf_characters(legacy_source_id) WHERE legacy_source_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_vf_sentences_legacy_source ON vf_sentences(legacy_source_id) WHERE legacy_source_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_vf_assets_legacy_source ON vf_assets(legacy_source_id) WHERE legacy_source_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_vf_emotions_legacy_source ON vf_emotion_tags(legacy_source_id) WHERE legacy_source_id IS NOT NULL;
"""


def initialize_database():
    with _lock:
        root = storage_root()
        for path in (root / "projects", root / "voices", root / "assets", root / "temp"):
            path.mkdir(parents=True, exist_ok=True)
        with session() as conn:
            conn.executescript(SCHEMA)
            existing = {row["name"] for row in conn.execute("PRAGMA table_info(vf_voices)").fetchall()}
            additions = {
                "legacy_engine": "TEXT", "legacy_voice_key": "TEXT", "gender": "TEXT", "voice_age": "TEXT",
                "voice_pitch": "TEXT", "dialect": "TEXT", "is_cloned": "INTEGER NOT NULL DEFAULT 0",
                "is_builtin": "INTEGER NOT NULL DEFAULT 0", "design_text": "TEXT", "emotions_json": "TEXT NOT NULL DEFAULT '[]'",
                "voice_group": "TEXT", "sample_storage_key": "TEXT", "embedding_storage_key": "TEXT",
                "legacy_params_json": "TEXT NOT NULL DEFAULT '{}'", "preview_text": "TEXT NOT NULL DEFAULT ''",
            }
            for name, definition in additions.items():
                if name not in existing:
                    conn.execute(f"ALTER TABLE vf_voices ADD COLUMN {name} {definition}")
            sentence_columns = {row["name"] for row in conn.execute("PRAGMA table_info(vf_sentences)").fetchall()}
            for name, definition in {
                "tone_description": "TEXT NOT NULL DEFAULT ''", "pause_after": "REAL NOT NULL DEFAULT 0",
                "source_start": "REAL", "source_end": "REAL",
            }.items():
                if name not in sentence_columns:
                    conn.execute(f"ALTER TABLE vf_sentences ADD COLUMN {name} {definition}")
            export_columns = {row["name"] for row in conn.execute("PRAGMA table_info(vf_exports)").fetchall()}
            for name, definition in {
                "status": "TEXT NOT NULL DEFAULT 'succeeded'", "task_id": "TEXT", "error_message": "TEXT",
                "format": "TEXT", "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
            }.items():
                if name not in export_columns:
                    conn.execute(f"ALTER TABLE vf_exports ADD COLUMN {name} {definition}")
            task_columns = {row["name"] for row in conn.execute("PRAGMA table_info(vf_tasks)").fetchall()}
            for name, definition in {
                "cancel_reason": "TEXT", "error_class": "TEXT", "resource_class": "TEXT NOT NULL DEFAULT 'io'",
                "queue": "TEXT NOT NULL DEFAULT 'voiceforge_export'", "timeout_seconds": "INTEGER",
                "max_retries": "INTEGER NOT NULL DEFAULT 3", "checkpoint_json": "TEXT NOT NULL DEFAULT '{}'",
                "deletion_requested": "INTEGER NOT NULL DEFAULT 0",
                # 是否已被任务泵投递（Celery 或本地线程池），用于并发占位统计
                "dispatched": "INTEGER NOT NULL DEFAULT 0",
            }.items():
                if name not in task_columns:
                    conn.execute(f"ALTER TABLE vf_tasks ADD COLUMN {name} {definition}")
            asset_columns = {row["name"] for row in conn.execute("PRAGMA table_info(vf_assets)").fetchall()}
            for name, definition in {
                "external_path": "TEXT NOT NULL DEFAULT ''", "sample_rate": "INTEGER", "channels": "INTEGER",
                "format": "TEXT", "is_favorite": "INTEGER NOT NULL DEFAULT 0", "path_key": "TEXT NOT NULL DEFAULT ''",
            }.items():
                if name not in asset_columns:
                    conn.execute(f"ALTER TABLE vf_assets ADD COLUMN {name} {definition}")
            for row in conn.execute("SELECT id, external_path FROM vf_assets WHERE external_path != '' AND path_key = ''").fetchall():
                path_key = os.path.normcase(os.path.normpath(row["external_path"])).replace("\\", "/")
                conn.execute("UPDATE vf_assets SET path_key = ? WHERE id = ?", (path_key, row["id"]))
            _seed_builtin_categories(conn)
            # Chapters: add parent_id, level, char_count for tree nesting
            chapter_columns = {row["name"] for row in conn.execute("PRAGMA table_info(vf_chapters)").fetchall()}
            if "parent_id" not in chapter_columns:
                conn.execute("ALTER TABLE vf_chapters ADD COLUMN parent_id TEXT")
            if "level" not in chapter_columns:
                conn.execute("ALTER TABLE vf_chapters ADD COLUMN level INTEGER NOT NULL DEFAULT 1")
            if "char_count" not in chapter_columns:
                conn.execute("ALTER TABLE vf_chapters ADD COLUMN char_count INTEGER NOT NULL DEFAULT 0")
            # Characters: align with LcVoiceForgeaApp project_characters (role def / binding / batch design)
            character_columns = {row["name"] for row in conn.execute("PRAGMA table_info(vf_characters)").fetchall()}
            for name, definition in {
                "sort_order": "INTEGER NOT NULL DEFAULT 0",
                "gender": "TEXT",
                "age_range": "TEXT",
                "personality": "TEXT",
                "voice_design_desc": "TEXT",
            }.items():
                if name not in character_columns:
                    conn.execute(f"ALTER TABLE vf_characters ADD COLUMN {name} {definition}")


BUILTIN_CATEGORIES = {
    "bgm": [
        ("epic", "史诗"), ("romantic", "浪漫"), ("suspense", "悬疑"), ("peaceful", "宁静"),
        ("battle", "战斗"), ("sad", "悲伤"), ("happy", "欢快"), ("mysterious", "神秘"), ("other", "其他"),
    ],
    "sfx": [
        ("nature", "自然"), ("weather", "天气"), ("city", "城市"), ("action", "动作"), ("emotion", "情感"),
        ("horror", "恐怖"), ("fantasy", "奇幻"), ("daily", "日常"), ("weapon", "武器"), ("vehicle", "载具"), ("other", "其他"),
    ],
    "ambience": [
        ("forest", "森林"), ("ocean", "海洋"), ("rain", "雨天"), ("city", "城市"), ("night", "夜晚"),
        ("cave", "洞穴"), ("market", "集市"), ("palace", "宫殿"), ("other", "其他"),
    ],
}


def _seed_builtin_categories(conn):
    import uuid
    for asset_type, items in BUILTIN_CATEGORIES.items():
        for sort_order, (name, label) in enumerate(items):
            exists = conn.execute(
                "SELECT id FROM vf_asset_categories WHERE name = ? AND asset_type = ?",
                (name, asset_type),
            ).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO vf_asset_categories (id, name, label, asset_type, sort_order) VALUES (?, ?, ?, ?, ?)",
                    (uuid.uuid4().hex, name, label, asset_type, sort_order),
                )


def row_to_dict(row):
    if row is None:
        return None
    data = dict(row)
    for key in ("tags_json", "params_json", "emotions_json", "legacy_params_json", "input_json", "output_json"):
        if key in data:
            target = key.removesuffix("_json")
            try:
                data[target] = json.loads(data.pop(key) or "{}")
            except json.JSONDecodeError:
                data[target] = [] if key == "tags_json" else {}
    return data

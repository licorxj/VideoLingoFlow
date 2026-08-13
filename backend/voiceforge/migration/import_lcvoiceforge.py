import argparse
import json
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend.voiceforge.database import initialize_database, session, storage_root
from backend.voiceforge.storage import copy_legacy_file, safe_file_name, sha256
from backend.voiceforge.voice_storage import write_voice_config


TABLES = ("projects", "chapters", "voice_profiles", "project_characters", "sentences", "emotion_tags", "assets", "operation_logs")


def source_connection(source_root: Path):
    database = source_root / "backend" / "data" / "voiceforge.db"
    if not database.exists():
        raise FileNotFoundError(f"未找到源数据库: {database}")
    snapshot_dir = storage_root() / "temp" / "legacy_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot = snapshot_dir / f"voiceforge-{uuid.uuid4().hex}.db"
    shutil.copy2(database, snapshot)
    return sqlite3.connect(snapshot), snapshot


def rows(conn, table):
    present = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
    if not present:
        return []
    columns = [item[1] for item in conn.execute(f"PRAGMA table_info({table})")]
    return [dict(zip(columns, item)) for item in conn.execute(f"SELECT * FROM {table} ORDER BY id")]


def copy_media(source_root: Path, source_path: str, key: str, report: dict, dry_run: bool):
    if not source_path:
        return None
    candidate = Path(source_path)
    if not candidate.is_absolute():
        candidates = [
            source_root / "backend" / source_path,
            source_root / "backend" / "data" / source_path,
        ]
        candidate = next((item for item in candidates if item.exists()), candidates[0])
    if not candidate.exists() or not candidate.is_file():
        report["missing_files"].append(str(candidate))
        return None
    if dry_run:
        report["files"].append({"source": str(candidate), "target": key, "size": candidate.stat().st_size})
        return key
    copied = copy_legacy_file(candidate, key)
    report["files"].append({"source": str(candidate), "target": key, "size": copied.stat().st_size, "sha256": sha256(copied)})
    return key


def json_value(value, fallback):
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def legacy_voice_emotions(source_root: Path, item: dict, voice_id: str, report: dict):
    emotions = []
    for emotion in json_value(item.get("emotions"), []):
        if not isinstance(emotion, dict) or not emotion.get("audio_path"):
            continue
        name = str(emotion.get("name") or "emotion").strip() or "emotion"
        suffix = Path(str(emotion["audio_path"])).suffix.lower() or ".wav"
        key = f"voices/{voice_id}/emotions/{safe_file_name(name, 'emotion')}{suffix}"
        copied = copy_media(source_root, emotion["audio_path"], key, report, False)
        if copied:
            emotions.append({"name": name, "audio_path": copied, "text": emotion.get("text") or "", "engine": emotion.get("engine") or item.get("engine") or "", "instruct": emotion.get("instruct") or ""})
    return emotions


def migrate_emotion_tags(source_root: Path):
    initialize_database()
    conn, snapshot = source_connection(source_root)
    try:
        source_tags = rows(conn, "emotion_tags")
    finally:
        conn.close()
        snapshot.unlink(missing_ok=True)
    report = {"source_count": len(source_tags), "inserted": 0, "reused": 0, "already_mapped": 0, "conflicts": [], "mappings": []}
    with session() as target_conn:
        for item in source_tags:
            source_id = str(item["id"])
            mapped = target_conn.execute("SELECT id FROM vf_emotion_tags WHERE legacy_source_id = ?", (source_id,)).fetchone()
            if mapped:
                report["already_mapped"] += 1
                report["mappings"].append({"source_id": source_id, "target_id": mapped["id"], "action": "already_mapped"})
                continue
            name = str(item.get("name") or "未命名标签").strip() or "未命名标签"
            existing = target_conn.execute("SELECT id, legacy_source_id FROM vf_emotion_tags WHERE name = ?", (name,)).fetchone()
            if existing:
                if existing["legacy_source_id"] and existing["legacy_source_id"] != source_id:
                    report["conflicts"].append({"source_id": source_id, "name": name, "target_id": existing["id"], "reason": "名称已绑定其他源标签"})
                    continue
                target_conn.execute("UPDATE vf_emotion_tags SET color = COALESCE(?, color), sort_order = ?, legacy_source_id = ? WHERE id = ?", (item.get("color"), item.get("sort_order") or 0, source_id, existing["id"]))
                report["reused"] += 1
                target_id = existing["id"]
                action = "reused"
            else:
                target_id = uuid.uuid4().hex
                target_conn.execute("INSERT INTO vf_emotion_tags (id, name, description, color, sort_order, legacy_source_id) VALUES (?, ?, '', ?, ?, ?)", (target_id, name, item.get("color"), item.get("sort_order") or 0, source_id))
                report["inserted"] += 1
                action = "inserted"
            report["mappings"].append({"source_id": source_id, "target_id": target_id, "name": name, "action": action})
    return report


def import_copy(source_root: Path, dry_run: bool = False):
    target = storage_root().resolve()
    if source_root.resolve() == target or source_root.resolve() in target.parents:
        raise ValueError("源目录不能是目标数据目录")
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "source_root": str(source_root), "dry_run": dry_run, "counts": {}, "files": [], "missing_files": [], "excluded": ["timeline", "scene_presets", "video", "exports"], "unmapped_voices": []}
    conn, snapshot = source_connection(source_root)
    try:
        source = {table: rows(conn, table) for table in TABLES}
    finally:
        conn.close()
        snapshot.unlink(missing_ok=True)
    report["counts"] = {table: len(items) for table, items in source.items()}
    media_refs = []
    for item in source["voice_profiles"]:
        if item.get("sample_path"):
            media_refs.append(("voice_reference", item.get("sample_path"), f"voices/{item['id']}/reference"))
    for item in source["sentences"]:
        if item.get("audio_path"):
            media_refs.append(("sentence_audio", item.get("audio_path"), f"projects/{item.get('project_id')}/audio/{item['id']}"))
    for item in source["assets"]:
        if item.get("file_path"):
            media_refs.append(("asset", item.get("file_path"), f"assets/{item['id']}"))
    for kind, source_path, target_key in media_refs:
        copy_media(source_root, source_path, target_key, report, True)
    report["media_references"] = len(media_refs)
    if dry_run:
        return report
    initialize_database()
    batch_id = uuid.uuid4().hex
    project_ids, chapter_ids, voice_ids, character_ids = {}, {}, {}, {}
    with session() as target_conn:
        pending_project_defaults = []
        for item in source["projects"]:
            existing = target_conn.execute("SELECT id FROM vf_projects WHERE legacy_source_id = ?", (str(item["id"]),)).fetchone()
            if existing:
                project_ids[str(item["id"])] = existing["id"]
                continue
            new_id = uuid.uuid4().hex
            project_ids[str(item["id"])] = new_id
            target_conn.execute("INSERT INTO vf_projects (id, name, description, source_language, target_language, status, default_interface_id, default_voice_id, default_speed, legacy_source_id, legacy_import_batch_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (new_id, item.get("name") or "未命名项目", item.get("description") or "", item.get("source_language") or item.get("language") or "zh-CN", item.get("target_language") or item.get("language") or "zh-CN", item.get("status") or "draft", None, None, item.get("default_speed") or 1.0, str(item["id"]), batch_id))
            pending_project_defaults.append((new_id, item.get("default_voice_id")))
        for item in source["chapters"]:
            project_id = project_ids.get(str(item.get("project_id")))
            if not project_id:
                continue
            existing = target_conn.execute("SELECT id FROM vf_chapters WHERE legacy_source_id = ?", (str(item["id"]),)).fetchone()
            if existing:
                chapter_ids[str(item["id"])] = existing["id"]
                continue
            new_id = uuid.uuid4().hex
            chapter_ids[str(item["id"])] = new_id
            target_conn.execute("INSERT INTO vf_chapters (id, project_id, order_index, title, legacy_source_id) VALUES (?, ?, ?, ?, ?)", (new_id, project_id, item.get("order_index") or 0, item.get("title") or "未命名章节", str(item["id"])))
        for item in source["voice_profiles"]:
            existing = target_conn.execute("SELECT id FROM vf_voices WHERE legacy_source_id = ?", (str(item["id"]),)).fetchone()
            if existing:
                voice_ids[str(item["id"])] = existing["id"]
                continue
            new_id = uuid.uuid4().hex
            voice_ids[str(item["id"])] = new_id
            sample = item.get("sample_path")
            sample_suffix = Path(sample or "sample.wav").suffix.lower() or ".wav"
            sample_key = copy_media(source_root, sample, f"voices/{new_id}/design{sample_suffix}", report, False)
            status = "needs_rebind"
            report["unmapped_voices"].append(item.get("display_name") or item.get("name"))
            tags = item.get("tags") or []
            if not isinstance(tags, str):
                tags = json.dumps(tags, ensure_ascii=False)
            params = json.dumps(json_value(item.get("engine_params"), {}), ensure_ascii=False)
            emotions = legacy_voice_emotions(source_root, item, new_id, report)
            target_conn.execute("INSERT INTO vf_voices (id, name, display_name, language, tags_json, description, reference_storage_key, params_json, status, legacy_engine, legacy_voice_key, gender, voice_age, voice_pitch, dialect, is_cloned, is_builtin, design_text, emotions_json, voice_group, sample_storage_key, legacy_params_json, legacy_source_id, legacy_import_batch_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (new_id, item.get("name") or "未命名音色", item.get("display_name") or item.get("name") or "未命名音色", item.get("language") or "zh-CN", tags, item.get("description") or "", sample_key, "{}", status, item.get("engine") or item.get("interface_id") or "", item.get("voice_key") or item.get("voice_id") or "", item.get("gender") or "", item.get("age") or "", item.get("pitch") or "", item.get("dialect") or "普通话", int(bool(item.get("is_cloned"))), int(bool(item.get("is_builtin"))), item.get("design_text") or "", json.dumps(emotions, ensure_ascii=False), item.get("voice_group") or "", sample_key, params, str(item["id"]), batch_id))
        for project_id, legacy_voice_id in pending_project_defaults:
            mapped_voice_id = voice_ids.get(str(legacy_voice_id))
            if mapped_voice_id:
                target_conn.execute("UPDATE vf_projects SET default_voice_id = ? WHERE id = ?", (mapped_voice_id, project_id))
        for item in source["project_characters"]:
            project_id = project_ids.get(str(item.get("project_id")))
            if not project_id:
                continue
            existing = target_conn.execute("SELECT id FROM vf_characters WHERE legacy_source_id = ?", (str(item["id"]),)).fetchone()
            if existing:
                character_ids[str(item["id"])] = existing["id"]
                continue
            new_id = uuid.uuid4().hex
            character_ids[str(item["id"])] = new_id
            target_conn.execute("INSERT INTO vf_characters (id, project_id, name, character_type, voice_profile_id, note, legacy_source_id) VALUES (?, ?, ?, ?, ?, ?, ?)", (new_id, project_id, item.get("name") or "角色", item.get("character_type") or "character", voice_ids.get(str(item.get("voice_profile_id") or item.get("voice_id"))), item.get("description") or "", str(item["id"])))
        for item in source["sentences"]:
            project_id = project_ids.get(str(item.get("project_id")))
            if not project_id:
                continue
            existing = target_conn.execute("SELECT id FROM vf_sentences WHERE legacy_source_id = ?", (str(item["id"]),)).fetchone()
            if existing:
                continue
            audio = item.get("audio_path")
            new_id = uuid.uuid4().hex
            key = copy_media(source_root, audio, f"projects/{project_id}/audio/{new_id}{Path(audio or 'audio.wav').suffix}", report, False)
            status = "done" if key and item.get("status") == "done" else "pending"
            target_conn.execute("INSERT INTO vf_sentences (id, project_id, chapter_id, character_id, order_index, text, edited_text, voice_profile_id, voice_id, speed, pitch, volume, emotion, status, audio_storage_key, audio_duration, legacy_source_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (new_id, project_id, chapter_ids.get(str(item.get("chapter_id"))), character_ids.get(str(item.get("character_id"))), item.get("order_index") or 0, item.get("text") or "", item.get("edited_text"), voice_ids.get(str(item.get("voice_id"))), item.get("voice_id"), item.get("speed") or 1.0, item.get("pitch") or 0.0, item.get("volume") or 1.0, item.get("emotion") or "neutral", status, key, item.get("audio_duration"), str(item["id"])))
        for item in source["emotion_tags"]:
            source_id = str(item["id"])
            if target_conn.execute("SELECT id FROM vf_emotion_tags WHERE legacy_source_id = ?", (source_id,)).fetchone():
                continue
            name = str(item.get("name") or "未命名标签").strip() or "未命名标签"
            existing_tag = target_conn.execute("SELECT id, legacy_source_id FROM vf_emotion_tags WHERE name = ?", (name,)).fetchone()
            if existing_tag and not existing_tag["legacy_source_id"]:
                target_conn.execute("UPDATE vf_emotion_tags SET color = COALESCE(?, color), sort_order = ?, legacy_source_id = ? WHERE id = ?", (item.get("color"), item.get("sort_order") or 0, source_id, existing_tag["id"]))
            elif not existing_tag:
                target_conn.execute("INSERT INTO vf_emotion_tags (id, name, description, color, sort_order, legacy_source_id) VALUES (?, ?, ?, ?, ?, ?)", (uuid.uuid4().hex, name, item.get("description") or "", item.get("color"), item.get("sort_order") or 0, source_id))
        for item in source["assets"]:
            if target_conn.execute("SELECT id FROM vf_assets WHERE legacy_source_id = ?", (str(item["id"]),)).fetchone():
                continue
            new_id = uuid.uuid4().hex
            source_path = item.get("file_path")
            key = copy_media(source_root, source_path, f"assets/{new_id}{Path(source_path or item.get('file_name') or 'audio.wav').suffix}", report, False)
            if not key:
                continue
            tags = item.get("tags") or []
            if not isinstance(tags, str):
                tags = json.dumps(tags, ensure_ascii=False)
            target_conn.execute("INSERT INTO vf_assets (id, name, asset_type, category, tags_json, storage_key, file_name, file_size, duration, description, legacy_source_id, legacy_import_batch_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (new_id, item.get("name") or "未命名素材", item.get("type") or "bgm", item.get("category"), tags, key, item.get("file_name") or safe_file_name(source_path), item.get("file_size") or 0, item.get("duration"), item.get("description") or "", str(item["id"]), batch_id))
    report["import_batch_id"] = batch_id
    for voice_id in voice_ids.values():
        write_voice_config(voice_id)
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    return report


def main():
    parser = argparse.ArgumentParser(description="只读复制 LcVoiceForgeaApp 数据到晴沐配音谷")
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report")
    parser.add_argument("--emotion-tags-only", action="store_true")
    args = parser.parse_args()
    report = migrate_emotion_tags(Path(args.source_root)) if args.emotion_tags_only else import_copy(Path(args.source_root), args.dry_run)
    content = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        Path(args.report).write_text(content, encoding="utf-8")
    print(content)


if __name__ == "__main__":
    main()

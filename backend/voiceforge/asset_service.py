import json
import mimetypes
import os
import subprocess
import uuid
import wave
from pathlib import Path

from fastapi import HTTPException

from backend.voiceforge.database import row_to_dict, session
from backend.voiceforge.storage import ALLOWED_AUDIO_EXTENSIONS, resolve_storage_key, safe_file_name


def _path_key(path):
    """路径去重键：归一化大小写与分隔符，Windows 下路径不区分大小写。"""
    return os.path.normcase(os.path.normpath(str(path))).replace("\\", "/")


def probe_audio_info(path):
    """探测音频元数据；探测失败时相关字段返回 None，不阻断入库。"""
    info = {"file_size": None, "format": None, "duration": None, "sample_rate": None, "channels": None}
    source = Path(path)
    if not source.is_file():
        return info
    info["file_size"] = source.stat().st_size
    suffix = source.suffix.lower().lstrip(".")
    info["format"] = suffix or None
    if suffix == "wav":
        try:
            with wave.open(str(source), "rb") as stream:
                params = stream.getparams()
                info["sample_rate"] = params.framerate
                info["channels"] = params.nchannels
                info["duration"] = params.nframes / max(params.framerate, 1)
        except Exception:
            pass
    else:
        try:
            completed = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration:stream=sample_rate,channels",
                    "-of", "json", str(source),
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=20,
            )
            data = json.loads(completed.stdout)
            fmt = data.get("format") or {}
            if fmt.get("duration"):
                info["duration"] = float(fmt["duration"])
            streams = data.get("streams") or []
            if streams:
                first = streams[0]
                if first.get("sample_rate"):
                    info["sample_rate"] = int(first["sample_rate"])
                if first.get("channels"):
                    info["channels"] = int(first["channels"])
        except Exception:
            pass
    return info


def resolve_asset_path(asset_row):
    """外部素材直接返回绝对路径；旧的上传复制记录回退到存储目录解析。"""
    if asset_row.get("external_path"):
        return Path(asset_row["external_path"])
    return resolve_storage_key(asset_row["storage_key"])


def get_asset(conn, asset_id: str):
    row = conn.execute("SELECT * FROM vf_assets WHERE id = ?", (asset_id,)).fetchone()
    return row_to_dict(row) if row else None


def create_online_asset(
    conn,
    name: str,
    asset_type: str,
    source_url: str,
    category: str = "",
    tags: list = None,
    description: str = "",
    source_site: str = "",
    source_id: str = "",
    file_size: int = 0,
    storage_key: str = None,
    file_name: str = None,
    mime_type: str = None,
    duration: float = None,
    downloaded: bool = False,
):
    """保存在线素材。

    - 仅记录源 URL（不下载）：``downloaded=False``，``external_path`` 设为 ``source_url``。
    - 已下载到本地 storage：``downloaded=True``，``external_path`` 留空，让本地存储键生效。
    """
    asset_id = uuid.uuid4().hex
    if not storage_key:
        storage_key = f"online/{asset_id}"
    if not file_name:
        file_name = safe_file_name(name or source_url, "online-audio.mp3")
    tags_json = json.dumps(tags or [])
    external_path = "" if downloaded else source_url
    path_key = storage_key if downloaded else (source_url or storage_key)
    conn.execute(
        "INSERT INTO vf_assets "
        "(id, name, asset_type, category, tags_json, storage_key, file_name, file_size, mime_type, duration, description, external_path, path_key, legacy_import_batch_id, legacy_source_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            asset_id, name, asset_type, category, tags_json, storage_key, file_name, file_size,
            mime_type, duration, description, external_path, path_key,
            source_site or None, source_id or None,
        ),
    )
    return get_asset(conn, asset_id)


def download_online_audio(source_url: str, asset_id: str, category: str = "sfx"):
    """把远程音频下载到 voiceforge 存储，返回 (storage_key, file_name, file_size, mime_type, duration)。"""
    import httpx

    from backend.voiceforge.services import audio_duration

    suffix = Path(source_url.split("?")[0]).suffix.lower()
    if suffix not in ALLOWED_AUDIO_EXTENSIONS:
        suffix = ".mp3"
    storage_key = f"{category}/{asset_id}{suffix}"
    destination = resolve_storage_key(storage_key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", source_url, timeout=60, follow_redirects=True) as response:
        response.raise_for_status()
        with destination.open("wb") as output:
            for chunk in response.iter_bytes(1024 * 1024):
                output.write(chunk)
    file_size = destination.stat().st_size
    mime_type = mimetypes.guess_type(destination.name)[0] or "audio/mpeg"
    duration = None
    try:
        duration = audio_duration(destination)
    except Exception:
        duration = None
    return storage_key, destination.name, file_size, mime_type, duration


def list_assets(
    conn,
    asset_type=None,
    category=None,
    tag=None,
    is_favorite=None,
    min_duration=None,
    max_duration=None,
    search="",
    page=1,
    page_size=20,
):
    clauses = ["1 = 1"]
    params = []
    if asset_type:
        clauses.append("asset_type = ?")
        params.append(asset_type)
    if category:
        clauses.append("category = ?")
        params.append(category)
    if tag:
        clauses.append("tags_json LIKE ?")
        params.append(f'%"{tag}"%')
    if is_favorite is not None:
        clauses.append("is_favorite = ?")
        params.append(1 if is_favorite else 0)
    if min_duration is not None:
        clauses.append("duration >= ?")
        params.append(min_duration)
    if max_duration is not None:
        clauses.append("duration <= ?")
        params.append(max_duration)
    if search:
        clauses.append("(name LIKE ? OR file_name LIKE ? OR description LIKE ?)")
        pattern = f"%{search}%"
        params.extend([pattern, pattern, pattern])
    where = " AND ".join(clauses)
    total = conn.execute(f"SELECT COUNT(*) FROM vf_assets WHERE {where}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM vf_assets WHERE {where} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        [*params, page_size, (page - 1) * page_size],
    ).fetchall()
    return [row_to_dict(row) for row in rows], total


def type_counts(conn):
    rows = conn.execute(
        "SELECT asset_type, COUNT(*) AS count FROM vf_assets GROUP BY asset_type"
    ).fetchall()
    return {row["asset_type"]: row["count"] for row in rows}


def create_asset(conn, name, asset_type, path, category=None, tags=None, description=""):
    """仅记录外部路径，不复制文件。以“类型 + 路径”去重：命中则只更新数据，不新建记录、不重复累加标签。"""
    source = Path(path)
    if source.suffix.lower() not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(400, "仅支持音频文件")
    if not source.is_file():
        raise HTTPException(404, "素材文件不存在")
    info = probe_audio_info(str(source))
    path_key = _path_key(source)
    existing = conn.execute(
        "SELECT * FROM vf_assets WHERE asset_type = ? AND path_key = ?",
        (asset_type, path_key),
    ).fetchone()
    if existing:
        updates = {}
        if name:
            updates["name"] = name
        if category is not None:
            updates["category"] = category
        if description:
            updates["description"] = description
        if tags:
            updates["tags"] = tags
        if updates:
            update_asset(conn, existing["id"], updates)
        conn.execute(
            "UPDATE vf_assets SET file_size = ?, mime_type = ?, duration = ?, sample_rate = ?, channels = ?, format = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (info["file_size"], mimetypes.guess_type(source.name)[0], info["duration"], info["sample_rate"], info["channels"], info["format"], existing["id"]),
        )
        return get_asset(conn, existing["id"]), False
    asset_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO vf_assets "
        "(id, name, asset_type, category, tags_json, storage_key, file_name, file_size, mime_type, duration, "
        "description, external_path, path_key, sample_rate, channels, format, is_favorite) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
        (
            asset_id,
            name or source.stem,
            asset_type,
            category,
            json.dumps(tags or [], ensure_ascii=False),
            f"external/{asset_id}",
            source.name,
            info["file_size"],
            mimetypes.guess_type(source.name)[0],
            info["duration"],
            description,
            str(source),
            path_key,
            info["sample_rate"],
            info["channels"],
            info["format"],
        ),
    )
    for tag_name in tags or []:
        bump_tag(conn, tag_name, +1)
    return get_asset(conn, asset_id), True


def update_asset(conn, asset_id: str, updates: dict):
    old = get_asset(conn, asset_id)
    if not old:
        return None
    old_tags = set(old.get("tags") or [])
    new_tags = updates.get("tags")
    fields = []
    values = []
    for key in ("name", "asset_type", "category", "tags", "description", "is_favorite"):
        if key not in updates:
            continue
        if key == "tags":
            fields.append("tags_json = ?")
            values.append(json.dumps(updates[key] or [], ensure_ascii=False))
        else:
            fields.append(f"{key} = ?")
            values.append(updates[key])
    if not fields:
        return old
    conn.execute(
        f"UPDATE vf_assets SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [*values, asset_id],
    )
    if new_tags is not None:
        new_set = set(new_tags)
        for tag_name in new_set - old_tags:
            bump_tag(conn, tag_name, +1)
        for tag_name in old_tags - new_set:
            bump_tag(conn, tag_name, -1)
    return get_asset(conn, asset_id)


def delete_assets(conn, asset_ids):
    """只删记录；旧的项目内复制记录（无 external_path）才清理项目内文件，外部文件一律不碰。"""
    placeholders = ",".join("?" for _ in asset_ids)
    rows = conn.execute(
        f"SELECT storage_key, external_path, tags_json FROM vf_assets WHERE id IN ({placeholders})",
        asset_ids,
    ).fetchall()
    for row in rows:
        if not row["external_path"]:
            resolve_storage_key(row["storage_key"]).unlink(missing_ok=True)
        for tag_name in json.loads(row["tags_json"] or "[]"):
            bump_tag(conn, tag_name, -1)
    conn.execute(f"DELETE FROM vf_assets WHERE id IN ({placeholders})", asset_ids)
    return len(rows)


def bump_tag(conn, name: str, delta: int):
    existing = conn.execute("SELECT id, usage_count FROM vf_asset_tags WHERE name = ?", (name,)).fetchone()
    if existing:
        usage = max(existing["usage_count"] + delta, 0)
        conn.execute("UPDATE vf_asset_tags SET usage_count = ? WHERE id = ?", (usage, existing["id"]))
    elif delta > 0:
        conn.execute("INSERT INTO vf_asset_tags (id, name, usage_count) VALUES (?, ?, 1)", (uuid.uuid4().hex, name))


def list_categories(conn, asset_type=None):
    sql = "SELECT * FROM vf_asset_categories"
    params = []
    if asset_type:
        sql += " WHERE asset_type = ?"
        params.append(asset_type)
    rows = conn.execute(sql + " ORDER BY asset_type, sort_order, id", params).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        count = conn.execute(
            "SELECT COUNT(*) FROM vf_assets WHERE category = ? AND asset_type = ?",
            (item["name"], item["asset_type"]),
        ).fetchone()[0]
        item["count"] = count
        result.append(item)
    return result


def create_category(conn, name, label, asset_type, sort_order=0):
    existing = conn.execute(
        "SELECT id FROM vf_asset_categories WHERE name = ? AND asset_type = ?", (name, asset_type)
    ).fetchone()
    if existing:
        raise HTTPException(409, "该类型下已存在同名分类")
    category_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO vf_asset_categories (id, name, label, asset_type, sort_order) VALUES (?, ?, ?, ?, ?)",
        (category_id, name, label, asset_type, sort_order),
    )
    return dict(conn.execute("SELECT * FROM vf_asset_categories WHERE id = ?", (category_id,)).fetchone())


def update_category(conn, category_id, updates):
    fields = [f"{key} = ?" for key in updates if key in ("name", "label", "sort_order")]
    if not fields:
        return None
    conn.execute(
        f"UPDATE vf_asset_categories SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        [*updates.values(), category_id],
    )
    return dict(conn.execute("SELECT * FROM vf_asset_categories WHERE id = ?", (category_id,)).fetchone()) or None


def delete_category(conn, category_id):
    row = conn.execute("SELECT id FROM vf_asset_categories WHERE id = ?", (category_id,)).fetchone()
    if not row:
        return False
    conn.execute("DELETE FROM vf_asset_categories WHERE id = ?", (category_id,))
    return True


def list_tags(conn, search="", asset_type=None):
    if asset_type:
        rows = conn.execute("SELECT tags_json FROM vf_assets WHERE asset_type = ?", (asset_type,)).fetchall()
        counter = {}
        for row in rows:
            for tag in json.loads(row["tags_json"] or "[]"):
                counter[tag] = counter.get(tag, 0) + 1
        if search:
            counter = {name: count for name, count in counter.items() if search in name}
        names = list(counter.keys())
        id_map = {}
        if names:
            placeholders = ",".join("?" for _ in names)
            for tag_row in conn.execute(
                f"SELECT id, name FROM vf_asset_tags WHERE name IN ({placeholders})", names
            ).fetchall():
                id_map[tag_row["name"]] = tag_row["id"]
        items = [
            {"id": id_map.get(name, name), "name": name, "usage_count": counter[name]}
            for name in sorted(counter, key=lambda name: -counter[name])
        ]
        return items[:100]
    sql = "SELECT * FROM vf_asset_tags"
    params = []
    if search:
        sql += " WHERE name LIKE ?"
        params.append(f"%{search}%")
    rows = conn.execute(sql + " ORDER BY usage_count DESC, name LIMIT 100", params).fetchall()
    return [dict(row) for row in rows]


def create_tag(conn, name):
    existing = conn.execute("SELECT * FROM vf_asset_tags WHERE name = ?", (name,)).fetchone()
    if existing:
        return dict(existing)
    tag_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO vf_asset_tags (id, name, usage_count) VALUES (?, ?, 0)", (tag_id, name)
    )
    return dict(conn.execute("SELECT * FROM vf_asset_tags WHERE id = ?", (tag_id,)).fetchone())


def delete_tag(conn, tag_id):
    row = conn.execute("SELECT id FROM vf_asset_tags WHERE id = ?", (tag_id,)).fetchone()
    if not row:
        return False
    conn.execute("DELETE FROM vf_asset_tags WHERE id = ?", (tag_id,))
    return True

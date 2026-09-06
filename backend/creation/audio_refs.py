"""音频类素材统一引用与 voiceforge 读写辅助。

音频、音色、音效、背景音乐的素材本体都在 voiceforge(vf_*)库中,创作项目
数据里引用它们时一律使用带前缀的引用格式 `vf:<表>:<id>`,以便与本地文件
路径、公共素材库 id 明确区分并可反查定位:

    vf:voices:<id>    vf_voices   音色
    vf:assets:<id>    vf_assets   音频素材(音效/背景音乐/配音素材等)
    vf:exports:<id>   vf_exports  导出音频片段
"""

import json
import re
import uuid

_VF_REF = re.compile(r"^vf:(voices|assets|exports):([A-Za-z0-9_-]+)$")
_VF_TABLES = {"voices": "vf_voices", "assets": "vf_assets", "exports": "vf_exports"}


def is_audio_ref(value: str) -> bool:
    return bool(_VF_REF.match(value or ""))


def make_voice_ref(voice_id: str) -> str:
    return f"vf:voices:{voice_id}"


def make_audio_asset_ref(asset_id: str) -> str:
    return f"vf:assets:{asset_id}"


def make_export_ref(export_id: str) -> str:
    return f"vf:exports:{export_id}"


def parse_audio_ref(ref: str) -> tuple[str, str]:
    """解析引用,返回 (表类别, 素材id);格式不对抛 ValueError。"""
    match = _VF_REF.match(ref or "")
    if not match:
        raise ValueError(f"非法音频素材引用(应为 vf:voices/assets/exports:<id>): {ref}")
    return match.group(1), match.group(2)


def resolve_audio_ref(ref: str) -> dict:
    """反查 voiceforge 库,返回素材完整行(含 storage_key、duration 等)。"""
    table_key, item_id = parse_audio_ref(ref)
    from backend.voiceforge.database import session as voiceforge_session

    with voiceforge_session() as conn:
        row = conn.execute(f"SELECT * FROM {_VF_TABLES[table_key]} WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise LookupError(f"音频素材不存在: {ref}")
    return dict(row)


def audio_ref_abspath(ref: str) -> str | None:
    """返回引用指向的音频文件绝对路径;素材没有存储键时返回 None。"""
    row = resolve_audio_ref(ref)
    storage_key = row.get("storage_key") or ""
    if not storage_key:
        return None
    from backend.voiceforge.database import storage_root

    root = storage_root().resolve()
    candidate = (root / storage_key).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"非法音频文件路径: {storage_key}")
    return str(candidate)


def list_voices(keyword: str = "") -> list[dict]:
    """列出音色库,可按名称/显示名模糊搜索。"""
    from backend.voiceforge.database import session as voiceforge_session

    sql = "SELECT id, name, display_name, language, gender, voice_age, description, status FROM vf_voices"
    params: tuple = ()
    if keyword:
        sql += " WHERE name LIKE ? OR display_name LIKE ?"
        params = (f"%{keyword}%", f"%{keyword}%")
    with voiceforge_session() as conn:
        return [dict(row) for row in conn.execute(sql + " ORDER BY created_at", params).fetchall()]


def list_audio_assets(asset_type: str = "", keyword: str = "") -> list[dict]:
    """列出音频素材(音效/背景音乐等),可按 asset_type(如 sfx/bgm)与关键词过滤。"""
    from backend.voiceforge.database import session as voiceforge_session

    sql = "SELECT id, name, asset_type, category, tags_json, file_name, duration, description, format FROM vf_assets"
    conditions, params = [], []
    if asset_type:
        conditions.append("asset_type = ?")
        params.append(asset_type)
    if keyword:
        conditions.append("(name LIKE ? OR description LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    with voiceforge_session() as conn:
        return [dict(row) for row in conn.execute(sql + " ORDER BY created_at", params).fetchall()]


def add_audio_asset(
    name: str,
    asset_type: str,
    *,
    storage_key: str,
    file_name: str,
    duration: float | None = None,
    description: str = "",
    category: str = "",
    mime_type: str = "",
    tags: list | None = None,
) -> dict:
    """向 voiceforge 音频素材库登记一条素材(不搬文件,storage_key 遵循 voiceforge 约定),返回其 vf:assets 引用。"""
    if not name or not storage_key or not file_name:
        raise ValueError("name、storage_key、file_name 不能为空")
    asset_id = uuid.uuid4().hex
    from backend.voiceforge.database import session as voiceforge_session

    with voiceforge_session() as conn:
        conn.execute(
            "INSERT INTO vf_assets (id, name, asset_type, category, tags_json, storage_key, file_name, mime_type, duration, description)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (asset_id, name, asset_type, category, json.dumps(tags or [], ensure_ascii=False), storage_key, file_name, mime_type, duration, description),
        )
    return {"id": asset_id, "ref": make_audio_asset_ref(asset_id), "name": name, "asset_type": asset_type, "storage_key": storage_key}


def update_audio_asset(asset_id: str, **fields) -> None:
    """更新音频素材元数据,可写字段:name/description/category/tags/duration/mime_type。"""
    allowed = {"name", "description", "category", "tags", "duration", "mime_type"}
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"不支持更新的字段: {sorted(unknown)}")
    assignments, params = [], []
    for key, value in fields.items():
        if key == "tags":
            key, value = "tags_json", json.dumps(value or [], ensure_ascii=False)
        assignments.append(f"{key} = ?")
        params.append(value)
    from backend.voiceforge.database import session as voiceforge_session

    with voiceforge_session() as conn:
        if conn.execute(f"UPDATE vf_assets SET {', '.join(assignments)} WHERE id = ?", (*params, asset_id)).rowcount != 1:
            raise LookupError(f"音频素材不存在: vf:assets:{asset_id}")


def delete_audio_asset(asset_id: str) -> None:
    """从 voiceforge 音频素材库删除登记(不删除磁盘文件)。"""
    from backend.voiceforge.database import session as voiceforge_session

    with voiceforge_session() as conn:
        if conn.execute("DELETE FROM vf_assets WHERE id = ?", (asset_id,)).rowcount != 1:
            raise LookupError(f"音频素材不存在: vf:assets:{asset_id}")

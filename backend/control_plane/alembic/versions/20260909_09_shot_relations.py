"""shot relation structuring (data migration)

分镜关联结构化数据迁移：
1. 存量分镜的 ``characters`` 由名字数组 ``["A"]`` 升级为 ``[{"name": "A", "id": "..."}]``，
   id 按同项目人物名/别名解析（未匹配留空，保持向后兼容读取）。
2. 回填 ``scene_id``：按 (地点+时间) 精确匹配场景，回退为按地点匹配。

Revision ID: 20260909_09
Revises: 20260909_08
"""

import json

import sqlalchemy as sa
from alembic import op


revision = "20260909_09"
down_revision = "20260909_08"
branch_labels = None
depends_on = None


def _load_json(raw, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return default


def _char_name(item):
    if isinstance(item, dict):
        return str(item.get("name") or "").strip()
    return str(item or "").strip()


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "cp_creation_shots" not in tables:
        return

    chap_creation = {}
    if "cp_creation_chapters" in tables:
        for cid, creation_id in bind.exec_driver_sql(
            "select id, creation_id from cp_creation_chapters"
        ).fetchall():
            chap_creation[cid] = creation_id

    # creation_id -> {人物名/别名: 人物 id}
    char_index = {}
    if "cp_creation_characters" in tables:
        for cid, creation_id, name, aliases in bind.exec_driver_sql(
            "select id, creation_id, name, aliases from cp_creation_characters"
        ).fetchall():
            idx = char_index.setdefault(creation_id, {})
            for key in [name, *(_load_json(aliases, []) or [])]:
                if key:
                    idx[str(key).strip()] = cid

    # creation_id -> {(地点,时间): 场景 id} / {地点: 场景 id}
    scene_index, scene_by_loc = {}, {}
    if "cp_creation_scenes" in tables:
        for sid, creation_id, loc, tm in bind.exec_driver_sql(
            "select id, creation_id, location, time from cp_creation_scenes"
        ).fetchall():
            loc = str(loc or "").strip()
            if not loc:
                continue
            scene_index.setdefault(creation_id, {})[(loc, str(tm or "").strip())] = sid
            scene_by_loc.setdefault(creation_id, {}).setdefault(loc, sid)

    rows = bind.exec_driver_sql(
        "select id, chapter_id, characters, location, time, scene_id from cp_creation_shots"
    ).fetchall()
    for shot_id, chapter_id, raw_chars, loc, tm, scene_id in rows:
        creation_id = chap_creation.get(chapter_id)
        new_chars = None
        chars = _load_json(raw_chars, None)
        if isinstance(chars, list) and any(not isinstance(c, dict) for c in chars):
            new_chars = []
            for item in chars:
                name = _char_name(item)
                if not name:
                    continue
                new_chars.append({"name": name,
                                  "id": (char_index.get(creation_id) or {}).get(name, "")})
        new_scene = None
        if not scene_id and creation_id:
            _loc, _tm = str(loc or "").strip(), str(tm or "").strip()
            new_scene = ((scene_index.get(creation_id) or {}).get((_loc, _tm))
                         or ((scene_by_loc.get(creation_id) or {}).get(_loc) if _loc else None))
        if new_chars is None and not new_scene:
            continue
        sets, params = [], []
        if new_chars is not None:
            sets.append("characters = ?")
            params.append(json.dumps(new_chars, ensure_ascii=False))
        if new_scene:
            sets.append("scene_id = ?")
            params.append(new_scene)
        params.append(shot_id)
        bind.exec_driver_sql(
            "update cp_creation_shots set " + ", ".join(sets) + " where id = ?",
            tuple(params),
        )


def downgrade() -> None:
    """结构化回退：{name,id} → 名字数组（scene_id 保留，避免破坏外键）。"""
    bind = op.get_bind()
    if "cp_creation_shots" not in set(sa.inspect(bind).get_table_names()):
        return
    for shot_id, raw_chars in bind.exec_driver_sql(
        "select id, characters from cp_creation_shots"
    ).fetchall():
        chars = _load_json(raw_chars, None)
        if not isinstance(chars, list) or not any(isinstance(c, dict) for c in chars):
            continue
        names = [n for n in (_char_name(c) for c in chars if isinstance(c, dict)) if n]
        bind.exec_driver_sql(
            "update cp_creation_shots set characters = ? where id = ?",
            (json.dumps(names, ensure_ascii=False), shot_id),
        )

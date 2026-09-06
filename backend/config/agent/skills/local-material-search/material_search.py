"""本地素材搜索 skill 脚本。

跨库搜索本项目的全部本地素材:
    image      图片素材库        cp_images          (控制面库 data/control-plane.db)
    video      视频素材库        cp_videos          (控制面库)
    character  公共角色库        cp_characters      (控制面库)
    asset      创作项目资产      cp_creation_assets (控制面库)
    voice      音色库            vf_voices          (voiceforge 库 voiceforge_data/voiceforge.db)
    audio      音频素材          vf_assets          (voiceforge 库,音效/背景音乐等)

支持按类(--kind)、按分组(--group)、按标签(--tag)、按描述/名称模糊查找(--query)。
必须用项目 venv 的 python 运行(依赖 sqlalchemy 等):
    venv312/Scripts/python.exe backend/config/agent/skills/local-material-search/material_search.py --kind image --query 走廊
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[5]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select

from backend.control_plane.database import session_scope
from backend.control_plane.models import Character, CreationAsset, ImageAsset, VideoAsset
from backend.creation import paths

KINDS = ("image", "video", "character", "asset", "voice", "audio")


def _iso(value):
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else value


def _load_tags(raw) -> list:
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def _fetch_images(session) -> list[dict]:
    rows = session.scalars(select(ImageAsset).order_by(ImageAsset.created_at)).all()
    return [
        {
            "kind": "image",
            "id": row.id,
            "name": Path(row.path).name,
            "description": row.description,
            "path": row.path,
            "abs_path": str(paths.resolve_storage_path(row.path)),
            "group_tags": list(row.group_tags or []),
            "custom_tags": list(row.custom_tags or []),
            "tags": [*list(row.group_tags or []), *list(row.custom_tags or [])],
            "width": row.width,
            "height": row.height,
            "aspect_ratio": row.aspect_ratio,
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def _fetch_videos(session) -> list[dict]:
    rows = session.scalars(select(VideoAsset).order_by(VideoAsset.created_at)).all()
    return [
        {
            "kind": "video",
            "id": row.id,
            "name": Path(row.path).name,
            "description": row.description,
            "path": row.path,
            "abs_path": str(paths.resolve_storage_path(row.path)),
            "group_tags": list(row.group_tags or []),
            "custom_tags": list(row.custom_tags or []),
            "tags": [*list(row.group_tags or []), *list(row.custom_tags or [])],
            "width": row.width,
            "height": row.height,
            "duration_seconds": row.duration_seconds,
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def _fetch_characters(session) -> list[dict]:
    rows = session.scalars(select(Character).order_by(Character.created_at)).all()
    return [
        {
            "kind": "character",
            "id": row.id,
            "name": row.name,
            "description": row.personality,
            "tags": list(row.tags or []),
            "aliases": list(row.aliases or []),
            "gender": row.gender,
            "age": row.age,
            "personality": row.personality,
            "occupation": row.occupation,
            "voice_design": row.voice_design,
            "voice_ref": row.voice_ref,
            "images_dir": row.images_dir,
            "origin_creation_id": row.origin_creation_id,
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def _fetch_creation_assets(session) -> list[dict]:
    rows = session.scalars(select(CreationAsset).order_by(CreationAsset.created_at)).all()
    return [
        {
            "kind": "asset",
            "asset_kind": row.asset_kind,
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "creation_id": row.creation_id,
            "chapter_id": row.chapter_id,
            "shot_id": row.shot_id,
            "ref_id": row.ref_id,
            "paths": list(row.paths or []),
            "sequence": row.sequence,
            "duration_seconds": row.duration_seconds,
            "created_at": _iso(row.created_at),
        }
        for row in rows
    ]


def _audio_abs_path(storage_key: str) -> str:
    if not storage_key:
        return ""
    try:
        from backend.voiceforge.database import storage_root

        root = storage_root().resolve()
        candidate = (root / storage_key).resolve()
        if candidate == root or root in candidate.parents:
            return str(candidate)
    except Exception:
        pass
    return ""


def _fetch_voices() -> list[dict]:
    from backend.voiceforge.database import session as vf_session

    with vf_session() as conn:
        rows = conn.execute(
            "SELECT id, name, display_name, gender, voice_age, language, description, tags_json, status FROM vf_voices ORDER BY created_at"
        ).fetchall()
    return [
        {
            "kind": "voice",
            "id": row["id"],
            "name": row["display_name"] or row["name"],
            "ref": f"vf:voices:{row['id']}",
            "description": row["description"],
            "tags": _load_tags(row["tags_json"]),
            "gender": row["gender"],
            "voice_age": row["voice_age"],
            "language": row["language"],
            "status": row["status"],
        }
        for row in rows
    ]


def _fetch_audio_assets() -> list[dict]:
    from backend.voiceforge.database import session as vf_session

    with vf_session() as conn:
        rows = conn.execute(
            "SELECT id, name, asset_type, category, tags_json, storage_key, duration, description FROM vf_assets ORDER BY created_at"
        ).fetchall()
    return [
        {
            "kind": "audio",
            "id": row["id"],
            "name": row["name"],
            "ref": f"vf:assets:{row['id']}",
            "asset_type": row["asset_type"],
            "category": row["category"],
            "description": row["description"],
            "tags": _load_tags(row["tags_json"]),
            "storage_key": row["storage_key"],
            "abs_path": _audio_abs_path(row["storage_key"]),
            "duration_seconds": row["duration"],
        }
        for row in rows
    ]


def collect(kind: str, warnings: list[str]) -> list[dict]:
    """按类拉取素材记录;kind=all 时返回全部。voiceforge 不可用时记入 warnings 并跳过。"""
    records: list[dict] = []
    kinds = KINDS if kind == "all" else (kind,)
    need_session_kinds = [item for item in kinds if item in ("image", "video", "character", "asset")]
    with session_scope() as session:
        for item in need_session_kinds:
            if item == "image":
                records.extend(_fetch_images(session))
            elif item == "video":
                records.extend(_fetch_videos(session))
            elif item == "character":
                records.extend(_fetch_characters(session))
            else:
                records.extend(_fetch_creation_assets(session))
    for item in (k for k in kinds if k in ("voice", "audio")):
        try:
            records.extend(_fetch_voices() if item == "voice" else _fetch_audio_assets())
        except Exception as exc:
            warnings.append(f"voiceforge {item} 读取失败(库未初始化或表缺失): {type(exc).__name__}: {exc}")
    return records


def _record_text(record: dict) -> str:
    parts: list[str] = []

    def walk(value):
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            parts.append(value)
        elif value is not None:
            parts.append(str(value))

    for key, value in record.items():
        if key == "kind":
            continue
        walk(value)
    return " ".join(parts).casefold()


def search(records: list[dict], *, group: str = "", tag: str = "", query: str = "", asset_kind: str = "") -> list[dict]:
    result = []
    needle = query.strip().casefold()
    for record in records:
        if asset_kind and record.get("kind") == "asset" and record.get("asset_kind") != asset_kind:
            continue
        if group and group not in list(record.get("group_tags") or []):
            continue
        if tag and tag not in list(record.get("tags") or []):
            continue
        if needle and needle not in _record_text(record):
            continue
        result.append(record)
    return result


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(prog="material_search.py", description="本地素材跨库搜索:图片/视频/角色/创作资产/音色/音频")
    parser.add_argument("--kind", default="all", choices=["all", *KINDS], help="按类搜索,默认全部")
    parser.add_argument("--group", default="", help="按分组标签过滤(仅 image/video 有分组字段)")
    parser.add_argument("--tag", default="", help="按标签过滤(分组+自定义/角色标签/音频标签)")
    parser.add_argument("--query", default="", help="按描述/名称/路径等字段模糊查找(大小写不敏感)")
    parser.add_argument("--asset-kind", default="", help="仅 --kind asset/all 时:过滤创作资产类型,如 scene_image/voiceover/bgm")
    parser.add_argument("--limit", type=int, default=50, help="最多返回条数,默认 50")
    parser.add_argument("--stats", action="store_true", help="只输出各素材类数量统计")
    parser.add_argument("--output", default="", help="结果写入 JSON 文件(默认打印终端)")
    args = parser.parse_args(argv)

    warnings: list[str] = []
    records = collect(args.kind, warnings)

    if args.stats:
        counts = {item: sum(1 for record in records if record["kind"] == item) for item in KINDS}
        payload = {"stats": counts, "warnings": warnings}
    else:
        matched = search(records, group=args.group, tag=args.tag, query=args.query, asset_kind=args.asset_kind)
        payload = {
            "total": len(matched),
            "returned": min(len(matched), max(args.limit, 0)),
            "results": matched[: max(args.limit, 0)],
            "warnings": warnings,
        }

    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"已写入 {args.output}(共 {payload.get('total', len(records))} 条)")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

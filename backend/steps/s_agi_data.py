"""AI 漫剧·项目数据读写节点。

把创作项目的数据面能力暴露成可编排节点，让外部节点（LLM / 生图 / 生视频 /
配音 / 剪辑等）可以自由接入漫剧生产链：

    agi_query          项目数据查询：读项目/章节/分镜/人物/场景/道具/素材
    agi_write          项目数据写入：把外部处理结果回写到项目指定数据点
    agi_asset_register 素材登记入库：把外部产物登记为项目资产

约定：
- 读写全部经 ``backend.creation`` 数据层，字段白名单由数据层校验并抛出可读错误；
- ``agi_query`` 同时输出 ``items``(JSON) 与 ``text``(文本)，后者可直接喂给 LLM
  节点做提示词优化，形成「查询 → 外部加工 → 写回」的自由编排；
- 每次执行写一份 cache JSON 作为产物，保证产物校验与重跑行为与其它节点一致。
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional

from backend.steps.base_step import BaseStep

# 查询目标：项目主表 / 章节 / 分镜 / 人物 / 场景 / 道具 / 素材
_QUERY_TARGETS = (
    "creation", "chapters", "chapter", "shots", "shot",
    "characters", "scenes", "props", "assets",
)

# 写入目标：每条记录一个 id，补丁字段由数据层白名单校验
_WRITE_TARGETS = ("creation", "chapter", "shot", "character", "scene", "prop", "asset")

# 素材类型自动推断（按扩展名兜底）
_ASSET_KIND_GUESS = (
    ((".mp4", ".mov", ".mkv", ".webm", ".avi"), "shot_video"),
    ((".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg"), "voiceover"),
    ((".png", ".jpg", ".jpeg", ".webp", ".bmp"), "shot_render"),
)

_TEXT_LIMIT = 20000


# --------------------------------------------------------------------------- #
# 通用工具
# --------------------------------------------------------------------------- #
def _cfg(step) -> dict:
    return getattr(step, "_node_config", {}) or {}


def _inputs(step) -> dict:
    return getattr(step, "_step_inputs", {}) or {}


def _node_id(step) -> str:
    return getattr(step, "_node_id", "unknown")


def _cache_path(task_dir: str, node_id: str, prefix: str) -> str:
    return os.path.join(task_dir, "cache", f"agi_{prefix}_{node_id}.json")


def _write_cache(task_dir: str, node_id: str, prefix: str, data: dict) -> str:
    path = _cache_path(task_dir, node_id, prefix)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return os.path.relpath(path, task_dir)


def _as_text(value) -> str:
    """端口值转字符串：列表取首个非空项。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        for item in value:
            text = _as_text(item)
            if text:
                return text
        return ""
    return str(value).strip()


def _read_text(value) -> str:
    """端口值可能是文本，也可能是文本文件路径，统一读成字符串。"""
    text = _as_text(value)
    if text and os.path.isfile(text):
        try:
            with open(text, "r", encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return text
    return text


def _as_list(value) -> list:
    """端口值转列表：支持列表、JSON 数组字符串、逗号/换行分隔字符串。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        out: list = []
        for item in value:
            out.extend(_as_list(item))
        return out
    if isinstance(value, dict):
        return [value]
    text = _as_text(value)
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except Exception:  # noqa: BLE001
        parsed = None
    if isinstance(parsed, list):
        out = []
        for item in parsed:
            out.extend(_as_list(item))
        return out
    if isinstance(parsed, (str, int, float)):
        return [str(parsed)]
    out = []
    for line in text.replace("\r", "\n").split("\n"):
        for piece in line.split(","):
            piece = piece.strip()
            if piece:
                out.append(piece)
    return out


def _as_int(value, default: int = 0) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _as_float(value, default=None):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _parse_data(value):
    """解析写入数据，返回 ``(patch, entries)``。

    - dict → patch：同一份补丁应用到 ``ids`` 中的每条记录；
    - list[dict] → entries：每条自带 id，逐条写入。
    """
    raw = value
    if isinstance(raw, str):
        text = _read_text(raw)
        if not text:
            return {}, []
        try:
            raw = json.loads(text)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"data 不是合法 JSON：{exc}") from exc
    if isinstance(raw, dict):
        return dict(raw), []
    if isinstance(raw, (list, tuple)):
        return {}, [dict(x) for x in raw if isinstance(x, dict)]
    return {}, []


def _pick_fields(item: dict, fields: List[str]) -> dict:
    """按配置裁剪字段，减少后续 LLM 节点的输入长度。"""
    if not fields:
        return item
    return {k: item.get(k) for k in fields if k in item}


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _to_text(items: list, limit: int = _TEXT_LIMIT) -> str:
    """把查询结果转成可直接喂给 LLM 的文本。"""
    if not items:
        return ""
    text = json.dumps(items, ensure_ascii=False, indent=2)
    if len(text) > limit:
        text = text[:limit] + "\n…(内容过长已截断)"
    return text


def _guess_kind(path: str) -> str:
    ext = os.path.splitext(str(path))[1].lower()
    for extensions, kind in _ASSET_KIND_GUESS:
        if ext in extensions:
            return kind
    return "shot_render"


def _creator_of(agi, target: str, ids: list, chapter_id: str):
    """未提供 creation_id 时，从 chapter/shot 反查项目。"""
    chid = chapter_id
    if not chid and ids:
        if target == "chapter":
            chid = str(ids[0])
        elif target == "shot":
            chid = agi.get_shot(str(ids[0])).get("chapter_id") or ""
    if chid:
        return (agi.get_chapter(chid).get("creation_id") or ""), chid
    return "", chid


def _load_items(agi, target: str, creation_id: str, chapter_id: str,
                ids: list, asset_kind: str) -> list:
    """按 target 取出记录列表。"""
    if target == "creation":
        return [agi.get_creation(creation_id, with_detail=True)]
    if target == "chapters":
        return list(agi.list_chapters(creation_id))
    if target == "chapter":
        if not chapter_id:
            raise RuntimeError("target=chapter 需要提供章节：请连接 chapter_id 或填写记录ID")
        return [agi.get_chapter(chapter_id, with_shots=True)]
    if target == "shots":
        if chapter_id:
            return list(agi.get_chapter(chapter_id, with_shots=True).get("shots") or [])
        out: list = []
        for chapter in agi.list_chapters(creation_id, with_shots=True):
            out.extend(chapter.get("shots") or [])
        return out
    if target == "shot":
        if not ids:
            raise RuntimeError("target=shot 需要提供分镜ID：请连接 ids 或填写记录ID")
        return [agi.get_shot(str(sid)) for sid in ids]
    if target == "characters":
        return list(agi.get_creation(creation_id, with_detail=True).get("characters") or [])
    if target == "scenes":
        return list(agi.list_scenes(creation_id))
    if target == "props":
        return list(agi.list_props(creation_id))
    if target == "assets":
        return list(agi.list_assets(creation_id, asset_kind=asset_kind, chapter_id=chapter_id or ""))
    return []


# --------------------------------------------------------------------------- #
# 项目数据查询
# --------------------------------------------------------------------------- #
class S_AGI_Query(BaseStep):
    """读取项目内指定数据点，输出 JSON 与文本，供外部节点加工。

    典型用法：读取某章全部分镜的 image_prompt → 交给 LLM 节点批量改写 →
    交给「项目数据写入」节点写回。
    """

    step_id = "agi_query"
    step_name = "项目数据查询"
    dependencies: list = []
    artifacts: list = []

    def check_artifact(self, task_dir: str) -> bool:
        return os.path.isfile(_cache_path(task_dir, _node_id(self), "query"))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> Dict[str, Any]:
        from backend import creation as agi

        cfg = _cfg(self)
        inp = _inputs(self)
        nid = _node_id(self)

        target = (_as_text(cfg.get("target")) or "shots").lower()
        if target not in _QUERY_TARGETS:
            raise RuntimeError(f"不支持的数据目标：{target}，可选 {sorted(_QUERY_TARGETS)}")

        fields = [str(f).strip() for f in _as_list(cfg.get("fields")) if str(f).strip()]
        status = _as_text(cfg.get("status"))
        asset_kind = _as_text(cfg.get("asset_kind"))
        limit = _as_int(cfg.get("limit"), 0)

        creation_id = _as_text(inp.get("creation_id")) or _as_text(cfg.get("creation_id"))
        chapter_id = _as_text(inp.get("chapter_id")) or _as_text(cfg.get("chapter_id"))
        ids = _as_list(inp.get("ids"))

        if not creation_id:
            creation_id, chapter_id = _creator_of(agi, target, ids, chapter_id)
        if not creation_id:
            raise RuntimeError("缺少 creation_id：请连接上游项目节点，或在配置中选择创作项目")
        agi.get_creation(creation_id)  # 校验项目存在

        items = _load_items(agi, target, creation_id, chapter_id, ids, asset_kind)

        if target != "creation" and ids:
            wanted = {str(x) for x in ids}
            filtered = [it for it in items if str(it.get("id") or "") in wanted]
            if filtered:
                items = filtered
        if status:
            items = [it for it in items if str(it.get("status") or "") == status]
        if limit > 0:
            items = items[:limit]
        items = [_pick_fields(it, fields) for it in items]

        cache = _write_cache(task_dir, nid, "query", {
            "creation_id": creation_id, "target": target,
            "count": len(items), "items": items,
        })
        if callback:
            callback(100, f"查询 {target}：{len(items)} 条")

        return {
            "artifacts": [cache],
            "outputs": {
                "creation_id": creation_id,
                "target": target,
                "count": len(items),
                "ids": _dump([it.get("id") for it in items if it.get("id")]),
                "items": _dump(items),
                "text": _to_text(items),
            },
        }


# --------------------------------------------------------------------------- #
# 项目数据写入
# --------------------------------------------------------------------------- #
class S_AGI_Write(BaseStep):
    """把外部处理结果回写到项目指定数据点。

    两种数据形态：
    - ``data`` 为 JSON 对象：同一份补丁批量应用到 ``ids`` 中的每条记录；
    - ``data`` 为 JSON 数组：每项自带 ``id``，逐条写入（适合 LLM 批量改写结果）。
    """

    step_id = "agi_write"
    step_name = "项目数据写入"
    dependencies: list = []
    artifacts: list = []

    def check_artifact(self, task_dir: str) -> bool:
        return os.path.isfile(_cache_path(task_dir, _node_id(self), "write"))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> Dict[str, Any]:
        from backend import creation as agi

        cfg = _cfg(self)
        inp = _inputs(self)
        nid = _node_id(self)

        target = (_as_text(cfg.get("target")) or "shot").lower()
        if target not in _WRITE_TARGETS:
            raise RuntimeError(f"不支持的数据目标：{target}，可选 {sorted(_WRITE_TARGETS)}")

        creation_id = _as_text(inp.get("creation_id")) or _as_text(cfg.get("creation_id"))
        ids = _as_list(inp.get("ids")) or _as_list(cfg.get("ids"))
        patch, entries = _parse_data(
            inp.get("data") if inp.get("data") is not None else cfg.get("data")
        )
        if not patch and not entries:
            raise RuntimeError("缺少写入数据：请连接 data（JSON 对象或对象数组）")

        if target != "creation":
            if not ids and not entries:
                raise RuntimeError("缺少记录ID：请连接 ids，或让 data 数组每项自带 id")
            if not creation_id:
                creation_id, _ = _creator_of(agi, target, ids or [e.get("id") for e in entries], "")
            if not creation_id:
                raise RuntimeError("缺少 creation_id：请连接上游项目节点")

        updaters = {
            "creation": lambda rid, values: agi.update_creation(creation_id, **values),
            "chapter": lambda rid, values: agi.update_chapter(rid, **values),
            "shot": lambda rid, values: agi.update_shot(rid, **values),
            "character": lambda rid, values: agi.update_creation_character(rid, **values),
            "scene": lambda rid, values: agi.update_scene(rid, **values),
            "prop": lambda rid, values: agi.update_prop(rid, **values),
            "asset": lambda rid, values: agi.update_asset(rid, **values),
        }
        update = updaters[target]

        updated: list = []
        if target == "creation":
            values = dict(patch or (entries[0] if entries else {}))
            values.pop("id", None)
            values.pop("target_id", None)
            if not values:
                raise RuntimeError("写入数据为空")
            updated.append(update(creation_id, values))
        elif entries:
            total = len(entries)
            for index, entry in enumerate(entries):
                values = dict(entry)
                rid = str(values.pop("id", "") or values.pop("target_id", "") or "").strip()
                if not rid:
                    raise RuntimeError("data 数组中的每一项都必须含 id 字段")
                updated.append(update(rid, values))
                if callback:
                    callback(int(100 * (index + 1) / total), f"写回 {target} {index + 1}/{total}")
        else:
            total = len(ids)
            for index, rid in enumerate(ids):
                updated.append(update(str(rid), dict(patch)))
                if callback:
                    callback(int(100 * (index + 1) / total), f"写回 {target} {index + 1}/{total}")

        if target != "creation" and callback:
            callback(100, f"写回 {target}：{len(updated)} 条")

        cache = _write_cache(task_dir, nid, "write", {
            "creation_id": creation_id, "target": target,
            "count": len(updated), "updated": updated,
        })
        return {
            "artifacts": [cache],
            "outputs": {
                "creation_id": creation_id,
                "target": target,
                "count": len(updated),
                "ids": _dump([u.get("id") for u in updated if u.get("id")]),
                "updated": _dump(updated),
            },
        }


# --------------------------------------------------------------------------- #
# 素材登记入库
# --------------------------------------------------------------------------- #
class S_AGI_AssetRegister(BaseStep):
    """把外部产物（生图/生视频/配音等）登记为项目资产，供导出节点消费。"""

    step_id = "agi_asset_register"
    step_name = "素材登记入库"
    dependencies: list = []
    artifacts: list = []

    def check_artifact(self, task_dir: str) -> bool:
        return os.path.isfile(_cache_path(task_dir, _node_id(self), "asset_register"))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> Dict[str, Any]:
        from backend import creation as agi

        cfg = _cfg(self)
        inp = _inputs(self)
        nid = _node_id(self)

        creation_id = _as_text(inp.get("creation_id")) or _as_text(cfg.get("creation_id"))
        shot_id = _as_text(inp.get("shot_id")) or _as_text(cfg.get("shot_id"))
        chapter_id = _as_text(inp.get("chapter_id")) or _as_text(cfg.get("chapter_id"))

        if not creation_id and shot_id:
            chapter_id = chapter_id or (agi.get_shot(shot_id).get("chapter_id") or "")
            if chapter_id:
                creation_id = agi.get_chapter(chapter_id).get("creation_id") or ""
        if not creation_id:
            raise RuntimeError("缺少 creation_id：请连接上游项目节点，或在配置中选择创作项目")

        paths = _as_list(inp.get("files"))
        if not paths:
            raise RuntimeError("缺少 files：请连接生图/生视频/配音等节点的文件输出")

        kind_cfg = _as_text(cfg.get("asset_kind")) or "auto"
        name_cfg = _as_text(cfg.get("name"))
        description = _as_text(cfg.get("description"))
        ref_id = _as_text(cfg.get("ref_id"))
        duration = _as_float(cfg.get("duration_seconds"))
        batch = len(paths) > 1

        assets: list = []
        for index, path in enumerate(paths):
            name = name_cfg or os.path.basename(str(path))
            if batch and name_cfg:
                name = f"{name_cfg}_{index + 1}"
            assets.append(agi.register_asset(
                creation_id,
                kind_cfg if kind_cfg != "auto" else _guess_kind(str(path)),
                chapter_id=chapter_id or None,
                shot_id=shot_id or None,
                name=name,
                ref_id=ref_id or None,
                paths_list=[str(path)],
                sequence=index if batch else None,
                duration_seconds=duration,
                description=description,
            ))
            if callback:
                callback(int(100 * (index + 1) / len(paths)),
                         f"登记素材 {index + 1}/{len(paths)}")

        cache = _write_cache(task_dir, nid, "asset_register", {
            "creation_id": creation_id, "count": len(assets), "assets": assets,
        })
        return {
            "artifacts": [cache],
            "outputs": {
                "creation_id": creation_id,
                "count": len(assets),
                "asset_ids": _dump([a.get("id") for a in assets if a.get("id")]),
                "assets": _dump(assets),
                "paths": _dump([str(p) for p in paths]),
            },
        }

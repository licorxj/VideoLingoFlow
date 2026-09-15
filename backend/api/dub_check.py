"""配音可视化检查：读取 / 更新 / 重生配音片段。

服务于工作流节点「配音可视化检查」的检查页弹窗（DubCheckDialog）。
数据以 s09_tts 产出的 dub_task.json 为唯一事实源，重生复用 S09TTS 的合成逻辑，
保证与正式配音链路（模式、参考音频、音色、调速容差）完全一致。
"""

import json
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.utils.audio_speed import get_audio_duration

router = APIRouter()

# 与 s09_tts 一致：段落原始参考音频的切割输出目录
_REFE_DIR = os.path.join("cache", "refe")

# 变速/对齐阶段写回的字段：重生成后必须清除，交由下游重新计算
# （与 s09_tts._clear_downstream_fields 保持一致）
_SPEED_CACHE_FIELDS = (
    "audio_file_adjusted",
    "adjusted_duration",
    "video_speed_ratio",
    "overflow",
    "need_truncate",
    "truncate_target_dur",
    "target_start",
    "target_end",
    "theory_gap",
    "new_start",
    "new_end",
)


# ---------------------------------------------------------------- 路径解析
def _workspace_root() -> Path:
    return Path(
        os.getenv("CONTROL_PLANE_WORKSPACE_ROOT", Path.cwd() / "control_plane_workspaces")
    ).resolve()


def _resolve_dub_path(path: str, task_id: str = "") -> Path:
    """解析配音任务 JSON 绝对路径：绝对路径直接用，相对路径按任务工作区解析。"""
    value = (path or "").strip()
    if not value:
        raise HTTPException(400, "配音任务路径为空")
    candidate = Path(value)
    if candidate.is_file():
        return candidate
    if task_id:
        root = _workspace_root()
        joined = (root / task_id / value).resolve()
        if root in joined.parents and joined.is_file():
            return joined
    raise HTTPException(404, f"配音任务文件不存在: {value}")


def _task_dir_of(dub_path: Path, task_id: str = "") -> Path:
    """配音任务所在任务目录（dub_task.json 位于 <task_dir>/cache/ 下）。"""
    parent = dub_path.parent
    if parent.name.lower() == "cache":
        return parent.parent
    if task_id:
        root = _workspace_root()
        candidate = (root / task_id).resolve()
        if candidate.is_dir():
            return candidate
    return parent


def _abs_in(task_dir: Path, raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    if os.path.isabs(value):
        return value
    return str(task_dir / value)


def _rel_in(task_dir: Path, abs_path: str) -> str:
    try:
        return os.path.relpath(abs_path, str(task_dir)).replace("\\", "/")
    except ValueError:
        return abs_path


def _clear_speed_cache(seg: dict, task_dir: Path) -> int:
    """清除该句的变速缓存（文件 + 字段），使下游变速/合并重新计算。

    删除 audio_file_adjusted 指向的文件；未记录该字段时按
    audio_file 推导 ``<stem>_adjusted<ext>``（如 cache/dub_temp/0001_adjusted.wav）。
    返回实际删除的文件数。
    """
    candidates: list[str] = []
    adjusted = str(seg.get("audio_file_adjusted") or "").strip()
    if adjusted:
        candidates.append(_abs_in(task_dir, adjusted))

    base = str(seg.get("audio_file") or "").strip()
    if base:
        origin = Path(_abs_in(task_dir, base))
        if origin.suffix:
            candidates.append(str(origin.with_name(f"{origin.stem}_adjusted{origin.suffix}")))

    removed = 0
    for path in candidates:
        try:
            if path and os.path.isfile(path):
                os.remove(path)
                removed += 1
        except OSError:
            continue

    for field in _SPEED_CACHE_FIELDS:
        seg.pop(field, None)
    return removed


def _segment_ref_audio(seg: dict, task_dir: Path) -> str:
    """段落参考音频：优先显式指定（ref_audio），回退 s09 切割的 cache/refe/<idx>.wav。"""
    explicit = str(seg.get("ref_audio") or "").strip()
    if explicit:
        return _rel_in(task_dir, _abs_in(task_dir, explicit))
    idx = seg.get("index", 0)
    try:
        idx_int = int(idx)
    except (TypeError, ValueError):
        idx_int = 0
    candidate = task_dir / _REFE_DIR / f"{idx_int:04d}.wav"
    return _rel_in(task_dir, str(candidate)) if candidate.is_file() else ""


def _load(dub_path: Path) -> dict:
    try:
        with open(dub_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"配音任务解析失败: {exc}") from None
    if not isinstance(data, dict):
        raise HTTPException(400, "配音任务格式非法（应为包含 segments 的对象）")
    if not isinstance(data.get("segments"), list):
        data["segments"] = []
    return data


def _save(dub_path: Path, data: dict) -> None:
    with open(dub_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def _speed_ratio(seg: dict) -> float:
    """变速比率 = 配音时长 / 原始时长。

    缺时长数据时回退到任务单里记录的 speed_ratio / speed_factor。
    """
    try:
        original = float(seg.get("original_duration") or seg.get("duration") or 0)
        real = float(seg.get("real_duration") or 0)
    except (TypeError, ValueError):
        return 1.0
    if original > 0 and real > 0:
        return round(real / original, 4)
    try:
        return round(float(seg.get("speed_ratio", seg.get("speed_factor", 1.0)) or 1.0), 4)
    except (TypeError, ValueError):
        return 1.0


def _view(seg: dict, task_dir: Path) -> dict:
    """把 segment 转成前端列表所需的展示结构。"""
    idx = seg.get("index", 0)
    audio_rel = str(seg.get("audio_file") or "").strip()
    audio_abs = _abs_in(task_dir, audio_rel)
    ref_rel = _segment_ref_audio(seg, task_dir)
    return {
        "index": idx,
        "id": idx,
        "text": seg.get("text", "") or "",
        "dub_text": seg.get("dub_text", seg.get("trans_text", "")) or "",
        "read_text": seg.get("read_text", "") or "",
        "read_tone_desc": seg.get("read_tone_desc", "") or "",
        "ref_audio": ref_rel,
        "ref_audio_exists": bool(ref_rel) and os.path.isfile(_abs_in(task_dir, ref_rel)),
        "audio_file": audio_rel,
        "audio_exists": bool(audio_rel) and os.path.isfile(audio_abs) and os.path.getsize(audio_abs) > 0,
        "original_duration": seg.get("original_duration", seg.get("duration", 0)) or 0,
        "duration": seg.get("duration", 0) or 0,
        "real_duration": seg.get("real_duration", 0) or 0,
        "speed_ratio": _speed_ratio(seg),
        "start": seg.get("start", 0) or 0,
        "end": seg.get("end", 0) or 0,
    }


# ---------------------------------------------------------------- 接口
class LoadRequest(BaseModel):
    path: str
    task_id: str = ""


@router.post("/load")
async def load_segments(req: LoadRequest):
    dub_path = _resolve_dub_path(req.path, req.task_id)
    task_dir = _task_dir_of(dub_path, req.task_id)
    data = _load(dub_path)
    segments = [_view(seg, task_dir) for seg in data.get("segments", [])]
    return {
        "path": str(dub_path),
        "task_dir": str(task_dir),
        "total": len(segments),
        "segments": segments,
    }


class UpdateItem(BaseModel):
    index: int
    read_text: Optional[str] = None
    read_tone_desc: Optional[str] = None
    ref_audio: Optional[str] = None
    speed_ratio: Optional[float] = None


class UpdateRequest(BaseModel):
    path: str
    task_id: str = ""
    items: list[UpdateItem]


@router.post("/update")
async def update_segments(req: UpdateRequest):
    """更新段落的可编辑字段（朗读文本 / 朗读指令 / 参考音频 / 变速比率）并落盘。"""
    dub_path = _resolve_dub_path(req.path, req.task_id)
    task_dir = _task_dir_of(dub_path, req.task_id)
    data = _load(dub_path)
    segments = data.get("segments", [])

    by_index = {}
    for seg in segments:
        try:
            by_index[int(seg.get("index", -1))] = seg
        except (TypeError, ValueError):
            continue

    updated = 0
    for item in req.items:
        seg = by_index.get(int(item.index))
        if seg is None:
            continue
        if item.read_text is not None:
            seg["read_text"] = item.read_text
        if item.read_tone_desc is not None:
            seg["read_tone_desc"] = item.read_tone_desc
        if item.ref_audio is not None:
            seg["ref_audio"] = item.ref_audio.strip()
        if item.speed_ratio is not None:
            seg["speed_ratio"] = float(item.speed_ratio)
        updated += 1

    _save(dub_path, data)
    return {"success": True, "updated": updated, "segments": [_view(s, task_dir) for s in segments]}


class RegenItem(BaseModel):
    index: int
    speed: Optional[float] = None
    # 前端已编辑的朗读文本/指令：重生前写回，保证用最新文本合成并落盘
    read_text: Optional[str] = None
    read_tone_desc: Optional[str] = None


class RegenerateRequest(BaseModel):
    path: str
    task_id: str = ""
    indices: list[int] = []
    speed: Optional[float] = None
    # 每条独立的重生速率（优先于上面的统一 speed）
    items: list[RegenItem] = []
    # TTS 接口设置（来自检查页顶部控件）
    engine: str = ""
    mode: str = ""
    voice: str = ""
    ref_audio: str = ""
    voice_design: str = ""
    controllable_clone: str = ""


@router.post("/regenerate")
async def regenerate_segments(req: RegenerateRequest):
    """对选中段落重新配音（可指定语速），复用 s09_tts 的合成逻辑。

    段落级参考音频优先（seg.ref_audio），未指定时用顶部控件的全局参考音频。
    合成后回写 real_duration / speed_ratio，并把结果落盘到 dub_task.json。
    """
    from backend.steps.s09_tts import S09TTS

    dub_path = _resolve_dub_path(req.path, req.task_id)
    task_dir = _task_dir_of(dub_path, req.task_id)
    data = _load(dub_path)
    segments = data.get("segments", [])

    by_index = {}
    for seg in segments:
        try:
            by_index[int(seg.get("index", -1))] = seg
        except (TypeError, ValueError):
            continue

    item_by_index = {}
    speed_by_index = {}
    for item in req.items or []:
        item_by_index[int(item.index)] = item
        speed_by_index[int(item.index)] = item.speed

    targets = []
    if req.indices:
        for raw in req.indices:
            seg = by_index.get(int(raw))
            if seg is not None:
                targets.append(seg)
    elif speed_by_index:
        for raw in speed_by_index:
            seg = by_index.get(int(raw))
            if seg is not None:
                targets.append(seg)
    if not targets:
        raise HTTPException(400, "没有可重生的段落（请先在列表中勾选条目）")

    # 未指定 TTS 引擎时回退任务内 tts_config.json，保证与正式链路一致
    engine = (req.engine or "").strip()
    mode = (req.mode or "").strip()
    voice = (req.voice or "").strip()
    ref_audio_global = (req.ref_audio or "").strip()
    voice_design = (req.voice_design or "").strip()
    cc_instruction = (req.controllable_clone or "").strip()
    if not engine or not mode:
        cfg_path = task_dir / "cache" / "tts_config.json"
        if cfg_path.is_file():
            try:
                with open(cfg_path, "r", encoding="utf-8") as handle:
                    cached = json.load(handle)
                engine = engine or str(cached.get("engine") or "")
                mode = mode or str(cached.get("mode") or "")
                ref_audio_global = ref_audio_global or str(cached.get("ref_audio_path") or "")
                roles = cached.get("voice_roles") or []
                voice = voice or (str(roles[0]) if roles else "")
                designs = cached.get("voice_design_roles") or []
                voice_design = voice_design or (str(designs[0]) if designs else "")
            except Exception:  # noqa: BLE001
                pass
    if not engine:
        raise HTTPException(400, "未指定 TTS 引擎，请在检查页顶部的 TTS 接口设置中选择接口")
    if not mode:
        raise HTTPException(400, "未指定 TTS 模式，请在检查页顶部的 TTS 接口设置中选择模式")

    # 克隆类模式必须有参考音频（行级显式 / 行级切割产物 / 全局），否则 TTS 引擎会直接 400，提前拦截
    if mode in ("clone", "controllable_clone"):
        global_has_ref = bool(ref_audio_global.strip())
        for seg in targets:
            if global_has_ref or _segment_ref_audio(seg, task_dir):
                break
        else:
            raise HTTPException(
                400,
                "克隆模式需要参考音频：请先在顶部『全局参考音频』填写，或在该行『参考音频』列选择后再重生",
            )

    step = S09TTS()
    results = []
    for seg in targets:
        idx = seg.get("index", 0)
        audio_rel = str(seg.get("audio_file") or "").strip()
        if not audio_rel:
            results.append({"index": idx, "success": False, "error": "段落缺少 audio_file"})
            continue
        audio_abs = _abs_in(task_dir, audio_rel)

        # ① 应用前端编辑的朗读文本/指令（用最新文本合成，并随任务单落盘）
        item = item_by_index.get(int(idx))
        if item is not None:
            if item.read_text is not None:
                seg["read_text"] = item.read_text
            if item.read_tone_desc is not None:
                seg["read_tone_desc"] = item.read_tone_desc

        # ② 清除该句变速缓存（删除 _adjusted.wav 与相关字段），交由下游重新计算
        cleared = _clear_speed_cache(seg, task_dir)

        # 参考音频优先级：单句显式指定 → 单句已切割产物(cache/refe/<idx>.wav) → 全局参考音频
        seg_ref = _segment_ref_audio(seg, task_dir) or ref_audio_global
        tts_config = {
            "mode": mode,
            "engine": engine,
            "clone_source": "fixed",
            "cc_colloquial_desc": cc_instruction,
            "ref_audio_path": seg_ref,
            "ref_audio_roles": [],
            "voice_roles": [voice] if voice else [],
            "voice_design_roles": [voice_design] if voice_design else [],
        }

        try:
            speed = speed_by_index.get(int(idx), req.speed)
        except (TypeError, ValueError):
            speed = req.speed
        try:
            if os.path.exists(audio_abs):
                os.remove(audio_abs)
            os.makedirs(os.path.dirname(audio_abs), exist_ok=True)
            ok = step._try_real_tts(seg, tts_config, audio_abs, str(task_dir), None, speed=speed)
        except Exception as exc:  # noqa: BLE001
            ok = False
            results.append({"index": idx, "success": False, "error": str(exc)})
            continue

        if not ok:
            results.append({"index": idx, "success": False, "error": "TTS 合成失败"})
            continue

        # ③ 真实时长写回（与 s09_tts 一致；不写 speed_ratio，避免下游变速重复应用）
        try:
            real_dur = get_audio_duration(audio_abs)
            if real_dur and real_dur > 0:
                seg["real_duration"] = round(float(real_dur), 4)
        except Exception:  # noqa: BLE001
            pass
        results.append({
            "index": idx,
            "success": True,
            "real_duration": seg.get("real_duration", 0),
            "cleared_cache": cleared,
        })

    _save(dub_path, data)
    return {
        "success": True,
        "results": results,
        "segments": [_view(s, task_dir) for s in segments],
    }

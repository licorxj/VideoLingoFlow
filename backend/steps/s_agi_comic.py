"""AI 漫剧(AGI 创作项目)全流程节点步骤。

分组：``aigc``（AIGC流程链）。覆盖一条完整生产链路：

    人物资产 → 场景资产 → 章节剧本 → 分镜剧本
            → 分镜首尾帧 → 分镜视频 → 分镜配音 → 分镜导出 → 章节导出

数据层统一走 ``backend.creation``（包别名 ``agi``）；底层生成能力复用现有
LLM / 生图(imagegen) / 生视频(videogen) / TTS 引擎，出片合成走 ffmpeg。

节点之间通过 ``creation_id`` / ``chapter_id`` / ``shot_id`` 串联，全部为字符串端口，
可直接连线上游节点的同名输出端口。
"""

import os
import json
import random
import shutil
import subprocess
import uuid
import re

from backend.steps.base_step import BaseStep


# --------------------------------------------------------------------------- #
# 通用工具
# --------------------------------------------------------------------------- #
def _cfg(step) -> dict:
    return getattr(step, "_node_config", {}) or {}

def _inputs(step) -> dict:
    return getattr(step, "_step_inputs", {}) or {}

def _node_id(step) -> str:
    return getattr(step, "_node_id", "unknown")


def _read_text(value, task_dir: str = "") -> str:
    """端口值可能是文本，也可能是文本文件路径，统一读成字符串。"""
    if not value or not isinstance(value, str):
        return ""
    v = value.strip()
    if os.path.isfile(v):
        with open(v, "r", encoding="utf-8") as f:
            return f.read().strip()
    if task_dir:
        rel = os.path.join(task_dir, v)
        if os.path.isfile(rel):
            with open(rel, "r", encoding="utf-8") as f:
                return f.read().strip()
    return v


def _resolve_file(value, task_dir: str = ""):
    """把端口/路径值解析为绝对路径；找不到返回 None。"""
    if not value or not isinstance(value, str):
        return None
    v = value.strip()
    cands = [v]
    if task_dir:
        cands.append(os.path.join(task_dir, v))
        cands.append(os.path.join(task_dir, "output", os.path.basename(v)))
    for c in cands:
        if os.path.isfile(c):
            return os.path.abspath(c)
    return None


def _cache_path(task_dir: str, node_id: str, prefix: str) -> str:
    cache = os.path.join(task_dir, "cache")
    os.makedirs(cache, exist_ok=True)
    return os.path.join(cache, f"agi_{prefix}_{node_id}.json")


def _write_cache(task_dir: str, node_id: str, prefix: str, data: dict) -> str:
    p = _cache_path(task_dir, node_id, prefix)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return os.path.relpath(p, task_dir)


def _finalize(out_dir: str, node_id: str, prefix: str, paths: list) -> list:
    """把生成产物重命名为约定命名，返回绝对路径列表。"""
    os.makedirs(out_dir, exist_ok=True)
    final = []
    for i, src in enumerate(paths):
        if not src or not os.path.exists(src):
            continue
        ext = os.path.splitext(src)[1] or ".png"
        dest = os.path.join(out_dir, f"{prefix}_{i + 1}_{node_id}{ext}")
        try:
            if os.path.abspath(src) != os.path.abspath(dest):
                os.replace(src, dest)
        except OSError:
            shutil.copy2(src, dest)
        final.append(dest)
    return final


def _run_ffmpeg(args: list):
    exe = shutil.which("ffmpeg") or "ffmpeg"
    proc = subprocess.run([exe, "-y"] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg 失败: " + proc.stderr.decode("utf-8", "ignore")[-600:])
    return True


def _concat_videos(paths: list, out_path: str):
    if len(paths) == 1:
        shutil.copy(paths[0], out_path)
        return
    inputs = []
    for p in paths:
        inputs += ["-i", p]
    fc = "".join(f"[{i}:v][{i}:a]" for i in range(len(paths))) + \
        f"concat=n={len(paths)}:v=1:a=1[outv][outa]"
    _run_ffmpeg(inputs + ["-filter_complex", fc, "-map", "[outv]", "-map", "[outa]", out_path])


# --------------------------------------------------------------------------- #
# 成片增强辅助：分辨率/比例预设、转场衔接、章节封面
# --------------------------------------------------------------------------- #
_RESOLUTION_HEIGHTS = {"480P": 480, "720P": 720, "1080P": 1080}
_ASPECT_RATIOS = {"16:9": 16.0 / 9.0, "9:16": 9.0 / 16.0, "1:1": 1.0}
_TRANSITIONS = {"none", "fade", "wipeleft", "wiperight", "wipeup", "wipedown",
                "fadeblack", "fadewhite", "smoothleft", "smoothright"}


def _target_dims(resolution: str, aspect_ratio: str):
    """解析分辨率+比例预设，返回 (w, h)；任一为 original 或未知则返回 None（原样）。"""
    res = (resolution or "").strip().upper()
    asp = (aspect_ratio or "").strip()
    if res == "ORIGINAL" or asp == "ORIGINAL":
        return None
    h = _RESOLUTION_HEIGHTS.get(res)
    r = _ASPECT_RATIOS.get(asp)
    if not h or not r:
        return None
    w = int(round(h * r / 2) * 2)
    return (w, h)


def _probe_video_dims(path: str):
    """用 ffprobe 取视频分辨率与时长，失败返回 (None, None, 0.0)。"""
    exe = shutil.which("ffprobe") or "ffprobe"
    try:
        proc = subprocess.run(
            [exe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0",
             path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        parts = proc.stdout.decode("utf-8", "ignore").strip().split(",")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            w, h = int(parts[0]), int(parts[1])
        else:
            return (None, None, 0.0)
    except Exception:  # noqa: BLE001
        return (None, None, 0.0)
    try:
        from backend.utils.audio_processor import get_video_duration
        dur = get_video_duration(path) or 0.0
    except Exception:  # noqa: BLE001
        dur = 0.0
    return (w, h, dur)


def _normalize_clip(src: str, out: str, w: int, h: int, fps: int = 25):
    """缩放+补边到目标分辨率，统一帧率与像素格式（保证转场各片段一致）。"""
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
          f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1")
    _run_ffmpeg(["-i", src, "-vf", vf, "-r", str(fps),
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-y", out])


def _image_to_clip(img: str, out: str, w: int, h: int, fps: int, duration: float):
    """静态封面图 → 带静音占位轨的视频片段（用作章节片头）。"""
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
          f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1")
    _run_ffmpeg(["-loop", "1", "-i", img,
                 "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                 "-vf", vf, "-r", str(fps), "-t", str(duration),
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", "-y", out])


def _concat_with_transitions(paths: list, out_path: str, transition: str = "none",
                             dur: float = 0.4, w: int = None, h: int = None, fps: int = 25):
    """拼接分镜成片；转场要求各片段同分辨率/帧率。

    - transition=none / 单片段：直接拼接或拷贝（兼容既有行为）。
    - 转场开启时自动把各片段归一化到 (w,h,fps)，再用 xfade/acrossfade 链式衔接。
    - 若未显式指定 (w,h)，按首片段分辨率归一化。
    """
    if len(paths) == 1:
        shutil.copy(paths[0], out_path)
        return
    transition = (transition or "none").strip().lower()
    if transition in ("none", ""):
        _concat_videos(paths, out_path)
        return

    # 归一化（转场前提）
    if w and h:
        targets = [(w, h)] * len(paths)
    else:
        fw, fh, _ = _probe_video_dims(paths[0])
        targets = [(fw or 1280, fh or 720)] * len(paths)
    norm = []
    base = os.path.dirname(out_path)
    for i, p in enumerate(paths):
        np = os.path.join(base, f"_norm_{i}_{os.path.basename(out_path)}")
        _normalize_clip(p, np, targets[i][0], targets[i][1], fps)
        norm.append(np)

    n = len(norm)
    durs = [_probe_video_dims(p)[2] for p in norm]
    td = max(0.05, float(dur))
    td = min(td, min(durs) / 2) if durs else td

    # 视频：xfade 链式（offset_i = 累计 - (i+1)*td 的递推）
    v_inputs = []
    for p in norm:
        v_inputs += ["-i", p]
    a_inputs = list(v_inputs)
    fc_v = ""
    off = durs[0] - td
    fc_v += f"[0:v][1:v]xfade=transition={transition}:duration={td:.3f}:offset={off:.3f}[v1]"
    for i in range(2, n):
        off = off + durs[i - 1] - td
        fc_v += f";[v{i-1}][{i}:v]xfade=transition={transition}:duration={td:.3f}:offset={off:.3f}[v{i}]"
    last_v = f"v{n-1}"

    fc_a = "[0:a][1:a]acrossfade=d={:.3f}:c1=tri:c2=tri[a1]".format(td)
    for i in range(2, n):
        fc_a += f";[a{i-1}][{i}:a]acrossfade=d={td:.3f}:c1=tri:c2=tri[a{i}]"
    last_a = f"a{n-1}"

    fc = fc_v + ";" + fc_a
    _run_ffmpeg(v_inputs + ["-filter_complex", fc, "-map", f"[{last_v}]",
                            "-map", f"[{last_a}]", "-y", out_path])


def _build_chapter_cover(chapter: dict, cfg: dict, out_dir: str, nid: str):
    """按章节标题/简介生成封面图（返回绝对路径）；生图失败返回 None。"""
    title = chapter.get("title") or "未命名章节"
    summary = (chapter.get("summary") or "").strip()
    prompt = (cfg.get("cover_prompt") or "").strip()
    if not prompt:
        prompt = (f"电影剧集章节封面海报，章节《{title}》。{summary}。"
                  f"主体角色与场景象征性呈现，电影级光影构图，留白用于标题排版。")
    asp = cfg.get("aspect_ratio")
    if asp in (None, "", "original"):
        asp = "16:9"
    try:
        imgs = _gen_images(prompt, out_dir, cfg, num=1, aspect=asp)
    except Exception:  # noqa: BLE001
        return None
    return imgs[0] if imgs else None


# --------------------------------------------------------------------------- #
# 按章节锁定生成配置（换模型不重跑全项目）
# --------------------------------------------------------------------------- #
# 锁定配置只记录「生成相关」参数，排除路由键与 force，避免续跑时覆盖 shot/chapter 路由。
_LOCK_EXCLUDE = {"shot_id", "chapter_id", "force", "text"}


def _lockable_cfg(cfg: dict) -> dict:
    return {k: v for k, v in (cfg or {}).items() if k not in _LOCK_EXCLUDE}


def _read_locked_cfg(chapter_id: str, step_id: str) -> dict:
    """读取某章节下某节点锁定的生成配置；无则返回 {}。"""
    if not chapter_id:
        return {}
    try:
        from backend import creation as agi
        ch = agi.get_chapter(chapter_id, with_shots=False)
    except Exception:  # noqa: BLE001
        return {}
    gc = ch.get("gen_config") or {}
    if isinstance(gc, str):
        try:
            gc = json.loads(gc)
        except Exception:  # noqa: BLE001
            gc = {}
    if not isinstance(gc, dict):
        gc = {}
    return gc.get(step_id) or {}


def _write_locked_cfg(chapter_id: str, step_id: str, cfg: dict) -> None:
    """把某节点的生效配置写回章节锁定。"""
    if not chapter_id:
        return
    try:
        from backend import creation as agi
        ch = agi.get_chapter(chapter_id, with_shots=False)
        gc = ch.get("gen_config") or {}
        if isinstance(gc, str):
            try:
                gc = json.loads(gc)
            except Exception:  # noqa: BLE001
                gc = {}
        if not isinstance(gc, dict):
            gc = {}
        gc[step_id] = _lockable_cfg(cfg)
        agi.update_chapter(chapter_id, gen_config=json.dumps(gc, ensure_ascii=False))
    except Exception:  # noqa: BLE001
        pass


def _resolve_effective_cfg(cfg: dict, chapter_id: str, step_id: str):
    """返回续跑时实际采用的配置。

    - 章节已锁定且非 force：合并锁定配置（锁定参数优先），续跑沿用原模型/接口。
    - 否则：使用节点当前 cfg（首跑或强制重跑），后续会写回新锁定。
    返回 (effective_cfg, use_lock)。
    """
    force = bool((cfg or {}).get("force", False))
    lock = _read_locked_cfg(chapter_id, step_id) if chapter_id else {}
    use_lock = bool(lock) and not force
    if use_lock:
        return {**cfg, **lock}, True
    return cfg, False


def _concat_audios(paths: list, out_path: str):
    if len(paths) == 1:
        shutil.copy(paths[0], out_path)
        return
    inputs = []
    for p in paths:
        inputs += ["-i", p]
    fc = "".join(f"[{i}:a]" for i in range(len(paths))) + \
        f"concat=n={len(paths)}:v=0:a=1[outa]"
    _run_ffmpeg(inputs + ["-filter_complex", fc, "-map", "[outa]", out_path])


# --------------------------------------------------------------------------- #
# 底层能力封装
# --------------------------------------------------------------------------- #
# 提示词模板库（MD，人工可维护）：backend/config/drama_prompts/
_PROMPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "drama_prompts")

# 节点 → 模板文件；未配置的节点不使用模板
_STEP_PROMPT_FILES = {
    "agi_project": "project_outline.md",
    "agi_deepen": "deepen_bible.md",
    "agi_character": "character_extract.md",
    "agi_scene": "scene_extract.md",
    "agi_chapter": "chapter_plan.md",
    "agi_shot": "storyboard_break.md",
}


def _load_prompt(filename: str) -> str:
    """读取提示词模板正文（自动剥离 YAML frontmatter）；缺失或损坏时返回空串。"""
    if not filename:
        return ""
    try:
        with open(os.path.join(_PROMPT_DIR, filename), encoding="utf-8") as f:
            text = f.read().strip()
    except Exception:  # noqa: BLE001
        return ""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[2].strip()
    return text


def _system_prompt(step_name: str, system: str = None) -> str:
    """模板正文 + 节点内置约束：内置约束在后，保证 JSON schema 不被模板覆盖。"""
    tpl = _load_prompt(_STEP_PROMPT_FILES.get(step_name, ""))
    if tpl and system:
        return tpl + "\n\n" + system
    return tpl or system or None


def _llm(step_name: str, prompt: str, system: str = None, json_mode: bool = True,
         model: str = ""):
    from backend.llm.llm_client import get_llm_client
    try:
        return get_llm_client().chat(step_name, prompt,
                                     system_prompt=_system_prompt(step_name, system),
                                     response_json=json_mode, model_override=model or "")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"LLM 调用失败：{e}") from e


def _pick_interface(manager_getter, cfg_key: str, cfg: dict) -> str:
    iface = (cfg.get(cfg_key) or "").strip()
    if iface:
        return iface
    try:
        enabled = manager_getter().get_enabled()
    except Exception:  # noqa: BLE001
        enabled = []
    if not enabled:
        raise RuntimeError(f"未配置可用接口（{cfg_key}），请先在「设置 → 其他能力接口」中添加并启用")
    return enabled[0]["id"]


def _gen_images(prompt: str, out_dir: str, cfg: dict, num: int = 1, aspect: str = "1:1",
                ref_images=None, seed=None) -> list:
    from backend.imagegen.imagegen_factory import get_imagegen_engine
    from backend.imagegen.imagegen_interface_manager import get_imagegen_interface_manager
    iface = _pick_interface(get_imagegen_interface_manager, "image_interface", cfg)
    engine = get_imagegen_engine(iface)
    paths = engine.generate(prompt=prompt, output_dir=out_dir, mode="txt2img",
                            aspect_ratio=aspect, num_images=num,
                            ref_images=list(ref_images) if ref_images else None,
                            seed=seed)
    if not paths:
        raise RuntimeError("生图未返回任何结果")
    return paths


def _gen_video(prompt: str, out_dir: str, cfg: dict, ref_images=None,
               duration: int = 5, aspect: str = "16:9") -> list:
    from backend.videogen.videogen_factory import get_videogen_engine
    from backend.videogen.videogen_interface_manager import get_videogen_interface_manager
    iface = _pick_interface(get_videogen_interface_manager, "video_interface", cfg)
    engine = get_videogen_engine(iface)
    paths = engine.generate(prompt=prompt, output_dir=out_dir,
                            model=(cfg.get("video_model") or "") or "",
                            mode="img2video", resolution=(cfg.get("resolution") or "720P"),
                            duration=duration, num_videos=1, ref_images=ref_images or None)
    if not paths:
        raise RuntimeError("生视频未返回任何结果")
    return paths


def _tts(text: str, out_path: str, cfg: dict, ref_audio: str = None) -> bool:
    from backend.tts.tts_factory import get_tts_engine
    from backend.tts.tts_interface_manager import get_tts_interface_manager
    iface = _pick_interface(get_tts_interface_manager, "tts_interface", cfg)
    engine = get_tts_engine(iface)
    kwargs = {}
    mode = (cfg.get("tts_mode") or "preset_voice")
    if mode == "controllable_clone" and ref_audio:
        kwargs["mode"] = "controllable_clone"
        kwargs["controllable_clone"] = cfg.get("tts_voice_design") or "自然清晰的配音"
        kwargs["ref_audio"] = ref_audio
    elif mode == "voice_design":
        kwargs["mode"] = "voice_design"
        kwargs["voice_design"] = cfg.get("tts_voice_design") or ""
    else:
        if cfg.get("tts_voice"):
            kwargs["voice"] = cfg.get("tts_voice")
    ok = engine.synthesize(text, str(out_path), **kwargs)
    if not ok or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError(f"TTS 合成失败：{text[:30]}…")
    return True


def _extract_list(resp):
    """从 LLM 的 JSON 响应里尽量提取出一个 list。"""
    if isinstance(resp, list):
        return resp
    if isinstance(resp, dict):
        for v in resp.values():
            if isinstance(v, list) and v and isinstance(v[0], (dict, str)):
                return v
        return [resp]
    if isinstance(resp, str):
        s = resp.strip()
        if s.startswith("```"):
            s = s.strip("`")
            if s.lower().startswith("json"):
                s = s[4:]
        try:
            return _extract_list(json.loads(s))
        except Exception:  # noqa: BLE001
            return []
    return []


_UNSAFE_FS = str.maketrans({ch: "_" for ch in '\\/:*?"<>|\r\n\t '})
DEFAULT_VIEW_LABELS = ("正面全身", "侧面半身", "背面全身")


def _safe_name(name: str) -> str:
    """把角色名转成可安全用作文件夹名的字符串。"""
    v = (name or "char").strip().translate(_UNSAFE_FS)
    return v or "char"


def _resolve_creation_of(shot_id=None, chapter_id=None):
    """根据 shot/chapter 反查 creation_id 与 chapter_id。"""
    from backend import creation as agi
    cid = None
    chid = chapter_id
    if shot_id:
        shot = agi.get_shot(shot_id)
        chid = shot.get("chapter_id")
    if chid and not cid:
        ch = agi.get_chapter(chid)
        cid = ch.get("creation_id")
    return cid, chid


def _resolve_shot_targets(shot_id: str, chapter_id: str) -> list:
    """单分镜或整章批处理：返回待处理的 shot_id 列表（按 order_no）。"""
    from backend import creation as agi
    if shot_id:
        return [shot_id]
    if chapter_id:
        chapter = agi.get_chapter(chapter_id, with_shots=True)
        return [s["id"] for s in (chapter.get("shots") or [])]
    return []


def _asset_abs(agi, p):
    """把资产路径（运行期绝对路径或 data/ 相对路径）还原为存在的绝对路径。"""
    try:
        ap = str(agi.resolve_storage_path(p))
        return ap if os.path.isfile(ap) else None
    except Exception:  # noqa: BLE001
        return None


def _collect_ref_images(agi, shot: dict, creation: dict, scene_assets: list,
                        max_refs: int = 4, use_char: bool = True, use_scene: bool = True) -> list:
    """为分镜生图收集参考图：先按出场人物取角色多视角图，再补场景概念图。"""
    refs, seen = [], set()
    if use_char:
        chars_by_name = {c.get("name"): c for c in (creation.get("characters") or [])}
        for c in (shot.get("characters") or []):
            name = c if isinstance(c, str) else (c.get("name") or "")
            lib_id = (chars_by_name.get(name) or {}).get("character_lib_id")
            if not lib_id:
                continue
            try:
                vdir = agi.get_character(lib_id).get("images_dir")
                if not vdir:
                    continue
                vabs = agi.resolve_public_path(vdir)
                if not os.path.isdir(vabs):
                    continue
                for fn in sorted(os.listdir(vabs)):
                    if fn.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                        p = os.path.join(str(vabs), fn)
                        if p not in seen:
                            seen.add(p)
                            refs.append(p)
                        break  # 每个角色取第一张视角图
            except Exception:  # noqa: BLE001
                continue
            if len(refs) >= max_refs:
                return refs[:max_refs]
    if use_scene:
        for a in scene_assets:
            for p in (a.get("paths") or []):
                abs_p = _asset_abs(agi, p)
                if abs_p and abs_p not in seen:
                    seen.add(abs_p)
                    refs.append(abs_p)
                    break
            if len(refs) >= max_refs:
                break
    return refs[:max_refs]


def _srt_time(sec: float) -> str:
    ms = int(max(0.0, float(sec)) * 1000)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _build_srt(lines: list) -> str:
    """lines: [(start_sec, end_sec, text)] → SRT 文本。"""
    blocks = []
    for i, (a, b, txt) in enumerate(lines, 1):
        blocks.append(f"{i}\n{_srt_time(a)} --> {_srt_time(b)}\n{txt}\n")
    return "\n".join(blocks)


def _mix_tracks(paths: list, out_path: str):
    """多条音轨(如 sfx+bgm)预混为一条，供 mix_audio 的 bgm 通道使用。"""
    if len(paths) == 1:
        shutil.copy(paths[0], out_path)
        return
    inputs = []
    for p in paths:
        inputs += ["-i", p]
    fc = ("".join(f"[{i}:a]" for i in range(len(paths))) +
          f"amix=inputs={len(paths)}:duration=longest:normalize=0[outa]")
    _run_ffmpeg(inputs + ["-filter_complex", fc, "-map", "[outa]", out_path])


def _burn_subtitle(video: str, srt_path: str, out_path: str) -> bool:
    """把 SRT 硬字幕烧录进视频；失败返回 False（由调用方回退为不烧录）。"""
    try:
        esc = srt_path.replace("\\", "/").replace(":", "\\:")
        _run_ffmpeg(["-i", video, "-vf", f"subtitles='{esc}'", "-c:a", "copy", out_path])
        return os.path.exists(out_path) and os.path.getsize(out_path) > 0
    except Exception:  # noqa: BLE001
        return False


def _style_hint(agi, creation_id: str, cfg: dict) -> str:
    """画风来源：节点配置优先，否则取项目骨架中的【画风锁定】段（剧本深化产出）。"""
    v = (cfg.get("art_style_prompt") or "").strip()
    if v:
        return v
    try:
        st = agi.get_creation(creation_id).get("script_text") or ""
        m = re.search(r"【画风锁定】\s*([\s\S]+?)(?=\n\n【|$)", st)
        return m.group(1).strip() if m else ""
    except Exception:  # noqa: BLE001
        return ""


def _extract_look(personality: str) -> str:
    """从 personality 字段解析【造型】锚点（剧本深化的人物设计提炼写入）。"""
    m = re.search(r"【造型】([^；]+)", personality or "")
    return m.group(1).strip() if m else ""


def _character_looks(creation: dict) -> dict:
    return {c.get("name"): _extract_look(c.get("personality") or "")
            for c in (creation.get("characters") or [])}


def _validate_bible(data, require_screenplay: bool = True) -> list:
    """剧本深化设定书的严格格式校验，返回错误列表（空=通过）。"""
    if not isinstance(data, dict):
        return ["响应不是 JSON 对象"]
    errs = []
    if not str(data.get("synopsis") or "").strip():
        errs.append("缺少 synopsis(剧本简介)")
    chs = data.get("chapters")
    if not isinstance(chs, list) or not chs:
        errs.append("缺少 chapters 非空数组")
    else:
        for i, c in enumerate(chs):
            if not isinstance(c, dict) or not str(c.get("title") or "").strip()                     or not str(c.get("content_plan") or "").strip():
                errs.append(f"chapters[{i}] 缺 title/content_plan")
    if require_screenplay:
        for i, c in enumerate(data.get("chapters") or []):
            body = str((c or {}).get("content_plan") or "")
            if not re.search(r"##\s*S\d", body):
                errs.append(f"chapters[{i}] content_plan 缺少格式化剧本场景头 `## S编号 | 内景/外景 · 地点 | 时间段`")
    chars = data.get("characters")
    if not isinstance(chars, list) or not chars:
        errs.append("缺少 characters 非空数组")
    else:
        names = set()
        for i, c in enumerate(chars):
            nm = str((c or {}).get("name") or "").strip() if isinstance(c, dict) else ""
            if not nm:
                errs.append(f"characters[{i}] 缺 name")
            elif nm in names:
                errs.append(f"characters[{i}] 姓名重复: {nm}")
            else:
                names.add(nm)
    return errs


def _project_screenplay(proj: dict, limit: int = 8000) -> str:
    """汇总项目格式化剧本（骨架 + 各章正文），作为资产提取的输入源。"""
    parts = []
    if proj.get("script_text"):
        parts.append(str(proj["script_text"]))
    for ch in (proj.get("chapters") or []):
        body = (ch.get("original_text") or ch.get("summary") or "").strip()
        if body:
            parts.append(f"【{ch.get('title') or '章节'}】\n{body}")
    return "\n\n".join(parts)[:limit]


def _has_screenplay(text: str) -> bool:
    """是否已是格式化剧本（含 `## S编号` 场景头）。"""
    return bool(re.search(r"##\s*S\d", text or ""))


def _normalize_name(name: str) -> str:
    """归一化姓名：去括号定位与空白，用于去重匹配（如「林小雨（主角）」→「林小雨」）。"""
    v = re.sub(r"[（(].*?[)）]", "", str(name or "")).strip()
    return re.sub(r"\s+", "", v)


def _scene_keys(location: str = "", time: str = "", name: str = "") -> list:
    """场景去重候选键（按优先级）：地点+时间段 → 仅地点 → 仅时间段/场景名。

    同时支持结构化字段（location/time）与 `地点 · 时间` 形式的场景名，
    兼容历史只按地点登记的场景。
    """
    loc = _normalize_name(location)
    t = _normalize_name(time)
    if not loc:
        parts = [x for x in re.split(r"[·|｜\-\u2014]", str(name or ""))
                 if _normalize_name(x)]
        loc = _normalize_name(parts[0]) if parts else _normalize_name(name)
        if not t and len(parts) > 1:
            t = _normalize_name(parts[1])
    keys = []
    if loc and t:
        keys.append(f"{loc}|{t}")
    if loc:
        keys.append(f"{loc}|")
    return keys


def _resolve_asset_mode(cfg: dict, screenplay: str) -> str:
    """资产来源模式：auto（有格式化剧本则提取）/ extract / generate。"""
    mode = (cfg.get("mode") or "auto").strip().lower()
    if mode == "auto":
        return "extract" if _has_screenplay(screenplay) else "generate"
    return mode if mode in ("extract", "generate") else "generate"


# --------------------------------------------------------------------------- #
# 节点实现
# --------------------------------------------------------------------------- #
class S_AGI_Project(BaseStep):
    """剧本创作·项目立项（起始节点）：创建创作项目并用 LLM 打好故事骨架。

    整条 AI 漫剧链路以本节点为唯一入口：产出 creation_id 作为贯穿参数，
    下游所有节点通过它读写项目骨架（人物/章节/分镜/资产）。
    """
    step_id = "agi_project"
    step_name = "项目立项·剧本创作"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        return os.path.isfile(_cache_path(task_dir, _node_id(self), "project"))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback=None, cancel_callback=None) -> dict:
        from backend import creation as agi
        cfg = _cfg(self)
        inp = _inputs(self)
        nid = _node_id(self)

        brief = _read_text(inp.get("text"), task_dir) or (cfg.get("outline_prompt") or "")
        name = (cfg.get("project_name") or "AI漫剧项目").strip() or "AI漫剧项目"
        creation = agi.create_creation(
            name,
            description=brief[:500] if brief else "",
            genre_tags=cfg.get("genre_tags") or "",
            art_style_tags=cfg.get("art_style_tags") or "",
            audience_tags=cfg.get("audience_tags") or "",
        )
        cid = creation["id"]
        if callback:
            callback(20, f"已创建创作项目《{name}》")

        system = "你是资深动漫总编剧，擅长搭建世界观与整体故事骨架。只输出 JSON，不要多余说明。"
        prompt = (f"为 AI 漫剧项目《{name}》搭建故事骨架。\n【创意/要求】\n{brief}\n\n"
                  f"返回 JSON：{{worldview:世界观设定, outline:整体故事大纲, "
                  f"script_text:可分集展开的总剧本文本}}。")
        resp = _llm(self.step_id, prompt, system=system, json_mode=True,
                            model=(cfg.get("llm_model") or ""))
        worldview, outline, script = "", "", ""
        if isinstance(resp, dict):
            worldview = resp.get("worldview") or ""
            outline = resp.get("outline") or ""
            script = resp.get("script_text") or resp.get("script") or ""
        script_text = "\n\n".join(
            f"【{head}】\n{body}" for head, body in
            (("世界观", worldview), ("大纲", outline), ("总剧本", script)) if body
        ) or brief
        agi.update_creation(cid, description=(outline or worldview or brief)[:500],
                            script_text=script_text)
        if callback:
            callback(90, "故事骨架（世界观/大纲/总剧本）已写入")

        project = dict(creation)
        project.update({"worldview": worldview, "outline": outline, "script_text": script_text})
        cache = _write_cache(task_dir, nid, "project", {"creation_id": cid})
        return {
            "artifacts": [cache],
            "outputs": {
                "creation_id": cid,
                "project": json.dumps(project, ensure_ascii=False),
            },
        }


class S_AGI_Deepen(BaseStep):
    """剧本深化：把项目骨架深化为结构化设定书（严格 JSON 校验，失败自动纠错重试一次）。

    入库：剧本简介(description)、章节内容规划(add_chapter)、人物设计提炼
    (同名提炼/新增写入)、画风元素锁定(script_text 追加【画风锁定】段，
    下游生图节点自动取用，分镜提示词并注入人物造型锚点)。
    """
    step_id = "agi_deepen"
    step_name = "剧本深化"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        return os.path.isfile(_cache_path(task_dir, _node_id(self), "deepen"))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback=None, cancel_callback=None) -> dict:
        from backend import creation as agi
        cfg = _cfg(self)
        inp = _inputs(self)
        nid = _node_id(self)

        creation_id = (inp.get("creation_id") or cfg.get("creation_id") or "").strip()
        if not creation_id:
            raise RuntimeError("缺少 creation_id：请连接「项目立项·剧本创作」节点")
        proj = agi.get_creation(creation_id, with_detail=True)
        existing = {c.get("name"): c.get("id") for c in proj.get("characters", [])}
        skeleton = proj.get("script_text") or ""
        n_ch = max(1, int(cfg.get("num_chapters") or 3))
        n_char = max(1, int(cfg.get("num_characters") or 3))
        art_in = (cfg.get("art_style_input") or "")
        extra = (cfg.get("extra_requirements") or "")
        model = cfg.get("llm_model") or ""
        replace_chapters = bool(cfg.get("replace_chapters"))

        schema = (
            '严格输出一个 JSON 对象（禁止多余文本），结构：\n'
            '{\n'
            '  "synopsis": "剧本简介，80-150字",\n'
            '  "art_style": {"style_bible": "画风锁定总述(20-60字，将用于全部生图)", '
            '"palette": "主色调与配色", "lighting": "光影风格", "texture": "线条与质感"},\n'
            '  "chapters": [{"title": "章节标题", "content_plan": "本章内容规划150-300字'
            '(起承转合/冲突/钩子)", "summary": "一句话简述"}],\n'
            '  "characters": [{"name": "姓名", "gender": "性别", "age": "年龄", '
            '"personality": "性格", "occupation": "职业", "aliases": ["别名"], '
            '"relationship_note": "人物关系", "voice_design": "音色设计", '
            '"visual_anchor": "外貌造型锚点(发型/服装/标志特征,30字内)"}]\n'
            '}'
        )
        system = "你是资深动漫总编剧兼美术监督。只输出符合 schema 的 JSON，禁止输出任何解释性文本。"
        prompt = (
            f"深化以下 AI 漫剧项目骨架，完成：剧本简介、{n_ch} 个章节的内容规划、"
            f"{n_char} 个人物设计提炼、画风元素锁定。\n"
            f"【项目骨架】\n{skeleton or '（空，依据名称与标签创作）'}\n"
            f"【已有人物】{list(existing.keys()) or '无'}（同名者做设计提炼，可补充新人物）\n"
            f"【画风人工指定】{art_in or '无，由你锁定'}\n"
            f"【额外要求】{extra or '无'}\n\n{schema}"
        )

        data, errs = {}, []
        for attempt in range(2):
            if attempt:
                prompt = (prompt + "\n\n【上一次输出未通过校验，请修复以下问题后"
                          "重新输出完整 JSON】\n- " + "\n- ".join(errs))
            resp = _llm(self.step_id, prompt, system=system, json_mode=True, model=model)
            data = resp if isinstance(resp, dict) else {}
            errs = _validate_bible(data,
                                   require_screenplay=bool(cfg.get("require_screenplay", True)))
            if not errs:
                break
        if errs:
            raise RuntimeError("剧本深化输出未通过格式校验：" + "；".join(errs))

        # 入库 1：剧本简介
        synopsis = str(data.get("synopsis") or "").strip()
        agi.update_creation(creation_id, description=synopsis)

        # 入库 2：画风元素锁定 → script_text 幂等追加【画风锁定】段
        art = data.get("art_style") or {}
        style_text = "；".join(str(art.get(k) or "").strip()
                               for k in ("style_bible", "palette", "lighting", "texture")
                               if str(art.get(k) or "").strip())
        if style_text:
            base = re.split(r"【画风锁定】", skeleton)[0].strip()
            agi.update_creation(creation_id,
                                script_text=(base + "\n\n【画风锁定】\n" + style_text).strip())

        # 入库 3：章节内容规划
        if replace_chapters:
            for ch in agi.list_chapters(creation_id):
                agi.remove_chapter(ch["id"])  # 级联删除其下分镜
        chapters = []
        for c in (data.get("chapters") or []):
            chapters.append(agi.add_chapter(
                creation_id,
                title=str(c.get("title") or "").strip(),
                original_text=str(c.get("content_plan") or "").strip(),
                summary=str(c.get("summary") or "").strip()))
            if callback:
                callback(60, f"章节规划入库：{chapters[-1].get('title')}")

        # 入库 4：人物设计提炼（同名更新，新增写入；造型锚点并入 personality）
        characters = []
        for c in (data.get("characters") or []):
            name = str(c.get("name") or "").strip()
            look = str(c.get("visual_anchor") or "").strip()
            personality = (f"【造型】{look}；" if look else "") + str(c.get("personality") or "").strip()
            fields = dict(
                gender=str(c.get("gender") or ""), age=str(c.get("age") or ""),
                personality=personality, occupation=str(c.get("occupation") or ""),
                aliases=c.get("aliases") or [],
                relationship_note=str(c.get("relationship_note") or ""),
                voice_design=str(c.get("voice_design") or ""),
                status="ready")
            if name in existing:
                member = agi.update_creation_character(existing[name], **fields)
                member["refined"] = True
            else:
                member = agi.add_creation_character(creation_id, name, **fields)
                member["refined"] = False
            characters.append(member)
            if callback:
                callback(80, f"人物{'提炼' if member.get('refined') else '新增'}：{name}")

        if callback:
            callback(95, f"剧本深化完成：简介/画风锁定/{len(chapters)}章/{len(characters)}人物 已入库")
        bible = {"synopsis": synopsis, "art_style": art,
                 "chapters": data.get("chapters") or [],
                 "characters": data.get("characters") or []}
        cache = _write_cache(task_dir, nid, "deepen", {"creation_id": creation_id, "bible": bible})
        return {
            "artifacts": [cache],
            "outputs": {
                "creation_id": creation_id,
                "bible": json.dumps(bible, ensure_ascii=False),
                "synopsis": synopsis,
                "style_bible": style_text,
            },
        }


class S_AGI_Character(BaseStep):
    """剧本创作-人物资产：为已有创作项目生成人物设定（起点唯一化：不再自建项目）。"""
    step_id = "agi_character"
    step_name = "人物资产创作"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        return os.path.isfile(_cache_path(task_dir, _node_id(self), "character"))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback=None, cancel_callback=None) -> dict:
        from backend import creation as agi
        cfg = _cfg(self)
        inp = _inputs(self)
        nid = _node_id(self)
        out_dir = os.path.join(task_dir, "output")
        os.makedirs(out_dir, exist_ok=True)

        brief = _read_text(inp.get("text"), task_dir)
        creation_id = (inp.get("creation_id") or cfg.get("creation_id") or "").strip()
        if not creation_id:
            raise RuntimeError("缺少 creation_id：请连接「项目立项·剧本创作」节点的 creation_id 输出，"
                               "或在下拉中选择已有创作项目")
        proj = agi.get_creation(creation_id, with_detail=True)  # 校验存在并取骨架
        screenplay = _project_screenplay(proj)
        mode = _resolve_asset_mode(cfg, screenplay)
        existing_map = {c.get("name"): c.get("id") for c in (proj.get("characters") or [])}
        existing_norm = {_normalize_name(n): (n, i) for n, i in existing_map.items()}

        style = _style_hint(agi, creation_id, cfg)
        system = ("你是资深动漫编剧兼角色设计师，擅长为 AI 漫剧设计立体、有记忆点的人物。"
                  "只输出 JSON，不要多余说明。")
        fields_hint = ("请返回 JSON 数组，每个元素包含字段："
                       "name(姓名), gender(性别), age(年龄), personality(性格), "
                       "occupation(职业/身份), aliases(别名数组), relationship_note(人物关系网), "
                       "voice_design(音色设计描述), "
                       "visual_anchor(造型锚点30-60字:发型/服装/配色/显著标志)。确保姓名不重复。")
        if mode == "extract":
            prompt = (f"从以下格式化剧本中**提取**人物：只保留真实出场、对剧情有影响的人物，"
                      f"不要创造剧本中未出现的人。\n"
                      f"【格式化剧本】\n{screenplay or '（暂无）'}\n\n"
                      f"【项目已有人物】{list(existing_map.keys()) or '无'}\n"
                      f"对同名人物做**设计提炼**（补足 visual_anchor 造型锚点与 voice_design 音色设计），"
                      f"不要重复创造；剧本中出现但项目尚无的人物可新增。宁少勿多。\n\n"
                      f"{fields_hint}")
        else:
            if (cfg.get("char_count_mode") or "follow") == "manual":
                try:
                    n = max(1, int(cfg.get("num_characters") or 4))
                except (TypeError, ValueError):
                    n = 4
                count_hint = f"设计 {n} 个主要人物（主角与关键配角）"
            else:
                count_hint = "人物数量由你依据剧情需要决定（建议 3-8 个主要人物，覆盖主角与关键配角）"
            prompt = (f"基于以下创意简介，{count_hint}：\n"
                      f"【创意简介】\n{brief}\n\n{fields_hint}")
        if style:
            prompt += f"\n整体画风要求：{style}"

        resp = _llm(self.step_id, prompt, system=system, json_mode=True,
                            model=(cfg.get("llm_model") or ""))
        chars = _extract_list(resp)
        if not chars:
            raise RuntimeError("LLM 未返回有效的人物设定")

        created = []
        portraits = []
        publish = bool(cfg.get("publish_to_library", True))
        views_raw = (cfg.get("view_prompts") or "，".join(DEFAULT_VIEW_LABELS))
        view_labels = [v.strip() for v in views_raw.replace("，", ",").split(",") if v.strip()] \
            or list(DEFAULT_VIEW_LABELS)
        try:
            n_views = max(1, int(cfg.get("num_views") or len(view_labels)))
        except (TypeError, ValueError):
            n_views = len(view_labels)
        if len(view_labels) >= n_views:
            view_labels = view_labels[:n_views]
        else:
            view_labels += [f"视角{k+1}" for k in range(len(view_labels), n_views)]
        tags = [t.strip() for t in (cfg.get("genre_tags") or "").replace("，", ",").split(",") if t.strip()]

        for i, c in enumerate(chars):
            if not isinstance(c, dict):
                continue
            name = (c.get("name") or f"人物{i+1}").strip()
            look = str(c.get("visual_anchor") or "").strip()
            fields = dict(
                gender=c.get("gender") or "", age=c.get("age") or "",
                personality=((f"【造型】{look}；" if look else "")
                             + str(c.get("personality") or "").strip()),
                occupation=c.get("occupation") or "",
                aliases=c.get("aliases") or [],
                relationship_note=c.get("relationship_note") or "",
                voice_design=c.get("voice_design") or "",
                status="ready")
            key = _normalize_name(name)
            if key in existing_norm:
                member = agi.update_creation_character(existing_norm[key][1], **fields)
                member["extracted"] = True
            else:
                member = agi.add_creation_character(creation_id, name, **fields)
                member["extracted"] = False

            # 发布到公共角色库（publish_character_to_library 会回写 character_lib_id）
            lib_role = None
            if publish:
                try:
                    lib_role = agi.publish_character_to_library(member["id"], tags=tags or ["角色"])
                    member["character_lib_id"] = lib_role["id"]
                    if callback:
                        callback(30, f"人物 {name} 已发布到公共角色库")
                except Exception as e:  # noqa: BLE001
                    lib_role = None
                    if callback:
                        callback(30, f"人物 {name} 发布公共角色库失败（跳过）：{e}")

            created.append(member)
            if callback:
                callback(20 + int(60 * (i + 1) / max(1, len(chars))),
                         f"已写入人物：{name}")

            if cfg.get("generate_images"):
                base = (f"{style}；动漫风格角色设定图，{name}，{c.get('gender','')}性，"
                        f"{c.get('age','')}岁，{c.get('personality','')}，清晰五官，高质感。")
                # 确定性种子：显式指定 → 沿用已存 → 随机（重生成一致性）
                try:
                    explicit = int(cfg["seed"]) if cfg.get("seed") not in (None, "") else None
                except (TypeError, ValueError):
                    explicit = None
                if explicit is not None:
                    seed = explicit
                elif member.get("seed_value"):
                    seed = member["seed_value"]
                else:
                    seed = random.randint(0, 2 ** 31 - 1)
                # 重生成时以已有参考图作 conditioning，保持角色形象一致
                cond_refs = []
                if member.get("reference_images"):
                    try:
                        for _rp in json.loads(member["reference_images"]):
                            if _rp and os.path.isfile(_rp):
                                cond_refs.append(_rp)
                    except Exception:  # noqa: BLE001
                        cond_refs = []
                try:
                    if lib_role:
                        # 多视角图 → 公共角色库 views 目录（data/ 相对路径入库）
                        views_abs = str(agi.resolve_public_path(
                            f"data/characters/{_safe_name(name)}_{lib_role['id'][:8]}/views"))
                        os.makedirs(views_abs, exist_ok=True)
                        view_files = []
                        for k, label in enumerate(view_labels):
                            p = f"{base}{label}视角，全身立绘，纯色背景，统一角色形象。"
                            imgs = _gen_images(p, views_abs, cfg, num=1, aspect="3:4",
                                              seed=seed, ref_images=cond_refs or None)
                            view_files.extend(_finalize(views_abs, nid, f"view_{k+1}", imgs))
                        rel_dir = agi.normalize_public_path(views_abs)
                        agi.update_character(lib_role["id"], images_dir=rel_dir)
                        agi.register_asset(
                            creation_id, "character", name=name, ref_id=lib_role["id"],
                            paths_list=[agi.normalize_public_path(v) for v in view_files],
                            description=f"{name} 角色多视角图")
                        member["images_dir"] = rel_dir
                        portraits.extend(view_files)
                        if callback:
                            callback(60, f"人物 {name} 多视角图 {len(view_files)} 张已入库")
                    else:
                        imgs = _gen_images(base + "全身或半身立绘。", out_dir, cfg, num=1,
                                          aspect="1:1", seed=seed, ref_images=cond_refs or None)
                        saved = _finalize(out_dir, nid, f"char_{i+1}", imgs)
                        for abs_p in saved:
                            agi.register_asset(creation_id, "scene_image",
                                               paths_list=[abs_p],
                                               description=f"{name} 角色立绘")
                        portraits.extend(saved)
                    # 回写种子与参考图（供后续重生成保持一致）
                    agi.update_creation_character(
                        member["id"], seed_value=seed,
                        reference_images=json.dumps([os.path.abspath(x) for x in
                                                     (view_files if lib_role else saved)],
                                                    ensure_ascii=False))
                except Exception as e:  # noqa: BLE001
                    if callback:
                        callback(80, f"人物 {name} 立绘生成失败（跳过）：{e}")

        data = {"creation_id": creation_id, "characters": created, "portraits": portraits}
        cache = _write_cache(task_dir, nid, "character", data)
        # artifacts 只收录任务目录内文件；公共角色库的 data/ 文件走 outputs/数据库引用
        task_root = os.path.abspath(task_dir) + os.sep
        local_imgs = [p for p in portraits
                      if os.path.abspath(p).startswith(task_root)]
        return {
            "artifacts": [cache] + [os.path.relpath(p, task_dir) for p in local_imgs],
            "outputs": {
                "creation_id": creation_id,
                "characters": json.dumps(created, ensure_ascii=False),
                "images": json.dumps(portraits, ensure_ascii=False),
            },
        }


class S_AGI_Voice(BaseStep):
    """人物音色生产：为项目人物合成音色样本，登记到 voiceforge 音频素材库并绑定 voice_ref。

    打通配音链路：本节点产出的 vf:assets 引用会绑定到人物 voice_ref，
    供「分镜配音」按人物音色克隆（controllable_clone）使用。
    """
    step_id = "agi_voice"
    step_name = "人物音色生产"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        return os.path.isfile(_cache_path(task_dir, _node_id(self), "voice"))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback=None, cancel_callback=None) -> dict:
        from backend import creation as agi
        from backend.utils.audio_processor import get_audio_duration
        from backend.voiceforge.database import storage_root, initialize_database
        from backend.voiceforge.storage import resolve_storage_key
        initialize_database()  # 幂等；空库环境下自动建表
        cfg = _cfg(self)
        inp = _inputs(self)
        nid = _node_id(self)
        out_dir = os.path.join(task_dir, "output")
        os.makedirs(out_dir, exist_ok=True)

        creation_id = (inp.get("creation_id") or cfg.get("creation_id") or "").strip()
        if not creation_id:
            raise RuntimeError("缺少 creation_id：请连接「人物资产创作」节点的 creation_id 输出")
        proj = agi.get_creation(creation_id, with_detail=True)
        characters = proj.get("characters") or []
        if not characters:
            raise RuntimeError("项目内没有人物，请先运行「人物资产创作」")

        overwrite = bool(cfg.get("overwrite"))
        template = cfg.get("sample_text") or "你好，我是{name}。{voice_design}"

        created = []
        samples = []
        total = max(1, len(characters))
        for i, c in enumerate(characters):
            name = c.get("name") or f"人物{i+1}"
            if c.get("voice_ref") and not overwrite:
                created.append({"name": name, "member_id": c["id"],
                                "voice_ref": c["voice_ref"], "skipped": True})
                continue
            text = template.replace("{name}", name).replace(
                "{voice_design}", c.get("voice_design") or "自然清晰的中文配音")
            tmp = os.path.join(out_dir, f"voice_sample_{i+1}_{nid}.wav")
            # 用人物自己的 voice_design 作为音色设计指令合成样本
            tts_cfg = dict(cfg)
            tts_cfg["tts_mode"] = "voice_design"
            tts_cfg["tts_voice_design"] = c.get("voice_design") or "自然清晰的中文配音"
            if callback:
                callback(10 + int(70 * (i + 1) / total), f"合成音色样本：{name}")
            _tts(text, tmp, tts_cfg)
            try:
                dur = get_audio_duration(tmp) or 0.0
            except Exception:  # noqa: BLE001
                dur = 0.0

            # 登记到 voiceforge 音频素材库（vf:assets 引用，可被 voice_ref/audio_ref_abspath 消费）
            asset_id = uuid.uuid4().hex
            key = f"assets/{asset_id}.wav"
            dest = resolve_storage_key(key)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(tmp, str(dest))
            rec = agi.add_audio_asset(
                f"{name} 音色样本", "voice", storage_key=key,
                file_name=f"{_safe_name(name)}_voice.wav", duration=dur,
                description=c.get("voice_design") or "")
            agi.update_creation_character(c["id"], voice_ref=rec["ref"])
            created.append({"name": name, "member_id": c["id"], "voice_ref": rec["ref"],
                            "sample": str(dest), "duration": dur})
            samples.append(tmp)  # 任务内样本副本；持久副本在 voiceforge，经 vf 引用指向

        cache = _write_cache(task_dir, nid, "voice",
                             {"creation_id": creation_id, "voices": created})
        return {
            "artifacts": [cache] + [os.path.relpath(p, task_dir) for p in samples],
            "outputs": {
                "creation_id": creation_id,
                "voices": json.dumps(created, ensure_ascii=False),
                "audio": samples[-1] if samples else "",
            },
        }


class S_AGI_Scene(BaseStep):
    """场景资产创作：生成场景描述并生成场景概念图，登记为 scene_image 资产。"""
    step_id = "agi_scene"
    step_name = "场景资产创作"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        return os.path.isfile(_cache_path(task_dir, _node_id(self), "scene"))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback=None, cancel_callback=None) -> dict:
        from backend import creation as agi
        cfg = _cfg(self)
        inp = _inputs(self)
        nid = _node_id(self)
        out_dir = os.path.join(task_dir, "output")
        os.makedirs(out_dir, exist_ok=True)

        creation_id = (inp.get("creation_id") or cfg.get("creation_id") or "").strip()
        if not creation_id:
            raise RuntimeError("缺少 creation_id：请连接「人物资产创作」节点的 creation_id 输出")
        agi.get_creation(creation_id)

        brief = _read_text(inp.get("text"), task_dir)
        proj = agi.get_creation(creation_id, with_detail=True)
        screenplay = _project_screenplay(proj)
        mode = _resolve_asset_mode(cfg, screenplay)
        style = _style_hint(agi, creation_id, cfg)
        n = max(1, int(cfg.get("num_scenes") or 6))
        system = "你是 AI 漫剧的场景美术指导，擅长用画面语言描述场景。只输出 JSON 数组。"
        existing_scenes = {}
        for s in agi.list_scenes(creation_id):
            for k in _scene_keys(location=s.get("location", ""), time=s.get("time", ""), name=s.get("name", "")):
                existing_scenes.setdefault(k, s)
        schema_hint = ("返回 JSON 数组，每个元素：{name:场景名(地点·时间), location:地点, time:时间段, "
                       "lighting:时间与光线/光影, prompt:按「地点与年代质感 / 空间与陈设 / 氛围」结构化描述}。")
        if mode == "extract":
            prompt = (f"从以下格式化剧本中**提取**场景：按「地点 + 时间段」去重，"
                      f"同地点不同时段视为不同场景。\n"
                      f"【格式化剧本】\n{screenplay or '（暂无）'}\n\n"
                      f"【项目已有场景】{[a.get('name') for a in existing_scenes.values()] or '无'}\n"
                      f"命中的直接复用、不要重复创建；可补充剧本中出现但尚无的场景。宁少勿多。\n\n"
                      f"{schema_hint}")
        else:
            prompt = (f"基于创意/剧本，设计 {n} 个关键场景。\n【补充】\n{brief}\n{schema_hint}")
        if style:
            prompt += f"\n整体画风：{style}"

        resp = _llm(self.step_id, prompt, system=system, json_mode=True,
                            model=(cfg.get("llm_model") or ""))
        scenes = _extract_list(resp)
        if not scenes:
            raise RuntimeError("LLM 未返回有效的场景描述")

        images = []
        scene_meta = []
        scene_ids = []
        for i, s in enumerate(scenes):
            if not isinstance(s, dict):
                s = {"name": f"场景{i+1}", "description": str(s)}
            location = str(s.get("location") or "").strip()
            time_txt = str(s.get("time") or "").strip()
            name = (s.get("name") or " · ".join([x for x in (location, time_txt) if x])
                    or f"场景{i+1}").strip()
            desc = (s.get("prompt") or s.get("description") or "").strip()
            lighting = (s.get("lighting") or "").strip()
            keys = _scene_keys(location, time_txt, name)
            scene = None
            for k in keys:
                if k in existing_scenes:
                    scene = existing_scenes[k]
                    break
            reused = scene is not None
            if reused:
                agi.update_scene(scene["id"], name=name, location=location, time=time_txt,
                                 lighting=lighting, prompt=desc, status="ready")
                scene_meta.append({**scene, "reused": True})
            else:
                scene = agi.add_creation_scene(creation_id, name=name, location=location,
                                               time=time_txt, lighting=lighting, prompt=desc)
                for k in keys:
                    existing_scenes.setdefault(k, scene)
                scene_meta.append({**scene, "reused": False})
            scene_ids.append(scene["id"])
            if cfg.get("generate_images"):
                p = f"{style}；动漫风格场景概念图，{desc}，氛围感强，电影级构图。"
                try:
                    imgs = _gen_images(p, out_dir, cfg, num=1, aspect="16:9")
                    saved = _finalize(out_dir, nid, f"scene_{i+1}", imgs)
                    for abs_p in saved:
                        # 仅新建场景登记独立资产，避免复用场景时重复堆积
                        if not reused:
                            agi.register_asset(creation_id, "scene_image", name=name,
                                               paths_list=[abs_p], description="场景固定视角图")
                        agi.update_scene(scene["id"], image_url=abs_p)
                    images.extend(saved)
                except Exception as e:  # noqa: BLE001
                    if callback:
                        callback(80, f"场景 {name} 配图生成失败（跳过）：{e}")
            if callback:
                callback(20 + int(70 * (i + 1) / max(1, len(scenes))), f"场景：{name}")

        data = {"creation_id": creation_id, "scene_ids": scene_ids, "scenes": scene_meta, "images": images}
        cache = _write_cache(task_dir, nid, "scene", data)
        return {
            "artifacts": [cache] + [os.path.relpath(p, task_dir) for p in images],
            "outputs": {
                "creation_id": creation_id,
                "scene_ids": json.dumps(scene_ids, ensure_ascii=False),
                "scenes": json.dumps(scene_meta, ensure_ascii=False),
                "images": json.dumps(images, ensure_ascii=False),
            },
        }


class S_AGI_Prop(BaseStep):
    """道具资产创作：从剧本提取/生成关键道具，生成白底单品图，登记为 prop 资产。"""
    step_id = "agi_prop"
    step_name = "道具资产创作"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        return os.path.isfile(_cache_path(task_dir, _node_id(self), "prop"))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback=None, cancel_callback=None) -> dict:
        from backend import creation as agi
        cfg = _cfg(self)
        inp = _inputs(self)
        nid = _node_id(self)
        out_dir = os.path.join(task_dir, "output")
        os.makedirs(out_dir, exist_ok=True)

        creation_id = (inp.get("creation_id") or cfg.get("creation_id") or "").strip()
        if not creation_id:
            raise RuntimeError("缺少 creation_id：请连接「人物资产创作」节点的 creation_id 输出")
        agi.get_creation(creation_id)

        brief = _read_text(inp.get("text"), task_dir)
        proj = agi.get_creation(creation_id, with_detail=True)
        screenplay = _project_screenplay(proj)
        mode = _resolve_asset_mode(cfg, screenplay)
        style = _style_hint(agi, creation_id, cfg)
        n = max(1, int(cfg.get("num_props") or 6))
        system = "你是 AI 漫剧的道具设计师，擅长提炼推动剧情的关键道具。只输出 JSON 数组。"
        existing = {p.get("name") for p in agi.list_props(creation_id)}
        schema_hint = ("返回 JSON 数组，每个元素：{name:道具名, type:道具类别, "
                       "description:道具描述与剧情作用, prompt:生图提示词(白底单品,清晰展示)}。")
        if mode == "extract":
            prompt = (f"从以下格式化剧本中**提取**推动剧情、值得单独生图的关键道具。\n"
                      f"【剧本】\n{screenplay or '（暂无）'}\n"
                      f"【已有道具】{sorted(existing) or '无'}\n"
                      f"命中的直接复用、不要重复创建；可补充剧本中出现但尚无的道具。宁少勿多。\n\n"
                      f"{schema_hint}")
        else:
            prompt = (f"基于创意/剧本设计 {n} 个关键道具。\n【补充】\n{brief}\n{schema_hint}")
        if style:
            prompt += f"\n整体画风：{style}"

        resp = _llm(self.step_id, prompt, system=system, json_mode=True,
                    model=(cfg.get("llm_model") or ""))
        props = _extract_list(resp)
        if not props:
            raise RuntimeError("LLM 未返回有效的道具")

        images = []
        prop_meta = []
        prop_ids = []
        for i, p in enumerate(props):
            if not isinstance(p, dict):
                p = {"name": f"道具{i+1}", "description": str(p)}
            name = str(p.get("name") or f"道具{i+1}").strip()
            if not name:
                continue
            ptype = str(p.get("type") or "").strip()
            desc = str(p.get("description") or "").strip()
            prompt_txt = str(p.get("prompt") or desc).strip()
            if name in existing:
                prop = next((x for x in agi.list_props(creation_id) if x.get("name") == name), None)
                if prop:
                    agi.update_prop(prop["id"], type=ptype, description=desc,
                                    prompt=prompt_txt, status="ready")
                    prop_meta.append({**prop, "reused": True})
                    prop_ids.append(prop["id"])
            else:
                prop = agi.add_creation_prop(creation_id, name, type=ptype,
                                             description=desc, prompt=prompt_txt)
                existing.add(name)
                prop_meta.append({**prop, "reused": False})
                prop_ids.append(prop["id"])
            if cfg.get("generate_images"):
                gen = f"{style}；动漫风格，白色背景单品道具图，{prompt_txt}，清晰无阴影，产品级展示。"
                try:
                    imgs = _gen_images(gen, out_dir, cfg, num=1, aspect="1:1")
                    saved = _finalize(out_dir, nid, f"prop_{i+1}", imgs)
                    for abs_p in saved:
                        agi.register_asset(creation_id, "prop_image", name=name,
                                           paths_list=[abs_p], description="道具单品图")
                        agi.update_prop(prop["id"], image_url=abs_p)
                    images.extend(saved)
                except Exception as e:  # noqa: BLE001
                    if callback:
                        callback(80, f"道具 {name} 配图生成失败（跳过）：{e}")
            if callback:
                callback(20 + int(70 * (i + 1) / max(1, len(props))), f"道具：{name}")

        data = {"creation_id": creation_id, "prop_ids": prop_ids, "props": prop_meta, "images": images}
        cache = _write_cache(task_dir, nid, "prop", data)
        return {
            "artifacts": [cache] + [os.path.relpath(p, task_dir) for p in images],
            "outputs": {
                "creation_id": creation_id,
                "prop_ids": json.dumps(prop_ids, ensure_ascii=False),
                "props": json.dumps(prop_meta, ensure_ascii=False),
                "images": json.dumps(images, ensure_ascii=False),
            },
        }


class S_AGI_Extract(BaseStep):
    """资产自动提取：从格式化剧本一次性提取人物/场景/道具，按名去重入库。

    对标 Drama 的 extractor Agent：把「逐节点手写资产」升级为「剧本 → 自动提取」，
    同名人物 / 同地点+时段场景 / 同名道具自动复用更新，新增项写入一级资产表。
    """
    step_id = "agi_extract"
    step_name = "资产自动提取"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        return os.path.isfile(_cache_path(task_dir, _node_id(self), "extract"))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback=None, cancel_callback=None) -> dict:
        from backend import creation as agi
        cfg = _cfg(self)
        inp = _inputs(self)
        nid = _node_id(self)

        creation_id = (inp.get("creation_id") or cfg.get("creation_id") or "").strip()
        if not creation_id:
            raise RuntimeError("缺少 creation_id：请连接「项目立项·剧本创作」节点的 creation_id 输出")
        proj = agi.get_creation(creation_id, with_detail=True)

        brief = _read_text(inp.get("text"), task_dir)
        screenplay = _project_screenplay(proj)
        mode = _resolve_asset_mode(cfg, screenplay)
        style = _style_hint(agi, creation_id, cfg)
        model = cfg.get("llm_model") or ""

        existing_chars = {_normalize_name(c.get("name", "")): c for c in proj.get("characters", [])}
        existing_scenes = {}
        for s in agi.list_scenes(creation_id):
            for k in _scene_keys(location=s.get("location", ""), time=s.get("time", ""), name=s.get("name", "")):
                existing_scenes.setdefault(k, s)
        existing_props = {p.get("name") for p in agi.list_props(creation_id)}

        system = "你是 AI 漫剧的资产提取器，依据剧本精确提取人物/场景/道具。只输出 JSON 对象，禁止多余文本。"
        schema = ('返回 JSON 对象：{"characters":[...], "scenes":[...], "props":[...]}。\n'
                  'characters 元素字段：name, gender, age, personality, occupation, aliases(数组), '
                  'relationship_note, voice_design, visual_anchor(造型锚点30-60字)。\n'
                  'scenes 元素字段：name, location, time, lighting, prompt(结构化场景描述)。\n'
                  'props 元素字段：name, type, description, prompt(生图提示词)。\n'
                  '只提取真实推动剧情、出场的资产；姓名/场景/道具务必不重复。')
        if mode == "extract":
            prompt = (f"从以下格式化剧本中**提取**人物/场景/道具，按名去重：\n"
                      f"【格式化剧本】\n{screenplay or '（暂无）'}\n"
                      f"【已有】人物{[c.get('name') for c in existing_chars.values()] or '无'}；"
                      f"场景{[s.get('name') for s in existing_scenes.values()] or '无'}；"
                      f"道具{sorted(existing_props) or '无'}\n"
                      f"同名者做设计提炼更新、不要重复创造；剧本中出现但尚无的可新增。宁少勿多。\n\n{schema}")
        else:
            prompt = (f"基于以下创意/剧本设计资产：\n【补充】\n{brief}\n\n"
                      f"建议 3-6 人物、4-8 场景、4-8 道具。\n\n{schema}")
        if style:
            prompt += f"\n整体画风：{style}"

        resp = _llm(self.step_id, prompt, system=system, json_mode=True, model=model)
        data = resp if isinstance(resp, dict) else {}

        char_ids, char_meta = [], []
        for c in (_extract_list(data.get("characters")) or []):
            if not isinstance(c, dict):
                continue
            name = str(c.get("name") or "").strip()
            if not name:
                continue
            look = str(c.get("visual_anchor") or "").strip()
            fields = dict(
                gender=str(c.get("gender") or ""), age=str(c.get("age") or ""),
                personality=((f"【造型】{look}；" if look else "") + str(c.get("personality") or "").strip()),
                occupation=str(c.get("occupation") or ""),
                aliases=c.get("aliases") or [],
                relationship_note=str(c.get("relationship_note") or ""),
                voice_design=str(c.get("voice_design") or ""),
                status="ready")
            key = _normalize_name(name)
            if key in existing_chars:
                member = agi.update_creation_character(existing_chars[key]["id"], **fields)
                member["extracted"] = True
            else:
                member = agi.add_creation_character(creation_id, name, **fields)
                member["extracted"] = False
                existing_chars[key] = member
            char_ids.append(member["id"])
            char_meta.append(member)
            if callback:
                callback(20, f"人物{'提炼' if member.get('extracted') else '新增'}：{name}")

        scene_ids, scene_meta = [], []
        for s in (_extract_list(data.get("scenes")) or []):
            if not isinstance(s, dict):
                s = {"name": str(s)}
            location = str(s.get("location") or "").strip()
            time_txt = str(s.get("time") or "").strip()
            name = (s.get("name") or " · ".join([x for x in (location, time_txt) if x])).strip()
            desc = (s.get("prompt") or s.get("description") or "").strip()
            lighting = (s.get("lighting") or "").strip()
            keys = _scene_keys(location, time_txt, name)
            scene = None
            for k in keys:
                if k in existing_scenes:
                    scene = existing_scenes[k]
                    break
            if scene:
                scene = agi.update_scene(scene["id"], name=name, location=location, time=time_txt,
                                         lighting=lighting, prompt=desc, status="ready")
                scene["reused"] = True
            else:
                scene = agi.add_creation_scene(creation_id, name=name, location=location,
                                               time=time_txt, lighting=lighting, prompt=desc)
                for k in keys:
                    existing_scenes.setdefault(k, scene)
                scene["reused"] = False
            scene_ids.append(scene["id"])
            scene_meta.append(scene)
            if callback:
                callback(50, f"场景{'复用' if scene.get('reused') else '新增'}：{name}")

        prop_ids, prop_meta = [], []
        for p in (_extract_list(data.get("props")) or []):
            if not isinstance(p, dict):
                p = {"name": str(p)}
            name = str(p.get("name") or "").strip()
            if not name:
                continue
            ptype = str(p.get("type") or "").strip()
            desc = str(p.get("description") or "").strip()
            prompt_txt = str(p.get("prompt") or desc).strip()
            if name in existing_props:
                prop = next((x for x in agi.list_props(creation_id) if x.get("name") == name), None)
                if not prop:
                    continue
                prop = agi.update_prop(prop["id"], type=ptype, description=desc, prompt=prompt_txt, status="ready")
                prop["reused"] = True
            else:
                prop = agi.add_creation_prop(creation_id, name, type=ptype, description=desc, prompt=prompt_txt)
                existing_props.add(name)
                prop["reused"] = False
            prop_ids.append(prop["id"])
            prop_meta.append(prop)
            if callback:
                callback(80, f"道具{'复用' if prop.get('reused') else '新增'}：{name}")

        out = {"creation_id": creation_id, "character_ids": char_ids, "scene_ids": scene_ids,
               "prop_ids": prop_ids, "characters": char_meta, "scenes": scene_meta, "props": prop_meta}
        cache = _write_cache(task_dir, nid, "extract", out)
        return {
            "artifacts": [cache],
            "outputs": {
                "creation_id": creation_id,
                "character_ids": json.dumps(char_ids, ensure_ascii=False),
                "scene_ids": json.dumps(scene_ids, ensure_ascii=False),
                "prop_ids": json.dumps(prop_ids, ensure_ascii=False),
                "characters": json.dumps(char_meta, ensure_ascii=False),
                "scenes": json.dumps(scene_meta, ensure_ascii=False),
                "props": json.dumps(prop_meta, ensure_ascii=False),
            },
        }


class S_AGI_Prompt(BaseStep):
    """提示词生成：把资产描述 → final_prompt（可调试/可人工改），供生图节点使用。

    对标 Drama 的 prompt_generator：先把资产描述结合整体画风生成最终生图提示词写入库，
    再进入生图节点，提升出图质量与可干预性。
    """
    step_id = "agi_prompt"
    step_name = "生成提示词"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        return os.path.isfile(_cache_path(task_dir, _node_id(self), "prompt"))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback=None, cancel_callback=None) -> dict:
        from backend import creation as agi
        cfg = _cfg(self)
        inp = _inputs(self)
        nid = _node_id(self)

        creation_id = (inp.get("creation_id") or cfg.get("creation_id") or "").strip()
        if not creation_id:
            raise RuntimeError("缺少 creation_id：请连接「项目立项·剧本创作」节点的 creation_id 输出")
        agi.get_creation(creation_id)
        style = _style_hint(agi, creation_id, cfg)
        asset_type = (cfg.get("asset_type") or "scene").strip().lower()
        if asset_type not in ("character", "scene", "prop"):
            asset_type = "scene"
        model = cfg.get("llm_model") or ""
        ids = inp.get("ids")
        id_list = []
        if isinstance(ids, str) and ids.strip():
            try:
                id_list = [str(x) for x in json.loads(ids) if x]
            except Exception:  # noqa: BLE001
                id_list = []
        elif isinstance(ids, list):
            id_list = [str(x) for x in ids if x]

        if asset_type == "character":
            assets = (agi.get_creation(creation_id, with_detail=True).get("characters") or [])
        elif asset_type == "scene":
            assets = agi.list_scenes(creation_id)
        else:
            assets = agi.list_props(creation_id)
        if id_list:
            assets = [a for a in assets if a.get("id") in set(id_list)]

        system = "你是 AI 漫剧的生图提示词工程师，把资产描述与整体画风融合成高质量生图提示词。"
        results = []
        for i, a in enumerate(assets):
            if asset_type == "character":
                look = _extract_look(a.get("personality") or "")
                src = (f"姓名：{a.get('name')}\n性别：{a.get('gender')}\n年龄：{a.get('age')}\n"
                       f"职业：{a.get('occupation')}\n性格：{a.get('personality')}\n"
                       f"造型锚点：{look or a.get('visual_anchor', '')}")
                label = f"角色 {a.get('name')}"
            elif asset_type == "scene":
                src = (f"场景：{a.get('name')}\n地点：{a.get('location')}\n时间：{a.get('time')}\n"
                       f"光影：{a.get('lighting')}\n描述：{a.get('prompt')}")
                label = f"场景 {a.get('name')}"
            else:
                src = (f"道具：{a.get('name')}\n类别：{a.get('type')}\n"
                       f"描述：{a.get('description')}\n生图要素：{a.get('prompt')}")
                label = f"道具 {a.get('name')}"
            prompt = (f"为「{label}」生成最终生图提示词（用于动漫风格图像生成）。\n"
                      f"【资产描述】\n{src}\n"
                      f"【整体画风】{style or '动漫风格'}\n"
                      f"输出：直接给出 final_prompt 文本（聚焦视觉要素：主体/构图/光影/画风，不超过 200 字）。")
            final = _llm(self.step_id, prompt, system=system, json_mode=False, model=model)
            final = (final if isinstance(final, str) else str(final)).strip()
            if asset_type == "character":
                agi.update_creation_character(a["id"], final_prompt=final)
            elif asset_type == "scene":
                agi.update_scene(a["id"], final_prompt=final)
            else:
                agi.update_prop(a["id"], final_prompt=final)
            results.append({"id": a.get("id"), "name": a.get("name"), "final_prompt": final})
            if callback:
                callback(int(90 * (i + 1) / max(1, len(assets))), f"提示词：{label}")

        cache = _write_cache(task_dir, nid, "prompt",
                             {"creation_id": creation_id, "asset_type": asset_type, "results": results})
        return {
            "artifacts": [cache],
            "outputs": {
                "creation_id": creation_id,
                "asset_type": asset_type,
                "ids": json.dumps([r["id"] for r in results], ensure_ascii=False),
                "final_prompts": json.dumps(results, ensure_ascii=False),
            },
        }


class S_AGI_Chapter(BaseStep):
    """章节剧本：为项目生成若干章节（标题/原文/简述）并写入。"""
    step_id = "agi_chapter"
    step_name = "章节剧本"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        return os.path.isfile(_cache_path(task_dir, _node_id(self), "chapter"))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback=None, cancel_callback=None) -> dict:
        from backend import creation as agi
        cfg = _cfg(self)
        inp = _inputs(self)
        nid = _node_id(self)

        creation_id = (inp.get("creation_id") or cfg.get("creation_id") or "").strip()
        if not creation_id:
            raise RuntimeError("缺少 creation_id：请连接上游节点的 creation_id 输出")
        proj = agi.get_creation(creation_id, with_detail=True)

        brief = _read_text(inp.get("text"), task_dir) or (proj.get("script_text") or "")
        n = max(1, int(cfg.get("num_chapters") or 1))
        system = "你是 AI 漫剧主编剧，擅长拆分章节、控制节奏。只输出 JSON 数组。"
        prompt = (f"基于以下剧本/简介，规划 {n} 个章节。\n【剧本】\n{brief}\n"
                  f"返回 JSON 数组，每个元素：{{title:章节标题, original_text:章节剧情原文, "
                  f"summary:本章简述}}。")
        resp = _llm(self.step_id, prompt, system=system, json_mode=True,
                            model=(cfg.get("llm_model") or ""))
        chapters = _extract_list(resp)
        if not chapters:
            raise RuntimeError("LLM 未返回有效的章节剧本")

        from backend.creation import status as cstatus
        force = bool(cfg.get("force"))
        existing = {ch["order_no"]: ch for ch in agi.list_chapters(creation_id)}
        produced, skipped = [], []
        for i, c in enumerate(chapters):
            if not isinstance(c, dict):
                c = {"title": f"第{i+1}章", "original_text": str(c), "summary": ""}
            order_no = i + 1
            title = (c.get("title") or f"第{i+1}章").strip()
            orig = c.get("original_text") or ""
            summary = c.get("summary") or ""
            prev = existing.get(order_no)
            if prev is not None and cstatus.should_skip(prev.get("status", ""), force=force):
                skipped.append(prev)
                if callback:
                    callback(20 + int(70 * (i + 1) / max(1, len(chapters))),
                             f"已跳过(就绪)：{prev.get('title')}")
                continue
            if prev is not None:
                ch = agi.update_chapter(prev["id"], title=title, original_text=orig,
                                        summary=summary, status=cstatus.STATUS_GENERATING)
            else:
                ch = agi.add_chapter(creation_id, order_no=order_no, title=title,
                                     original_text=orig, summary=summary,
                                     status=cstatus.STATUS_GENERATING)
            ch = agi.update_chapter(ch["id"], status=cstatus.STATUS_READY)
            produced.append(ch)
            if callback:
                callback(20 + int(70 * (i + 1) / max(1, len(chapters))),
                         f"已写入章节：{ch.get('title')}")

        all_ch = produced + skipped
        out_ids = [c["id"] for c in all_ch]
        data = {"creation_id": creation_id, "chapter_ids": out_ids, "chapters": all_ch,
                "created_chapter_ids": [c["id"] for c in produced],
                "skipped_chapter_ids": [c["id"] for c in skipped]}
        cache = _write_cache(task_dir, nid, "chapter", data)
        return {
            "artifacts": [cache],
            "outputs": {
                "creation_id": creation_id,
                "chapter_id": out_ids[-1] if out_ids else "",
                "chapter_ids": json.dumps(out_ids, ensure_ascii=False),
                "created_chapter_ids": json.dumps([c["id"] for c in produced], ensure_ascii=False),
                "skipped_chapter_ids": json.dumps([c["id"] for c in skipped], ensure_ascii=False),
                "chapters": json.dumps(all_ch, ensure_ascii=False),
            },
        }


class S_AGI_Shot(BaseStep):
    """分镜剧本：为某章节生成若干分镜（人物/场景/对话/音效设计）并写入。"""
    step_id = "agi_shot"
    step_name = "分镜剧本"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        return os.path.isfile(_cache_path(task_dir, _node_id(self), "shot"))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback=None, cancel_callback=None) -> dict:
        from backend import creation as agi
        cfg = _cfg(self)
        inp = _inputs(self)
        nid = _node_id(self)

        chapter_id = (inp.get("chapter_id") or cfg.get("chapter_id") or "").strip()
        if not chapter_id:
            raise RuntimeError("缺少 chapter_id：请连接「章节剧本」节点的 chapter_id 输出")
        chapter = agi.get_chapter(chapter_id)
        creation_id = chapter.get("creation_id")

        proj = agi.get_creation(creation_id, with_detail=True)
        char_names = [c.get("name") for c in proj.get("characters", [])]
        brief = _read_text(inp.get("text"), task_dir) or (chapter.get("original_text") or "")
        n = max(1, int(cfg.get("num_shots") or 8))
        system = "你是 AI 漫剧分镜师，擅长把章节拆成镜头语言。只输出 JSON 数组。"
        prompt = (f"为以下章节设计 {n} 个分镜。\n【章节】\n{brief}\n"
                  f"【出场人物库】{char_names}\n"
                  f"返回 JSON 数组，每个元素：{{characters:出场人物名数组, "
                  f"scene_descriptions:场景描述数组, dialogues:对话数组(每项{{character,content}}), "
                  f"shot_type:镜头类型(如特写/中景/全景), angle:拍摄角度, movement:运镜方式, "
                  f"atmosphere:氛围与光影, location:地点, time:时间段, "
                  f"duration_seconds:本分镜时长(秒,8-15), "
                  f"bgm_design:背景音乐设计, sfx_design:音效设计}}。")
        resp = _llm(self.step_id, prompt, system=system, json_mode=True,
                            model=(cfg.get("llm_model") or ""))
        shots = _extract_list(resp)
        if not shots:
            raise RuntimeError("LLM 未返回有效的分镜剧本")

        from backend.creation import status as cstatus
        force = bool(cfg.get("force"))
        _chap = agi.get_chapter(chapter_id, with_shots=True)
        existing_shots = {s["order_no"]: s for s in (_chap.get("shots") or [])}
        produced, skipped = [], []
        for i, s in enumerate(shots):
            if not isinstance(s, dict):
                s = {"scene_descriptions": [str(s)]}
            dur = s.get("duration_seconds")
            dur_val = None
            if str(dur or "").strip() not in ("", None):
                try:
                    dur_val = float(dur)
                except (TypeError, ValueError):
                    dur_val = None
            order_no = i + 1
            fields = dict(
                characters=s.get("characters") or [],
                scene_descriptions=s.get("scene_descriptions") or [],
                dialogues=s.get("dialogues") or [],
                bgm_design=s.get("bgm_design") or "",
                sfx_design=s.get("sfx_design") or "",
                shot_type=s.get("shot_type") or "",
                angle=s.get("angle") or "",
                movement=s.get("movement") or "",
                atmosphere=s.get("atmosphere") or "",
                location=s.get("location") or "",
                time=s.get("time") or "",
                duration_seconds=dur_val,
            )
            prev = existing_shots.get(order_no)
            if prev is not None and cstatus.should_skip(prev.get("status", ""), force=force):
                skipped.append(prev)
                if callback:
                    callback(20 + int(70 * (i + 1) / max(1, len(shots))),
                             f"已跳过(就绪)分镜 #{prev.get('order_no')}")
                continue
            if prev is not None:
                shot = agi.update_shot(prev["id"], status=cstatus.STATUS_GENERATING, **fields)
            else:
                shot = agi.add_shot(chapter_id, status=cstatus.STATUS_GENERATING, **fields)
            shot = agi.update_shot(shot["id"], status=cstatus.STATUS_READY)
            produced.append(shot)
            if callback:
                callback(20 + int(70 * (i + 1) / max(1, len(shots))),
                         f"已写入分镜 #{shot.get('order_no')}")

        all_shots = produced + skipped
        out_ids = [s["id"] for s in all_shots]
        data = {"chapter_id": chapter_id, "shot_ids": out_ids, "shots": all_shots,
                "created_shot_ids": [s["id"] for s in produced],
                "skipped_shot_ids": [s["id"] for s in skipped]}
        cache = _write_cache(task_dir, nid, "shot", data)
        return {
            "artifacts": [cache],
            "outputs": {
                "chapter_id": chapter_id,
                "shot_ids": json.dumps(out_ids, ensure_ascii=False),
                "created_shot_ids": json.dumps([s["id"] for s in produced], ensure_ascii=False),
                "skipped_shot_ids": json.dumps([s["id"] for s in skipped], ensure_ascii=False),
                "shots": json.dumps(all_shots, ensure_ascii=False),
            },
        }


class S_AGI_ShotFrames(BaseStep):
    """分镜首尾帧：为分镜生成首/尾帧概念图（支持整章批处理），可注入角色/场景参考图。"""
    step_id = "agi_shot_frames"
    step_name = "分镜首尾帧"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        return os.path.isfile(_cache_path(task_dir, _node_id(self), "frames"))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback=None, cancel_callback=None) -> dict:
        from backend import creation as agi
        cfg = _cfg(self)
        inp = _inputs(self)
        nid = _node_id(self)
        out_dir = os.path.join(task_dir, "output")
        os.makedirs(out_dir, exist_ok=True)

        shot_id = (inp.get("shot_id") or cfg.get("shot_id") or "").strip()
        chapter_id = (inp.get("chapter_id") or cfg.get("chapter_id") or "").strip()
        targets = _resolve_shot_targets(shot_id, chapter_id)
        if not targets:
            raise RuntimeError("缺少 shot_id / chapter_id：连接「分镜剧本」输出，或填 chapter_id 批处理整章")

        force = bool(cfg.get("force", False))
        cfg, use_lock = _resolve_effective_cfg(cfg, chapter_id, self.step_id)
        first_shot = agi.get_shot(targets[0])
        creation_id, _ = _resolve_creation_of(shot_id=targets[0])
        creation = agi.get_creation(creation_id, with_detail=True)
        scene_assets = [a for a in agi.list_assets(creation_id, asset_kind="scene_image")
                        if not a.get("shot_id")]
        style = _style_hint(agi, creation_id, cfg)
        use_char = bool(cfg.get("use_char_ref", True))
        use_scene = bool(cfg.get("use_scene_ref", True))
        try:
            max_refs = max(0, int(cfg.get("max_ref_images") or 4))
        except (TypeError, ValueError):
            max_refs = 4
        batch = len(targets) > 1

        results = []
        local_files = []
        for idx, sid in enumerate(targets):
            shot = agi.get_shot(sid)
            _, ch_id = _resolve_creation_of(shot_id=sid)
            if not force and agi.list_assets(creation_id, asset_kind="scene_image", shot_id=sid):
                if callback:
                    callback(int(90 * (idx + 1) / len(targets)), f"分镜 {idx + 1} 首尾帧已存在，跳过")
                results.append({"shot_id": sid, "first_frame": "", "last_frame": ""})
                continue
            scene_txt = "；".join(shot.get("scene_descriptions") or [])
            _looks = _character_looks(creation)
            char_txt = "、".join(
                (f"{n}（{_looks[n]}）" if _looks.get(n) else n)
                for n in [c if isinstance(c, str) else c.get("name", "")
                          for c in (shot.get("characters") or [])] if n)
            base = f"{style}；动漫分镜关键帧，{scene_txt}"
            if char_txt:
                base += f"，画面中人物：{char_txt}"
            refs = _collect_ref_images(agi, shot, creation, scene_assets, max_refs,
                                       use_char=use_char, use_scene=use_scene) if max_refs else []
            r = {"shot_id": sid, "first_frame": "", "last_frame": ""}
            if cfg.get("generate_first", True):
                p = base + "，分镜起始画面，构图完整，可作为视频首帧。"
                imgs = _gen_images(p, out_dir, cfg, num=1, aspect="16:9", ref_images=refs)
                saved = _finalize(out_dir, nid, f"first_{idx + 1}", imgs)
                for abs_p in saved:
                    agi.register_asset(creation_id, "scene_image", chapter_id=ch_id,
                                       shot_id=sid, paths_list=[abs_p], description="分镜首帧")
                r["first_frame"] = saved[0] if saved else ""
                local_files.extend(saved)
            if cfg.get("generate_last", True):
                p = base + "，分镜结束画面，与起始呼应，可作为视频尾帧。"
                imgs = _gen_images(p, out_dir, cfg, num=1, aspect="16:9", ref_images=refs)
                saved = _finalize(out_dir, nid, f"last_{idx + 1}", imgs)
                for abs_p in saved:
                    agi.register_asset(creation_id, "scene_image", chapter_id=ch_id,
                                       shot_id=sid, paths_list=[abs_p], description="分镜尾帧")
                r["last_frame"] = saved[0] if saved else ""
                local_files.extend(saved)
            results.append(r)
            if callback:
                callback(int(90 * (idx + 1) / len(targets)),
                         f"分镜 {idx + 1}/{len(targets)} 首尾帧完成（参考图 {len(refs)} 张）")

        if not use_lock and chapter_id:
            _write_locked_cfg(chapter_id, self.step_id, cfg)
        firsts = [r["first_frame"] for r in results if r["first_frame"]]
        lasts = [r["last_frame"] for r in results if r["last_frame"]]
        head = results[0]
        cache = _write_cache(task_dir, nid, "frames", {"results": results})
        return {
            "artifacts": [cache] + [os.path.relpath(p, task_dir) for p in local_files],
            "outputs": {
                "shot_id": "" if batch else head["shot_id"],
                "first_frame": "" if batch else head["first_frame"],
                "last_frame": "" if batch else head["last_frame"],
                "shot_ids": json.dumps([r["shot_id"] for r in results], ensure_ascii=False),
                "first_frames": json.dumps(firsts, ensure_ascii=False),
                "last_frames": json.dumps(lasts, ensure_ascii=False),
                "images": json.dumps(firsts + lasts, ensure_ascii=False),
            },
        }


class S_AGI_ShotVideo(BaseStep):
    """分镜视频制作：以首/尾帧 + 画面描述生成视频（支持整章批处理），登记 shot_video。"""
    step_id = "agi_shot_video"
    step_name = "分镜视频制作"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        return os.path.isfile(_cache_path(task_dir, _node_id(self), "shotvideo"))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback=None, cancel_callback=None) -> dict:
        from backend import creation as agi
        cfg = _cfg(self)
        inp = _inputs(self)
        nid = _node_id(self)
        out_dir = os.path.join(task_dir, "output")
        os.makedirs(out_dir, exist_ok=True)

        shot_id = (inp.get("shot_id") or cfg.get("shot_id") or "").strip()
        chapter_id = (inp.get("chapter_id") or cfg.get("chapter_id") or "").strip()
        targets = _resolve_shot_targets(shot_id, chapter_id)
        if not targets:
            raise RuntimeError("缺少 shot_id / chapter_id：连接「分镜剧本」输出，或填 chapter_id 批处理整章")

        force = bool(cfg.get("force", False))
        cfg, use_lock = _resolve_effective_cfg(cfg, chapter_id, self.step_id)

        # 视频提示词只用画面语言（场景+运镜），台词属于音频层，混入会干扰画面生成
        prompt_override = _read_text(inp.get("text"), task_dir)
        camera = (cfg.get("camera_prompt") or "")
        duration = max(1, int(cfg.get("duration") or 5))
        aspect = (cfg.get("aspect_ratio") or "16:9")
        batch = len(targets) > 1

        results = []
        local_files = []
        for idx, sid in enumerate(targets):
            shot = agi.get_shot(sid)
            creation_id, ch_id = _resolve_creation_of(shot_id=sid)
            if not force and agi.list_assets(creation_id, asset_kind="shot_video", shot_id=sid):
                _a = agi.list_assets(creation_id, asset_kind="shot_video", shot_id=sid)[0]
                _p = (_a.get("paths") or [""])[0]
                if callback:
                    callback(int(90 * idx / len(targets)), f"分镜 {idx + 1} 视频已存在，跳过")
                results.append({"shot_id": sid, "video": _p})
                continue

            first = last = None
            if not batch:
                first = _resolve_file(inp.get("first_frame"), task_dir)
                last = _resolve_file(inp.get("last_frame"), task_dir)
            if not (first and last):
                paths = []
                for a in agi.list_assets(creation_id, asset_kind="scene_image", shot_id=sid):
                    for p in (a.get("paths") or []):
                        abs_p = _asset_abs(agi, p)
                        if abs_p:
                            paths.append(abs_p)
                if not first and paths:
                    first = paths[0]
                if not last and paths:
                    last = paths[-1]
            if not (first and last):
                raise RuntimeError(f"分镜 {sid} 缺少首帧/尾帧：请先运行「分镜首尾帧」")

            if prompt_override:
                prompt = prompt_override
            else:
                # 按 video_prompt.md 规范拼装：3 秒一段、@角色引用、后续段用"切到"衔接
                at_chars = "".join(
                    f"@{c}" for c in
                    [x if isinstance(x, str) else (x.get("name") or "")
                     for x in (shot.get("characters") or [])] if c)
                _scenes = list(shot.get("scene_descriptions") or [])
                _lines = []
                for _i, _s in enumerate(_scenes):
                    _head = f"{_i * 3}-{(_i + 1) * 3}秒："
                    if _i:
                        _head += "切到"
                    _lines.append(_head + (at_chars + "，" if at_chars else "") + _s)
                for _j, _d in enumerate(shot.get("dialogues") or []):
                    if not isinstance(_d, dict) or not _d.get("content"):
                        continue
                    _tail = f"，{_d.get('character') or ''}说：「{_d['content']}」"
                    if _j < len(_lines):
                        _lines[_j] += _tail
                    else:
                        _lines.append(f"{len(_lines) * 3}-{(len(_lines) + 1) * 3}秒："
                                      + (at_chars + "，" if at_chars else "")
                                      + _d["content"])
                prompt = "\n".join(_lines) if _lines else ""
                if not prompt:
                    prompt = "；".join(_scenes) + (f"，{camera}" if camera else "")
                elif camera:
                    prompt = f"{camera}\n" + prompt
            if callback:
                callback(int(90 * idx / len(targets)), f"分镜 {idx + 1}/{len(targets)} 提交生视频…")
            vids = _gen_video(prompt, out_dir, cfg, ref_images=[first, last],
                              duration=duration, aspect=aspect)
            saved = _finalize(out_dir, nid, f"shotvideo_{idx + 1}", vids)
            if not saved:
                raise RuntimeError(f"分镜 {sid} 生视频未返回任何结果")
            agi.register_asset(creation_id, "shot_video", chapter_id=ch_id, shot_id=sid,
                               paths_list=[saved[0]], duration_seconds=float(duration))
            results.append({"shot_id": sid, "video": saved[0]})
            local_files.extend(saved)

        if not use_lock and chapter_id:
            _write_locked_cfg(chapter_id, self.step_id, cfg)
        head = results[0]
        cache = _write_cache(task_dir, nid, "shotvideo", {"results": results})
        return {
            "artifacts": [cache] + [os.path.relpath(p, task_dir) for p in local_files],
            "outputs": {
                "shot_id": "" if batch else head["shot_id"],
                "video": "" if batch else head["video"],
                "shot_ids": json.dumps([r["shot_id"] for r in results], ensure_ascii=False),
                "videos": json.dumps([r["video"] for r in results], ensure_ascii=False),
            },
        }


class S_AGI_ShotDub(BaseStep):
    """分镜配音：按分镜对话逐句 TTS（依人物音色克隆），拼接配音并同步产出 SRT 字幕。

    人物 voice_ref 来自「人物音色生产」节点（vf: 引用）；无 voice_ref 时回退
    节点配置的预设音色/音色设计。
    """
    step_id = "agi_shot_dub"
    step_name = "分镜配音"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        return os.path.isfile(_cache_path(task_dir, _node_id(self), "dub"))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback=None, cancel_callback=None) -> dict:
        from backend import creation as agi
        from backend.utils.audio_processor import get_audio_duration
        cfg = _cfg(self)
        inp = _inputs(self)
        nid = _node_id(self)
        out_dir = os.path.join(task_dir, "output")
        os.makedirs(out_dir, exist_ok=True)

        shot_id = (inp.get("shot_id") or cfg.get("shot_id") or "").strip()
        chapter_id = (inp.get("chapter_id") or cfg.get("chapter_id") or "").strip()
        targets = _resolve_shot_targets(shot_id, chapter_id)
        if not targets:
            raise RuntimeError("缺少 shot_id / chapter_id：连接「分镜剧本」输出，或填 chapter_id 批处理整章")

        force = bool(cfg.get("force", False))
        cfg, use_lock = _resolve_effective_cfg(cfg, chapter_id, self.step_id)
        first_shot = agi.get_shot(targets[0])
        creation_id, _ = _resolve_creation_of(shot_id=targets[0])
        proj = agi.get_creation(creation_id, with_detail=True)
        voice_map = {c.get("name"): c.get("voice_ref") for c in proj.get("characters", [])}
        batch = len(targets) > 1
        make_srt = bool(cfg.get("make_srt", True))

        results = []
        local_files = []
        for idx, sid in enumerate(targets):
            shot = agi.get_shot(sid)
            _, ch_id = _resolve_creation_of(shot_id=sid)
            if not force and agi.list_assets(creation_id, asset_kind="voiceover", shot_id=sid):
                _a = agi.list_assets(creation_id, asset_kind="voiceover", shot_id=sid)[0]
                _p = (_a.get("paths") or [""])[0]
                _st = (_a.get("metadata") or {}).get("subtitle", "") if isinstance(_a.get("metadata"), dict) else ""
                if not _st and _p:  # metadata 读取不可靠时，回退音频同名 .srt
                    _guess = os.path.splitext(_p)[0] + ".srt"
                    if os.path.isfile(_guess):
                        _st = _guess
                if callback:
                    callback(int(90 * idx / len(targets)), f"分镜 {idx + 1} 配音已存在，跳过")
                results.append({"shot_id": sid, "audio": _p, "subtitle": _st, "duration": _a.get("duration_seconds") or 0.0})
                continue
            dialogues = [d for d in (shot.get("dialogues") or [])
                         if isinstance(d, dict) and d.get("content")]
            if not dialogues:
                if batch:
                    if callback:
                        callback(int(90 * idx / len(targets)), f"分镜 {idx + 1} 无对话，跳过")
                    continue
                raise RuntimeError("该分镜没有可配音的对话内容")

            segs = []
            lines = []
            t = 0.0
            for i, d in enumerate(dialogues):
                char = d.get("character", "")
                voice_ref = voice_map.get(char)
                ref_audio = None
                if voice_ref:
                    try:
                        ref_audio = agi.audio_ref_abspath(voice_ref)
                    except Exception:  # noqa: BLE001
                        ref_audio = None
                seg = os.path.join(out_dir, f"dub_seg_{idx + 1}_{i + 1}_{nid}.wav")
                if callback:
                    callback(int(85 * idx / len(targets)) +
                             int(10 * (i + 1) / len(dialogues)), f"分镜 {idx + 1} 合成：{char}")
                _tts(d["content"], seg, cfg, ref_audio=ref_audio)
                segs.append(seg)
                try:
                    seg_dur = get_audio_duration(seg) or 0.0
                except Exception:  # noqa: BLE001
                    seg_dur = 0.0
                lines.append((t, t + seg_dur, f"{char}：{d['content']}"))
                t += seg_dur

            dub_path = os.path.join(out_dir, f"voiceover_{idx + 1}_{nid}.wav")
            _concat_audios(segs, dub_path)
            try:
                dur = get_audio_duration(dub_path) or 0.0
            except Exception:  # noqa: BLE001
                dur = 0.0
            srt_path = ""
            meta = {}
            if make_srt and lines:
                srt_path = os.path.join(out_dir, f"voiceover_{idx + 1}_{nid}.srt")
                with open(srt_path, "w", encoding="utf-8") as f:
                    f.write(_build_srt(lines))
                meta = {"subtitle": srt_path}
                local_files.append(srt_path)
            agi.register_asset(creation_id, "voiceover", chapter_id=ch_id, shot_id=sid,
                               paths_list=[dub_path], duration_seconds=dur, metadata=meta)
            results.append({"shot_id": sid, "audio": dub_path, "subtitle": srt_path,
                            "duration": dur})
            local_files.append(dub_path)

        if not use_lock and chapter_id:
            _write_locked_cfg(chapter_id, self.step_id, cfg)
        if not results:
            raise RuntimeError("本章没有可配音的分镜（均无对话）")
        head = results[0]
        cache = _write_cache(task_dir, nid, "dub", {"results": results})
        return {
            "artifacts": [cache] + [os.path.relpath(p, task_dir) for p in local_files],
            "outputs": {
                "shot_id": "" if batch else head["shot_id"],
                "audio": "" if batch else head["audio"],
                "voiceover": json.dumps(head, ensure_ascii=False),
                "shot_ids": json.dumps([r["shot_id"] for r in results], ensure_ascii=False),
                "audios": json.dumps([r["audio"] for r in results], ensure_ascii=False),
                "subtitles": json.dumps([r["subtitle"] for r in results if r["subtitle"]],
                                        ensure_ascii=False),
            },
        }


class S_AGI_ShotExport(BaseStep):
    """分镜导出：分镜视频 + 配音 + BGM/音效混流，可烧录字幕（支持整章批处理），登记 shot_render。"""
    step_id = "agi_shot_export"
    step_name = "分镜导出"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        return os.path.isfile(_cache_path(task_dir, _node_id(self), "shotexport"))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback=None, cancel_callback=None) -> dict:
        from backend import creation as agi
        from backend.utils import audio_processor
        from backend.utils.audio_processor import get_video_duration
        cfg = _cfg(self)
        inp = _inputs(self)
        nid = _node_id(self)
        out_dir = os.path.join(task_dir, "output")
        os.makedirs(out_dir, exist_ok=True)

        shot_id = (inp.get("shot_id") or cfg.get("shot_id") or "").strip()
        chapter_id = (inp.get("chapter_id") or cfg.get("chapter_id") or "").strip()
        targets = _resolve_shot_targets(shot_id, chapter_id)
        if not targets:
            raise RuntimeError("缺少 shot_id / chapter_id：连接「分镜剧本」输出，或填 chapter_id 批处理整章")

        force = bool(cfg.get("force", False))
        cfg, use_lock = _resolve_effective_cfg(cfg, chapter_id, self.step_id)
        batch = len(targets) > 1
        burn = bool(cfg.get("burn_subtitle"))

        results = []
        local_files = []
        for idx, sid in enumerate(targets):
            creation_id, ch_id = _resolve_creation_of(shot_id=sid)
            if not bool(cfg.get("force", False)) and agi.list_assets(creation_id, asset_kind="shot_render", shot_id=sid):
                _a = agi.list_assets(creation_id, asset_kind="shot_render", shot_id=sid)
                if _a and _a[0].get("paths"):
                    if callback:
                        callback(int(90 * (idx + 1) / len(targets)), f"分镜 {idx + 1} 成片已存在，跳过")
                    results.append({"shot_id": sid, "render": _a[0]["paths"][0]})
                    continue

            video = None if batch else _resolve_file(inp.get("video"), task_dir)
            audio = None if batch else _resolve_file(inp.get("audio"), task_dir)
            srt = None if batch else _resolve_file(inp.get("subtitle"), task_dir)
            bgm = None if batch else _resolve_file(inp.get("bgm"), task_dir)
            sfx = None if batch else _resolve_file(inp.get("sfx"), task_dir)

            # 无连线时按分镜查库回退（视频/配音/字幕元数据）
            if not video:
                a = agi.list_assets(creation_id, asset_kind="shot_video", shot_id=sid)
                if a and a[0].get("paths"):
                    video = _asset_abs(agi, a[0]["paths"][0])
            if not audio:
                a = agi.list_assets(creation_id, asset_kind="voiceover", shot_id=sid)
                if a and a[0].get("paths"):
                    audio = _asset_abs(agi, a[0]["paths"][0])
            if not srt and audio:
                # 字幕回溯：配音 wav 同目录同名 .srt（metadata 列与 SQLAlchemy 声明属性冲突，dict 读取不可靠）
                guess = os.path.splitext(audio)[0] + ".srt"
                if os.path.isfile(guess):
                    srt = guess
            if not video:
                raise RuntimeError(f"分镜 {sid} 缺少视频：请先运行「分镜视频制作」")

            # sfx 与 bgm 预混为一条轨，走 mix_audio 的 bgm 通道
            bgm_track = bgm
            if sfx:
                if bgm:
                    merged = os.path.join(out_dir, f"sfx_bgm_{idx + 1}_{nid}.wav")
                    _mix_tracks([sfx, bgm], merged)
                    bgm_track = merged
                else:
                    bgm_track = sfx

            final = os.path.join(out_dir, f"shot_render_{idx + 1}_{nid}.mp4")
            mixed = os.path.join(out_dir, f"shot_mix_{idx + 1}_{nid}.mp4")
            if audio:
                audio_processor.mix_audio(
                    video_path=video, dub_path=audio, bgm_path=bgm_track,
                    bgm_vol=float(cfg.get("bgm_vol") or 0.3),
                    dub_vol=float(cfg.get("dub_vol") or 0.9),
                    fade_in=float(cfg.get("fade_in") or 0.3),
                    fade_out=float(cfg.get("fade_out") or 0.3),
                    output_path=mixed,
                    mute_original=bool(cfg.get("mute_original", False)),
                )
            else:
                shutil.copy(video, mixed)

            if burn and srt and os.path.isfile(srt):
                if not _burn_subtitle(mixed, srt, final):
                    if callback:
                        callback(int(90 * idx / len(targets)),
                                 f"分镜 {idx + 1} 字幕烧录失败（回退为无字幕成片）")
                    shutil.copy(mixed, final)
            else:
                shutil.copy(mixed, final)
            if not os.path.exists(final) or os.path.getsize(final) == 0:
                raise RuntimeError(f"分镜 {sid} 出片失败")

            try:
                dur = get_video_duration(final) or 0.0
            except Exception:  # noqa: BLE001
                dur = 0.0
            agi.register_asset(creation_id, "shot_render", chapter_id=ch_id, shot_id=sid,
                               paths_list=[final], duration_seconds=dur)
            try:
                agi.update_shot(sid, status="ready")
            except Exception:  # noqa: BLE001
                pass
            results.append({"shot_id": sid, "render": final})
            local_files.append(final)
            if callback:
                callback(int(90 * (idx + 1) / len(targets)),
                         f"分镜 {idx + 1}/{len(targets)} 出片完成")

        head = results[0]
        if not use_lock and chapter_id:
            _write_locked_cfg(chapter_id, self.step_id, cfg)
        cache = _write_cache(task_dir, nid, "shotexport", {"results": results})
        return {
            "artifacts": [cache] + [os.path.relpath(p, task_dir) for p in local_files],
            "outputs": {
                "shot_id": "" if batch else head["shot_id"],
                "render": "" if batch else head["render"],
                "shot_ids": json.dumps([r["shot_id"] for r in results], ensure_ascii=False),
                "renders": json.dumps([r["render"] for r in results], ensure_ascii=False),
            },
        }


class S_AGI_ChapterExport(BaseStep):
    """章节导出：拼接本章所有分镜成片为一个章节视频，登记 chapter_render。"""
    step_id = "agi_chapter_export"
    step_name = "章节导出"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        return os.path.isfile(_cache_path(task_dir, _node_id(self), "chapterexport"))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback=None, cancel_callback=None) -> dict:
        from backend import creation as agi
        cfg = _cfg(self)
        inp = _inputs(self)
        nid = _node_id(self)
        out_dir = os.path.join(task_dir, "output")
        os.makedirs(out_dir, exist_ok=True)

        chapter_id = (inp.get("chapter_id") or cfg.get("chapter_id") or "").strip()
        if not chapter_id:
            raise RuntimeError("缺少 chapter_id")
        chapter = agi.get_chapter(chapter_id)
        creation_id = chapter.get("creation_id")

        # 可重拼：指定历史拼接记录 ID 时，复用其分镜成片源（只换转场/封面重新拼接）
        reuse_id = (cfg.get("reuse_stitch_id") or "").strip()

        # 优先使用连线传入的 renders 列表，否则按分镜顺序查 shot_render 资产
        renders = []
        raw = inp.get("renders")
        if isinstance(raw, str) and raw.strip():
            try:
                renders = json.loads(raw)
            except Exception:  # noqa: BLE401
                renders = []
        if not renders:
            proj = agi.get_creation(creation_id, with_detail=True)
            order = {s["id"]: s.get("order_no", 0)
                     for ch in proj.get("chapters", []) if ch["id"] == chapter_id
                     for s in ch.get("shots", [])}
            assets = agi.list_assets(creation_id, asset_kind="shot_render", chapter_id=chapter_id)
            pairs = []
            for a in assets:
                for p in (a.get("paths") or []):
                    abs_p = _resolve_file(p, task_dir)
                    if abs_p:
                        pairs.append((order.get(a.get("shot_id"), 0), abs_p))
            pairs.sort(key=lambda x: x[0])
            renders = [p for _, p in pairs]
        if not renders:
            raise RuntimeError("本章没有可分镜成片：请连接「分镜导出」的 render 输出，或先运行分镜导出")
        if reuse_id:
            _hist = agi.get_chapter_stitch(reuse_id)
            if _hist.get("chapter_id") != chapter_id:
                raise RuntimeError("reuse_stitch_id 不属于本章节")
            _src = _hist.get("sources") or ""
            try:
                renders = json.loads(_src) if isinstance(_src, str) and _src else list(_src or [])
            except Exception:  # noqa: BLE001
                renders = []
            if not renders:
                raise RuntimeError("所选拼接历史没有可用的分镜成片源")

        # 成片增强：分辨率/比例预设、章节封面片头、转场衔接
        resolution = (cfg.get("resolution") or "original").strip().upper()
        aspect_ratio = (cfg.get("aspect_ratio") or "original").strip()
        transition = (cfg.get("transition") or "none").strip().lower()
        try:
            t_dur = float(cfg.get("transition_duration") or 0.4)
        except (TypeError, ValueError):
            t_dur = 0.4
        make_cover = bool(cfg.get("make_cover"))
        try:
            cover_dur = float(cfg.get("cover_duration") or 3.0)
        except (TypeError, ValueError):
            cover_dur = 3.0

        tdims = _target_dims(resolution, aspect_ratio)
        clips = list(renders)
        cover_img = ""

        if make_cover:
            cover_img = _build_chapter_cover(chapter, cfg, out_dir, nid)
            if cover_img:
                if tdims:
                    cw, ch = tdims
                else:
                    fw, fh, _ = _probe_video_dims(renders[0])
                    cw, ch = fw or 1280, fh or 720
                cclip = os.path.join(out_dir, f"chapter_cover_clip_{nid}.mp4")
                _image_to_clip(cover_img, cclip, cw, ch, 25, cover_dur)
                clips.insert(0, cclip)
                agi.register_asset(creation_id, "chapter_cover", chapter_id=chapter_id,
                                   paths_list=[cover_img])
                try:
                    agi.update_chapter(chapter_id, cover=cover_img)
                except Exception:  # noqa: BLE001
                    pass
                if callback:
                    callback(70, "已生成章节封面片头")

        final = os.path.join(out_dir, f"chapter_render_{nid}.mp4")
        if tdims:
            norm = []
            for i, p in enumerate(clips):
                np = os.path.join(out_dir, f"crender_norm_{i}_{nid}.mp4")
                _normalize_clip(p, np, tdims[0], tdims[1], 25)
                norm.append(np)
            if transition != "none":
                _concat_with_transitions(norm, final, transition, t_dur)
            else:
                _concat_videos(norm, final)
        else:
            _concat_with_transitions(clips, final, transition, t_dur)
        if not os.path.exists(final) or os.path.getsize(final) == 0:
            raise RuntimeError("章节成片拼接失败")

        dur = 0.0
        try:
            from backend.utils.audio_processor import get_video_duration
            dur = get_video_duration(final) or 0.0
        except Exception:  # noqa: BLE401
            dur = 0.0
        agi.register_asset(creation_id, "chapter_render", chapter_id=chapter_id,
                           paths_list=[final], duration_seconds=dur)
        # 记录拼接历史（有序分镜成片源 + 转场/封面配置 + 产物），供后续重拼复用
        agi.add_chapter_stitch(
            creation_id, chapter_id,
            transition=transition, transition_duration=t_dur,
            resolution=resolution, aspect_ratio=aspect_ratio,
            make_cover=make_cover, cover_duration=cover_dur,
            cover_image=cover_img,
            sources=json.dumps([os.path.abspath(p) for p in renders], ensure_ascii=False),
            output=os.path.abspath(final), duration_seconds=dur,
        )
        if callback:
            callback(95, "章节成片已登记")
        cache = _write_cache(task_dir, nid, "chapterexport", {"chapter_id": chapter_id, "render": final})
        return {
            "artifacts": [cache, os.path.relpath(final, task_dir)],
            "outputs": {"chapter_id": chapter_id, "render": final},
        }

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
import shutil
import subprocess
import uuid

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
def _llm(step_name: str, prompt: str, system: str = None, json_mode: bool = True):
    from backend.llm.llm_client import get_llm_client
    try:
        return get_llm_client().chat(step_name, prompt, system_prompt=system, response_json=json_mode)
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
                ref_images=None) -> list:
    from backend.imagegen.imagegen_factory import get_imagegen_engine
    from backend.imagegen.imagegen_interface_manager import get_imagegen_interface_manager
    iface = _pick_interface(get_imagegen_interface_manager, "image_interface", cfg)
    engine = get_imagegen_engine(iface)
    paths = engine.generate(prompt=prompt, output_dir=out_dir, mode="txt2img",
                            aspect_ratio=aspect, num_images=num,
                            ref_images=list(ref_images) if ref_images else None)
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
        resp = _llm(self.step_id, prompt, system=system, json_mode=True)
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
        agi.get_creation(creation_id)  # 校验存在

        n = max(1, int(cfg.get("num_characters") or 4))
        style = (cfg.get("art_style_prompt") or "")
        system = ("你是资深动漫编剧兼角色设计师，擅长为 AI 漫剧设计立体、有记忆点的人物。"
                  "只输出 JSON，不要多余说明。")
        prompt = (f"基于以下创意简介，设计 {n} 个主要人物（主角与关键配角）：\n"
                  f"【创意简介】\n{brief}\n\n"
                  f"请返回 JSON 数组，每个元素包含字段："
                  f"name(姓名), gender(性别), age(年龄), personality(性格), "
                  f"occupation(职业/身份), aliases(别名数组), relationship_note(人物关系网), "
                  f"voice_design(音色设计描述)。确保姓名不重复。")
        if style:
            prompt += f"\n整体画风要求：{style}"

        resp = _llm(self.step_id, prompt, system=system, json_mode=True)
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
            member = agi.add_creation_character(
                creation_id, name,
                gender=c.get("gender") or "", age=c.get("age") or "",
                personality=c.get("personality") or "", occupation=c.get("occupation") or "",
                aliases=c.get("aliases") or [], relationship_note=c.get("relationship_note") or "",
                voice_design=c.get("voice_design") or "",
            )

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
                try:
                    if lib_role:
                        # 多视角图 → 公共角色库 views 目录（data/ 相对路径入库）
                        views_abs = str(agi.resolve_public_path(
                            f"data/characters/{_safe_name(name)}_{lib_role['id'][:8]}/views"))
                        os.makedirs(views_abs, exist_ok=True)
                        view_files = []
                        for k, label in enumerate(view_labels):
                            p = f"{base}{label}视角，全身立绘，纯色背景，统一角色形象。"
                            imgs = _gen_images(p, views_abs, cfg, num=1, aspect="3:4")
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
                        imgs = _gen_images(base + "全身或半身立绘。", out_dir, cfg, num=1, aspect="1:1")
                        saved = _finalize(out_dir, nid, f"char_{i+1}", imgs)
                        for abs_p in saved:
                            agi.register_asset(creation_id, "scene_image",
                                               paths_list=[abs_p],
                                               description=f"{name} 角色立绘")
                        portraits.extend(saved)
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
        style = (cfg.get("art_style_prompt") or "")
        n = max(1, int(cfg.get("num_scenes") or 6))
        system = "你是 AI 漫剧的场景美术指导，擅长用画面语言描述场景。只输出 JSON 数组。"
        prompt = (f"基于创意/剧本，设计 {n} 个关键场景。\n【补充】\n{brief}\n"
                  f"返回 JSON 数组，每个元素：{{name:场景名, description:场景视觉描述}}。")
        if style:
            prompt += f"\n整体画风：{style}"

        resp = _llm(self.step_id, prompt, system=system, json_mode=True)
        scenes = _extract_list(resp)
        if not scenes:
            raise RuntimeError("LLM 未返回有效的场景描述")

        images = []
        scene_meta = []
        for i, s in enumerate(scenes):
            if not isinstance(s, dict):
                s = {"name": f"场景{i+1}", "description": str(s)}
            name = (s.get("name") or f"场景{i+1}").strip()
            desc = (s.get("description") or "").strip()
            scene_meta.append({"name": name, "description": desc})
            if cfg.get("generate_images"):
                p = f"{style}；动漫风格场景概念图，{desc}，氛围感强，电影级构图。"
                try:
                    imgs = _gen_images(p, out_dir, cfg, num=1, aspect="16:9")
                    saved = _finalize(out_dir, nid, f"scene_{i+1}", imgs)
                    for abs_p in saved:
                        agi.register_asset(creation_id, "scene_image",
                                           paths_list=[abs_p], description=f"{name}：{desc}")
                    images.extend(saved)
                except Exception as e:  # noqa: BLE001
                    if callback:
                        callback(80, f"场景 {name} 配图生成失败（跳过）：{e}")
            if callback:
                callback(20 + int(70 * (i + 1) / max(1, len(scenes))), f"场景：{name}")

        data = {"creation_id": creation_id, "scenes": scene_meta, "images": images}
        cache = _write_cache(task_dir, nid, "scene", data)
        return {
            "artifacts": [cache] + [os.path.relpath(p, task_dir) for p in images],
            "outputs": {
                "creation_id": creation_id,
                "scenes": json.dumps(scene_meta, ensure_ascii=False),
                "images": json.dumps(images, ensure_ascii=False),
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
        resp = _llm(self.step_id, prompt, system=system, json_mode=True)
        chapters = _extract_list(resp)
        if not chapters:
            raise RuntimeError("LLM 未返回有效的章节剧本")

        created = []
        for i, c in enumerate(chapters):
            if not isinstance(c, dict):
                c = {"title": f"第{i+1}章", "original_text": str(c), "summary": ""}
            ch = agi.add_chapter(
                creation_id,
                title=(c.get("title") or f"第{i+1}章").strip(),
                original_text=c.get("original_text") or "",
                summary=c.get("summary") or "",
            )
            created.append(ch)
            if callback:
                callback(20 + int(70 * (i + 1) / max(1, len(chapters))),
                         f"已写入章节：{ch.get('title')}")

        out_ids = [c["id"] for c in created]
        data = {"creation_id": creation_id, "chapter_ids": out_ids, "chapters": created}
        cache = _write_cache(task_dir, nid, "chapter", data)
        return {
            "artifacts": [cache],
            "outputs": {
                "creation_id": creation_id,
                "chapter_id": out_ids[-1] if out_ids else "",
                "chapter_ids": json.dumps(out_ids, ensure_ascii=False),
                "chapters": json.dumps(created, ensure_ascii=False),
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
                  f"bgm_design:背景音乐设计, sfx_design:音效设计}}。")
        resp = _llm(self.step_id, prompt, system=system, json_mode=True)
        shots = _extract_list(resp)
        if not shots:
            raise RuntimeError("LLM 未返回有效的分镜剧本")

        created = []
        for i, s in enumerate(shots):
            if not isinstance(s, dict):
                s = {"scene_descriptions": [str(s)]}
            shot = agi.add_shot(
                chapter_id,
                characters=s.get("characters") or [],
                scene_descriptions=s.get("scene_descriptions") or [],
                dialogues=s.get("dialogues") or [],
                bgm_design=s.get("bgm_design") or "",
                sfx_design=s.get("sfx_design") or "",
            )
            created.append(shot)
            if callback:
                callback(20 + int(70 * (i + 1) / max(1, len(shots))),
                         f"已写入分镜 #{shot.get('order_no')}")

        out_ids = [s["id"] for s in created]
        data = {"chapter_id": chapter_id, "shot_ids": out_ids, "shots": created}
        cache = _write_cache(task_dir, nid, "shot", data)
        return {
            "artifacts": [cache],
            "outputs": {
                "chapter_id": chapter_id,
                "shot_ids": json.dumps(out_ids, ensure_ascii=False),
                "shots": json.dumps(created, ensure_ascii=False),
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

        first_shot = agi.get_shot(targets[0])
        creation_id, _ = _resolve_creation_of(shot_id=targets[0])
        creation = agi.get_creation(creation_id, with_detail=True)
        scene_assets = [a for a in agi.list_assets(creation_id, asset_kind="scene_image")
                        if not a.get("shot_id")]
        style = (cfg.get("art_style_prompt") or "")
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
            scene_txt = "；".join(shot.get("scene_descriptions") or [])
            char_txt = "、".join([c if isinstance(c, str) else c.get("name", "")
                                 for c in (shot.get("characters") or [])])
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

            prompt = prompt_override or ("；".join(shot.get("scene_descriptions") or [])
                                         + (f"，{camera}" if camera else ""))
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

        batch = len(targets) > 1
        burn = bool(cfg.get("burn_subtitle"))

        results = []
        local_files = []
        for idx, sid in enumerate(targets):
            creation_id, ch_id = _resolve_creation_of(shot_id=sid)

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
            results.append({"shot_id": sid, "render": final})
            local_files.append(final)
            if callback:
                callback(int(90 * (idx + 1) / len(targets)),
                         f"分镜 {idx + 1}/{len(targets)} 出片完成")

        head = results[0]
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

        final = os.path.join(out_dir, f"chapter_render_{nid}.mp4")
        _concat_videos(renders, final)
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
        if callback:
            callback(95, "章节成片已登记")
        cache = _write_cache(task_dir, nid, "chapterexport", {"chapter_id": chapter_id, "render": final})
        return {
            "artifacts": [cache, os.path.relpath(final, task_dir)],
            "outputs": {"chapter_id": chapter_id, "render": final},
        }

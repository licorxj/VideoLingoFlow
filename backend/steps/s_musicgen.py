"""s_musicgen: AI 音乐生成能力节点（KieAI / Suno），每种能力一个节点。

节点 id 与能力映射：
  music_txt2music         文生音乐（txt2music）
  music_instrumental      纯音乐（instrumental）
  music_lyrics            歌词生成（lyrics）
  music_extend            音乐扩展（extend：按 audio_id 续写）
  music_cover             翻唱 / 风格迁移（cover：参考音频）
  music_add_instrumental  添加伴奏（add_instrumental）
  music_add_vocals        添加人声（add_vocals）
  music_separate          人声 / 分轨分离（separate）
  music_to_wav            转 WAV（to_wav：按 task_id / audio_id）
  music_upload_extend     上传本地音频并扩展（upload_extend）

产物统一落盘到 <task_dir>/cache/music，文件名格式：
  <提示词前 15 字符>_<node_id>[_<序号>].<ext>

输出：
  - audio   : 首个音频路径（歌词节点为歌词文本路径）
  - audios  : 音频路径列表（歌词 / 转码节点不产出）
  - params  : 生成参数 JSON 相对路径（含 audio_id / task_id，供下游扩展 / 分离 / 转码节点消费）

提示词来源兼容：开启「使用节点内提示词」(custom_prompt_enabled) 且内容非空时取
custom_prompt，否则取上游连线 text 输入。
"""
import os
import re
import json
import shutil
import logging
from typing import Callable, Optional

from backend.steps.base_step import BaseStep

logger = logging.getLogger(__name__)

# 面板参数 → wrapper 关键字参数（透传，空值忽略）
_PASSTHROUGH_STR = (
    "style", "title", "tags", "negative_tags", "vocal_gender",
    "persona_id", "persona_model",
)
_PASSTHROUGH_BOOL = ("instrumental", "custom_mode", "default_param_flag")
_PASSTHROUGH_NUM = ("duration", "continue_at")


def _read_input_as_text(value, task_dir: str = "") -> str:
    """解析文本输入：若是 .txt 文件路径则读内容，否则原样返回。"""
    if not value or not isinstance(value, str):
        return str(value) if value else ""
    candidate = value.strip()
    if os.path.isfile(candidate):
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return candidate
    if task_dir:
        rel = os.path.join(task_dir, candidate)
        if os.path.isfile(rel):
            try:
                with open(rel, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception:
                return candidate
    return value.strip()


def _sanitize_prefix(prompt: str) -> str:
    """取提示词前 15 字符并清洗为合法文件名片段。"""
    p = (prompt or "").replace("\r", " ").replace("\n", " ").strip()
    p = p[:15]
    p = re.sub(r'[\\/:*?"<>|\t]', "_", p)
    p = p.strip().replace(" ", "_")
    return p or "music"


def _resolve_path(value, task_dir: str) -> str:
    """把连线传入的文件路径解析为绝对路径（可能是相对 task_dir 的路径）。"""
    if not value or not isinstance(value, str):
        return ""
    raw = value.strip()
    if not raw:
        return ""
    if os.path.isabs(raw):
        return raw if os.path.exists(raw) else ""
    joined = os.path.join(task_dir, raw)
    return joined if os.path.exists(joined) else ""


def _read_upstream_json(value, task_dir: str) -> dict:
    """读取上游音乐参数 JSON（可能是路径字符串或已解析的 dict）。"""
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    path = _resolve_path(value, task_dir)
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning("AI音乐: 读取上游参数 JSON 失败: %s", e)
        return {}


def _extract_ids(obj, out=None, depth: int = 0) -> dict:
    """从接口原始返回 / 参数 JSON 中递归提取 audio_id 与 task_id。"""
    if out is None:
        out = {}
    if depth > 6:
        return out
    if isinstance(obj, list):
        for x in obj:
            _extract_ids(x, out, depth + 1)
        return out
    if not isinstance(obj, dict):
        return out
    for k, v in obj.items():
        if k in ("audio_id", "audioId") and isinstance(v, (str, int)) and str(v) and not out.get("audio_id"):
            out["audio_id"] = str(v)
        elif k in ("task_id", "taskId") and isinstance(v, (str, int)) and str(v) and not out.get("task_id"):
            out["task_id"] = str(v)
        elif isinstance(v, (dict, list)):
            _extract_ids(v, out, depth + 1)
    # 兜底：Suno 返回的曲目 id 即 audioId
    if not out.get("audio_id"):
        v = obj.get("id")
        if isinstance(v, (str, int)) and str(v):
            out["audio_id"] = str(v)
    return out


def _resolve_interface(config: dict) -> str:
    """解析音乐生成接口：节点配置 > 全局默认（musicgen.method）> 首个启用接口。"""
    from backend.musicgen.musicgen_interface_manager import get_musicgen_interface_manager

    mgr = get_musicgen_interface_manager()
    iface = (config.get("interface") or "").strip()
    if iface and mgr.get(iface):
        return iface
    try:
        from backend.config.config_manager import config as app_config
        default = app_config.get("musicgen.method")
        if default and mgr.get(default):
            return str(default)
    except Exception:
        pass
    enabled = mgr.get_enabled()
    if enabled:
        return enabled[0]["id"]
    raise RuntimeError("未配置任何音乐生成接口，请在「全局设置 → AI音乐生成」中添加并启用接口。")


class S_MusicGenBase(BaseStep):
    """AI 音乐生成基类：子类只需声明 capability 与输入要求。"""

    step_id = "musicgen_base"
    step_name = "AI 音乐生成"
    dependencies = []

    # 子类覆盖
    capability = "txt2music"
    prompt_required = True   # 是否必须有提示词
    need_audio = False       # 是否需要本地参考音频（audio 输入口）
    audio_required = False   # 参考音频是否必填
    need_upstream = False    # 是否需要上游参数 JSON（audio_id / task_id）
    text_output = False      # 输出为文本（歌词节点）
    list_output = True       # 是否输出 audios 列表

    # ── BaseStep 接口 ──────────────────────────────────────────────────────
    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        d = os.path.join(task_dir, "cache", "music")
        if not os.path.isdir(d) or not node_id:
            return False
        for f in os.listdir(d):
            if f"_{node_id}" in f:
                return True
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    # ── 执行 ──────────────────────────────────────────────────────────────
    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        config = getattr(self, "_node_config", {}) or {}
        inputs = getattr(self, "_step_inputs", {}) or {}

        # 1. 提示词：节点内自定义优先，其次连线文本输入
        prompt = ""
        if config.get("custom_prompt_enabled"):
            prompt = (config.get("custom_prompt", "") or "").strip()
        if not prompt:
            prompt = _read_input_as_text(inputs.get("text", ""), task_dir)
        if self.prompt_required and not prompt:
            raise ValueError("提示词为空：请连接文本输入，或在节点面板开启「使用节点内提示词」并填写。")

        # 2. 接口 / 模型
        iface_id = _resolve_interface(config)
        model = (config.get("model") or "").strip()

        # 3. 本地参考音频
        audio_path = ""
        if self.need_audio:
            audio_path = _resolve_path(inputs.get("audio", ""), task_dir)
            if not audio_path and self.audio_required:
                raise ValueError("缺少参考音频：请连接 audio 输入口。")

        # 4. 上游参数 JSON（audio_id / task_id）
        upstream = _read_upstream_json(inputs.get("json", ""), task_dir)
        ids = _extract_ids(upstream)
        audio_id = (config.get("audio_id") or "").strip() or ids.get("audio_id", "")
        task_id = str(upstream.get("task_id") or ids.get("task_id") or "")
        if self.need_upstream and not (audio_id or task_id):
            raise ValueError("缺少 audio_id / task_id：请连接上游音乐节点的「生成参数JSON」输出。")

        # 5. 组装 wrapper 参数
        kwargs = {}
        for key in _PASSTHROUGH_STR:
            v = config.get(key)
            if isinstance(v, str):
                v = v.strip()
            if v not in (None, ""):
                kwargs[key] = v
        for key in _PASSTHROUGH_BOOL:
            v = config.get(key)
            if v is not None:
                kwargs[key] = bool(v)
        for key in _PASSTHROUGH_NUM:
            v = config.get(key)
            if v not in (None, ""):
                try:
                    kwargs[key] = int(v)
                except (TypeError, ValueError):
                    pass
        if audio_path:
            kwargs["audio_path"] = audio_path
        if audio_id:
            kwargs["audio_id"] = audio_id
        if task_id:
            kwargs["task_id"] = task_id
        stem_type = (config.get("stem_type") or "").strip()
        if stem_type:
            kwargs["stem_type"] = stem_type
        poll_timeout = config.get("poll_timeout")
        if poll_timeout:
            try:
                kwargs["poll_timeout"] = int(poll_timeout)
            except (TypeError, ValueError):
                pass

        if callback:
            callback(10, f"AI音乐 准备中（{self.capability} / {model or '默认模型'}）...")

        # 6. 调用工厂执行
        from backend.musicgen.musicgen_factory import get_musicgen_engine

        engine = get_musicgen_engine(iface_id)
        if engine is None:
            raise RuntimeError(f"音乐生成接口 '{iface_id}' 不可用，请在「全局设置 → AI音乐生成」中启用。")

        temp_dir = os.path.join(task_dir, "cache", "_musicgen_temp", node_id)
        cache_dir = os.path.join(task_dir, "cache", "music")
        os.makedirs(temp_dir, exist_ok=True)
        os.makedirs(cache_dir, exist_ok=True)

        try:
            if callback:
                callback(30, "已提交生成任务，等待接口返回（音乐生成较慢，请耐心等待）...")
            paths = engine.generate(
                prompt=prompt,
                output_dir=temp_dir,
                model=model,
                mode=self.capability,
                api_key="",
                **kwargs,
            )
        except Exception as e:
            raise RuntimeError(f"AI音乐生成失败: {e}") from e

        paths = [p for p in (paths or []) if p and os.path.exists(p)]
        if not paths:
            raise RuntimeError("AI音乐生成未返回任何产物（请检查接口 / 模型 / 参数或 API Key）。")

        # 7. 产物落盘（文件名带 node_id，避免同类型多实例互相覆盖）
        prefix = _sanitize_prefix(prompt or self.capability)
        saved = []
        for i, src in enumerate(paths):
            ext = os.path.splitext(src)[1] or ".mp3"
            name = f"{prefix}_{node_id}_{i + 1}{ext}" if len(paths) > 1 else f"{prefix}_{node_id}{ext}"
            dest = os.path.join(cache_dir, name)
            shutil.copy2(src, dest)
            saved.append(os.path.join("cache", "music", name))

        # 8. 生成参数 JSON（含 audio_id / task_id，供下游扩展 / 分离 / 转码消费）
        result_ids = {}
        meta_path = os.path.join(temp_dir, "_musicgen_result.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    result_ids = _extract_ids(json.load(f))
            except Exception:
                result_ids = {}
        params = {
            "node_id": node_id,
            "interface": iface_id,
            "mode": self.capability,
            "model": model,
            "prompt": prompt,
            "audio_id": result_ids.get("audio_id") or audio_id or "",
            "task_id": result_ids.get("task_id") or task_id or "",
            "saved": saved,
            "created_at": __import__("datetime").datetime.now().isoformat(),
        }
        params_dir = os.path.join(task_dir, "cache", "musicgen")
        os.makedirs(params_dir, exist_ok=True)
        params_rel = os.path.join("cache", "musicgen", f"{node_id}_params.json")
        with open(os.path.join(task_dir, params_rel), "w", encoding="utf-8") as f:
            json.dump(params, f, ensure_ascii=False, indent=2)

        shutil.rmtree(temp_dir, ignore_errors=True)

        if callback:
            callback(100, f"已保存 {len(saved)} 个产物到 cache/music")

        # 9. 输出端口（key 与 builtin_node_types 的 outputs 端口 id 一一对应）
        outputs = {"params": params_rel}
        if self.text_output:
            outputs["text"] = saved[0]
        else:
            outputs["audio"] = saved[0]
            if self.list_output:
                outputs["audios"] = saved

        return {
            "artifacts": list(saved) + [params_rel],
            "outputs": outputs,
        }


# ─────────────────────────────────────────────────────────────────────────────
# 各能力节点
# ─────────────────────────────────────────────────────────────────────────────
class S_MusicTxt2Music(S_MusicGenBase):
    step_id = "music_txt2music"
    step_name = "AI音乐-文生音乐"
    capability = "txt2music"
    prompt_required = True


class S_MusicInstrumental(S_MusicGenBase):
    step_id = "music_instrumental"
    step_name = "AI音乐-纯音乐"
    capability = "instrumental"
    prompt_required = True


class S_MusicLyrics(S_MusicGenBase):
    step_id = "music_lyrics"
    step_name = "AI音乐-歌词生成"
    capability = "lyrics"
    prompt_required = True
    text_output = True
    list_output = False


class S_MusicExtend(S_MusicGenBase):
    step_id = "music_extend"
    step_name = "AI音乐-音乐扩展"
    capability = "extend"
    prompt_required = False
    need_upstream = True


class S_MusicCover(S_MusicGenBase):
    step_id = "music_cover"
    step_name = "AI音乐-翻唱/风格迁移"
    capability = "cover"
    prompt_required = True
    need_audio = True
    audio_required = True


class S_MusicAddInstrumental(S_MusicGenBase):
    step_id = "music_add_instrumental"
    step_name = "AI音乐-添加伴奏"
    capability = "add_instrumental"
    prompt_required = False
    need_audio = True
    audio_required = True


class S_MusicAddVocals(S_MusicGenBase):
    step_id = "music_add_vocals"
    step_name = "AI音乐-添加人声"
    capability = "add_vocals"
    prompt_required = True
    need_audio = True
    audio_required = True


class S_MusicSeparate(S_MusicGenBase):
    step_id = "music_separate"
    step_name = "AI音乐-人声分离"
    capability = "separate"
    prompt_required = False
    need_audio = True
    audio_required = False


class S_MusicToWav(S_MusicGenBase):
    step_id = "music_to_wav"
    step_name = "AI音乐-转WAV"
    capability = "to_wav"
    prompt_required = False
    need_upstream = True
    list_output = False


class S_MusicUploadExtend(S_MusicGenBase):
    step_id = "music_upload_extend"
    step_name = "AI音乐-上传并扩展"
    capability = "upload_extend"
    prompt_required = False
    need_audio = True
    audio_required = True

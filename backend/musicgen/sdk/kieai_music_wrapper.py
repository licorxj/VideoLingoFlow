"""KieAI Music (Suno) SDK wrapper — 与 kie.ai 官方 ai-music-api 完全对齐。

统一调用模式（docs.kie.ai/suno-api）：
  提交  POST https://api.kie.ai/api/v1/jobs/createTask
        body {"model": "ai-music-api/<op>", "input": {...snake_case}}
  轮询  GET  https://api.kie.ai/api/v1/jobs/recordInfo?taskId=
        曲目位于 resultJson.resultObject.data[]（id / audio_url / ...）

每个模式对应一个官方操作（经 backend/kieai_sdk/kieai/suno.py 的
SunoMusicClient 提交，提交前按官方规格校验参数）：
    txt2music        -> ai-music-api/generate               (custom_mode=False)
    instrumental     -> ai-music-api/generate               (instrumental=True)
    lyrics           -> ai-music-api/generate-lyrics
    extend           -> ai-music-api/extend                 (audio_id)
    cover            -> ai-music-api/upload-and-cover-audio (upload_url 或 task_id+audio_id)
    add_instrumental -> ai-music-api/add-instrumental       (upload_url)
    add_vocals       -> ai-music-api/add-vocals             (upload_url)
    separate         -> ai-music-api/separate-vocals        (task_id+audio_id 或 audio_url)
    to_wav           -> ai-music-api/convert-to-wav-format  (task_id + audio_id)
    upload_extend    -> ai-music-api/upload-and-extend-audio(upload_url)
    persona          -> ai-music-api/generate-persona       (同步，返回 persona_id)
    replace_section  -> ai-music-api/replace-section        (task_id+audio_id 或 upload_url+model)
    music_video      -> ai-music-api/create-music-video     (task_id+audio_id -> mp4)
    timestamped      -> ai-music-api/timeStamped-lyrics     (逐词时间戳歌词 JSON)
    sounds           -> ai-music-api/sounds                 (音效，V6_WILD)
    mashup           -> ai-music-api/mashup                 (两段音频混音)
    boost_style      -> ai-music-api/boost-music-style      (风格增强，结果串回 style)
    cover_art        -> ai-music-api/cover-generate         (任务封面图 x2)
    voice_clone      -> Voice 三步链 validation-phrase -> create-voice -> check-voice
    midi             -> ai-music-api/generate-midi-from-audio (分离任务 -> 音符 JSON)
    recovery         -> ai-music-api/suno-recovery-audio    (恢复历史音频链接)

generate() 返回本地文件路径列表（生成类接口通常 2 个变体；文本类模式为
歌词/风格/MIDI JSON 文件），并把 {task_id, tracks, persona_id, voice_id, ...}
落盘到 <output_dir>/_musicgen_result.json 供下游节点链式消费。
"""
import os
import json
import logging
import traceback

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "V6"

# mode -> 官方 ai-music-api 操作（SunoMusicClient.submit 的 op 名）
MODE_OPS = {
    "txt2music": "generate",
    "instrumental": "generate",
    "lyrics": "generate_lyrics",
    "extend": "extend",
    "cover": "upload_and_cover",
    "add_instrumental": "add_instrumental",
    "add_vocals": "add_vocals",
    "separate": "separate_vocals",
    "to_wav": "convert_to_wav",
    "upload_extend": "upload_and_extend",
    "persona": "generate_persona",
    "replace_section": "replace_section",
    "music_video": "create_music_video",
    "timestamped": "timestamped_lyrics",
    "sounds": "sounds",
    "mashup": "mashup",
    "boost_style": "boost_style",
    "cover_art": "cover_generate",
    "midi": "generate_midi",
    "recovery": "recovery_audio",
    # voice_clone 为三步链（validation-phrase -> create-voice -> check-voice），无单一 op
}

# 专用轮询通道：mode -> wait 变体（默认统一 recordInfo 轮询）
MODE_POLL = {
    "midi": "midi",          # 音符另查 /api/v1/midi/record-info
    "recovery": "recovery",  # 专用 recovery record-info（code 201/200/500）
}

# separate 旧 stem_type 值 -> 官方 type 枚举
_SEPARATE_TYPE_MAP = {
    "all": "separate_vocal",
    "vocals": "separate_vocal",
    "vocal": "separate_vocal",
    "instrumental": "separate_vocal",
    "separate_vocal": "separate_vocal",
    "split_stem": "split_stem",
    "split_stem_advanced": "split_stem_advanced",
}


def _to_int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _to_float(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _suno_client(api_key: str, poll_timeout: int):
    """构造 SunoMusicClient（三级 key 回退在 SDK 内部完成）。"""
    try:
        from kieai import SunoMusicClient
    except ImportError:
        from backend.kieai_sdk.kieai import SunoMusicClient
    music = SunoMusicClient(api_key=api_key or None)
    interval = max(getattr(music.client, "poll_interval", 3), 0.1)
    music.client.max_poll = max(1, int(poll_timeout / interval))
    return music


def _build_input(mode: str, op: str, prompt: str, model: str, kwargs: dict) -> dict:
    """按官方 input 规格组装参数（snake_case；校验由 validate_params 完成）。

    custom_mode 默认 False（官方推荐：非自定义模式下 prompt 是创意描述）；
    仅在节点面板显式开启「自定义模式」时按 custom 语义传参（prompt 严格作为歌词）。
    """
    custom = bool(kwargs.get("custom_mode", False))
    instrumental = bool(kwargs.get("instrumental", False)) or mode == "instrumental"
    p: dict = {}

    def add(name, value, transform=None):
        if value is not None and value != "":
            p[name] = transform(value) if transform else value

    if op == "generate":
        p["custom_mode"] = custom
        p["instrumental"] = instrumental
        p["model"] = model
        add("prompt", prompt)
        add("lyrics", kwargs.get("lyrics"))
        add("style", kwargs.get("style"))
        add("title", kwargs.get("title"))
        if custom:
            add("negative_tags", kwargs.get("negative_tags"))
            add("vocal_gender", kwargs.get("vocal_gender"))
            add("style_weight", kwargs.get("style_weight"), _to_float)
            add("weirdness_constraint", kwargs.get("weirdness_constraint"), _to_float)
            add("audio_weight", kwargs.get("audio_weight"), _to_float)
            add("variety", kwargs.get("variety"), _to_int)
            add("duration", kwargs.get("duration"), _to_int)
            add("persona_id", kwargs.get("persona_id"))
            add("persona_model", kwargs.get("persona_model"))
        else:
            # 官方约束：非自定义模式不要传 duration / vocal_gender / 权重类参数
            add("negative_tags", kwargs.get("negative_tags"))

    elif op == "generate_lyrics":
        p["prompt"] = prompt

    elif op == "extend":
        p["model"] = model
        audio_id = kwargs.get("audio_id") or kwargs.get("audioId")
        task_id = kwargs.get("task_id") or kwargs.get("taskId")
        if audio_id:
            p["audio_id"] = audio_id
        elif task_id:
            p["task_id"] = task_id
            p["_needs_audio_id"] = True
        else:
            raise ValueError("extend 模式需要 Task ID 或 audio_id（连接上游音乐节点输出）")
        add("prompt", prompt)
        add("lyrics", kwargs.get("lyrics"))
        add("style", kwargs.get("style"))
        add("title", kwargs.get("title"))
        add("negative_tags", kwargs.get("negative_tags"))
        add("continue_at", kwargs.get("continue_at", kwargs.get("continueAt")), _to_float)
        add("persona_id", kwargs.get("persona_id"))
        add("persona_model", kwargs.get("persona_model"))
        if instrumental:
            p["instrumental"] = True
        else:
            add("vocal_gender", kwargs.get("vocal_gender"))
            add("style_weight", kwargs.get("style_weight"), _to_float)
            add("weirdness_constraint", kwargs.get("weirdness_constraint"), _to_float)
            add("audio_weight", kwargs.get("audio_weight"), _to_float)

    elif op == "upload_and_cover":
        p["model"] = model
        p["instrumental"] = instrumental
        task_id = kwargs.get("task_id") or kwargs.get("taskId")
        audio_id = kwargs.get("audio_id") or kwargs.get("audioId")
        upload_url = kwargs.get("upload_url") or kwargs.get("uploadUrl")
        local = kwargs.get("audio_path") or kwargs.get("audio_file") or kwargs.get("ref_audio")
        if upload_url:
            p["upload_url"] = upload_url
        elif local and os.path.exists(local):
            p["audio_path"] = local  # 标记，稍后上传（见 _finalize_input）
        elif task_id:
            p["task_id"] = task_id
            if audio_id:
                p["audio_id"] = audio_id
            else:
                p["_needs_audio_id"] = True
        else:
            raise ValueError("cover 模式需要提供 参考音频 / Task ID / upload_url 之一")
        add("prompt", prompt)
        add("lyrics", kwargs.get("lyrics"))
        add("style", kwargs.get("style"))
        add("title", kwargs.get("title"))
        add("negative_tags", kwargs.get("negative_tags"))
        if not instrumental:
            add("vocal_gender", kwargs.get("vocal_gender"))
            add("style_weight", kwargs.get("style_weight"), _to_float)
            add("weirdness_constraint", kwargs.get("weirdness_constraint"), _to_float)
            add("audio_weight", kwargs.get("audio_weight"), _to_float)
        add("variety", kwargs.get("variety"), _to_int)
        add("duration", kwargs.get("duration"), _to_int)
        add("persona_id", kwargs.get("persona_id"))
        add("persona_model", kwargs.get("persona_model"))

    elif op == "add_instrumental":
        p["model"] = model or _DEFAULT_MODEL
        add("title", kwargs.get("title") or (prompt[:60] if prompt else "") or "Instrumental")
        add("tags", kwargs.get("tags") or kwargs.get("style") or "instrumental")
        p["negative_tags"] = kwargs.get("negative_tags") or ""
        add("lyrics", kwargs.get("lyrics"))
        add("vocal_gender", kwargs.get("vocal_gender"))
        add("style_weight", kwargs.get("style_weight"), _to_float)
        add("weirdness_constraint", kwargs.get("weirdness_constraint"), _to_float)
        add("audio_weight", kwargs.get("audio_weight"), _to_float)
        add("variety", kwargs.get("variety"), _to_int)
        p["_needs_upload"] = True  # upload_url 必填

    elif op == "add_vocals":
        p["model"] = model or _DEFAULT_MODEL
        add("title", kwargs.get("title") or (prompt[:60] if prompt else "") or "Vocals")
        add("style", kwargs.get("style") or "pop")
        p["negative_tags"] = kwargs.get("negative_tags") or ""
        add("prompt", prompt)
        add("lyrics", kwargs.get("lyrics"))
        add("vocal_gender", kwargs.get("vocal_gender"))
        add("style_weight", kwargs.get("style_weight"), _to_float)
        add("weirdness_constraint", kwargs.get("weirdness_constraint"), _to_float)
        add("audio_weight", kwargs.get("audio_weight"), _to_float)
        add("variety", kwargs.get("variety"), _to_int)
        p["_needs_upload"] = True

    elif op == "separate_vocals":
        stem_type = (kwargs.get("stem_type") or kwargs.get("type") or "separate_vocal").strip()
        p["type"] = _SEPARATE_TYPE_MAP.get(stem_type, stem_type)
        if p["type"] == "split_stem_advanced":
            add("stem_name", kwargs.get("stem_name"))
        task_id = kwargs.get("task_id") or kwargs.get("taskId")
        audio_id = kwargs.get("audio_id") or kwargs.get("audioId")
        audio_url = kwargs.get("audio_url") or kwargs.get("audioUrl")
        local = kwargs.get("audio_path") or kwargs.get("audio_file") or kwargs.get("ref_audio")
        if task_id and audio_id:
            p["task_id"] = task_id
            p["audio_id"] = audio_id
        elif audio_url:
            p["audio_url"] = audio_url
        elif local and os.path.exists(local):
            p["audio_path"] = local
        else:
            raise ValueError("separate 模式需要提供 task_id+audio_id / audio_url / 本地音频之一")

    elif op == "convert_to_wav":
        task_id = kwargs.get("task_id") or kwargs.get("taskId")
        audio_id = kwargs.get("audio_id") or kwargs.get("audioId")
        if not (task_id or audio_id):
            raise ValueError("to_wav 模式需要 Task ID 或 audio_id（请连接上游音乐节点的 Task ID / 参数 JSON）")
        p["task_id"] = task_id or ""
        if audio_id:
            p["audio_id"] = audio_id
        else:
            p["_needs_audio_id"] = True  # 仅 Task ID 时由 _finalize_input 反查

    elif op == "upload_and_extend":
        p["model"] = model
        add("prompt", prompt)
        add("lyrics", kwargs.get("lyrics"))
        add("style", kwargs.get("style"))
        add("title", kwargs.get("title"))
        add("negative_tags", kwargs.get("negative_tags"))
        add("continue_at", kwargs.get("continue_at", kwargs.get("continueAt")), _to_float)
        add("persona_id", kwargs.get("persona_id"))
        add("persona_model", kwargs.get("persona_model"))
        if instrumental:
            p["instrumental"] = True
        else:
            add("vocal_gender", kwargs.get("vocal_gender"))
            add("style_weight", kwargs.get("style_weight"), _to_float)
            add("weirdness_constraint", kwargs.get("weirdness_constraint"), _to_float)
            add("audio_weight", kwargs.get("audio_weight"), _to_float)
        p["_needs_upload"] = True

    elif op == "generate_persona":
        # 同步端点：required task_id + audio_id + name + description
        p["task_id"] = kwargs.get("task_id") or kwargs.get("taskId") or ""
        audio_id = kwargs.get("audio_id") or kwargs.get("audioId")
        if audio_id:
            p["audio_id"] = audio_id
        elif p["task_id"]:
            p["_needs_audio_id"] = True  # 仅 Task ID 时反查
        else:
            raise ValueError("Persona 模式需要 Task ID 或 audio_id（连接上游音乐节点输出）")
        add("name", kwargs.get("name") or (prompt[:30] if prompt else "") or "Persona")
        add("description", kwargs.get("description"))
        if not p.get("description"):
            raise ValueError("Persona 模式需要填写「人物描述」")
        add("style", kwargs.get("style"))
        add("vocal_start", kwargs.get("vocal_start"), _to_int)
        add("vocal_end", kwargs.get("vocal_end"), _to_int)

    elif op == "replace_section":
        # xor: task_id+audio_id 或 upload_url+model；required: prompt/tags/title/infill/full_lyrics
        if not model:
            raise ValueError("replace_section 模式需要模型（上传音频来源时必填）")
        task_id = kwargs.get("task_id") or kwargs.get("taskId")
        audio_id = kwargs.get("audio_id") or kwargs.get("audioId")
        upload_url = kwargs.get("upload_url") or kwargs.get("uploadUrl")
        local = kwargs.get("audio_path") or kwargs.get("audio_file") or kwargs.get("ref_audio")
        if local and os.path.exists(local):
            p["audio_path"] = local
            p["model"] = model
        elif upload_url:
            p["upload_url"] = upload_url
            p["model"] = model
        elif task_id:
            p["task_id"] = task_id
            if audio_id:
                p["audio_id"] = audio_id
            else:
                p["_needs_audio_id"] = True
        else:
            raise ValueError("replace_section 模式需要 Task ID / 待替换音频 / upload_url 之一")
        add("prompt", prompt)
        add("tags", kwargs.get("tags"))
        add("title", kwargs.get("title"))
        add("full_lyrics", kwargs.get("full_lyrics"))
        add("lyrics", kwargs.get("section_lyrics") or kwargs.get("lyrics"))
        add("infill_start_s", kwargs.get("infill_start_s"), _to_float)
        add("infill_end_s", kwargs.get("infill_end_s"), _to_float)
        add("negative_tags", kwargs.get("negative_tags"))
        add("vocal_gender", kwargs.get("vocal_gender"))
        add("style_weight", kwargs.get("style_weight"), _to_float)
        add("weirdness_constraint", kwargs.get("weirdness_constraint"), _to_float)
        add("audio_weight", kwargs.get("audio_weight"), _to_float)
        add("variety", kwargs.get("variety"), _to_int)
        add("persona_id", kwargs.get("persona_id"))
        add("persona_model", kwargs.get("persona_model"))

    elif op == "create_music_video":
        p["task_id"] = kwargs.get("task_id") or kwargs.get("taskId") or ""
        audio_id = kwargs.get("audio_id") or kwargs.get("audioId")
        if audio_id:
            p["audio_id"] = audio_id
        elif p["task_id"]:
            p["_needs_audio_id"] = True
        else:
            raise ValueError("音乐视频模式需要 Task ID（连接上游音乐节点输出）")
        add("author", kwargs.get("author"))
        add("domain_name", kwargs.get("domain_name"))

    elif op == "timestamped_lyrics":
        p["task_id"] = kwargs.get("task_id") or kwargs.get("taskId") or ""
        audio_id = kwargs.get("audio_id") or kwargs.get("audioId")
        if audio_id:
            p["audio_id"] = audio_id
        elif p["task_id"]:
            p["_needs_audio_id"] = True
        else:
            raise ValueError("时间戳歌词模式需要 Task ID（连接上游音乐节点输出）")

    elif op == "sounds":
        p["prompt"] = prompt
        p["model"] = model  # 官方枚举 V5/V5_5/V6/V6_WILD/V6_MINI（推荐 V6_WILD）
        add("sound_loop", kwargs.get("sound_loop"))
        add("sound_tempo", kwargs.get("sound_tempo"), _to_int)
        add("sound_key", kwargs.get("sound_key"))
        add("grab_lyrics", kwargs.get("grab_lyrics"))

    elif op == "mashup":
        # upload_url_list 恰好 2 个：audio1/audio2 两个输入口（本地自动上传）
        if not model:
            raise ValueError("mashup 模式需要模型")
        p["model"] = model
        u1 = kwargs.get("upload_url") or kwargs.get("audio_url") or ""
        u2 = kwargs.get("upload_url2") or kwargs.get("audio_url2") or ""
        l1 = kwargs.get("audio_path") or ""
        l2 = kwargs.get("audio_path2") or ""
        seg1 = u1 if u1 else (f"local:{l1}" if l1 and os.path.exists(l1) else "")
        seg2 = u2 if u2 else (f"local:{l2}" if l2 and os.path.exists(l2) else "")
        if not (seg1 and seg2):
            raise ValueError("混音模式需要恰好 2 段音频（连接 audio1 + audio2 两个输入口）")
        p["_mashup_inputs"] = [seg1, seg2]  # _finalize_input 中上传/展开
        add("style", kwargs.get("style") or prompt)
        add("title", kwargs.get("title") or (prompt[:60] if prompt else "") or "Mashup")
        add("prompt", kwargs.get("mashup_prompt"))
        add("lyrics", kwargs.get("lyrics"))
        add("vocal_gender", kwargs.get("vocal_gender"))
        add("style_weight", kwargs.get("style_weight"), _to_float)
        add("weirdness_constraint", kwargs.get("weirdness_constraint"), _to_float)
        add("audio_weight", kwargs.get("audio_weight"), _to_float)
        add("variety", kwargs.get("variety"), _to_int)
        add("duration", kwargs.get("duration"), _to_int)
        add("persona_id", kwargs.get("persona_id"))
        add("persona_model", kwargs.get("persona_model"))

    elif op == "boost_style":
        p["content"] = prompt or kwargs.get("content") or ""

    elif op == "cover_generate":
        p["task_id"] = kwargs.get("task_id") or kwargs.get("taskId") or ""
        if not p["task_id"]:
            raise ValueError("封面生成模式需要 Task ID（连接上游音乐节点输出）")

    elif op == "generate_midi":
        # required: 分离任务 task_id；audio_id 为可选的指定 stem id（勿自动反查）
        p["task_id"] = kwargs.get("task_id") or kwargs.get("taskId") or ""
        if not p["task_id"]:
            raise ValueError("MIDI 模式需要分离任务的 Task ID（连接「人声分离」节点输出）")
        add("audio_id", kwargs.get("audio_id"))

    elif op == "recovery_audio":
        p["task_id"] = kwargs.get("task_id") or kwargs.get("taskId") or ""
        if not p["task_id"]:
            raise ValueError("音频恢复模式需要原任务的 Task ID")

    return p


async def _resolve_upload(music, local_path: str) -> str:
    """把本地音频上传为可公开访问的 URL（官方 input 需要 URL）。"""
    import base64
    with open(local_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    fn = os.path.basename(local_path)
    r = await music.client.upload(method="base64", base64Data=b64,
                                  uploadPath="audios", fileName=fn)
    if isinstance(r, dict):
        u = r.get("downloadUrl") or r.get("url") or r.get("data", {}).get("downloadUrl")
        if u:
            return u
    raise ValueError(f"音频上传失败，未返回 URL: {r}")


async def _resolve_audio_id(music, task_id: str) -> str:
    """只连了上游 Task ID 时，反查该任务音轨拿 audio_id（免去用户手填）。"""
    if not task_id:
        return ""
    try:
        from kieai import RECORD_INFO_URL
    except ImportError:
        from backend.kieai_sdk.kieai import RECORD_INFO_URL
    try:
        last = await music.client._get_json_retry(
            f"{RECORD_INFO_URL}?taskId={task_id}")
        from kieai import SunoMusicClient
        parsed = SunoMusicClient._parse_record(last.get("data") or {}, task_id)
        tracks = parsed.get("tracks") or []
        for t in tracks:
            if isinstance(t, dict) and t.get("id"):
                return str(t["id"])
        # 分离任务的源曲目信息在 resultObject.origin_data
        obj = (parsed.get("raw") or {}).get("resultObject") or {}
        for t in (obj.get("origin_data") or []):
            if isinstance(t, dict) and t.get("id"):
                return str(t["id"])
    except Exception as e:
        logger.warning("反查 Task ID %s 的 audio_id 失败: %s", task_id, e)
    return ""


async def _finalize_input(music, input_body: dict) -> dict:
    """收尾处理：本地文件上传为 URL、仅连 Task ID 时反查 audio_id、混音 URL 列表展开。"""
    out = dict(input_body)
    mashup_inputs = out.pop("_mashup_inputs", None)
    if mashup_inputs is not None:
        resolved: list = []
        for item in mashup_inputs:
            if item.startswith("local:"):
                resolved.append(await _resolve_upload(music, item[len("local:"):]))
            else:
                resolved.append(item)
        out["upload_url_list"] = resolved
    local = out.pop("audio_path", None)
    if local and "upload_url" not in out:
        out["upload_url"] = await _resolve_upload(music, local)
    needs_audio_id = out.pop("_needs_audio_id", False)
    if needs_audio_id:
        resolved = await _resolve_audio_id(music, out.get("task_id", ""))
        if resolved:
            out["audio_id"] = resolved
        else:
            raise ValueError(
                f"无法从 Task ID '{out.get('task_id')}' 获取 audio_id，"
                "请连接上游音乐节点的「生成参数JSON」或手工填写 audio_id")
    if out.pop("_needs_upload", False) and not out.get("upload_url"):
        raise ValueError("该模式需要提供音频（audio 输入口）或 upload_url")
    return out


_LYRICS_KEYS = ("lyrics", "lyric", "text", "content")


def _extract_lyrics(obj, depth: int = 0) -> str:
    """从接口返回结构中递归提取歌词文本。"""
    if depth > 6:
        return ""
    if isinstance(obj, str):
        return obj.strip()
    if isinstance(obj, list):
        parts = [_extract_lyrics(x, depth + 1) for x in obj]
        return "\n".join([p for p in parts if p]).strip()
    if isinstance(obj, dict):
        for k in _LYRICS_KEYS:
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        for v in obj.values():
            got = _extract_lyrics(v, depth + 1)
            if got:
                return got
    return ""


def _ext_from_url(url: str, default: str = ".mp3") -> str:
    path = (url or "").split("?")[0]
    if "." in path.rsplit("/", 1)[-1]:
        return "." + path.rsplit(".", 1)[-1].lower()
    return default


def _find_value(obj, keys, depth: int = 0):
    """在返回结构中递归查找第一个命中的 key 的值。"""
    if depth > 6:
        return None
    if isinstance(obj, dict):
        for k in keys:
            v = obj.get(k)
            if v not in (None, "", [], {}):
                return v
        for v in obj.values():
            got = _find_value(v, keys, depth + 1)
            if got is not None:
                return got
    elif isinstance(obj, list):
        for x in obj:
            got = _find_value(x, keys, depth + 1)
            if got is not None:
                return got
    return None


def _collect_urls(obj, out=None) -> list:
    """递归收集结构中所有 http(s) URL（恢复音频的返回结构不固定）。"""
    if out is None:
        out = []
    if isinstance(obj, str):
        if obj.startswith("http"):
            out.append(obj)
    elif isinstance(obj, list):
        for x in obj:
            _collect_urls(x, out)
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_urls(v, out)
    return out


def _save_text(output_dir: str, name: str, content) -> str:
    """落盘文本 / JSON 产物，返回文件路径。"""
    p = os.path.join(output_dir, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content if isinstance(content, str)
                else json.dumps(content, ensure_ascii=False, indent=2, default=str))
    return p


async def _voice_clone_flow(music, kwargs: dict) -> tuple:
    """Suno Voice 三步链（全免费）：validation-phrase -> create-voice -> check-voice。

    voice_id = 验证短语任务的 taskId（可传回 generate/extend 的 persona_model）。
    verify_url（用户朗读验证短语的录音）留空时复用人声样本。
    返回 (meta, [])。
    """
    voice_url = kwargs.get("upload_url") or kwargs.get("audio_url") or ""
    local = kwargs.get("audio_path") or ""
    if not voice_url and local and os.path.exists(local):
        voice_url = await _resolve_upload(music, local)
    if not voice_url:
        raise ValueError("音色克隆需要提供人声样本（audio 输入口）")
    start = _to_int(kwargs.get("vocal_start_s"), 0) or 0
    end = _to_int(kwargs.get("vocal_end_s"), 0) or 0
    if end <= start:
        raise ValueError("人声片段终点(vocal_end_s)必须大于起点(vocal_start_s)")

    vparams = {"voice_url": voice_url, "vocal_start_s": start, "vocal_end_s": end}
    if kwargs.get("language"):
        vparams["language"] = kwargs["language"]
    logger.info("KieAI music: voice_clone step1 validation-phrase")
    vsub = await music.submit("voice_validate", **vparams)
    if vsub.get("sync"):
        raise RuntimeError("validation-phrase 应为异步任务，未返回 taskId")
    voice_id = vsub["taskId"]
    await music.wait(voice_id)

    cparams = {"task_id": voice_id,
               "verify_url": kwargs.get("verify_url") or voice_url}
    for k in ("voice_name", "description", "style", "singer_skill_level"):
        if kwargs.get(k):
            cparams[k] = kwargs[k]
    logger.info("KieAI music: voice_clone step2 create-voice")
    csub = await music.submit("voice_create", **cparams)
    if csub.get("sync"):
        raise RuntimeError("create-voice 应为异步任务，未返回 taskId")
    create_task_id = csub["taskId"]
    await music.wait(create_task_id)

    logger.info("KieAI music: voice_clone step3 check-voice")
    chk = await music.submit("voice_check", task_id=create_task_id)
    payload = {k: v for k, v in chk.items() if k != "sync"}
    is_available = _find_value(payload, ("isAvailable", "is_available"))
    meta = {"voice_id": voice_id, "voice_create_task_id": create_task_id,
            "is_available": is_available, "raw": payload}
    return meta, []


async def generate(
    prompt: str,
    output_dir: str,
    model: str = "",
    mode: str = "txt2music",
    api_key: str = "",
    **kwargs,
) -> list:
    """提交 Suno 任务并轮询到完成，下载全部产物到 output_dir。

    返回本地文件路径列表（生成类通常 2 个变体；文本类模式为歌词/风格/MIDI JSON）。
    原始结果（task_id / tracks / persona_id / voice_id 等）落盘
    _musicgen_result.json 供下游串联。失败时抛出异常。
    """
    poll_timeout = _to_int(kwargs.get("poll_timeout"), 600) or 600
    os.makedirs(output_dir, exist_ok=True)

    # Voice 三步链（无单一 op）
    if mode == "voice_clone":
        music = _suno_client(api_key, poll_timeout)
        try:
            async with music:
                meta, local_paths = await _voice_clone_flow(music, kwargs)
                _write_meta(output_dir, meta)
                return local_paths
        except Exception as e:
            logger.error("KieAI music voice_clone failed: %s", e)
            logger.error(traceback.format_exc())
            raise

    op = MODE_OPS.get(mode)
    if not op:
        raise ValueError(f"不支持的音乐模式 '{mode}'，可选: {sorted(MODE_OPS)}")
    poll_kind = MODE_POLL.get(mode, "")
    model = model or ("V6_WILD" if mode == "sounds" else _DEFAULT_MODEL)

    music = _suno_client(api_key, poll_timeout)
    try:
        async with music:
            input_body = _build_input(mode, op, prompt, model, kwargs)
            input_body = await _finalize_input(music, input_body)
            logger.info(
                "KieAI music: mode=%s op=%s model=%s input=%s",
                mode, op, model,
                {k: ("<url>" if "url" in k and isinstance(v, str) else v)
                 for k, v in input_body.items()},
            )
            sub = await music.submit(op, **input_body)
            meta: dict = {"mode": mode, "op": op, "model": model}
            local_paths: list = []

            if sub.get("sync"):
                # 同步端点（generate-persona / check-voice）：直接携带最终结果
                payload = {k: v for k, v in sub.items() if k != "sync"}
                meta["sync_result"] = payload
                if op == "generate_persona":
                    pid = _find_value(payload, ("persona_id", "personaId"))
                    if not pid:
                        raise RuntimeError(
                            f"Persona 生成完成但未返回 persona_id: {payload}")
                    meta["persona_id"] = pid
                _write_meta(output_dir, meta)
                return []

            task_id = sub["taskId"]
            meta["task_id"] = meta["taskId"] = task_id

            if poll_kind == "recovery":
                # 恢复音频：专用轮询端点（code 201 运行中 / 200 完成 / 500 失败）
                entries = await music.wait_recovery(task_id)
                meta["recovery"] = entries
                _write_meta(output_dir, meta)
                for i, url in enumerate(_collect_urls(entries)):
                    dest = os.path.join(output_dir,
                                        f"{i + 1}_recovered{_ext_from_url(url)}")
                    await music.client._download_file(url, dest)
                    local_paths.append(dest)
                if not local_paths:
                    raise RuntimeError(f"恢复任务 {task_id} 完成但未返回可下载音频")
                return local_paths

            if poll_kind == "midi":
                # MIDI：先轮询任务完成，音符另查 /api/v1/midi/record-info
                done = await music.wait_midi(task_id)
            else:
                done = await music.wait(task_id)

            tracks = done.get("tracks") or []
            raw = done.get("raw") or {}
            meta["tracks"] = tracks
            meta["result"] = done.get("result")
            try:
                meta["raw"] = raw if len(json.dumps(raw, default=str)) < 200000 else {}
            except Exception:
                meta["raw"] = {}

            if poll_kind == "midi":
                notes = done.get("midi")
                if not notes:
                    raise RuntimeError(f"MIDI 任务 {task_id} 完成但未返回音符数据")
                meta["midi"] = notes
                _write_meta(output_dir, meta)
                return [_save_text(output_dir, "midi_notes.json", notes)]

            if op == "timestamped_lyrics":
                obj = raw.get("resultObject") or {}
                if not obj:
                    raise RuntimeError(
                        f"时间戳歌词任务 {task_id} 完成但未返回数据")
                _write_meta(output_dir, meta)
                return [_save_text(output_dir, "timestamped_lyrics.json", obj)]

            if op == "boost_style":
                obj = raw.get("resultObject") or {}
                style = _find_value(obj or raw, ("style", "content", "result"))
                if not style:
                    raise RuntimeError(
                        f"风格增强任务 {task_id} 完成但未返回结果")
                _write_meta(output_dir, meta)
                return [_save_text(output_dir, "boosted_style.txt", str(style))]

            # 音频 / 图像 / 视频类：优先 tracks 里的音频 URL，其次 resultUrls
            for i, track in enumerate(tracks):
                url = (track.get("audio_url") or track.get("audioUrl")
                       or track.get("stream_audio_url") or "")
                if not url:
                    continue
                tid = str(track.get("id") or f"{i + 1}")[:8]
                dest = os.path.join(output_dir, f"{i + 1}_{tid}{_ext_from_url(url)}")
                await music.client._download_file(url, dest)
                local_paths.append(dest)
            if not local_paths:
                for i, url in enumerate(done.get("resultUrls") or []):
                    dest = os.path.join(output_dir,
                                        f"{i + 1}_result{_ext_from_url(url)}")
                    await music.client._download_file(url, dest)
                    local_paths.append(dest)
            if not local_paths and op == "generate_lyrics":
                lyrics = _extract_lyrics(raw)
                if not lyrics:
                    raise RuntimeError("歌词生成完成但未返回歌词文本")
                local_paths = [_save_text(output_dir, "lyrics.txt", lyrics)]
            if not local_paths:
                raise RuntimeError(f"任务 {task_id} 已完成但未返回可下载产物")
            _write_meta(output_dir, meta)
            return local_paths
    except Exception as e:
        logger.error("KieAI music generate failed: %s", e)
        logger.error(traceback.format_exc())
        raise


def _write_meta(output_dir: str, meta: dict) -> None:
    try:
        with open(os.path.join(output_dir, "_musicgen_result.json"), "w",
                  encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2, default=str)
    except Exception:
        pass

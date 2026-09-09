"""KieAI Music (Suno) SDK wrapper.

Bridges the music generation factory to the KieAI/Suno catalog models. Each
generation MODE maps to a concrete catalog model id. The KieClient submits the
task, polls until completion and downloads the resulting audio into output_dir,
returning a list of local file paths.

Modes -> catalog ids:
    txt2music        -> generate-music      (instrumental=False)
    instrumental     -> generate-music      (instrumental=True)
    lyrics           -> generate-lyrics
    extend           -> extend-music        (needs audioId)
    cover            -> upload-and-cover-audio (needs upload_url or audio_path)
    add_instrumental -> add-instrumental    (needs upload_url or audio_path)
    add_vocals       -> add-vocals          (needs upload_url or audio_path)
    separate         -> separate-vocals     (needs task_id/audio_id/audio_url)
    to_wav           -> convert-to-wav      (needs task_id/audio_id)
    upload_extend    -> upload-and-extend-audio (needs upload_url or audio_path)
"""
import os
import json
import base64
import logging
import traceback

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "V5_5"

MODE_CATALOG = {
    "txt2music": "generate-music",
    "instrumental": "generate-music",
    "lyrics": "generate-lyrics",
    "extend": "extend-music",
    "cover": "upload-and-cover-audio",
    "add_instrumental": "add-instrumental",
    "add_vocals": "add-vocals",
    "separate": "separate-vocals",
    "to_wav": "convert-to-wav",
    "upload_extend": "upload-and-extend-audio",
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


async def _resolve_audio_url(client, kwargs: dict) -> str:
    """Return a URL for an audio input, uploading a local file if necessary."""
    url = kwargs.get("upload_url") or kwargs.get("uploadUrl")
    if url:
        return url
    local = kwargs.get("audio_path") or kwargs.get("audio_file") or kwargs.get("ref_audio")
    if local and os.path.exists(local):
        with open(local, "rb") as f:
            raw = f.read()
        b64 = base64.b64encode(raw).decode("utf-8")
        fn = os.path.basename(local)
        try:
            r = await client.upload(method="base64", base64Data=b64, uploadPath="audios", fileName=fn)
        except Exception as e:
            logger.error(f"Audio upload failed: {e}")
            raise
        if isinstance(r, dict):
            u = r.get("downloadUrl") or r.get("url") or r.get("data", {}).get("downloadUrl")
            if u:
                return u
        raise ValueError(f"Upload returned no URL: {r}")
    raise ValueError("需提供 upload_url/uploadUrl，或本地音频 audio_path")


async def _accepted_names(client, catalog_id: str):
    entry = client.catalog.get(catalog_id)
    if not entry:
        raise ValueError(f"catalog model '{catalog_id}' not found")
    return {p.name for p in entry.params}


async def _build_params(client, catalog_id: str, prompt: str, model: str, kwargs: dict) -> dict:
    names = await _accepted_names(client, catalog_id)
    p = {}

    def add(name, value, transform=None):
        if name in names and value is not None and value != "":
            p[name] = transform(value) if transform else value

    if catalog_id == "generate-music":
        add("prompt", prompt)
        add("customMode", kwargs.get("custom_mode", True), bool)
        add("instrumental", (catalog_id == "generate-music" and kwargs.get("mode") == "instrumental") or bool(kwargs.get("instrumental", False)), bool)
        add("model", model)
        add("style", kwargs.get("style"))
        add("title", kwargs.get("title"))
        add("negativeTags", kwargs.get("negative_tags"))
        add("vocalGender", kwargs.get("vocal_gender"))
        add("styleWeight", kwargs.get("style_weight"), _to_float)
        add("weirdnessConstraint", kwargs.get("weirdness_constraint"), _to_float)
        add("audioWeight", kwargs.get("audio_weight"), _to_float)
        add("personaId", kwargs.get("persona_id"))
        add("personaModel", kwargs.get("persona_model"))
        add("duration", kwargs.get("duration"), _to_int)
        add("gptId", kwargs.get("gpt_id"))
        add("language", kwargs.get("language"))

    elif catalog_id == "generate-lyrics":
        add("prompt", prompt)
        add("style", kwargs.get("style"))
        add("title", kwargs.get("title"))

    elif catalog_id == "extend-music":
        audio_id = kwargs.get("audio_id") or kwargs.get("audioId")
        if not audio_id:
            raise ValueError("extend 模式需要提供 audio_id/audioId")
        p["audioId"] = audio_id
        add("model", model)
        add("defaultParamFlag", bool(kwargs.get("default_param_flag", False)), bool)
        add("continueAt", kwargs.get("continue_at") if kwargs.get("continue_at") is not None else kwargs.get("continueAt"), _to_int)
        add("prompt", prompt)
        add("style", kwargs.get("style"))
        add("title", kwargs.get("title"))
        add("instrumental", bool(kwargs.get("instrumental", False)), bool)
        add("negativeTags", kwargs.get("negative_tags"))
        add("vocalGender", kwargs.get("vocal_gender"))
        add("styleWeight", kwargs.get("style_weight"), _to_float)
        add("weirdnessConstraint", kwargs.get("weirdness_constraint"), _to_float)
        add("audioWeight", kwargs.get("audio_weight"), _to_float)
        add("personaId", kwargs.get("persona_id"))
        add("personaModel", kwargs.get("persona_model"))

    elif catalog_id == "upload-and-cover-audio":
        upload_url = await _resolve_audio_url(client, kwargs)
        p["uploadUrl"] = upload_url
        add("customMode", kwargs.get("custom_mode", True), bool)
        add("instrumental", bool(kwargs.get("instrumental", False)), bool)
        add("model", model)
        add("prompt", prompt)
        add("style", kwargs.get("style"))
        add("title", kwargs.get("title"))
        add("negativeTags", kwargs.get("negative_tags"))
        add("vocalGender", kwargs.get("vocal_gender"))
        add("styleWeight", kwargs.get("style_weight"), _to_float)
        add("weirdnessConstraint", kwargs.get("weirdness_constraint"), _to_float)
        add("audioWeight", kwargs.get("audio_weight"), _to_float)
        add("personaId", kwargs.get("persona_id"))
        add("personaModel", kwargs.get("persona_model"))

    elif catalog_id == "add-instrumental":
        upload_url = await _resolve_audio_url(client, kwargs)
        p["uploadUrl"] = upload_url
        add("model", model)
        add("title", kwargs.get("title") or (prompt[:60] if prompt else ""))
        add("tags", kwargs.get("tags"))
        add("negativeTags", kwargs.get("negative_tags"))
        add("vocalGender", kwargs.get("vocal_gender"))
        add("styleWeight", kwargs.get("style_weight"), _to_float)
        add("weirdnessConstraint", kwargs.get("weirdness_constraint"), _to_float)
        add("audioWeight", kwargs.get("audio_weight"), _to_float)

    elif catalog_id == "add-vocals":
        upload_url = await _resolve_audio_url(client, kwargs)
        p["uploadUrl"] = upload_url
        add("prompt", prompt)
        add("title", kwargs.get("title") or (prompt[:60] if prompt else ""))
        add("style", kwargs.get("style"))
        add("negativeTags", kwargs.get("negative_tags"))
        add("vocalGender", kwargs.get("vocal_gender"))
        add("styleWeight", kwargs.get("style_weight"), _to_float)
        add("weirdnessConstraint", kwargs.get("weirdness_constraint"), _to_float)
        add("audioWeight", kwargs.get("audio_weight"), _to_float)
        add("model", model)

    elif catalog_id == "separate-vocals":
        stem_type = kwargs.get("stem_type") or kwargs.get("type") or "all"
        audio_url = kwargs.get("audio_url") or kwargs.get("audioUrl")
        audio_id = kwargs.get("audio_id") or kwargs.get("audioId")
        task_id = kwargs.get("task_id") or kwargs.get("taskId")
        if not (audio_url or audio_id or task_id):
            # 提供了本地音频文件：先上传取得 URL，再按 audioUrl 提交
            local = kwargs.get("audio_path") or kwargs.get("audio_file") or kwargs.get("ref_audio")
            if local and os.path.exists(local):
                audio_url = await _resolve_audio_url(client, kwargs)
        if audio_url:
            p["audioUrl"] = audio_url
        elif audio_id:
            p["audioId"] = audio_id
        elif task_id:
            p["taskId"] = task_id
        else:
            raise ValueError("separate 模式需要提供 audio_url/audio_id/task_id 之一")
        add("type", stem_type)

    elif catalog_id == "convert-to-wav":
        task_id = kwargs.get("task_id") or kwargs.get("taskId")
        audio_id = kwargs.get("audio_id") or kwargs.get("audioId")
        if task_id:
            p["taskId"] = task_id
        if audio_id:
            p["audioId"] = audio_id
        if not (task_id or audio_id):
            raise ValueError("to_wav 模式需要提供 task_id/audio_id")

    elif catalog_id == "upload-and-extend-audio":
        upload_url = await _resolve_audio_url(client, kwargs)
        p["uploadUrl"] = upload_url
        add("defaultParamFlag", bool(kwargs.get("default_param_flag", False)), bool)
        add("model", model)
        add("prompt", prompt)
        add("style", kwargs.get("style"))
        add("title", kwargs.get("title"))
        add("continueAt", kwargs.get("continue_at") if kwargs.get("continue_at") is not None else kwargs.get("continueAt"), _to_int)
        add("instrumental", bool(kwargs.get("instrumental", False)), bool)
        add("negativeTags", kwargs.get("negative_tags"))
        add("vocalGender", kwargs.get("vocal_gender"))
        add("styleWeight", kwargs.get("style_weight"), _to_float)
        add("weirdnessConstraint", kwargs.get("weirdness_constraint"), _to_float)
        add("audioWeight", kwargs.get("audio_weight"), _to_float)
        add("personaId", kwargs.get("persona_id"))
        add("personaModel", kwargs.get("persona_model"))

    return p


_LYRICS_KEYS = ("lyrics", "lyric", "text", "content", "prompt")


def _extract_lyrics(obj, depth: int = 0) -> str:
    """从接口返回结构中递归提取歌词文本（歌词模式可能只返回文本、无可下载产物）。"""
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


async def generate(
    prompt: str,
    output_dir: str,
    model: str = "",
    mode: str = "txt2music",
    api_key: str = "",
    **kwargs,
) -> list:
    """Generate music via KieAI/Suno and return local file paths.

    Returns an empty list on failure (errors are logged).
    """
    model = model or _DEFAULT_MODEL
    catalog_id = MODE_CATALOG.get(mode)
    if not catalog_id:
        logger.error(f"Unsupported music mode '{mode}'. Supported: {list(MODE_CATALOG)}")
        return []

    os.makedirs(output_dir, exist_ok=True)

    try:
        from kieai import KieClient
    except ImportError:
        try:
            from backend.kieai_sdk.kieai import KieClient
        except Exception as e:
            logger.error(f"Failed to import KieClient: {e}")
            return []

    poll_timeout = _to_int(kwargs.get("poll_timeout"), 600) or 600

    try:
        async with KieClient(api_key=api_key or None) as client:
            client.max_poll = max(1, int(poll_timeout / max(getattr(client, "poll_interval", 3), 0.1)))
            params = await _build_params(client, catalog_id, prompt, model, kwargs)
            logger.info(f"KieAI music: mode={mode} model={model} catalog={catalog_id} params={ {k:(v if k!='uploadUrl' else '<url>') for k,v in params.items()} }")
            result = await client.generate(catalog_id, output_path=output_dir, **params)
            local_paths = result.get("local_paths") or []
            # 落盘原始返回结构（不含已下载文件），供下游 extend / separate / to_wav 取 audio_id、task_id
            try:
                meta = {k: v for k, v in result.items() if k != "local_paths"}
                with open(os.path.join(output_dir, "_musicgen_result.json"), "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2, default=str)
            except Exception:
                pass
            # 歌词模式：接口仅返回文本（无可下载产物）时，把歌词落盘为 lyrics.txt
            if not local_paths and catalog_id == "generate-lyrics":
                lyrics = _extract_lyrics(result)
                if lyrics:
                    lp = os.path.join(output_dir, "lyrics.txt")
                    with open(lp, "w", encoding="utf-8") as f:
                        f.write(lyrics)
                    local_paths = [lp]
            if not local_paths:
                logger.warning(f"KieAI music returned no local paths. Result keys: {list(result.keys()) if isinstance(result, dict) else type(result)}")
            return local_paths
    except Exception as e:
        logger.error(f"KieAI music generate failed: {e}")
        logger.error(traceback.format_exc())
        return []

"""LCTTS 管家 本地 API 封装（sdk 型 TTS 接口）。

调用 LCTTS 管家（统一 TTS API 管家 / LcTTS Hub）的本地 HTTP 服务（默认端口 5199）：

    POST /api/tts?model=<引擎名>                    统一合成入口（参数原样透传引擎）
    GET  /api/hub/engines/{model}/params            拉取该引擎支持的参数表与端点模板
    GET  /api/hub/passthrough{endpoints.task}?model=...        异步任务型轮询
    GET  /api/hub/passthrough{endpoints.download}?model=...    异步任务型下载

具体调度到哪个引擎由 ``model`` 决定（voxcpm / omnivoice / index25 / dots / confucius4 /
audio8 / auk 等）。管家会自动拉起 / 复用目标引擎进程（含首次模型下载，可能数分钟），
并原样回吐引擎响应（状态码、Content-Type、音频字节或任务 JSON）。

支持：
  - 同步型：响应直接为音频字节（audio/*）或 JSON 含 audio_url / audio_base64 / output_path
  - 异步任务型：响应含 task_id → 轮询任务状态 → 下载成品音频
  - 声音克隆（提供 ref_audio 本地路径）/ 声音设计（voice_design / controllable_clone 作为 instruct）
  - 原生语速（引擎参数含 ``speed`` 时生效，否则忽略）

请求体字段名与引擎 API 完全一致（经管家原样透传），与项目 TTS 工厂的请求参数解耦。
管家即接口，无额外认证；本封装默认连接本机 127.0.0.1:5199。
"""
import json
import logging
import os
import time

import requests
from backend.tts.tts_interface_manager import finalize_tts_output

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "http://127.0.0.1:5199"
DEFAULT_MODEL = "voxcpm"
DEFAULT_POLL_INTERVAL = 2.0

# Hub 控制开关（对应自检清单 §2.1 / §7.1）
#  inject_defaults=1 → Hub 对我们已发字段原样透传，仅对"我们未发的可选参数"补默认值（安全网）
#  strict=1          → Hub 先校验必填，缺真正必填项直接 400，避免注定失败的请求触发引擎冷启动
_HUB_INJECT_DEFAULTS = 1
_HUB_STRICT = 1

# 候选的「参考音频 本地路径」参数名（优先用路径，免上传；hub 与本项目同机运行）
_REF_PATH_CANDIDATES = [
    "ref_audio_path", "speaker_audio_path", "spk_audio_path",
    "reference_audio", "reference_audio_file",
]
# 候选的「参考音频 文件上传」参数名（仅当路径型不存在且引擎要求上传时使用）
_REF_FILE_CANDIDATES = ["ref_audio", "speaker_audio", "spk_audio", "audio"]
# 候选的「参考音频文本」参数名
_REF_TEXT_CANDIDATES = ["prompt_text", "ref_text", "ref_text_en"]

# ---- 引擎参数 schema 缓存 ----
# Hub 的 /params 只读注册表 manifest，单次毫秒级，但批量配音时每句都拉会产生 N 次冗余往返。
# 按 model 缓存，默认 5 分钟 TTL；若 Hub 返回 ETag 则改用 If-None-Match/304 精确失效
# （Hub 改完 defaults 后 ETag 变化，下次请求自动拿到新 schema）。
_SCHEMA_CACHE: dict = {}
_SCHEMA_TTL = 300.0


def clear_schema_cache(model: str = None):
    """主动清空 schema 缓存。model 为 None 时清空全部。

    建议在通过 PUT /config 修改 defaults / 引擎配置后调用，确保下次合成拉取最新 schema。
    """
    if model is None:
        _SCHEMA_CACHE.clear()
    else:
        _SCHEMA_CACHE.pop(model, None)


def _fetch_schema(base: str, model: str) -> dict:
    """拉取（或命中缓存的）引擎参数 schema。

    返回 schema dict；网络异常且无缓存时抛出异常由调用方处理。
    """
    now = time.monotonic()
    cached = _SCHEMA_CACHE.get(model)
    if cached and now - cached["time"] < _SCHEMA_TTL:
        return cached["schema"]

    headers = {}
    if cached and cached.get("etag"):
        headers["If-None-Match"] = cached["etag"]
    try:
        resp = requests.get(
            f"{base}/api/hub/engines/{model}/params", timeout=15, headers=headers
        )
    except requests.exceptions.RequestException:
        if cached:
            logger.warning(f"LCTTS hub: params fetch failed, reuse stale schema for '{model}'")
            return cached["schema"]
        raise

    # Hub 支持 ETag：配置未变时返回 304，直接复用缓存
    if resp.status_code == 304 and cached:
        cached["time"] = now
        return cached["schema"]
    resp.raise_for_status()
    schema = resp.json()
    _SCHEMA_CACHE[model] = {
        "schema": schema,
        "time": now,
        "etag": resp.headers.get("ETag"),
        "alias": resp.headers.get("X-Hub-Alias"),
    }
    return schema


def _coerce(schema_param, value):
    """按 schema 声明的类型把配置里的字符串默认值尽量转为正确类型。"""
    if value is None:
        return None
    ptype = (schema_param or {}).get("type", "string")
    try:
        if ptype == "number":
            return float(value)
        if ptype == "integer":
            return int(value)
        if ptype == "boolean":
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("1", "true", "yes", "y", "on")
    except (ValueError, TypeError):
        return value
    return value


def _load_config():
    """读取 tts_interfaces.json 中 lctts_hub 接口的配置。

    返回 dict：
    - api_url / model / poll_interval：优先取 sdk_extra_args，model 缺失时回退 config.model
    - custom_params：来自 custom_params 列表（未解析的 key/default/description）
    不依赖密钥，无需 resolve_deep。
    """
    cfg_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "config", "tts_interfaces.json")
    )
    try:
        with open(cfg_path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        for iface in data.get("interfaces", []):
            if iface.get("id") == "lctts_hub":
                cfg = iface.get("config", {})
                extra = cfg.get("sdk_extra_args", {}) or {}
                return {
                    "api_url": extra.get("api_url", DEFAULT_API_URL),
                    "model": extra.get("model", cfg.get("model", DEFAULT_MODEL)),
                    "poll_interval": float(extra.get("poll_interval", DEFAULT_POLL_INTERVAL)),
                    "custom_params": cfg.get("custom_params", []) or [],
                }
    except Exception as e:
        logger.warning(f"LCTTS hub: failed to load config overrides: {e}")
    return {
        "api_url": DEFAULT_API_URL,
        "model": DEFAULT_MODEL,
        "poll_interval": DEFAULT_POLL_INTERVAL,
        "custom_params": [],
    }


def _resolve_model(model, cfg):
    if model:
        return model
    if cfg.get("model"):
        return cfg["model"]
    return DEFAULT_MODEL


def _build_body(schema, text, ref_audio, ref_text, speed, mode,
                voice_design, controllable_clone, cfg, kwargs):
    """依据引擎参数 schema 组装请求体（与引擎 API 字段名一致）。"""
    engine_params = schema.get("params", {}) or {}

    # 文本字段名（index25 用 input_text，其余用 text）
    text_key = "input_text" if "input_text" in engine_params else "text"
    body = {text_key: text}

    # 参考音频：优先用本地路径（同机），否则回退文件上传
    if ref_audio and os.path.exists(ref_audio):
        ref_abspath = os.path.abspath(ref_audio)
        ref_key = next((k for k in _REF_PATH_CANDIDATES if k in engine_params), None)
        if ref_key:
            body[ref_key] = ref_abspath
        else:
            ref_file_key = next(
                (k for k in _REF_FILE_CANDIDATES
                 if k in engine_params and engine_params[k].get("type") == "file"),
                None,
            )
            if ref_file_key:
                body[ref_file_key] = ref_abspath  # 命中文件型时由调用方按 multipart 上传

    # 参考音频文本
    if ref_text:
        rt_key = next((k for k in _REF_TEXT_CANDIDATES if k in engine_params), None)
        if rt_key:
            body[rt_key] = ref_text

    # 语速（仅引擎原生支持时）
    if speed is not None and abs(float(speed) - 1.0) > 0.01 and "speed" in engine_params:
        body["speed"] = float(speed)

    # 声音设计 / 可控克隆：作为 instruct 指令
    design_text = voice_design or controllable_clone
    if mode in ("voice_design", "controllable_clone") and design_text:
        if "instruct" in engine_params:
            body["instruct"] = design_text
        if "emo_control_method" in engine_params:
            body["emo_control_method"] = "instruct"
        if "emo_vector" in engine_params and controllable_clone:
            body["emo_vector"] = controllable_clone

    # 配置中的 custom_params 默认值（仅当引擎 schema 含该字段时填入）
    for cp in cfg.get("custom_params", []):
        key = cp.get("key")
        if not key or key in body or key == text_key:
            continue
        if key not in engine_params:
            continue
        dv = cp.get("default", "")
        if dv in (None, ""):
            continue
        body[key] = _coerce(engine_params[key], dv)

    # 调用时透传的引擎专属参数（覆盖默认值）
    for k, v in (kwargs or {}).items():
        if k in ("text", "output_path", "ref_audio", "ref_text", "speed",
                 "mode", "voice_design", "controllable_clone", "timeout",
                 "api_url", "model", "voice", "poll_interval", "kwargs"):
            continue
        if k in engine_params and v not in (None, ""):
            body[k] = _coerce(engine_params[k], v)

    return body, text_key


def synthesize(
    text,
    output_path,
    ref_audio=None,
    mode=None,
    speed=None,
    timeout=600,
    api_url=None,
    model=None,
    voice=None,
    ref_text=None,
    voice_design=None,
    controllable_clone=None,
    poll_interval=None,
    **kwargs,
):
    """调用 LCTTS 管家 合成语音并写入 output_path。

    参数优先级：调用时显式传入 > 配置文件 tts_interfaces.json 中 lctts_hub 的设置 >
    代码内硬编码默认值。
    """
    if not text:
        logger.error("LCTTS hub: empty text")
        return False

    cfg = _load_config()
    base = (api_url or cfg["api_url"] or DEFAULT_API_URL).rstrip("/")
    target_model = _resolve_model(model or kwargs.get("model"), cfg)
    poll_interval = float(poll_interval or cfg["poll_interval"] or DEFAULT_POLL_INTERVAL)
    timeout = float(timeout or 600)

    # 1) 拉取引擎参数 schema（命中缓存则免往返；Hub 支持 ETag 时按 304 精确失效）
    try:
        schema = _fetch_schema(base, target_model)
    except Exception as e:
        logger.error(f"LCTTS hub: failed to fetch params for model '{target_model}': {e}")
        return False

    # 排错辅助：Hub 回显本次字段翻译（如 text>instruction;ref_audio>audio）
    _alias = _SCHEMA_CACHE.get(target_model, {}).get("alias")
    if _alias:
        logger.debug(f"LCTTS hub: alias mapping for '{target_model}': {_alias}")

    body, text_key = _build_body(
        schema, text, ref_audio, ref_text, speed, mode,
        voice_design, controllable_clone, cfg, kwargs,
    )
    # 服务端直接落盘（引擎支持 output_path 时传入，失败再降级下载）
    if "output_path" in (schema.get("params") or {}) and os.path.isabs(output_path):
        body["output_path"] = os.path.abspath(output_path)

    endpoints = schema.get("endpoints", {}) or {}
    body_mode = schema.get("body_mode", "auto")

    # 声音设计 / 可控克隆：若引擎存在 design 端点则显式指定 endpoint
    endpoint = None
    if mode in ("voice_design", "controllable_clone") and endpoints.get("design"):
        endpoint = "design"

    tts_url = (
        f"{base}/api/tts?model={target_model}"
        f"&inject_defaults={_HUB_INJECT_DEFAULTS}&strict={_HUB_STRICT}"
    )
    if endpoint:
        tts_url += f"&endpoint={endpoint}"

    # 判定是否需要 multipart 文件上传
    file_keys = [k for k in body
                 if k in _REF_FILE_CANDIDATES
                 and (schema["params"].get(k) or {}).get("type") == "file"]
    use_multipart = bool(file_keys)

    try:
        if use_multipart:
            # 文件字段以 (filename, fileobj) 上传，其余作为表单字段
            data = {}
            files = {}
            for k, v in list(body.items()):
                if k in file_keys:
                    try:
                        files[k] = (os.path.basename(str(v)), open(v, "rb"), "audio/wav")
                    except Exception as fe:
                        logger.error(f"LCTTS hub: cannot open ref audio {v}: {fe}")
                        return False
                else:
                    data[k] = str(v) if v is not None else ""
            try:
                resp = requests.post(tts_url, data=data, files=files, timeout=timeout)
            finally:
                for _, f in files.values():
                    try:
                        f.close()
                    except Exception:
                        pass
        elif body_mode == "json":
            resp = requests.post(tts_url, json=body, timeout=timeout)
        else:
            # 其余引擎为 multipart/form-data（文本/路径字段）
            form = {k: (str(v) if v is not None else "") for k, v in body.items()}
            resp = requests.post(tts_url, data=form, timeout=timeout)
    except requests.exceptions.ConnectionError as e:
        logger.error(f"LCTTS hub service unreachable at {base}: {e}")
        return False
    except Exception:
        logger.exception("LCTTS hub request failed")
        return False

    if resp.status_code != 200:
        logger.error(f"LCTTS hub: tts request failed {resp.status_code}: {resp.text[:300]}")
        return False

    ctype = resp.headers.get("Content-Type", "")

    # 2a) 同步音频字节直接落盘
    if ctype.startswith("audio/") or ctype in ("application/octet-stream",):
        return finalize_tts_output(output_path, content=resp.content, timeout=timeout)

    # 2b) JSON 响应
    try:
        data = resp.json()
    except Exception:
        logger.error("LCTTS hub: non-audio, non-json response")
        return False

    # 2c) 异步任务型（含 task_id）
    if data.get("task_id"):
        return _poll_async(base, target_model, data["task_id"], endpoints,
                           output_path, timeout, poll_interval)

    # 2d) 服务端已写盘（output_path）或返回下载 URL / base64
    remote = data.get("output_path") or data.get("audio_path")
    if remote and os.path.isfile(remote) and os.path.getsize(remote) > 0:
        return finalize_tts_output(output_path, remote_path=remote, timeout=timeout)
    url = data.get("audio_url") or data.get("download_url")
    if url:
        if url.startswith("/"):
            url = base + url
        return finalize_tts_output(output_path, download_url=url, timeout=timeout)
    b64 = data.get("audio_base64") or data.get("audio")
    if b64 and isinstance(b64, str):
        import base64 as _b64
        try:
            return finalize_tts_output(
                output_path, content=_b64.b64decode(b64), timeout=timeout
            )
        except Exception:
            logger.exception("LCTTS hub: base64 decode failed")
            return False

    logger.error(f"LCTTS hub: unrecognized response: {str(data)[:300]}")
    return False


def _poll_async(base, model, task_id, endpoints, output_path, timeout, poll_interval):
    """异步任务型：轮询任务状态直到完成，再下载成品音频。"""
    task_tpl = endpoints.get("task", "/api/v1/tasks/{task_id}")
    dl_tpl = endpoints.get("download", "/api/v1/voice/download/{task_id}")
    task_url = f"{base}/api/hub/passthrough{task_tpl.replace('{task_id}', task_id)}?model={model}"
    dl_url = f"{base}/api/hub/passthrough{dl_tpl.replace('{task_id}', task_id)}?model={model}"

    logger.info(f"LCTTS hub: async task {task_id} created, polling {task_url}")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(max(0.5, poll_interval))
        try:
            status_resp = requests.get(task_url, timeout=15)
            if status_resp.status_code != 200:
                continue
            status_data = status_resp.json()
            status = status_data.get("status", "")
            if status == "completed":
                # 优先用服务端写盘路径，否则 HTTP 下载
                remote = status_data.get("output_path")
                if remote and os.path.isfile(remote) and os.path.getsize(remote) > 0:
                    return finalize_tts_output(output_path, remote_path=remote, timeout=timeout)
                dl = requests.get(dl_url, timeout=timeout)
                if dl.status_code == 200 and dl.content:
                    return finalize_tts_output(output_path, content=dl.content, timeout=timeout)
                logger.error("LCTTS hub: download returned empty")
                return False
            if status == "failed":
                logger.error(f"LCTTS hub: task failed: {status_data.get('message', '')}")
                return False
        except Exception as pe:
            logger.warning(f"LCTTS hub: poll error: {pe}")
            continue

    logger.error(f"LCTTS hub: timeout after {timeout}s waiting for task {task_id}")
    return False


def list_voices():
    """LCTTS 管家为声音克隆/设计聚合层，无预置音色列表。"""
    return []

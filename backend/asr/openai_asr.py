"""OpenAI-compatible ASR abstraction layer.

统一封装任意「兼容 OpenAI 音频转录接口」的 ASR 引擎，标准端点为
``POST {base_url}/v1/audio/transcriptions``（如 OpenAI、Groq、DeepInfra、
本地 Whisper 服务、各类兼容网关等）。

职责：
1. 根据接口配置构造 multipart/form-data 请求（音频字段名、鉴权头、model/language
   等均可配置），与具体服务解耦。
2. 自动请求 ``response_format=verbose_json`` 以获取段级 / 词级时间戳。
3. 把 OpenAI 返回归一为 VideoLingo 标准 ASR 结果
   ``{text, language, segments:[{start,end,text,words:[{start,end,text}]}]}``，
   便于下游 VAD / 对齐 / 标点 / 说话人节点直接复用。
"""
from __future__ import annotations

import os
import json

import requests


DEFAULT_ENDPOINT = "/v1/audio/transcriptions"
DEFAULT_AUDIO_PARAM = "file"
DEFAULT_AUTH_HEADER = "Authorization"
DEFAULT_AUTH_SCHEME = "Bearer"
DEFAULT_RESPONSE_FORMAT = "verbose_json"


def build_openai_request(cfg: dict, audio_path: str, language=None, model=None):
    """根据接口配置构造 OpenAI 兼容请求。

    Returns
    -------
    tuple
        ``(url, headers, fields, file_tuple)``：
        - ``url``: 完整请求地址
        - ``headers``: 鉴权头等额外请求头
        - ``fields``: form 表单字段（不含音频文件本身）
        - ``file_tuple``: ``(param_name, (filename, fileobj, mime))``，调用方负责关闭 fileobj
    """
    base_url = (cfg.get("api_url") or cfg.get("base_url") or "").strip().rstrip("/")
    if not base_url:
        raise ValueError("OpenAI 兼容接口缺少 api_url（或 base_url）")
    endpoint = (cfg.get("endpoint") or DEFAULT_ENDPOINT).strip()
    if endpoint and not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    # 兼容两种常见约定，避免拼出 /v1/v1/... 重复路径段：
    #  - base_url 已含 /v1（OpenAI SDK 风格，如 https://api.openai.com/v1）
    #  - 或 endpoint 已含 /v1（如 /v1/audio/transcriptions）
    if base_url.endswith("/v1") and endpoint.startswith("/v1"):
        endpoint = endpoint[3:]  # "/v1/audio/transcriptions" -> "/audio/transcriptions"
    url = base_url + endpoint

    audio_param = cfg.get("audio_param") or DEFAULT_AUDIO_PARAM
    api_key = cfg.get("api_key") or cfg.get("sdk_api_key") or ""
    auth_header = cfg.get("auth_header") or DEFAULT_AUTH_HEADER
    auth_scheme = cfg.get("auth_scheme") or DEFAULT_AUTH_SCHEME

    # model / language：显式参数优先，回退到接口配置
    model = model or cfg.get("model")
    language = language or cfg.get("language")
    if language in (None, "", "auto"):
        language = None  # OpenAI 省略 language 即自动检测

    response_format = cfg.get("response_format") or DEFAULT_RESPONSE_FORMAT

    fields: dict = {}
    if model:
        fields["model"] = model
    if language:
        fields["language"] = language
    if response_format:
        fields["response_format"] = response_format
    if cfg.get("prompt"):
        fields["prompt"] = cfg["prompt"]
    if cfg.get("temperature") not in (None, ""):
        try:
            fields["temperature"] = float(cfg["temperature"])
        except (TypeError, ValueError):
            pass
    # 自定义参数（补充默认字段，已存在的字段不覆盖）
    for cp in cfg.get("custom_params", []) or []:
        key = cp.get("key")
        if key and key not in fields:
            fields[key] = cp.get("default", "")

    headers: dict = {}
    if api_key:
        headers[auth_header] = f"{auth_scheme} {api_key}" if auth_scheme else api_key

    if not audio_path or not os.path.exists(audio_path):
        raise ValueError(f"音频文件不存在: {audio_path}")
    filename = os.path.basename(audio_path)
    fileobj = open(audio_path, "rb")
    file_tuple = (audio_param, (filename, fileobj, "application/octet-stream"))

    return url, headers, fields, file_tuple


def _normalize_openai(data: dict, duration: float = 0.0) -> dict:
    """把 OpenAI 转录响应归一为 VideoLingo 标准 ASR 结果。"""
    text = (data.get("text") or "").strip()
    language = data.get("language")

    segments_in = data.get("segments") or []
    segments_out = []
    for seg in segments_in:
        if not isinstance(seg, dict):
            continue
        words_in = seg.get("words") or []
        words_out = [
            {
                "start": w.get("start"),
                "end": w.get("end"),
                "text": w.get("word", ""),
            }
            for w in words_in
            if isinstance(w, dict)
        ]
        segments_out.append({
            "start": float(seg.get("start", 0.0)),
            "end": float(seg.get("end", 0.0)),
            "text": (seg.get("text") or "").strip(),
            "words": words_out,
        })

    if not segments_out:
        # 无段级信息：用全文本构造单个段落，避免下游节点拿到空 segments
        segments_out.append({
            "start": 0.0,
            "end": float(data.get("duration") or duration or 0.0),
            "text": text,
            "words": [],
        })

    return {
        "text": text,
        "language": language,
        "segments": segments_out,
    }


def run_openai_asr(
    cfg: dict,
    audio_path: str,
    output_path: str = None,
    *,
    language=None,
    model=None,
    timeout: int = None,
    **kwargs,
) -> dict:
    """执行一次 OpenAI 兼容的音频转录并将结果归一化。

    Parameters
    ----------
    cfg : dict         接口配置（api_url / endpoint / api_key / model / ...）
    audio_path : str   音频文件路径
    output_path : str  可选，结果写出路径（JSON）
    language, model :  可选，覆盖配置中的默认值
    timeout : int      可选请求超时（秒），默认取 cfg.timeout 或 300

    Returns
    -------
    dict  VideoLingo 标准 ASR 结果
    """
    url, headers, fields, file_tuple = build_openai_request(
        cfg, audio_path, language=language, model=model
    )
    timeout = timeout or cfg.get("timeout") or 300
    try:
        resp = requests.post(
            url,
            headers=headers,
            data=fields,
            files={file_tuple[0]: file_tuple[1]},
            timeout=timeout,
        )
    finally:
        try:
            file_tuple[1][1].close()
        except Exception:
            pass

    if resp.status_code != 200:
        raise Exception(f"OpenAI ASR 请求失败: {resp.status_code} {resp.text[:500]}")

    try:
        data = resp.json()
    except Exception:
        # text / srt / vtt 等非 JSON 响应格式：原样作为文本
        data = {"text": resp.text}

    if not isinstance(data, dict):
        data = {"text": str(data)}

    result = _normalize_openai(data)
    if output_path:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    return result

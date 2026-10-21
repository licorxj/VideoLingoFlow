"""ACE-Step 1.5「step music」免费音乐生成 SDK 包装器。

定位
----
backend/musicgen 工厂（SDKMagicGen）按接口配置 ``sdk_module`` 动态路由——
KieAI/Suno 走 ``kieai_music_wrapper``，本模块承接 ACE-Step 1.5 的另一条分路。
两者请求契约有本质区别：

  KieAI/Suno : createTask 提交 → recordInfo 轮询（异步任务）
  ACE-Step   : 云端 = OpenRouter 兼容同步对话接口，base64 音频内联返回；
               本地 = /release_task 提交 → /query_result 轮询 → /v1/audio 下载

来源
----
封装修复自 original-bgm-forge 技能的 L2/L3 引擎（acestep_bridge.py），
请求格式遵循 ACE-Step 官方文档：
  本地整合包 API : X:/ACE-Step-1.5/docs/zh/API.md
  云端 API      : X:/ACE-Step-1.5/docs/zh/ONLINE_API.md

官方标价 $0（免费）：云端 key 在 https://acemusic.ai/api-key 免费领取；
本地整合包（ACE-Step-1.5 便携包，MIT 许可）无需 key。

四种模式（对应官方「输入模式」）
------------------------------
  step_txt2music     标签模式   : <prompt> 描述 </prompt>（+可选 <lyrics>）→ 完整歌曲（含人声）
  step_natural       自然语言   : 一句话描述 → 5Hz LM 自动创作描述与歌词并生成
  step_lyrics2music  纯歌词模式 : <lyrics> 歌词 </lyrics>（+可选 <prompt> 风格）→ 歌曲
  step_instrumental  纯音乐     : instrumental=true，<prompt> → 无人声纯音乐

节点自定义输入（提示词 / 歌词）优先于连线输入（step 层保证），本模块只管组装请求。

api_mode 路由（接口 JSON ``config.api_mode``）
---------------------------------------------
  cloud  : 官方云 https://api.acemusic.ai（POST /v1/chat/completions，同步）
  native : 本地整合包 http://127.0.0.1:8001（/release_task → /query_result 轮询）
  auto   : 按 URL 判断（https / 含 acemusic.ai → cloud，否则 native）
"""
import os
import json
import time
import base64
import shutil
import logging
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

# 云端默认（OpenRouter 兼容协议，同步返回 base64 音频）
DEFAULT_CLOUD_API_URL = "https://api.acemusic.ai"
CLOUD_MODEL_ID = "acemusic/acestep-v1.5-turbo"
# 本地整合包默认（官方 start_api_server.bat 默认端口 8001）
DEFAULT_NATIVE_API_URL = "http://127.0.0.1:8001"
DEFAULT_NATIVE_MODEL = "acestep-v15-turbo"
# 云端在线 ID → 本地权重目录名（拼写差异：v1.5 → v15）
_NATIVE_MODEL_MAP = {"acestep-v1.5-turbo": "acestep-v15-turbo"}
# 节点「模型」下拉两项选择 → 契约分路（local=本地整合包 / cloud=免费在线）
_MODEL_SELECTION = {"local": "native", "cloud": "cloud"}

STEP_MODES = ("step_txt2music", "step_natural", "step_lyrics2music", "step_instrumental")
# 兼容别名：ACE-Step 接口也可承接 KieAI 命名的同名模式
_MODE_ALIASES = {"txt2music": "step_txt2music", "instrumental": "step_instrumental"}

# 云 API 前置 Cloudflare，对非浏览器 UA 返回 403 "error code: 1010"，必须带浏览器 UA
_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# 模型参数默认值（接口 JSON model_metadata.*.params 可覆盖）
# 云端不支持 batch_size 参数：批次生成 = 循环请求，每次间隔 5 秒
_CLOUD_BATCH_INTERVAL = 5
_DEFAULTS = {
    "audio_format": "mp3",       # mp3 / wav / flac / opus / aac
    "inference_steps": 8,        # turbo 模型推荐 8；base/sft 用 32~50
    "guidance_scale": 7.0,       # CFG（仅 base 模型有效）
    "temperature": 0.85,         # LM 采样温度
    "top_p": 0.9,
    "vocal_language": "en",      # 演唱语言（zh/en/ja...；纯音乐忽略）
    "batch_size": 1,
    "timeout": 900,              # 云端 30s~数分钟；本地首次含权重加载
    "poll_interval": 3,          # native 轮询间隔（秒）
    "lm_optimize": True,         # LM 优化提示词（use_cot_caption）
    "thinking": False,           # LM 深度思考（质量更高、更慢）
}


# ─────────────────────────────────────────────────────────────────────────────
# 密钥 / 路由解析
# ─────────────────────────────────────────────────────────────────────────────
def _resolve_api_key(api_key: str) -> str:
    """密钥优先级：调用者传入 > 项目密钥管理器（secret://ACESTEP_API_KEY）> 环境变量。"""
    if api_key and str(api_key).strip():
        text = str(api_key).strip()
        if text.startswith("secret://"):
            try:
                from backend.config.credential_store import resolve as _resolve_ref
                resolved = str(_resolve_ref(text) or "").strip()
                if resolved:
                    return resolved
            except Exception:
                pass
        return text
    try:
        from backend.config.credential_store import resolve as _resolve_ref
        resolved = str(_resolve_ref("secret://ACESTEP_API_KEY") or "").strip()
        if resolved:
            return resolved
    except Exception:
        pass
    return os.getenv("ACESTEP_API_KEY", "")


def _is_cloud_url(url: str) -> bool:
    u = (url or "").strip().lower()
    return u.startswith("https://") or "acemusic.ai" in u


def _resolve_route(api_url: str, api_mode: str):
    """返回 (base_url, contract)；contract ∈ {"cloud", "native"}。"""
    mode = (api_mode or "auto").strip().lower()
    url = (api_url or "").strip() or DEFAULT_CLOUD_API_URL
    if mode == "cloud":
        return url.rstrip("/"), "cloud"
    if mode == "native":
        return url.rstrip("/"), "native"
    return url.rstrip("/"), ("cloud" if _is_cloud_url(url) else "native")


def _resolve_selection_route(model: str, api_url: str):
    """选择值（local / cloud，来自节点「接口类型」或历史模型选择值）决定契约分路。

    返回 None 表示不是分路选择值，走 _resolve_route 常规解析。
    """
    sel = (model or "").strip().lower()
    if sel not in _MODEL_SELECTION:
        return None
    contract = _MODEL_SELECTION[sel]
    if contract == "native":
        # 本地整合包：接口 JSON 的 api_url 若是云端地址则忽略，用本地默认
        url = (api_url or "").strip()
        base = url.rstrip("/") if (url and not _is_cloud_url(url)) else DEFAULT_NATIVE_API_URL
        return base, contract
    return ((api_url or "").strip() or DEFAULT_CLOUD_API_URL).rstrip("/"), contract


def _normalize_model(model: str, contract: str) -> str:
    """云端用 acemusic/ 前缀 id，本地用裸模型名——按契约自动映射。"""
    model = (model or "").strip()
    if contract == "cloud":
        # 云端仅接受在线模型 ID；本地命名一律映射到官方云端模型
        return model if model.startswith("acemusic/") else CLOUD_MODEL_ID
    # acemusic/acestep-v1.5-turbo → 本地权重目录名 acestep-v15-turbo
    local = model.replace("acemusic/", "")
    if not local:
        return DEFAULT_NATIVE_MODEL
    return _NATIVE_MODEL_MAP.get(local, local)


# ─────────────────────────────────────────────────────────────────────────────
# 请求组装
# ─────────────────────────────────────────────────────────────────────────────
def _tag(name: str, text: str) -> str:
    return f"<{name}>{text}</{name}>"


def build_content(mode: str, prompt: str, lyrics: str) -> str:
    """按官方「输入模式」组装 messages 内容（标签模式 / 自然语言 / 纯歌词 / 纯音乐）。"""
    prompt = (prompt or "").strip()
    lyrics = (lyrics or "").strip()
    if mode == "step_natural":
        # 自然语言模式：不带标签，LLM 自动创作描述与歌词
        return prompt
    if mode == "step_lyrics2music":
        parts = []
        if prompt:
            parts.append(_tag("prompt", prompt))
        parts.append(_tag("lyrics", lyrics))
        return "\n".join(parts)
    # step_txt2music / step_instrumental：标签模式
    parts = []
    if prompt:
        parts.append(_tag("prompt", prompt))
    if lyrics and mode != "step_instrumental":  # 纯音乐忽略歌词
        parts.append(_tag("lyrics", lyrics))
    return "\n".join(parts)


def _validate(mode: str, prompt: str, lyrics: str):
    if mode not in STEP_MODES:
        raise ValueError(
            f"ACE-Step step music 不支持模式 '{mode}'（支持：{', '.join(STEP_MODES)}）——"
            "请在该节点的全局设置中选择「ACE-Step step music（免费）」接口。")
    if mode in ("step_txt2music", "step_instrumental", "step_natural") and not prompt.strip():
        raise ValueError("提示词为空：请在节点上填写提示词，或连接上游文本输入。")
    if mode == "step_lyrics2music" and not lyrics.strip():
        raise ValueError("歌词为空：请在节点上填写歌词，或连接上游歌词输入。")


# ─────────────────────────────────────────────────────────────────────────────
# HTTP 基础
# ─────────────────────────────────────────────────────────────────────────────
def _post_json(url: str, body: dict, api_key: str, timeout: int = 60) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps({k: v for k, v in body.items() if v is not None}).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": _BROWSER_UA,
                 "Accept": "application/json"},
    )
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        if e.code == 401:
            raise RuntimeError(
                "ACE-Step API 鉴权失败（401）：云端模式请先在 acemusic.ai/api-key "
                "免费领取 API Key，并填入【全局设置 → 密钥管理器】"
                "（密钥名称 ACESTEP_API_KEY）；本地整合包模式请检查服务端 ACESTEP_API_KEY。"
                f" {detail}") from e
        raise RuntimeError(f"ACE-Step API 请求失败（HTTP {e.code}）：{detail or e.reason}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"ACE-Step API 无法连接：{e.reason}（地址 {url}；"
            "本地模式请确认整合包 API 服务已启动）") from e


def _download(url: str, api_key: str, dest: str, timeout: int = 300):
    req = urllib.request.Request(url, headers={"User-Agent": _BROWSER_UA})
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    with open(dest, "wb") as f:
        f.write(data)


# ─────────────────────────────────────────────────────────────────────────────
# 云端契约：POST /v1/chat/completions（同步，base64 内联）
# ─────────────────────────────────────────────────────────────────────────────
def _run_cloud(base, model, mode, prompt, lyrics, opts, output_dir, api_key):
    """云端契约：OpenRouter 兼容同步接口。

    云端不支持 batch_size 参数——批次生成通过循环多次请求实现：
    每次请求 1 首，请求之间间隔 _CLOUD_BATCH_INTERVAL 秒连续发起。
    """
    instrumental = mode == "step_instrumental"
    batch = max(1, int(opts.get("batch_size") or 1))
    body = {
        "model": model,
        "stream": False,
        "messages": [{"role": "user", "content": build_content(mode, prompt, lyrics)}],
        "duration": opts.get("duration"),
        "bpm": opts.get("bpm"),
        "instrumental": instrumental or None,
        "thinking": bool(opts.get("thinking")),
        "use_cot_caption": bool(opts.get("lm_optimize")),
        "temperature": opts.get("temperature"),
        "top_p": opts.get("top_p"),
        "audio_format": opts.get("audio_format"),
        "inference_steps": opts.get("inference_steps"),
        "guidance_scale": opts.get("guidance_scale"),
        "seed": opts.get("seed"),
        "time_signature": opts.get("time_signature"),  # 留空由模型决定（_post_json 过滤 None）
    }
    if not instrumental:
        body["vocal_language"] = opts.get("vocal_language") or "en"

    url = f"{base}/v1/chat/completions"
    timeout = int(opts.get("timeout") or 900)
    ext = ".mp3" if (opts.get("audio_format") or "mp3") == "mp3" else f".{opts.get('audio_format')}"
    os.makedirs(output_dir, exist_ok=True)

    t0 = time.time()
    paths, contents, res_ids = [], [], []
    for i in range(batch):
        if i > 0:
            time.sleep(_CLOUD_BATCH_INTERVAL)
        try:
            res = _post_json(url, body, api_key, timeout=timeout)
        except Exception as e:
            if i == 0:
                raise
            logger.warning("ACE-Step 云端批次第 %s/%s 次请求失败（%s），已保留前 %s 个产物",
                           i + 1, batch, e, len(paths))
            break
        try:
            msg = (res.get("choices") or [{}])[0].get("message") or {}
            audio_entries = msg.get("audio") or []
            content = msg.get("content", "")
        except (IndexError, AttributeError, TypeError):
            if i == 0:
                raise RuntimeError(f"ACE-Step 云 API 响应格式异常：{str(res)[:300]}")
            logger.warning("ACE-Step 云端批次第 %s/%s 次响应异常，已保留前 %s 个产物",
                           i + 1, batch, len(paths))
            break

        if not audio_entries:
            err = res.get("detail") or content or str(res)[:300]
            if i == 0:
                raise RuntimeError(f"ACE-Step 云 API 未返回音频：{err}")
            logger.warning("ACE-Step 云端批次第 %s/%s 次未返回音频，已保留前 %s 个产物",
                           i + 1, batch, len(paths))
            break

        for entry in audio_entries:
            aurl = (entry.get("audio_url") or {}).get("url", "")
            if not aurl:
                continue
            b64 = aurl.split(",", 1)[1] if "," in aurl else aurl
            fp = os.path.join(output_dir, f"acestep_{len(paths) + 1}{ext}")
            with open(fp, "wb") as f:
                f.write(base64.b64decode(b64))
            paths.append(fp)
        contents.append(content or "")
        res_ids.append(str(res.get("id") or ""))

    if not paths:
        raise RuntimeError("ACE-Step 云 API 音频条目为空")

    # LM 生成元数据 / 歌词落盘供排查
    content = "\n\n".join(c for c in contents if c)
    if content:
        try:
            with open(os.path.join(output_dir, "_acestep_meta.txt"), "w", encoding="utf-8") as f:
                f.write(content)
        except OSError:
            pass
    logger.info("ACE-Step 云 API 生成完成：%s（%s 批次，%.0fs）",
                ", ".join(os.path.basename(p) for p in paths),
                f"{len(res_ids)}/{batch}", time.time() - t0)
    return paths, {"task_id": ",".join(x for x in res_ids if x), "contract": "cloud",
                   "content": content, "model": model}


# ─────────────────────────────────────────────────────────────────────────────
# 本地契约：/release_task → /query_result 轮询 → /v1/audio 下载
# ─────────────────────────────────────────────────────────────────────────────
def _run_native(base, model, mode, prompt, lyrics, opts, output_dir, api_key):
    instrumental = mode == "step_instrumental"
    payload = {
        "task_type": "text2music",
        "prompt": prompt,
        "lyrics": ("[Instrumental]" if instrumental else lyrics) or "",
        "instrumental": instrumental or None,
        "thinking": bool(opts.get("thinking")),
        "use_cot_caption": bool(opts.get("lm_optimize")),
        "model": model,
        "inference_steps": int(opts.get("inference_steps") or 8),
        "audio_duration": opts.get("duration"),
        "audio_format": opts.get("audio_format"),
        "batch_size": int(opts.get("batch_size") or 1),
        "vocal_language": None if instrumental else (opts.get("vocal_language") or "en"),
        "bpm": opts.get("bpm"),
        "key_scale": opts.get("key_scale"),
        "seed": opts.get("seed"),
    }
    if opts.get("seed") is None:
        payload["use_random_seed"] = True
        payload["seed"] = None
    if opts.get("time_signature"):  # 节拍：留空由模型决定，不传参数
        payload["time_signature"] = int(opts["time_signature"])

    api_key = api_key  # 本地服务未启用鉴权时留空即可
    info = _post_json(f"{base}/release_task", payload, api_key, timeout=60)
    data = info.get("data") if isinstance(info.get("data"), dict) else info
    task_id = (data.get("task_id") or data.get("job_id") or "")
    if not task_id:
        raise RuntimeError(f"ACE-Step 本地服务未返回 task_id：{str(info)[:300]}")

    deadline = time.time() + float(opts.get("timeout") or 900)
    interval = float(opts.get("poll_interval") or 3)
    while time.time() < deadline:
        time.sleep(interval)
        try:
            res = _post_json(f"{base}/query_result",
                             {"task_id_list": [task_id]}, api_key, timeout=30)
        except Exception as e:  # 网络抖动继续轮询
            logger.warning("ACE-Step 轮询异常（重试）: %s", e)
            continue
        items = res.get("data") or []
        if isinstance(items, dict):
            items = items.get("tasks") or [items]
        entry = next((t for t in items if isinstance(t, dict) and
                      str(t.get("task_id")) == str(task_id)), None)
        if entry is None:
            continue
        status = entry.get("status")
        if status == 2 or str(status).lower() in ("failed", "error"):
            raise RuntimeError(f"ACE-Step 任务失败：{str(entry)[:300]}")
        if status == 1 or str(status).lower() in ("succeeded", "completed", "success"):
            return _collect_native_results(base, entry, api_key, opts, output_dir, task_id, model)
        # status 0：排队 / 执行中，继续轮询
    raise RuntimeError(f"ACE-Step 任务 {task_id} 轮询超时")


def _collect_native_results(base, entry, api_key, opts, output_dir, task_id, model):
    """解析 result（JSON 字符串数组）→ 下载 /v1/audio 音频。"""
    raw = entry.get("result") or "[]"
    try:
        results = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        results = []
    if not isinstance(results, list):
        results = [results]

    os.makedirs(output_dir, exist_ok=True)
    paths = []
    fmt = opts.get("audio_format") or "mp3"
    for i, item in enumerate(results):
        if not isinstance(item, dict):
            continue
        file_ref = item.get("file") or ""
        if not file_ref:
            continue
        ext = f".{fmt}" if not os.path.splitext(file_ref)[1] else os.path.splitext(file_ref)[1]
        fp = os.path.join(output_dir, f"acestep_{i + 1}{ext}")
        if file_ref.startswith("http"):
            _download(file_ref, api_key, fp)
        else:
            _download(f"{base}{file_ref}", api_key, fp)
        paths.append(fp)
    if not paths:
        raise RuntimeError(f"ACE-Step 任务已完成但未找到音频：{str(entry)[:300]}")
    meta = {"task_id": task_id, "contract": "native", "model": model,
            "metas": results[0].get("metas") if results else None,
            "seed_value": results[0].get("seed_value") if results else None}
    return paths, meta


# ─────────────────────────────────────────────────────────────────────────────
# 工厂入口（SDKMagicGen 动态调用）
# ─────────────────────────────────────────────────────────────────────────────
async def generate(
    prompt: str,
    output_dir: str,
    model: str = "",
    mode: str = "step_txt2music",
    api_key: str = "",
    api_url: str = "",
    api_mode: str = "",
    api_type: str = "",
    **kwargs,
) -> list:
    """生成音乐并把产物落盘到 output_dir，返回本地文件路径列表。

    参数来源优先级：节点配置（kwargs）> 接口 JSON 模型参数（model_metadata.*.params）
    > sdk_extra_args > 本模块默认值（_DEFAULTS）。
    """
    mode = _MODE_ALIASES.get(mode, mode)
    opts = dict(_DEFAULTS)
    for key in ("audio_format", "vocal_language", "key_scale"):
        v = kwargs.get(key)
        if v not in (None, ""):
            opts[key] = str(v).strip()
    # 节拍（time_signature）：可选 2/3/4/6（对应 2/4、3/4、4/4、6/8 拍），留空由模型决定
    ts = str(kwargs.get("time_signature") or "").strip()
    opts["time_signature"] = int(ts) if ts.isdigit() else None
    for key in ("duration", "bpm", "seed", "batch_size"):
        v = kwargs.get(key)
        if v not in (None, ""):
            try:
                opts[key] = float(v) if key == "duration" else int(float(v))
            except (TypeError, ValueError):
                pass
    for key in ("inference_steps", "guidance_scale", "temperature", "top_p"):
        v = kwargs.get(key)
        if v not in (None, ""):
            try:
                opts[key] = float(v) if key in ("guidance_scale", "temperature", "top_p") else int(float(v))
            except (TypeError, ValueError):
                pass
    opts["timeout"] = int(kwargs.get("timeout") or kwargs.get("poll_timeout") or opts["timeout"])
    # LM 优化提示词 / 深度思考：节点设置项，缺省沿用默认（优化开、思考关）
    opts["lm_optimize"] = bool(kwargs.get("lm_optimize", opts["lm_optimize"]))
    opts["thinking"] = bool(kwargs.get("thinking", opts["thinking"]))

    lyrics = str(kwargs.get("lyrics") or "")
    prompt = str(prompt or "")
    _validate(mode, prompt, lyrics)

    api_key = _resolve_api_key(api_key)
    # 分路优先级：模型选择值（历史兼容）> 节点「接口类型」（api_type）> 接口 api_mode
    route = _resolve_selection_route(model, api_url)
    if route is None:
        route = _resolve_selection_route(api_type, api_url)
    if route is not None:
        base, contract = route
        model = _normalize_model(model, contract)
    else:
        base, contract = _resolve_route(api_url or DEFAULT_CLOUD_API_URL, api_mode)
        model = _normalize_model(model, contract)

    logger.info("ACE-Step step music：%s / %s / %s → %s (%s)",
                mode, model, opts.get("duration"), base, contract)
    if contract == "cloud":
        paths, meta = _run_cloud(base, model, mode, prompt, lyrics, opts, output_dir, api_key)
    else:
        paths, meta = _run_native(base, model, mode, prompt, lyrics, opts, output_dir, api_key)

    # 结果元数据落盘（供 step 层生成参数 JSON；结构与 kieai wrapper 对齐）
    # paths 记录全部产物（批次生成数量 > 2 时超出 audio_1/audio_2 端口的产物在此可见）
    meta.update({"mode": mode, "prompt": prompt, "lyrics": lyrics,
                 "paths": [os.path.basename(p) for p in paths],
                 "tracks": [], "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    try:
        with open(os.path.join(output_dir, "_musicgen_result.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
    return paths

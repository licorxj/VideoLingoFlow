#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""火山引擎方舟 Seedance 视频生成 SDK（requests 直连，异步任务模式）。

直连：
  - 创建任务：POST https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks
  - 查询任务：GET  https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks/{id}
  - 上传文件：POST https://ark.cn-beijing.volces.com/api/v3/files  （本地素材 -> asset:// 引用）

Seedance 是异步任务接口：本模块负责「组装请求体 + 提交任务 + 轮询至终态 + 下载产物 + 落盘」，
不感知 VideoLingo 业务概念（mode / 分辨率档位等由 seedance_wrapper 适配），便于单独复用与测试。

官方文档要点（详见 _TASK_TYPES / _PARAM_NOTES）：
  - content 元素支持：text / image_url / video_url / audio_url / draft_task
  - 图生视频-首帧：1 张 image_url，role=first_frame（或不填）
  - 图生视频-首尾帧：2 张 image_url，role=first_frame / last_frame
  - 全模态参考生视频：reference_image(role) + reference_video(role) + reference_audio(role)
  - 视频产物通过 content.video_url 返回（URL 有效期 24h），可选 last_frame_url
  - 鉴权：请求头 Authorization: Bearer <API Key>

素材引用规则（_resolve_media）：
  - image_url.url / audio_url.url：支持 URL / Base64(data:) / asset://
  - video_url.url：官方不支持 Base64，**本地视频自动走 /api/v3/files 上传**，得到 file id 后以
    asset://{id} 引用（图片/音频本地文件仍走 Base64，无需上传）
"""
import os
import time
import json
import base64
import logging
import requests
from typing import Callable, Optional

logger = logging.getLogger(__name__)

SEEDANCE_TASK_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"
SEEDANCE_FILE_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3/files"

# 文件上传默认用途（方舟 files 接口必填项；user_data = 通用用户素材）
DEFAULT_FILE_PURPOSE = "user_data"
# 上传后等待文件处理就绪的超时（秒）；视频会上传后在平台侧做抽帧等预处理
DEFAULT_FILE_READY_TIMEOUT = 180

# 已知模型 ID（用户可在 UI 中替换为自己的 Model ID / Endpoint ID）
SEEDANCE_MODELS = [
    "doubao-seedance-2-5-pro-260628",
    "doubao-seedance-2-0-pro-260528",
    "doubao-seedance-1-5-pro-251215",
    "doubao-seedance-1-0-pro-250528",
]
DEFAULT_MODEL = "doubao-seedance-2-5-pro-260628"

# 轮询默认参数（视频生成耗时较长）
DEFAULT_POLL_INTERVAL = 5        # 秒
DEFAULT_POLL_TIMEOUT = 1800      # 秒

# 终态集合
_TERMINAL = {"succeeded", "failed", "cancelled", "expired"}


# ---------------------------------------------------------------------------
# 模型能力矩阵（按 model 前缀匹配；用于合法性兜底与参数裁剪）
# ---------------------------------------------------------------------------
# resolutions: 该模型支持的分辨率集合（文档中的 resolution 取值）
# duration: [min, max] 取值区间（整数秒）；-1 代表智能选择（由模型决定长度）
# supports: 各专属能力是否支持
_MODEL_FAMILY = {
    "doubao-seedance-2-5": {
        "resolutions": {"480p", "720p", "1080p"},
        "duration": [4, 30], "allow_neg1": True,
        "ratio_default": "adaptive",
        "supports": {"generate_audio", "output_format_mov", "seed", "camera_fixed",
                     "omni", "tools_web_search", "priority", "return_last_frame", "draft"},
    },
    "doubao-seedance-2-0": {
        "resolutions": {"480p", "720p", "1080p", "4k"},
        "duration": [4, 15], "allow_neg1": True,
        "ratio_default": "adaptive",
        "supports": {"generate_audio", "seed", "omni", "tools_web_search", "priority",
                     "return_last_frame", "draft"},
    },
    "doubao-seedance-1-5": {
        "resolutions": {"480p", "720p", "1080p"},
        "duration": [4, 12], "allow_neg1": True,
        "ratio_default": "adaptive",
        "supports": {"generate_audio", "seed", "camera_fixed", "return_last_frame", "draft",
                     "service_tier_flex"},
    },
    "doubao-seedance-1-0": {
        "resolutions": {"480p", "720p", "1080p"},
        "duration": [2, 12], "allow_neg1": False,
        "ratio_default": "16:9",
        "supports": {"generate_audio", "seed", "camera_fixed"},
    },
}


def _family(model: str) -> dict:
    """按 model 前缀匹配能力矩阵，未命中返回 2.5 的宽松集合。"""
    if not model:
        return _MODEL_FAMILY["doubao-seedance-2-5"]
    for prefix, fam in _MODEL_FAMILY.items():
        if model.startswith(prefix):
            return fam
    return _MODEL_FAMILY["doubao-seedance-2-5"]


def _get_api_key(api_key: str = "") -> str:
    """API Key 取值优先级: 函数参数 > 环境变量 ARK_API_KEY。"""
    return os.environ.get("ARK_API_KEY", "") or api_key


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# 文件 -> 可提交载荷
# ---------------------------------------------------------------------------
def _normalize_resolution(resolution: str) -> str:
    """统一为小写（前端常传 720P，官方用 720p）。"""
    if not resolution:
        return "720p"
    return resolution.strip().lower()


def _resolve_media(ref, kind: str, api_key: str = ""):
    """把参考素材（本地路径 / http(s) URL / data URI / asset://）解析为可直接提交的 url 字符串。

    kind: "image" | "video" | "audio"。
    返回 (url_str, error)。Seedance 规则：
      - image_url.url / audio_url.url：接受 URL / Base64(data:) / asset://
      - video_url.url：**不支持 Base64**，本地视频自动走 /api/v3/files 上传 -> asset://{id}
        其余（URL / asset:// / data URI）原样透传。
    """
    if not isinstance(ref, str) or not ref:
        return None, "空素材"
    if ref.startswith("data:") or ref.startswith("asset://"):
        return ref, None
    if ref.startswith("http://") or ref.startswith("https://"):
        return ref, None
    if os.path.exists(ref):
        if kind == "video":
            # 官方文档：video_url 仅接受 URL / asset://，本地视频需先上传到方舟
            try:
                fid = _upload_file(ref, api_key=api_key)
                _wait_file_ready(fid, api_key=api_key)
                return f"asset://{fid}", None
            except Exception as e:
                return None, f"本地视频上传失败: {e}"
        try:
            ext = os.path.splitext(ref)[1].lstrip(".").lower() or "png"
            mime = {
                "jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp",
                "bmp": "bmp", "gif": "gif", "tiff": "tiff", "heic": "heic",
            }.get(ext, "png") if kind == "image" else {
                "wav": "wav", "mp3": "mp3", "m4a": "m4a",
            }.get(ext, "wav")
            prefix = "image" if kind == "image" else "audio"
            with open(ref, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            return f"data:{prefix}/{mime};base64,{b64}", None
        except Exception as e:
            return None, f"读取素材失败: {e}"
    return None, f"无效素材: {ref}"


# ---------------------------------------------------------------------------
# 文件上传（方舟 files 接口）
# ---------------------------------------------------------------------------
def _upload_file(file_path: str, api_key: str = "", purpose: str = DEFAULT_FILE_PURPOSE,
                 expire_at: int = None) -> str:
    """上传本地文件到方舟平台，返回 file id（供内容以 asset://{id} 引用）。

    接口：POST /api/v3/files  （multipart: file=@path, purpose=user_data）
    响应：{"object":"file","id":"file-...","purpose":"user_data",...,"status":"processing"}
    """
    api_key = _get_api_key(api_key)
    if not api_key:
        raise RuntimeError("未配置 API Key（接口设置或环境变量 ARK_API_KEY）")
    if not os.path.exists(file_path):
        raise RuntimeError(f"Seedance: 待上传文件不存在: {file_path}")

    logger.info("Seedance 上传文件 %s purpose=%s", file_path, purpose)
    with open(file_path, "rb") as f:
        files = {"file": (os.path.basename(file_path), f)}
        data = {"purpose": purpose}
        if expire_at:
            data["expire_at"] = str(int(expire_at))
        resp = requests.post(
            SEEDANCE_FILE_ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}"},
            files=files, data=data, timeout=300,
        )
    if resp.status_code != 200:
        snip = resp.text[:800]
        raise RuntimeError(f"Seedance 上传文件 HTTP {resp.status_code}: {snip}")
    data = resp.json()
    if data.get("error"):
        err = data["error"]
        raise RuntimeError(f"Seedance 上传文件错误 [{err.get('code')}]: {err.get('message')}")
    fid = data.get("id")
    if not fid:
        raise RuntimeError(f"Seedance: 上传响应缺少 id: {json.dumps(data, ensure_ascii=False)[:300]}")
    logger.info("Seedance 文件已上传 id=%s status=%s", fid, data.get("status"))
    return fid


def _wait_file_ready(file_id: str, api_key: str = "", timeout: int = DEFAULT_FILE_READY_TIMEOUT):
    """轮询文件对象状态直到 available（视频需平台侧抽帧等预处理）。

    超时仅告警不抛错（生成任务侧仍会引用该 asset；若确未就绪由生成接口报错）。
    """
    api_key = _get_api_key(api_key)
    waited = 0
    interval = 3
    while waited <= timeout:
        try:
            resp = requests.get(
                f"{SEEDANCE_FILE_ENDPOINT}/{file_id}",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=30,
            )
            d = resp.json()
        except Exception as e:
            logger.warning("Seedance: 查询文件 %s 状态失败: %s", file_id, e)
            return None
        st = d.get("status")
        if st == "available":
            return d
        if st == "failed":
            err = d.get("error") or {}
            raise RuntimeError(f"Seedance 文件处理失败[{file_id}]: {err.get('message')}")
        time.sleep(interval)
        waited += interval
    logger.warning("Seedance: 文件 %s 未在 %ss 内处理就绪，尝试直接使用", file_id, timeout)
    return None


def upload_file(file_path: str, api_key: str = "", purpose: str = DEFAULT_FILE_PURPOSE,
                expire_at: int = None):
    """对外暴露：上传本地文件并返回 asset:// 引用字符串。"""
    fid = _upload_file(file_path, api_key=api_key, purpose=purpose, expire_at=expire_at)
    return f"asset://{fid}"


# ---------------------------------------------------------------------------
# content 组装
# ---------------------------------------------------------------------------
def build_content(prompt: str, ref_images=None, ref_videos=None, ref_audios=None,
                  mode: str = "txt2video", api_key: str = "") -> list:
    """根据 mode 组装 Seedance content 列表（官方能力类型映射）。

    mode 映射（与 backend/videogen 服务层一致）：
      txt2video : 纯文本
      img2video : 图生视频-首帧（1 张 image_url, role=first_frame）
      flf2video : 图生视频-首尾帧（2 张 image_url, role=first_frame/last_frame）
      autovideo : 全模态参考生视频（reference_image + reference_video + reference_audio 任意组合）

    api_key: 用于本地视频素材经 /api/v3/files 上传后获取 asset:// 引用。
    """
    content = []
    if prompt:
        content.append({"type": "text", "text": prompt})

    if mode == "img2video":
        imgs = (ref_images or [])[:1]
        for img in imgs:
            url, err = _resolve_media(img, "image", api_key=api_key)
            if err:
                logger.warning("Seedance: 首帧图解析失败: %s", err)
                continue
            content.append({"type": "image_url", "image_url": {"url": url}, "role": "first_frame"})
    elif mode == "flf2video":
        imgs = (ref_images or [])[:2]
        roles = ["first_frame", "last_frame"]
        for img, role in zip(imgs, roles):
            url, err = _resolve_media(img, "image", api_key=api_key)
            if err:
                logger.warning("Seedance: 首尾帧图[%s]解析失败: %s", role, err)
                continue
            content.append({"type": "image_url", "image_url": {"url": url}, "role": role})
    elif mode == "autovideo":
        # 全模态参考生视频：三种素材互斥于首/尾帧场景，可任意组合
        for img in (ref_images or []):
            url, err = _resolve_media(img, "image", api_key=api_key)
            if err:
                logger.warning("Seedance: 参考图解析失败: %s", err)
                continue
            content.append({"type": "image_url", "image_url": {"url": url}, "role": "reference_image"})
        for vid in (ref_videos or []):
            url, err = _resolve_media(vid, "video", api_key=api_key)
            if err:
                logger.warning("Seedance: 参考视频解析失败: %s", err)
                continue
            content.append({"type": "video_url", "video_url": {"url": url}, "role": "reference_video"})
        for aud in (ref_audios or []):
            url, err = _resolve_media(aud, "audio", api_key=api_key)
            if err:
                logger.warning("Seedance: 参考音频解析失败: %s", err)
                continue
            content.append({"type": "audio_url", "audio_url": {"url": url}, "role": "reference_audio"})
    # txt2video: 仅文本，content 已含 text
    return content


# ---------------------------------------------------------------------------
# 任务提交 / 查询 / 轮询
# ---------------------------------------------------------------------------
def create_task(body: dict, api_key: str = "", timeout: int = 60) -> str:
    """提交视频生成任务，返回 task id。"""
    api_key = _get_api_key(api_key)
    if not api_key:
        raise RuntimeError("未配置 API Key（接口设置或环境变量 ARK_API_KEY）")
    if not body.get("model"):
        raise RuntimeError("Seedance: 缺少 model")
    if not body.get("content"):
        raise RuntimeError("Seedance: 缺少 content（提示词或参考素材）")

    # 调试：打印每次请求的原始参数（剔除密钥字段）
    _debug_body = {k: v for k, v in body.items() if k not in ("api_key", "authorization")}
    logger.info(
        "Seedance 创建任务 model=%s endpoint=%s body=%s",
        body.get("model"), SEEDANCE_TASK_ENDPOINT,
        json.dumps(_debug_body, ensure_ascii=False),
    )

    resp = requests.post(
        SEEDANCE_TASK_ENDPOINT,
        headers=_headers(api_key),
        json=body,
        timeout=timeout,
    )
    if resp.status_code != 200:
        snip = resp.text[:800]
        raise RuntimeError(f"Seedance 创建任务 HTTP {resp.status_code}: {snip}")
    data = resp.json()
    if data.get("error"):
        err = data["error"]
        raise RuntimeError(f"Seedance 创建任务错误 [{err.get('code')}]: {err.get('message')}")
    task_id = data.get("id")
    if not task_id:
        raise RuntimeError(f"Seedance: 响应缺少任务 ID: {json.dumps(data, ensure_ascii=False)[:300]}")
    return task_id


def query_task(task_id: str, api_key: str = "", timeout: int = 60) -> dict:
    """查询任务状态，返回完整 task 字典。"""
    api_key = _get_api_key(api_key)
    resp = requests.get(
        f"{SEEDANCE_TASK_ENDPOINT}/{task_id}",
        headers=_headers(api_key),
        timeout=timeout,
    )
    if resp.status_code != 200:
        snip = resp.text[:500]
        raise RuntimeError(f"Seedance 查询任务 HTTP {resp.status_code}: {snip}")
    return resp.json()


def _poll_until_done(task_id: str, api_key: str, poll_interval: int, poll_timeout: int,
                     on_progress: Optional[Callable[[str], None]] = None) -> dict:
    """轮询任务直到终态，返回最终 task 字典。"""
    waited = 0
    last_status = None
    while waited <= poll_timeout:
        data = query_task(task_id, api_key)
        status = data.get("status")
        if status != last_status:
            last_status = status
            if on_progress:
                on_progress(f"任务 {task_id} 状态：{status}")
            logger.info("Seedance 任务 %s 状态 %s", task_id, status)
        if status in _TERMINAL:
            if status == "succeeded":
                return data
            err = data.get("error") or {}
            msg = err.get("message") or f"任务终态 {status}"
            raise RuntimeError(f"Seedance 任务失败[{status}]: {msg}")
        time.sleep(poll_interval)
        waited += poll_interval
    raise TimeoutError(f"Seedance 任务轮询超时 (>{poll_timeout}s), taskId={task_id}")


# ---------------------------------------------------------------------------
# 下载产物
# ---------------------------------------------------------------------------
def _download(url: str, save_dir: str, index: int, ext_hint: str = "mp4") -> str:
    os.makedirs(save_dir, exist_ok=True)
    resp = requests.get(url, timeout=300, stream=True)
    resp.raise_for_status()
    ct = resp.headers.get("content-type", "").lower()
    if "webm" in ct:
        ext = "webm"
    elif "mov" in ct or "quicktime" in ct:
        ext = "mov"
    elif "png" in ct:
        ext = "png"
    else:
        ext = ext_hint or "mp4"
    path = os.path.join(save_dir, f"output_{index}.{ext}")
    with open(path, "wb") as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)
    logger.info("Seedance: 已保存 %s", path)
    return path


# ---------------------------------------------------------------------------
# 统一底层入口
# ---------------------------------------------------------------------------
def generate_video(body: dict, api_key: str = "", save_dir: str = "",
                   poll_interval: int = DEFAULT_POLL_INTERVAL,
                   poll_timeout: int = DEFAULT_POLL_TIMEOUT,
                   on_progress: Optional[Callable[[str], None]] = None,
                   raise_on_error: bool = False):
    """底层调用：组装最终请求体、提交任务、轮询、下载并落盘。

    Args:
        body: 已组装好的完整请求体（model / content / resolution / ratio / ...）。
        api_key: 火山方舟 API Key（ARK_API_KEY 环境变量可兜底）。
        save_dir: 落盘目录。
        poll_interval / poll_timeout: 轮询参数。
        on_progress: 进度回调。
        raise_on_error: True 时异常上抛，便于节点层展示真实原因。
    Returns:
        dict: {"videos": [path...], "last_frame": path|None, "task_id": str,
               "video_url": str|None}
        失败时按 raise_on_error 决定抛异常或返回 {"videos": [], ...}。
    """
    empty = {"videos": [], "last_frame": None, "task_id": None, "video_url": None}
    try:
        task_id = create_task(body, api_key=api_key)
        if on_progress:
            on_progress(f"任务已提交 {task_id}，等待生成…")
        task = _poll_until_done(
            task_id, api_key, poll_interval, poll_timeout, on_progress=on_progress)
        content = task.get("content") or {}
        video_url = content.get("video_url")
        last_frame_url = content.get("last_frame_url")
        videos = []
        if video_url:
            ext = "mov" if (task.get("output_format") == "mov") else "mp4"
            videos.append(_download(video_url, save_dir, 0, ext))
        last_frame = None
        if last_frame_url:
            last_frame = _download(last_frame_url, save_dir, 0, "png")
        if not videos:
            raise RuntimeError("Seedance: 任务成功但响应中无 video_url")
        return {"videos": videos, "last_frame": last_frame,
                "task_id": task_id, "video_url": video_url}
    except Exception as e:
        if raise_on_error:
            raise
        logger.error("Seedance: 调用失败: %s", e)
        import traceback
        traceback.print_exc()
        return empty


def list_models(api_key: str = ""):
    """返回已知 Seedance 模型 ID 列表。"""
    return list(SEEDANCE_MODELS)

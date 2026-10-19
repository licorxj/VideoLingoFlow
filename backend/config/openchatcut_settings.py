"""OpenChatCut（AI剪辑台）设置 → 环境变量映射（纯函数，无 Web 框架依赖）。

被两处引用：
- ``backend/api/openchatcut.py``：保存设置时生成 .env.local 并热推送 /api/keys；
- ``backend/manager.py``：启动 OpenChatCut 进程时把同一组变量注入子进程 env
  （isolated-dev 模式下 settings.env 一旦存在，.env.local 不再被读取，
  进程 env 是该模式官方设计的注入通道）。

合规说明：只写运行时配置文件与进程环境，不修改 OpenChatCut 源码。
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OPENCHATCUT_DIR = PROJECT_ROOT / "thirdparty" / "openchatcut"
ENV_FILE = OPENCHATCUT_DIR / ".env.local"

DEFAULT_PORT = 5199
DEFAULT_HOST = "127.0.0.1"
# 主后端端口（manager 默认 11001，vite 代理 /api 也指向它）
BACKEND_PORT = str(os.environ.get("VIDEOLINGO_BACKEND_PORT") or "11001")
# Agent 大模型默认模型名（主项目 LLM 路由中的剪辑台专用策略/模型）
DEFAULT_LLM_MODEL = "vlf-agent"
# Agent 大模型默认接入地址：直连本项目 LLM 路由器（OpenAI 兼容 /v1）。
# 路由器自身已完成上游选路、故障转移与真实密钥管理，且不校验调用方密钥。
LLM_ROUTER_PORT = str(os.environ.get("LLM_ROUTER_PORT") or "8800")
DEFAULT_LLM_BASE_URL = f"http://localhost:{LLM_ROUTER_PORT}/v1"

_SECTIONS = ("llm", "image", "tts", "video", "mcp")

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "host": DEFAULT_HOST,
    "port": DEFAULT_PORT,
    # Agent 大模型：默认直连本项目 LLM 路由器（OpenAI 兼容 /v1/chat/completions）。
    # 路由器不校验调用方密钥：留空时由 ensure_api_keys() 随机生成占位值即可
    "llm": {
        "provider": "openai",
        "base_url": DEFAULT_LLM_BASE_URL,
        "api_key": "",
        "model": DEFAULT_LLM_MODEL,
    },
    # 生图 / TTS：OpenChatCut 的 image 与 voice/openai 共用 IMAGE_BASE_URL，
    # 统一指向本项目桥接端 /api/openchatcut-bridge/v1。
    # 生图按请求是否带参考图解耦：无参考图 → txt2img_model，有参考图 → img2img_model
    "image": {
        "base_url": f"http://127.0.0.1:{BACKEND_PORT}/api/openchatcut-bridge/v1",
        "api_key": "",
        "model": "",
        "txt2img_model": "",
        "img2img_model": "",
        "interface_id": "",
    },
    # TTS：base_url 留空表示复用 image.base_url（同一桥接端）
    "tts": {
        "base_url": "",
        "api_key": "",
        "model": "",
        "interface_id": "",
    },
    # 生视频：注入 SEEDANCE_*（火山方舟 / 兼容端点），留空则不注入
    "video": {"base_url": "", "api_key": "", "model": ""},
    # 外部 MCP 访问令牌（OpenChatCut 的 /api/external-mcp/mcp，仅启动时生效）。
    # 外部 Agent 直连剪辑台端口，不经本项目转发；留空时自动随机生成，始终保持开启
    "mcp": {"token": ""},
    # Agent 本地媒体浏览/导入根目录（桌面端默认不限；浏览器模式必须白名单）
    "agent_import_roots": "",
    # OpenChatCut 媒体目录（留空用其默认 public/media/uploads/）
    "media_dir": "",
}


def random_api_key() -> str:
    """生成一个随机占位密钥。

    llm / image / tts 的请求都经本项目桥接端转发，真实密钥由主项目自身配置提供，
    桥接端不校验该值；但 OpenChatCut 侧要求非空（否则探活/请求被判为未配置）。
    因此这里随机生成一个占位值，避免用户在设置页纠结「该填什么 Key」。
    """
    return "vlf-occ-" + secrets.token_urlsafe(24)


def ensure_api_keys(cfg: dict[str, Any]) -> dict[str, Any]:
    """为桥接段（llm/image/tts）的空 api_key 填入随机占位值（原地修改并返回）。

    video（SEEDANCE 直连第三方）/ mcp（真实访问令牌）不在此列，需用户自行填写。
    """
    for section in ("llm", "image", "tts"):
        sub = cfg.get(section)
        if not isinstance(sub, dict):
            sub = {}
            cfg[section] = sub
        if not str(sub.get("api_key") or "").strip():
            sub["api_key"] = random_api_key()
    return cfg


def ensure_mcp_token(cfg: dict[str, Any]) -> dict[str, Any]:
    """为外部 MCP 端点生成访问令牌（原地修改并返回）。

    该端点由 OpenChatCut 自身对外暴露，本项目不转发请求，只负责注入令牌；
    外部访问默认开启，因此未配置时自动随机生成。
    """
    mcp = cfg.get("mcp")
    if not isinstance(mcp, dict):
        mcp = {}
        cfg["mcp"] = mcp
    if not str(mcp.get("token") or "").strip():
        mcp["token"] = random_api_key()
    return cfg


def workspace_root() -> str:
    root = os.environ.get("CONTROL_PLANE_WORKSPACE_ROOT")
    if root:
        return str(Path(root).resolve())
    return str((PROJECT_ROOT / "control_plane_workspaces").resolve())


def merge_defaults(stored: dict[str, Any] | None) -> dict[str, Any]:
    stored = stored if isinstance(stored, dict) else {}
    merged: dict[str, Any] = {}
    for key, value in DEFAULT_CONFIG.items():
        if key in _SECTIONS:
            sub = dict(value)
            incoming = stored.get(key)
            if isinstance(incoming, dict):
                sub.update({k: v for k, v in incoming.items() if v is not None})
            merged[key] = sub
        else:
            incoming = stored.get(key)
            merged[key] = value if incoming is None else incoming
    if not merged.get("agent_import_roots"):
        merged["agent_import_roots"] = workspace_root()
    # Agent 大模型默认填入 vlf-agent（历史配置里存了空串也回填默认）
    llm = merged.get("llm")
    if isinstance(llm, dict):
        if not str(llm.get("model") or "").strip():
            llm["model"] = DEFAULT_LLM_MODEL
        # 历史默认曾指向已下线的桥接中转地址 /api/cutia-bridge，
        # 现统一改为直连 LLM 路由器；用户显式填过其他地址则保持不动。
        base_url = str(llm.get("base_url") or "")
        if not base_url.strip() or "/api/cutia-bridge" in base_url:
            llm["base_url"] = DEFAULT_LLM_BASE_URL
    return merged


def env_pairs(cfg: dict[str, Any]) -> dict[str, str]:
    """把主项目设置映射为 OpenChatCut 环境变量。"""
    llm = cfg.get("llm") or {}
    image = cfg.get("image") or {}
    tts = cfg.get("tts") or {}
    video = cfg.get("video") or {}
    mcp = cfg.get("mcp") or {}

    pairs: dict[str, str] = {}
    provider = str(llm.get("provider") or "openai").strip() or "openai"
    pairs["LLM_PROVIDER"] = provider
    if provider == "openai":
        # chat 模式：OpenAI 兼容 /chat/completions（默认直连本项目 LLM 路由器 /v1）
        pairs["LLM_OPENAI_BASE_URL"] = str(llm.get("base_url") or "") or DEFAULT_LLM_BASE_URL
        # 路由器不校验调用方密钥，但要求非空：未配置时随机占位
        pairs["LLM_OPENAI_API_KEY"] = str(llm.get("api_key") or "") or random_api_key()
        pairs["LLM_OPENAI_MODEL"] = str(llm.get("model") or "")
        pairs["LLM_OPENAI_API_MODE"] = "chat"

    # 生图 + OpenAI TTS 共用 IMAGE_BASE_URL（OpenChatCut 服务端约定）
    pairs["IMAGE_BASE_URL"] = str(image.get("base_url") or "")
    pairs["IMAGE_API_KEY"] = str(image.get("api_key") or "") or random_api_key()
    pairs["OPENAI_API_KEY"] = str(tts.get("api_key") or image.get("api_key") or "") or random_api_key()
    tts_model = str(tts.get("model") or "")
    if tts_model:
        pairs["OPENAI_TTS_MODEL"] = tts_model

    video_base = str(video.get("base_url") or "")
    if video_base:
        pairs["SEEDANCE_BASE_URL"] = video_base
        pairs["SEEDANCE_API_KEY"] = str(video.get("api_key") or "")
        pairs["SEEDANCE_VIDEO_MODEL"] = str(video.get("model") or "")

    # 外部 MCP 访问默认开启：未配置令牌时自动随机生成
    pairs["OPENCHATCUT_MCP_TOKEN"] = str(mcp.get("token") or "") or random_api_key()

    host = str(cfg.get("host") or DEFAULT_HOST)
    port = int(cfg.get("port") or DEFAULT_PORT)
    pairs["OPENCHATCUT_EDITOR_URL"] = f"http://{host}:{port}"

    pairs["AGENT_IMPORT_ROOTS"] = str(cfg.get("agent_import_roots") or "") or workspace_root()

    media_dir = str(cfg.get("media_dir") or "")
    if media_dir:
        pairs["MEDIA_DIR"] = media_dir
    return pairs


# 可通过 POST /api/keys 热更新的键（其余仅启动时经 env 生效）
HOT_KEYS = (
    "LLM_PROVIDER",
    "LLM_OPENAI_BASE_URL",
    "LLM_OPENAI_API_KEY",
    "LLM_OPENAI_MODEL",
    "LLM_OPENAI_API_MODE",
    "IMAGE_BASE_URL",
    "IMAGE_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_TTS_MODEL",
    "SEEDANCE_BASE_URL",
    "SEEDANCE_API_KEY",
    "SEEDANCE_VIDEO_MODEL",
    "AGENT_IMPORT_ROOTS",
    "MEDIA_DIR",
)


def resolved_env_pairs(cfg: dict[str, Any]) -> dict[str, str]:
    """env_pairs + secret:// 引用还原（数据库不可用时原样返回，由调用方兜底）。"""
    pairs = env_pairs(cfg)
    try:
        from backend.config.credential_store import resolve_deep

        return {key: str(resolve_deep(value)) for key, value in pairs.items()}
    except Exception:  # noqa: BLE001
        return pairs

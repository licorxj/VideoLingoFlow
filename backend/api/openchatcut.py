"""OpenChatCut（thirdparty/openchatcut）接入管理 API。

合规边界（重要）：
- **不修改 OpenChatCut 源码**。所有参数通过其官方环境配置文件
  ``thirdparty/openchatcut/.env.local`` 注入（vite loadEnv 启动时读取），
  这是该项目文档化的配置入口，不属于源码改动。
- 本项目侧只写「桥接件」：OpenChatCut 的 Agent 大模型、生图、TTS
  经 ``/api/openchatcut-bridge/v1`` 路由回本项目已配置的接口层
  （LLM 路由器 / 生图接口 / TTS 接口），密钥只保留在本项目。
- 剪辑功能由 OpenChatCut 独立进程提供（默认 5199），主项目 UI 只放
  「打开剪辑台」按钮，新标签页跳转，不 iframe 内嵌。

配置存放在 settings（config.yaml）的 ``openchatcut`` 命名空间下；
设置 → 环境变量映射集中在 ``backend/config/openchatcut_settings.py``。
"""

from __future__ import annotations

import logging
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config.config_manager import config
from backend.config.credential_store import mask_deep
from backend.config.openchatcut_settings import (
    BACKEND_PORT,
    DEFAULT_PORT,
    ENV_FILE,
    HOT_KEYS,
    OPENCHATCUT_DIR,
    ensure_api_keys,
    ensure_mcp_token,
    env_pairs,
    merge_defaults,
    resolved_env_pairs,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/openchatcut", tags=["openchatcut"])

_INJECT_HEADER = "# ---- 以下由 VideoLingo「AI剪辑台」设置注入（勿手改，保存设置时会被覆盖） ----"


def _stored() -> dict:
    data = config.get("openchatcut", {}) or {}
    return data if isinstance(data, dict) else {}


def _merged() -> dict:
    return merge_defaults(_stored())


def _mask(cfg: dict) -> dict:
    masked = mask_deep(cfg)
    token = (cfg.get("mcp") or {}).get("token") or ""
    if token:
        masked["mcp"]["token"] = "***"
    return masked


def write_env_file(cfg: dict) -> dict[str, str]:
    """把设置合并写入 .env.local，保留用户手写的其它键与注释。"""
    pairs = resolved_env_pairs(cfg)
    managed = set(pairs)

    lines: list[str] = []
    if ENV_FILE.is_file():
        try:
            lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
        except OSError as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"读取 .env.local 失败: {exc}")

    output: list[str] = []
    seen: set[str] = set()
    for line in lines:
        match = re.match(r"^\s*([A-Za-z0-9_]+)\s*=", line)
        if match and match.group(1) in managed:
            key = match.group(1)
            if key in seen:
                continue  # 去掉重复定义，避免歧义
            seen.add(key)
            output.append(f"{key}={pairs[key]}")
        else:
            output.append(line)

    missing = [key for key in pairs if key not in seen]
    if missing:
        if output and output[-1].strip():
            output.append("")
        output.append(_INJECT_HEADER)
        output.extend(f"{key}={pairs[key]}" for key in missing)

    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    ENV_FILE.write_text("\n".join(output).rstrip("\n") + "\n", encoding="utf-8")
    return pairs


def _hot_push_keys(cfg: dict) -> bool:
    """把可热更新的键 POST 到 OpenChatCut 的 /api/keys（其设置面板同款接口）。

    isolated-dev 模式下 settings.env 一旦存在，.env.local 不再参与读取；
    /api/keys 会同时更新内存 keystore 并持久化，保存后无需重启即生效。
    服务未运行或请求失败时静默跳过（重启后经进程 env 生效）。
    """
    port = int(cfg.get("port") or DEFAULT_PORT)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.5):
            pass
    except OSError:
        return False

    import httpx

    pairs = resolved_env_pairs(cfg)
    patch = {key: pairs[key] for key in HOT_KEYS if key in pairs}
    if not patch:
        return False
    try:
        response = httpx.post(
            f"http://127.0.0.1:{port}/api/keys",
            json=patch,
            timeout=10.0,
            trust_env=False,
            # 上游对写请求有同源形状门禁（loopback + 同源 Origin + Sec-Fetch-Site）
            headers={
                "Origin": f"http://127.0.0.1:{port}",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        if response.status_code == 200:
            return True
        logger.warning("[openchatcut] 热推送 /api/keys 失败: HTTP %s %s", response.status_code, response.text[:200])
    except Exception as exc:  # noqa: BLE001
        logger.warning("[openchatcut] 热推送 /api/keys 异常: %s", exc)
    return False


class ConfigUpdate(BaseModel):
    enabled: bool | None = None
    host: str | None = None
    port: int | None = None
    llm: dict | None = None
    image: dict | None = None
    tts: dict | None = None
    video: dict | None = None
    mcp: dict | None = None
    agent_import_roots: str | None = None
    media_dir: str | None = None


@router.get("/config")
def get_config():
    """读取 AI剪辑台设置（密钥脱敏）。"""
    return {"config": _mask(_merged())}


@router.put("/config")
def update_config(req: ConfigUpdate):
    """保存设置并立即注入 OpenChatCut（.env.local + 运行中实例热更新）。"""
    stored = _stored()
    patch = req.model_dump(exclude_none=True)
    for key, value in patch.items():
        if key in ("llm", "image", "tts", "video", "mcp") and isinstance(value, dict):
            section = dict(stored.get(key) or {})
            section.update({k: v for k, v in value.items() if v is not None})
            stored[key] = section
        else:
            stored[key] = value
    if "port" in stored:
        try:
            stored["port"] = int(stored["port"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="端口必须为整数")
    # 桥接段（llm/image/tts）的 api_key 无需用户填写：为空时随机生成占位值并落盘，
    # 保证 .env.local / 热推送 / 进程 env 三条注入通道拿到的都是非空值。
    # 外部 MCP 令牌同理（默认开启），生成后落盘，避免每次重启令牌变化。
    ensure_api_keys(stored)
    ensure_mcp_token(stored)
    config.set("openchatcut", stored)
    merged = merge_defaults(stored)
    pairs = write_env_file(merged)
    hot = _hot_push_keys(merged)
    return {
        "config": _mask(merged),
        "env_keys": sorted(pairs.keys()),
        "hot_applied": hot,
    }


@router.post("/apply-env")
def apply_env():
    """按当前设置重新生成 .env.local 并热推送（不修改设置）。"""
    if not OPENCHATCUT_DIR.is_dir():
        raise HTTPException(status_code=404, detail="thirdparty/openchatcut 不存在，请先部署项目")
    merged = _merged()
    pairs = write_env_file(merged)
    hot = _hot_push_keys(merged)
    return {"env_keys": sorted(pairs.keys()), "hot_applied": hot}


@router.get("/env-preview")
def env_preview():
    """预览将要注入的环境变量（密钥脱敏）。"""
    cfg = _merged()
    pairs = env_pairs(cfg)
    masked = mask_deep(pairs)
    return {"env": masked, "env_file": str(ENV_FILE), "env_exists": ENV_FILE.is_file()}


# --------------------------------------------------------------------------- #
# 下拉选项：读取本项目已配置的接口层（生图 / TTS），供设置页下拉选择
# --------------------------------------------------------------------------- #


def _model_name(model: Any) -> str:
    if isinstance(model, str):
        return model.strip()
    if isinstance(model, dict):
        value = model.get("id") or model.get("name") or model.get("model")
        return str(value).strip() if value else ""
    return ""


def _modes_of(meta: dict) -> list[str]:
    modes = meta.get("modes") or []
    if isinstance(modes, str):
        return [modes]
    return [str(m) for m in modes if m]


@router.get("/options/image")
def image_options():
    """已启用生图接口及其按模式拆分的模型清单（文生图 t2i / 图生图 i2i）。

    模型元数据缺 modes 时视为两种模式都支持，避免旧配置在 dropdown 里消失。
    """
    from backend.imagegen.imagegen_interface_manager import get_imagegen_interface_manager

    manager = get_imagegen_interface_manager()
    interfaces = []
    for iface in manager.get_enabled() or []:
        if not isinstance(iface, dict) or not iface.get("id"):
            continue
        iface_id = str(iface.get("id"))
        meta = manager.get_model_metadata(iface_id) or {}
        txt2img: list[str] = []
        img2img: list[str] = []
        for model in manager.get_models(iface_id) or []:
            name = _model_name(model)
            if not name:
                continue
            modes = _modes_of(meta.get(name) or {})
            if not modes or "t2i" in modes or "txt2img" in modes:
                txt2img.append(name)
            if not modes or "i2i" in modes or "img2img" in modes:
                img2img.append(name)
        interfaces.append(
            {
                "id": iface_id,
                "name": iface.get("name") or iface_id,
                "txt2img_models": txt2img,
                "img2img_models": img2img,
            }
        )
    return {"interfaces": interfaces}


@router.get("/options/tts")
def tts_options():
    """已启用 TTS 接口及其模型 / 音色清单（供设置页下拉选择）。"""
    from backend.tts.tts_interface_manager import get_tts_interface_manager, infer_tts_interface_modes

    manager = get_tts_interface_manager()
    interfaces = []
    for iface in manager.get_enabled() or []:
        if not isinstance(iface, dict) or not iface.get("id"):
            continue
        cfg = iface.get("config") or {}
        models = [_model_name(m) for m in (cfg.get("model_options") or [])]
        voices = []
        for voice in cfg.get("voice_options") or []:
            name = _model_name(voice) or (voice if isinstance(voice, str) else "")
            if name:
                voices.append(name)
        interfaces.append(
            {
                "id": str(iface.get("id")),
                "name": iface.get("name") or iface.get("id"),
                "models": [m for m in models if m],
                "voices": voices,
                "modes": infer_tts_interface_modes(iface),
            }
        )
    return {"interfaces": interfaces}


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


def _editor_proxy_url() -> str:
    """主项目后端上的反代地址（/openchatcut/ → 剪辑台 5199）。

    仅作备用：OpenChatCut 是 Vite 应用且无 basePath，页面里的资源走根路径绝对引用，
    经子路径反代后这些请求不会带上 /openchatcut 前缀，会落到主项目 SPA（白屏）。
    因此「打开剪辑台」默认用 direct_url（它自身的地址），见 _editor_open_url()。
    """
    return f"http://127.0.0.1:{BACKEND_PORT}/openchatcut/"


def _editor_open_url(host: str, port: int) -> str:
    """打开剪辑台使用的地址：它自身的 http://host:port/（新标签页，不走 iframe）。"""
    return f"http://{host}:{port}/"


def _node_info() -> tuple[bool, str | None]:
    """检测本机 Node.js：返回（是否存在, 版本字符串或 None）。"""
    node = shutil.which("node") or shutil.which("node.exe")
    if not node:
        return False, None
    try:
        result = subprocess.run(
            [node, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        version = (result.stdout or "").strip()
        return True, version or None
    except (OSError, subprocess.SubprocessError):
        # node 存在但版本探测失败：视为可用，交给安装脚本进一步校验
        return True, None


# --------------------------------------------------------------------------- #
# 依赖安装：后台线程执行 thirdparty/install_openchatcut.py（跨平台脚本）
# --------------------------------------------------------------------------- #

_INSTALL_SCRIPT = Path(__file__).resolve().parents[2] / "thirdparty" / "install_openchatcut.py"
_INSTALL_LOG_LIMIT = 500

_install_lock = threading.Lock()
_install_state: dict = {
    "running": False,
    "success": None,
    "exit_code": None,
    "started_at": None,
    "finished_at": None,
    "log": [],
}


def _install_worker() -> None:
    try:
        proc = subprocess.Popen(
            [sys.executable, str(_INSTALL_SCRIPT)],
            cwd=str(_INSTALL_SCRIPT.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        for line in proc.stdout or []:
            line = line.rstrip("\r\n")
            if line:
                _install_state["log"].append(line)
                del _install_state["log"][:-_INSTALL_LOG_LIMIT]
        code = proc.wait()
        _install_state["exit_code"] = code
        _install_state["success"] = code == 0
    except Exception as exc:  # noqa: BLE001
        logger.warning("[openchatcut] 安装脚本执行异常: %s", exc)
        _install_state["log"].append(f"[backend] 安装脚本执行异常: {exc}")
        _install_state["success"] = False
        _install_state["exit_code"] = -1
    finally:
        _install_state["running"] = False
        _install_state["finished_at"] = time.time()


class InstallRequest(BaseModel):
    force: bool | None = None


@router.post("/install")
def install(req: InstallRequest | None = None):
    """后台执行 thirdparty/install_openchatcut.py：拉取项目 + 安装依赖 + 构建前端。

    前置校验（不满足时不启动安装，前端据此提醒用户）：
    - 未检测到 Node.js → ``error=node_missing``
    - 项目目录缺失且未检测到 git（拉取项目需要）→ ``error=git_missing``
    """
    if not _INSTALL_SCRIPT.is_file():
        raise HTTPException(status_code=500, detail=f"安装脚本缺失: {_INSTALL_SCRIPT}")

    node_found, _node_version = _node_info()
    if not node_found:
        return {
            "started": False,
            "error": "node_missing",
            "message": "未检测到 Node.js。剪辑台依赖 Node.js 24.x 运行，请先到 https://nodejs.org 安装（建议 LTS），完成后重试。",
        }
    if not OPENCHATCUT_DIR.is_dir() and not shutil.which("git"):
        return {
            "started": False,
            "error": "git_missing",
            "message": "本机尚未部署剪辑台项目，且未检测到 git，无法自动拉取源码。请先安装 git（https://git-scm.com）后重试。",
        }

    with _install_lock:
        if _install_state["running"]:
            return {"started": False, "already_running": True}
        _install_state.update(
            running=True,
            success=None,
            exit_code=None,
            started_at=time.time(),
            finished_at=None,
            log=[f"$ {sys.executable} {_INSTALL_SCRIPT.name}" + (" --force" if req and req.force else "")],
        )
        threading.Thread(
            target=_install_worker, args=(), daemon=True, name="openchatcut-install"
        ).start()
    return {"started": True}


@router.get("/install-status")
def install_status():
    """查询后台安装进度（log 为脚本输出的尾部）。"""
    with _install_lock:
        state = dict(_install_state)
        state["log"] = list(_install_state["log"][-80:])
    return state


@router.get("/status")
def status():
    """OpenChatCut 部署与服务状态。"""
    cfg = _merged()
    port = int(cfg.get("port") or DEFAULT_PORT)
    host = str(cfg.get("host") or "127.0.0.1")
    env_mtime = 0.0
    if ENV_FILE.is_file():
        try:
            env_mtime = ENV_FILE.stat().st_mtime
        except OSError:
            env_mtime = 0.0
    node_found, node_version = _node_info()
    return {
        "repo": OPENCHATCUT_DIR.is_dir(),
        "deps": (OPENCHATCUT_DIR / "node_modules").is_dir(),
        # 前端构建产物：存在时启动走生产模式，缺失回退 dev server
        "build": (OPENCHATCUT_DIR / "dist" / "index.html").is_file(),
        # 本机 Node.js 检测（剪辑台依赖 Node 24.x；缺失时前端提醒安装）
        "node_ok": node_found,
        "node_version": node_version,
        "installing": _install_state["running"],
        "env_file": ENV_FILE.is_file(),
        "env_mtime": env_mtime,
        "port": port,
        "running": _port_open(port),
        # 新标签页打开剪辑台自身地址（Vite 应用无 basePath，不能挂子路径反代）
        "editor_url": _editor_open_url(host, port),
        "direct_url": f"http://{host}:{port}/",
        "mcp_url": f"http://{host}:{port}/api/external-mcp/mcp",
    }


@router.get("/editor-url")
def editor_url():
    """返回「打开剪辑台」按钮使用的地址。"""
    cfg = _merged()
    port = int(cfg.get("port") or DEFAULT_PORT)
    host = str(cfg.get("host") or "127.0.0.1")
    return {
        "url": _editor_open_url(host, port),
        "direct_url": _editor_open_url(host, port),
        "proxy_url": _editor_proxy_url(),
        "running": _port_open(port),
    }


@router.get("/tools")
def tools():
    """列出可无头调用的剪辑台工具及其参数 schema（供「剪辑编排」节点 ops 可视化编辑）。"""
    from backend import openchatcut_client as occ_client

    schema = occ_client.tool_schemas(headless_only=True)
    return schema


@router.get("/projects")
def projects():
    """列出剪辑台项目（供工作流节点下拉选择）。

    经官方 occ CLI 读取本地项目库，不需要打开剪辑台页面；CLI 不可用时返回
    available=False 与原因（前端据此提示去「AI剪辑台」页安装依赖）。
    """
    from backend import openchatcut_client as occ_client

    ok, reason = occ_client.available()
    if not ok:
        return {"available": False, "reason": reason, "projects": []}
    result = occ_client.list_projects()
    if not result.ok:
        return {
            "available": True,
            "reason": result.message or result.tail(5),
            "projects": [],
        }
    raw = result.data if isinstance(result.data, list) else []
    items = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("id") or "").strip()
        if not pid:
            continue
        items.append({"id": pid, "name": item.get("name") or pid})
    return {"available": True, "reason": "", "projects": items}


@router.get("/project-info")
def project_info():
    """调用项目说明与免责声明（前端展示，随版本可调整）。"""
    return {
        "name": "OpenChatCut",
        "upstream": "https://github.com/0xsline/OpenChatCut",
        "website": "https://openchatcut.com",
        "license": "AGPL-3.0-or-later",
        "version_hint": "独立进程运行，源码未做修改；配置经 .env.local 注入",
        "notice": (
            "AI剪辑台基于开源项目 OpenChatCut（AGPL-3.0）提供的本地优先、"
            "Agent 原生视频编辑器能力，本项目未修改其源码，仅通过其官方环境配置 "
            ".env.local 注入接口参数，并通过 MCP / HTTP 接口与其独立进程协作。"
        ),
        "disclaimer": (
            "免责声明：剪辑台内的 AI 生成内容（图像 / 视频 / 语音 / 音乐）由第三方模型服务产生，"
            "可能存在不准确或侵权风险，请自行审核后使用；导出与发布行为请遵守相应平台规范与法律法规。"
            "OpenChatCut 按 AGPL-3.0 许可「按原样」提供，不作任何明示或默示担保。"
        ),
    }

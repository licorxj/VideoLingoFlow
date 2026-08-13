"""AIGC 能力接口 API：其他能力接口（ComfyUI / RunningHub / 即梦）。

暴露配置读写、状态探测与测试调用，供前端「其他能力接口」设置页与 AIGC 流程链节点使用。
配置统一存放在 settings（config.yaml）的 aigc 命名空间下。
"""
import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, Optional

from backend.config.config_manager import config
from backend.aigc.comfyui_service import ComfyUIService
from backend.aigc.runninghub_service import RunningHubService
from backend.aigc.jimeng_service import JimengService, jimeng_cli_executable
from backend.aigc.errors import AIGCError

router = APIRouter(prefix="/api/aigc", tags=["aigc-capabilities"])


DEFAULT_CONFIG = {
    "comfyui": {
        "instances": ["127.0.0.1:8188"],
        "timeout": 1800,
    },
    "runninghub": {
        "base_url": "https://www.runninghub.ai",
        "api_key": "",
        "wallet_api_key": "",
        "timeout": 1800,
    },
    "jimeng": {
        "bin": "",
        "use_wsl": False,
        "timeout": 120,
    },
}


def _get_aigc_config() -> dict:
    return config.get("aigc", {}) or {}


def _merge_defaults(aigc: dict) -> dict:
    merged = {}
    for k, v in DEFAULT_CONFIG.items():
        sub = dict(v)
        sub.update(aigc.get(k) or {})
        merged[k] = sub
    return merged


@router.get("/config")
async def get_aigc_config():
    return {"config": _merge_defaults(_get_aigc_config())}


class AIGCConfigUpdate(BaseModel):
    provider: str
    values: Dict[str, Any]


@router.put("/config")
async def update_aigc_config(req: AIGCConfigUpdate):
    if req.provider not in DEFAULT_CONFIG:
        raise HTTPException(status_code=400, detail="未知的能力 provider")
    aigc = _get_aigc_config()
    sub = dict(aigc.get(req.provider) or {})
    sub.update(req.values)
    aigc[req.provider] = sub
    config.set("aigc", aigc)
    return {"config": _merge_defaults(aigc)}


@router.get("/status")
async def aigc_status():
    """探测三项能力的可用性状态。"""
    aigc = _merge_defaults(_get_aigc_config())
    status = {}

    # ComfyUI：探测第一个实例是否可达
    comfy = aigc["comfyui"]
    if comfy.get("instances"):
        addr = comfy["instances"][0]
        try:
            import urllib.request
            req = urllib.request.Request(f"http://{addr}/system_stats")
            with urllib.request.urlopen(req, timeout=3) as resp:
                ok = resp.status == 200
        except Exception:
            ok = False
        status["comfyui"] = {"reachable": ok, "instance": addr}
    else:
        status["comfyui"] = {"reachable": False, "instance": ""}

    # RunningHub：仅报告是否已配置 Key
    rh = aigc["runninghub"]
    status["runninghub"] = {
        "configured": bool(rh.get("api_key") or rh.get("wallet_api_key")),
        "base_url": rh.get("base_url"),
    }

    # 即梦：探测 CLI 是否存在
    jm = aigc["jimeng"]
    exe = jimeng_cli_executable(jm)
    status["jimeng"] = {"cli_found": bool(exe), "exe": exe}
    return {"status": status}


@router.post("/comfyui/test")
async def test_comfyui(body: dict = None):
    aigc = _merge_defaults(_get_aigc_config())
    svc = ComfyUIService(aigc["comfyui"])
    try:
        info = svc._reserve_backend()
        return {"success": True, "instance": info}
    except AIGCError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post("/runninghub/test")
async def test_runninghub(body: dict = None):
    aigc = _merge_defaults(_get_aigc_config())
    svc = RunningHubService(aigc["runninghub"])
    if not (svc.api_key or svc.wallet_api_key):
        raise HTTPException(status_code=400, detail="未配置 RunningHub API Key")
    return {"success": True, "configured": True}


@router.post("/jimeng/version")
async def jimeng_version():
    aigc = _merge_defaults(_get_aigc_config())
    svc = JimengService(aigc["jimeng"])
    try:
        ver = await asyncio.to_thread(svc.version)
        return {"version": ver, "cli_found": bool(jimeng_cli_executable(aigc["jimeng"]))}
    except AIGCError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post("/jimeng/install")
async def jimeng_install():
    """检查即梦 CLI 是否已安装；未安装时按平台执行官方安装命令（curl -s https://jimeng.jianying.com/cli | bash）。"""
    aigc = _merge_defaults(_get_aigc_config())
    svc = JimengService(aigc["jimeng"])
    try:
        result = await asyncio.to_thread(svc.install_cli)
        return result
    except AIGCError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

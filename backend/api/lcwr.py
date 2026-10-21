"""LCWR 本地 API 代理：健康检查与模型列表，供去水印节点前端使用。

前端通过本代理访问 LCWR（默认 http://localhost:1120），避免浏览器直接跨域调用本地服务；
LCWR 服务不可用时模型列表回退为文档内置列表。
"""
import requests
from fastapi import APIRouter

router = APIRouter(prefix="/api/lcwr", tags=["lcwr"])

# 与 LCWR V2.0（app4）engine.config.InpaintMode 保持一致：共 6 个本地模型。
# app4 已移除 bernini 与在线模型链路，此处不可再出现，否则提交会返回 400。
STATIC_MODELS = [
    {"id": "lama", "name": "LaMa（快速）", "type": "local"},
    {"id": "sttn", "name": "STTN（时空张量）", "type": "local"},
    {"id": "propainter", "name": "ProPainter（高质量）", "type": "local"},
    {"id": "diffueraser", "name": "DiffuEraser（扩散模型）", "type": "local"},
    {"id": "effecterase", "name": "EffectErase（效果消除，CC BY-NC 非商用）", "type": "local"},
    {"id": "e2fgvi", "name": "E2FGVI（视频补全，CC BY-NC 非商用）", "type": "local"},
]


@router.get("/health")
def lcwr_health(base_url: str = "http://localhost:1120"):
    """检查 LCWR 本地 API 是否在线。"""
    try:
        resp = requests.get(base_url.rstrip("/") + "/health", timeout=5)
        if resp.status_code == 200:
            try:
                return {"connected": True, "detail": resp.json()}
            except ValueError:
                return {"connected": True, "detail": {}}
    except requests.RequestException:
        pass
    return {"connected": False, "detail": {}}


@router.get("/models")
def lcwr_models(base_url: str = "http://localhost:1120"):
    """获取 LCWR 可用模型列表；服务不可用时回退内置列表。"""
    base_url = base_url.rstrip("/")
    try:
        resp = requests.get(base_url + "/models", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            models = data.get("all_models") or data.get("local_models") or []
            if models:
                return {"connected": True, "models": models, "fallback": False}
    except requests.RequestException:
        pass
    return {"connected": False, "models": STATIC_MODELS, "fallback": True}

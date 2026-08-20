import ipaddress

from fastapi import APIRouter, HTTPException, Request

from backend.updater import llm_router_updater

router = APIRouter(prefix="/api/llm-router-update")


def _is_loopback(request: Request) -> bool:
    host = request.client.host if request.client else ""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@router.get("/status")
async def status():
    return llm_router_updater.get_status()


@router.post("/run")
async def run(request: Request):
    if not _is_loopback(request):
        raise HTTPException(status_code=403, detail="仅允许本机启动路由器更新")
    return llm_router_updater.run_update()

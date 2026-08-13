"""FastAPI main entry point. CORS + route mounting + WebSocket."""
import ipaddress
import os
import sys
import time
import uuid
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import Scope, Receive, Send

from backend.api import tasks, settings, history, batch, llm, ws, tts_interfaces, asr_interfaces, logs, workflows, node_types, community, file_browser, prompts, subtitle_presets, subtitle_preview, imagegen_interfaces, publish, separation_interfaces, subscription, public_info, editor, editor_agent, cutia, voiceforge, voiceforge_ws, control_plane, control_plane_assets, control_plane_workspace, collaboration_ws, pi_rpc, aigc_capabilities, github_update
from backend.control_plane import runtime_flags
from backend.utils.observability import correlation_id


class WebSocketSafeStaticFiles(StaticFiles):
    """根路径静态文件挂载的保护层：WebSocket scope 直接拒绝，
    避免未匹配的 ws 请求落入 StaticFiles 的 assert scope['type'] == 'http' 崩溃。"""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1000, "reason": "Not Found"})
            return
        await super().__call__(scope, receive, send)


class UnicodeJSONResponse(JSONResponse):
    def render(self, content):
        import json as _json
        return _json.dumps(content, ensure_ascii=False, default=str).encode("utf-8")


app = FastAPI(title="VideoLingo API", version="2.0.0", default_response_class=UnicodeJSONResponse)


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        token = correlation_id.set(request.headers.get("X-Correlation-ID") or uuid.uuid4().hex)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = correlation_id.get()
            response.headers["X-Request-Duration-Ms"] = str(round((time.perf_counter() - started) * 1000, 2))
            return response
        finally:
            correlation_id.reset(token)


app.add_middleware(CorrelationMiddleware)

lan_mode_enabled = os.getenv("VIDEOLINGO_LAN_MODE", "").strip().lower() in {"1", "true", "yes", "on"}
# 远程模式为运行时标志：启动时从环境变量初始化，控制面开关接口可实时更新（无需重启）
runtime_flags.remote_mode_enabled = os.getenv("VIDEOLINGO_REMOTE_MODE", "").strip().lower() in {"1", "true", "yes", "on"}


def _is_local_host(host: str) -> bool:
    """判断请求 Host 是否为本机/局域网内网地址。"""
    hostname = host.split(":")[0].strip().lower()
    if hostname in {"", "localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ipaddress.ip_address(hostname).is_private
    except ValueError:
        return False


class RemoteAccessGuard(BaseHTTPMiddleware):
    """远程网络协作开关：关闭时拒绝公网入口（https / 非本机域名）的业务请求。"""

    async def dispatch(self, request, call_next):
        if not runtime_flags.remote_mode_enabled:
            proto = (request.headers.get("x-forwarded-proto", "") or "").lower()
            host = request.headers.get("host", "") or ""
            is_remote = proto == "https" or (host and not _is_local_host(host))
            if is_remote and request.method != "OPTIONS":
                return JSONResponse(status_code=403, content={
                    "code": "remote_access_disabled",
                    "message": "远程网络协作已关闭，请在主机端多人协作页面开启",
                })
        return await call_next(request)


app.add_middleware(RemoteAccessGuard)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:11002", "http://127.0.0.1:11002",
                    "http://localhost:11003", "http://127.0.0.1:11003",
                    "http://localhost:11004", "http://127.0.0.1:11004",
                    "http://localhost:11005", "http://127.0.0.1:11005"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_origin_regex=r"https?://(?:localhost|127\.0\.0\.1|(?:\d{1,3}\.){3}\d{1,3})(?::\d+)?" if lan_mode_enabled else None,
)

app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(editor.router, prefix="/api/editor", tags=["editor"])
app.include_router(editor_agent.router, prefix="/api/editor", tags=["editor-agent"])
app.include_router(cutia.router, prefix="/api/cutia", tags=["cutia"])
app.include_router(settings.router, prefix="/api/settings", tags=["settings"])
app.include_router(history.router, prefix="/api/history", tags=["history"])
app.include_router(batch.router, prefix="/api/batch", tags=["batch"])
app.include_router(llm.router, prefix="/api/llm", tags=["llm"])
app.include_router(pi_rpc.router, prefix="/api/pi", tags=["pi-agent"])
app.include_router(aigc_capabilities.router, tags=["aigc-capabilities"])
app.include_router(tts_interfaces.router, prefix="/api/tts-interfaces", tags=["tts-interfaces"])
app.include_router(tts_interfaces.voice_router, prefix="/api/tts-voices", tags=["tts-voices"])
app.include_router(asr_interfaces.router, prefix="/api/asr-interfaces", tags=["asr-interfaces"])
app.include_router(imagegen_interfaces.router, prefix="/api/imagegen-interfaces", tags=["imagegen-interfaces"])
app.include_router(separation_interfaces.router, prefix="/api/separation-interfaces", tags=["separation-interfaces"])
app.include_router(publish.router, prefix="/api/publish", tags=["publish"])
app.include_router(subscription.router, prefix="/api/subscription", tags=["subscription"])
app.include_router(public_info.router, tags=["public-info"])
app.include_router(github_update.router, tags=["github-update"])
app.include_router(control_plane.router, prefix="/api/control", tags=["control-plane"])
app.include_router(control_plane_assets.router, prefix="/api/control", tags=["control-plane-assets"])
app.include_router(control_plane_workspace.router, prefix="/api/control", tags=["control-plane-workspace"])
app.include_router(ws.router, prefix="/ws", tags=["websocket"])
app.include_router(collaboration_ws.router, prefix="/ws", tags=["collaboration-websocket"])
app.include_router(logs.router, prefix="/ws", tags=["logs"])
app.include_router(workflows.router, prefix="/api/workflows", tags=["workflows"])
app.include_router(node_types.router, tags=["node-types"])
app.include_router(community.router, tags=["community"])
app.include_router(file_browser.router, tags=["file-browser"])
app.include_router(prompts.router, tags=["prompts"])
app.include_router(subtitle_presets.router, prefix="/api/subtitle-presets", tags=["subtitle-presets"])
app.include_router(subtitle_preview.router, prefix="/api/subtitle-preview", tags=["subtitle-preview"])
app.include_router(voiceforge.router, prefix="/api/voiceforge", tags=["voiceforge"])
app.include_router(voiceforge_ws.router, prefix="/ws/voiceforge", tags=["voiceforge-websocket"])

os.makedirs(os.path.join(ROOT, "tasks"), exist_ok=True)


# 挂载 temp 目录为静态文件，用于提供预览视频
temp_dir = os.path.join(ROOT, "temp")
os.makedirs(temp_dir, exist_ok=True)
app.mount("/temp", StaticFiles(directory=temp_dir), name="temp")


def _readiness_dependencies():
    from backend.control_plane import check_schema
    from backend.voiceforge.tasks.celery_app import celery_available, celery_worker_available
    from backend.control_plane.celery_runtime import celery_app as control_plane_celery

    control_plane = check_schema()
    control_plane_worker = False
    if control_plane_celery is not None:
        try:
            control_plane_worker = bool(control_plane_celery.control.ping(timeout=0.5))
        except Exception:
            control_plane_worker = False
    data_root = os.getenv("CONTROL_PLANE_DATA_ROOT", os.path.join(ROOT, "data"))
    return {
        "control_plane_schema": control_plane["schema"],
        "data_root": os.path.isdir(data_root),
        "asset_root": os.path.isdir(os.getenv("CONTROL_PLANE_ASSET_ROOT", os.path.join(data_root, "assets"))),
        "redis": celery_available(),
        "celery_worker": celery_worker_available(),
        "control_plane_worker": control_plane_worker,
    }


@app.get("/api/health")
@app.get("/api/health/live")
async def health_live():
    return {"status": "ok", "version": "2.0.0"}


@app.get("/api/health/ready")
async def health_ready():
    dependencies = _readiness_dependencies()
    if not all(dependencies.values()):
        raise HTTPException(status_code=503, detail={"status": "not_ready", "dependencies": dependencies})
    return {"status": "ready", "dependencies": dependencies}


@app.get("/api/metrics")
async def metrics():
    from backend.control_plane.database import session_scope
    from backend.control_plane.models import Task
    from backend.control_plane.workflow_runtime import RESOURCE_TOKENS, _queue_depth
    from backend.control_plane.celery_runtime import celery_app as control_plane_celery
    from sqlalchemy import func, select
    lines = ["videolingo_up 1"]
    try:
        with session_scope() as session:
            for status, count in session.execute(select(Task.status, func.count()).group_by(Task.status)):
                lines.append(f'videolingo_tasks{{status="{status}"}} {count}')
            failed = session.scalar(select(func.count()).select_from(Task).where(Task.status == "failed")) or 0
            total = session.scalar(select(func.count()).select_from(Task)) or 0
            lines.append(f"videolingo_task_failure_ratio {failed / total if total else 0}")
    except Exception:
        lines.append("videolingo_control_plane_available 0")
    for resource, capacity in RESOURCE_TOKENS.capacities.items():
        lines.append(f'videolingo_resource_capacity{{resource="{resource}"}} {capacity}')
        lines.append(f'videolingo_queue_depth{{resource="{resource}"}} {_queue_depth(resource)}')
    worker_count = 0
    worker_capabilities = {}
    if control_plane_celery is not None:
        try:
            worker_capabilities = control_plane_celery.control.inspect().stats() or {}
            worker_count = len(worker_capabilities)
        except Exception:
            worker_capabilities = {}
    lines.append(f"videolingo_workers {worker_count}")
    for worker, stats in worker_capabilities.items():
        capabilities = stats.get("pool", {}).get("implementation", "unknown") if isinstance(stats, dict) else "unknown"
        lines.append(f'videolingo_worker_alive{{worker="{worker}",capability="{capabilities}"}} 1')
    disk = shutil.disk_usage(os.getenv("CONTROL_PLANE_WORKSPACE_ROOT", ROOT))
    lines.append(f"videolingo_storage_bytes_free {disk.free}")
    lines.append(f"videolingo_storage_bytes_total {disk.total}")
    return Response(content="\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@app.post("/api/restart")
async def restart_server():
    raise HTTPException(status_code=501, detail={"code": "manager_required", "message": "请通过 manager 管理 API 进程"})


@app.on_event("startup")
async def startup_event():
    from alembic import command
    from alembic.config import Config
    from backend.voiceforge import initialize_database
    migration_config = Config(os.path.join(ROOT, "alembic.ini"))
    command.upgrade(migration_config, "head")
    initialize_database()
    print("VoiceForge database initialized")

    from backend.tts.tts_interface_manager import get_tts_interface_manager
    mgr = get_tts_interface_manager()
    mgr.reload()
    print(f"TTS interfaces loaded: {len(mgr.list_all())}")

    from backend.asr.asr_interface_manager import get_asr_interface_manager
    asr_mgr = get_asr_interface_manager()
    asr_mgr.reload()
    print(f"ASR interfaces loaded: {len(asr_mgr.list_all())}")

    from backend.imagegen.imagegen_interface_manager import get_imagegen_interface_manager
    img_mgr = get_imagegen_interface_manager()
    img_mgr.reload()
    print(f"ImageGen interfaces loaded: {len(img_mgr.list_all())}")

    from backend.api.logs import install_log_redirectors
    install_log_redirectors()
    print("Log redirectors installed")

    from backend.api.ws_queue import start_queue_drainer
    start_queue_drainer()
    print("WS queue drainer started")


@app.on_event("shutdown")
async def shutdown_event():
    from backend.pi_rpc import get_pi_manager
    await get_pi_manager().close_all()


frontend_build = os.path.join(ROOT, "frontend", "dist")
if os.path.isdir(frontend_build):
    app.mount("/", WebSocketSafeStaticFiles(directory=frontend_build, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=11001)

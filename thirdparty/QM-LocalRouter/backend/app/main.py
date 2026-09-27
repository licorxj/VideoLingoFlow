import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from contextlib import asynccontextmanager
from app.config import settings
from app.database import init_db
from app.routers import providers, api_keys, models, strategies, logs, dashboard, proxy, icons, backup, conversations
from app.routers.settings import router as settings_router, _get_settings
from app.routers import providers, api_keys, models, strategies, logs, dashboard, proxy, icons, backup, conversations, service
from app.routers import online_providers
from app.routers import client_keys
from app.routers import oauth_login
from app.routers import oauth_flow
from app.routers import cli_import


class DynamicCORSMiddleware(BaseHTTPMiddleware):
    """CORS middleware that reads lan_access setting dynamically."""
    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin", "")
        app_settings = _get_settings()
        lan_access = app_settings.get("lan_access", False)

        # Preflight
        if request.method == "OPTIONS":
            response = Response()
            if lan_access or not origin:
                response.headers["Access-Control-Allow-Origin"] = "*"
            elif origin in settings.CORS_ORIGINS:
                response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = "*"
            response.headers["Access-Control-Allow-Headers"] = "*"
            response.headers["Access-Control-Allow-Credentials"] = "true"
            return response

        response = await call_next(request)

        if lan_access or not origin:
            response.headers["Access-Control-Allow-Origin"] = "*"
        elif origin in settings.CORS_ORIGINS:
            response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
        response.headers["Access-Control-Allow-Credentials"] = "true"

        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Check auto-backup on startup
    try:
        await backup.check_auto_backup()
    except Exception:
        pass
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(DynamicCORSMiddleware)

# Management APIs
app.include_router(online_providers.router)
app.include_router(client_keys.router)
app.include_router(client_keys.endpoints_router)
app.include_router(oauth_login.router)
app.include_router(oauth_flow.router)
app.include_router(cli_import.router)
app.include_router(providers.router)
app.include_router(proxy.alias_router)
app.include_router(api_keys.router)
app.include_router(models.router)
app.include_router(strategies.router)
app.include_router(logs.router)
app.include_router(dashboard.router)

# Icon search/download
app.include_router(icons.router)

# Backup/restore
app.include_router(backup.router)
app.include_router(conversations.router)

app.include_router(service.router)
# Proxy endpoints (OpenAI-compatible)
app.include_router(settings_router)
app.include_router(proxy.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": settings.APP_VERSION}


# --- Production frontend serving ---
# In production the built SPA (frontend/dist) is served by this same process,
# so a single uvicorn handles UI + API on one port. The Vite dev server is
# used during development and takes precedence there (nginx fronts dist in Docker).
_FRONTEND_DIST = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "frontend", "dist",
)

if os.path.isdir(_FRONTEND_DIST):
    _assets_dir = os.path.join(_FRONTEND_DIST, "assets")
    if os.path.isdir(_assets_dir):
        app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        # Unknown API paths must stay JSON 404s, never the SPA shell
        if full_path.split("/", 1)[0] in ("api", "v1", "k"):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = os.path.abspath(os.path.join(_FRONTEND_DIST, full_path))
        if full_path and candidate.startswith(_FRONTEND_DIST + os.sep) and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_FRONTEND_DIST, "index.html"))

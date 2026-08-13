from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from contextlib import asynccontextmanager
from app.config import settings
from app.database import init_db
from app.routers import providers, api_keys, models, strategies, logs, dashboard, proxy, icons, backup, conversations
from app.routers.settings import router as settings_router, _get_settings
from app.routers import providers, api_keys, models, strategies, logs, dashboard, proxy, icons, backup, conversations, service


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
app.include_router(providers.router)
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

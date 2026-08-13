import hashlib
import secrets
from datetime import datetime, timedelta, timezone

# passlib 1.7.4 与 bcrypt>=4 的版本探测兼容：bcrypt 4.x 移除了 __about__，
# passlib 读取版本号时抛 (trapped) error，功能不受影响但会污染日志。
# 在 import passlib 前补上 __about__ 属性，消除该警告。
import bcrypt as _bcrypt
if not hasattr(_bcrypt, "__about__"):
    class _BcryptAbout:
        __version__ = getattr(_bcrypt, "__version__", "unknown")
    _bcrypt.__about__ = _BcryptAbout()

from fastapi import Depends, HTTPException, Request
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from backend.control_plane.database import session_scope
from backend.control_plane.models import AuditEvent, Project, ProjectMember, Role, Session, User, UserRole

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SESSION_TTL = timedelta(hours=12)
ROLE_PERMISSIONS = {
    "admin": {"admin", "project:read", "project:write", "project:manage", "workflow:write", "task:execute", "task:cancel", "asset:download", "asset:write", "asset:delete"},
    "editor": {"project:read", "project:write", "workflow:write", "task:execute", "asset:download", "asset:write", "asset:delete"},
    "viewer": {"project:read", "asset:download"},
}


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return bool(password_hash) and pwd_context.verify(password, password_hash)


def password_hash(password: str) -> str:
    return pwd_context.hash(password)


def issue_session(db: DbSession, user: User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(Session(token_hash=hash_token(token), user_id=user.id, expires_at=datetime.now(timezone.utc) + SESSION_TTL))
    return token


def audit(db: DbSession, actor_id: str | None, action: str, resource_type: str, resource_id: str | None = None, payload: dict | None = None) -> None:
    db.add(AuditEvent(actor_id=actor_id, action=action, resource_type=resource_type, resource_id=resource_id, payload=payload or {}))


def audit_event(actor_id: str | None, action: str, resource_type: str, resource_id: str | None = None, payload: dict | None = None) -> None:
    with session_scope() as db:
        audit(db, actor_id, action, resource_type, resource_id, payload)


def resolve_session_token(token: str) -> User | None:
    """Resolve a session token to a User, or None when invalid/expired/revoked."""
    if not token:
        return None
    with session_scope() as db:
        session = db.scalar(select(Session).where(Session.token_hash == hash_token(token)))
        if not session or session.revoked_at or _utc(session.expires_at) <= datetime.now(timezone.utc) or not session.user.is_active:
            actor_id = session.user_id if session else None
            session_id = session.id if session else None
            audit_event(actor_id, "session_rejected", "session", session_id)
            return None
        user = db.scalar(select(User).where(User.id == session.user_id))
        db.expunge(user)
        return user


def current_user(request: Request) -> User:
    authorization = request.headers.get("Authorization", "")
    token = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else request.cookies.get("cp_session", "")
    if not token:
        raise HTTPException(401, detail={"code": "not_authenticated", "message": "需要登录"})
    user = resolve_session_token(token)
    if user is None:
        raise HTTPException(401, detail={"code": "session_invalid", "message": "会话已失效"})
    return user


async def ws_user_from_request(websocket) -> User | None:
    """Resolve the authenticated user for a WebSocket connection (Authorization / Cookie / ?token=)."""
    authorization = websocket.headers.get("authorization", "")
    token = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else None
    if not token:
        cookies = websocket.headers.get("cookie", "")
        for part in cookies.split(";"):
            part = part.strip()
            if part.startswith("cp_session="):
                token = part[len("cp_session="):]
                break
    if not token:
        token = (websocket.query_params.get("token") or "").strip()
    user = resolve_session_token(token)
    if user is None:
        await websocket.close(code=4401)
        return None
    return user


def roles_for(db: DbSession, user_id: str) -> set[str]:
    return set(db.scalars(select(Role.name).join(UserRole).where(UserRole.user_id == user_id)).all())


def require_permission(permission: str):
    def dependency(user: User = Depends(current_user)) -> User:
        with session_scope() as db:
            if permission not in set().union(*(ROLE_PERMISSIONS.get(role, set()) for role in roles_for(db, user.id))):
                audit_event(user.id, "access_denied", "permission", payload={"permission": permission})
                raise HTTPException(403, detail={"code": "forbidden", "message": "没有执行此操作的权限"})
        return user
    return dependency


def project_access(project_id: str, permission: str, user: User) -> Project:
    with session_scope() as db:
        project = db.get(Project, project_id)
        allowed = False
        if project:
            if "admin" in roles_for(db, user.id):
                allowed = True
            elif project.owner_id == user.id:
                allowed = permission in {"project:read", "project:write", "project:manage", "workflow:write", "task:execute", "task:cancel", "asset:download", "asset:write", "asset:delete"}
            else:
                member = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.user_id == user.id))
                allowed = member is not None and permission in ROLE_PERMISSIONS.get(member.role, set())
        if not project or not allowed:
            audit_event(user.id, "access_denied", "project", project_id, {"permission": permission})
            raise HTTPException(403 if project else 404, detail={"code": "project_forbidden", "message": "无权访问项目"})
        db.expunge(project)
        return project


def require_project(project_id: str, permission: str):
    def dependency(user: User = Depends(current_user)) -> Project:
        return project_access(project_id, permission, user)
    return dependency

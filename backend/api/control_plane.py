import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import desc, select, update

from backend.control_plane.database import session_scope
from backend.control_plane.models import AuditEvent, JoinApplication, Project, ProjectMember, Role, Session, Task, User, UserRole, WorkflowVersion
from backend.control_plane.security import audit, audit_event, current_user, hash_token, issue_session, password_hash, project_access, require_permission, roles_for, verify_password
from backend.workflow_validation import normalize_workflow

router = APIRouter()


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=128)
    password: str = Field(min_length=8, max_length=256)
    display_name: str = Field(default="", max_length=256)


class JoinApplyRequest(BaseModel):
    username: str = Field(min_length=3, max_length=128)
    password: str = Field(min_length=8, max_length=256)
    display_name: str = Field(default="", max_length=256)
    reason: str = Field(default="", max_length=2000)


class RejectRequest(BaseModel):
    note: str = Field(default="", max_length=2000)


class LanModeRequest(BaseModel):
    enabled: bool


class ActiveRequest(BaseModel):
    is_active: bool


class CredentialsChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_username: str | None = Field(default=None, min_length=3, max_length=128)
    new_password: str | None = Field(default=None, min_length=8, max_length=256)


class UserRoleRequest(BaseModel):
    role: str = Field(min_length=1, max_length=64)


class ProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=10000)


class MemberRequest(BaseModel):
    username: str = Field(min_length=3, max_length=128)
    role: str = Field(default="viewer", pattern="^(viewer|editor)$")


class TransferRequest(BaseModel):
    username: str = Field(min_length=3, max_length=128)


class WorkflowSaveRequest(BaseModel):
    definition: dict
    expected_revision: int = Field(ge=0)
    force: bool = False


def user_view(user: User, roles: set[str]) -> dict:
    return {"id": user.id, "username": user.username, "display_name": user.display_name, "roles": sorted(roles), "is_active": user.is_active}


def project_view(project: Project) -> dict:
    return {"id": project.id, "name": project.name, "description": project.description, "owner_id": project.owner_id, "version": project.version}


def _cookie_secure(http_request: Request) -> bool:
    """HTTPS 下（如 Cloudflare Tunnel 携带 x-forwarded-proto）为会话 Cookie 置 secure=True。"""
    return (http_request.headers.get("x-forwarded-proto", "") or "").lower() == "https"


@router.post("/auth/bootstrap")
def bootstrap(request: Credentials, response: Response, http_request: Request):
    with session_scope() as db:
        if db.scalar(select(User.id).limit(1)):
            raise HTTPException(409, detail={"code": "bootstrap_complete", "message": "本地管理员已初始化"})
        admin_role = Role(name="admin")
        editor_role = Role(name="editor")
        viewer_role = Role(name="viewer")
        user = User(username=request.username, display_name=request.display_name, password_hash=password_hash(request.password))
        db.add_all([admin_role, editor_role, viewer_role, user])
        db.flush()
        db.add(UserRole(user_id=user.id, role_id=admin_role.id))
        token = issue_session(db, user)
        audit(db, user.id, "bootstrap", "user", user.id)
        response.set_cookie("cp_session", token, httponly=True, samesite="lax", secure=_cookie_secure(http_request), max_age=43200)
        return {"user": user_view(user, {"admin"})}


@router.post("/auth/login")
def login(request: Credentials, response: Response, http_request: Request):
    with session_scope() as db:
        user = db.scalar(select(User).where(User.username == request.username))
        if not user:
            audit_event(None, "login_rejected", "user", None, {"username": request.username, "reason": "no_such_user"})
            raise HTTPException(401, detail={"code": "invalid_credentials", "message": "用户名或密码错误"})
        if not user.is_active:
            audit_event(user.id, "login_rejected", "user", user.id, {"username": request.username, "reason": "account_disabled"})
            raise HTTPException(401, detail={"code": "account_disabled", "message": "账号已被禁用，请联系管理员"})
        if not verify_password(request.password, user.password_hash):
            audit_event(user.id, "login_rejected", "user", user.id, {"username": request.username, "reason": "bad_password"})
            raise HTTPException(401, detail={"code": "invalid_credentials", "message": "用户名或密码错误"})
        token = issue_session(db, user)
        audit(db, user.id, "login", "user", user.id)
        response.set_cookie("cp_session", token, httponly=True, samesite="lax", secure=_cookie_secure(http_request), max_age=43200)
        return {"user": user_view(user, roles_for(db, user.id))}


@router.post("/auth/logout")
def logout(request: Request, response: Response, user: User = Depends(current_user)):
    authorization = request.headers.get("Authorization", "")
    token = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else request.cookies.get("cp_session", "")
    with session_scope() as db:
        db.execute(update(Session).where(Session.token_hash == hash_token(token), Session.revoked_at.is_(None)).values(revoked_at=datetime.now(timezone.utc)))
        audit(db, user.id, "logout", "user", user.id)
    response.delete_cookie("cp_session")
    return {"ok": True}


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    with session_scope() as db:
        return {"user": user_view(user, roles_for(db, user.id))}


@router.post("/auth/apply")
def apply_join(request: JoinApplyRequest):
    with session_scope() as db:
        if db.scalar(select(User.id).where(User.username == request.username)):
            raise HTTPException(409, detail={"code": "username_taken", "message": "用户名已存在"})
        if db.scalar(select(JoinApplication.id).where(JoinApplication.username == request.username, JoinApplication.status == "pending")):
            raise HTTPException(409, detail={"code": "application_pending", "message": "已有待审批的注册申请"})
        application = JoinApplication(username=request.username, display_name=request.display_name, password_hash=password_hash(request.password), reason=request.reason)
        db.add(application)
        db.flush()
        audit(db, None, "join_applied", "user", application.id, {"username": request.username})
        return {"application_id": application.id, "status": "pending"}


@router.get("/auth/apply/{application_id}")
def get_apply_status(application_id: str):
    with session_scope() as db:
        application = db.get(JoinApplication, application_id)
        if not application:
            raise HTTPException(404, detail={"code": "application_not_found", "message": "申请不存在"})
        return {"application_id": application.id, "status": application.status, "created_at": application.created_at}


@router.get("/admin/applications")
def list_applications(status: str | None = Query(default=None, pattern="^(pending|approved|rejected)$"), user: User = Depends(require_permission("admin"))):
    with session_scope() as db:
        statement = select(JoinApplication).order_by(desc(JoinApplication.created_at))
        if status:
            statement = statement.where(JoinApplication.status == status)
        applications = db.scalars(statement).all()
        return {"applications": [
            {"id": item.id, "username": item.username, "display_name": item.display_name, "reason": item.reason,
             "status": item.status, "created_at": item.created_at, "reviewed_at": item.reviewed_at,
             "reviewed_by": item.reviewed_by, "review_note": item.review_note}
            for item in applications
        ]}


@router.post("/admin/applications/{application_id}/approve")
def approve_application(application_id: str, user: User = Depends(require_permission("admin"))):
    with session_scope() as db:
        application = db.get(JoinApplication, application_id)
        if not application:
            raise HTTPException(404, detail={"code": "application_not_found", "message": "申请不存在"})
        if application.status != "pending":
            raise HTTPException(409, detail={"code": "application_not_pending", "message": "申请已被处理"})
        if db.scalar(select(User.id).where(User.username == application.username)):
            raise HTTPException(409, detail={"code": "username_taken", "message": "用户名已被占用"})
        viewer_role = db.scalar(select(Role).where(Role.name == "viewer"))
        if not viewer_role:
            raise HTTPException(500, detail={"code": "role_missing", "message": "角色初始化缺失"})
        target = User(username=application.username, display_name=application.display_name, password_hash=application.password_hash, is_active=True)
        db.add(target)
        db.flush()
        db.add(UserRole(user_id=target.id, role_id=viewer_role.id))
        application.status = "approved"
        application.reviewed_at = datetime.now(timezone.utc)
        application.reviewed_by = user.id
        audit(db, user.id, "join_approved", "user", target.id, {"application_id": application_id, "username": application.username})
        return {"user": user_view(target, {"viewer"})}


@router.post("/admin/applications/{application_id}/reject")
def reject_application(application_id: str, request: RejectRequest, user: User = Depends(require_permission("admin"))):
    with session_scope() as db:
        application = db.get(JoinApplication, application_id)
        if not application:
            raise HTTPException(404, detail={"code": "application_not_found", "message": "申请不存在"})
        if application.status != "pending":
            raise HTTPException(409, detail={"code": "application_not_pending", "message": "申请已被处理"})
        application.status = "rejected"
        application.reviewed_at = datetime.now(timezone.utc)
        application.reviewed_by = user.id
        application.review_note = request.note
        audit(db, user.id, "join_rejected", "user", application.id, {"username": application.username, "note": request.note})
        return {"ok": True}


@router.get("/presence")
def list_presence(user: User = Depends(current_user)):
    from backend.api.collaboration_ws import _presence_snapshot
    return {"members": _presence_snapshot()}


def _local_env_path() -> Path:
    override = os.environ.get("CONTROL_PLANE_LAN_ENV_PATH")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / ".runtime" / "local_env.bat"


def _read_mode_value(path: Path, key: str) -> bool:
    """读取 local_env.bat 中的布尔型配置（如 VIDEOLINGO_LAN_MODE）。"""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    needle = f"{key.lower()}="
    for line in lines:
        text = line.strip().lower().replace(" ", "")
        if text.startswith("set") and needle in text:
            return text.split("=", 1)[1].strip('"') in {"1", "true", "yes", "on"}
    return False


def _write_mode_value(path: Path, key: str, enabled: bool) -> bool:
    """写入/替换 local_env.bat 中的布尔型配置（如 VIDEOLINGO_LAN_MODE）。"""
    value = "1" if enabled else "0"
    line_new = f'set "{key.upper()}={value}"'
    try:
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    except OSError:
        return False
    needle = f"{key.lower()}="
    replaced = False
    out = []
    for line in lines:
        text = line.strip().lower().replace(" ", "")
        if text.startswith("set") and needle in text:
            out.append(line_new)
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(line_new)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
        return True
    except OSError:
        return False


def _read_lan_mode() -> bool:
    return _read_mode_value(_local_env_path(), "videolingo_lan_mode")


def _write_lan_mode(enabled: bool) -> bool:
    return _write_mode_value(_local_env_path(), "videolingo_lan_mode", enabled)


def _read_remote_mode() -> bool:
    return _read_mode_value(_local_env_path(), "videolingo_remote_mode")


def _write_remote_mode(enabled: bool) -> bool:
    return _write_mode_value(_local_env_path(), "videolingo_remote_mode", enabled)


@router.get("/lan-mode")
def get_lan_mode():
    return {"enabled": _read_lan_mode(), "restart_required": False}


@router.post("/lan-mode")
def set_lan_mode(request: LanModeRequest, user: User = Depends(require_permission("admin"))):
    ok = _write_lan_mode(request.enabled)
    audit_event(user.id, "lan_mode_changed", "system", None, {"enabled": request.enabled})
    if not ok:
        raise HTTPException(500, detail={"code": "lan_mode_write_failed", "message": "无法写入本机配置"})
    return {"ok": True, "enabled": request.enabled, "restart_required": True}


@router.get("/remote-mode")
def get_remote_mode():
    return {"enabled": _read_remote_mode(), "restart_required": False}


def _find_cloudflared() -> str | None:
    """定位 cloudflared 可执行文件：常见安装目录 + PATH。"""
    if os.name == "nt":
        for env_var in ("ProgramFiles(x86)", "ProgramFiles"):
            root = os.environ.get(env_var)
            if root:
                candidate = os.path.join(root, "cloudflared", "cloudflared.exe")
                if os.path.isfile(candidate):
                    return candidate
    found = shutil.which("cloudflared") or shutil.which("cloudflared.exe")
    return found or None


def _cloudflared_running() -> bool:
    """检测 cloudflared 进程是否在运行（Windows 用 tasklist，其余平台用 pgrep）。"""
    try:
        if os.name == "nt":
            result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq cloudflared.exe", "/NH"], capture_output=True, text=True, timeout=10)
            return "cloudflared.exe" in result.stdout
        result = subprocess.run(["pgrep", "-x", "cloudflared"], capture_output=True, text=True, timeout=10)
        return bool(result.stdout.strip())
    except Exception:
        return False


def _wake_cloudflared(cloudflared: str) -> bool:
    """后台唤醒 cloudflared（读取 ~/.cloudflared/config.yml 启动隧道），返回是否存活。"""
    try:
        flags = 0
        if os.name == "nt":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
        subprocess.Popen(
            [cloudflared, "tunnel", "run"],
            cwd=str(Path.home()),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )
        time.sleep(2)
        return _cloudflared_running()
    except Exception:
        return False


def _cloudflared_check_and_wake() -> dict:
    """检查 cloudflared：未安装 → 提示运行 setup_cloudflare_tunnel.bat；未运行 → 尝试唤醒。"""
    cloudflared = _find_cloudflared()
    if not cloudflared:
        return {
            "installed": False,
            "running": False,
            "action": "install",
            "message": "未检测到 cloudflared，请运行软件根目录的 setup_cloudflare_tunnel.bat 完成安装与隧道配置",
        }
    if _cloudflared_running():
        return {"installed": True, "running": True, "action": "none", "message": "cloudflared 已在运行，隧道正常"}
    started = _wake_cloudflared(cloudflared)
    return {
        "installed": True,
        "running": started,
        "action": "started" if started else "failed",
        "message": "cloudflared 未运行，已尝试唤醒"
        if started
        else "cloudflared 未运行且唤醒失败，请检查 ~/.cloudflared/config.yml 配置，或运行 setup_cloudflare_tunnel.bat",
    }


@router.post("/remote-mode")
def set_remote_mode(request: LanModeRequest, user: User = Depends(require_permission("admin"))):
    ok = _write_remote_mode(request.enabled)
    audit_event(user.id, "remote_mode_changed", "system", None, {"enabled": request.enabled})
    if not ok:
        raise HTTPException(500, detail={"code": "remote_mode_write_failed", "message": "无法写入本机配置"})
    # 实时更新运行时标志：开关立即生效，无需重启（配置文件持久化，重启后仍保持）
    from backend.control_plane import runtime_flags
    runtime_flags.remote_mode_enabled = request.enabled
    response: dict = {"ok": True, "enabled": request.enabled, "restart_required": False}
    if request.enabled:
        cloudflared_status = _cloudflared_check_and_wake()
        audit_event(user.id, "cloudflared_check", "system", None, cloudflared_status)
        response["cloudflared"] = cloudflared_status
    return response


@router.post("/users/me/credentials")
def change_credentials(request: CredentialsChangeRequest, user: User = Depends(current_user)):
    with session_scope() as db:
        current = db.get(User, user.id)
        if not current or not verify_password(request.current_password, current.password_hash):
            raise HTTPException(403, detail={"code": "invalid_credentials", "message": "当前密码错误"})
        if not request.new_username and not request.new_password:
            raise HTTPException(400, detail={"code": "nothing_to_change", "message": "至少修改用户名或密码之一"})
        username_changed = False
        if request.new_username and request.new_username != current.username:
            if db.scalar(select(User.id).where(User.username == request.new_username)):
                raise HTTPException(409, detail={"code": "username_taken", "message": "用户名已存在"})
            current.username = request.new_username
            username_changed = True
        if request.new_password:
            current.password_hash = password_hash(request.new_password)
        audit(db, user.id, "credentials_changed", "user", user.id, {"username_changed": username_changed})
        return {"user": user_view(current, roles_for(db, user.id))}


@router.post("/users/{user_id}/active")
def set_user_active(user_id: str, request: ActiveRequest, user: User = Depends(require_permission("admin"))):
    with session_scope() as db:
        target = db.get(User, user_id)
        if not target:
            raise HTTPException(404, detail={"code": "user_not_found", "message": "用户不存在"})
        if target.id == user.id and not request.is_active:
            raise HTTPException(400, detail={"code": "cannot_disable_self", "message": "不能禁用自己"})
        target.is_active = request.is_active
        if not request.is_active:
            db.execute(update(Session).where(Session.user_id == target.id, Session.revoked_at.is_(None)).values(revoked_at=datetime.now(timezone.utc)))
        audit(db, user.id, "user_active_changed", "user", target.id, {"is_active": request.is_active})
        return {"user": user_view(target, roles_for(db, target.id))}


@router.get("/users")
def list_users(user: User = Depends(require_permission("admin"))):
    with session_scope() as db:
        users = db.scalars(select(User).order_by(User.username)).all()
        return {"users": [user_view(item, roles_for(db, item.id)) for item in users]}


@router.post("/users")
def create_user(request: Credentials, user: User = Depends(require_permission("admin"))):
    with session_scope() as db:
        if db.scalar(select(User.id).where(User.username == request.username)):
            raise HTTPException(409, detail={"code": "username_taken", "message": "用户名已存在"})
        target = User(username=request.username, display_name=request.display_name, password_hash=password_hash(request.password))
        db.add(target)
        db.flush()
        audit(db, user.id, "user_created", "user", target.id)
        return {"user": user_view(target, set())}


@router.put("/users/{user_id}/roles")
def assign_role(user_id: str, request: UserRoleRequest, user: User = Depends(require_permission("admin"))):
    with session_scope() as db:
        target = db.get(User, user_id)
        role = db.scalar(select(Role).where(Role.name == request.role))
        if not target or not role:
            raise HTTPException(404, detail={"code": "not_found", "message": "用户或角色不存在"})
        if not db.get(UserRole, {"user_id": target.id, "role_id": role.id}):
            db.add(UserRole(user_id=target.id, role_id=role.id))
        audit(db, user.id, "role_assigned", "user", target.id, {"role": role.name})
        return {"user": user_view(target, roles_for(db, target.id) | {role.name})}


@router.post("/projects")
def create_project(request: ProjectRequest, user: User = Depends(current_user)):
    with session_scope() as db:
        project = Project(name=request.name, description=request.description, owner_id=user.id)
        db.add(project)
        db.flush()
        audit(db, user.id, "project_created", "project", project.id)
        return {"project": project_view(project)}


@router.get("/projects")
def list_projects(user: User = Depends(current_user)):
    with session_scope() as db:
        admin = "admin" in roles_for(db, user.id)
        statement = select(Project).order_by(Project.name) if admin else select(Project).outerjoin(ProjectMember).where((Project.owner_id == user.id) | (ProjectMember.user_id == user.id)).order_by(Project.name)
        return {"projects": [project_view(item) for item in db.scalars(statement).unique().all()]}


@router.get("/projects/{project_id}")
def get_project(project_id: str, user: User = Depends(current_user)):
    return {"project": project_view(project_access(project_id, "project:read", user))}


@router.get("/projects/{project_id}/members")
def list_members(project_id: str, user: User = Depends(current_user)):
    project_access(project_id, "project:read", user)
    with session_scope() as db:
        members = db.scalars(select(ProjectMember).where(ProjectMember.project_id == project_id)).all()
        return {"members": [{"user": user_view(db.get(User, member.user_id), roles_for(db, member.user_id)), "role": member.role} for member in members]}


@router.post("/projects/{project_id}/members")
def invite_member(project_id: str, request: MemberRequest, user: User = Depends(current_user)):
    project_access(project_id, "project:manage", user)
    with session_scope() as db:
        target = db.scalar(select(User).where(User.username == request.username))
        if not target:
            raise HTTPException(404, detail={"code": "user_not_found", "message": "用户不存在"})
        member = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.user_id == target.id))
        if member:
            member.role = request.role
        else:
            db.add(ProjectMember(project_id=project_id, user_id=target.id, role=request.role))
        audit(db, user.id, "member_changed", "project", project_id, {"user_id": target.id, "role": request.role})
        return {"ok": True}


@router.delete("/projects/{project_id}/members/{user_id}")
def remove_member(project_id: str, user_id: str, user: User = Depends(current_user)):
    project_access(project_id, "project:manage", user)
    with session_scope() as db:
        member = db.scalar(select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id))
        if not member:
            raise HTTPException(404, detail={"code": "member_not_found", "message": "项目成员不存在"})
        db.delete(member)
        audit(db, user.id, "member_removed", "project", project_id, {"user_id": user_id})
        return {"ok": True}


@router.post("/projects/{project_id}/owner")
def transfer_owner(project_id: str, request: TransferRequest, user: User = Depends(current_user)):
    project_access(project_id, "project:manage", user)
    with session_scope() as db:
        project = db.get(Project, project_id)
        if project.owner_id != user.id:
            raise HTTPException(403, detail={"code": "owner_required", "message": "仅项目所有者可以转移所有权"})
        target = db.scalar(select(User).where(User.username == request.username))
        if not target:
            raise HTTPException(404, detail={"code": "user_not_found", "message": "用户不存在"})
        project.owner_id = target.id
        audit(db, user.id, "project_owner_transferred", "project", project_id, {"new_owner_id": target.id})
        return {"project": project_view(project)}


@router.get("/projects/{project_id}/tasks")
def list_project_tasks(project_id: str, user: User = Depends(current_user)):
    project_access(project_id, "project:read", user)
    with session_scope() as db:
        tasks = db.scalars(select(Task).where(Task.project_id == project_id).order_by(desc(Task.created_at)).limit(200)).all()
        return {"tasks": [
            {"id": task.id, "status": task.status, "created_at": task.created_at,
             "name": (task.payload or {}).get("task_name") or (task.payload or {}).get("name") or task.id[:8]}
            for task in tasks
        ]}


@router.get("/projects/{project_id}/workflows/{workflow_key}")
def get_workflow(project_id: str, workflow_key: str, user: User = Depends(current_user)):
    project_access(project_id, "project:read", user)
    with session_scope() as db:
        workflow = db.scalar(select(WorkflowVersion).where(WorkflowVersion.project_id == project_id, WorkflowVersion.workflow_key == workflow_key).order_by(desc(WorkflowVersion.revision)))
        if not workflow:
            raise HTTPException(404, detail={"code": "workflow_not_found", "message": "工作流不存在"})
        definition, migrated, removed = normalize_workflow(workflow.definition)
        if migrated or removed:
            workflow.definition = definition
            db.flush()
        return {"workflow": {"key": workflow.workflow_key, "revision": workflow.revision, "definition": definition}}


@router.put("/projects/{project_id}/workflows/{workflow_key}")
def save_workflow(project_id: str, workflow_key: str, request: WorkflowSaveRequest, user: User = Depends(current_user)):
    project_access(project_id, "workflow:write", user)
    definition, _, _ = normalize_workflow(request.definition)
    with session_scope() as db:
        current = db.scalar(select(WorkflowVersion).where(WorkflowVersion.project_id == project_id, WorkflowVersion.workflow_key == workflow_key).order_by(desc(WorkflowVersion.revision)))
        actual_revision = current.revision if current else 0
        if actual_revision != request.expected_revision and not request.force:
            audit_event(user.id, "workflow_conflict", "workflow", current.id if current else None, {"project_id": project_id, "workflow_key": workflow_key, "expected_revision": request.expected_revision, "actual_revision": actual_revision})
            raise HTTPException(409, detail={"code": "revision_conflict", "message": "工作流已被其他成员修改", "expected_revision": request.expected_revision, "actual_revision": actual_revision, "current_definition": current.definition if current else None})
        workflow = WorkflowVersion(project_id=project_id, workflow_key=workflow_key, revision=actual_revision + 1, definition=definition)
        db.add(workflow)
        db.flush()
        audit(db, user.id, "workflow_saved", "workflow", workflow.id, {"project_id": project_id, "workflow_key": workflow_key, "revision": workflow.revision, "forced": request.force})
        return {"workflow": {"key": workflow_key, "revision": workflow.revision, "definition": workflow.definition}}


@router.get("/audit")
def list_audit(project_id: str | None = None, limit: int = Query(default=100, ge=1, le=500), user: User = Depends(require_permission("admin"))):
    with session_scope() as db:
        statement = select(AuditEvent).order_by(desc(AuditEvent.created_at)).limit(limit)
        if project_id:
            statement = statement.where(AuditEvent.resource_id == project_id)
        events = db.scalars(statement).all()
        return {"events": [{"id": event.id, "actor_id": event.actor_id, "action": event.action, "resource_type": event.resource_type, "resource_id": event.resource_id, "payload": event.payload, "created_at": event.created_at} for event in events]}

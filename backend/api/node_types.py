"""
Node type management API.
Backend-driven node definitions stored as JSON files.
Supports: list, create, update, delete, export (ZIP), import (ZIP).
"""
import asyncio
import os
import json
import zipfile
import shutil
import uuid
import re
from pathlib import Path
from pathlib import PurePosixPath
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from datetime import datetime, timezone

from backend.config.builtin_node_types import (
    BUILTIN_NODE_IDS,
    delete_builtin_node_type,
    get_builtin_node_type,
    get_builtin_node_types,
)
from backend.config.node_schema import get_node_schema, validate_node_type_data
from backend.control_plane.security import current_user, require_permission

router = APIRouter(prefix="/api/node-types", tags=["node-types"], dependencies=[Depends(current_user)])

NODE_TYPES_DIR = Path(__file__).parent.parent / "config" / "node_types"
SHARE_DIR = Path(__file__).parent.parent.parent / "share"
NODE_BACKUP_DIR = Path(__file__).parent.parent / "backups" / "node_types"
NODE_TYPES_DIR.mkdir(parents=True, exist_ok=True)
SHARE_DIR.mkdir(parents=True, exist_ok=True)
NODE_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
PACKAGE_SCHEMA_VERSION = "1.0"
NODE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def _validate_node_id(node_id: str) -> str:
    value = str(node_id or "").strip()
    if not NODE_ID_PATTERN.fullmatch(value):
        raise HTTPException(status_code=400, detail="Node ID must contain only letters, digits, '_' or '-' and be at most 80 characters")
    return value


def _atomic_json_write(path: Path, data: dict) -> None:
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


class NodeTypeConfig(BaseModel):
    id: str
    name: str
    version: str = "1.0.0"
    category: str = "process"
    description: str = ""
    icon: str = "Wrench"
    color: str = "#6b7280"
    inputs: list = []
    outputs: list = []
    defaultConfig: dict = {}
    configFields: list = []
    isBuiltIn: bool = False
    # Execution config for custom nodes
    execType: str = ""  # "python" | "shell" | "llm" | "" (no exec)
    execCode: str = ""  # inline code or shell command
    execFile: str = ""  # path to external .py file
    execTimeout: int = 300  # seconds
    kind: str = "normal"
    groupDefinition: Optional[dict] = None


class ExportRequest(BaseModel):
    nodeId: str
    shareName: str
    shareDescription: str = ""
    author: str = ""
    sourceUrl: str = ""
    tags: list[str] = []


class RestoreBackupRequest(BaseModel):
    createBackup: bool = True


def _load_all_nodes() -> list[dict]:
    """Load built-in nodes and custom nodes from disk."""
    nodes = []
    for node in get_builtin_node_types():
        node["isBuiltIn"] = True
        nodes.append(node)
    # Load custom nodes from JSON files
    if NODE_TYPES_DIR.exists():
        for f in sorted(NODE_TYPES_DIR.glob("*.json")):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                    data["isBuiltIn"] = False
                    nodes.append(data)
            except Exception:
                continue
    return nodes


def _validate_or_raise(data: dict) -> None:
    try:
        validate_node_type_data(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _validate_package_members(member_names: list[str]) -> None:
    """Validate archive members to avoid path traversal and unsupported roots."""
    for member in member_names:
        normalized = member.replace("\\", "/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or Path(normalized).drive or ".." in path.parts:
            raise HTTPException(status_code=400, detail=f"Invalid package member path: {member}")
        if path.parts and path.parts[0].startswith(".") and path.parts[0] not in {".well-known"}:
            raise HTTPException(status_code=400, detail=f"Unsupported hidden package member: {member}")


def _load_package_payload(temp_zip: Path) -> tuple[list[str], dict, dict]:
    """Load package members, node_config and share_meta from a ZIP file."""
    with zipfile.ZipFile(temp_zip, "r") as zf:
        member_names = zf.namelist()
        _validate_package_members(member_names)
        if "node_config.json" not in member_names:
            raise HTTPException(status_code=400, detail="Invalid node package: missing node_config.json")
        node_data = json.loads(zf.read("node_config.json"))
        share_meta = json.loads(zf.read("share_meta.json")) if "share_meta.json" in member_names else {}

    if not isinstance(node_data, dict):
        raise HTTPException(status_code=400, detail="Invalid node package: node_config.json must be an object")
    if share_meta and not isinstance(share_meta, dict):
        raise HTTPException(status_code=400, detail="Invalid node package: share_meta.json must be an object")
    return member_names, node_data, share_meta


def _is_archive_member_included(rel: str) -> bool:
    """与导入提取规则保持一致：顶层 __MACOSX 与隐藏成员会被跳过/拒绝。

    - 顶层以 `.` 开头（非 .well-known）→ 导入校验直接 400
    - 顶层以 __MACOSX 开头 → 导入提取时跳过
    - 子目录隐藏文件 → 导入会保留，导出也保留（两端一致）
    """
    parts = PurePosixPath(rel.replace("\\", "/")).parts
    if not parts:
        return False
    if parts[0].startswith("__MACOSX"):
        return False
    if parts[0].startswith(".") and parts[0] not in {".well-known"}:
        return False
    return True


def _prepare_export_node_data(node_data: dict) -> tuple[dict, str]:
    """Strip runtime-only fields and normalize exported node config.

    规范化规则与导入侧 (_analyze_package/_resolve_exec_file_for_import) 对齐：
    - execFile 必须是包内成员（相对 code_dir 的路径），否则导入会 400
    - 相对路径原样保留（导入侧同样视为包内路径），绝对路径转为相对 code_dir
    - 无法随包分发时退回内联 execCode；两者皆无则拒绝导出
    """
    export_data = json.loads(json.dumps(node_data))
    code_dir = export_data.pop("codeDir", "") or ""
    export_data.pop("isBuiltIn", None)
    export_data["schemaVersion"] = PACKAGE_SCHEMA_VERSION

    if export_data.get("execType") == "python":
        exec_file = str(export_data.get("execFile", "") or "").replace("\\", "/").strip()
        if exec_file:
            if os.path.isabs(exec_file):
                # 绝对路径：相对 code_dir 转成包内路径
                if code_dir and os.path.isdir(code_dir):
                    try:
                        rel_exec = os.path.relpath(exec_file, code_dir).replace("\\", "/")
                    except ValueError:
                        rel_exec = ""
                else:
                    rel_exec = ""
            else:
                # 相对路径即包内路径，与导入解析规则一致
                rel_exec = exec_file

            usable = (
                rel_exec
                and not rel_exec.startswith("..")
                and _is_archive_member_included(rel_exec)
                and bool(code_dir)
                and os.path.exists(os.path.join(code_dir, rel_exec))
            )
            if usable:
                export_data["execFile"] = rel_exec
            elif str(export_data.get("execCode", "") or "").strip():
                # execFile 无法随包分发：退回内联代码执行
                export_data["execFile"] = ""
            else:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Cannot export node: python node has no inline execCode and "
                        f"execFile is not inside the node code directory: {exec_file}"
                    ),
                )

    return export_data, code_dir


def _normalize_version(value: str | None) -> str:
    version = str(value or "").strip()
    return version or "1.0.0"


def _parse_version_parts(version: str) -> tuple[int | str, ...]:
    parts: list[int | str] = []
    for item in version.replace("-", ".").split("."):
        item = item.strip()
        if not item:
            continue
        parts.append(int(item) if item.isdigit() else item.lower())
    return tuple(parts or [0])


def _compare_versions(package_version: str, local_version: str) -> str:
    package_parts = _parse_version_parts(package_version)
    local_parts = _parse_version_parts(local_version)
    max_len = max(len(package_parts), len(local_parts))
    for idx in range(max_len):
        package_part = package_parts[idx] if idx < len(package_parts) else 0
        local_part = local_parts[idx] if idx < len(local_parts) else 0
        if package_part == local_part:
            continue
        if isinstance(package_part, int) and isinstance(local_part, int):
            return "upgrade" if package_part > local_part else "downgrade"
        return "different"
    return "same"


def _get_existing_custom_node(node_id: str) -> dict | None:
    fpath = NODE_TYPES_DIR / f"{node_id}.json"
    if not fpath.exists():
        return None
    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["isBuiltIn"] = False
    return data


def _build_version_comparison(node_id: str, package_name: str, package_version: str) -> tuple[dict | None, dict]:
    local_node = _get_existing_custom_node(node_id)
    if not local_node:
        return None, {
            "status": "new",
            "message": f"将安装新节点 {package_name} {package_version}",
            "localVersion": "",
            "packageVersion": package_version,
            "requiresConfirmation": False,
            "recommendedBackup": False,
        }

    local_version = _normalize_version(local_node.get("version"))
    compare_status = _compare_versions(package_version, local_version)
    if compare_status == "upgrade":
        message = f"将把本地节点从 {local_version} 升级到 {package_version}"
    elif compare_status == "downgrade":
        message = f"将用较旧版本 {package_version} 覆盖本地 {local_version}"
    elif compare_status == "same":
        message = f"将用相同版本 {package_version} 覆盖本地节点"
    else:
        message = f"将用不同版本格式的节点包 {package_version} 覆盖本地 {local_version}"

    return (
        {
            "id": local_node.get("id", node_id),
            "name": local_node.get("name", ""),
            "version": local_version,
            "category": local_node.get("category", ""),
        },
        {
            "status": compare_status,
            "message": message,
            "localVersion": local_version,
            "packageVersion": package_version,
            "requiresConfirmation": compare_status in {"same", "downgrade", "different"},
            "recommendedBackup": compare_status in {"upgrade", "same", "downgrade", "different"},
        },
    )


def _backup_existing_node(node_id: str, local_node: dict | None) -> str:
    """Backup existing node config and code directory before overwrite."""
    backup_name = f"{node_id}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    backup_dir = NODE_BACKUP_DIR / backup_name
    backup_dir.mkdir(parents=True, exist_ok=True)

    config_path = NODE_TYPES_DIR / f"{node_id}.json"
    if config_path.exists():
        shutil.copy2(config_path, backup_dir / "node_config.json")

    # 注意：codeDir 为空时 Path("") 会退化为 Path(".")，str 结果 "." 为真，
    # 因此必须先判断原始字符串非空，否则会把整个项目目录递归复制进备份。
    raw_code_dir = str(local_node.get("codeDir", "") or "").strip() if local_node else ""
    if raw_code_dir:
        code_dir = Path(raw_code_dir)
        if code_dir.exists() and code_dir.is_dir():
            shutil.copytree(code_dir, backup_dir / "code", dirs_exist_ok=True)

    return str(backup_dir)


def _parse_backup_timestamp(backup_name: str) -> str:
    parts = backup_name.rsplit("_", 1)
    if len(parts) != 2:
        return ""
    try:
        dt = datetime.strptime(parts[1], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        return ""


def _get_backup_dir(node_id: str, backup_id: str) -> Path:
    backup_dir = NODE_BACKUP_DIR / backup_id
    if not backup_dir.exists() or not backup_dir.is_dir() or not backup_id.startswith(f"{node_id}_"):
        raise HTTPException(status_code=404, detail="Node backup not found")
    return backup_dir


def _list_node_backups(node_id: str) -> list[dict]:
    backups: list[dict] = []
    for backup_dir in sorted(
        NODE_BACKUP_DIR.glob(f"{node_id}_*"),
        key=lambda item: item.name,
        reverse=True,
    ):
        if not backup_dir.is_dir():
            continue

        config_path = backup_dir / "node_config.json"
        backup_node = {}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    backup_node = json.load(f)
            except Exception:
                backup_node = {}

        backups.append(
            {
                "id": backup_dir.name,
                "nodeId": node_id,
                "path": str(backup_dir),
                "createdAt": _parse_backup_timestamp(backup_dir.name),
                "hasCode": (backup_dir / "code").exists(),
                "node": {
                    "id": backup_node.get("id", node_id),
                    "name": backup_node.get("name", ""),
                    "version": backup_node.get("version", ""),
                    "category": backup_node.get("category", ""),
                },
            }
        )
    return backups


def _restore_node_backup(node_id: str, backup_id: str, create_backup: bool) -> tuple[dict, str]:
    backup_dir = _get_backup_dir(node_id, backup_id)
    config_path = backup_dir / "node_config.json"
    if not config_path.exists():
        raise HTTPException(status_code=400, detail="Invalid backup: missing node_config.json")

    with open(config_path, "r", encoding="utf-8") as f:
        node_data = json.load(f)

    if node_data.get("id") != node_id:
        raise HTTPException(status_code=400, detail="Backup node ID does not match target node")

    local_node = _get_existing_custom_node(node_id)
    current_backup_path = ""
    if local_node and create_backup:
        current_backup_path = _backup_existing_node(node_id, local_node)

    nodes_code_dir = Path(__file__).parent.parent / "nodes" / node_id
    if nodes_code_dir.exists():
        shutil.rmtree(nodes_code_dir)

    backup_code_dir = backup_dir / "code"
    if backup_code_dir.exists() and backup_code_dir.is_dir():
        shutil.copytree(backup_code_dir, nodes_code_dir, dirs_exist_ok=True)

    node_data["isBuiltIn"] = False
    node_data["schemaVersion"] = PACKAGE_SCHEMA_VERSION
    node_data["version"] = _normalize_version(node_data.get("version"))
    node_data["codeDir"] = str(nodes_code_dir) if nodes_code_dir.exists() else ""
    _validate_or_raise(node_data)

    fpath = NODE_TYPES_DIR / f"{node_id}.json"
    _atomic_json_write(fpath, node_data)

    return node_data, current_backup_path


def _resolve_exec_file_for_import(node_data: dict, member_names: list[str]) -> tuple[str, list[str]]:
    """Resolve and validate execFile path inside imported package."""
    warnings: list[str] = []
    exec_type = node_data.get("execType", "")
    exec_file = str(node_data.get("execFile", "") or "").replace("\\", "/").strip()
    exec_code = str(node_data.get("execCode", "") or "").strip()

    if exec_type == "python":
        if exec_file:
            if exec_file in member_names:
                return exec_file, warnings
            legacy_name = PurePosixPath(exec_file).name
            if legacy_name and legacy_name in member_names:
                warnings.append(f"execFile used legacy absolute path, normalized to package file: {legacy_name}")
                return legacy_name, warnings
            raise HTTPException(status_code=400, detail=f"Invalid node package: execFile not found in ZIP: {exec_file}")
        if not exec_code:
            raise HTTPException(status_code=400, detail="Invalid node package: python node requires execFile or execCode")

    if exec_type in {"shell", "llm"} and not exec_code:
        raise HTTPException(status_code=400, detail=f"Invalid node package: {exec_type} node requires execCode")

    return exec_file, warnings


def _analyze_package(node_data: dict, member_names: list[str], share_meta: dict) -> tuple[dict, list[str]]:
    """Analyze package metadata and normalize importable node config."""
    if not isinstance(node_data, dict):
        raise HTTPException(status_code=400, detail="Invalid node package: node_config.json must be an object")

    analyzed = json.loads(json.dumps(node_data))
    node_id = analyzed.get("id", "")
    if not node_id:
        raise HTTPException(status_code=400, detail="Invalid node config: missing id")
    node_id = _validate_node_id(node_id)
    analyzed["id"] = node_id
    if node_id in BUILTIN_NODE_IDS:
        raise HTTPException(status_code=400, detail="Cannot import over built-in node types")

    warnings: list[str] = []
    analyzed["version"] = _normalize_version(analyzed.get("version") or share_meta.get("version"))
    schema_version = str(analyzed.get("schemaVersion") or share_meta.get("schemaVersion") or "").strip()
    if not schema_version:
        warnings.append("Package missing schemaVersion, treated as legacy package")
    elif schema_version != PACKAGE_SCHEMA_VERSION:
        warnings.append(f"Package schemaVersion={schema_version}, current={PACKAGE_SCHEMA_VERSION}")

    normalized_exec_file, exec_warnings = _resolve_exec_file_for_import(analyzed, member_names)
    warnings.extend(exec_warnings)
    if normalized_exec_file:
        analyzed["execFile"] = normalized_exec_file

    _validate_or_raise(analyzed)
    return analyzed, warnings


@router.get("")
async def list_node_types():
    """List all custom node types."""
    nodes = _load_all_nodes()
    return {"nodes": nodes}


@router.get("/schema")
async def get_node_types_schema():
    """Get shared node schema metadata."""
    return get_node_schema()


@router.get("/{node_id}")
async def get_node_type(node_id: str):
    """Get a specific node type."""
    builtin = get_builtin_node_type(node_id)
    if builtin:
        builtin["isBuiltIn"] = True
        return builtin
    fpath = NODE_TYPES_DIR / f"{node_id}.json"
    if not fpath.exists():
        raise HTTPException(status_code=404, detail="Node type not found")
    with open(fpath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


@router.get("/{node_id}/backups")
async def list_node_type_backups(node_id: str):
    """List local backups for a custom node."""
    if node_id in BUILTIN_NODE_IDS:
        raise HTTPException(status_code=400, detail="Built-in node types do not have local backups")
    return {"backups": _list_node_backups(node_id)}


@router.post("/{node_id}/backups/{backup_id}/restore", dependencies=[Depends(require_permission("workflow:write"))])
async def restore_node_type_backup(node_id: str, backup_id: str, req: RestoreBackupRequest | None = None):
    """Restore a custom node from a local backup directory."""
    node_id = _validate_node_id(node_id)
    if node_id in BUILTIN_NODE_IDS:
        raise HTTPException(status_code=400, detail="Cannot restore built-in node types")

    node_data, current_backup_path = _restore_node_backup(
        node_id,
        backup_id,
        True if req is None else bool(req.createBackup),
    )
    return {
        "ok": True,
        "node": node_data,
        "restoredFrom": backup_id,
        "currentBackupPath": current_backup_path,
    }


@router.post("", dependencies=[Depends(require_permission("workflow:write"))])
async def create_node_type(config: NodeTypeConfig):
    """Create a new custom node type."""
    node_id = _validate_node_id(config.id)

    # Check if built-in
    if node_id in BUILTIN_NODE_IDS:
        raise HTTPException(status_code=400, detail="Cannot modify built-in node types")

    fpath = NODE_TYPES_DIR / f"{node_id}.json"
    if fpath.exists():
        raise HTTPException(status_code=409, detail="Node type already exists")
    data = config.model_dump()
    data["isBuiltIn"] = False
    _validate_or_raise(data)
    _atomic_json_write(fpath, data)
    return {"ok": True, "node": data}


@router.put("/{node_id}", dependencies=[Depends(require_permission("workflow:write"))])
async def update_node_type(node_id: str, config: NodeTypeConfig):
    """Update a custom node type."""
    node_id = _validate_node_id(node_id)
    if config.id.strip() != node_id:
        raise HTTPException(status_code=400, detail="Node ID in path and payload must match")
    if node_id in BUILTIN_NODE_IDS:
        raise HTTPException(status_code=400, detail="Cannot modify built-in node types")
    fpath = NODE_TYPES_DIR / f"{node_id}.json"
    if not fpath.exists():
        raise HTTPException(status_code=404, detail="Node type not found")
    data = config.model_dump()
    data["isBuiltIn"] = False
    _validate_or_raise(data)
    _atomic_json_write(fpath, data)
    return {"ok": True, "node": data}


@router.delete("/{node_id}", dependencies=[Depends(require_permission("workflow:write"))])
async def delete_node_type(node_id: str):
    node_id = _validate_node_id(node_id)
    if node_id in BUILTIN_NODE_IDS:
        delete_builtin_node_type(node_id)
        return {"ok": True, "isBuiltIn": True}
    fpath = NODE_TYPES_DIR / f"{node_id}.json"
    if not fpath.exists():
        raise HTTPException(status_code=404, detail="Node type not found")
    fpath.unlink()
    return {"ok": True}


@router.post("/export", dependencies=[Depends(require_permission("workflow:write"))])
async def export_node_type(req: ExportRequest):
    """Export a node type as a ZIP file to the share/ folder."""
    # Try custom nodes first, then built-in
    fpath = NODE_TYPES_DIR / f"{req.nodeId}.json"
    if fpath.exists():
        with open(fpath, "r", encoding="utf-8") as f:
            node_data = json.load(f)
    else:
        node_data = get_builtin_node_type(req.nodeId)
        if not node_data:
            raise HTTPException(status_code=404, detail="Node type not found")
        node_data["isBuiltIn"] = True

    export_node_data, code_dir = _prepare_export_node_data(node_data)

    # Create ZIP
    safe_name = req.shareName.replace(" ", "_").replace("/", "_")
    zip_name = f"node_{safe_name}_{req.nodeId}.zip"
    zip_path = SHARE_DIR / zip_name

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Write config JSON
        zf.writestr("node_config.json", json.dumps(export_node_data, ensure_ascii=False, indent=2))
        # Write share metadata
        meta = {
            "shareName": req.shareName,
            "description": req.shareDescription,
            "nodeId": req.nodeId,
            "version": export_node_data.get("version", "1.0.0"),
            "schemaVersion": PACKAGE_SCHEMA_VERSION,
            "author": req.author.strip(),
            "sourceUrl": req.sourceUrl.strip(),
            "tags": [str(tag).strip() for tag in req.tags if str(tag).strip()],
            "exportedAt": datetime.now(timezone.utc).isoformat(),
        }
        zf.writestr("share_meta.json", json.dumps(meta, ensure_ascii=False, indent=2))

        # Include code files if they exist
        if code_dir and os.path.isdir(code_dir):
            for root, dirs, files in os.walk(code_dir):
                # 与导入规则一致：顶层隐藏目录 / __MACOSX 不打包，避免自产包被导入校验拒绝
                dirs[:] = [d for d in dirs if _is_archive_member_included(os.path.join(root, d))]
                for fname in files:
                    fpath = os.path.join(root, fname)
                    arcname = os.path.relpath(fpath, code_dir).replace("\\", "/")
                    if not _is_archive_member_included(arcname):
                        continue
                    zf.write(fpath, arcname)

    return {"ok": True, "zipPath": str(zip_path), "fileName": zip_name}


@router.post("/validate-package", dependencies=[Depends(require_permission("workflow:write"))])
async def validate_node_type_package(file: UploadFile = File(...)):
    """Preflight validation for a node package ZIP without importing it."""
    if not file.filename.endswith(".zip"):
        return {"ok": False, "valid": False, "errors": ["File must be a ZIP file"], "warnings": []}

    content = await file.read()
    temp_zip = NODE_TYPES_DIR / f"_validate_{uuid.uuid4().hex[:8]}.zip"
    try:
        with open(temp_zip, "wb") as f:
            f.write(content)

        try:
            member_names, node_data, share_meta = _load_package_payload(temp_zip)
            analyzed, warnings = _analyze_package(node_data, member_names, share_meta)
        except HTTPException as exc:
            return {
                "ok": False,
                "valid": False,
                "errors": [str(exc.detail)],
                "warnings": [],
                "packageFiles": [],
            }

        preview = {
            "id": analyzed.get("id"),
            "name": analyzed.get("name"),
            "version": analyzed.get("version", "1.0.0"),
            "category": analyzed.get("category"),
            "execType": analyzed.get("execType", ""),
            "execFile": analyzed.get("execFile", ""),
            "schemaVersion": analyzed.get("schemaVersion") or share_meta.get("schemaVersion") or "",
        }
        local_node, version_comparison = _build_version_comparison(
            preview["id"],
            preview["name"],
            preview["version"],
        )
        normalized_share_meta = {
            "shareName": share_meta.get("shareName", ""),
            "description": share_meta.get("description", ""),
            "nodeId": share_meta.get("nodeId", analyzed.get("id", "")),
            "version": _normalize_version(share_meta.get("version") or analyzed.get("version")),
            "schemaVersion": share_meta.get("schemaVersion", preview["schemaVersion"]),
            "author": share_meta.get("author", ""),
            "sourceUrl": share_meta.get("sourceUrl", ""),
            "tags": share_meta.get("tags", []),
            "exportedAt": share_meta.get("exportedAt", ""),
        }
        return {
            "ok": True,
            "valid": True,
            "errors": [],
            "warnings": warnings,
            "packageFiles": [name for name in member_names if not name.endswith("/")],
            "node": preview,
            "shareMeta": normalized_share_meta,
            "localNode": local_node,
            "versionComparison": version_comparison,
        }
    finally:
        temp_zip.unlink(missing_ok=True)


@router.post("/import", dependencies=[Depends(require_permission("workflow:write"))])
async def import_node_type(
    file: UploadFile = File(...),
    allowOverwrite: bool = Form(False),
    createBackup: bool = Form(False),
    renameTo: str = Form(""),
):
    """Import a node type from a ZIP file.
    ZIP should contain node_config.json + optional run.py + requirements.txt + other files.

    renameTo: 以新 id 重命名导入（包内 node id 将被替换为新 id，作为全新节点安装，
    不触发覆盖逻辑；新 id 不得与内置/现有自定义节点冲突）。
    """
    if not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a ZIP file")

    content = await file.read()

    def _do_import():
        temp_zip = NODE_TYPES_DIR / f"_temp_{uuid.uuid4().hex[:8]}.zip"
        try:
            with open(temp_zip, "wb") as f:
                f.write(content)

            member_names, node_data, share_meta = _load_package_payload(temp_zip)
            node_data, warnings = _analyze_package(node_data, member_names, share_meta)

            rename_to = _validate_node_id(renameTo) if renameTo.strip() else ""
            is_rename = bool(rename_to)
            if is_rename:
                if rename_to == node_data.get("id"):
                    raise HTTPException(status_code=400, detail="renameTo must be different from the package node id")
                if rename_to in BUILTIN_NODE_IDS:
                    raise HTTPException(status_code=400, detail=f"Cannot rename to a built-in node type id: {rename_to}")
                if _get_existing_custom_node(rename_to):
                    raise HTTPException(status_code=409, detail=f"Node type id already exists: {rename_to}，请更换其他名称")
                node_data["id"] = rename_to
                node_id = rename_to
                local_node = None
                package_version = _normalize_version(node_data.get("version") or share_meta.get("version"))
                version_comparison = {
                    "status": "new",
                    "message": f"将以新 id {rename_to} 安装节点 {node_data.get('name', rename_to)} {package_version}",
                    "localVersion": "",
                    "packageVersion": package_version,
                    "requiresConfirmation": False,
                    "recommendedBackup": False,
                }
            else:
                node_id = node_data.get("id", "")
                local_node, version_comparison = _build_version_comparison(
                    node_id,
                    node_data.get("name", node_id),
                    _normalize_version(node_data.get("version") or share_meta.get("version")),
                )
                if local_node and not allowOverwrite:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Node type already exists. {version_comparison['message']}；请确认覆盖后重试。",
                    )

            backup_path = ""
            if local_node and createBackup:
                backup_path = _backup_existing_node(node_id, local_node)

            # Create node code directory: backend/nodes/{node_id}/
            nodes_code_dir = Path(__file__).parent.parent / "nodes" / node_id
            if nodes_code_dir.exists():
                shutil.rmtree(nodes_code_dir)
            nodes_code_dir.mkdir(parents=True, exist_ok=True)

            # Extract all files from ZIP to node code directory
            with zipfile.ZipFile(temp_zip, "r") as zf:
                for member in member_names:
                    if member.startswith("__MACOSX") or member.startswith("."):
                        continue
                    normalized_member = member.replace("\\", "/")
                    target = (nodes_code_dir / normalized_member).resolve()
                    if nodes_code_dir.resolve() not in target.parents:
                        raise HTTPException(status_code=400, detail=f"Invalid package member path: {member}")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not member.endswith("/"):
                        with zf.open(member) as src, open(target, "wb") as dst:
                            dst.write(src.read())

            # Update execFile to point to extracted run.py
            if node_data.get("execType") == "python" and node_data.get("execFile"):
                node_data["execFile"] = str(nodes_code_dir / node_data["execFile"])

            # Install requirements.txt if present
            req_file = nodes_code_dir / "requirements.txt"
            install_result = ""
            if req_file.exists():
                raise HTTPException(status_code=400, detail="requirements.txt is not supported for direct node import")

            # Save node config JSON
            node_data["isBuiltIn"] = False
            node_data["codeDir"] = str(nodes_code_dir)
            node_data["schemaVersion"] = PACKAGE_SCHEMA_VERSION
            node_data["version"] = _normalize_version(node_data.get("version") or share_meta.get("version"))
            fpath = NODE_TYPES_DIR / f"{node_id}.json"
            _atomic_json_write(fpath, node_data)

            # List extracted files
            extracted = [str(p.relative_to(nodes_code_dir)) for p in nodes_code_dir.rglob("*") if p.is_file()]

            return {
                "ok": True,
                "node": node_data,
                "extractedFiles": extracted,
                "installResult": install_result,
                "packageWarnings": warnings,
                "backupPath": backup_path,
                "versionComparison": version_comparison,
            }
        finally:
            temp_zip.unlink(missing_ok=True)

    return await asyncio.to_thread(_do_import)

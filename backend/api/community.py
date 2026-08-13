"""共享社区：打包与发布。

打包规范（每个节点/工作流 = 一个文件夹）：
    share/community/{resourceId}/
      ├─ resource.json     # 介绍：type/name/description/author/category/tags/version/sourceId
      ├─ node_config.json  # 节点定义（净化后，同现有导出）
      ├─ code/...          # 节点代码目录（可选）
      ├─ workflow.json     # 标准化工作流（仅工作流）
      └─ preview.png       # 快照附图

发布时把文件夹内容上传到 Cloudflare Worker（POST {baseUrl}/api/resources，公开接口），
Worker 负责写入 R2 并登记 D1 元数据。

安全设计（软件分发场景）：
- 社区 Worker 地址由前端在构建时注入（VITE_COMMUNITY_API_URL），随软件分发，无需用户配置；
- 发布上传为公开接口（Worker 侧内置大小限制与限频防滥用）；
- 治理删除令牌（ADMIN_TOKEN）只保存在 Cloudflare Secret 中，不进入分发包与本地配置。
"""
import io
import json
import mimetypes
import os
import shutil
import tempfile
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from backend.api.node_types import (
    NODE_TYPES_DIR,
    _backup_existing_node,
    _build_version_comparison,
    _get_existing_custom_node,
    _is_archive_member_included,
    _normalize_version,
    _prepare_export_node_data,
    get_builtin_node_type,
)
from backend.api.workflows import WORKFLOWS_DIR
from backend.config.builtin_node_types import BUILTIN_NODE_IDS
from backend.config.node_schema import validate_node_type_data
from backend.workflow_validation import normalize_workflow

router = APIRouter(prefix="/api/community", tags=["community"])

COMMUNITY_DIR = Path(__file__).parent.parent.parent / "share" / "community"
COMMUNITY_DIR.mkdir(parents=True, exist_ok=True)


def _resource_json(
    resource_id: str, type_: str, name: str, description: str,
    author: str, category: str, tags: List[str], version: str, source_id: str,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "type": type_,
        "name": name,
        "description": description,
        "author": author,
        "category": category,
        "tags": tags,
        "version": version,
        "sourceId": source_id,
        "resourceId": resource_id,
        "createdAt": now,
        "updatedAt": now,
    }


def _parse_tags(raw: str) -> List[str]:
    try:
        value = json.loads(raw or "[]")
        if not isinstance(value, list):
            return []
        return [str(t).strip() for t in value if str(t).strip()]
    except (json.JSONDecodeError, TypeError):
        return []


def _generate_placeholder_preview(text: str, color: str = "#6366f1") -> bytes:
    """生成 640x360 占位预览图（Pillow，已依赖）。"""
    from PIL import Image, ImageDraw, ImageFont

    w, h = 640, 360
    img = Image.new("RGB", (w, h), color)
    draw = ImageDraw.Draw(img)
    font = None
    for fp in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            font = ImageFont.truetype(fp, 26)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()
    draw.text((24, h - 60), (text or "Community").strip()[:24], fill="white", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _write_preview(folder: Path, preview: Optional[UploadFile], fallback_text: str) -> None:
    if preview and preview.filename:
        content = preview.file.read()
        if content:
            (folder / "preview.png").write_bytes(content)
            return
    if not (folder / "preview.png").exists():
        (folder / "preview.png").write_bytes(_generate_placeholder_preview(fallback_text))


def _bundle_workflow_nodes(folder: Path, wf: dict) -> tuple[List[str], List[str]]:
    """把工作流引用的本地自定义节点定义捆绑进包（nodes/{nodeId}/）。

    仅捆绑本地存在的自定义节点；内置节点无需捆绑；无法导出（如 python 节点
    无内联代码且代码目录不可达）的节点跳过并记入告警，避免阻断整个工作流分享。
    """
    bundled: List[str] = []
    skipped: List[str] = []
    node_ids = {
        n.get("data", {}).get("nodeType")
        for n in wf.get("nodes", [])
        if isinstance(n, dict) and isinstance(n.get("data"), dict)
    }
    for nid in node_ids:
        if not nid or nid in BUILTIN_NODE_IDS:
            continue
        fpath = NODE_TYPES_DIR / f"{nid}.json"
        if not fpath.exists():
            continue  # 作者本地也没有该节点定义（未知类型），跳过
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                node_data = json.load(f)
            node_data["isBuiltIn"] = False
            export_data, code_dir = _prepare_export_node_data(node_data)
            nfolder = folder / "nodes" / nid
            nfolder.mkdir(parents=True, exist_ok=True)
            with open(nfolder / "node_config.json", "w", encoding="utf-8") as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            if code_dir and os.path.isdir(code_dir):
                for root, dirs, files in os.walk(code_dir):
                    dirs[:] = [d for d in dirs if _is_archive_member_included(os.path.join(root, d))]
                    for fname in files:
                        src = os.path.join(root, fname)
                        rel = os.path.relpath(src, code_dir).replace("\\", "/")
                        if not _is_archive_member_included(rel):
                            continue
                        target = nfolder / rel
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, target)
            bundled.append(nid)
        except HTTPException as exc:
            skipped.append(f"{nid}（{exc.detail}）")
        except Exception:
            skipped.append(nid)
    return bundled, skipped


# ---------------------------------------------------------------- #
# 打包                                                               #
# ---------------------------------------------------------------- #
@router.post("/pack-node")
async def pack_node(
    nodeId: str = Form(...),
    shareName: str = Form(""),
    description: str = Form(""),
    author: str = Form(""),
    category: str = Form(""),
    tags: str = Form("[]"),
    version: str = Form(""),
    preview: Optional[UploadFile] = File(None),
):
    node_id = nodeId.strip()
    if not node_id:
        raise HTTPException(status_code=400, detail="nodeId required")

    fpath = NODE_TYPES_DIR / f"{node_id}.json"
    if fpath.exists():
        with open(fpath, "r", encoding="utf-8") as f:
            node_data = json.load(f)
        node_data["isBuiltIn"] = False
    else:
        node_data = get_builtin_node_type(node_id)
        if not node_data:
            raise HTTPException(status_code=404, detail="Node type not found")
        node_data["isBuiltIn"] = True

    export_data, code_dir = _prepare_export_node_data(node_data)

    name = shareName.strip() or export_data.get("name", node_id)
    desc = description.strip() or export_data.get("description", "")
    author_v = author.strip()
    category_v = category.strip() or export_data.get("category", "process")
    version_v = version.strip() or export_data.get("version", "1.0.0")
    tags_list = _parse_tags(tags)

    resource_id = uuid.uuid4().hex[:12]
    folder = COMMUNITY_DIR / resource_id
    folder.mkdir(parents=True, exist_ok=True)

    with open(folder / "node_config.json", "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)

    # 复制代码目录（与 ZIP 导出规则一致：顶层隐藏目录 / __MACOSX 不打包）
    if code_dir and os.path.isdir(code_dir):
        for root, dirs, files in os.walk(code_dir):
            dirs[:] = [d for d in dirs if _is_archive_member_included(os.path.join(root, d))]
            for fname in files:
                src = os.path.join(root, fname)
                rel = os.path.relpath(src, code_dir).replace("\\", "/")
                if not _is_archive_member_included(rel):
                    continue
                target = folder / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)

    _write_preview(folder, preview, name)

    resource = _resource_json(resource_id, "node", name, desc, author_v, category_v, tags_list, version_v, node_id)
    with open(folder / "resource.json", "w", encoding="utf-8") as f:
        json.dump(resource, f, ensure_ascii=False, indent=2)

    files = [str(p.relative_to(folder)).replace("\\", "/") for p in folder.rglob("*") if p.is_file()]
    return {"resourceId": resource_id, "folder": folder.name, "files": files}


@router.post("/pack-workflow")
async def pack_workflow(
    workflow: str = Form(...),
    shareName: str = Form(""),
    description: str = Form(""),
    author: str = Form(""),
    category: str = Form(""),
    tags: str = Form("[]"),
    version: str = Form(""),
    preview: Optional[UploadFile] = File(None),
):
    try:
        wf_data = json.loads(workflow)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="workflow must be a JSON string")
    if not isinstance(wf_data, dict):
        raise HTTPException(status_code=400, detail="workflow must be an object")

    wf, _migrated, _removed = normalize_workflow(wf_data)

    name = shareName.strip() or wf.get("name", "未命名工作流")
    desc = description.strip() or wf.get("description", "")
    author_v = author.strip()
    category_v = category.strip() or "通用工作流"
    version_v = version.strip() or "1.0.0"
    tags_list = _parse_tags(tags)

    resource_id = uuid.uuid4().hex[:12]
    folder = COMMUNITY_DIR / resource_id
    folder.mkdir(parents=True, exist_ok=True)

    wf["name"] = name
    if desc:
        wf["description"] = desc
    with open(folder / "workflow.json", "w", encoding="utf-8") as f:
        json.dump(wf, f, ensure_ascii=False, indent=2)

    # 捆绑工作流引用的自定义节点（nodes/{nodeId}/node_config.json + 代码），
    # 便于下载方一键补齐；无法导出的节点跳过并记录告警。
    bundled_nodes, skipped_nodes = _bundle_workflow_nodes(folder, wf)

    _write_preview(folder, preview, name)

    resource = _resource_json(resource_id, "workflow", name, desc, author_v, category_v, tags_list, version_v, wf.get("id", ""))
    resource["bundledNodes"] = bundled_nodes
    if skipped_nodes:
        resource["skippedNodes"] = skipped_nodes
    with open(folder / "resource.json", "w", encoding="utf-8") as f:
        json.dump(resource, f, ensure_ascii=False, indent=2)

    files = [str(p.relative_to(folder)).replace("\\", "/") for p in folder.rglob("*") if p.is_file()]
    return {
        "resourceId": resource_id,
        "folder": folder.name,
        "files": files,
        "bundledNodes": bundled_nodes,
        "skippedNodes": skipped_nodes,
    }


# ---------------------------------------------------------------- #
# 发布（上传到 Cloudflare Worker 公开接口）                           #
# ---------------------------------------------------------------- #
@router.post("/publish")
async def publish(folder: str = Form(...), baseUrl: str = Form("")):
    base_url = baseUrl.strip().rstrip("/")
    if not base_url:
        raise HTTPException(status_code=400, detail="社区服务地址未配置（VITE_COMMUNITY_API_URL）")

    rel = folder.strip().strip("/\\")
    folder_path = (COMMUNITY_DIR / rel).resolve()
    if not str(folder_path).startswith(str(COMMUNITY_DIR.resolve())) or not folder_path.is_dir():
        raise HTTPException(status_code=404, detail="打包目录不存在")

    resource_path = folder_path / "resource.json"
    if not resource_path.exists():
        raise HTTPException(status_code=400, detail="缺少 resource.json，请先打包")
    with open(resource_path, "r", encoding="utf-8") as f:
        resource = json.load(f)

    preview_path = folder_path / "preview.png"
    content_files = [
        p for p in folder_path.rglob("*")
        if p.is_file() and p not in (resource_path, preview_path)
    ]

    data = {
        "type": resource.get("type", ""),
        "name": resource.get("name", ""),
        "description": resource.get("description", ""),
        "author": resource.get("author", ""),
        "category": resource.get("category", ""),
        "tags": json.dumps(resource.get("tags", []), ensure_ascii=False),
        "version": resource.get("version", "1.0.0"),
        "sourceId": resource.get("sourceId", ""),
    }
    files = [
        (
            "files",
            (
                str(p.relative_to(folder_path)).replace("\\", "/"),
                p.read_bytes(),
                mimetypes.guess_type(p.name)[0] or "application/octet-stream",
            ),
        )
        for p in content_files
    ]
    if preview_path.exists():
        files.append(("preview", ("preview.png", preview_path.read_bytes(), "image/png")))

    try:
        async with httpx.AsyncClient(timeout=120) as http:
            resp = await http.post(
                f"{base_url}/api/resources",
                data=data,
                files=files,
            )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"社区服务连接失败: {exc}")

    if resp.status_code != 201:
        try:
            detail = resp.json().get("error", resp.text)
        except Exception:
            detail = resp.text
        raise HTTPException(status_code=resp.status_code, detail=f"发布失败: {detail}")

    result = resp.json()
    return {**result, "url": f"{base_url}/api/resources/{result['id']}"}


# ---------------------------------------------------------------- #
# 工作流导入：分析 + 安装（含捆绑的自定义节点）                         #
# ---------------------------------------------------------------- #
def _extract_workflow_summary(zip_path: Path) -> dict:
    with zipfile.ZipFile(zip_path) as zf:
        try:
            wf = json.loads(zf.read("workflow.json"))
        except Exception:
            raise HTTPException(status_code=400, detail="无效的工作流包：缺少或损坏的 workflow.json")
    nodes = wf.get("nodes", []) if isinstance(wf, dict) else []
    return {
        "id": wf.get("id", "") if isinstance(wf, dict) else "",
        "name": wf.get("name", "未命名工作流") if isinstance(wf, dict) else "未命名工作流",
        "nodeCount": len(nodes) if isinstance(nodes, list) else 0,
    }


def _extract_bundled_nodes(zip_path: Path) -> list:
    """预检：列出包内捆绑的自定义节点及与本地版本的对比结果。"""
    result = []
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            if not member.startswith("nodes/") or not member.endswith("/node_config.json"):
                continue
            parts = member.split("/")
            if len(parts) < 2:
                continue
            node_id = parts[1]
            try:
                cfg = json.loads(zf.read(member))
            except Exception:
                continue
            name = str(cfg.get("name", node_id) or node_id)
            version = _normalize_version(cfg.get("version"))
            if node_id in BUILTIN_NODE_IDS:
                continue
            local_node, comparison = _build_version_comparison(node_id, name, version)
            result.append({
                "nodeId": node_id,
                "name": name,
                "version": version,
                "status": comparison.get("status", "new"),
                "localVersion": comparison.get("localVersion", ""),
                "exists": local_node is not None,
                "message": comparison.get("message", ""),
            })
    return result


@router.post("/analyze-workflow-package")
async def analyze_workflow_package(file: UploadFile = File(...)):
    """预检工作流包：工作流摘要 + 捆绑节点列表（含本地版本对比）。"""
    content = await file.read()
    with tempfile.TemporaryDirectory() as td:
        zip_path = Path(td) / "pkg.zip"
        zip_path.write_bytes(content)
        return {
            "workflow": _extract_workflow_summary(zip_path),
            "nodes": _extract_bundled_nodes(zip_path),
        }


def _install_node_from_dir(node_dir: Path, rename_to: str = "") -> dict:
    """从包内节点目录安装节点（覆盖前自动备份；rename_to 以新 id 安装）。"""
    cfg_path = node_dir / "node_config.json"
    if not cfg_path.exists():
        raise HTTPException(status_code=400, detail=f"节点目录缺少 node_config.json: {node_dir.name}")
    with open(cfg_path, "r", encoding="utf-8") as f:
        node_data = json.load(f)
    node_id = str(node_data.get("id", "") or "").strip()
    if not node_id:
        raise HTTPException(status_code=400, detail="节点缺少 id")
    if node_id in BUILTIN_NODE_IDS:
        raise HTTPException(status_code=400, detail=f"不能安装内置节点: {node_id}")

    renamed = False
    if rename_to:
        renamed = True
        if rename_to == node_id:
            raise HTTPException(status_code=400, detail="renameTo 不能与原节点 id 相同")
        if rename_to in BUILTIN_NODE_IDS:
            raise HTTPException(status_code=400, detail=f"不能重命名为内置节点 id: {rename_to}")
        if _get_existing_custom_node(rename_to):
            raise HTTPException(status_code=409, detail=f"节点 id 已存在: {rename_to}")
        node_data["id"] = rename_to
        node_id = rename_to

    local_node = _get_existing_custom_node(node_id)
    backup_path = ""
    if local_node:
        backup_path = str(_backup_existing_node(node_id, local_node))

    nodes_code_dir = Path(__file__).parent.parent / "nodes" / node_id
    if nodes_code_dir.exists():
        shutil.rmtree(nodes_code_dir)
    nodes_code_dir.mkdir(parents=True, exist_ok=True)
    for f in node_dir.rglob("*"):
        if not f.is_file() or f == cfg_path:
            continue
        rel = f.relative_to(node_dir)
        target = nodes_code_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)

    if node_data.get("execType") == "python" and node_data.get("execFile"):
        node_data["execFile"] = str(nodes_code_dir / node_data["execFile"])

    node_data["isBuiltIn"] = False
    node_data["codeDir"] = str(nodes_code_dir)
    node_data["schemaVersion"] = "1.0"
    node_data["version"] = _normalize_version(node_data.get("version"))
    try:
        validate_node_type_data(node_data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    fpath = NODE_TYPES_DIR / f"{node_id}.json"
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(node_data, f, ensure_ascii=False, indent=2)
    return {
        "nodeId": node_id,
        "action": "rename" if renamed else "install",
        "newId": node_id if renamed else None,
        "backupPath": backup_path or None,
    }


@router.post("/import-workflow")
async def import_workflow_package(
    file: UploadFile = File(...),
    name: str = Form(""),
    decisions: str = Form("{}"),
):
    """导入工作流：按 decisions 安装捆绑节点（install/rename/skip）+ 保存为新的全局工作流。

    decisions: {"节点id": {"action": "install"|"rename"|"skip", "renameTo": "新id"}}
    """
    try:
        decision_map = json.loads(decisions or "{}")
        if not isinstance(decision_map, dict):
            decision_map = {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="decisions 必须为 JSON 对象")

    content = await file.read()
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        zip_path = td_path / "pkg.zip"
        zip_path.write_bytes(content)
        extract_dir = td_path / "pkg"
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)

        # 1) 解析并保存工作流
        wf_path = extract_dir / "workflow.json"
        if not wf_path.exists():
            raise HTTPException(status_code=400, detail="无效的工作流包：缺少 workflow.json")
        with open(wf_path, "r", encoding="utf-8") as f:
            wf_data = json.load(f)
        wf, _migrated, _removed = normalize_workflow(wf_data)
        wf_name = name.strip() or wf.get("name", "未命名工作流")
        wf["name"] = wf_name
        new_id = uuid.uuid4().hex[:12]
        wf["id"] = new_id
        wf["type"] = "user"
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        wf["createdAt"] = wf.get("createdAt") or now
        wf["updatedAt"] = now

        # 2) 按决策安装捆绑节点
        installed: list = []
        failed: list = []
        nodes_root = extract_dir / "nodes"
        if nodes_root.is_dir():
            for nfolder in sorted(nodes_root.iterdir()):
                if not nfolder.is_dir():
                    continue
                node_id = nfolder.name
                decision = decision_map.get(node_id, {}) or {}
                action = str(decision.get("action", "install"))
                if action == "skip":
                    continue
                rename_to = str(decision.get("renameTo", "") or "").strip()
                if action == "rename" and not rename_to:
                    failed.append({"nodeId": node_id, "error": "改名导入需要填写新 id"})
                    continue
                try:
                    installed.append(_install_node_from_dir(nfolder, rename_to=rename_to))
                except HTTPException as exc:
                    failed.append({"nodeId": node_id, "error": str(exc.detail)})
                except Exception as exc:
                    failed.append({"nodeId": node_id, "error": str(exc)})

        # 3) 写盘
        fp = Path(WORKFLOWS_DIR) / f"{new_id}.json"
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(wf, f, ensure_ascii=False, indent=2)

    return {
        "workflow": {"id": new_id, "name": wf_name},
        "installed": installed,
        "failed": failed,
    }


# ---------------------------------------------------------------- #
# 本地已打包列表（管理用）                                            #
# ---------------------------------------------------------------- #
@router.get("/packages")
async def list_packages():
    packages = []
    for folder in sorted(COMMUNITY_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not folder.is_dir():
            continue
        resource = {}
        rp = folder / "resource.json"
        if rp.exists():
            try:
                with open(rp, "r", encoding="utf-8") as f:
                    resource = json.load(f)
            except Exception:
                resource = {}
        files = [str(p.relative_to(folder)).replace("\\", "/") for p in folder.rglob("*") if p.is_file()]
        packages.append({
            "resourceId": folder.name,
            "folder": folder.name,
            "name": resource.get("name", ""),
            "type": resource.get("type", ""),
            "createdAt": resource.get("createdAt", ""),
            "files": files,
        })
    return {"packages": packages}

"""User data backup / restore API.

將用户数据备份到「项目之外」的目录，避免被更新覆盖。
备份内容可选择：接口配置、全局设置参数、字幕样式、工作流、自定义节点。
每次备份会生成一个带 manifest.json 的文件夹，恢复时据此重建。
恢复支持两种模式：覆盖模式（overwrite）与增量恢复模式（incremental）。
"""
import json
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

router = APIRouter(tags=["backup"])

BACKUP_TYPE = "videolingo-userdata-backup"
MANIFEST_VERSION = 1

# 接口配置文件（独立于 config.yaml）
INTERFACE_FILES = [
    "asr_interfaces.json",
    "tts_interfaces.json",
    "ocr_interfaces.json",
    "imagegen_interfaces.json",
    "separation_interfaces.json",
    "videogen_interfaces.json",
]

CATEGORIES = {
    "interface": {
        "label": "接口配置",
        "description": "ASR / TTS / OCR / 图像生成 / 音频分离 / 视频生成 等接口定义文件",
    },
    "globalsettings": {
        "label": "全局设置参数",
        "description": "config.yaml 全部参数（含 LLM 接口密钥与模型配置）",
    },
    "subtitle": {
        "label": "字幕样式",
        "description": "字幕预设样式（subtitle_presets 目录）",
    },
    "workflow": {
        "label": "工作流",
        "description": "用户工作流定义与分组（workflows 目录 + workflow_groups.json）",
    },
    "customnode": {
        "label": "自定义节点",
        "description": "自定义节点类型与内置节点删除记录（node_types 目录）",
    },
}


# ---------- 路径校验 ----------

def _require_outside_project(path: Path) -> Path:
    """校验备份存放目录必须位于项目之外，避免被更新覆盖。"""
    p = path.resolve()
    proj = PROJECT_ROOT.resolve()
    if p == proj or proj in p.parents:
        raise HTTPException(
            status_code=400,
            detail="备份目录必须位于项目之外（项目目录及其子目录内不允许），防止被更新刷掉",
        )
    if not p.is_absolute():
        raise HTTPException(status_code=400, detail="请提供绝对路径作为备份目录")
    return p


def _validate_backup_folder(path: Path) -> Path:
    """校验指定文件夹是一个合法的 VideoLingoLc 用户数据备份。"""
    folder = path.resolve()
    manifest_path = folder / "manifest.json"
    if not manifest_path.is_file():
        raise HTTPException(status_code=400, detail="所选路径不是有效的备份（缺少 manifest.json）")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="manifest.json 解析失败")
    if manifest.get("type") != BACKUP_TYPE:
        raise HTTPException(status_code=400, detail="不是 VideoLingoLc 用户数据备份")
    return folder


# ---------- 源文件枚举 ----------

def _category_source_files(category: str):
    """返回 [(abs_src, srcRel, destRel), ...]，srcRel 以 data/ 开头，destRel 相对 CONFIG_DIR。"""
    files = []
    if category == "interface":
        for fn in INTERFACE_FILES:
            p = CONFIG_DIR / fn
            if p.exists():
                files.append((p, f"data/{fn}", fn))
    elif category == "globalsettings":
        p = CONFIG_DIR / "config.yaml"
        if p.exists():
            files.append((p, "data/config.yaml", "config.yaml"))
    elif category == "subtitle":
        d = CONFIG_DIR / "subtitle_presets"
        if d.is_dir():
            for f in sorted(d.glob("*.json")):
                files.append((f, f"data/subtitle_presets/{f.name}", f"subtitle_presets/{f.name}"))
    elif category == "workflow":
        d = CONFIG_DIR / "workflows"
        if d.is_dir():
            for f in sorted(d.glob("*.json")):
                files.append((f, f"data/workflows/{f.name}", f"workflows/{f.name}"))
        g = CONFIG_DIR / "workflow_groups.json"
        if g.exists():
            files.append((g, "data/workflows/workflow_groups.json", "workflow_groups.json"))
    elif category == "customnode":
        d = CONFIG_DIR / "node_types"
        if d.is_dir():
            for f in sorted(d.glob("*.json")):
                files.append((f, f"data/node_types/{f.name}", f"node_types/{f.name}"))
        g = CONFIG_DIR / "deleted_builtin_node_ids.json"
        if g.exists():
            files.append((g, "data/node_types/deleted_builtin_node_ids.json", "deleted_builtin_node_ids.json"))
    return files


# ---------- 合并工具 ----------

def _deep_merge(base: dict, over: dict) -> dict:
    for k, v in over.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def _merge_file(src: Path, dest: Path) -> None:
    """增量模式下，按文件类型合并（dict 深合并 / yaml 顶层合并），而非简单覆盖。"""
    if dest.suffix == ".json":
        base = json.loads(dest.read_text(encoding="utf-8")) if dest.exists() else {}
        over = json.loads(src.read_text(encoding="utf-8"))
        if isinstance(base, dict) and isinstance(over, dict):
            _deep_merge(base, over)
        else:
            base = over
        dest.write_text(json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")
    elif dest.suffix in (".yaml", ".yml"):
        from ruamel.yaml import YAML

        y = YAML()
        y.preserve_quotes = True
        base = y.load(dest.read_text(encoding="utf-8")) or {}
        over = y.load(src.read_text(encoding="utf-8")) or {}
        if isinstance(base, dict) and isinstance(over, dict):
            for k, v in over.items():
                base[k] = v
        else:
            base = over
        y.dump(base, dest.open("w", encoding="utf-8"))
    else:
        shutil.copy2(src, dest)


# ---------- 请求模型 ----------

class CreateBackupRequest(BaseModel):
    backupDir: str
    options: list[str] = []


class RestoreRequest(BaseModel):
    backupPath: str
    options: list[str] = []
    mode: str = "overwrite"  # overwrite | incremental


# ---------- 路由 ----------

@router.get("/options")
async def backup_options():
    """返回可备份项及其当前数据量，供前端渲染选项。"""
    out = []
    for cid, meta in CATEGORIES.items():
        out.append({
            "id": cid,
            "label": meta["label"],
            "description": meta["description"],
            "currentCount": len(_category_source_files(cid)),
        })
    return {"options": out}


@router.get("/list")
async def list_backups(dir: str):
    """列出某目录下所有合法的 VideoLingoLc 用户数据备份。"""
    base = _require_outside_project(Path(dir))
    if not base.is_dir():
        raise HTTPException(status_code=400, detail="备份目录不存在")
    backups = []
    for folder in sorted(base.iterdir(), reverse=True):
        if not folder.is_dir():
            continue
        manifest_path = folder / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("type") != BACKUP_TYPE:
            continue
        backups.append({
            "path": str(folder),
            "name": folder.name,
            "createdAt": manifest.get("createdAt", ""),
            "options": manifest.get("options", []),
            "itemCount": len(manifest.get("items", [])),
        })
    return {"backups": backups}


@router.post("/create")
async def create_backup(req: CreateBackupRequest):
    """在指定（项目之外）目录创建一次用户数据备份。"""
    base = _require_outside_project(Path(req.backupDir))
    opts = [o for o in req.options if o in CATEGORIES]
    if not opts:
        raise HTTPException(status_code=400, detail="请至少选择一个备份项")
    base.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = base / f"videolingo_userdata_{ts}"
    # 同一秒多次备份时避免冲突
    n = 1
    while folder.exists():
        folder = base / f"videolingo_userdata_{ts}_{n}"
        n += 1

    data_dir = folder / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    items = []
    copied = 0
    for cat in opts:
        for abs_src, src_rel, dest_rel in _category_source_files(cat):
            dst = folder / src_rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(abs_src, dst)
            items.append({"category": cat, "srcRel": src_rel, "destRel": dest_rel})
            copied += 1

    manifest = {
        "app": "VideoLingoLc",
        "type": BACKUP_TYPE,
        "version": MANIFEST_VERSION,
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "options": opts,
        "items": items,
    }
    (folder / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "success": True,
        "backupPath": str(folder),
        "createdAt": manifest["createdAt"],
        "options": opts,
        "itemCount": copied,
    }


def _pre_delete(cat: str, planned_dests: set, mode: str) -> None:
    """覆盖模式下，先删除目标目录中「未被本次备份覆盖」的用户数据文件。

    工作流目录会保留 type=="task" 的任务工作流，避免破坏正在进行的任务。
    """
    if mode != "overwrite":
        return
    if cat == "subtitle":
        d = CONFIG_DIR / "subtitle_presets"
        if d.is_dir():
            for f in d.glob("*.json"):
                if f not in planned_dests:
                    f.unlink()
    elif cat == "workflow":
        d = CONFIG_DIR / "workflows"
        if d.is_dir():
            for f in d.glob("*.json"):
                if f in planned_dests:
                    continue
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
                if data.get("type") == "task":
                    continue
                f.unlink()
        g = CONFIG_DIR / "workflow_groups.json"
        if g.exists() and g not in planned_dests:
            g.unlink()
    elif cat == "customnode":
        d = CONFIG_DIR / "node_types"
        if d.is_dir():
            for f in d.glob("*.json"):
                if f not in planned_dests:
                    f.unlink()
        g = CONFIG_DIR / "deleted_builtin_node_ids.json"
        if g.exists() and g not in planned_dests:
            g.unlink()


def _restore_category(cat: str, folder: Path, manifest: dict, mode: str) -> int:
    items = [it for it in manifest.get("items", []) if it.get("category") == cat]
    if not items:
        return 0
    planned = []
    for it in items:
        src = folder / it["srcRel"]
        if not src.exists():
            continue
        dest = CONFIG_DIR / it["destRel"]
        planned.append((src, dest))
    planned_dests = {d for _, d in planned}
    _pre_delete(cat, planned_dests, mode)

    written = 0
    for src, dest in planned:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if mode == "incremental" and dest.exists() and dest.suffix in (".json", ".yaml", ".yml"):
            _merge_file(src, dest)
        else:
            shutil.copy2(src, dest)
        written += 1
    return written


@router.post("/restore")
async def restore_backup(req: RestoreRequest):
    """从指定备份文件夹恢复用户数据。"""
    folder = _validate_backup_folder(Path(req.backupPath))
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))

    opts = [o for o in req.options if o in CATEGORIES and o in manifest.get("options", [])]
    if not opts:
        raise HTTPException(status_code=400, detail="请选择要恢复的备份项")
    mode = req.mode if req.mode in ("overwrite", "incremental") else "overwrite"

    results = []
    for cat in opts:
        n = _restore_category(cat, folder, manifest, mode)
        results.append({"category": cat, "restored": n, "label": CATEGORIES[cat]["label"]})
    return {"success": True, "mode": mode, "restored": results}

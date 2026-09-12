# -*- coding: utf-8 -*-
"""引擎适配层基础设施：输出类型 / 任务台账 / 输入物化 / 接口挑选。

设计原则（对应迁移计划 v2）：
- 引擎调用一律「落盘优先」，EngineOutput 持有盘上路径；base64 仅作兼容出口；
- referenceList 输入兼容 本地路径 / http(s) URL / data URI，统一物化为本地文件；
- 每次调用可包 with_task_record() 写 tf_tasks 台账（对齐源 withTaskRecord）。
"""
import base64
import binascii
import shutil
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import requests


class EngineOutput:
    """引擎产物：落盘文件列表 + base64 兼容出口（对齐源 vendor 契约的有头 base64）。"""

    def __init__(self, paths: list[str]):
        self.paths = [str(p) for p in paths]

    @property
    def first(self) -> str:
        if not self.paths:
            raise RuntimeError("引擎未返回任何产物")
        return self.paths[0]

    @property
    def ok(self) -> bool:
        return bool(self.paths)

    def to_base64(self, index: int = 0) -> str:
        """有头 base64（data:image/png;base64,...），对齐源 imageRequest 返回契约。"""
        p = Path(self.paths[index])
        mime = "image/png"
        suffix = p.suffix.lower()
        if suffix in (".jpg", ".jpeg"):
            mime = "image/jpeg"
        elif suffix == ".webp":
            mime = "image/webp"
        elif suffix in (".wav",):
            mime = "audio/wav"
        elif suffix in (".mp3",):
            mime = "audio/mpeg"
        elif suffix in (".mp4",):
            mime = "video/mp4"
        data = base64.b64encode(p.read_bytes()).decode()
        return f"data:{mime};base64,{data}"

    def save(self, path: str | Path, index: int = 0) -> str:
        """把产物复制/移动到指定路径（对齐源 .save(path)），返回目标路径。"""
        src = Path(self.paths[index])
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        return str(dest)

    def __repr__(self) -> str:  # pragma: no cover
        return f"EngineOutput(paths={self.paths})"


def materialize_input(value, out_dir: str | Path) -> str:
    """把 referenceList 项物化为本地文件，返回路径。

    支持：本地路径 / http(s) URL / data URI。失败抛 ValueError。
    """
    if value is None:
        raise ValueError("空的参考输入")
    v = str(value).strip()
    if not v:
        raise ValueError("空的参考输入")

    # 本地路径
    p = Path(v)
    if p.is_file():
        return str(p)

    # data URI
    if v.startswith("data:"):
        try:
            header, b64 = v.split(",", 1)
        except ValueError:
            raise ValueError("非法 data URI（缺少逗号）")
        mime = header[5:].split(";")[0] or "image/png"
        ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(mime, "png")
        try:
            raw = base64.b64decode(b64, validate=True)
        except binascii.Error as exc:
            raise ValueError(f"非法 base64: {exc}")
        out = Path(out_dir) / f"ref_{uuid.uuid4().hex[:8]}.{ext}"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(raw)
        return str(out)

    # http(s) URL
    if v.startswith(("http://", "https://")):
        resp = requests.get(v, timeout=60)
        if resp.status_code != 200:
            raise ValueError(f"下载参考输入失败: HTTP {resp.status_code}")
        ctype = resp.headers.get("content-type", "")
        ext = "png"
        if "jpeg" in ctype or "jpg" in ctype:
            ext = "jpg"
        elif "webp" in ctype:
            ext = "webp"
        elif "mp4" in ctype:
            ext = "mp4"
        elif "audio" in ctype:
            ext = "wav"
        out = Path(out_dir) / f"ref_{uuid.uuid4().hex[:8]}.{ext}"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(resp.content)
        return str(out)

    raise ValueError(f"参考输入不存在或不可识别: {v[:80]}")


def normalize_refs(reference_list, out_dir) -> list[str]:
    """referenceList → 本地路径列表（保持顺序）。"""
    refs = list(reference_list or [])
    return [materialize_input(item, out_dir) for item in refs]


def pick_enabled(manager_getter, prefer: str = "") -> str:
    """挑选已启用接口：显式指定优先，否则第一个已启用。"""
    prefer = (prefer or "").strip()
    if prefer:
        return prefer
    try:
        enabled = manager_getter().get_enabled()
    except Exception:  # noqa: BLE001
        enabled = []
    if not enabled:
        raise RuntimeError("没有已启用的能力接口，请先在「设置 → 其他能力接口」中配置")
    return enabled[0]["id"]


def resolve_capability(kind: str, prefix: str) -> tuple[str, str]:
    """读取 config.yaml 里按模式配置的画布默认「接口 + 模型」。

    键格式（画布设置弹窗写入）：
        {kind}.{prefix}_interface      模式专属接口，如 imagegen.t2i_interface
        {kind}.default_{prefix}_model  模式专属模型，如 videogen.default_t2v_model
    兼容旧键：{kind}.method 作为接口的兜底回退。
    返回 (interface, model)，均可为空串（由调用方再回退到首个已启用接口/引擎默认）。
    """
    try:
        from backend.config.config_manager import config as app_config

        sub = app_config.get(kind) or {}
        iface = str(sub.get(f"{prefix}_interface") or sub.get("method") or "")
        model = str(sub.get(f"default_{prefix}_model") or "")
        return iface, model
    except Exception:  # noqa: BLE001
        return "", ""


# ------------------------------------------------------------------ #
# 任务台账（对齐源 withTaskRecord / o_tasks）
# ------------------------------------------------------------------ #
@contextmanager
def task_record(name: str, type_: str, project_id: int | None = None):
    """包装一次 AI 调用，写 tf_tasks 台账；台账异常不影响主流程。"""
    from backend.control_plane.database import session_scope
    from backend.toonflow.core.models import TfTask

    start = int(time.time() * 1000)
    task_id = None
    try:
        with session_scope() as session:
            row = TfTask(name=name, type=type_, state="生成中", projectId=project_id, startTime=start)
            session.add(row)
            session.flush()
            task_id = row.id
    except Exception:  # noqa: BLE001
        pass
    try:
        yield task_id
    except Exception as exc:
        try:
            with session_scope() as session:
                row = session.get(TfTask, task_id)
                if row:
                    row.state = "生成失败"
                    row.remark = str(exc)[:2000]
                    row.endTime = int(time.time() * 1000)
        except Exception:  # noqa: BLE001
            pass
        raise
    else:
        try:
            with session_scope() as session:
                row = session.get(TfTask, task_id)
                if row:
                    row.state = "已完成"
                    row.endTime = int(time.time() * 1000)
        except Exception:  # noqa: BLE001
            pass

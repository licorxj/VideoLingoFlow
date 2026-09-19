"""opencode CLI 集成接口。

提供「列出可用模型」能力，供节点设置面板的「加载模型」按钮使用：
既把模型列表回填为下拉选择项，也顺带完成一次连通性自检
（能列出模型 = CLI 可执行、配置可读、模型注册表可用）。
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, Query

from backend.steps.s_opencode_agent import resolve_opencode_exe

router = APIRouter()

# opencode models 需读取本地配置与插件，首次可能偏慢；给足超时但不无限等待
_LIST_TIMEOUT = 90

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


@router.get("/models")
def list_models(exe: str = Query("", description="可选：覆盖 opencode 可执行文件路径")):
    """执行 ``opencode models``，返回可用模型 id 列表（``provider/model``）。

    返回体：``{ok, exe, models, elapsed, error}``。失败不抛 5xx，而是以
    ``ok=false`` + ``error`` 回传，便于前端在设置面板内直接展示原因。
    """
    started = time.monotonic()

    def _fail(executable: str, message: str) -> dict:
        return {
            "ok": False,
            "exe": executable,
            "models": [],
            "elapsed": round(time.monotonic() - started, 2),
            "error": message,
        }

    exe = (exe or "").strip()
    if exe and not Path(exe).is_file():
        # 显式配置了路径时不做静默回退：连通性自检要能直接暴露「路径写错了」
        return _fail(exe, f"配置的 opencode 路径不存在：{exe}")
    try:
        resolved = resolve_opencode_exe({"opencode_exe": exe})
    except RuntimeError as exc:
        return _fail("", str(exc))

    try:
        proc = subprocess.run(
            [resolved, "models"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_LIST_TIMEOUT,
            stdin=subprocess.DEVNULL,
            env={**os.environ, "NO_COLOR": "1"},
        )
    except subprocess.TimeoutExpired:
        return _fail(resolved, f"执行 opencode models 超时（>{_LIST_TIMEOUT}s）")
    except OSError as exc:
        return _fail(resolved, f"无法执行 opencode：{exc}")

    elapsed = round(time.monotonic() - started, 2)
    models = []
    for line in (proc.stdout or "").splitlines():
        name = _ANSI_RE.sub("", line).strip()
        # 只保留 provider/model 形态的条目，滤掉日志与空行
        if name and "/" in name and " " not in name:
            models.append(name)

    if not models:
        tail = ((proc.stderr or "") or (proc.stdout or "")).strip()[-400:]
        detail = f"opencode models 退出码 {proc.returncode}" if proc.returncode else "未解析到任何模型条目"
        return _fail(resolved, f"{detail}：{tail}" if tail else detail)

    return {
        "ok": True,
        "exe": resolved,
        "models": models,
        "elapsed": elapsed,
        "error": "",
    }

"""opencode / mimo CLI 集成接口。

提供「列出可用模型」能力，供节点设置面板的「加载模型」按钮使用：
既把模型列表回填为下拉选择项，也顺带完成一次连通性自检
（能列出模型 = CLI 可执行、配置可读、模型注册表可用）。

mimo（@mimo-ai/cli）与 opencode 同源，但 `models` 输出会在模型名后附加
" — window 1M, compacts at 900K" 之类的后缀，故这里统一按行首的
provider/model token 提取，兼容两种输出格式。
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, Query

from backend.steps.s_opencode_agent import cli_spec, normalize_cli, resolve_agent_exe, subprocess_env

router = APIRouter()

# CLI 需读取本地配置与插件，首次可能偏慢；给足超时但不无限等待
_LIST_TIMEOUT = 90

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# 行首的 provider/model（mimo 会在其后附 " — window ..."，只取前半段；
# 用 [^\s/]+ 限定 provider 段，避免把日志行误判为模型条目）
_MODEL_LINE_RE = re.compile(r"^([^\s/]+/\S+)")


@router.get("/models")
def list_models(
    exe: str = Query("", description="可选：覆盖当前 CLI 的可执行文件路径"),
    cli: str = Query("opencode", description="CLI 类型：opencode / mimo"),
):
    """执行 ``<cli> models``，返回可用模型 id 列表（``provider/model``）。

    返回体：``{ok, cli, exe, models, elapsed, error}``。失败不抛 5xx，而是以
    ``ok=false`` + ``error`` 回传，便于前端在设置面板内直接展示原因。
    """
    started = time.monotonic()
    kind = normalize_cli({"cli": cli})

    def _fail(executable: str, message: str) -> dict:
        return {
            "ok": False,
            "cli": kind,
            "exe": executable,
            "models": [],
            "elapsed": round(time.monotonic() - started, 2),
            "error": message,
        }

    exe = (exe or "").strip()
    if exe and not Path(exe).is_file():
        # 显式配置了路径时不做静默回退：连通性自检要能直接暴露「路径写错了」
        return _fail(exe, f"配置的 {kind} 路径不存在：{exe}")
    _spec = cli_spec({"cli": kind})
    if not _spec.get("list_models", True):
        # Claude Code / Codex 没有 models 子命令，只能手工填写模型名
        hint = f"（{_spec['model_hint']}）" if _spec.get("model_hint") else ""
        return _fail("", f"{kind} 不提供 models 命令，请在模型框直接填写模型名{hint}")
    try:
        resolved = resolve_agent_exe({"cli": kind, "cli_path": exe})
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
            env=subprocess_env(),
        )
    except subprocess.TimeoutExpired:
        return _fail(resolved, f"执行 {kind} models 超时（>{_LIST_TIMEOUT}s）")
    except OSError as exc:
        return _fail(resolved, f"无法执行 {kind}：{exc}")

    elapsed = round(time.monotonic() - started, 2)
    models: list = []
    seen: set = set()
    for line in (proc.stdout or "").splitlines():
        name = _ANSI_RE.sub("", line).strip()
        match = _MODEL_LINE_RE.match(name)
        if not match:
            continue
        model = match.group(1)
        if model not in seen:
            seen.add(model)
            models.append(model)

    if not models:
        tail = ((proc.stderr or "") or (proc.stdout or "")).strip()[-400:]
        detail = f"{kind} models 退出码 {proc.returncode}" if proc.returncode else "未解析到任何模型条目"
        return _fail(resolved, f"{detail}：{tail}" if tail else detail)

    return {
        "ok": True,
        "cli": kind,
        "exe": resolved,
        "models": models,
        "elapsed": elapsed,
        "error": "",
    }

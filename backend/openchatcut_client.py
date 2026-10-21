"""OpenChatCut（AI剪辑台）命令行封装 —— 主项目节点无头调用剪辑台能力。

为什么用官方 ``occ`` CLI 而不是 MCP：
- ``occ`` 同源复用 OpenChatCut 的离线工具集（39 个 server-direct 工具），并补上
  MCP 离线模式下被拒的两项关键能力：**无头出片（render）** 与 **剪映草稿导出**；
- 不需要 MCP 会话 / bearer token / SSE 解析，也不受 45s wait、180s 调用上限约束；
- 默认 dry-run，``--apply`` 才原子提交（revision 校验 + 提交前版本快照，可回滚）；
- ``--json`` 输出 + 退出码 0/1/2，适合 Celery 无人值守场景。

运转前提（缺一不可，``available()`` 会逐项检查）：
  ``thirdparty/openchatcut`` 已部署 → 已 npm install（node_modules）→ 有 node → 有 tsx
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.config.desk_i18n import PARAM_ZH, TOOL_ZH

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OCC_DIR = PROJECT_ROOT / "thirdparty" / "openchatcut"
CLI_ENTRY = "cli/main.ts"
TSX_CLI = OCC_DIR / "node_modules" / "tsx" / "dist" / "cli.mjs"

DEFAULT_TIMEOUT = 1800  # 30 分钟；渲染长片时可经节点配置覆盖


class OpenChatCutUnavailable(RuntimeError):
    """剪辑台 CLI 不可用（未部署 / 未安装依赖 / 缺 node）。"""


@dataclass
class OccResult:
    """一次 occ 调用的结果。"""

    ok: bool
    returncode: int
    stdout: str
    stderr: str
    command: list[str] = field(default_factory=list)
    data: Any | None = None

    @property
    def message(self) -> str:
        """给节点/前端看的简短结论：优先取 JSON 里的 message，其次首尾 stderr/stdout。"""
        if isinstance(self.data, dict):
            for key in ("message", "error", "reason"):
                value = self.data.get(key)
                if value:
                    return str(value)
        tail = (self.stderr or "").strip() or (self.stdout or "").strip()
        if not tail:
            return ""
        lines = [line for line in tail.splitlines() if line.strip()]
        return lines[-1][:400]

    def tail(self, limit: int = 20) -> str:
        text = (self.stderr or "").strip() or (self.stdout or "").strip()
        lines = [line for line in text.splitlines() if line.strip()]
        return "\n".join(lines[-limit:])


def _node_exe() -> str | None:
    return shutil.which("node.exe") or shutil.which("node")


def available() -> tuple[bool, str]:
    """检查 occ CLI 是否可调用；返回 (可用?, 不可用原因)。"""
    if not OCC_DIR.is_dir():
        return False, f"剪辑台项目未部署：{OCC_DIR} 不存在"
    if not (OCC_DIR / "node_modules").is_dir():
        return False, "剪辑台依赖未安装，请先在「AI 剪辑台」页面点击「安装依赖」"
    if not (OCC_DIR / CLI_ENTRY).is_file():
        return False, f"缺少 CLI 入口：{OCC_DIR / CLI_ENTRY}"
    if not TSX_CLI.is_file():
        return False, f"缺少 tsx 运行时：{TSX_CLI}"
    node = _node_exe()
    if not node:
        return False, "未找到 node（OpenChatCut 需要 Node.js 24.x）"
    return True, ""


def run_occ(
    subargs: list[str],
    *,
    project: str = "",
    data_dir: str = "",
    apply: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
) -> OccResult:
    """执行一次 occ 子命令。

    :param subargs: 子命令与参数，如 ``["project", "list"]`` / ``["render", "--out", path]``
    :param project: 剪辑台项目 id（等价 ``--project``）
    :param data_dir: OpenChatCut 数据目录（留空用其默认位置）
    :param apply: 是否加 ``--apply`` 真正写入（不加则 dry-run）
    """
    ok, reason = available()
    if not ok:
        raise OpenChatCutUnavailable(reason)

    node = _node_exe() or "node"
    cmd: list[str] = [node, str(TSX_CLI), CLI_ENTRY]
    # 全局选项必须在子命令之前
    if project:
        cmd += ["--project", str(project)]
    if data_dir:
        cmd += ["--data-dir", str(data_dir)]
    cmd += [str(a) for a in subargs]
    if apply:
        cmd.append("--apply")
    cmd.append("--json")

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(OCC_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return OccResult(False, -1, "", f"occ 调用超时（>{timeout}s）：{' '.join(subargs[:3])}", cmd)
    except OSError as exc:
        return OccResult(False, -1, "", f"occ 调用失败: {exc}", cmd)

    data: Any | None = None
    raw = (proc.stdout or "").strip()
    if raw:
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            # 非 JSON 输出（提示/警告混排）时取最后一个 JSON 块
            for chunk in reversed(raw.splitlines()):
                chunk = chunk.strip()
                if chunk.startswith("{"):
                    try:
                        data = json.loads(chunk)
                        break
                    except (ValueError, TypeError):
                        continue
    return OccResult(proc.returncode == 0, proc.returncode, proc.stdout or "", proc.stderr or "", cmd, data)


def list_projects(data_dir: str = "") -> OccResult:
    """列出剪辑台项目（``occ project list``）。"""
    return run_occ(["project", "list"], data_dir=data_dir)


def create_project(
    name: str,
    *,
    size: str = "",
    fps: str = "",
    data_dir: str = "",
    timeout: int = 120,
) -> OccResult:
    """新建剪辑台工程（``occ project new <name> [--size WxH] [--fps N]``）。

    返回 ``{id, name, updatedAt}``；``id`` 即后续所有节点串联用的 project 标记。
    """
    args = ["project", "new", str(name)]
    if size:
        args += ["--size", str(size)]
    if fps:
        args += ["--fps", str(fps)]
    return run_occ(args, data_dir=data_dir, timeout=timeout)


def tool_schemas(headless_only: bool = True, data_dir: str = "") -> dict:
    """读取 headless 工具的参数 schema（供前端 ops 可视化编辑器动态生成表单）。

    数据源：上游已提交的权威目录 ``assets/agent/openchatcut-tool-schemas.json``，
    与 ``occ tools ls`` 的 headless 标记取交集，保证「看得见就能调」。
    """
    catalog = OCC_DIR / "assets" / "agent" / "openchatcut-tool-schemas.json"
    if not catalog.is_file():
        return {"available": False, "reason": f"工具目录缺失: {catalog}", "tools": []}

    names: set[str] | None = None
    if headless_only:
        listing = list_tools(headless_only=True, data_dir=data_dir)
        if listing.ok and isinstance(listing.data, list):
            names = {str(t.get("name")) for t in listing.data if t.get("name")}
        if not names:
            return {"available": False, "reason": "无法读取 occ 工具清单", "tools": []}

    try:
        data = json.loads(catalog.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"available": False, "reason": f"工具目录解析失败: {exc}", "tools": []}

    tools: list[dict] = []
    seen: set[str] = set()
    for group in ("edit", "ask"):
        for tool in data.get(group) or []:
            name = tool.get("name")
            if not name or name in seen or (names is not None and name not in names):
                continue
            seen.add(name)
            schema = tool.get("input_schema") or tool.get("inputSchema") or {}
            props = schema.get("properties") or {}
            params = []
            for key, spec in props.items():
                if not isinstance(spec, dict):
                    continue
                params.append(
                    {
                        "name": key,
                        "type": spec.get("type") or "string",
                        "enum": spec.get("enum"),
                        "description": (spec.get("description") or "")[:120],
                        "required": key in (schema.get("required") or []),
                        # 中文显示名（无收录时前端回退英文）
                        "label": PARAM_ZH.get(name, {}).get(key) or key,
                    }
                )
            zh = TOOL_ZH.get(name) or {}
            tools.append(
                {
                    "name": name,
                    "label": zh.get("label") or name,
                    "description": zh.get("desc") or (tool.get("description") or "").strip().split("\n")[0][:200],
                    "params": params,
                }
            )
    tools.sort(key=lambda t: t["name"])
    return {"available": True, "reason": "", "tools": tools}


def list_tools(headless_only: bool = False, data_dir: str = "") -> OccResult:
    """列出剪辑台可用工具（``occ tools ls``，``--all`` 含需浏览器的）。"""
    args = ["tools", "ls"]
    if not headless_only:
        args.append("--all")
    return run_occ(args, data_dir=data_dir)


def call_tool(
    tool: str,
    args: dict | None = None,
    *,
    project: str = "",
    data_dir: str = "",
    apply: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
) -> OccResult:
    """调用单个剪辑台工具（``occ tools call <tool> --args '<json>'``）。

    dry-run（``apply=False``）时不加 ``--apply``，工具只做校验/预览。
    """
    cmd_args = ["tools", "call", str(tool), "--args", json.dumps(args or {}, ensure_ascii=False)]
    return run_occ(cmd_args, project=project, data_dir=data_dir, apply=apply, timeout=timeout)


# --------------------------------------------------------------------------- #
# ops 编排：把多个工具调用串成一次批量执行（供「AI剪辑链」节点使用）
# --------------------------------------------------------------------------- #

_PLACEHOLDER = re.compile(r"\{\{\s*(input|prev)((?:\.\w+)*)\s*\}\}")


def _resolve_path(source, path: str):
    """按 ``a.b.0.c`` 形式从 dict/list 里取值。"""
    current = source
    for part in [p for p in path.split(".") if p]:
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return current


def substitute(value, inputs: dict, previous):
    """替换 ops 参数里的占位符：

    - ``{{input.path}}`` → 节点输入（如 ``{{input.asset_ids}}``）
    - ``{{prev.path}}``   → 上一个 op 的结果（如 ``{{prev.assetIds}}``）

    整个字符串就是一个占位符时保留原类型（数组/对象），否则做字符串内嵌。
    """
    if isinstance(value, str):
        match = _PLACEHOLDER.fullmatch(value.strip())
        if match:
            source = inputs if match.group(1) == "input" else previous
            return _resolve_path(source, match.group(2))
        def _repl(m):
            source = inputs if m.group(1) == "input" else previous
            resolved = _resolve_path(source, m.group(2))
            return "" if resolved is None else (
                json.dumps(resolved, ensure_ascii=False) if isinstance(resolved, (dict, list)) else str(resolved)
            )
        return _PLACEHOLDER.sub(_repl, value)
    if isinstance(value, list):
        return [substitute(item, inputs, previous) for item in value]
    if isinstance(value, dict):
        return {k: substitute(v, inputs, previous) for k, v in value.items()}
    return value


def run_ops(
    ops: list[dict],
    *,
    project: str = "",
    data_dir: str = "",
    apply: bool = False,
    inputs: dict | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> list[dict]:
    """顺序执行 ops；任一失败即中止（除非该 op 声明 ``continue_on_error``）。

    返回每步 ``{"tool","ok","result","message"}``，最后一步结果可作为下一步的
    ``{{prev}}`` 来源，实现节点内多工具串联。
    """
    steps: list[dict] = []
    previous = None
    for index, op in enumerate(ops or []):
        tool = str(op.get("tool") or "").strip()
        if not tool:
            steps.append({"tool": "", "ok": False, "result": None, "message": f"第 {index + 1} 个 op 缺少 tool"})
            break
        raw_args = op.get("args") or {}
        args = substitute(raw_args, inputs or {}, previous)
        if not isinstance(args, dict):
            args = {"value": args}
        result = call_tool(
            tool,
            args,
            project=project,
            data_dir=data_dir,
            apply=apply,
            timeout=timeout,
        )
        previous = result.data if result.ok else previous
        steps.append(
            {
                "tool": tool,
                "ok": result.ok,
                "result": result.data,
                "message": result.message,
            }
        )
        if not result.ok and not op.get("continue_on_error"):
            break
    return steps


def render(
    project: str,
    out_path: str,
    *,
    resolution: str = "",
    fps: str = "",
    codec: str = "",
    from_second: str = "",
    to_second: str = "",
    apply: bool = False,
    data_dir: str = "",
    timeout: int = DEFAULT_TIMEOUT,
) -> OccResult:
    """无头出片：``occ render --out <file>``。

    dry-run（``apply=False``）时附加 ``--dry-run``，只输出渲染计划不落盘。
    """
    args: list[str] = ["render", "--out", str(out_path)]
    if resolution:
        args += ["--resolution", str(resolution)]
    if fps:
        args += ["--fps", str(fps)]
    if codec:
        args += ["--codec", str(codec)]
    if from_second:
        args += ["--from", str(from_second)]
    if to_second:
        args += ["--to", str(to_second)]
    if not apply:
        args.append("--dry-run")
    return run_occ(args, project=project, data_dir=data_dir, apply=apply, timeout=timeout)


def export_jianying(
    project: str,
    out_dir: str,
    *,
    draft_name: str = "",
    apply: bool = False,
    data_dir: str = "",
    timeout: int = DEFAULT_TIMEOUT,
) -> OccResult:
    """导出剪映/CapCut 草稿：``occ export jianying --out-dir <dir>``。"""
    args: list[str] = ["export", "jianying", "--out-dir", str(out_dir)]
    if draft_name:
        args += ["--draft-name", str(draft_name)]
    return run_occ(args, project=project, data_dir=data_dir, apply=apply, timeout=timeout)

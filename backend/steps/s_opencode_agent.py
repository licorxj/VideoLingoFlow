"""s_opencode_agent: 本地 CLI 智能体工作流节点（opencode / mimo / Claude Code / Codex）。

把本机已安装的 CLI 智能体以工作流节点的方式嵌入执行链路；各 CLI 的命令形态与
事件协议差异集中声明在 CLI_SPECS 中，并分别由对应的事件解析分支处理：

- 组装任务指令（节点指令 + 任务背景 + 输入端口数据 + 输出产物契约）
- 按 CLI 规格非交互执行一次任务（opencode/mimo 为 ``run <prompt> --format json``，
  Claude Code 为 ``-p``，Codex 为 ``exec --json``）；工作目录由子进程 cwd 指定，
  命令行会按 CLI 版本实际支持的 flag 裁剪（见 ``_cli_help_flags``）
- 逐行解析 stdout 的 JSON 事件流（各协议见 ``_event_updates`` 的分布分支）：
    * 文本块   → 汇总为最终回答
    * 工具调用 → 映射为进度
    * 阶段/回合事件 → 阶段进度
    * 错误事件 → 归集为失败原因
  终止条件：CLI 在会话结束后自行退出。
- 以约定结束标识 ``[OC_TASK_DONE]`` 验收；命中则按验收 JSON 收拢产物到 cache/，
  未命中则退化为「取最终文本作 text 输出」的尽力而为模式（不因协议不遵守而失败）。

节点设置里的「自动放行工具权限」默认开启：CLI 在非交互模式下对未预授权的工具
权限请求会**自动拒绝**，不开则智能体基本无法读写文件、跑命令（flag 名随 CLI 而变）。
"""
import functools
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from backend.steps.base_step import BaseStep

# 约定的任务结束标识：agent 最终回复须包含该标记，后跟验收 JSON
DONE_MARKER = "[OC_TASK_DONE]"


class _ModelAttemptError(RuntimeError):
    """单次模型尝试的传输/权限级失败（如未授权、无支付方式、全程无输出超时）。

    这类失败可通过切换兜底模型重试；与「智能体自报任务失败」区分开：
    后者说明模型工作正常、只是任务本身失败，不应触发模型回退。
    """

# 输出文件类型 -> 默认扩展名（text 为字符串直接输出）
OUTPUT_TYPE_EXT = {
    "text": "",
    "txt": ".txt",
    "json": ".json",
    "subtitle": ".srt",
    "image": ".png",
    "audio": ".mp3",
    "video": ".mp4",
}

# 单次 CLI 会话默认超时（秒）
DEFAULT_TIMEOUT = 1800

# 提示词超过该长度时改为落盘引用，规避 Windows 命令行长度上限
PROMPT_INLINE_LIMIT = 20000

# 失败诊断时保留的非 JSON 输出行数上限（避免刷屏）
RAW_OUTPUT_LIMIT = 20


def _safe_output_path(task_dir: str, relative: str) -> Path:
    """将 agent 报告的相对路径解析为任务目录内绝对路径，防止路径穿越。"""
    root = Path(task_dir).resolve()
    candidate = Path(relative)
    resolved = candidate if candidate.is_absolute() else (root / candidate).resolve()
    if root not in resolved.parents and resolved != root:
        raise ValueError(f"Agent output escapes task directory: {relative}")
    return resolved


# stderr / 事件里可能带 ANSI 色码，报错前先剥掉
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# 额度 / 限流类错误的关键词：命中时给出可操作提示
_LIMIT_HINTS = (
    "429", "rate limit", "ratelimit", "too many requests", "daily free limit",
    "inference_cap_error", "quota",
)
_LIMIT_TIP = "（提示：该模型的免费额度或限流已用尽，可更换模型、配置兜底模型，或稍后重试）"


def _strip_ansi(text: str) -> str:
    """去掉 ANSI 色码，便于把 CLI 输出直接写进错误信息。"""
    return _ANSI_RE.sub("", str(text or ""))


def _oneline(text: Any) -> str:
    """折叠为单行：按行汇总的失败信息只取首行，多行内容会被截断丢失。"""
    return " ".join(str(text or "").split())


def _classify_error(raw: Any) -> str:
    """把 CLI 的错误载荷转成可读文案。

    各 CLI 会把结构化错误塞进文本字段（如 Cline 的
    ``{"error":{"code":"...","message":"..."}}``），直接展示会是难读的 JSON，
    这里统一抽取出 ``message (CODE)``；无法解析时按原文（剥色码）返回。
    """
    text = _oneline(_strip_ansi(raw))
    if not text:
        return ""
    payload = None
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
    if isinstance(payload, dict):
        err = payload.get("error")
        code = ""
        if isinstance(err, dict):
            code = str(err.get("code") or err.get("name") or "")
            message = str(err.get("message") or "")
        elif isinstance(err, str):
            message = err
        else:
            message = str(payload.get("message") or payload.get("reason") or "")
        if message:
            return f"{message}（{code}）" if code else message
        if code:
            return code
    return text


# ---------------------------------------------------------------------------
# CLI 规格表：节点可在 opencode / mimo / claude / codex 四种 CLI 间切换。
#
# opencode 与 mimo（@mimo-ai/cli，即 "mimocode"）同源：
#   run <message> --format json [-m provider/model] [--agent] [--thinking]
#       [--dir <dir>] [--variant <v>] [--pure]  # 后三者仅旧版本支持
#   事件流同构（step_start / text / tool_use / step_finish / error），仅
#   「自动放行权限」flag 名与 `models` 输出格式不同（后者在 API 侧适配）。
#   注意：opencode v2 起移除了 --dir / --variant / --pure，variant 改为写入模型名
#   （provider/model#variant），工作目录则由子进程 cwd 决定；这些差异在运行时按
#   `_cli_help_flags` 的探测结果自动适配，故规格表里仍保留旧写法。
#
# Claude Code（protocol="claude"）：
#   claude -p <message> --output-format stream-json --verbose
#       [--model] [--agent] [--dangerously-skip-permissions]
#   无 run 子命令、不支持目录参数（改用进程 cwd）、无 -m/--variant/--thinking/
#   --pure，也没有 `models` 子命令；事件流为 system / assistant / user /
#   result，最终文本与失败判定取自 result 事件——注意其 subtype 可能是
#   "success" 但 is_error=true，必须看 is_error 字段。
#
# Codex（protocol="codex"）：
#   codex exec <message> --json -C <dir> [-m model] --skip-git-repo-check
#       [-o <last_message_file>] [--dangerously-bypass-approvals-and-sandbox]
#   用 exec 子命令，目录用 -C，权限放行需 bypass flag；任务目录通常不是 git
#   仓库，故始终带 --skip-git-repo-check。事件流为 thread.started /
#   turn.started / item.started|updated|completed / turn.completed /
#   turn.failed / error；无 models 子命令。事件项名可能随版本变化，因此除
#   宽松解析外，还用 -o 落盘「最后一条消息」作为协议无关的最终文本兜底。
# ---------------------------------------------------------------------------
CLI_SPECS: dict = {
    "opencode": {
        "label": "opencode",
        "protocol": "opencode",
        "run_style": "run",
        "json_output_args": ("--format", "json"),
        # 注意：opencode v2 起移除了 --dir（改用进程 cwd）、--variant
        # （改为 provider/model#variant）与 --pure；这里保留旧写法供老版本使用，
        # 运行时会按 ``_cli_help_flags`` 探测结果自动裁剪不支持的 flag。
        "dir_flag": "--dir",
        "variant_sep": "#",
        "model_flag": "-m",
        "supports": ("variant", "thinking", "pure"),
        "list_models": True,
        "path_keys": ("cli_path", "opencode_exe"),
        "envs": ("OPENCODE_EXE",),
        "commands": ("opencode",),
        "auto_flag": "--auto",
        "extra_paths": (
            (".cherrystudio", "bin", "opencode.exe"),
            (".cherrystudio", "install", "global", "node_modules",
             "opencode-ai", "bin", "opencode.exe"),
        ),
    },
    "mimo": {
        "label": "mimo",
        "protocol": "opencode",
        "run_style": "run",
        "json_output_args": ("--format", "json"),
        "dir_flag": "--dir",
        "model_flag": "-m",
        "supports": ("variant", "thinking", "pure"),
        "list_models": True,
        "path_keys": ("cli_path", "mimo_exe"),
        "envs": ("MIMO_EXE",),
        "commands": ("mimo",),
        "auto_flag": "--dangerously-skip-permissions",
        "extra_paths": (),
    },
    "claude": {
        "label": "claude",
        "protocol": "claude",
        "run_style": "print",
        "json_output_args": ("--output-format", "stream-json", "--verbose"),
        "dir_flag": None,
        "model_flag": "--model",
        "supports": (),
        "list_models": False,
        "model_hint": "如 sonnet / opus",
        # 注意：cherrystudio 自带的 claude.exe 可能已损坏（bun 报错），故不做安装位置回退
        "path_keys": ("cli_path", "claude_exe"),
        "envs": ("CLAUDE_EXE",),
        "commands": ("claude",),
        "auto_flag": "--dangerously-skip-permissions",
        "extra_paths": (),
    },
    "codex": {
        "label": "codex",
        "protocol": "codex",
        "run_style": "exec",
        "json_output_args": ("--json",),
        "dir_flag": "-C",
        "model_flag": "-m",
        "supports": (),
        "list_models": False,
        "model_hint": "如 gpt-5-codex / o3",
        # 任务目录通常不是 git 仓库，不加会被 codex 直接拒绝
        "always_args": ("--skip-git-repo-check",),
        "path_keys": ("cli_path", "codex_exe"),
        "envs": ("CODEX_EXE",),
        "commands": ("codex",),
        "auto_flag": "--dangerously-bypass-approvals-and-sandbox",
        "extra_paths": ((".cherrystudio", "bin", "codex.exe"),),
    },
    "cline": {
        "label": "cline",
        "protocol": "cline",
        "run_style": "plain",
        "json_output_args": ("--json",),
        # 注意：Cline 的 -c 是 --cwd（opencode 的 -c 是 --continue），按 CLI 区分
        "dir_flag": "-c",
        "model_flag": "-m",
        "supports": (),
        "list_models": False,
        "model_hint": "留空用 cline 默认模型",
        # Cline 默认即自动放行工具（--auto-approve 默认 true），故关闭时需显式传 false
        "auto_flag": "--auto-approve",
        "auto_value": "true",
        "auto_off_args": ("--auto-approve", "false"),
        "path_keys": ("cli_path", "cline_exe"),
        "envs": ("CLINE_EXE",),
        "commands": ("cline",),
        "extra_paths": (),
    },
}

DEFAULT_CLI = "opencode"

# 定位可执行文件时，最多用 --help 验证前几个候选（每个候选一次冷启动）
_EXE_PROBE_LIMIT = 4


def normalize_cli(config: Optional[dict] = None) -> str:
    """解析节点选择的 CLI 类型（opencode / mimo / claude / codex），未知值回退默认。"""
    value = str((config or {}).get("cli") or "").strip().lower()
    return value if value in CLI_SPECS else DEFAULT_CLI


def cli_spec(config: Optional[dict] = None) -> dict:
    """当前 CLI 的完整规格（命令组装、事件协议、能力开关）。"""
    return CLI_SPECS[normalize_cli(config)]


def cli_label(config: Optional[dict] = None) -> str:
    """当前 CLI 的展示名（用于进度与错误提示）。"""
    return cli_spec(config)["label"]


def auto_approve_flag(config: Optional[dict] = None) -> str:
    """当前 CLI 的「自动放行工具权限」flag（各 CLI 命名不同）。"""
    return cli_spec(config)["auto_flag"]


def _read_npmrc_prefix(path: Path) -> str:
    """读取 npmrc 中的 ``prefix=`` 配置（npm 全局包的安装目录）。"""
    try:
        if not path.is_file():
            return ""
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith(("#", ";")) or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip().lower() != "prefix":
                continue
            value = value.strip().strip('"').strip("'")
            if value.startswith("~"):
                value = str(Path.home() / value.lstrip("~/\\"))
            return value
    except OSError:
        return ""
    return ""


@functools.lru_cache(maxsize=1)
def _npm_global_dirs() -> tuple:
    """npm 全局 bin 目录候选（结果按进程缓存）。

    启动脚本会清空 PATH，故位置不能只靠 PATH 推断，按以下优先级收集：
    1. 启动脚本运行时记录的 ``NPM_GLOBAL_DIR``
    2. npmrc 的 ``prefix=``（纯文件读取，不依赖 npm 与 PATH）
    3. ``npm prefix -g``（优先用启动脚本记录的 NPM_CMD）
    4. 由 node 安装位置旁推的 ``node_global`` / ``node_modules``
    5. npm 默认全局目录 ``%APPDATA%\\npm``
    """
    dirs: list = []

    def _add(path: object) -> None:
        # 注意：Path("") 会规范化成 "."，必须先挡掉空值
        raw = str(path).strip()
        if not raw:
            return
        try:
            candidate = Path(raw)
        except (TypeError, ValueError):
            return
        if candidate.is_dir() and candidate not in dirs:
            dirs.append(candidate)

    # 1) 启动脚本清空 PATH 前探测并记录的位置
    _add(os.environ.get("NPM_GLOBAL_DIR"))

    # 2) npmrc 里的 prefix
    npmrc_paths = [Path.home() / ".npmrc"]
    appdata = os.environ.get("APPDATA")
    if appdata:
        npmrc_paths.append(Path(appdata) / "npm" / "etc" / "npmrc")
    for rc_path in npmrc_paths:
        _add(_read_npmrc_prefix(rc_path))

    # 3) npm 自报的全局前缀（优先用启动脚本记录的 npm 命令）
    npm = (os.environ.get("NPM_CMD") or "").strip() or shutil.which("npm")
    if npm:
        try:
            proc = subprocess.run(
                [npm, "prefix", "-g"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                stdin=subprocess.DEVNULL,
            )
            for line in reversed((proc.stdout or "").splitlines()):
                if line.strip():
                    _add(line.strip())
                    break
        except Exception:
            pass

    # 4) 由 node 安装位置旁推（node 目录同样优先用启动脚本记录的 NODE_DIR）
    node_dirs: list = []
    recorded_node_dir = (os.environ.get("NODE_DIR") or "").strip()
    if recorded_node_dir:
        node_dirs.append(Path(recorded_node_dir))
    node = shutil.which("node")
    if node:
        node_dirs.append(Path(node).parent)
    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(env_name)
        if root:
            node_dirs.append(Path(root) / "nodejs")
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        node_dirs.append(Path(local_appdata) / "Programs" / "nodejs")
    for node_dir in node_dirs:
        _add(node_dir / "node_global")
        _add(node_dir.parent / "node_global")
        _add(node_dir / "node_modules")

    # 5) npm 默认全局目录
    _add(Path.home() / "AppData" / "Roaming" / "npm")
    return tuple(dirs)


@functools.lru_cache(maxsize=1)
def _node_dirs() -> tuple:
    """node 可执行文件所在目录候选（供 .cmd 垫片补齐 PATH）。

    npm 生成的 ``.cmd`` 垫片内部会调用 ``node``（同目录没有 node.exe 时走 PATH），
    而后端进程的 PATH 未必包含 node，故需要显式补进子进程环境。
    位置来源：启动脚本记录的 ``NODE_DIR`` > PATH 里的 node > 由 npm 全局目录旁推。
    """
    dirs: list = []

    def _add_dir(path: Path) -> None:
        if (path / "node.exe").is_file() or (path / "node").is_file():
            text = str(path)
            if text not in dirs:
                dirs.append(text)

    # 启动脚本清空 PATH 前探测并记录的 node 目录
    recorded = (os.environ.get("NODE_DIR") or "").strip()
    if recorded:
        _add_dir(Path(recorded))

    node = shutil.which("node")
    if node:
        _add_dir(Path(node).parent)

    # 由 npm 全局目录旁推：常见布局为 <node 安装目录>/node_global
    for global_dir in _npm_global_dirs():
        parent = Path(global_dir).parent
        _add_dir(parent)
        _add_dir(parent.parent)
    return tuple(dirs)


def subprocess_env() -> dict:
    """CLI 子进程环境：去色，并把 node 目录补进 PATH（供 .cmd 垫片调用 node）。"""
    env = {**os.environ, "NO_COLOR": "1"}
    extra = [d for d in _node_dirs() if d]
    if extra:
        env["PATH"] = os.pathsep.join([*extra, env.get("PATH", "")])
    return env


# 各 run_style 调用 ``--help`` 的方式（用于探测 CLI 实际支持的 flag）
_HELP_ARGS = {
    "run": ("run", "--help"),
    "exec": ("exec", "--help"),
    "print": ("--help",),
    "plain": ("--help",),
}


@functools.lru_cache(maxsize=16)
def _cli_help_flags(exe: str, run_style: str) -> Optional[frozenset]:
    """探测某个可执行文件支持哪些 flag（结果按进程缓存）。

    第三方 CLI 升级会移除或改名 flag（如 opencode v2 移除了 ``--dir``、
    ``--variant``、``--pure``），而传入未知 flag 时 CLI 只会打印 usage 并以非
    0 退出——每个模型都会以同样的方式失败。故这里读一次 ``--help`` 输出、
    抽取其中的 flag 名作为白名单，由 ``_build_command`` 按需裁剪命令行。

    返回 ``None`` 表示无法判定（CLI 不可用或 --help 无输出），此时按规格表
    原样传参，保持既有行为。同一返回值也用于判断某个候选可执行文件是否真的
    可用（失效的垫片会在 --help 阶段就报错退出）。
    """
    try:
        proc = subprocess.run(
            [*exec_argv(exe), *_HELP_ARGS.get(run_style, ("--help",))],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            stdin=subprocess.DEVNULL,
            env=subprocess_env(),
        )
    except Exception:
        return None
    blob = "\n".join([proc.stdout or "", proc.stderr or ""])
    names = set(re.findall(r"--[a-zA-Z][\w-]*", blob))
    return frozenset(names) if names else None


def _flag_supported(flags: Optional[frozenset], flag: Optional[str]) -> bool:
    """flag 是否可用：无法判定时保守地认为可用（维持旧行为）。

    单字母短 flag（``-m`` / ``-C`` 等）不参与裁剪：help 里常以 ``--long, -x``
    的别名形式出现，难以稳定匹配，误裁的代价比多传更大。
    """
    if not flag:
        return False
    if not flag.startswith("--") or flags is None:
        return True
    return flag in flags


# npm 垫片里的真实入口路径形如 "%dp0%\node_modules\<pkg>\bin\<name>"
_NPM_SHIM_PATH_RE = re.compile(r'"?%dp0%\\([^"\s]+)"?')
# 垫片里会顺带提到这些名字，但它们不是 CLI 入口
_NON_TARGET_NAMES = frozenset({"node", "node.exe", "npm", "npm.cmd", "npx", "npx.cmd"})


def _node_exe(shim_dir: Path) -> str:
    """垫片所需的 node 可执行文件：垫片同目录 > NODE_DIR/PATH 推导 > PATH。"""
    for directory in (shim_dir, *(Path(d) for d in _node_dirs())):
        candidate = directory / "node.exe"
        if candidate.is_file():
            return str(candidate)
    return shutil.which("node") or ""


@functools.lru_cache(maxsize=16)
def _unwrap_npm_shim(exe: str) -> Optional[list]:
    """展开 npm 生成的 .cmd/.bat 垫片，返回可直接执行的命令前缀。

    Windows 下运行 .cmd/.bat 必须经由 cmd.exe，而 cmd 会自行解析命令行中的
    换行、``|``、``^``、``%`` 等字符（工作流节点的任务说明几乎必然包含 ``|``），
    参数一旦被破坏，CLI 就会表现为：输出退回交互式渲染、flag 丢失、乃至挂起
    等待根本不存在的输入。垫片内容形如：

    - ``"%dp0%\\node_modules\\@opencode\\cli\\bin\\opencode.exe" %*``（原生二进制）
    - ``"%_prog%" "%dp0%\\node_modules\\@mimo-ai\\cli\\bin\\mimo" %*``（node 脚本）

    据此还原真实入口：原生可执行文件直接调用，node 脚本补上 node 前缀。
    返回 None 表示无法展开（非垫片或目标缺失），调用方按原样使用。
    """
    path = Path(exe)
    if path.suffix.lower() not in (".cmd", ".bat") or not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    # 垫片真正的调用行是含 %* 的那行（其它行只是探测 node/dp0）
    lines = [ln for ln in text.splitlines() if "%*" in ln] or text.splitlines()
    target = ""
    for line in lines:
        for match in _NPM_SHIM_PATH_RE.finditer(line):
            relative = match.group(1)
            if not relative:
                continue
            candidate = path.parent / relative
            if candidate.is_file() and candidate.name.lower() not in _NON_TARGET_NAMES:
                target = str(candidate)
                break
        if target:
            break
    if not target:
        return None
    if Path(target).suffix.lower() in (".exe", ".com"):
        return [target]
    node = _node_exe(path.parent)
    return [node, target] if node else None


@functools.lru_cache(maxsize=16)
def exec_argv(exe: str) -> tuple:
    """CLI 的命令前缀：优先展开 npm 垫片，失败则原样使用可执行文件。"""
    unwrapped = _unwrap_npm_shim(exe)
    return tuple(unwrapped) if unwrapped else (exe,)


def _iter_cli_candidates(spec: dict, config: dict, home: Path) -> list:
    """候选可执行文件路径：设置 > 环境变量 > PATH > npm 全局目录 > 常见安装位置。"""
    candidates: list = []
    for key in spec["path_keys"]:
        candidates.append(str(config.get(key) or "").strip())
    for env_name in spec["envs"]:
        candidates.append(os.environ.get(env_name, "").strip())
    for command in spec["commands"]:
        candidates.append(shutil.which(command) or "")
        # PATH 里没有时，到 npm 全局目录里按「命令名 + 可执行后缀」再找一遍
        for directory in _npm_global_dirs():
            for suffix in (".cmd", ".exe", ".bat", ""):
                candidates.append(str(directory / f"{command}{suffix}"))
    for parts in spec["extra_paths"]:
        candidates.append(str(home.joinpath(*parts)))
    return candidates


def resolve_agent_exe(config: Optional[dict] = None) -> str:
    """定位当前 CLI 可执行文件：节点设置 > 环境变量 > PATH > npm 全局目录 > 常见安装位置。

    模块级函数，供节点步骤与 API（模型列表 / 连通性测试）共用。
    """
    config = config or {}
    spec = cli_spec(config)
    home = Path.home()
    existing = [
        item for item in _iter_cli_candidates(spec, config, home)
        if item and Path(item).is_file()
    ]
    # 同一命令名下可能并存多个版本（如重装后残留的旧垫片），有效性以能否响应
    # --help 为准；全部无法响应时退化为第一个存在的文件（保持旧行为）
    for candidate in existing[:_EXE_PROBE_LIMIT]:
        if _cli_help_flags(candidate, spec["run_style"]) is not None:
            return candidate
    if existing:
        return existing[0]

    tried = _npm_global_dirs()
    hint = f"（已尝试这些目录：{'、'.join(str(d) for d in tried[:2])}）" if tried else ""
    raise RuntimeError(
        f"未找到 {spec['label']} 可执行文件：请在节点设置中填写 CLI 路径，"
        f"或设置环境变量 {spec['envs'][0]}{hint}"
    )


def resolve_opencode_exe(config: Optional[dict] = None) -> str:
    """兼容入口：定位 opencode 可执行文件（等价于 resolve_agent_exe 指定 opencode）。"""
    merged = dict(config or {})
    merged["cli"] = "opencode"
    return resolve_agent_exe(merged)


class S_OpenCodeAgent(BaseStep):
    step_id = "opencode_agent"
    step_name = "本地CLI智能体"
    dependencies = []

    # ---------- BaseStep 契约 ----------

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        if not node_id:
            return False
        return (Path(task_dir) / "cache" / f"oc_agent_{node_id}_result.json").is_file()

    def validate_inputs(self, task_dir: str) -> bool:
        config = getattr(self, "_node_config", {}) or {}
        return bool(str(config.get("instruction", "")).strip())

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        config = getattr(self, "_node_config", {}) or {}
        inputs = getattr(self, "_step_inputs", {}) or {}
        node_id = getattr(self, "_node_id", "") or "node"
        instruction = str(config.get("instruction", "")).strip()
        if not instruction:
            raise ValueError("本地 CLI 智能体需要填写任务指令")

        task_dir_path = Path(task_dir).resolve()
        task_dir_path.mkdir(parents=True, exist_ok=True)
        cache_dir = task_dir_path / "cache"
        cache_dir.mkdir(exist_ok=True)

        def progress(percent: int, message: str) -> None:
            if callback:
                try:
                    callback(percent, message)
                except Exception:
                    pass

        # 工作目录：默认任务目录，可指定子目录（让智能体在隔离目录内作业）
        work_dir = task_dir_path
        dir_name = str(config.get("dir_name") or "").strip()
        if dir_name:
            work_dir = (task_dir_path / dir_name)
            work_dir.mkdir(parents=True, exist_ok=True)

        cli_name = cli_label(config)
        exe = self._resolve_exe(config)
        input_ports = {
            f"input_{i}": inputs.get(f"input_{i}", "")
            for i in range(1, int(config.get("inputCount", 2)) + 1)
        }
        output_items = self._normalize_output_items(config.get("output_items", []))
        recommended = self._collect_recommended_tools(config)
        prompt = self._build_prompt(
            instruction, task_dir_path, work_dir, input_ports, output_items, recommended,
        )

        # 模型回退链：主模型 + 兜底模型（顺序尝试，仅在模型/传输级失败时回退）
        attempts = self._attempt_models(config)
        events: Optional[dict] = None
        failures: list = []
        for index, model in enumerate(attempts, start=1):
            if cancel_callback and cancel_callback():
                raise RuntimeError("任务已取消")
            label = model or f"{cli_name} 默认模型"
            if index == 1:
                progress(5, f"正在启动 {cli_name} 会话（模型：{label}）")
            else:
                reason = failures[-1].split(":", 1)[-1].strip() if failures else ""
                progress(
                    5,
                    f"切换兜底模型 {index}/{len(attempts)}：{label}"
                    + (f"（上一模型失败：{reason[:60]}）" if reason else ""),
                )
            cmd = self._build_command(exe, config, work_dir, prompt, node_id, cache_dir, model)
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(work_dir),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=subprocess_env(),
                )
            except OSError as exc:
                raise RuntimeError(f"无法启动 {cli_name}（{exe}）：{exc}") from exc
            try:
                events = self._stream_events(proc, config, cancel_callback, progress, label)
                break
            except _ModelAttemptError as exc:
                # 折叠为单行：多行内容在按行汇总时会被截断
                failures.append(f"{label}: {_oneline(exc)[:400]}")
                continue

        if events is None:
            raise RuntimeError("所有模型尝试均失败：\n" + "\n".join(f"- {item}" for item in failures))

        aggregate = "\n\n".join(part.strip() for part in events["texts"] if part.strip())
        final_text = ""
        for part in reversed(events["texts"]):
            if part.strip():
                final_text = part.strip()
                break

        # Codex 兜底：-o 落盘的「最后一条消息」是最可靠的结果来源，
        # 事件项命名随版本变化时也不受影响
        if cli_spec(config)["protocol"] == "codex":
            last_message = ""
            try:
                last_message_path = self._last_message_path(cache_dir, node_id)
                if last_message_path.is_file():
                    last_message = last_message_path.read_text(
                        encoding="utf-8", errors="replace",
                    ).strip()
            except OSError:
                last_message = ""
            if last_message:
                final_text = last_message
                aggregate = f"{aggregate}\n\n{last_message}" if aggregate else last_message

        # 验收：优先整体文本，其次最终文本块
        result = self._parse_done_payload(aggregate) or self._parse_done_payload(final_text)

        if result is None:
            progress(92, "未检测到结束标识，按最终文本尽力收拢产物")
        else:
            progress(92, "正在收拢产物")

        outputs, artifacts = self._collect_outputs(
            task_dir_path, cache_dir, node_id, result, output_items, final_text,
        )

        # 始终落一份结果 JSON：既保证 check_artifact 可靠，也便于排查
        result_file = cache_dir / f"oc_agent_{node_id}_result.json"
        result_file.write_text(
            json.dumps(
                {
                    "status": str((result or {}).get("status") or ("success" if result else "unverified")),
                    "message": str((result or {}).get("message") or ""),
                    "text": final_text,
                    "outputs": outputs,
                    "tool_calls": events["tool_calls"],
                    "exit_code": events["returncode"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        artifacts.insert(0, f"cache/{result_file.name}")

        progress(100, f"{cli_name} 智能体完成")
        return {"artifacts": artifacts, "outputs": outputs}

    # ---------- 命令与进程 ----------

    def _build_command(self, exe: str, config: dict, work_dir: Path, prompt: str,
                       node_id: str, cache_dir: Path, model: str = "") -> list:
        """按当前 CLI 规格组装命令行（run 子命令 / -p 打印 / exec 三种形态）。"""
        spec = cli_spec(config)
        message = prompt
        if len(prompt) > PROMPT_INLINE_LIMIT:
            prompt_file = cache_dir / f"oc_agent_{node_id}_prompt.md"
            prompt_file.write_text(prompt, encoding="utf-8")
            message = (
                f"完整任务说明已写入文件：{prompt_file}\n"
                "请先读取该文件，并严格按其中的背景、输入与输出契约执行本次任务。"
            )

        run_style = spec["run_style"]
        # 绕过 cmd.exe：npm 垫片（.cmd）会被 cmd 重新解析命令行，吃掉 prompt 里的
        # 换行 / | / ^ / % 等字符，导致参数被破坏
        prefix = list(exec_argv(exe))
        # 按 CLI 实际支持的 flag 裁剪命令行：第三方 CLI 升级会移除 flag，
        # 传入未知 flag 会让每个模型都以退出码非 0 的同样方式失败
        supported = _cli_help_flags(exe, run_style)
        # Cline 需把 message 放到最后：实测输出类 flag 位于 prompt 之后时不生效
        message_last = run_style == "plain"
        if run_style == "run":
            cmd = [*prefix, "run", message, *spec["json_output_args"]]
        elif run_style == "exec":
            # Codex：codex exec <message> --json ...；-o 把最后一条消息写入文件，
            # 作为与事件协议无关的最终文本兜底
            always = [a for a in spec.get("always_args", ()) if _flag_supported(supported, a)]
            cmd = [*prefix, "exec", message, *spec["json_output_args"], *always]
            cmd += ["-o", str(S_OpenCodeAgent._last_message_path(cache_dir, node_id))]
        elif run_style == "print":
            # Claude Code：-p/--print 非交互，prompt 紧随其后
            cmd = [*prefix, "-p", message, *spec["json_output_args"]]
        else:
            # Cline：没有子命令，prompt 作为位置参数（最后追加）
            cmd = [*prefix, *spec["json_output_args"]]
        dir_flag = spec.get("dir_flag")
        if _flag_supported(supported, dir_flag):
            # CLI 不支持时由进程 cwd 承担工作目录（Popen 已设置 cwd=work_dir）
            cmd += [dir_flag, str(work_dir)]

        agent = str(config.get("agent") or "").strip()
        variant = str(config.get("variant") or "").strip()
        model_arg = model
        variant_args: list = []
        if variant and "variant" in spec["supports"]:
            if _flag_supported(supported, "--variant"):
                variant_args = ["--variant", variant]
            elif spec.get("variant_sep") and model_arg:
                # 新版 opencode：variant 并入模型名（provider/model#variant）
                model_arg = f"{model_arg}{spec['variant_sep']}{variant}"
        if model_arg:
            cmd += [spec["model_flag"], model_arg]
        if agent and _flag_supported(supported, "--agent"):
            cmd += ["--agent", agent]
        cmd += variant_args
        # 非交互模式下未预授权的工具权限会被自动拒绝，故默认自动放行
        # （flag 名/取值随 CLI 而变，见 CLI_SPECS.auto_flag / auto_value / auto_off_args）
        if config.get("auto_approve", True):
            if _flag_supported(supported, spec["auto_flag"]):
                cmd.append(spec["auto_flag"])
                auto_value = spec.get("auto_value")
                if auto_value:
                    cmd.append(auto_value)
        elif spec.get("auto_off_args"):
            # 某些 CLI 默认就放行（如 Cline），关闭时必须显式传 false
            cmd += list(spec["auto_off_args"])
        if config.get("thinking") and "thinking" in spec["supports"] \
                and _flag_supported(supported, "--thinking"):
            cmd.append("--thinking")
        if config.get("pure") and "pure" in spec["supports"] \
                and _flag_supported(supported, "--pure"):
            cmd.append("--pure")
        if message_last:
            cmd.append(message)
        return cmd

    @staticmethod
    def _last_message_path(cache_dir: Path, node_id: str) -> Path:
        """Codex ``-o/--output-last-message`` 的落盘路径（协议无关的结果兜底）。"""
        return cache_dir / f"oc_agent_{node_id}_last_message.md"

    def _stream_events(self, proc: subprocess.Popen, config: dict,
                       cancel_callback: Optional[Callable], progress: Callable,
                       model_label: str = "") -> dict:
        """读取 stdout 的 JSON 事件流，返回汇总结果；超时/取消则终止进程并抛错。

        模型/传输级失败抛 ``_ModelAttemptError``（可回退重试）；
        取消、以及「已产出内容但超时」抛 RuntimeError（不回退）。
        """
        line_queue: "queue.Queue[Optional[str]]" = queue.Queue()
        err_lines: list = []

        def pump_stdout():
            try:
                for line in proc.stdout:  # type: ignore[union-attr]
                    line_queue.put(line)
            except Exception:
                pass
            finally:
                try:
                    proc.stdout.close()  # type: ignore[union-attr]
                except Exception:
                    pass
                line_queue.put(None)

        def pump_stderr():
            try:
                for line in proc.stderr:  # type: ignore[union-attr]
                    err_lines.append(line)
            except Exception:
                pass
            finally:
                try:
                    proc.stderr.close()  # type: ignore[union-attr]
                except Exception:
                    pass

        t_out = threading.Thread(target=pump_stdout, daemon=True)
        t_err = threading.Thread(target=pump_stderr, daemon=True)
        t_out.start()
        t_err.start()

        spec = cli_spec(config)
        timeout = float(config.get("timeout") or DEFAULT_TIMEOUT)
        deadline = time.monotonic() + timeout
        texts: list = []
        errors: list = []
        counters = {"tool_calls": 0}
        # 非 JSON 输出行（usage / 报错文案等）：诊断失败原因的关键线索
        raw_output: list = []
        stream_done = False
        cancelled = False

        while True:
            if cancel_callback and cancel_callback():
                cancelled = True
                break
            if time.monotonic() > deadline:
                break
            try:
                line = line_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if line is None:
                stream_done = True
                break
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                # 非事件行：多为 CLI 的 usage / 参数错误提示（传了未知 flag 时会打到这里）
                if len(raw_output) < RAW_OUTPUT_LIMIT:
                    raw_output.append(line[:300])
                continue
            if not isinstance(event, dict):
                continue
            for percent, message_text in self._event_updates(
                spec["protocol"], event, texts, errors, counters,
            ):
                progress(percent, message_text)

        if not stream_done:
            self._terminate(proc)
            t_out.join(timeout=2)
            t_err.join(timeout=2)
            if cancelled:
                raise RuntimeError("任务已取消")
            if not texts and not counters["tool_calls"]:
                # 全程无任何输出即超时：判定为该模型不可用，允许回退到兜底模型
                raise _ModelAttemptError(f"模型 {model_label} 超时且无任何输出（>{int(timeout)}s）")
            raise RuntimeError(f"{cli_label(config)} 执行超时（>{int(timeout)}s）")

        try:
            returncode = proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self._terminate(proc)
            returncode = proc.wait(timeout=10)

        t_out.join(timeout=3)
        t_err.join(timeout=3)
        stderr_tail = _strip_ansi("".join(err_lines))[-800:].strip()
        stdout_tail = "\n".join(raw_output)[-600:].strip()
        # 部分 CLI（如 Cline）把可读原因只写在 stderr 的 error 事件里
        stderr_messages = self._stderr_messages(err_lines)
        # stderr 里的 JSON 事件已被结构化提取，这里只补非 JSON 的原始日志，避免重复
        stderr_plain = "\n".join(
            line for line in (_strip_ansi(raw).strip() for raw in err_lines)
            if line and not line.startswith("{")
        )[-600:].strip()
        extra = (f"\nstderr: {stderr_plain}" if stderr_plain else "") \
            + (f"\nstdout: {stdout_tail}" if stdout_tail else "")

        if returncode != 0 or errors:
            detail = "；".join(
                dict.fromkeys(m for m in [*errors, *stderr_messages[-1:]] if m)
            )[:600] or f"退出码 {returncode}"
            # CLI 打印 usage 通常意味着命令行参数不被该版本支持
            if stdout_tail and re.search(r"^\s*(USAGE|FLAGS)\b", stdout_tail, re.MULTILINE):
                detail = f"{detail}（命令行参数不被该版本支持，请检查 CLI 版本与节点设置）"
            elif any(h in detail.lower() for h in _LIMIT_HINTS):
                detail += _LIMIT_TIP
            raise _ModelAttemptError(f"模型 {model_label} 调用失败：{detail}{extra}")

        if not texts and not counters["tool_calls"]:
            # 进程正常退出但零产出：CLI 实际什么都没做（多为模型不可用、鉴权或网络问题）。
            # 判为本次尝试失败 → 触发兜底模型；全部失败则明确报错，
            # 避免出现「节点成功但产物为空」的假成功。
            raise _ModelAttemptError(
                f"模型 {model_label} 未产生任何输出（退出码 {returncode}）{extra}"
            )

        return {
            "texts": texts,
            "tool_calls": counters["tool_calls"],
            "returncode": returncode,
            "stderr_tail": stderr_tail,
        }

    @classmethod
    def _event_updates(cls, protocol: str, event: dict, texts: list, errors: list,
                       counters: dict) -> list:
        """把一条 CLI 事件映射为 [(进度百分比, 提示文案), ...]，就地累积文本/错误/工具数。

        - protocol="opencode"：opencode 与 mimo 的 ``run --format json`` 事件流
        - protocol="claude"：Claude Code 的 ``--output-format stream-json`` 事件流
        """
        if protocol == "claude":
            return cls._claude_event_updates(event, texts, errors, counters)
        if protocol == "codex":
            return cls._codex_event_updates(event, texts, errors, counters)
        if protocol == "cline":
            return cls._cline_event_updates(event, texts, errors, counters)

        updates: list = []
        etype = event.get("type")
        if etype == "text":
            part = event.get("part") or {}
            text = str(part.get("text") or "")
            if text.strip():
                texts.append(text)
                updates.append((min(85, 30 + len(texts) * 5), f"生成：{text.strip()[-50:]}"))
        elif etype == "tool_use":
            part = event.get("part") or {}
            counters["tool_calls"] += 1
            count = counters["tool_calls"]
            updates.append((min(80, 25 + count), f"调用工具：{part.get('tool') or 'tool'}"))
        elif etype == "step_start":
            updates.append((20, "智能体开始推理"))
        elif etype == "step_finish":
            updates.append((88, "本轮推理结束"))
        elif etype == "error":
            errors.append(cls._error_message(event))
            updates.append((90, f"错误：{errors[-1][:80]}"))
        return updates

    @classmethod
    def _claude_event_updates(cls, event: dict, texts: list, errors: list,
                              counters: dict) -> list:
        """Claude Code stream-json：system(init) / assistant / user / result。

        result 事件同时承载最终文本与成败判定；注意其 subtype 可能是
        ``success`` 但 ``is_error=true``（例如 API Key 无效），必须看 is_error。
        """
        updates: list = []
        etype = event.get("type")
        if etype == "system" and event.get("subtype") == "init":
            counters["model"] = str(event.get("model") or counters.get("model") or "")
            updates.append((20, f"智能体会话已就绪（模型：{counters['model'] or '默认'}）"))
        elif etype == "assistant":
            content = (event.get("message") or {}).get("content") or []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text = str(block.get("text") or "")
                    if text.strip():
                        texts.append(text)
                        updates.append((min(85, 30 + len(texts) * 5), f"生成：{text.strip()[-50:]}"))
                elif block.get("type") == "tool_use":
                    counters["tool_calls"] += 1
                    count = counters["tool_calls"]
                    updates.append((min(80, 25 + count), f"调用工具：{block.get('name') or 'tool'}"))
        elif etype == "result":
            text = str(event.get("result") or "").strip()
            failed = bool(event.get("is_error")) or str(event.get("subtype") or "").startswith("error")
            if failed:
                errors.append(text or f"会话失败（{event.get('subtype')}）")
                updates.append((90, f"错误：{errors[-1][:80]}"))
            elif text and text not in texts:
                texts.append(text)
                updates.append((88, "本轮推理结束"))
        elif etype == "error":
            errors.append(cls._error_message(event))
            updates.append((90, f"错误：{errors[-1][:80]}"))
        return updates

    @classmethod
    def _codex_event_updates(cls, event: dict, texts: list, errors: list,
                             counters: dict) -> list:
        """Codex ``exec --json`` 事件：thread.started / turn.started /
        item.started|updated|completed / turn.completed / turn.failed / error。

        事件项（item.type）命名可能随版本变化，故对 item 做宽松匹配：文本只
        认 agent_message（仅 completed 时收集，避免流式增量重复），带工具语义
        的项按工具调用计数；最终文本另有 ``-o`` 落盘兜底。
        """
        updates: list = []
        etype = str(event.get("type") or "")
        if etype == "thread.started":
            updates.append((15, "会话已建立"))
        elif etype == "turn.started":
            updates.append((20, "智能体开始推理"))
        elif etype in ("item.started", "item.updated", "item.completed"):
            item = event.get("item")
            if not isinstance(item, dict):
                return updates
            itype = str(item.get("type") or "")
            if itype == "reasoning":
                updates.append((24, "思考中…"))
            elif itype == "agent_message":
                text = str(item.get("text") or "")
                if etype == "item.completed" and text.strip() and text not in texts:
                    texts.append(text)
                    updates.append((min(85, 30 + len(texts) * 5), f"生成：{text.strip()[-50:]}"))
            elif itype == "error":
                message = str(item.get("message") or "会话错误")
                errors.append(message)
                updates.append((90, f"错误：{message[:80]}"))
            elif itype:
                counters["tool_calls"] += 1
                count = counters["tool_calls"]
                label = item.get("command") or item.get("query") or itype
                updates.append((min(80, 25 + count), f"调用工具：{str(label)[:40]}"))
        elif etype == "turn.completed":
            updates.append((88, "本轮推理结束"))
        elif etype == "turn.failed":
            err = event.get("error")
            message = err.get("message") if isinstance(err, dict) else str(err or "")
            errors.append(str(message or "会话失败"))
            updates.append((90, f"错误：{errors[-1][:80]}"))
        elif etype == "error":
            errors.append(str(event.get("message") or cls._error_message(event)))
            updates.append((90, f"错误：{errors[-1][:80]}"))
        return updates

    @classmethod
    def _cline_event_updates(cls, event: dict, texts: list, errors: list,
                             counters: dict) -> list:
        """Cline ``--json`` 事件：hook_event / agent_event / run_result。

        ``agent_event.event.type`` 取值：
        - ``iteration_start`` / ``iteration_end``（含 toolCallCount）→ 回合进度
        - ``content_start`` / ``content_end``（contentType: reasoning|text）→ 文本按段收集
        - ``usage`` → 忽略
        - ``done``（含完整 ``text`` 与 ``reason``）→ 最终文本 + 成败判定
        末行 ``run_result``（finishReason）作为收尾确认。
        """
        updates: list = []
        etype = str(event.get("type") or "")

        if etype == "hook_event":
            if str(event.get("hookEventName") or "") == "agent_start":
                updates.append((15, "会话已建立"))
            return updates

        if etype == "run_result":
            reason = str(event.get("finishReason") or "")
            model_info = event.get("model")
            if isinstance(model_info, dict):
                # 记录实际使用的模型，失败提示里能指明是哪个模型受限
                counters["model"] = str(model_info.get("id") or counters.get("model") or "")
            if reason and reason != "completed":
                if not errors:
                    # done 事件通常已给出具体原因，这里仅作兜底
                    errors.append(_classify_error(event.get("text")) or f"会话结束：{reason}")
                updates.append((88, "会话结束"))
            else:
                updates.append((88, "本轮推理结束"))
            return updates

        if etype != "agent_event":
            return updates
        inner = event.get("event")
        if not isinstance(inner, dict):
            return updates
        itype = str(inner.get("type") or "")

        if itype == "iteration_start":
            iteration = int(inner.get("iteration") or 0) or (len(texts) + 1)
            updates.append((20, f"第 {iteration} 轮推理"))
        elif itype == "content_end":
            # 文本按「段」收集（content_start 是分块流，拼接会重复）
            if str(inner.get("contentType") or "") == "text":
                text = str(inner.get("text") or "")
                if text.strip() and text not in texts:
                    texts.append(text)
                    updates.append((min(85, 30 + len(texts) * 5), f"生成：{text.strip()[-50:]}"))
            else:
                updates.append((28, "思考中…"))
        elif itype == "iteration_end":
            count = int(inner.get("toolCallCount") or 0)
            if count:
                counters["tool_calls"] += count
                updates.append((min(80, 25 + counters["tool_calls"]), f"调用工具 ×{count}"))
        elif itype == "done":
            reason = str(inner.get("reason") or "")
            if reason and reason != "completed":
                # 失败时 text 是结构化错误载荷（如 429 JSON），不能当正文收集
                message = _classify_error(inner.get("text")) or f"会话结束：{reason}"
                errors.append(message)
                updates.append((90, f"错误：{message[:80]}"))
            else:
                text = str(inner.get("text") or "").strip()
                if text and text not in texts:
                    texts.append(text)
                updates.append((88, "本轮推理结束"))
        return updates

    @staticmethod
    def _error_message(event: dict) -> str:
        """从 error 事件中提取可读信息（兼容 error.name / error.data.message 等形态）。"""
        err = event.get("error")
        if isinstance(err, str):
            return _classify_error(err) or "CLI 会话错误"
        if isinstance(err, dict):
            data = err.get("data")
            if isinstance(data, dict) and data.get("message"):
                return str(data["message"])
            message = _classify_error(json.dumps(err, ensure_ascii=False))
            if message:
                return message
        return _classify_error(json.dumps(event, ensure_ascii=False)) or "CLI 会话错误"

    @staticmethod
    def _stderr_messages(err_lines: list) -> list:
        """从 stderr 的 JSON 事件里提取可读错误文案。

        部分 CLI（如 Cline）会把真正的失败原因只写到 stderr 的 ``type=error``
        事件里，失败提示带上它用户才知道该怎么办。
        """
        messages: list = []
        for raw in err_lines:
            line = _strip_ansi(raw).strip()
            if not line.startswith("{"):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            message = _classify_error(json.dumps(payload, ensure_ascii=False))
            # 无法结构化解析时会回吐原始 JSON，这种就不要了
            if message and not message.startswith("{") and message not in messages:
                messages.append(message)
        return messages

    @staticmethod
    def _terminate(proc: subprocess.Popen) -> None:
        try:
            proc.terminate()
        except Exception:
            pass
        time.sleep(0.5)
        if proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass

    def _resolve_exe(self, config: dict) -> str:
        """定位当前 CLI 可执行文件（见模块级 resolve_agent_exe）。"""
        return resolve_agent_exe(config)

    def _attempt_models(self, config: dict) -> list:
        """构造模型尝试链：主模型（可留空=用 CLI 默认模型）+ 兜底模型（按序）。

        ``fallback_models`` 支持列表或按逗号/分号/换行分隔的字符串；去重且保序。
        """
        primary = str(config.get("model") or "").strip()
        raw = config.get("fallback_models")
        items = raw if isinstance(raw, list) else re.split(r"[,;\r\n]+", str(raw or ""))
        fallbacks = [str(item).strip() for item in items if str(item).strip()]

        attempts: list = []
        for model in [primary, *fallbacks]:
            if model not in attempts:
                attempts.append(model)
        return attempts or [""]

    # ---------- 组装逻辑 ----------

    def _normalize_output_items(self, raw_items: Any) -> list:
        """规范化输出产物设置，保证与输出端口一一对应。"""
        if not isinstance(raw_items, list):
            return []
        items: list = []
        for i, item in enumerate(raw_items[:8], start=1):
            if not isinstance(item, dict):
                item = {}
            port = str(item.get("port") or f"输出{i}")
            out_type = str(item.get("type") or "text")
            if out_type not in OUTPUT_TYPE_EXT:
                out_type = "text"
            items.append({
                "index": i,
                "port": port,
                "type": out_type,
                "desc": str(item.get("desc") or ""),
            })
        return items

    def _collect_recommended_tools(self, config: dict) -> dict:
        """收集前端选定的 Skill / MCP（与「小pi通用智能体」同构的配置项）。"""
        def _as_list(raw) -> list:
            if isinstance(raw, list):
                items = raw
            elif raw in (None, ""):
                items = []
            else:
                items = [raw]
            return [str(item).strip() for item in items if str(item).strip()]

        return {"skills": _as_list(config.get("skills")), "mcps": _as_list(config.get("mcps"))}

    def _build_prompt(self, instruction: str, task_dir: Path, work_dir: Path,
                      input_ports: dict, output_items: list,
                      recommended: Optional[dict] = None) -> str:
        """拼装交给 CLI 的任务指令（各 CLI 均无独立 system prompt 入参，全部并入 message）。"""
        workflow_path = task_dir / "workflow.json"
        task_json_path = task_dir / "task.json"
        background = {
            "task_dir": str(task_dir),
            "work_dir": str(work_dir),
            "workflow_json": str(workflow_path) if workflow_path.is_file() else "",
            "task_json": str(task_json_path) if task_json_path.is_file() else "",
        }
        parts = [
            instruction,
            "你是当前 VideoLingoFlow 工作流中的一个自动化节点执行器。"
            "请直接在给定工作目录内完成任务，不要反问用户、不要等待确认与交互。",
            f"## 任务背景\n{json.dumps(background, ensure_ascii=False, indent=2)}",
        ]
        # CLI 没有「按次指定 Skill/MCP」的统一命令行参数（各自从自身配置中发现可用项），
        # 因此与「小pi通用智能体」保持一致：把用户勾选的项作为本任务的优先推荐注入提示词。
        if recommended and (recommended.get("skills") or recommended.get("mcps")):
            parts.append(
                "## 推荐使用的 Skill / MCP\n"
                f"{json.dumps(recommended, ensure_ascii=False, indent=2)}\n"
                "（以上为本任务建议优先使用的项；CLI 会从自身配置中发现可用的 Skill 与 MCP，"
                "可按需选用其它工具。）"
            )
        parts += [
            f"## 本节点输入端口\n{json.dumps(input_ports, ensure_ascii=False, indent=2)}",
            f"## 本节点要求输出的产物\n{json.dumps(output_items, ensure_ascii=False, indent=2)}",
            (
                "## 执行与回报规则\n"
                "1. 输入端口的值可能为字符串或文件路径（相对任务目录），请按需读取后再处理。\n"
                "2. 需要落盘的产物请保存到任务目录下（推荐 cache/），并记录其相对路径。\n"
                "3. 任务完成后，在最终回复的最后单独输出一行结束标识：\n"
                f"   {DONE_MARKER}\n"
                "   并在其后输出验收 JSON（不要用代码块包裹）：\n"
                '   {"status": "success", "message": "简要说明", '
                '"outputs": {"1": "相对路径或文本值", "2": "..."}}\n'
                "   （任务失败时把 status 填为 \"failed\"）\n"
                "   其中 outputs 的键为输出序号（1 开始），值可以是相对任务目录的文件路径，"
                "或字符串类型产物的直接文本值。\n"
                "4. 若执行失败，同样输出结束标识并置 status 为 failed。"
            ),
        ]
        return "\n\n".join(parts)

    def _parse_done_payload(self, text: str) -> Optional[dict]:
        """从最终回复中解析 [OC_TASK_DONE] 标记后的验收 JSON。"""
        if not text or DONE_MARKER not in text:
            return None
        after = text.split(DONE_MARKER, 1)[1].strip()
        match = re.search(r"\{.*\}", after, re.DOTALL)
        if not match:
            return None
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def _collect_outputs(self, task_dir: Path, cache_dir: Path, node_id: str,
                         result: Optional[dict], output_items: list,
                         fallback_text: str) -> tuple:
        """按输出产物设置收拢产物到 cache/oc_agent_{node_id}_{i}{ext}，返回 (outputs, artifacts)。"""
        outputs: dict = {}
        artifacts: list = []
        reported = {}
        if isinstance(result, dict):
            raw = result.get("outputs") or {}
            if isinstance(raw, dict):
                reported = raw

        for item in output_items:
            index = item["index"]
            out_type = item["type"]
            port = item["port"]
            value = reported.get(str(index)) or reported.get(port)
            if value is None or value == "":
                # 未遵守回报协议时：首个 text 端口回填最终回答，尽力而为
                if result is None and index == 1 and out_type == "text":
                    outputs[f"output_{index}"] = fallback_text
                else:
                    outputs[f"output_{index}"] = ""
                continue
            if out_type == "text":
                outputs[f"output_{index}"] = str(value)
                continue
            try:
                src = _safe_output_path(str(task_dir), str(value))
            except ValueError:
                outputs[f"output_{index}"] = ""
                continue
            if not src.is_file():
                dst = cache_dir / f"oc_agent_{node_id}_{index}{OUTPUT_TYPE_EXT[out_type]}"
                dst.write_text(str(value), encoding="utf-8")
                artifacts.append(f"cache/{dst.name}")
                outputs[f"output_{index}"] = f"cache/{dst.name}"
                continue
            ext = src.suffix or OUTPUT_TYPE_EXT[out_type]
            dst = cache_dir / f"oc_agent_{node_id}_{index}{ext}"
            shutil.copy2(src, dst)
            artifacts.append(f"cache/{dst.name}")
            outputs[f"output_{index}"] = f"cache/{dst.name}"

        if isinstance(result, dict) and str(result.get("status", "")).lower() == "failed":
            raise RuntimeError(str(result.get("message") or "智能体报告任务失败"))
        return outputs, artifacts


StepOpenCodeAgent = S_OpenCodeAgent

"""s_opencode_agent: 本地 CLI 智能体工作流节点（opencode / mimo / Claude Code / Codex）。

把本机已安装的 CLI 智能体以工作流节点的方式嵌入执行链路；各 CLI 的命令形态与
事件协议差异集中声明在 CLI_SPECS 中，并分别由对应的事件解析分支处理：

- 组装任务指令（节点指令 + 任务背景 + 输入端口数据 + 输出产物契约）
- 按 CLI 规格非交互执行一次任务（opencode/mimo 为
  ``run <prompt> --format json --dir <work_dir>``，Claude Code 为 ``-p``，
  Codex 为 ``exec --json``）
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


def _safe_output_path(task_dir: str, relative: str) -> Path:
    """将 agent 报告的相对路径解析为任务目录内绝对路径，防止路径穿越。"""
    root = Path(task_dir).resolve()
    candidate = Path(relative)
    resolved = candidate if candidate.is_absolute() else (root / candidate).resolve()
    if root not in resolved.parents and resolved != root:
        raise ValueError(f"Agent output escapes task directory: {relative}")
    return resolved


# ---------------------------------------------------------------------------
# CLI 规格表：节点可在 opencode / mimo / claude / codex 四种 CLI 间切换。
#
# opencode 与 mimo（@mimo-ai/cli，即 "mimocode"）同源：
#   run <message> --format json --dir <dir> [-m model] [--agent] [--variant]
#       [--thinking] [--pure]
#   事件流同构（step_start / text / tool_use / step_finish / error），仅
#   「自动放行权限」flag 名与 `models` 输出格式不同（后者在 API 侧适配）。
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
        "dir_flag": "--dir",
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
}

DEFAULT_CLI = "opencode"


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
    for candidate in _iter_cli_candidates(spec, config, home):
        if candidate and Path(candidate).is_file():
            return candidate

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
                progress(5, f"主模型不可用，切换兜底模型 {index}/{len(attempts)}：{label}")
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
                failures.append(f"{label}: {str(exc).splitlines()[0]}")
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
        if run_style == "run":
            cmd = [exe, "run", message, *spec["json_output_args"]]
        elif run_style == "exec":
            # Codex：codex exec <message> --json ...；-o 把最后一条消息写入文件，
            # 作为与事件协议无关的最终文本兜底
            cmd = [exe, "exec", message, *spec["json_output_args"], *spec.get("always_args", ())]
            cmd += ["-o", str(S_OpenCodeAgent._last_message_path(cache_dir, node_id))]
        else:
            # Claude Code：-p/--print 非交互，prompt 紧随其后
            cmd = [exe, "-p", message, *spec["json_output_args"]]
        dir_flag = spec.get("dir_flag")
        if dir_flag:
            cmd += [dir_flag, str(work_dir)]
        if model:
            cmd += [spec["model_flag"], model]
        agent = str(config.get("agent") or "").strip()
        if agent:
            cmd += ["--agent", agent]
        variant = str(config.get("variant") or "").strip()
        if variant and "variant" in spec["supports"]:
            cmd += ["--variant", variant]
        # 非交互模式下未预授权的工具权限会被自动拒绝，故默认自动放行
        # （flag 名随 CLI 而变，见 CLI_SPECS.auto_flag）
        if config.get("auto_approve", True):
            cmd.append(spec["auto_flag"])
        if config.get("thinking") and "thinking" in spec["supports"]:
            cmd.append("--thinking")
        if config.get("pure") and "pure" in spec["supports"]:
            cmd.append("--pure")
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
        stderr_tail = "".join(err_lines)[-800:].strip()

        if returncode != 0 or errors:
            detail = "；".join(m for m in errors[:3] if m) or f"退出码 {returncode}"
            raise _ModelAttemptError(
                f"模型 {model_label} 调用失败：{detail}"
                + (f"\nstderr: {stderr_tail}" if stderr_tail else "")
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

    @staticmethod
    def _error_message(event: dict) -> str:
        """从 error 事件中提取可读信息（兼容 error.name / error.data.message 等形态）。"""
        err = event.get("error")
        if isinstance(err, str):
            return err
        if isinstance(err, dict):
            data = err.get("data")
            if isinstance(data, dict) and data.get("message"):
                return str(data["message"])
            if err.get("message"):
                return str(err["message"])
            if err.get("name"):
                return str(err["name"])
        return "CLI 会话错误"

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
                '   {"status": "success" | "failed", "message": "简要说明", '
                '"outputs": {"1": "相对路径或文本值", "2": "..."}}\n'
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

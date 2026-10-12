"""自定义节点运行时（execType: python / shell / llm / 空）。

节点执行契约与 workflow_runtime 的内置步骤分支保持一致：

- 子进程环境：注入项目根 PYTHONPATH（自定义脚本可 ``import backend...``）、
  PYTHONUNBUFFERED、venv bin/Scripts 置顶 PATH（ffmpeg/pip 解析到项目虚拟环境）
- Windows 隐藏控制台窗口（CREATE_NO_WINDOW），避免后台弹出黑框
- 取消协作：每 ~0.5s 复查 DB 任务状态 + cache 下的 .cancel_* 标记，
  命中则 kill 进程树并按取消处理（taskkill /F /T，可杀掉 ffmpeg 等孙进程）
- 超时同样走 kill 进程树，不再只杀直接子进程
- 支持子进程用 ``@PROGRESS@|<percent>|<message>`` 行协议上报进度
- outputs/artifacts 返回相对工作区的路径（与内置步骤一致，便于迁移/归档）
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable


NODE_TYPES_DIR = Path(__file__).parent.parent / "config" / "node_types"

# 取消信号复查间隔（秒）：贴合 workflow_runtime 线程域节点的 0.5s 缓存策略
_CANCEL_POLL_INTERVAL = 0.5
# stdout 行 -> 主线程的转发粒度（秒）
_LINE_POLL_INTERVAL = 0.25
# 任务处于这些状态即判定为取消
_CANCELLED_STATUSES = {"stopping", "deleting", "cancelled"}


def _find_project_root() -> str:
    """向上定位项目根目录（含 backend/main.py 的目录）。

    源码布局：backend/control_plane/custom_node_runtime.py          -> parents[2]
    编译布局：backend/control_plane_binaries/<py>/<plat>/backend/control_plane/ -> parents[5]
    """
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "backend" / "main.py").exists():
            return str(parent)
    return str(current.parents[2])


_PROJECT_ROOT = _find_project_root()


def load_custom_node_definition(node_type: str) -> dict | None:
    """读取自定义节点定义（backend/config/node_types/<nodeType>.json）。"""
    node_id = str(node_type or "").strip()
    if not node_id or node_id in {".", ".."} or "/" in node_id or "\\" in node_id:
        return None
    path = NODE_TYPES_DIR / f"{node_id}.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _rel(path: Path, workspace: Path) -> str:
    """统一为相对工作区路径（正斜杠），跨工作区时才保留绝对路径。"""
    try:
        return Path(path).resolve().relative_to(workspace.resolve()).as_posix()
    except (ValueError, OSError):
        return str(path).replace("\\", "/")


def _child_env(extra: dict[str, str] | None = None) -> dict:
    """子进程环境：与 _run_node_subprocess 保持同一构造方式。"""
    env = os.environ.copy()
    env["PYTHONPATH"] = _PROJECT_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    # 无缓冲输出：保证 @PROGRESS@ 行及时回传，避免进度更新滞后
    env["PYTHONUNBUFFERED"] = "1"
    # venv bin/Scripts 置顶：子进程里的 ffmpeg/pip 解析到项目虚拟环境
    _bin = os.path.dirname(os.path.abspath(sys.executable))
    if _bin:
        parts = [part for part in env.get("PATH", "").split(os.pathsep) if part and part != _bin]
        parts.insert(0, _bin)
        env["PATH"] = os.pathsep.join(parts)
    if extra:
        env.update(extra)
    return env


def _cancel_reason(task_id: str, cache_dir: Path, state: dict) -> str | None:
    """取消判定：DB 任务终态 + 取消标记文件（cache/.cancel_*）。

    命中一次即永久置位（不可回退），避免进程退出期间状态反复。
    """
    if state["cancelled"]:
        return state["reason"]
    now = time.monotonic()
    if now - state["at"] < _CANCEL_POLL_INTERVAL:
        return None
    state["at"] = now
    try:
        if any(cache_dir.glob(".cancel_*")):
            return _mark_cancelled(state, "user_requested")
    except OSError:
        pass
    if task_id:
        try:
            from backend.control_plane.database import session_scope
            from backend.control_plane.models import Task

            with session_scope() as session:
                task = session.get(Task, task_id)
                if task is None:
                    return _mark_cancelled(state, "task_missing")
                if task.status in _CANCELLED_STATUSES:
                    return _mark_cancelled(state, task.cancel_reason or "user_requested")
        except Exception:
            # DB 抖动/会话异常不作为取消信号，交由下一次轮询重试
            return None
    return None


def _mark_cancelled(state: dict, reason: str) -> str:
    state["cancelled"] = True
    state["reason"] = reason
    return reason


def _handle_line(line: str, progress: Callable[[int, str], None] | None) -> None:
    """解析 @PROGRESS@|<percent>|<message> 行协议并转发给进度回调。"""
    if not progress or not line.startswith("@PROGRESS@|"):
        return
    try:
        _, percent, message = line.split("|", 2)
        progress(max(0, min(100, int(percent))), message)
    except (ValueError, TypeError):
        pass


def _run_process(
    command: str | list[str],
    use_shell: bool,
    workspace: Path,
    cache_dir: Path,
    timeout: int,
    task_id: str,
    extra_env: dict[str, str],
    progress: Callable[[int, str], None] | None = None,
) -> tuple[int, list[str]]:
    """启动自定义节点子进程并等待结束，返回 (returncode, stdout_lines)。

    取消/超时均走 kill_process_tree，避免留下 ffmpeg 等孤儿孙进程。
    """
    from backend.control_plane.runtime import TaskCancelledError, TaskTimeoutError, kill_process_tree

    proc = subprocess.Popen(
        command,
        shell=use_shell,
        cwd=str(workspace),
        env=_child_env(extra_env),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    lines: list[str] = []
    line_queue: queue.Queue = queue.Queue()

    def _reader() -> None:
        try:
            for line in proc.stdout or []:
                line_queue.put(line)
        except Exception:
            pass
        finally:
            line_queue.put(None)

    threading.Thread(target=_reader, daemon=True).start()

    def _drain(block: bool) -> None:
        while True:
            try:
                raw = line_queue.get(timeout=_LINE_POLL_INTERVAL) if block else line_queue.get_nowait()
            except queue.Empty:
                return
            if raw is None:
                return
            line = raw.rstrip("\r\n")
            lines.append(line)
            _handle_line(line, progress)

    cancel_state = {"at": 0.0, "cancelled": False, "reason": ""}
    started = time.monotonic()
    try:
        while proc.poll() is None:
            _drain(block=True)
            if timeout and time.monotonic() - started > timeout:
                kill_process_tree(proc.pid)
                raise TaskTimeoutError(f"自定义节点超时: {timeout}s")
            reason = _cancel_reason(task_id, cache_dir, cancel_state)
            if reason:
                # 与主线程一致：落地标记后硬杀，供脚本侧轮询感知
                try:
                    (cache_dir / f".cancel_{task_id or 'task'}").touch()
                except OSError:
                    pass
                kill_process_tree(proc.pid)
                raise TaskCancelledError(reason)
        _drain(block=False)
    finally:
        if proc.poll() is None:
            kill_process_tree(proc.pid)
            try:
                proc.wait(timeout=10)
            except Exception:
                pass
    returncode = proc.returncode if proc.returncode is not None else -1
    try:
        proc.wait(timeout=10)
    except Exception:
        pass
    return returncode, lines


def _run_llm(node_type: str, node_id: str, definition: dict, node_config: dict, step_inputs: dict, workspace: Path, cache_dir: Path) -> dict:
    """LLM 类型自定义节点：走统一 LLMClient（路由/重试/日志），替代旧的裸 OpenAI 直连。"""
    prompt = str(definition.get("execCode") or "")
    for key, value in {**step_inputs, **node_config}.items():
        prompt = prompt.replace("{" + str(key) + "}", str(value))

    from backend.llm.llm_client import get_llm_client

    temperature: Any = node_config.get("temperature", 0.7)
    try:
        temperature = float(temperature)
    except (TypeError, ValueError):
        temperature = None
    content = get_llm_client().chat(
        step_name=f"custom_node_{node_type}",
        prompt=prompt,
        response_json=False,
        temperature=temperature,
        model_override=str(node_config.get("model") or ""),
        system_prompt=str(node_config.get("systemPrompt") or node_config.get("system_prompt") or "") or None,
    )
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    output_path = cache_dir / f"{node_id}_llm_output.txt"
    output_path.write_text(text, encoding="utf-8")
    rel = _rel(output_path, workspace)
    return {"outputs": {"text": rel}, "artifacts": [rel]}


def run_custom_node(
    node_type: str,
    node_id: str,
    definition: dict,
    node_config: dict,
    step_inputs: dict,
    workspace: Path,
    timeout: int,
    progress: Callable[[int, str], None] | None = None,
) -> dict:
    """执行自定义节点，返回 {"outputs": {...}, "artifacts": [...], "stdout": str}。

    ``progress`` 为可选进度回调；子进程可用 @PROGRESS@|<pct>|<msg> 行驱动它。
    """
    workspace = Path(workspace)
    cache_dir = workspace / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    task_id = workspace.name
    definition = definition or {}
    exec_type = str(definition.get("execType") or "").lower()
    if not exec_type:
        return {"outputs": dict(step_inputs), "artifacts": []}

    if exec_type == "llm":
        return _run_llm(node_type, node_id, definition, node_config or {}, step_inputs or {}, workspace, cache_dir)
    if exec_type not in {"python", "shell"}:
        raise ValueError(f"不支持的自定义节点执行类型: {exec_type}")

    command = str(definition.get("execCode") or "")
    code_dir = Path(str(definition.get("codeDir") or ""))
    exec_file = str(definition.get("execFile") or "")
    script_path: Path | None = None

    if exec_type == "python" and not command:
        if not exec_file:
            raise ValueError("自定义 Python 节点缺少内联代码或入口文件")
        script_path = Path(exec_file)
        if not script_path.is_absolute():
            script_path = code_dir / script_path if code_dir else script_path
        if not script_path.exists():
            raise ValueError(f"自定义 Python 入口文件不存在: {script_path}")
        process_command: list[str] | str = [sys.executable, str(script_path)]
        use_shell = False
    elif exec_type == "python":
        with tempfile.NamedTemporaryFile("w", suffix=".py", prefix=f"custom_{node_id}_", dir=cache_dir, encoding="utf-8", delete=False) as file:
            file.write(
                "import json\n"
                "import os\n"
                "task_dir = os.environ['TASK_DIR']\n"
                "cache_dir = os.environ['CACHE_DIR']\n"
                "node_id = os.environ['NODE_ID']\n"
                "node_config = json.loads(os.environ['NODE_CONFIG_JSON'])\n"
                "step_inputs = json.loads(os.environ['STEP_INPUTS_JSON'])\n"
                "config = node_config\n"
                "inputs = step_inputs\n"
                "produced = {}\n"
                + command
                + "\nwith open(os.environ['OUTPUTS_JSON_PATH'], 'w', encoding='utf-8') as _outputs_file:\n    json.dump(produced, _outputs_file, ensure_ascii=False)\n"
            )
            script_path = Path(file.name)
        process_command = [sys.executable, str(script_path)]
        use_shell = False
    else:
        if not command:
            raise ValueError("自定义 Shell 节点缺少命令")
        process_command = command
        use_shell = True
        script_path = None

    outputs_path = cache_dir / f"{node_id}_outputs.json"
    extra_env = {
        "TASK_DIR": str(workspace),
        "CACHE_DIR": str(cache_dir),
        "NODE_ID": node_id,
        "OUTPUTS_JSON_PATH": str(outputs_path),
        "NODE_CONFIG_JSON": json.dumps(node_config or {}, ensure_ascii=False),
        "STEP_INPUTS_JSON": json.dumps(step_inputs or {}, ensure_ascii=False),
        **{f"INPUT_{str(key).upper()}": str(value) for key, value in (step_inputs or {}).items()},
        **{f"CONFIG_{str(key).upper()}": str(value) for key, value in (node_config or {}).items()},
    }
    try:
        returncode, lines = _run_process(
            process_command, use_shell, workspace, cache_dir, max(1, int(timeout or 1)), task_id, extra_env, progress
        )
    finally:
        if exec_type == "python" and command and script_path:
            script_path.unlink(missing_ok=True)

    if returncode != 0:
        raise RuntimeError(("\n".join(lines[-20:]) or "自定义节点执行失败")[-1000:])

    outputs: dict = {}
    if outputs_path.exists():
        try:
            outputs = json.loads(outputs_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            outputs = {}
    if not isinstance(outputs, dict):
        raise ValueError("OUTPUTS_JSON_PATH 必须写入 JSON 对象")
    artifacts = [_rel(path, workspace) for path in cache_dir.glob(f"{node_id}_*") if path != outputs_path]
    return {"outputs": outputs, "artifacts": artifacts, "stdout": "\n".join(lines)[-1000:]}

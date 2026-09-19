"""s_opencode_agent: OpenCode 智能体工作流节点。

把本地 opencode CLI（https://opencode.ai）以工作流节点的方式嵌入执行链路：

- 组装任务指令（节点指令 + 任务背景 + 输入端口数据 + 输出产物契约）
- 以 ``opencode run <prompt> --format json --dir <work_dir>`` 非交互执行一次任务
- 逐行解析 stdout 的 JSON 事件流：
    * ``text``     完成的文本块（part.text）→ 汇总为最终回答
    * ``tool_use`` 工具调用 → 映射为进度
    * ``step_start`` / ``step_finish`` → 阶段进度
    * ``error``    会话错误 → 归集为失败原因
  终止条件：opencode 在会话 ``session.status == idle`` 后自行退出。
- 以约定结束标识 ``[OC_TASK_DONE]`` 验收；命中则按验收 JSON 收拢产物到 cache/，
  未命中则退化为「取最终文本作 text 输出」的尽力而为模式（不因协议不遵守而失败）。

节点设置里的 ``--auto``（自动放行工具权限）默认开启：opencode 在非交互模式下
对未预授权的工具权限请求会**自动拒绝**，不开则智能体基本无法读写文件、跑命令。
"""
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

# 单次 opencode 会话默认超时（秒）
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


def resolve_opencode_exe(config: Optional[dict] = None) -> str:
    """定位 opencode 可执行文件：节点设置 > 环境变量 > PATH > 常见安装位置。

    模块级函数，供节点步骤与 API（模型列表 / 连通性测试）共用。
    """
    config = config or {}
    home = Path.home()
    candidates = [
        str(config.get("opencode_exe") or "").strip(),
        os.environ.get("OPENCODE_EXE", "").strip(),
        shutil.which("opencode") or "",
        str(home / ".cherrystudio" / "bin" / "opencode.exe"),
        str(home / ".cherrystudio" / "install" / "global" / "node_modules"
            / "opencode-ai" / "bin" / "opencode.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError(
        "未找到 opencode 可执行文件：请在节点设置中填写 opencode 路径，"
        "或设置环境变量 OPENCODE_EXE"
    )


class S_OpenCodeAgent(BaseStep):
    step_id = "opencode_agent"
    step_name = "OpenCode 智能体"
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
            raise ValueError("OpenCode 智能体需要填写任务指令")

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
            label = model or "opencode 默认模型"
            if index == 1:
                progress(5, f"正在启动 opencode 会话（模型：{label}）")
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
                    env={**os.environ, "NO_COLOR": "1"},
                )
            except OSError as exc:
                raise RuntimeError(f"无法启动 opencode（{exe}）：{exc}") from exc
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

        progress(100, "OpenCode 智能体完成")
        return {"artifacts": artifacts, "outputs": outputs}

    # ---------- 命令与进程 ----------

    def _build_command(self, exe: str, config: dict, work_dir: Path, prompt: str,
                       node_id: str, cache_dir: Path, model: str = "") -> list:
        """组装 opencode run 命令行（message 紧随 run，与 CLI 实测用法一致）。"""
        message = prompt
        if len(prompt) > PROMPT_INLINE_LIMIT:
            prompt_file = cache_dir / f"oc_agent_{node_id}_prompt.md"
            prompt_file.write_text(prompt, encoding="utf-8")
            message = (
                f"完整任务说明已写入文件：{prompt_file}\n"
                "请先读取该文件，并严格按其中的背景、输入与输出契约执行本次任务。"
            )

        cmd = [exe, "run", message, "--format", "json", "--dir", str(work_dir)]
        if model:
            cmd += ["-m", model]
        agent = str(config.get("agent") or "").strip()
        if agent:
            cmd += ["--agent", agent]
        variant = str(config.get("variant") or "").strip()
        if variant:
            cmd += ["--variant", variant]
        # 非交互模式下未预授权的工具权限会被自动拒绝，故默认自动放行
        if config.get("auto_approve", True):
            cmd.append("--auto")
        if config.get("thinking"):
            cmd.append("--thinking")
        if config.get("pure"):
            cmd.append("--pure")
        return cmd

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

        timeout = float(config.get("timeout") or DEFAULT_TIMEOUT)
        deadline = time.monotonic() + timeout
        texts: list = []
        errors: list = []
        tool_calls = 0
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
            etype = event.get("type")

            if etype == "text":
                part = event.get("part") or {}
                text = str(part.get("text") or "")
                if text.strip():
                    texts.append(text)
                    progress(min(85, 30 + len(texts) * 5), f"生成：{text.strip()[-50:]}")
            elif etype == "tool_use":
                part = event.get("part") or {}
                tool_calls += 1
                progress(min(80, 25 + tool_calls), f"调用工具：{part.get('tool') or 'tool'}")
            elif etype == "step_start":
                progress(20, "智能体开始推理")
            elif etype == "step_finish":
                progress(88, "本轮推理结束")
            elif etype == "error":
                errors.append(self._error_message(event))
                progress(90, f"错误：{errors[-1][:80]}")

        if not stream_done:
            self._terminate(proc)
            t_out.join(timeout=2)
            t_err.join(timeout=2)
            if cancelled:
                raise RuntimeError("任务已取消")
            if not texts and not tool_calls:
                # 全程无任何输出即超时：判定为该模型不可用，允许回退到兜底模型
                raise _ModelAttemptError(f"模型 {model_label} 超时且无任何输出（>{int(timeout)}s）")
            raise RuntimeError(f"opencode 执行超时（>{int(timeout)}s）")

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
            "tool_calls": tool_calls,
            "returncode": returncode,
            "stderr_tail": stderr_tail,
        }

    @staticmethod
    def _error_message(event: dict) -> str:
        """从 error 事件中提取可读信息（opencode: error.name / error.data.message）。"""
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
        return "opencode 会话错误"

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
        """定位 opencode 可执行文件（见模块级 resolve_opencode_exe）。"""
        return resolve_opencode_exe(config)

    def _attempt_models(self, config: dict) -> list:
        """构造模型尝试链：主模型（可留空=用 opencode 默认模型）+ 兜底模型（按序）。

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
        """拼装交给 opencode 的任务指令（opencode 无独立 system prompt 入参，全部并入 message）。"""
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
        # opencode 没有「按次指定 Skill/MCP」的命令行参数（它从自身配置中发现可用项），
        # 因此与「小pi通用智能体」保持一致：把用户勾选的项作为本任务的优先推荐注入提示词。
        if recommended and (recommended.get("skills") or recommended.get("mcps")):
            parts.append(
                "## 推荐使用的 Skill / MCP\n"
                f"{json.dumps(recommended, ensure_ascii=False, indent=2)}\n"
                "（以上为本任务建议优先使用的项；opencode 会从自身配置中发现可用的 Skill 与 MCP，"
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

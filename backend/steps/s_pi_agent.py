"""s_pi_agent: 小Pi通用智能体工作流节点。

把 Pi 以工作流节点方式嵌入工作流执行链路：
- 组装该节点 Pi 会话的系统提示（全局默认人设 + 节点人设 + 任务背景 + 推荐工具 + 输入输出契约）
- 发起一次性 Pi 会话并执行任务
- 流式反馈执行过程（thinking/text 摘要 → callback 进度）
- 以约定结束标识 [PI_TASK_DONE] 验收结果
- 将智能体生成的按序号命名的产物收拢到 task_dir/cache/agent_{node_id}_{i}{ext}
"""
import asyncio
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Callable, Optional

from backend.pi_rpc import get_pi_manager
from backend.pi_rpc.client import PiRpcClient
from backend.steps.base_step import BaseStep

# 约定的任务结束标识：agent 最终回复须包含该标记，后跟验收 JSON
DONE_MARKER = "[PI_TASK_DONE]"

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


def _safe_output_path(task_dir: str, relative: str) -> Path:
    """将 agent 报告的相对路径解析为任务目录内绝对路径，防止路径穿越。"""
    root = Path(task_dir).resolve()
    candidate = Path(relative)
    if candidate.is_absolute():
        resolved = candidate
    else:
        resolved = (root / candidate).resolve()
    if root not in resolved.parents and resolved != root:
        raise ValueError(f"Agent output escapes task directory: {relative}")
    return resolved


class S_PiAgent(BaseStep):
    step_id = "pi_agent"
    step_name = "小pi通用智能体"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        if not node_id:
            return False
        cache_dir = os.path.join(task_dir, "cache")
        if not os.path.isdir(cache_dir):
            return False
        prefix = f"agent_{node_id}_"
        return any(name.startswith(prefix) for name in os.listdir(cache_dir))

    def validate_inputs(self, task_dir: str) -> bool:
        config = getattr(self, "_node_config", {}) or {}
        return bool(str(config.get("persona", "")).strip())

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        config = getattr(self, "_node_config", {}) or {}
        inputs = getattr(self, "_step_inputs", {}) or {}
        node_id = getattr(self, "_node_id", "") or "node"
        persona = str(config.get("persona", "")).strip()
        if not persona:
            raise ValueError("小pi通用智能体需要人设设定")

        task_dir_path = Path(task_dir).resolve()
        task_dir_path.mkdir(parents=True, exist_ok=True)
        cache_dir = task_dir_path / "cache"
        cache_dir.mkdir(exist_ok=True)

        # 组装输入输出契约
        input_ports = {f"input_{i}": inputs.get(f"input_{i}", "") for i in range(1, int(config.get("inputCount", 2)) + 1)}
        output_items = self._normalize_output_items(config.get("output_items", []))

        # 任务背景：task_dir / workflow.json / task.json
        workflow_path = task_dir_path / "workflow.json"
        task_json_path = task_dir_path / "task.json"
        background = {
            "task_dir": str(task_dir_path),
            "workflow_json": str(workflow_path) if workflow_path.is_file() else "",
            "task_json": str(task_json_path) if task_json_path.is_file() else "",
        }

        # 推荐工具：skills / mcps / docs
        recommended = self._collect_recommended_tools(config)

        system_prompt = self._build_system_prompt(persona, background, recommended, input_ports, output_items)

        def progress(percent: int, message: str) -> None:
            if callback:
                try:
                    callback(percent, message)
                except Exception:
                    pass

        # 一次性 Pi 会话（不在全局会话管理器注册，结束时关闭）
        async def _execute() -> dict:
            manager = get_pi_manager()
            client: PiRpcClient | None = None
            try:
                if cancel_callback and cancel_callback():
                    raise RuntimeError("任务已取消")
                progress(5, "正在启动小 Pi 智能体会话")
                client = await manager.workflow_session(
                    system_prompt=system_prompt,
                    cwd=str(task_dir_path),
                    tools=None,  # 使用全局 allow_tools
                )
                if cancel_callback and cancel_callback():
                    raise RuntimeError("任务已取消")
                progress(10, "小 Pi 智能体会话已就绪")

                final_text: list[str] = []
                last_msg: dict[str, Any] = {}

                async def _on_event(event: dict[str, Any]) -> None:
                    nonlocal last_msg
                    etype = event.get("type", "")
                    if etype == "agent_start":
                        progress(15, "智能体开始思考")
                    delta = event.get("assistantMessageEvent") or {}
                    dtype = delta.get("type", "")
                    if dtype == "thinking_delta" and delta.get("delta"):
                        snippet = str(delta["delta"])[:60]
                        progress(min(60, 20 + len(final_text) % 40), f"思考中: {snippet}")
                    elif dtype == "text_delta" and delta.get("delta"):
                        final_text.append(str(delta["delta"]))
                        snippet = str(delta["delta"])[-50:]
                        progress(min(85, 40 + len(final_text) % 45), f"生成: {snippet}")
                    elif etype == "message_end":
                        message = event.get("message") or {}
                        if isinstance(message, dict) and message.get("role") == "assistant":
                            last_msg = message
                    elif etype == "agent_end":
                        # agent_end 携带完整消息列表，可拿到最终 assistant 完整回复
                        for message in event.get("messages") or []:
                            if isinstance(message, dict) and message.get("role") == "assistant":
                                last_msg = message
                    elif etype == "tool_execution_end":
                        progress(50, f"调用工具: {event.get('toolName', '')}")

                client.subscribe(_on_event)
                if cancel_callback and cancel_callback():
                    raise RuntimeError("任务已取消")
                progress(20, "发送任务指令")
                task_instruction = self._build_task_instruction(input_ports, output_items)
                # Pi 的 prompt 命令在“preflight 通过”时即返回响应，LLM 生成是异步的。
                # 必须等待 Pi 发出终止事件（agent_settled/agent_end/pi_closed）后才可验收，
                # 否则 final_text 尚未收集完成，会误报“未返回 [PI_TASK_DONE]”。
                settled = asyncio.Event()

                async def _on_terminal(event: dict[str, Any]) -> None:
                    if event.get("type") in ("agent_settled", "agent_end", "pi_closed"):
                        settled.set()

                client.subscribe(_on_terminal)
                await client.prompt(task_instruction, "steer", 300)
                if cancel_callback and cancel_callback():
                    raise RuntimeError("任务已取消")
                try:
                    await asyncio.wait_for(settled.wait(), timeout=300)
                except asyncio.TimeoutError:
                    pass

                # 汇总最终助手回复（text 部分）
                full_text = "".join(final_text)
                if not full_text and last_msg:
                    content = last_msg.get("content") or []
                    full_text = "".join(
                        str(item.get("text", ""))
                        for item in content
                        if isinstance(item, dict) and item.get("type") == "text"
                    )
                result = self._parse_done_payload(full_text)
                if result is None:
                    snippet = (full_text.strip() or "(empty)")[-600:]
                    stderr_tail = " | ".join(getattr(client, "stderr_tail", []) or [])[-500:]
                    raise RuntimeError(
                        f"智能体未返回约定的任务结束标识 [PI_TASK_DONE]，请检查其输出。"
                        f"Pi 实际输出尾部：{snippet}"
                        + (f"；Pi stderr：{stderr_tail}" if stderr_tail else "")
                    )

                progress(90, "正在收拢产物")
                outputs = self._collect_outputs(task_dir_path, cache_dir, node_id, result, output_items)
                progress(100, "节点完成")
                return outputs
            finally:
                if client is not None:
                    try:
                        await client.close()
                    except Exception:
                        pass

        try:
            return asyncio.run(_execute())
        except RuntimeError as exc:
            if cancel_callback and cancel_callback():
                raise RuntimeError(f"任务已取消: {exc}") from exc
            raise

    # ---------- 组装逻辑 ----------

    def _normalize_output_items(self, raw_items: Any) -> list[dict[str, Any]]:
        """规范化输出产物设置，保证与输出端口一一对应。"""
        if not isinstance(raw_items, list):
            return []
        items: list[dict[str, Any]] = []
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

    def _collect_recommended_tools(self, config: dict[str, Any]) -> dict[str, Any]:
        """收集前端选定的 Skill/MCP/参考文档。"""
        skills = config.get("skills") or []
        mcps = config.get("mcps") or []
        if not isinstance(skills, list):
            skills = [skills]
        if not isinstance(mcps, list):
            mcps = [mcps]
        return {
            "skills": [str(item) for item in skills if str(item).strip()],
            "mcps": [str(item) for item in mcps if str(item).strip()],
            "docs_path": str(config.get("docs_path") or ""),
            "external_doc": str(config.get("external_doc") or ""),
        }

    def _build_system_prompt(
        self,
        persona: str,
        background: dict[str, Any],
        recommended: dict[str, Any],
        input_ports: dict[str, Any],
        output_items: list[dict[str, Any]],
    ) -> str:
        """拼装节点 Pi 会话的系统提示。"""
        parts = [
            persona,
            "你是当前 VideoLingoFlow 工作流中的一个节点执行器。你的任务由工作流节点发起，执行完成后必须以约定的结束标识回报验收结果。",
            f"## 任务背景\n{json.dumps(background, ensure_ascii=False, indent=2)}",
            f"## 推荐使用的工具\n{json.dumps(recommended, ensure_ascii=False, indent=2)}",
            f"## 本节点输入端口\n{json.dumps(input_ports, ensure_ascii=False, indent=2)}",
            f"## 本节点要求输出的产物\n{json.dumps(output_items, ensure_ascii=False, indent=2)}",
            (
                "## 执行与回报规则\n"
                f"1. 输入端口的值可能为字符串或文件路径（相对任务目录），请按需读取后再处理。\n"
                "2. 按要求完成本次任务并生成产物。每个需要落盘的产物请保存到任务目录下（推荐 cache/ 目录），并记录其相对路径。\n"
                "3. 任务完成后，在最终回复的最后单独输出一行结束标识：\n"
                f"   {DONE_MARKER}\n"
                "   并在其后输出验收 JSON（不要用代码块包裹）：\n"
                '   {"status": "success" | "failed", "message": "简要说明", "outputs": {"1": "相对路径或文本值", "2": "..."}}\n'
                "   其中 outputs 的键为输出序号（1 开始），值可以是相对任务目录的文件路径，或字符串类型产物的直接文本值。\n"
                "4. 若执行失败，同样输出结束标识并置 status 为 failed。"
            ),
        ]
        return "\n\n".join(parts)

    def _build_task_instruction(self, input_ports: dict[str, Any], output_items: list[dict[str, Any]]) -> str:
        return (
            "请开始执行本次工作流节点任务。\n"
            f"输入端口数据：{json.dumps(input_ports, ensure_ascii=False)}\n"
            f"输出要求：{json.dumps(output_items, ensure_ascii=False)}\n"
            "完成后按系统提示中的约定输出 [PI_TASK_DONE] 结束标识与验收 JSON。"
        )

    def _parse_done_payload(self, text: str) -> dict[str, Any] | None:
        """从最终回复中解析 [PI_TASK_DONE] 标记后的验收 JSON。"""
        if DONE_MARKER not in text:
            return None
        after = text.split(DONE_MARKER, 1)[1].strip()
        match = re.search(r"\{.*\}", after, re.DOTALL)
        if not match:
            return None
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def _collect_outputs(
        self,
        task_dir: Path,
        cache_dir: Path,
        node_id: str,
        result: dict[str, Any],
        output_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """按输出产物设置收拢智能体产物到 cache/agent_{node_id}_{i}{ext}，返回端口输出映射。"""
        status = str(result.get("status", "failed"))
        outputs: dict[str, Any] = {}
        artifacts: list[str] = []
        reported = result.get("outputs") or {}
        if not isinstance(reported, dict):
            reported = {}

        for item in output_items:
            index = item["index"]
            out_type = item["type"]
            port = item["port"]
            value = reported.get(str(index)) or reported.get(port)
            if value is None or value == "":
                outputs[f"output_{index}"] = ""
                continue
            if out_type == "text":
                # 字符串类型：直接作为端口输出值
                outputs[f"output_{index}"] = str(value)
                continue
            # 文件类型：解析路径并复制到 cache 目录
            try:
                src = _safe_output_path(str(task_dir), str(value))
            except ValueError:
                outputs[f"output_{index}"] = ""
                continue
            if not src.is_file():
                # 文件不存在，把文本原样落盘
                dst = cache_dir / f"agent_{node_id}_{index}{OUTPUT_TYPE_EXT[out_type]}"
                dst.write_text(str(value), encoding="utf-8")
                artifacts.append(f"cache/{dst.name}")
                outputs[f"output_{index}"] = f"cache/{dst.name}"
                continue
            ext = src.suffix or OUTPUT_TYPE_EXT[out_type]
            dst = cache_dir / f"agent_{node_id}_{index}{ext}"
            shutil.copy2(src, dst)
            artifacts.append(f"cache/{dst.name}")
            outputs[f"output_{index}"] = f"cache/{dst.name}"

        if status == "failed":
            raise RuntimeError(str(result.get("message") or "智能体报告任务失败"))
        return {"artifacts": artifacts, "outputs": outputs}

# -*- coding: utf-8 -*-
"""
指定调用工作流节点（Step）

作用：用户在卡片上指定若干要调用的工作流（分组 + 工作流），后端按选择顺序把每个工作流的
「通用调用方法 / 工作流入口 / 输入与输出 / 节点组成与可选配置」组装成一份参考提示词，
从「提示词」端口输出给下游智能体使用。不落盘，纯内存文本输出。
"""
import json
from pathlib import Path

from backend.steps.base_step import BaseStep

# 工作流定义目录：backend/config/workflows/{id}.json
WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / "config" / "workflows"

PROMPT_HEADER = (
    "# 工作流调用参考（自动生成）\n"
    "以下按本节点配置所选工作流的顺序，逐一给出供智能体调用的参考信息，"
    "每项包含：通用调用方法、工作流入口、输入与输出、节点组成与可选配置。\n"
)

GENERIC_METHOD = (
    "【通用调用方法】该工作流由工作流引擎统一调度：通过工作流 id 引用本工作流，"
    "将上游数据接入其输入端口（或输入节点的配置），引擎按节点连线顺序依次执行内部各节点，"
    "全部完成后从输出端口（或输出节点）取用结果；工作流的整体行为由其内部各节点的配置共同决定。"
)


def _fmt_ports(ports) -> str:
    if not ports:
        return "（无）"
    return "、".join(f"{p.get('label', '')}({p.get('type', '')})" for p in ports)


def _workflow_io(wf_data: dict) -> str:
    """解析工作流的输入/输出：输入节点的输出端口 + 输出节点的输入端口。"""
    from backend.config.builtin_node_types import get_builtin_node_type

    nodes = wf_data.get("nodes") or []
    lines = []
    for n in nodes:
        data = n.get("data") or {}
        nt = data.get("nodeType") or n.get("nodeType") or ""
        label = data.get("label") or nt
        if nt == "input":
            def_ = get_builtin_node_type(nt) or {}
            lines.append(f"  - 输入节点「{label}」输出端口：{_fmt_ports(def_.get('outputs'))}")
        elif nt == "output":
            def_ = get_builtin_node_type(nt) or {}
            lines.append(f"  - 输出节点「{label}」输入端口：{_fmt_ports(def_.get('inputs'))}")
    if not lines:
        return "（该工作流未使用独立输入/输出节点，IO 由内部节点连线决定）"
    return "\n".join(lines)


def _workflow_nodes(wf_data: dict) -> str:
    """列出工作流组成节点及其非空配置概要。"""
    nodes = wf_data.get("nodes") or []
    if not nodes:
        return "（无节点）"
    lines = []
    for i, n in enumerate(nodes, 1):
        data = n.get("data") or {}
        nt = data.get("nodeType") or n.get("nodeType") or "unknown"
        label = data.get("label") or nt
        cfg = data.get("config") or {}
        kv = []
        for k, v in cfg.items():
            if v is None or v == "" or v == [] or v == {}:
                continue
            if isinstance(v, str) and not v.strip():
                continue
            sv = v if isinstance(v, (str, int, float, bool)) else json.dumps(v, ensure_ascii=False)
            if isinstance(sv, str) and len(sv) > 60:
                sv = sv[:60] + "…"
            kv.append(f"{k}={sv}")
        cfg_str = "；".join(kv[:12]) if kv else "（无配置）"
        lines.append(f"  {i}. {label}（nodeType: {nt}）配置：{cfg_str}")
    return "\n".join(lines)


class StepSpecifiedWorkflow(BaseStep):
    step_id = "specified_workflow"
    step_name = "指定调用工作流"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        # 本节点不落盘，内存输出即视为完成。
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir, callback=None, cancel_callback=None):
        node_config = getattr(self, "_node_config", {}) or {}
        selection = node_config.get("workflows") or []

        # 收集所选工作流 id（去重、保序、忽略空选）
        seen: set[str] = set()
        ordered_ids: list[str] = []
        for item in selection:
            if not isinstance(item, dict):
                continue
            wid = str(item.get("workflow") or "").strip()
            if not wid or wid in seen:
                continue
            seen.add(wid)
            ordered_ids.append(wid)

        blocks = []
        for i, wid in enumerate(ordered_ids, 1):
            fp = WORKFLOWS_DIR / f"{wid}.json"
            if not fp.exists():
                blocks.append(
                    f"## {i}. {wid}（id: {wid}）\n"
                    f"{GENERIC_METHOD}\n\n"
                    f"【工作流入口】\n（未找到工作流定义文件：backend/config/workflows/{wid}.json）\n\n"
                    f"【工作流的输入和输出】\n（无法解析）\n\n"
                    f"【工作流的节点组成与可选配置】\n（无法解析）"
                )
                continue
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
            except Exception:
                blocks.append(
                    f"## {i}. {wid}（id: {wid}）\n{GENERIC_METHOD}\n\n"
                    f"【工作流入口】\n（工作流定义文件读取/解析失败）\n\n"
                    f"【工作流的输入和输出】\n（无法解析）\n\n"
                    f"【工作流的节点组成与可选配置】\n（无法解析）"
                )
                continue
            name = data.get("name", wid)
            desc = data.get("description", "")
            nodes = data.get("nodes") or []
            edges = data.get("edges") or []
            block = (
                f"## {i}. {name}（id: {wid}）\n"
                f"{GENERIC_METHOD}\n\n"
                f"【工作流入口】\n"
                f"- 工作流 ID：{wid}\n"
                f"- 名称：{name}\n"
                f"- 描述：{desc or '（无）'}\n"
                f"- 定义文件：backend/config/workflows/{wid}.json\n"
                f"- 规模：{len(nodes)} 个节点 / {len(edges)} 条连线\n\n"
                f"【工作流的输入和输出】\n{_workflow_io(data)}\n\n"
                f"【工作流的节点组成与可选配置】\n{_workflow_nodes(data)}"
            )
            blocks.append(block)

        if not blocks:
            prompt = PROMPT_HEADER + "\n（未在节点配置中选择任何有效工作流，无法生成调用参考。）"
        else:
            prompt = PROMPT_HEADER + "\n\n".join(blocks) + "\n"

        if callback:
            try:
                callback(100, f"已生成工作流调用参考提示词（{len(blocks)} 个工作流，{len(prompt)} 字）")
            except Exception:
                pass
        # 不落盘：直接以内联文本作为输出，在节点间内存传递。
        return {"outputs": {"prompt": prompt}}

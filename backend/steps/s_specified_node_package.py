# -*- coding: utf-8 -*-
"""
指定调用节点包节点（Step）

作用：用户在卡片上指定若干要调用的节点（分组 + 节点），后端按选择顺序把每个节点的
「通用调用方法 / 入口脚本路径 / 输入与输出端口 / 可选设置参数」组装成一份参考提示词，
从「提示词」端口输出给下游智能体使用。不落盘，纯内存文本输出。
"""
import inspect
import os

from backend.steps.base_step import BaseStep
from backend.config.node_schema import NODE_CATEGORIES

CAT_LABEL = {c["value"]: c["label"] for c in NODE_CATEGORIES}

PROMPT_HEADER = (
    "# 节点调用参考（自动生成）\n"
    "以下按本节点配置所选节点的顺序，逐一给出供智能体调用的参考信息，"
    "每项包含：通用调用方法、入口脚本路径、输入与输出端口、可选设置参数。\n"
)

GENERIC_METHOD = (
    "【通用调用方法】该节点由工作流引擎统一调度：在画布中按节点 id 引用本节点，"
    "将上游节点输出连接至其输入端口完成数据接入，引擎调用「入口脚本路径」对应的步骤执行，"
    "执行完毕后从输出端口取用结果；节点行为由「可选设置参数」配置，未显式设置项使用默认值。"
)


def _entry_script_path(nid: str) -> str:
    from backend.steps.step_registry import get_step_instance

    inst = get_step_instance(nid)
    if inst is None:
        return "（未注册对应执行步骤，可能为自定义节点）"
    cls = type(inst)
    try:
        f = inspect.getfile(cls)
    except Exception:
        f = ""
    f = os.path.normpath(f).replace("\\", "/")
    marker = "backend/steps/"
    idx = f.find(marker)
    if idx >= 0:
        return f[idx:]
    return getattr(cls, "__module__", str(cls))


def _fmt_ports(ports) -> str:
    if not ports:
        return "（无）"
    return "\n".join(
        f"  - {p.get('id')}：{p.get('label', '')}（类型 {p.get('type', '')}）" for p in ports
    )


def _fmt_fields(def_: dict) -> str:
    fields = def_.get("configFields") or []
    if not fields:
        return "（无可选设置参数）"
    dc = def_.get("defaultConfig") or {}
    lines = []
    for f in fields:
        key = f.get("key")
        label = f.get("label")
        ftype = f.get("type")
        default = dc.get(key, "（无）")
        lines.append(f"  - {label}（key={key}，类型 {ftype}，默认值：{default}）")
    return "\n".join(lines)


class StepSpecifiedNodePackage(BaseStep):
    step_id = "specified_node_package"
    step_name = "指定调用节点包"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        # 本节点不落盘，内存输出即视为完成。
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir, callback=None, cancel_callback=None):
        from backend.config.builtin_node_types import get_builtin_node_type

        node_config = getattr(self, "_node_config", {}) or {}
        packages = node_config.get("packages") or []

        # 收集所选节点 id（去重、保序、忽略空选）
        seen: set[str] = set()
        ordered_ids: list[str] = []
        for item in packages:
            if not isinstance(item, dict):
                continue
            nid = str(item.get("node") or "").strip()
            if not nid or nid in seen:
                continue
            seen.add(nid)
            ordered_ids.append(nid)

        blocks = []
        for i, nid in enumerate(ordered_ids, 1):
            def_ = get_builtin_node_type(nid)
            if def_ is None:
                blocks.append(
                    f"## {i}. {nid}（id: {nid}，分组：未知）\n"
                    f"{GENERIC_METHOD}\n\n"
                    f"【入口脚本路径】\n{_entry_script_path(nid)}\n\n"
                    f"【输入与输出端口】\n（未在内置节点清单中找到该节点定义，无法列出端口）\n\n"
                    f"【可选设置参数】\n（无）"
                )
                continue
            cat = def_.get("category", "")
            cat_label = CAT_LABEL.get(cat, cat)
            block = (
                f"## {i}. {def_.get('name', nid)}（id: {nid}，分组：{cat_label}）\n"
                f"{GENERIC_METHOD}\n\n"
                f"【入口脚本路径】\n{_entry_script_path(nid)}\n\n"
                f"【输入与输出端口】\n输入：\n{_fmt_ports(def_.get('inputs'))}\n"
                f"输出：\n{_fmt_ports(def_.get('outputs'))}\n\n"
                f"【可选设置参数】\n{_fmt_fields(def_)}"
            )
            blocks.append(block)

        if not blocks:
            prompt = PROMPT_HEADER + "\n（未在节点配置中选择任何有效节点，无法生成调用参考。）"
        else:
            prompt = PROMPT_HEADER + "\n\n".join(blocks) + "\n"

        if callback:
            try:
                callback(100, f"已生成节点调用参考提示词（{len(blocks)} 个节点，{len(prompt)} 字）")
            except Exception:
                pass
        # 不落盘：直接以内联文本作为输出，在节点间内存传递。
        return {"outputs": {"prompt": prompt}}

# -*- coding: utf-8 -*-
"""生产 Agent（三层编排）—— 移植源 productionAgent/index.ts：

    决策层（production_agent_decision.md，system）
      ├─ 工具 run_sub_agent_*：派发执行层子 Agent（每个子 Agent = 对应技能文件 + 相关服务端工具的
      │   一次 tool-loop，语义对齐源"子 Agent 即工具"）
      ├─ 工具 run_supervision：监督层按质检规则审核产出（production_agent_supervision.md）
      └─ 服务端工具：get_flowData 等（源"前端执行器回调"已全部服务端化）

所有 LLM 调用走本项目 llm_client 路由；事件经 emit 单向推送到前端侧边栏。
"""
import json
from typing import Callable

from backend.toonflow.agents.loop import run_tool_loop
from backend.toonflow.agents.memory import Memory
from backend.toonflow.agents.tools import (
    build_supervision_tool, build_workspace_tools, common_skill_body,
)
from backend.toonflow.agents.workspace import project_summary

DECISION_SKILL = "production_agent_decision.md"
EXEC_SKILLS = {
    "derive_assets": "production_execution_derive_assets.md",
    "generate_assets": "production_execution_generate_assets.md",
    "director_plan": "production_execution_director_plan.md",
    "storyboard_table": "production_execution_storyboard_table.md",
    "storyboard_panel": "production_execution_storyboard_panel.md",
    "storyboard_gen": "production_execution_storyboard_gen.md",
}
SUPERVISION_SKILL = "production_agent_supervision.md"


def _sub_agent_tool(name: str, skill_file: str, description: str,
                    build_tools: Callable, project_id: int, emit,
                    result_hook: Callable[[str], None] | None = None) -> "Tool":
    """执行层子 Agent：一次独立 tool-loop，system 为对应技能文件。

    build_tools() 返回该子 Agent 可用的工具字典（各 _make_* 已按需裁剪）。
    result_hook(result_text)：子 Agent 结束后对产出的落库钩子
    （源"面板流式写入"的服务端等价物），异常转为 warn 不中断。
    """
    from backend.toonflow.agents.loop import Tool

    def execute(args):
        instruction = str(args.get("instruction") or "").strip()
        if not instruction:
            return {"error": "instruction 不能为空"}
        sub_tools = build_tools()
        system = common_skill_body(skill_file)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": instruction},
        ]
        emit("thinking", {"text": f"[子Agent:{name}] 启动（技能 {skill_file}）"})
        result = run_tool_loop(messages, sub_tools, agent_key=f"productionAgent:{name}",
                               max_steps=60, emit=emit)
        if result_hook:
            try:
                result_hook(result)
                emit("thinking", {"text": f"[子Agent:{name}] 产出已落库"})
            except Exception as exc:  # noqa: BLE001
                emit("warn", {"message": f"[子Agent:{name}] 产出落库失败: {exc}"})
        return result

    return Tool(name, description,
                {"type": "object",
                 "properties": {"instruction": {"type": "string"}},
                 "required": ["instruction"]}, execute)


def run_decision_agent(project_id: int, user_text: str, emit=None) -> str:
    """决策层主循环：理解意图 → 拆解派发 → 质量把关 → 汇报（带向量化记忆）。"""
    emit = emit or (lambda kind, payload: None)
    summary = project_summary(project_id)
    memory = Memory("productionAgent", project_id)

    workspace_tools = build_workspace_tools(project_id)
    supervision = build_supervision_tool(project_id, SUPERVISION_SKILL)

    def _make_derive():
        sub = build_workspace_tools(project_id)
        return {k: sub[k] for k in ("get_flowData", "add_derive_asset", "del_derive_asset",
                                    "get_production_status")}

    def _make_generate_assets():
        sub = build_workspace_tools(project_id)
        return {k: sub[k] for k in ("get_flowData", "generate_assets", "get_production_status")}

    def _make_plan():
        sub = build_workspace_tools(project_id)
        return {k: sub[k] for k in ("get_flowData",)}

    def _make_board():
        sub = build_workspace_tools(project_id)
        return {k: sub[k] for k in ("get_flowData", "generate_storyboard",
                                    "generate_storyboard_images", "get_production_status")}

    def _persist_board_result(text: str) -> None:
        """分镜表子 Agent 产出落库：解析 <storyboardTable> 标签并重建分镜行。"""
        from backend.toonflow.pipeline import storyboard as pipe_board

        n = pipe_board.persist_storyboard_table_markdown(project_id, text)
        if n == 0:
            raise ValueError("输出中未找到 <storyboardTable> 标签或无有效分镜行")

    tools: dict = {}
    tools.update(workspace_tools)
    tools.update({supervision.name: supervision})
    tools.update({memory.deep_retrieve_tool().name: memory.deep_retrieve_tool()})

    # 记忆注入：短期未摘要消息 + 历史摘要 + 向量召回
    mem = memory.get(user_text)
    mem_lines = []
    if mem["shortTerm"]:
        mem_lines.append("近期对话：\n" + "\n".join(
            f"{m['role']}: {m['content'][:200]}" for m in mem["shortTerm"]))
    if mem["summaries"]:
        mem_lines.append("历史摘要：\n" + "\n".join(
            f"- {s['content'][:200]}" for s in mem["summaries"]))
    if mem["rag"]:
        mem_lines.append("相关记忆：\n" + "\n".join(
            f"- {r['content'][:200]}" for r in mem["rag"] if r["similarity"] > 0.35))
    memory_block = ("\n\n## 记忆（本项目历史会话）\n" + "\n\n".join(mem_lines)) if mem_lines else ""
    tools["run_sub_agent_derive_assets"] = _sub_agent_tool(
        "run_sub_agent_derive_assets", EXEC_SKILLS["derive_assets"],
        "派发执行层：分析剧本/事件，新增或修改衍生资产（角色多形态/场景状态/道具变体）",
        _make_derive, project_id, emit)
    tools["run_sub_agent_generate_assets"] = _sub_agent_tool(
        "run_sub_agent_generate_assets", EXEC_SKILLS["generate_assets"],
        "派发执行层：为缺失图片的资产生成图片（会自动挑选待生成清单）",
        _make_generate_assets, project_id, emit)
    tools["run_sub_agent_director_plan"] = _sub_agent_tool(
        "run_sub_agent_director_plan", EXEC_SKILLS["director_plan"],
        "派发执行层：阅读剧本与事件，产出拍摄计划（保存到工作区 scriptPlan）",
        _make_plan, project_id, emit)
    tools["run_sub_agent_storyboard"] = _sub_agent_tool(
        "run_sub_agent_storyboard", EXEC_SKILLS["storyboard_table"],
        "派发执行层：生成/重建分镜表与分镜面板（含图提示词润色），耗时约1-3分钟",
        _make_board, project_id, emit, result_hook=_persist_board_result)
    tools["run_sub_agent_storyboard_gen"] = _sub_agent_tool(
        "run_sub_agent_storyboard_gen", EXEC_SKILLS["storyboard_gen"],
        "派发执行层：批量生成分镜图（异步提交，用 get_production_status 轮询进度）",
        _make_board, project_id, emit)

    system = (
        common_skill_body(DECISION_SKILL)
        + "\n\n## 项目上下文（实时）\n" + json.dumps(summary, ensure_ascii=False)
        + "\n\n## 工作区约定\nget_flowData 的 key：script(剧本)/scriptPlan(拍摄计划)/"
          "assets(资产清单)/storyboardTable(分镜表)/storyboard(分镜面板)/novelEvents(小说事件)。"
          "生成类工具均为异步提交，用 get_production_status 轮询进度后再决策下一步。"
        + memory_block
    )
    memory.add("user", user_text)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_text},
    ]
    result = run_tool_loop(messages, tools, agent_key="productionAgent:decisionAgent",
                           max_steps=100, emit=emit)
    memory.add("assistant", result or "")
    return result

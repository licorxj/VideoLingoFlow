# -*- coding: utf-8 -*-
"""剧本 Agent（决策层 + 服务端工具）—— 移植源 scriptAgent，P3 简化版：

决策层（script_agent_decision.md）持有工具：
    import_novel(text)            导入并切分章节（按「第X章」标题行切分）
    generate_events()             事件提取（异步）
    get_novel_events()            读事件工作区
    make_script_draft()           事件 → 剧本草稿（同步单发，P3 后续升级为骨架/改编/剧本三子 Agent）
    extract_assets()              剧本资产提取（异步）
    get_status()                  进度统计
    run_supervision(phase)        监督层审核（script_agent_supervision.md）
"""
import json
import re

from backend.toonflow.agents.loop import run_tool_loop, Tool
from backend.toonflow.agents.memory import Memory
from backend.toonflow.agents.tools import build_supervision_tool, common_skill_body
from backend.toonflow.agents.workspace import project_summary

DECISION_SKILL = "script_agent_decision.md"
SUPERVISION_SKILL = "script_agent_supervision.md"


def _split_chapters(text: str) -> list[dict]:
    """按「第X章」标题行切分小说文本为章节列表。"""
    pattern = re.compile(r"^\s*(第[0-9一二三四五六七八九十百千零两]+章[^\n]*)$", re.M)
    matches = list(pattern.finditer(text))
    if not matches:
        return [{"reel": "", "chapter": "第1章", "chapterData": text.strip()}]
    chapters = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end():end].strip()
        if body:
            chapters.append({"reel": "", "chapter": m.group(1).strip()[:80], "chapterData": body})
    return chapters


def run_script_agent(project_id: int, user_text: str, emit=None) -> str:
    emit = emit or (lambda kind, payload: None)
    summary = project_summary(project_id)
    supervision = build_supervision_tool(project_id, SUPERVISION_SKILL)

    def import_novel(args):
        from backend.toonflow.pipeline import novel as pipe

        text = str(args.get("text") or "").strip()
        if not text:
            return {"error": "text 不能为空"}
        chapters = _split_chapters(text)
        ids = pipe.add_novel(project_id, chapters)
        pipe.generate_events(project_id, ids)
        return {"ok": True, "chapters": len(chapters), "eventsQueued": len(chapters)}

    def generate_events(args):
        from backend.toonflow.pipeline import novel as pipe

        return pipe.generate_events(project_id)

    def get_novel_events(args):
        from backend.toonflow.agents.workspace import get_flow_data

        return get_flow_data(project_id, "novelEvents") or "（还没有事件提取结果）"

    def make_script_draft(args):
        from backend.toonflow.pipeline import script as pipe

        title = str(args.get("title") or "Agent 剧本草稿")
        return pipe.generate_script_draft(project_id, title)

    def extract_assets(args):
        from sqlalchemy import select

        from backend.control_plane.database import session_scope
        from backend.toonflow.core.models import TfScript
        from backend.toonflow.pipeline import script as pipe

        with session_scope() as session:
            s = session.scalars(select(TfScript).where(
                TfScript.projectId == project_id).order_by(TfScript.id.desc())).first()
            if s is None:
                return {"error": "项目还没有剧本，请先 make_script_draft"}
            script_id = s.id
        return pipe.extract_assets(script_id)

    def get_status(args):
        from backend.toonflow.pipeline import novel as pipe_novel

        return {**project_summary(project_id)["stats"], **pipe_novel.event_state(project_id)}

    memory = Memory("scriptAgent", project_id)
    tools = {
        "import_novel": Tool("import_novel", "导入小说全文并自动切分章节、触发事件提取（异步）",
                             {"type": "object", "properties": {"text": {"type": "string"}},
                              "required": ["text"]}, import_novel),
        "generate_events": Tool("generate_events", "对未提取的章节触发事件提取（异步）", {}, [], generate_events),
        "get_novel_events": Tool("get_novel_events", "读取事件工作区（章节：事件 行列表）", {}, [], get_novel_events),
        "make_script_draft": Tool("make_script_draft", "按事件线生成剧本草稿（同步，约1-2分钟）",
                                  {"type": "object", "properties": {"title": {"type": "string"}}}, [], make_script_draft),
        "extract_assets": Tool("extract_assets", "从最新剧本提取角色/场景/道具资产（异步）", {}, [], extract_assets),
        "get_status": Tool("get_status", "查询各阶段进度统计", {}, [], get_status),
        supervision.name: supervision,
        memory.deep_retrieve_tool().name: memory.deep_retrieve_tool(),
    }

    mem = memory.get(user_text)
    mem_lines = []
    if mem["shortTerm"]:
        mem_lines.append("近期对话：\n" + "\n".join(
            f"{m['role']}: {m['content'][:200]}" for m in mem["shortTerm"]))
    if mem["summaries"]:
        mem_lines.append("历史摘要：\n" + "\n".join(f"- {s['content'][:200]}" for s in mem["summaries"]))
    memory_block = ("\n\n## 记忆（本项目历史会话）\n" + "\n\n".join(mem_lines)) if mem_lines else ""

    system = (
        common_skill_body(DECISION_SKILL)
        + "\n\n## 项目上下文（实时）\n" + json.dumps(summary, ensure_ascii=False)
        + "\n\n## 工作区约定\n事件提取为异步，import_novel/generate_events 后用 get_status 轮询；"
          "剧本草稿为同步调用。关键产出后调用 run_supervision 审核。"
        + memory_block
    )
    memory.add("user", user_text)
    result = run_tool_loop(
        [{"role": "system", "content": system}, {"role": "user", "content": user_text}],
        tools, agent_key="scriptAgent:decisionAgent", max_steps=60, emit=emit)
    memory.add("assistant", result or "")
    return result

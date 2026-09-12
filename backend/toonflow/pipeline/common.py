# -*- coding: utf-8 -*-
"""pipeline 公共工具：提示词模板读取 / 画风前缀 / JSON 解析容错。"""
import json
import re
from pathlib import Path

from sqlalchemy import select

from backend.toonflow.core.models import TfPrompt, TfProject

SKILLS_ROOT = Path(__file__).resolve().parents[1] / "skills"


def prompt_by_type(session, type_: str) -> str:
    """o_prompt 种子模板：useData 优先（对齐源 useData/data 语义）。"""
    row = session.scalars(select(TfPrompt).where(TfPrompt.type == type_)).first()
    if row is None:
        raise ValueError(f"提示词模板缺失: {type_}（请检查种子数据）")
    return row.effective()


def art_style_prefix(project: TfProject) -> str:
    """项目画风 → art_skills/<画风>/prefix.md 正文（源 getArtPrompt）。"""
    style = (project.artStyle or "").strip()
    if not style:
        return ""
    for candidate in (SKILLS_ROOT / "art_skills" / style / "prefix.md",
                      SKILLS_ROOT / "art_skills" / style / "art_prompt" / "prefix.md"):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip()
    return ""


def skill_body(filename: str) -> str:
    """读技能正文（剥离 frontmatter），作为 system 指令。"""
    p = SKILLS_ROOT / filename
    if not p.is_file():
        raise ValueError(f"技能文件缺失: {filename}")
    text = p.read_text(encoding="utf-8")
    return re.sub(r"^---\r?\n[\s\S]*?\r?\n---\r?\n?", "", text).strip()


def llm(prompt: str, *, system: str = "", json_mode: bool = True, project_id=None):
    from backend.toonflow.engines import Ai

    return Ai.text.invoke(prompt, system=system, json_mode=json_mode, project_id=project_id)


def parse_json(resp) -> dict:
    """LLM 返回 → dict（容错 markdown 代码块包裹）。"""
    if isinstance(resp, dict):
        return resp
    text = str(resp).strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\r?\n|\r?\n```$", "", text)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                data = json.loads(match.group(0))
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                pass
    return {}

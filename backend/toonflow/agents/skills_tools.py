# -*- coding: utf-8 -*-
"""Skill 加载器 —— 移植自 Toonflow `src/utils/agent/skillsTools.ts`，语义保持一致。

资产：backend/toonflow/skills/（源 data/skills 原样拷贝，文案零改动）
    - 主技能：skills/<attribution>.md（frontmatter 含 name/description）
    - 二级资源（workspace，非递归）：如 art_skills/<画风>/、story_skills/、production_skills/
    - 三级资源（attachedSkills，递归）：整库附带

用法（P3 Agent tool-loop 中作为两个工具的宿主）：
    bundle = use_skill({"mainSkill": ["production_agent_decision"],
                        "workspace": ["production_skills"],
                        "attachedSkills": ["art_skills/2D_90s_japanese_anime"]})
    bundle["prompt"]                     # 注入 system 的 <available_skills> 段
    bundle["activate_skill"]("name")     # → {"content": "<skill_content>..."}
    bundle["read_skill_file"]("path")    # → {"content": "<skill_content>..."}
"""
from __future__ import annotations

import re
from pathlib import Path

# 主技能归属（源 SkillAttribution 枚举，文件名即 skills/ 下的 md 文件名）
SKILL_ATTRIBUTIONS = (
    # 剧本Agent
    "script_agent_decision",        # 决策
    "script_execution_skeleton",    # 故事骨架
    "script_execution_adaptation",  # 改编策略
    "script_execution_script",      # 剧本生成
    "script_agent_supervision",     # 审核
    # 生产Agent
    "production_agent_decision",
    "production_agent_execution",
    "production_agent_supervision",
)

SKILLS_ROOT = Path(__file__).resolve().parents[1] / "skills"


def _to_unix(path_str: str) -> str:
    return path_str.replace("\\", "/")


def _ensure_non_empty_body(body: str, fallback: str) -> str:
    trimmed = body.strip()
    return trimmed if trimmed else fallback


def parse_frontmatter(content: str) -> dict:
    """解析 SKILL.md 的 frontmatter，取 name/description（与源实现同规则，含块标量）。"""
    match = re.match(r"^\uFEFF?---[ \t]*\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)", content)
    if not match:
        raise ValueError("技能文件缺少有效的 frontmatter，确保以 --- 包裹并包含 name 和 description 字段。")
    result: dict[str, str] = {}
    lines = match.group(1).splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#"):
            i += 1
            continue
        key_match = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", line)
        if not key_match:
            i += 1
            continue
        key = key_match.group(1).strip()
        raw_value = (key_match.group(2) or "").strip()
        i += 1
        if re.match(r"^[>|][+-]?[0-9]*$", raw_value):
            is_folded = raw_value.startswith(">")
            block_lines: list[str] = []
            block_indent: int | None = None
            while i < len(lines):
                current = lines[i]
                current_trimmed = current.strip()
                if current_trimmed == "":
                    if block_indent is not None:
                        block_lines.append("")
                    i += 1
                    continue
                current_indent = len(current) - len(current.lstrip())
                if block_indent is None:
                    block_indent = current_indent
                if current_indent < block_indent:
                    break
                block_lines.append(current[block_indent:])
                i += 1
            if is_folded:
                folded = "\n".join(block_lines)
                folded = re.sub(r"\n{2,}", "\n\n", folded)
                folded = re.sub(r"([^\n])\n([^\n])", r"\1 \2", folded)
                result[key] = folded.strip()
            else:
                result[key] = "\n".join(block_lines).strip()
            continue
        unquoted = re.sub(r"^(['\"])([\s\S]*)\1$", r"\2", raw_value)
        result[key] = unquoted
    if not result.get("name") or not result.get("description"):
        raise ValueError("技能文件缺少必要字段: name 或 description。")
    return {"name": result["name"], "description": result["description"]}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _safe_resolve(relative: str) -> Path | None:
    """路径穿越防护（对齐源 is-path-inside 语义）。"""
    root = SKILLS_ROOT.resolve()
    candidate = (root / relative).resolve()
    if candidate == root or root in candidate.parents:
        return candidate
    return None


def _collect_md_files(dirs: list[str], recursive: bool) -> list[str]:
    """收集目录下（可选递归）的 md 文件，返回相对 skills 根的 unix 路径。"""
    out: list[str] = []
    for d in dirs:
        safe = _safe_resolve(d)
        if safe is None or not safe.exists():
            continue
        pattern = "**/*.md" if recursive else "*.md"
        for p in sorted(safe.glob(pattern)):
            if p.is_file():
                out.append(_to_unix(str(p.relative_to(SKILLS_ROOT))))
    return out


def build_skill_prompt(skills: list[dict]) -> str:
    """构建 <available_skills> 注入段（原文照抄源实现）。"""
    entries = "\n".join(
        f'  <skill>\n    <name>{s["name"]}</name>\n    <description>{s["description"]}</description>\n  </skill>'
        for s in skills
    )
    return f"""## Skills
以下技能提供了专业任务的专用指令。
当任务与某个技能的描述匹配时，调用 activate_skill 工具并传入技能名称来加载完整指令。
加载后遵循技能指令执行任务，需要时调用 read_skill_file 读取资源文件内容。

<available_skills>
{entries}
</available_skills>"""


def _parse_main_skill(name: str, path: Path) -> dict:
    """主技能元信息：有 frontmatter 用之；没有（如决策层，整文件即指令）回退归属名。

    源系统的用法印证：决策层 skill 由 Agent 直接整文件读为 system prompt（不走
    parseFrontmatter），useSkill 只用于带 frontmatter 的执行层/监督层技能。
    """
    content = _read(path)
    try:
        parsed = parse_frontmatter(content)
    except ValueError:
        parsed = {"name": name, "description": ""}
    return {"path": _to_unix(str(path)), **parsed}


def use_skill(main_skill: list[str], workspace: list[str] | None = None,
              attached_skills: list[str] | None = None) -> dict:
    """装配一次 Agent 会话的技能包（对齐源 useSkill）。"""
    workspace = workspace or []
    attached_skills = attached_skills or []
    main_skills: list[dict] = []
    for name in main_skill:
        if name not in SKILL_ATTRIBUTIONS:
            raise ValueError(f"未知主技能归属: {name}（可选 {SKILL_ATTRIBUTIONS}）")
        skill_path = SKILLS_ROOT / f"{name}.md"
        if not skill_path.is_file():
            raise FileNotFoundError(f"主技能文件不存在: {skill_path}")
        main_skills.append(_parse_main_skill(name, skill_path))

    skill_paths = {
        "mainSkill": main_skills,
        "secondarySkills": _collect_md_files(workspace, recursive=False),
        "tertiarySkills": _collect_md_files(attached_skills, recursive=True),
    }
    return {
        "prompt": build_skill_prompt(main_skills),
        "skillPaths": skill_paths,
        "activate_skill": _make_activate(main_skills, skill_paths),
        "read_skill_file": _make_read_file(skill_paths),
    }


def _make_activate(main_skills: list[dict], skill_paths: dict):
    """activate_skill 工具：把技能正文包 <skill_content> 注入（防重复加载）。"""
    activated: set[str] = set()
    skill_map = {s["name"]: s for s in main_skills}

    def activate_skill(name: str) -> dict:
        if name in activated:
            return {"alreadyActive": True, "message": f'技能 "{name}" 已激活，无需重复加载'}
        matched = skill_map.get(name)
        if not matched:
            return {"error": f'未找到技能 "{name}"'}
        raw = _read(Path(matched["path"]))
        activated.add(name)
        body = _ensure_non_empty_body(
            re.sub(r"^---\r?\n[\s\S]*?\r?\n---\r?\n?", "", raw), "该技能文件无正文内容。")
        content = f'<skill_content name="{name}">\n{body}\n\n使用 read_skill_file 工具读取资源文件。\n'
        if skill_paths["secondarySkills"]:
            content += "\n<skill_resources>\n"
            for p in skill_paths["secondarySkills"]:
                content += f"  <file>{p}</file>\n"
            content += "</skill_resources>\n"
        content += "</skill_content>"
        return {"content": content}

    return activate_skill


def _make_read_file(skill_paths: dict):
    """read_skill_file 工具：读取技能目录下的资源文件（含路径穿越防护）。"""

    def read_skill_file(file_path: str) -> dict:
        normalized = _to_unix((file_path or "").strip())
        if not normalized:
            return {"error": "filePath 不能为空"}
        full = _safe_resolve(normalized)
        if full is None:
            return {"error": "Access denied: path is outside skill directory"}
        if not full.is_file():
            return {"error": f"File not found: {file_path}"}
        body = _ensure_non_empty_body(_read(full), "该资源文件为空。")
        content = f"<skill_content>\n{body}\n\n可以使用 read_skill_file 工具读取资源文件。\n"
        if skill_paths["tertiarySkills"]:
            content += "\n<skill_resources>\n"
            for p in skill_paths["tertiarySkills"]:
                content += f"  <file>{p}</file>\n"
            content += "</skill_resources>\n"
        content += "</skill_content>"
        return {"content": content}

    return read_skill_file


def list_skills() -> list[dict]:
    """枚举全部主技能与资源库（供前端/设置页展示）。"""
    out = []
    for name in SKILL_ATTRIBUTIONS:
        p = SKILLS_ROOT / f"{name}.md"
        if not p.is_file():
            continue
        meta = _parse_main_skill(name, p)
        out.append({"attribution": name, "file": p.name, **meta})
    return out


def list_skill_libraries() -> list[dict]:
    """枚举资源库目录（art_skills/story_skills/production_skills 及其子库）。"""
    out = []
    if not SKILLS_ROOT.is_dir():
        return out
    for child in sorted(SKILLS_ROOT.iterdir()):
        if child.is_dir():
            out.append({"dir": child.name, "mdFiles": len(list(child.glob("**/*.md"))),
                        "children": sorted(c.name for c in child.iterdir() if c.is_dir())})
    return out

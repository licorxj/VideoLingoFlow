# -*- coding: utf-8 -*-
"""小说阶段：章节导入 / 事件提取（eventExtraction 模板，单行 | 分隔 7 字段）。"""
import re

from sqlalchemy import select

from backend.toonflow.pipeline import common, submit
from backend.toonflow.core.models import TfNovel


def add_novel(project_id: int, chapters: list[dict]) -> list[int]:
    """导入章节：[{reel, chapter, chapterData}]，返回 id 列表。"""
    from backend.control_plane.database import session_scope

    ids = []
    with session_scope() as session:
        for ch in chapters:
            row = TfNovel(
                projectId=project_id,
                reel=str(ch.get("reel") or ""),
                chapter=str(ch.get("chapter") or ""),
                chapterData=str(ch.get("chapterData") or ""),
            )
            session.add(row)
            session.flush()
            ids.append(row.id)
    return ids


def _validate_event(text: str) -> str | None:
    """校验事件行：以 | 开头结尾、恰好 7 字段。合法返回清洗后文本。"""
    line = (text or "").strip().strip("`")
    line = line.strip()
    if not (line.startswith("|") and line.endswith("|")):
        return None
    body = line[1:-1]
    fields = [f.strip() for f in body.split("|")]
    if len(fields) != 7 or any(not f for f in fields):
        return None
    return line


def _extract_one(novel_id: int) -> None:
    from backend.control_plane.database import session_scope

    with session_scope() as session:
        row = session.get(TfNovel, novel_id)
        if row is None:
            return
        project_id = row.projectId
        chapter_text = row.chapterData or ""
        template = common.prompt_by_type(session, "eventExtraction")
        row.eventState = 2  # 提取中（前端轮询依赖该状态；对齐 script.extractState 语义）

    system = template
    prompt = f"请提取以下章节的事件信息：\n\n{chapter_text}"
    event_line = None
    for _ in range(2):  # 源实现同样允许一次重试
        resp = common.llm(prompt, system=system, json_mode=False, project_id=project_id)
        event_line = _validate_event(str(resp))
        if event_line:
            break
        prompt = f"上次输出不符合格式（必须是一行，以|开头结尾、恰好7个字段）。请重新提取：\n\n{chapter_text}"

    with session_scope() as session:
        row = session.get(TfNovel, novel_id)
        if row is None:
            return
        row.event = event_line or ""
        row.eventState = 1 if event_line else -1


def generate_events(project_id: int, novel_ids: list[int] | None = None) -> dict:
    """触发事件提取（异步）。返回 {queued: n}。"""
    from backend.control_plane.database import session_scope

    with session_scope() as session:
        stmt = select(TfNovel).where(TfNovel.projectId == project_id)
        if novel_ids:
            stmt = stmt.where(TfNovel.id.in_([int(i) for i in novel_ids]))
        targets = [r.id for r in session.scalars(stmt).all() if (r.chapterData or "").strip()]
        # 立即置为"提取中"：前端靠 eventState===2 启动轮询，缺了它 UI 会一直停在"未提取"
        for r in session.scalars(select(TfNovel).where(
                TfNovel.id.in_([int(i) for i in targets]))).all() if targets else []:
            r.eventState = 2

    for nid in targets:
        submit(_extract_one, nid)
    return {"queued": len(targets)}


def extract_event_single(novel_id: int) -> dict:
    """重新提取单个章节的事件（画布章节卡片「重新提取」用，异步）。"""
    submit(_extract_one, int(novel_id))
    return {"queued": 1}


def event_state(project_id: int) -> dict:
    """轮询：{total, done, failed, pending, events: [{id, chapter, event}]}。"""
    from backend.control_plane.database import session_scope

    with session_scope() as session:
        rows = session.scalars(select(TfNovel).where(TfNovel.projectId == project_id)).all()
        events = [{"id": r.id, "chapter": r.chapter, "event": r.event,
                   "state": r.eventState} for r in rows]
    done = sum(1 for e in events if e["state"] == 1)
    failed = sum(1 for e in events if e["state"] == -1)
    return {"total": len(events), "done": done, "failed": failed,
            "pending": len(events) - done - failed, "events": events}

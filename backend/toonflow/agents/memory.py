# -*- coding: utf-8 -*-
"""Agent 向量化记忆 —— 逐行为移植源 utils/agent/memory.ts。

隔离：isolationKey = f"{agentType}:{projectId}"（分项目存取，查询只扫本项目行）。
机制：
    add(role, content)        每条消息向量化入库；未摘要消息累积到 messagesPerSummary(3) 条时
                              由 LLM 压缩为 ≤500 字摘要入库并标记原文已摘要（摘要失败降级为截断拼接）
    get(text)                 {shortTerm 最近5条未摘要 / summaries 最近10条 / rag 向量 top-3}
    deep_retrieve(keyword)    向量召回 top-5 摘要 → LLM 判断相关性 → 展开原始消息
阈值可经 tf_settings 覆盖（key 与源 o_setting 相同）。
"""
import json
import uuid

from sqlalchemy import select

from backend.toonflow.agents.embedding import cosine_similarity, get_embedding
from backend.toonflow.agents.loop import Tool
from backend.toonflow.core.models import TfMemory, TfSetting

DEFAULTS = {
    "messagesPerSummary": 3,
    "summaryMaxLength": 500,
    "shortTermLimit": 5,
    "summaryLimit": 10,
    "ragLimit": 3,
    "deepRetrieveSummaryLimit": 5,
}


class Memory:
    def __init__(self, agent_type: str, project_id: int):
        self.agent_type = agent_type
        self.isolation_key = f"{agent_type}:{project_id}"
        self.project_id = project_id

    # ---------------- 配置 ----------------
    def _config(self, keys: list[str]) -> dict:
        from backend.control_plane.database import session_scope

        out = {k: DEFAULTS[k] for k in keys}
        try:
            with session_scope() as session:
                rows = session.scalars(select(TfSetting).where(
                    TfSetting.key.in_([f"memory:{k}" for k in keys]))).all()
                for row in rows:
                    name = row.key.split(":", 1)[1]
                    if name in out:
                        try:
                            out[name] = int(row.value)
                        except (TypeError, ValueError):
                            pass
        except Exception:  # noqa: BLE001
            pass
        return out

    # ---------------- 写入 ----------------
    def _summary(self, contents: list[str], max_len: int) -> str:
        """LLM 压缩摘要；LLM 不可用时降级为截断拼接（保证记忆不丢）。"""
        numbered = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(contents))
        try:
            from backend.toonflow.engines import Ai

            text = str(Ai.text.invoke(
                numbered,
                system=f"你是一个记忆压缩助手。请将以下多条记忆内容压缩为一段简洁的摘要，"
                       f"不超过{max_len}个字符。只输出摘要内容，不要加任何前缀或解释。",
                json_mode=False, project_id=self.project_id)).strip()
            if text:
                return text[:max_len]
        except Exception:  # noqa: BLE001
            pass
        return ("；".join(c.replace("\n", " ")[:80] for c in contents))[:max_len]

    def add(self, role: str, content: str) -> None:
        cfg = self._config(["messagesPerSummary", "summaryMaxLength"])
        content = (content or "").strip()
        if not content:
            return
        from backend.control_plane.database import session_scope

        with session_scope() as session:
            session.add(TfMemory(
                id=uuid.uuid4().hex, isolationKey=self.isolation_key, type="message",
                role=role, content=content[:4000],
                embedding=json.dumps(get_embedding(content)),
                createTime=int(__import__("time").time() * 1000),
            ))
            unsummarized = session.scalars(select(TfMemory).where(
                TfMemory.isolationKey == self.isolation_key,
                TfMemory.type == "message", TfMemory.summarized == 0,
            ).order_by(TfMemory.createTime)).all()

        per = int(cfg["messagesPerSummary"])
        if len(unsummarized) < per:
            return
        batch = unsummarized[:per]
        batch_ids = [m.id for m in batch]
        summary = self._summary([m.content for m in batch], int(cfg["summaryMaxLength"]))
        with session_scope() as session:
            session.add(TfMemory(
                id=uuid.uuid4().hex, isolationKey=self.isolation_key, type="summary",
                content=summary, embedding=json.dumps(get_embedding(summary)),
                relatedMessageIds=json.dumps(batch_ids),
                createTime=int(__import__("time").time() * 1000),
            ))
            for m in session.scalars(select(TfMemory).where(TfMemory.id.in_(batch_ids))).all():
                m.summarized = 1

    # ---------------- 读取 ----------------
    @staticmethod
    def _vector_search(rows: list[TfMemory], query_embedding: list[float], limit: int) -> list[dict]:
        scored = []
        for row in rows:
            try:
                emb = json.loads(row.embedding or "[]")
            except json.JSONDecodeError:
                emb = []
            scored.append({"id": row.id, "content": row.content,
                           "similarity": cosine_similarity(query_embedding, emb)})
        scored.sort(key=lambda x: x["similarity"], reverse=True)
        return scored[:limit]

    def get(self, text: str) -> dict:
        cfg = self._config(["shortTermLimit", "summaryLimit", "ragLimit"])
        from backend.control_plane.database import session_scope

        with session_scope() as session:
            short = session.scalars(select(TfMemory).where(
                TfMemory.isolationKey == self.isolation_key,
                TfMemory.type == "message", TfMemory.summarized == 0,
            ).order_by(TfMemory.createTime.desc()).limit(int(cfg["shortTermLimit"]))).all()
            summaries = session.scalars(select(TfMemory).where(
                TfMemory.isolationKey == self.isolation_key,
                TfMemory.type == "summary",
            ).order_by(TfMemory.createTime.desc()).limit(int(cfg["summaryLimit"]))).all()
            all_messages = session.scalars(select(TfMemory).where(
                TfMemory.isolationKey == self.isolation_key, TfMemory.type == "message")).all()

        short = list(reversed(short))
        summaries = list(reversed(summaries))
        rag = self._vector_search(list(all_messages), get_embedding(text), int(cfg["ragLimit"]))
        return {
            "shortTerm": [{"role": m.role, "content": m.content} for m in short],
            "summaries": [{"id": s.id, "content": s.content} for s in summaries],
            "rag": rag,
        }

    def deep_retrieve(self, keyword: str) -> list[dict]:
        """向量召回摘要 → LLM 判相关性 → 展开原始消息（对齐源 deepRetrieve）。"""
        cfg = self._config(["deepRetrieveSummaryLimit"])
        from backend.control_plane.database import session_scope

        with session_scope() as session:
            all_summaries = session.scalars(select(TfMemory).where(
                TfMemory.isolationKey == self.isolation_key, TfMemory.type == "summary")).all()
        top = self._vector_search(list(all_summaries), get_embedding(keyword),
                                  int(cfg["deepRetrieveSummaryLimit"]))
        if not top:
            return []
        try:
            from backend.toonflow.engines import Ai

            listing = "\n".join(f"[{s['id']}] {s['content']}" for s in top)
            text = str(Ai.text.invoke(
                f"关键词: {keyword}\n\n摘要列表:\n{listing}",
                system='你是一个信息检索助手。判断哪些摘要与关键词相关，只返回相关摘要的id列表，'
                       '用JSON数组格式，例如 ["id1","id2"]。不要解释。',
                json_mode=True, project_id=self.project_id))
            relevant = json.loads(str(text)) if isinstance(text, str) else text
            relevant = [str(x) for x in relevant] if isinstance(relevant, list) else []
        except Exception:  # noqa: BLE001
            relevant = [s["id"] for s in top]  # 判定失败时退化为全部召回
        if not relevant:
            return []
        ids = []
        for s in top:
            if s["id"] in relevant:
                row = next((x for x in all_summaries if x.id == s["id"]), None)
                if row:
                    ids.extend(json.loads(row.relatedMessageIds or "[]"))
        if not ids:
            return []
        with session_scope() as session:
            rows = session.scalars(select(TfMemory).where(
                TfMemory.id.in_(ids)).order_by(TfMemory.createTime)).all()
            return [{"id": m.id, "content": m.content} for m in rows]

    def deep_retrieve_tool(self) -> Tool:
        return Tool(
            "deep_retrieve", "深度检索记忆：当需要回忆与某个关键词相关的详细历史信息时使用",
            {"type": "object", "properties": {"keyword": {"type": "string"}},
             "required": ["keyword"]},
            lambda args: (lambda r: {"found": bool(r), "memories": [m["content"] for m in r]})
            (self.deep_retrieve(str(args.get("keyword") or ""))),
        )

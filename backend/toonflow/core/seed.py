# -*- coding: utf-8 -*-
"""Toonflow 种子数据：建表 + 提示词/Agent 映射 种子（源自 initDB.ts，原文零改动）。

种子文件：
    core/prompt_seed.json        源 o_prompt 四大模板（事件提取/剧本资产提取/视频提示词生成/音色绑定）
    core/agent_deploy_seed.json  源 o_agentDeploy 的 17 个 Agent 能力槽位
技能/画风/题材资产在 skills/ 目录，由 agents.skills_tools 运行时加载，不进种子。
"""
import json
from pathlib import Path

from sqlalchemy import select

from backend.toonflow.core.models import TfAgentDeploy, TfPrompt, TfBase

_SEED_DIR = Path(__file__).resolve().parent
_seeded = False


def ensure_tables() -> None:
    """幂等建表（开发便利；正式环境走 alembic 20260910_05_toonflow_core）。"""
    from backend.control_plane.database import get_engine

    TfBase.metadata.create_all(bind=get_engine(), tables=[
        t for t in TfBase.metadata.sorted_tables
    ])
    _ensure_columns()


# 增量列：create_all 不会 ALTER 已存在的表，故按 PRAGMA 检查后补列（幂等）
_INCREMENTAL_COLUMNS = {
    "tf_projects": {"videoResolution": "TEXT NOT NULL DEFAULT '720P'"},
}


def _ensure_columns() -> None:
    """为已存在的旧表补齐新增列（SQLite 为主；其它方言按 inspector 判断）。"""
    try:
        from sqlalchemy import inspect, text

        from backend.control_plane.database import get_engine

        engine = get_engine()
        insp = inspect(engine)
        for table, columns in _INCREMENTAL_COLUMNS.items():
            if not insp.has_table(table):
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            with engine.begin() as conn:
                for col, ddl in columns.items():
                    if col not in existing:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                        print(f"[toonflow:seed] added column {table}.{col}")
    except Exception as exc:  # noqa: BLE001
        print(f"[toonflow:seed] ensure_columns skipped: {exc}")


def _upsert_prompts(session) -> int:
    seed = json.loads((_SEED_DIR / "prompt_seed.json").read_text(encoding="utf-8"))
    existing = {p.type: p for p in session.scalars(select(TfPrompt)).all()}
    count = 0
    for item in seed:
        row = existing.get(item["type"])
        if row is None:
            session.add(TfPrompt(name=item["name"], type=item["type"], data=item["data"]))
            count += 1
        elif not row.data:
            row.data = item["data"]
            count += 1
    return count


def _upsert_agents(session) -> int:
    seed = json.loads((_SEED_DIR / "agent_deploy_seed.json").read_text(encoding="utf-8"))
    existing = {a.key: a for a in session.scalars(select(TfAgentDeploy)).all()}
    count = 0
    for item in seed:
        row = existing.get(item["key"])
        if row is None:
            session.add(TfAgentDeploy(
                key=item["key"], name=item.get("name") or "", desc=item.get("desc") or "",
                temperature=int(item.get("temperature") or 1),
                maxOutputTokens=int(item.get("maxOutputTokens") or 0),
                disabled=bool(item.get("disabled")),
            ))
            count += 1
    return count


def ensure_seeded() -> None:
    """幂等种子：只在缺失时插入，不覆盖用户改动。"""
    global _seeded
    if _seeded:
        return
    from backend.control_plane.database import session_scope

    ensure_tables()
    with session_scope() as session:
        n1 = _upsert_prompts(session)
        n2 = _upsert_agents(session)
        if n1 or n2:
            print(f"[toonflow] seeded: +{n1} prompts, +{n2} agent slots")
    _seeded = True

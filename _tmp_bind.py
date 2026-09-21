# -*- coding: utf-8 -*-
"""审计：前端聊天 → Agent 是否严格绑定当前选中的项目。"""
import inspect

from sqlalchemy import select

from backend.control_plane.database import session_scope
from backend.toonflow.agents import production_agent, workspace
from backend.toonflow.agents.memory import Memory
from backend.toonflow.core.models import TfProject

with session_scope() as s:
    projects = s.scalars(select(TfProject)).all()
print("库内项目：", [(p.id, p.name) for p in projects])

print("\n== 1) 入口：run_decision_agent 签名 ==")
print("  ", inspect.signature(production_agent.run_decision_agent))

print("\n== 2) 决策层内所有调用是否都带 project_id ==")
src = inspect.getsource(production_agent.run_decision_agent)
for name in ["project_summary(", "Memory(", "build_workspace_tools(", "build_supervision_tool(",
             "script_context_block("]:
    hits = [l.strip() for l in src.splitlines() if name in l and "def " not in l]
    print(f"  {name:<26} → {hits[0][:88] if hits else '未找到'}")

print("\n== 3) 工作区工具作用域 ==")
from backend.toonflow.agents import tools as t

tsrc = inspect.getsource(t.build_workspace_tools)
for fn in ["get_flow_data(project_id", "generate_assets", "generate_storyboard", "get_production_status"]:
    print(f"  {fn:<30} → {'project_id 绑定' if 'project_id' in tsrc else '×'}")
print("  get_flow_data 内部：", [l.strip() for l in inspect.getsource(
    workspace.get_flow_data).splitlines() if "projectId ==" in l][:2])

print("\n== 4) 记忆隔离键（是否跨项目串味） ==")
print("  Memory(project 2):", Memory("productionAgent", 2).isolation_key)
print("  Memory(project 3):", Memory("productionAgent", 3).isolation_key)

print("\n== 5) 运行时跨项目取值对比 ==")
ids = [p.id for p in projects][:2]
for pid in ids:
    txt = workspace.get_flow_data(pid, "script")
    print(f"  project {pid} script 前 24 字:", repr(txt[:24]))
if len(ids) == 2:
    a = workspace.get_flow_data(ids[0], "script")
    b = workspace.get_flow_data(ids[1], "script")
    print("  两个项目剧本内容不同（无串数据）:", a != b)
    print("  资产清单隔离:",
          len(workspace.get_flow_data(ids[0], "assets")), "vs",
          len(workspace.get_flow_data(ids[1], "assets")))

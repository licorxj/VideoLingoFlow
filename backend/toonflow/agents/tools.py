# -*- coding: utf-8 -*-
"""Agent 服务端工具集 —— 源 productionAgent/tools.ts 的服务端化版本。

源系统里工具经 socket 回调"前端执行器"完成，本项目改为直接调 pipeline 服务层：
写库类工具同步完成；生成类工具提交后台并配合 get_production_status 轮询。
另附技能工具（activate_skill/read_skill_file）与监督工具。
"""
import json
from typing import Callable

from sqlalchemy import select

from backend.toonflow.agents import skills_tools
from backend.toonflow.agents.loop import Tool
from backend.toonflow.pipeline import assets as pipe_assets
from backend.toonflow.pipeline import storyboard as pipe_board
from backend.toonflow.pipeline import videos as pipe_videos
from backend.toonflow.pipeline import dubbing as pipe_dub
from backend.toonflow.pipeline import script as pipe_script


def _tool(name: str, description: str, properties: dict, required: list[str],
          execute: Callable[[dict], object]) -> Tool:
    return Tool(name, description,
                {"type": "object", "properties": properties, "required": required}, execute)


def _ids(args: dict) -> list[int]:
    return [int(x) for x in (args.get("ids") or [])]


def build_workspace_tools(project_id: int) -> dict[str, Tool]:
    """工作区读写 + 流水线触发/状态 工具（制作 Agent 通用）。"""
    tools: dict[str, Tool] = {}

    def get_flow_data(args):
        from backend.toonflow.agents.workspace import get_flow_data

        key = str(args.get("key") or "")
        value = get_flow_data(project_id, key)
        return value if isinstance(value, str) else value

    tools["get_flowData"] = _tool(
        "get_flowData", "获取工作区数据。key 可选：script(剧本，当前对话剧本)/script:<剧本id>(指定剧本)/"
        "scriptPlan(拍摄计划)/assets(资产清单)/storyboardTable(分镜表)/storyboard(分镜面板)/novelEvents(小说事件)",
        {"key": {"type": "string"}}, ["key"], get_flow_data)

    def add_derive_asset(args):
        from backend.control_plane.database import session_scope
        from backend.toonflow.core.models import TfAsset, TfScriptAsset

        parent_id = int(args["assetsId"])
        derive_id = args.get("id")
        name = str(args.get("name") or "").strip()
        if not name:
            return {"error": "name 不能为空"}
        with session_scope() as session:
            parent = session.get(TfAsset, parent_id)
            if parent is None:
                return {"error": f"父资产不存在: {parent_id}"}
            if derive_id:
                row = session.get(TfAsset, int(derive_id))
                if row is None or row.assetsId != parent_id:
                    return {"error": f"衍生资产不存在或不属于父资产: {derive_id}"}
                row.name, row.describe = name, str(args.get("desc") or "")
                return {"ok": True, "id": row.id, "updated": True}
            row = TfAsset(projectId=parent.projectId, assetsId=parent_id, name=name,
                          type=parent.type, describe=str(args.get("desc") or ""))
            session.add(row)
            session.flush()
            latest = session.scalars(select(TfScript.id).where(
                TfScript.projectId == parent.projectId).order_by(TfScript.id.desc())).first()
            if latest:
                session.add(TfScriptAsset(scriptId=latest, assetId=row.id))
            return {"ok": True, "id": row.id, "created": True}

    tools["add_derive_asset"] = _tool(
        "add_derive_asset", "新增或更新衍生资产（如角色的多形态/多装扮）。assetsId=父资产ID；"
        "id 为空表示新增，否则更新该衍生资产",
        {"assetsId": {"type": "integer"}, "id": {"type": ["integer", "null"]},
         "name": {"type": "string"}, "desc": {"type": "string"}},
        ["assetsId", "name", "desc"], add_derive_asset)

    def del_derive_asset(args):
        from backend.control_plane.database import session_scope
        from backend.toonflow.core.models import TfAsset

        aid = int(args["id"])
        with session_scope() as session:
            row = session.get(TfAsset, aid)
            if row is None or row.assetsId is None:
                return {"error": f"衍生资产不存在或不是衍生资产: {aid}"}
            session.delete(row)
        return {"ok": True, "deleted": aid}

    tools["del_derive_asset"] = _tool(
        "del_derive_asset", "删除衍生资产", {"id": {"type": "integer"}}, ["id"], del_derive_asset)

    def generate_assets(args):
        ids = _ids(args)
        if not ids:
            ids = [a["id"] for a in pipe_assets.list_asset_ids_without_image(project_id)]
        return pipe_assets.generate_asset_images(ids)

    tools["generate_assets"] = _tool(
        "generate_assets", "为资产生成图片（异步）。ids 为空时自动补齐所有还没有图的资产",
        {"ids": {"type": "array", "items": {"type": "integer"}}}, [], generate_assets)

    def generate_storyboard(args):
        """触发分镜表+面板（同步执行：单次 LLM 调用，结果直接可查）。"""
        script_id = args.get("scriptId")
        if not script_id:
            from backend.control_plane.database import session_scope
            from backend.toonflow.core.models import TfScript

            with session_scope() as session:
                s = session.scalars(select(TfScript).where(
                    TfScript.projectId == project_id).order_by(TfScript.id.desc())).first()
                script_id = s.id if s else None
        if not script_id:
            return {"error": "项目还没有剧本"}
        pipe_board.generate_storyboard_table_sync(project_id, int(script_id))
        pipe_board.polish_storyboard_prompts_sync(project_id)
        from backend.toonflow.agents.workspace import get_flow_data

        return {"ok": True, "storyboardTable": get_flow_data(project_id, "storyboardTable")}

    tools["generate_storyboard"] = _tool(
        "generate_storyboard", "生成/重建分镜表与分镜面板（同步，耗时约1-3分钟）。"
        "scriptId 省略时用项目最新剧本",
        {"scriptId": {"type": "integer"}}, [], generate_storyboard)

    def generate_storyboard_images(args):
        return pipe_board.generate_storyboard_images(project_id, _ids(args) or None)

    tools["generate_storyboard_images"] = _tool(
        "generate_storyboard_images", "批量生成分镜图（异步）。ids 为空时补齐所有缺图分镜",
        {"ids": {"type": "array", "items": {"type": "integer"}}}, [], generate_storyboard_images)

    def generate_video_prompts(args):
        return pipe_videos.generate_video_prompts(project_id, _ids(args) or None)

    tools["generate_video_prompts"] = _tool(
        "generate_video_prompts", "为分镜生成视频提示词（异步）。ids 为空时处理全部分镜",
        {"ids": {"type": "array", "items": {"type": "integer"}}}, [], generate_video_prompts)

    def generate_videos(args):
        return pipe_videos.generate_videos(project_id, _ids(args) or None,
                                           force=bool(args.get("force")))

    tools["generate_videos"] = _tool(
        "generate_videos", "为分镜生成视频（异步，需要已有视频提示词）。force=true 强制重跑",
        {"ids": {"type": "array", "items": {"type": "integer"}}, "force": {"type": "boolean"}},
        [], generate_videos)

    def bind_audios(args):
        return pipe_dub.bind_character_audios(project_id)

    tools["bind_audios"] = _tool(
        "bind_audios", "从配音谷音色库为角色匹配音色（异步）", {}, [], bind_audios)

    def get_production_status(args):
        from backend.toonflow.agents.workspace import project_summary

        return project_summary(project_id)["stats"]

    tools["get_production_status"] = _tool(
        "get_production_status", "查询制作进度统计（资产/分镜/提示词/图片/视频各阶段完成数）",
        {}, [], get_production_status)

    return tools


def build_skill_tools(main_skill: str, workspace_dirs: list[str] | None = None) -> tuple[dict[str, Tool], dict]:
    """技能装配工具（activate_skill / read_skill_file），对齐源 skillsTools。

    返回 (工具字典, 技能包 bundle)；bundle["prompt"] 用于拼装 system。
    """
    bundle = skills_tools.use_skill([main_skill], workspace=workspace_dirs or [])
    tools: dict[str, Tool] = {}
    tools["activate_skill"] = Tool(
        "activate_skill", f"激活技能加载完整指令。可用技能：{main_skill}",
        {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        lambda args: bundle["activate_skill"](str(args.get("name") or "")))
    tools["read_skill_file"] = Tool(
        "read_skill_file", "读取技能资源文件（相对 skills 目录路径）",
        {"type": "object", "properties": {"filePath": {"type": "string"}}, "required": ["filePath"]},
        lambda args: bundle["read_skill_file"](str(args.get("filePath") or "")))
    return tools, bundle


def build_supervision_tool(project_id: int, skill_file: str) -> Tool:
    """监督 QC 工具：把当前工作区摘要交给监督层 Agent 审核，返回审核意见。"""
    def run_supervision(args):
        from backend.toonflow.agents.workspace import project_summary, get_flow_data

        phase = str(args.get("phase") or "")
        focus = str(args.get("focus") or "")
        summary = project_summary(project_id)
        detail = {k: get_flow_data(project_id, k) for k in ("assets", "storyboardTable")}
        system = common_skill_body(skill_file)
        prompt = (f"阶段：{phase}\n项目：{json.dumps(summary, ensure_ascii=False)}\n"
                  f"关注点：{focus or '按审核规则全面检查'}\n"
                  f"工作区数据：{json.dumps(detail, ensure_ascii=False)[:24000]}\n"
                  "请给出审核意见（问题清单+修改建议+是否可放行）。")
        from backend.toonflow.engines import Ai

        return Ai.text.invoke(prompt, system=system, json_mode=False, project_id=project_id)

    return Tool("run_supervision", "调用监督层 Agent 按质检规则审核当前阶段产出",
                {"type": "object", "properties": {"phase": {"type": "string"},
                                                  "focus": {"type": "string"}},
                "required": ["phase"]}, run_supervision)


def common_skill_body(filename: str) -> str:
    from backend.toonflow.pipeline.common import skill_body

    return skill_body(filename)

"""AI剪辑链（OpenChatCut / 剪辑台）节点 —— 分组 ``ai_desk``。

面向**通用剪辑任务**（不限漫剧/AIGC 项目）：四个节点覆盖
「新建工程 → 素材进场 → 编排剪辑 → 渲染导出」整条链路，全部经官方 ``occ`` CLI
无头执行（不需要打开剪辑台页面）。节点之间以 **剪辑台项目 ID** 串联：
每个节点都有 ``project`` 输入/输出端口，把项目 ID 一路传到底。

    desk_project   新建剪辑工程（occ project new，输出新项目 ID）
    desk_material  素材导入 + 上轨（import_asset(s)/import_folder → edit_item adds）
    desk_edit      剪辑编排（AI 语义剪辑 read_script→LLM→apply_script + ops 批量工具调用）
    desk_export    渲染导出（occ render 无头出片 / export jianying 剪映草稿）

无人值守约束（OpenChatCut 侧设计）：
- 只覆盖 headless 工具；分析类（静音/beat/场景检测）、生成类（submit_*）、
  上传/网络/视觉检查需打开剪辑台页面；
- 同一项目同一时刻只允许一个 owner，**必须串行**；
- 默认 dry_run=True：先演练，确认无误再正式执行。
"""
from __future__ import annotations

import json
import os

from backend.steps.base_step import BaseStep, step_check_cancel
from backend import openchatcut_client as occ

_PREFIX = "desk"


# --------------------------------------------------------------------------- #
# 通用工具
# --------------------------------------------------------------------------- #
def _cfg(step) -> dict:
    return getattr(step, "_node_config", {}) or {}


def _inputs(step) -> dict:
    return getattr(step, "_step_inputs", {}) or {}


def _node_id(step) -> str:
    return getattr(step, "_node_id", "unknown")


def _cache_path(task_dir: str, node_id: str, prefix: str) -> str:
    cache = os.path.join(task_dir, "cache")
    os.makedirs(cache, exist_ok=True)
    return os.path.join(cache, f"agi_{prefix}_{node_id}.json")


def _write_cache(task_dir: str, node_id: str, prefix: str, data: dict) -> str:
    p = _cache_path(task_dir, node_id, prefix)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return os.path.relpath(p, task_dir)


def _parse_json_list(value) -> list:
    """把端口/配置值解析为字符串列表：支持 list、JSON 数组、换行/逗号分隔。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        out: list = []
        for item in value:
            out.extend(_parse_json_list(item))
        return out
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [str(x) for x in data if str(x).strip()]
        except (ValueError, TypeError):
            pass
    parts = [p.strip() for p in text.replace("\r", "\n").split("\n")]
    if len(parts) == 1:
        parts = [p.strip() for p in text.split(",")]
    return [p for p in parts if p]


def _resolve_file(value, task_dir: str = ""):
    if not value or not isinstance(value, str):
        return None
    v = value.strip()
    cands = [v]
    if task_dir:
        cands.append(os.path.join(task_dir, v))
        cands.append(os.path.join(task_dir, "output", os.path.basename(v)))
    for c in cands:
        if os.path.isfile(c):
            return os.path.abspath(c)
    return None


# 剪辑台 CLI 常见失败原因 → 可操作提示（原文已透传，这里补一句怎么办）
_FAILURE_HINTS = (
    ("no video clips", "剪映/成片导出要求时间线视频轨上有真实片段（图片轨、纯音频不算），请先把素材放到视频轨"),
    ("media files not found", "有素材未落在本地，请先在剪辑台打开该项目完成媒体本地化，或检查「AI剪辑台 → 媒体目录」配置"),
    ("does not exist or is invalid", "项目不存在或已损坏：请重新选择剪辑台项目"),
    ("already has an active", "该项目正被剪辑台页面或另一个任务占用（同一时刻只允许一个 owner），请关闭编辑器页面或稍后重试"),
    ("requires the browser editor", "该能力需要打开剪辑台编辑器页面才能使用，无人值守下不可用"),
    ("not found", "未找到目标（项目/素材/模板/片段），请检查 ID 或名称是否正确"),
)


def _hint_for(message: str) -> str:
    low = (message or "").lower()
    for needle, hint in _FAILURE_HINTS:
        if needle in low:
            return hint
    return ""


def _project_of(cfg: dict, inp: dict) -> str:
    project = _first(cfg, inp, "project")
    if not project:
        raise RuntimeError(
            "缺少剪辑台项目：在节点配置里选择 project，或连接上游节点的 project 端口"
        )
    return project


def _first(cfg: dict, inp: dict, key: str) -> str:
    """取值优先级：**节点配置（手动输入）优先，连线输入备选**，两者都空则无输入。

    字符串类字段统一走这里，避免各节点各写一套优先逻辑。
    """
    manual = cfg.get(key)
    if manual is not None and str(manual).strip():
        return str(manual).strip()
    wired = inp.get(key)
    if wired is not None and str(wired).strip():
        return str(wired).strip()
    return ""


def _first_list(cfg: dict, inp: dict, key: str) -> list:
    """列表类字段（paths / asset_ids / clip_ids / ops）的同等优先级取值。"""
    manual = _parse_json_list(cfg.get(key))
    if manual:
        return manual
    return _parse_json_list(inp.get(key))


def _preflight(cfg: dict, task_dir: str = ""):
    """预检 + 取出公共参数；剪辑台不可用时抛错并给出修复指引。

    ``use_task_output_dir=True`` 时用「本任务目录下的 output」作为剪辑台数据目录，
    让每次任务的数据互相隔离（默认用剪辑台自己的数据目录）。
    """
    ok, reason = occ.available()
    if not ok:
        raise RuntimeError(f"剪辑台不可用：{reason}")
    data_dir = str(cfg.get("data_dir") or "").strip()
    if bool(cfg.get("use_task_output_dir")) and task_dir:
        data_dir = os.path.join(task_dir, "output")
    try:
        timeout = int(cfg.get("timeout") or occ.DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        timeout = occ.DEFAULT_TIMEOUT
    return data_dir, timeout


def _extract_assets(result) -> list[str]:
    """从工具调用结果里抽取素材 id（import_asset(s) 的返回形状）。"""
    if result is None:
        return []
    data = result if isinstance(result, dict) else {}
    for key in ("assetIds", "assets", "importedAssets", "imported"):
        value = data.get(key)
        if isinstance(value, list) and value:
            out = []
            for item in value:
                if isinstance(item, dict):
                    out.append(str(item.get("id") or item.get("assetId") or ""))
                elif item:
                    out.append(str(item))
            return [x for x in out if x]
    if isinstance(data.get("assetId"), str):
        return [data["assetId"]]
    return []


def _extract_clips(result) -> list[str]:
    """从工具调用结果里抽取片段 id。"""
    if not isinstance(result, dict):
        return []
    for key in ("itemIds", "clipIds", "items", "clips", "added"):
        value = result.get(key)
        if isinstance(value, list) and value:
            out = []
            for item in value:
                if isinstance(item, dict):
                    out.append(str(item.get("id") or item.get("itemId") or ""))
                elif item:
                    out.append(str(item))
            return [x for x in out if x]
    return []


# --------------------------------------------------------------------------- #
# 节点 0：新建剪辑工程
# --------------------------------------------------------------------------- #
class S_DeskProject(BaseStep):
    """在剪辑台里新建一个工程，输出新项目 ID 供下游节点串联。"""

    step_id = "desk_project"
    step_name = "新建剪辑工程"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        return os.path.isfile(_cache_path(task_dir, _node_id(self), _PREFIX))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback=None, cancel_callback=None) -> dict:
        cfg = _cfg(self)
        inp = _inputs(self)
        nid = _node_id(self)

        name = _first(cfg, inp, "name")
        if not name:
            raise RuntimeError("缺少工程名称：在节点配置里填写 name（建议带日期/批次，便于在剪辑台里辨认），或连接上游输入")

        data_dir, _timeout = _preflight(cfg, task_dir)

        step_check_cancel(cancel_callback)
        if callback:
            callback(30, f"在剪辑台新建工程「{name}」…")

        result = occ.create_project(
            name,
            size=str(cfg.get("size") or "").strip(),
            fps=str(cfg.get("fps") or "").strip(),
            data_dir=data_dir,
        )
        if not result.ok:
            detail = result.message or result.tail(10)
            hint = _hint_for(detail)
            raise RuntimeError(f"新建剪辑工程失败（exit {result.returncode}）：{detail}" + (f"\n提示：{hint}" if hint else ""))

        project_id = ""
        if isinstance(result.data, dict):
            project_id = str(result.data.get("id") or "")
        if not project_id:
            raise RuntimeError(f"新建工程返回异常，未拿到项目 ID：{result.tail(10)}")

        cache = _write_cache(task_dir, nid, _PREFIX, {"project": project_id, "name": name})
        if callback:
            callback(100, f"工程已创建：{name}")
        return {
            "artifacts": [cache],
            "outputs": {
                "project": project_id,
                "name": name,
                "plan": f"occ project new {name} → {project_id}",
            },
        }


# --------------------------------------------------------------------------- #
# 节点 1：素材导入 + 上轨
# --------------------------------------------------------------------------- #
class S_DeskMaterial(BaseStep):
    """把本地素材导入剪辑台媒体池，并按声明式配置放到时间线轨道上。"""

    step_id = "desk_material"
    step_name = "剪辑素材导入"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        return os.path.isfile(_cache_path(task_dir, _node_id(self), _PREFIX))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback=None, cancel_callback=None) -> dict:
        cfg = _cfg(self)
        inp = _inputs(self)
        nid = _node_id(self)
        project = _project_of(cfg, inp)
        data_dir, timeout = _preflight(cfg, task_dir)
        dry_run = bool(cfg.get("dry_run", True))

        # 1) 收集素材路径：path(单个) / paths(多个) / folder(整目录) / asset_ids(跳过导入)
        #    取值优先级：节点配置优先，连线备选（_first / _first_list）
        raw_paths = _first_list(cfg, inp, "paths")
        single = _first(cfg, inp, "path")
        if single:
            raw_paths = [single] + raw_paths
        folder = _first(cfg, inp, "folder")
        resolved = [p for p in (_resolve_file(x, task_dir) or x for x in raw_paths) if p]
        if folder:
            folder_abs = _resolve_file(folder, task_dir) or folder
            if os.path.isdir(folder_abs):
                resolved.append(folder_abs)

        step_check_cancel(cancel_callback)
        if callback:
            callback(15, f"导入 {len(resolved)} 个素材到剪辑台媒体池…")

        imported_ids: list[str] = []
        if resolved:
            files = [p for p in resolved if os.path.isfile(p)]
            dirs = [p for p in resolved if os.path.isdir(p)]
            for path in files:
                r = occ.call_tool("import_asset", {"path": path},
                                  project=project, data_dir=data_dir, apply=not dry_run, timeout=timeout)
                if not r.ok:
                    raise RuntimeError(
                        f"导入素材失败 {os.path.basename(path)}：{r.message}\n提示：{_hint_for(r.message) or '确认路径存在且在媒体导入白名单内'}"
                    )
                imported_ids.extend(_extract_assets(r.data) or [])
            for path in dirs:
                r = occ.call_tool("import_folder", {"path": path},
                                  project=project, data_dir=data_dir, apply=not dry_run, timeout=timeout)
                if not r.ok:
                    raise RuntimeError(
                        f"导入目录失败 {path}：{r.message}\n提示：{_hint_for(r.message) or '确认目录内包含受支持的媒体文件'}"
                    )
                imported_ids.extend(_extract_assets(r.data) or [])

        asset_ids = _first_list(cfg, inp, "asset_ids") or imported_ids
        if not asset_ids:
            raise RuntimeError("没有可导入的素材：请连接 path / paths / folder 端口，或直接填 asset_ids（已入库的素材）")

        # 2) 上轨（可选）
        add_to_track = bool(cfg.get("add_to_track", True))
        clip_ids: list[str] = []
        if add_to_track and not dry_run is False:
            track = str(cfg.get("track") or "V1").strip() or "V1"
            try:
                from_frame = int(float(cfg.get("from_frame") or 0))
            except (TypeError, ValueError):
                from_frame = 0
            try:
                duration = int(float(cfg.get("duration_frames") or 0)) or None
            except (TypeError, ValueError):
                duration = None
            kind = str(cfg.get("clip_type") or "").strip().lower()

            adds = []
            for asset_id in asset_ids:
                add = {
                    "type": kind or "video",
                    "assetId": asset_id,
                    "track": track,
                    "fromFrame": from_frame,
                }
                if duration:
                    add["durationInFrames"] = duration
                adds.append(add)
                if from_frame and duration:
                    from_frame += duration
            if callback:
                callback(60, f"把 {len(adds)} 个素材放到轨道 {track}…")
            r = occ.call_tool(
                "edit_item",
                {"adds": adds},
                project=project, data_dir=data_dir, apply=not dry_run, timeout=timeout,
            )
            if not r.ok:
                raise RuntimeError(f"上轨失败：{r.message}\n提示：{_hint_for(r.message) or '检查轨道名（视频 V1/V2…、音频 A1/A2…）与素材类型是否匹配'}")
            clip_ids = _extract_clips(r.data)
        elif add_to_track and dry_run:
            if callback:
                callback(60, "演练模式：跳过上轨（关闭 dry_run 后才会写入时间线）")

        cache = _write_cache(task_dir, nid, _PREFIX, {
            "project": project, "dry_run": dry_run, "asset_ids": asset_ids, "clip_ids": clip_ids,
        })
        if callback:
            callback(100, f"素材就绪：{len(asset_ids)} 个入库，{len(clip_ids)} 个上轨")
        return {
            "artifacts": [cache],
            "outputs": {
                "project": project,
                "asset_ids": json.dumps(asset_ids, ensure_ascii=False),
                "clip_ids": json.dumps(clip_ids, ensure_ascii=False),
                "plan": f"import {len(resolved)} path(s) → asset_ids={asset_ids} → track adds={len(clip_ids)}",
            },
        }


# --------------------------------------------------------------------------- #
# 节点 2：剪辑编排（AI 语义剪辑 + ops 批量工具调用）
# --------------------------------------------------------------------------- #
class S_DeskEdit(BaseStep):
    """剪辑编排：AI 语义剪辑（read_script → LLM → apply_script）或 ops 批量调用剪辑台工具。

    ops 是声明式数组，每项 ``{"tool": "<工具名>", "args": {...}}``；参数里可用
    ``{{input.xxx}}`` 引用本节点输入、``{{prev.xxx}}`` 引用上一个 op 的结果，
    从而在一个节点内完成「读时间线 → 找片段 → 改时序 → 加模板」这类串联操作。
    """

    step_id = "desk_edit"
    step_name = "剪辑编排"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        return os.path.isfile(_cache_path(task_dir, _node_id(self), _PREFIX))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback=None, cancel_callback=None) -> dict:
        cfg = _cfg(self)
        inp = _inputs(self)
        nid = _node_id(self)
        project = _project_of(cfg, inp)
        data_dir, timeout = _preflight(cfg, task_dir)
        dry_run = bool(cfg.get("dry_run", True))

        mode = str(cfg.get("mode") or "ops").strip().lower()
        if mode not in ("ops", "ai_script"):
            raise RuntimeError(f"不支持的编排模式: {mode}（可选 ops / ai_script）")

        step_check_cancel(cancel_callback)
        if mode == "ai_script":
            return self._run_ai_script(task_dir, nid, project, data_dir, timeout, dry_run, cfg, inp, callback, cancel_callback)
        return self._run_ops(task_dir, nid, project, data_dir, timeout, dry_run, cfg, inp, callback, cancel_callback)

    # ---- ops 模式 ----
    def _run_ops(self, task_dir, nid, project, data_dir, timeout, dry_run, cfg, inp, callback, cancel_callback):
        raw_ops = cfg.get("ops") if str(cfg.get("ops") or "").strip() else inp.get("ops")
        if raw_ops is None or (isinstance(raw_ops, str) and not raw_ops.strip()):
            ops = []
        elif isinstance(raw_ops, str):
            try:
                ops = json.loads(raw_ops)
            except (ValueError, TypeError) as exc:
                raise RuntimeError(f"ops 不是合法 JSON：{exc}")
        else:
            ops = raw_ops
        if not isinstance(ops, list) or not ops:
            raise RuntimeError("缺少 ops：请在配置里添加工具调用，或连接上游 ops 输入")

        if callback:
            callback(15, f"按序执行 {len(ops)} 个剪辑台工具调用…")
        inputs = {
            "project": project,
            "asset_ids": _first_list(cfg, inp, "asset_ids"),
            "clip_ids": _first_list(cfg, inp, "clip_ids"),
        }
        steps = occ.run_ops(
            ops,
            project=project,
            data_dir=data_dir,
            apply=not dry_run,
            inputs=inputs,
            timeout=timeout,
        )
        failed = [s for s in steps if not s["ok"]]
        if failed:
            first = failed[0]
            raise RuntimeError(
                f"第 {steps.index(first) + 1} 个工具调用失败（{first['tool']}）：{first['message']}\n"
                f"提示：{_hint_for(first['message']) or '检查工具名与参数；occ tools ls 可查看可用工具'}"
            )
        cache = _write_cache(task_dir, nid, _PREFIX, {
            "project": project, "dry_run": dry_run, "mode": "ops", "steps": steps,
        })
        if callback:
            callback(100, f"{len(steps)} 个工具调用完成")
        return {
            "artifacts": [cache],
            "outputs": {
                "project": project,
                "result": json.dumps([{k: v for k, v in s.items() if k != "result"} for s in steps], ensure_ascii=False),
                "last": json.dumps(steps[-1].get("result"), ensure_ascii=False) if steps else "",
                "plan": json.dumps([s["tool"] for s in steps], ensure_ascii=False),
            },
        }

    # ---- AI 语义剪辑模式 ----
    def _run_ai_script(self, task_dir, nid, project, data_dir, timeout, dry_run, cfg, inp, callback, cancel_callback):
        instruction = _first(cfg, inp, "instruction")
        if not instruction:
            raise RuntimeError("缺少剪辑指令（instruction）：在配置里说明要让剪辑台做什么改动，或连接上游输入")

        if callback:
            callback(10, "读取当前时间线（timeline.md）…")
        read = occ.call_tool("read_script", {}, project=project, data_dir=data_dir, timeout=timeout)
        if not read.ok:
            raise RuntimeError(f"读取时间线失败：{read.message}\n提示：{_hint_for(read.message) or '确认项目存在且已 target'}")

        timeline_md = ""
        if isinstance(read.data, dict):
            timeline_md = str(read.data.get("timelineMd") or read.data.get("markdown") or read.data.get("script") or "")
        elif isinstance(read.data, str):
            timeline_md = read.data
        if not timeline_md:
            raise RuntimeError("read_script 未返回 timeline.md 内容（可能时间线为空）")

        if callback:
            callback(40, "调用 LLM 按指令编辑 timeline.md…")
        from backend.steps.s_agi_comic import _llm

        system = (
            "你是视频剪辑师，下面是剪辑台时间线的 timeline.md（分段 id 编码的 Markdown）。"
            "按用户指令编辑后，原样返回完整的 timeline.md（不要解释、不要代码块包裹）。"
            "编辑语法：删除词用 ~~词~~；可整段删除、调整顺序、合并；不要改动除内容以外的结构。"
        )
        prompt = f"【剪辑指令】\n{instruction}\n\n【当前 timeline.md】\n{timeline_md}"
        step_check_cancel(cancel_callback)
        resp = _llm(self.step_id, prompt, system=system, json_mode=False)
        edited = _text_of(resp)
        if not edited.strip():
            raise RuntimeError("LLM 未返回编辑后的 timeline.md")
        if "```" in edited:  # 去掉可能的代码块包裹
            edited = edited.replace("```markdown", "").replace("```", "").strip()

        if callback:
            callback(70, "预校验编辑结果（preview，不落盘）…")
        preview = occ.call_tool(
            "apply_script",
            {"timelineMd": edited, "preview": True},
            project=project, data_dir=data_dir, timeout=timeout,
        )
        if not preview.ok:
            raise RuntimeError(
                f"编辑结果校验失败（未写入）：{preview.message}\n提示：保持 [sN] 行结构与轨道小节，仅改文字内容"
            )

        if dry_run:
            diff = json.dumps(preview.data, ensure_ascii=False)[:3000] if preview.data else ""
            cache = _write_cache(task_dir, nid, _PREFIX, {
                "project": project, "dry_run": True, "mode": "ai_script", "preview": diff,
            })
            if callback:
                callback(100, "演练完成：校验通过但未写入（关闭 dry_run 后正式提交）")
            return {
                "artifacts": [cache],
                "outputs": {"project": project, "result": diff, "last": "", "plan": "read_script → llm edit → apply_script(preview)"},
            }

        if callback:
            callback(85, "提交编辑到时间线…")
        applied = occ.call_tool(
            "apply_script",
            {"timelineMd": edited},
            project=project, data_dir=data_dir, apply=True, timeout=timeout,
        )
        if not applied.ok:
            raise RuntimeError(f"提交剪辑失败：{applied.message}\n提示：{_hint_for(applied.message) or '并发写冲突时重试即可'}")
        cache = _write_cache(task_dir, nid, _PREFIX, {
            "project": project, "dry_run": False, "mode": "ai_script",
            "result": json.dumps(applied.data, ensure_ascii=False)[:2000],
        })
        if callback:
            callback(100, "AI 剪辑已提交")
        return {
            "artifacts": [cache],
            "outputs": {
                "project": project,
                "result": json.dumps(applied.data, ensure_ascii=False)[:3000],
                "last": "",
                "plan": "read_script → llm edit → apply_script(apply)",
            },
        }


def _text_of(resp) -> str:
    """从 LLM 响应里取纯文本。"""
    if resp is None:
        return ""
    if isinstance(resp, str):
        return resp
    for key in ("text", "content", "output"):
        value = resp.get(key) if isinstance(resp, dict) else getattr(resp, key, None)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, list):
            parts = [str(x.get("text") or x.get("content") or "") if isinstance(x, dict) else str(x) for x in value]
            joined = "".join(parts).strip()
            if joined:
                return joined
    return str(resp)


# --------------------------------------------------------------------------- #
# 节点 3：渲染导出
# --------------------------------------------------------------------------- #
class S_DeskExport(BaseStep):
    """渲染剪辑台项目成片（occ render，无头）或导出剪映/CapCut 草稿。"""

    step_id = "desk_export"
    step_name = "剪辑台渲染导出"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        return os.path.isfile(_cache_path(task_dir, _node_id(self), _PREFIX))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback=None, cancel_callback=None) -> dict:
        cfg = _cfg(self)
        inp = _inputs(self)
        nid = _node_id(self)
        project = _project_of(cfg, inp)
        data_dir, timeout = _preflight(cfg, task_dir)

        mode = str(cfg.get("mode") or "render").strip().lower()
        if mode not in ("render", "jianying"):
            raise RuntimeError(f"不支持的导出模式: {mode}（可选 render / jianying）")
        dry_run = bool(cfg.get("dry_run", True))

        step_check_cancel(cancel_callback)
        if callback:
            callback(10, f"调用剪辑台 CLI（{mode}，{'演练' if dry_run else '正式'}）…")

        out_dir = os.path.join(task_dir, "output")
        os.makedirs(out_dir, exist_ok=True)
        if mode == "render":
            out_name = str(cfg.get("out_name") or f"desk_render_{nid}.mp4").strip()
            if not out_name.lower().endswith((".mp4", ".webm", ".mov")):
                out_name += ".mp4"
            out_file = os.path.join(out_dir, out_name)
            result = occ.render(
                project, out_file,
                resolution=str(cfg.get("resolution") or "").strip(),
                fps=str(cfg.get("fps") or "").strip(),
                codec=str(cfg.get("codec") or "").strip(),
                apply=not dry_run, data_dir=data_dir, timeout=timeout,
            )
        else:
            out_file = os.path.join(out_dir, f"jianying_{nid}")
            result = occ.export_jianying(
                project, out_file,
                draft_name=str(cfg.get("draft_name") or "").strip(),
                apply=not dry_run, data_dir=data_dir, timeout=timeout,
            )

        if callback:
            callback(70, "剪辑台调用返回，校验产物…")

        if not result.ok:
            detail = result.message or result.tail(10)
            hint = _hint_for(detail)
            raise RuntimeError(f"剪辑台导出失败（exit {result.returncode}）：{detail}" + (f"\n提示：{hint}" if hint else ""))

        if dry_run:
            plan = result.data if result.data is not None else result.stdout
            if not isinstance(plan, str):
                plan = json.dumps(plan, ensure_ascii=False, indent=2)
            plan = (plan or result.tail(20))[:4000]
            cache = _write_cache(task_dir, nid, _PREFIX, {"project": project, "mode": mode, "dry_run": True, "plan": plan})
            if callback:
                callback(100, "演练完成：未写入任何文件（关闭 dry_run 后才会出片）")
            return {
                "artifacts": [cache],
                "outputs": {"project": project, "mode": mode, "render": "", "plan": plan},
            }

        produced = ""
        if mode == "render":
            if os.path.isfile(out_file) and os.path.getsize(out_file) > 0:
                produced = out_file
            else:
                raise RuntimeError(f"剪辑台未产出文件：{out_file}（CLI 输出：{result.message or result.tail(10)}）")
        else:
            if os.path.isdir(out_file) and os.listdir(out_file):
                produced = out_file
            else:
                raise RuntimeError(f"剪映草稿目录为空：{out_file}（CLI 输出：{result.message or result.tail(10)}）")

        creation_id = _first(cfg, inp, "creation_id")
        chapter_id = _first(cfg, inp, "chapter_id")
        if creation_id:
            try:
                duration = 0.0
                if mode == "render":
                    try:
                        from backend.utils.audio_processor import get_video_duration

                        duration = get_video_duration(produced) or 0.0
                    except Exception:  # noqa: BLE001
                        duration = 0.0
                from backend import creation as agi

                agi.register_asset(
                    creation_id, "chapter_render",
                    chapter_id=chapter_id or None,
                    paths_list=[produced], duration_seconds=duration,
                )
            except Exception as exc:  # noqa: BLE001
                if callback:
                    callback(95, f"资产登记失败（产物已生成）：{exc}")

        cache = _write_cache(task_dir, nid, _PREFIX, {"project": project, "mode": mode, "dry_run": False, "output": produced})
        if callback:
            callback(100, "剪辑台导出完成")
        return {
            "artifacts": [cache, produced],
            "outputs": {"project": project, "mode": mode, "render": produced, "plan": ""},
        }

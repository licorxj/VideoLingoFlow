"""HyperFrames 系列节点的公共基类。

把「创意」与「渲染」两个阶段抽象成可复用方法，供三个节点组合使用：

- :class:`S_HyperFramesCreative` 只跑创意阶段
- :class:`S_HyperFramesRender` 只跑渲染阶段
- :class:`S_HyperFramesAgent` 复合节点，按设置的跨度跑其中的一段或两段

阶段方法只做编排，具体能力来自 :mod:`backend.utils.hyperframes`。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Callable, Optional

from backend.steps.base_step import BaseStep
from backend.utils import hyperframes as hf


def _config(node: Any) -> dict:
    return getattr(node, "_node_config", {}) or {}


def _inputs(node: Any) -> dict:
    return getattr(node, "_step_inputs", {}) or {}


def _node_id(node: Any) -> str:
    return getattr(node, "_node_id", "") or "node"


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


def _rel_or_abs(task_dir: str, path: Path) -> str:
    """产物路径：任务目录内返回相对路径，目录外返回绝对路径。"""
    try:
        return str(Path(path).resolve().relative_to(Path(task_dir).resolve())).replace("\\", "/")
    except (ValueError, OSError):
        return str(Path(path).resolve())


class HyperFramesBase(BaseStep):
    """HyperFrames 系列节点公共实现。"""

    #: 结果 JSON 的文件基名（子类覆盖）
    result_base = "hyperframes"

    dependencies: list = []
    artifacts: list = []

    # ---------------- BaseStep 接口 ----------------
    def _result_path(self, task_dir: str) -> Path:
        return Path(task_dir) / "cache" / f"{self.result_base}_{_node_id(self)}.json"

    def check_artifact(self, task_dir: str) -> bool:
        return self._result_path(task_dir).is_file()

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    # ---------------- 通用辅助 ----------------
    def _project_dir(self, task_dir: str, config: dict, inputs: dict, create: bool = True) -> Path:
        """确定项目目录：连线输入 > 节点配置 > 任务缓存默认目录。"""
        linked = hf.resolve_input_path(task_dir, inputs.get("project_dir") or inputs.get("any"))
        if linked is not None and linked.is_dir():
            return linked.resolve()
        return hf.resolve_project_dir(task_dir, config, _node_id(self), create=create)

    @staticmethod
    def _cli_settings(config: dict) -> tuple[str, str]:
        cli = str(config.get("cli_command") or hf.DEFAULT_CLI).strip() or hf.DEFAULT_CLI
        package = str(config.get("cli_package") or hf.DEFAULT_PACKAGE).strip()
        return cli, package

    @staticmethod
    def _as_int(value: Any, default: int, minimum: int = 1) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return default
        return number if number >= minimum else default

    def _write_result(self, task_dir: str, payload: dict) -> Path:
        path = self._result_path(task_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _collect_assets(self, task_dir: str, inputs: dict, keys: tuple[str, ...] = ("assets", "source", "input")) -> dict:
        """把连线输入整理成给 Pi 会话的材料清单。"""
        materials: dict[str, str] = {}
        for key in keys:
            raw = inputs.get(key)
            if raw in (None, "", []):
                continue
            if isinstance(raw, (list, tuple)):
                values = [str(item) for item in raw if str(item).strip()]
            else:
                values = [str(raw)]
            resolved = []
            for value in values:
                candidate = Path(value)
                if not candidate.is_absolute():
                    candidate = Path(task_dir) / candidate
                resolved.append(str(candidate.resolve() if candidate.exists() else Path(value)))
            materials[key] = resolved[0] if len(resolved) == 1 else json.dumps(resolved, ensure_ascii=False)
        return materials

    def _copy_into_cache(self, task_dir: str, source: Path, filename: str) -> Path:
        cache_dir = Path(task_dir) / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        target = cache_dir / filename
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        return target

    # ---------------- 阶段一：创意 ----------------
    def run_creative_phase(
        self,
        task_dir: str,
        config: dict,
        inputs: dict,
        callback: Optional[Callable] = None,
        cancel_callback: Optional[Callable] = None,
        progress_range: tuple[int, int] = (5, 95),
    ) -> dict:
        """产出（或加载）BRIEF.md。

        ``mode=load`` 走确定性路径：直接把已有的 BRIEF.md 装进项目目录并解析路由，
        不发起 Pi 会话；``mode=create`` 由 Pi 会话按意图访谈写简报。
        """
        low, high = progress_range
        project_dir = self._project_dir(task_dir, config, inputs)
        cli, package = self._cli_settings(config)
        mode = str(config.get("mode") or "create").strip().lower()
        route = str(config.get("workflow") or "").strip()

        def progress(percent: int, message: str) -> None:
            if callback:
                try:
                    callback(percent, message)
                except Exception:
                    pass

        progress(low, f"项目目录：{project_dir}")

        # ---- 加载已有简报 ----
        if mode == "load":
            source = (
                hf.resolve_input_path(task_dir, inputs.get("brief"))
                or hf.resolve_input_path(task_dir, config.get("brief_path"))
                or hf.find_brief(project_dir)
            )
            if source is None or not source.is_file():
                raise FileNotFoundError(
                    "加载模式未找到 BRIEF.md：请通过 brief 输入端口接入已有简报，"
                    "或在节点设置里填写 BRIEF.md 路径 / 项目目录。"
                )
            brief_path = hf.install_brief_into_project(source, project_dir)
            detected = hf.read_brief_route(brief_path)
            progress(high, f"已加载简报：{brief_path}")
            return {
                "project_dir": str(project_dir),
                "brief": str(brief_path),
                "workflow": route or detected,
                "summary": f"复用既有简报（路由：{route or detected or '未标注'}）",
                "source_brief": str(source),
            }

        # ---- 新建简报 ----
        if _as_bool(config.get("update_skills", True)):
            progress(low + 5, "检查 HyperFrames 技能安装状态")
            try:
                hf.ensure_workflow_skills(
                    route, project_dir, cli=cli, package=package,
                    timeout=self._as_int(config.get("skills_timeout"), 600),
                    callback=callback, cancel_callback=cancel_callback,
                )
            except RuntimeError as exc:
                # 技能刷新失败不应阻断：Pi 会话内仍可按需安装
                progress(low + 8, f"技能刷新跳过：{exc}")

        materials = self._collect_assets(task_dir, inputs)
        subject = str(config.get("subject") or "").strip()
        if not subject:
            inline = hf.first_value(inputs.get("source") or inputs.get("text") or inputs.get("any"))
            # 内联文本（非文件路径）直接当作主题描述
            if inline and not hf.resolve_input_path(task_dir, inline):
                subject = inline

        system_prompt = hf.build_creative_prompt(
            project_dir=project_dir,
            route=route,
            subject=subject,
            run_mode=str(config.get("run_mode") or "collaborative"),
            style_preset=str(config.get("style_preset") or ""),
            aspect=str(config.get("aspect") or "auto"),
            language=str(config.get("language") or ""),
            materials=materials,
            extra_instruction=str(config.get("extra_instruction") or ""),
        )
        instruction = (
            "请按系统提示开始本次创意工作：读取 HyperFrames 技能入口与路由契约，"
            "收敛主题与必选项，把最终简报写入项目目录的 BRIEF.md，"
            f"然后输出 {hf.DONE_MARKER} 与验收 JSON。"
        )

        progress(low + 10, "启动小 Pi 会话进行创意收敛")
        final_text = hf.run_pi_task(
            system_prompt, instruction, cwd=project_dir,
            callback=callback, cancel_callback=cancel_callback,
            settle_timeout=self._as_int(config.get("settle_timeout"), 1800),
            progress_range=(low + 10, high - 5),
        )
        payload = hf.require_done_payload(final_text)
        if str(payload.get("status", "failed")) == "failed":
            raise RuntimeError(str(payload.get("message") or "创意阶段失败"))

        brief_path = hf.find_brief(project_dir)
        if brief_path is None:
            reported = str(payload.get("brief") or "BRIEF.md")
            candidate = Path(reported)
            if not candidate.is_absolute():
                candidate = project_dir / candidate
            brief_path = candidate if candidate.is_file() else None
        if brief_path is None:
            raise RuntimeError(
                f"创意阶段结束但未找到 BRIEF.md（项目目录：{project_dir}）。"
                "请确认小 Pi 已把简报写入该目录。"
            )

        workflow = str(payload.get("workflow") or hf.read_brief_route(brief_path) or route or "")
        progress(high, "创意阶段完成")
        return {
            "project_dir": str(project_dir),
            "brief": str(brief_path),
            "workflow": workflow,
            "summary": str(payload.get("summary") or payload.get("message") or ""),
        }

    # ---------------- 阶段二：渲染 ----------------
    def run_render_phase(
        self,
        task_dir: str,
        config: dict,
        inputs: dict,
        creative: Optional[dict] = None,
        callback: Optional[Callable] = None,
        cancel_callback: Optional[Callable] = None,
        progress_range: tuple[int, int] = (5, 95),
    ) -> dict:
        """按 BRIEF.md 构建合成并渲染成片。"""
        low, high = progress_range
        node_id = _node_id(self)
        creative = creative or {}

        # 上游 project_dir 端口 > 创意阶段产出的目录 > 配置/默认目录
        linked_project = hf.resolve_input_path(task_dir, inputs.get("project_dir"))
        if linked_project is not None and not linked_project.is_dir():
            linked_project = None
        inherited = creative.get("project_dir") or ""
        project_dir = (
            linked_project
            or (Path(inherited) if inherited and Path(inherited).is_dir() else None)
            or self._project_dir(task_dir, config, inputs)
        )
        project_dir.mkdir(parents=True, exist_ok=True)

        def progress(percent: int, message: str) -> None:
            if callback:
                try:
                    callback(percent, message)
                except Exception:
                    pass

        brief_path = (
            hf.resolve_input_path(task_dir, inputs.get("brief"))
            or hf.resolve_input_path(task_dir, config.get("brief_path"))
            or (Path(creative["brief"]) if creative.get("brief") and Path(creative["brief"]).is_file() else None)
            or hf.find_brief(project_dir)
        )
        if brief_path is None or not brief_path.is_file():
            raise FileNotFoundError(
                "渲染阶段需要 BRIEF.md：请把「HyperFrames 创意」节点的 brief 端口连过来，"
                "或在节点设置里填写 BRIEF.md 路径 / 项目目录。"
            )

        route = str(config.get("workflow") or creative.get("workflow") or hf.read_brief_route(brief_path) or "")
        cli, package = self._cli_settings(config)
        stage = str(config.get("stage") or "build_and_render")
        output_name = str(config.get("output_name") or "output.mp4").strip() or "output.mp4"

        if _as_bool(config.get("update_skills", True)):
            progress(low + 5, "检查 HyperFrames 技能安装状态")
            try:
                hf.ensure_workflow_skills(
                    route, project_dir, cli=cli, package=package,
                    timeout=self._as_int(config.get("skills_timeout"), 600),
                    callback=callback, cancel_callback=cancel_callback,
                )
            except RuntimeError as exc:
                progress(low + 8, f"技能刷新跳过：{exc}")

        materials = self._collect_assets(task_dir, inputs, keys=("assets",))
        system_prompt = hf.build_render_prompt(
            project_dir=project_dir,
            brief_path=brief_path,
            route=route,
            stage=stage,
            output_name=output_name,
            extra_instruction=str(config.get("extra_instruction") or ""),
            publish=_as_bool(config.get("publish", False)),
        )
        instruction = (
            "请按系统提示执行制作：先完整阅读 BRIEF.md，再按其 workflow 路由推进，"
            f"完成 {stage} 阶段的任务，最后输出 {hf.DONE_MARKER} 与验收 JSON。"
        )
        if materials:
            instruction += f"\n本节点附带的素材：{json.dumps(materials, ensure_ascii=False)}"

        progress(low + 10, "启动小 Pi 会话执行制作与渲染")
        final_text = hf.run_pi_task(
            system_prompt, instruction, cwd=project_dir,
            callback=callback, cancel_callback=cancel_callback,
            settle_timeout=self._as_int(config.get("settle_timeout"), 3600),
            progress_range=(low + 10, high - 10),
        )
        payload = hf.require_done_payload(final_text)
        if str(payload.get("status", "failed")) == "failed":
            raise RuntimeError(str(payload.get("message") or "渲染阶段失败"))

        video_value = hf.first_value(payload.get("video"))
        video_path: Optional[Path] = None
        if video_value:
            candidate = Path(video_value)
            if not candidate.is_absolute():
                candidate = project_dir / candidate
            video_path = candidate.resolve() if candidate.is_file() else None
        if video_path is None:
            video_path = hf.locate_render_output(project_dir, str(config.get("output_path") or ""))

        url = hf.first_value(payload.get("url"))
        result: dict[str, Any] = {
            "project_dir": str(project_dir),
            "brief": str(brief_path),
            "workflow": route,
            "url": url,
            "message": str(payload.get("message") or ""),
        }

        if video_path is not None and video_path.is_file():
            suffix = video_path.suffix.lower() or ".mp4"
            cached = self._copy_into_cache(task_dir, video_path, f"hyperframes_render_{node_id}{suffix}")
            result["video"] = str(cached)
            result["video_source"] = str(video_path)
            progress(high, f"成片已就位：{cached.name}")
        elif stage == "validate":
            progress(high, "校验完成（本阶段不产出成片）")
        else:
            progress(high, "未找到成片：请检查小 Pi 是否执行了渲染")

        return result

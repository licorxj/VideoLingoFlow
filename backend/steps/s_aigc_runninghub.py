"""AIGC RunningHub 工作流节点步骤。"""
import os
import shutil
import json

from backend.steps.base_step import BaseStep
from backend.aigc.runninghub_service import RunningHubService
from backend.aigc.errors import AIGCError

from backend.steps.s_aigc_comfyui import _read_input_as_text


def _resolve_output(task_dir: str, node_id: str, paths: list) -> list:
    """将已下载到 task output 目录的产物重命名为约定命名，返回相对路径（同目录 rename，无复制）。"""
    out_dir = os.path.join(task_dir, "output")
    os.makedirs(out_dir, exist_ok=True)
    final = []
    for i, src in enumerate(paths):
        if not src or not os.path.exists(src):
            continue
        ext = os.path.splitext(src)[1] or ".png"
        dest = os.path.join(out_dir, f"aigc_runninghub_{i + 1}_{node_id}{ext}")
        try:
            if os.path.abspath(src) != os.path.abspath(dest):
                os.rename(src, dest)
        except OSError:
            shutil.copy2(src, dest)
        final.append(f"output/{os.path.basename(dest)}")
    return final


class S_AIGC_RunningHub(BaseStep):
    step_id = "aigc_runninghub"
    step_name = "RunningHub 生成"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        out = os.path.join(task_dir, "output")
        if not os.path.isdir(out):
            return False
        return any(f"aigc_runninghub_" in f and f"_{node_id}" in f for f in os.listdir(out))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback=None, cancel_callback=None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        cfg = getattr(self, "_node_config", {}) or {}
        inputs = getattr(self, "_step_inputs", {}) or {}

        from backend.config.config_manager import config
        aigc = config.get("aigc", {}) or {}
        svc = RunningHubService(aigc.get("runninghub") or {})

        kind = cfg.get("kind", "workflow")
        if isinstance(kind, list):
            kind = kind[0] if kind else "workflow"
        entry_id = (cfg.get("entry_id") or "").strip()
        if not entry_id:
            raise AIGCError("未填写 RunningHub 工作流/应用 ID")

        prompt = (cfg.get("prompt_override") or "").strip() or _read_input_as_text(inputs.get("text"), task_dir)

        # 多图输入：首帧→图片2→图片3→图片4→尾帧 自动组装（跳过空端口）
        from backend.aigc.params import resolve_image_inputs, resolve_resolution, resolve_num_images, resolve_reference_video
        ref_images = resolve_image_inputs(inputs, task_dir)
        # 参考视频输入（可选）
        ref_video = resolve_reference_video(inputs, task_dir)
        width, height = resolve_resolution(cfg)
        num_images = resolve_num_images(cfg)
        aspect_ratio = cfg.get("aspect_ratio") or ""
        if isinstance(aspect_ratio, list):
            aspect_ratio = aspect_ratio[0] if aspect_ratio else ""

        node_info_list = []
        raw_nl = (cfg.get("node_info_list") or "").strip()
        if raw_nl:
            try:
                node_info_list = json.loads(raw_nl)
            except Exception as e:
                raise AIGCError(f"节点参数 JSON 解析失败：{e}") from e

        if callback:
            callback(15, f"提交 RunningHub {kind} 任务 {entry_id} ...")

        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        result = svc.run(
            entry_id=entry_id,
            kind="ai_app" if kind == "ai_app" else "workflow",
            prompt=prompt,
            reference_images=ref_images,
            reference_video=ref_video,
            node_info_list=node_info_list or None,
            callback=callback,
            output_dir=output_dir,
            width=width,
            height=height,
            aspect_ratio=aspect_ratio,
            num_images=num_images,
        )

        paths = result.get("images", []) + result.get("videos", [])
        final = _resolve_output(task_dir, node_id, paths)
        if not final:
            raise AIGCError("RunningHub 未返回任何产物")
        return {
            "artifacts": final,
            "outputs": {
                "images": str(final),
                "first": final[0] if final else "",
                "files": str(final),
            },
        }

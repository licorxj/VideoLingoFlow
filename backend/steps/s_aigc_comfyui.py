"""AIGC ComfyUI 工作流节点步骤。"""
import os
import json

from backend.steps.base_step import BaseStep
from backend.aigc.comfyui_service import ComfyUIService
from backend.aigc.errors import AIGCError


def _read_input_as_text(value, task_dir: str = "") -> str:
    if not value or not isinstance(value, str):
        return ""
    candidate = value.strip()
    if os.path.isfile(candidate):
        with open(candidate, "r", encoding="utf-8") as f:
            return f.read().strip()
    if task_dir:
        rel = os.path.join(task_dir, candidate)
        if os.path.isfile(rel):
            with open(rel, "r", encoding="utf-8") as f:
                return f.read().strip()
    return candidate


def _resolve_output(task_dir: str, node_id: str, paths: list) -> list:
    """将已下载到 task output 目录的产物重命名为约定命名，返回相对路径。

    服务层已直接把产物下载到 task_dir/output，此处仅做同目录改名（os.rename，无复制）。
    """
    out_dir = os.path.join(task_dir, "output")
    os.makedirs(out_dir, exist_ok=True)
    final = []
    for i, src in enumerate(paths):
        if not src or not os.path.exists(src):
            continue
        ext = os.path.splitext(src)[1] or ".png"
        dest = os.path.join(out_dir, f"aigc_comfyui_{i + 1}_{node_id}{ext}")
        try:
            if os.path.abspath(src) != os.path.abspath(dest):
                os.rename(src, dest)
        except OSError:
            import shutil
            shutil.copy2(src, dest)
        final.append(f"output/{os.path.basename(dest)}")
    return final


class S_AIGC_ComfyUI(BaseStep):
    step_id = "aigc_comfyui"
    step_name = "ComfyUI 生图"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        out = os.path.join(task_dir, "output")
        if not os.path.isdir(out):
            return False
        return any(f"aigc_comfyui_" in f and f"_{node_id}" in f for f in os.listdir(out))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback=None, cancel_callback=None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        cfg = getattr(self, "_node_config", {}) or {}
        inputs = getattr(self, "_step_inputs", {}) or {}

        from backend.config.config_manager import config
        aigc = config.get("aigc", {}) or {}
        svc = ComfyUIService(aigc.get("comfyui") or {})

        workflow_name = (cfg.get("workflow_json") or "Z-Image.json").strip()
        workflow_path = os.path.join(os.path.dirname(__file__), "..", "aigc", "workflows", workflow_name)
        workflow_path = os.path.abspath(workflow_path)
        if not os.path.isfile(workflow_path):
            raise AIGCError(f"未找到 ComfyUI 工作流文件：{workflow_name}")

        with open(workflow_path, "r", encoding="utf-8") as f:
            workflow = json.load(f)

        mode = cfg.get("mode", "txt2img")
        if isinstance(mode, list):
            mode = mode[0] if mode else "txt2img"
        prompt = (cfg.get("prompt_override") or "").strip() or _read_input_as_text(inputs.get("text"), task_dir)
        if not prompt and mode == "txt2img":
            raise AIGCError("提示词为空：请连接文本输入或在节点中填写覆盖提示词")
        # 分辨率：支持 预设(1K/2K/3K/4K) / 长宽 / 自定义文本
        from backend.aigc.params import resolve_resolution, resolve_num_images, resolve_image_inputs, resolve_reference_video
        width, height = resolve_resolution(cfg)
        num_images = resolve_num_images(cfg)
        # 多图输入：首帧→图片2→图片3→图片4→尾帧 自动组装（跳过空端口）
        ref_images = resolve_image_inputs(inputs, task_dir)
        # 参考视频输入（可选）
        ref_video = resolve_reference_video(inputs, task_dir)

        node_params = {}
        raw_np = (cfg.get("node_params") or "").strip()
        if raw_np:
            try:
                node_params = json.loads(raw_np)
            except Exception as e:
                raise AIGCError(f"节点参数 JSON 解析失败：{e}") from e

        if callback:
            callback(15, f"提交 ComfyUI 工作流 {workflow_name} ...")

        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        result = svc.run_workflow(
            workflow=workflow,
            prompt_text=prompt,
            width=width,
            height=height,
            params=node_params,
            ref_images=ref_images,
            ref_video=ref_video,
            callback=callback,
            output_dir=output_dir,
            num_images=num_images,
        )

        final = _resolve_output(task_dir, node_id, result.get("images", []))
        extra = _resolve_output(task_dir, node_id + "_x", result.get("videos", []) + result.get("files", []))
        all_paths = final + extra
        if not all_paths:
            raise AIGCError("ComfyUI 未返回任何产物")
        return {
            "artifacts": all_paths,
            "outputs": {
                "images": str(final),
                "first": final[0] if final else "",
                "files": str(all_paths),
            },
        }

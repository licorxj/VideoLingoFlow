"""AIGC 即梦 CLI 工作流节点步骤。"""
import os
import json
import shutil

from backend.steps.base_step import BaseStep
from backend.aigc.jimeng_service import JimengService
from backend.aigc.errors import AIGCError

from backend.steps.s_aigc_comfyui import _read_input_as_text


def _collect_local_paths(obj) -> list:
    """从即梦 CLI 返回的 JSON 中提取本地文件路径。"""
    paths = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and os.path.isfile(v):
                paths.append(v)
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, str) and os.path.isfile(item):
                        paths.append(item)
                    elif isinstance(item, dict):
                        paths.extend(_collect_local_paths(item))
    return paths


def _resolve_output(task_dir: str, node_id: str, paths: list) -> list:
    """把即梦 CLI 落盘的本地文件移动到 task output 目录（move，同盘 rename / 跨盘复制后删源，不保留双份）。"""
    out_dir = os.path.join(task_dir, "output")
    os.makedirs(out_dir, exist_ok=True)
    final = []
    for i, src in enumerate(paths):
        if not src or not os.path.exists(src):
            continue
        ext = os.path.splitext(src)[1] or ".png"
        dest = os.path.join(out_dir, f"aigc_jimeng_{i + 1}_{node_id}{ext}")
        try:
            if os.path.abspath(src) == os.path.abspath(dest):
                pass
            else:
                shutil.move(src, dest)
        except OSError:
            shutil.copy2(src, dest)
        final.append(f"output/{os.path.basename(dest)}")
    return final


class S_AIGC_Jimeng(BaseStep):
    step_id = "aigc_jimeng"
    step_name = "即梦 CLI 生成"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        out = os.path.join(task_dir, "output")
        if not os.path.isdir(out):
            return False
        return any(f"aigc_jimeng_" in f and f"_{node_id}" in f for f in os.listdir(out))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback=None, cancel_callback=None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        cfg = getattr(self, "_node_config", {}) or {}
        inputs = getattr(self, "_step_inputs", {}) or {}

        from backend.config.config_manager import config
        aigc = config.get("aigc", {}) or {}
        svc = JimengService(aigc.get("jimeng") or {})

        mode = cfg.get("mode", "image")
        if isinstance(mode, list):
            mode = mode[0] if mode else "image"
        prompt = (cfg.get("prompt_override") or "").strip() or _read_input_as_text(inputs.get("text"), task_dir)
        if not prompt:
            raise AIGCError("提示词为空：请连接文本输入或在节点中填写覆盖提示词")

        # 多图输入：首帧→图片2→图片3→图片4→尾帧 自动组装（跳过空端口）
        from backend.aigc.params import (
            resolve_image_inputs,
            resolve_resolution,
            resolve_num_images,
            resolve_reference_video,
            resolution_label,
        )
        images = resolve_image_inputs(inputs, task_dir)
        # 参考视频输入（可选，仅视频模式生效）
        ref_video = resolve_reference_video(inputs, task_dir)
        model = cfg.get("model") or ""
        if isinstance(model, list):
            model = model[0] if model else ""
        width, height = resolve_resolution(cfg)
        resolution = resolution_label(width, height)
        ratio = cfg.get("aspect_ratio") or ""
        if isinstance(ratio, list):
            ratio = ratio[0] if ratio else ""
        num_images = resolve_num_images(cfg)

        if callback:
            callback(15, "调用即梦 CLI ...")

        if mode == "video":
            result = svc.generate_video(
                prompt=prompt,
                images=images,
                ref_video=ref_video,
                model=model,
                resolution=resolution,
                ratio=ratio,
                callback=callback,
            )
        else:
            result = svc.generate_image(
                prompt=prompt,
                images=images,
                model=model,
                resolution=resolution,
                ratio=ratio,
                num_images=num_images,
                callback=callback,
            )

        async_query = bool(cfg.get("async_query", True))
        if async_query:
            submit_id = None
            if isinstance(result, dict):
                submit_id = result.get("submit_id") or result.get("task_id") or result.get("id")
            if submit_id:
                if callback:
                    callback(60, f"即梦任务已提交 {submit_id}，查询中 ...")
                result = svc.query_task(submit_id)

        local_paths = []
        if isinstance(result, dict):
            local_paths = _collect_local_paths(result)
            # 兼容 _stdout 中的路径（兜底）
            if not local_paths and result.get("_stdout"):
                for tok in result["_stdout"].split():
                    if os.path.isfile(tok.strip().strip('"\'')):
                        local_paths.append(tok.strip().strip('"\''))
        elif isinstance(result, str):
            if os.path.isfile(result):
                local_paths = [result]

        final = _resolve_output(task_dir, node_id, local_paths)
        if not final:
            # 未解析到本地文件：把整份 JSON 结果保存，便于排查
            os.makedirs(os.path.join(task_dir, "output"), exist_ok=True)
            dump = os.path.join(task_dir, "output", f"aigc_jimeng_raw_{node_id}.json")
            with open(dump, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            raise AIGCError("即梦 CLI 未返回可识别的本地文件，已保存原始结果用于排查")
        return {
            "artifacts": final,
            "outputs": {
                "images": str(final),
                "first": final[0] if final else "",
                "files": str(final),
            },
        }

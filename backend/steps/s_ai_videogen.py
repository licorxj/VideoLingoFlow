"""s_ai_videogen: AI video generation node, mirroring s_imagegen.

输入:
  - prompt : 提示词（文本，或 .txt 文件路径，后端自动判断读取）
  - images : 图片 / 图片列表（路径，单个字符串或数组）
  - audio  : 音频（路径）；若连接，则强制声音=keep_original

输出:
  - videos : 生成的视频列表（相对路径）
  - video  : 首个视频路径

提示词前缀(prompt_prefix) 会在后端执行时拼接到连线输入的提示词之前，作为最终提示词。
生成类型(mode) 可由用户显式选择，否则根据已连接的输入自动推断
（≥2 张图→flf2video，1 张图→img2video，否则 txt2video）。
"""
import os
import shutil
from typing import Callable, Optional

from backend.steps.base_step import BaseStep


def _read_input_as_text(value, task_dir: str = "") -> str:
    """Resolve input: if it's a .txt file path, read its content; otherwise return as-is."""
    if not value or not isinstance(value, str):
        return str(value) if value else ""
    candidate = value.strip()
    if os.path.isfile(candidate):
        with open(candidate, "r", encoding="utf-8") as f:
            return f.read().strip()
    if task_dir:
        rel = os.path.join(task_dir, candidate)
        if os.path.isfile(rel):
            with open(rel, "r", encoding="utf-8") as f:
                return f.read().strip()
    return value.strip()


def _resolve_paths(value, task_dir: str = ""):
    """value 可以是路径字符串或路径数组，返回存在的绝对路径列表。"""
    if not value:
        return []
    items = value if isinstance(value, list) else [value]
    out = []
    for v in items:
        if not isinstance(v, str) or not v.strip():
            continue
        c = v.strip()
        if os.path.isfile(c):
            out.append(c)
        elif task_dir and os.path.isfile(os.path.join(task_dir, c)):
            out.append(os.path.join(task_dir, c))
    return out


class S_AiVideoGen(BaseStep):
    step_id = "ai_video_gen"
    step_name = "AI生视频"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        output_dir = os.path.join(task_dir, "output")
        if not os.path.isdir(output_dir):
            return False
        for f in os.listdir(output_dir):
            if f.endswith(f"_gen_video_{node_id}") or f"_gen_video_{node_id}." in f:
                return True
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        # --- 1. 读取配置 ---
        def _first(v):
            if isinstance(v, list):
                return v[0] if v else ""
            return v or ""

        interface = _first(node_config.get("interface", ""))
        model = _first(node_config.get("model", ""))
        mode = _first(node_config.get("mode", ""))
        resolution = _first(node_config.get("resolution", "")) or "720P"
        duration = int(node_config.get("duration", 5) or 5)
        num_videos = int(node_config.get("num_videos", 1) or 1)
        sound = _first(node_config.get("sound", "")) or "on"
        negative_prompt = _first(node_config.get("negative_prompt", ""))
        prompt_prefix = _first(node_config.get("prompt_prefix", ""))
        output_prefix = _first(node_config.get("output_prefix", "")) or "video"
        optimize_prompt = node_config.get("optimize_prompt")
        poll_timeout = node_config.get("poll_timeout")

        if not interface:
            raise ValueError("未选择视频生成接口，请在节点上选择接口。")

        # --- 2. 解析提示词（文本或 txt 文件） ---
        raw_text = step_inputs.get("prompt", "")
        connected_prompt = _read_input_as_text(raw_text, task_dir)
        if prompt_prefix and connected_prompt:
            final_prompt = f"{prompt_prefix}\n{connected_prompt}"
        else:
            final_prompt = (prompt_prefix or connected_prompt).strip()
        if not final_prompt:
            raise ValueError("提示词为空，请连接文本/txt 输入或填写提示词前缀。")

        # --- 3. 解析图片 / 音频输入 ---
        ref_images = _resolve_paths(step_inputs.get("images"), task_dir)
        audio_paths = _resolve_paths(step_inputs.get("audio"), task_dir)
        ref_videos = _resolve_paths(step_inputs.get("ref_videos"), task_dir)

        # 音频输入连接时，强制保留原声
        if audio_paths:
            sound = "keep_original"

        # --- 4. 推断生成类型(mode) ---
        if not mode:
            if len(ref_videos) >= 1:
                mode = "autovideo"
            elif len(ref_images) >= 2:
                mode = "flf2video"
            elif len(ref_images) == 1:
                mode = "img2video"
            else:
                mode = "txt2video"

        # 校验所选模型是否支持该模式
        from backend.videogen.videogen_interface_manager import get_videogen_interface_manager
        mgr = get_videogen_interface_manager()
        meta = mgr.get_model_metadata(interface).get(model, {}) if model else {}
        supported_modes = meta.get("modes", []) if meta else []
        if supported_modes and mode not in supported_modes:
            raise ValueError(
                f"模型 {model} 不支持生成类型 {mode}，支持的类型：{', '.join(supported_modes)}"
            )

        if callback:
            callback(20, f"生成视频（{mode}, {model or '默认'}, {resolution}, {duration}s）...")

        # --- 5. 获取引擎并生成 ---
        from backend.videogen.videogen_factory import get_videogen_engine
        engine = get_videogen_engine(interface)
        if not engine:
            raise RuntimeError(f"无法创建视频生成引擎：接口 '{interface}' 不存在或未启用。")

        temp_dir = os.path.join(task_dir, "output", f"_videogen_temp_{node_id}")
        os.makedirs(temp_dir, exist_ok=True)

        if callback:
            callback(40, "调用视频生成引擎...")

        extra = {}
        if optimize_prompt is not None:
            extra["optimize_prompt"] = bool(optimize_prompt)
        if poll_timeout:
            extra["poll_timeout"] = int(poll_timeout)

        try:
            result_paths = engine.generate(
                prompt=final_prompt,
                output_dir=temp_dir,
                model=model,
                mode=mode,
                resolution=resolution,
                duration=duration,
                num_videos=num_videos,
                ref_images=ref_images if ref_images else None,
                ref_videos=ref_videos if ref_videos else None,
                audio=sound,
                **extra,
            )
        except Exception as e:
            raise RuntimeError(f"视频生成失败：{e}") from e

        if not result_paths:
            raise RuntimeError("视频生成未返回结果，请检查接口配置与日志。")

        if callback:
            callback(80, f"已生成 {len(result_paths)} 个视频，正在重命名...")

        # --- 6. 重命名输出文件 ---
        output_dir = os.path.join(task_dir, "output")
        os.makedirs(output_dir, exist_ok=True)
        final_paths = []
        for i, src_path in enumerate(result_paths):
            if not os.path.exists(src_path):
                continue
            ext = os.path.splitext(src_path)[1] or ".mp4"
            dest_name = f"{output_prefix}_{i + 1}_gen_video_{node_id}{ext}"
            dest_path = os.path.join(output_dir, dest_name)
            shutil.copy2(src_path, dest_path)
            final_paths.append(f"output/{dest_name}")

        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

        if not final_paths:
            raise RuntimeError("生成的视频均未能保存。")

        if callback:
            callback(100, f"已保存 {len(final_paths)} 个视频")

        return {
            "artifacts": list(final_paths),
            "outputs": {
                "videos": final_paths,
                "video": final_paths[0] if final_paths else "",
            },
        }

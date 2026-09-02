"""Seedream 生图能力节点：每种能力一个节点，统一调用 seedream_wrapper。

节点 id 与能力映射：
  seedream_txt2img    文生图（txt2img）
  seedream_img2img    图生图（img2img）
  seedream_fusion     多图融合（fusion）
  seedream_grid       组图生成（grid / sequential_image_generation）
  seedream_websearch  联网搜索生图（websearch / tools=[web_search]）
  seedream_layer      图层拆分（img2img + layer_decomposition，需 5.0 Pro）

产物统一落盘到 <task_dir>/cache/images，文件名格式：
  <提示词前 15 字符>_<node_id>[_<序号>].<ext>
支持「流式输出」(stream) 与「提示词优化」(optimize_prompt) 面板开关，默认开启；
流式模式下每条 SSE 事件会经 callback 上报到节点进度条下方实时显示。
"""
import os
import re
import json
import shutil
import logging
from typing import Callable, Optional

from backend.steps.base_step import BaseStep

logger = logging.getLogger(__name__)


def _get_seedream_interface_default_model() -> str:
    """当节点未显式选择模型时，回退到「字节 Seedream」图像生成接口的默认模型设置。

    接口以 sdk_module 标识（id 为生成型 UUID，不硬编码）。
    """
    try:
        from backend.imagegen.imagegen_interface_manager import (
            get_imagegen_interface_manager,
        )
        mgr = get_imagegen_interface_manager()
        for iface in mgr.get_enabled():
            cfg = iface.get("config", {}) or {}
            if cfg.get("sdk_module") == "backend.imagegen.sdk.seedream_wrapper":
                dm = (cfg.get("default_model") or "").strip()
                if dm:
                    return dm
    except Exception as e:
        logger.warning("读取 Seedream 接口默认模型失败: %s", e)
    return ""


def _read_input_as_text(value, task_dir: str = "") -> str:
    """解析文本输入：若是文件路径则读内容，否则原样返回。"""
    if not value or not isinstance(value, str):
        return str(value) if value else ""
    candidate = value.strip()
    if os.path.isfile(candidate):
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return candidate
    if task_dir:
        rel = os.path.join(task_dir, candidate)
        if os.path.isfile(rel):
            try:
                with open(rel, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception:
                return candidate
    return value.strip()


def _sanitize_prefix(prompt: str) -> str:
    """取提示词前 15 字符并清洗为合法文件名片段。"""
    p = (prompt or "").replace("\r", " ").replace("\n", " ").strip()
    p = p[:15]
    p = re.sub(r'[\\/:*?"<>|\t]', "_", p)
    p = p.strip().replace(" ", "_")
    return p or "seedream"


def _copy_seed(src: str, cache_dir: str, name_stem: str) -> str:
    """把单张图片/坐标文件复制到 cache/images，返回相对路径（失败返回空串）。"""
    if not src or not os.path.exists(src):
        return ""
    ext = os.path.splitext(src)[1] or ".png"
    dest = os.path.join(cache_dir, f"{name_stem}{ext}")
    shutil.copy2(src, dest)
    return os.path.join("cache", "images", os.path.basename(dest))


def _get_api_key_from_env_or_interface() -> str:
    """API Key 优先级：环境变量 ARK_API_KEY > Seedream 接口配置（config.sdk_api_key / api_key）。"""
    from backend.imagegen.sdk import seedream_sdk
    api_key = seedream_sdk._get_api_key("")
    if api_key:
        return api_key
    try:
        from backend.imagegen.imagegen_interface_manager import (
            get_imagegen_interface_manager,
        )
        mgr = get_imagegen_interface_manager()
        for iface in mgr.get_enabled():
            if iface.get("type") != "sdk":
                continue
            cfg = iface.get("config", {})
            module = cfg.get("sdk_module", "")
            package = cfg.get("sdk_package", "")
            if "seedream" in module.lower() or "seedream" in package.lower():
                key = cfg.get("sdk_api_key", "") or cfg.get("api_key", "")
                if key:
                    return key
    except Exception as e:
        logger.warning("读取 Seedream 接口配置失败: %s", e)
    return ""


def _resolve_refs(value, task_dir: str = ""):
    """把参考图输入（字符串路径 / 路径列表 / 逗号或 JSON 列表）解析为绝对路径列表。"""
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        items = list(value)
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        if s.startswith("[") or "," in s:
            try:
                items = json.loads(s)
            except Exception:
                items = [x for x in s.split(",") if x.strip()]
        else:
            items = [s]
    else:
        items = []
    resolved = []
    for it in items:
        if not isinstance(it, str):
            continue
        it = it.strip()
        if not it:
            continue
        if os.path.isabs(it) and os.path.isfile(it):
            resolved.append(it)
        elif task_dir and os.path.isfile(os.path.join(task_dir, it)):
            resolved.append(os.path.join(task_dir, it))
    return resolved


class S_SeedreamBase(BaseStep):
    step_id = "seedream_base"
    step_name = "Seedream 生图"
    dependencies = []
    # 子类覆盖
    capability = "txt2img"
    need_refs = False
    layer_decomposition = False

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        d = os.path.join(task_dir, "cache", "images")
        if not os.path.isdir(d) or not node_id:
            return False
        for f in os.listdir(d):
            if f"_{node_id}" in f:
                return True
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        from backend.imagegen.sdk import seedream_wrapper

        node_id = getattr(self, "_node_id", "unknown")
        config = getattr(self, "_node_config", {}) or {}
        inputs = getattr(self, "_step_inputs", {}) or {}

        # 1. 提示词：自定义提示词优先，否则取连线文本
        custom_enabled = bool(config.get("custom_prompt_enabled", False))
        prompt = (config.get("custom_prompt", "") or "").strip() if custom_enabled else ""
        if not prompt:
            prompt = _read_input_as_text(inputs.get("text", ""), task_dir)
        if not prompt:
            raise ValueError(
                "提示词为空：请连接文本输入，或在面板中开启「自定义提示词」并填写。")

        stream_on = bool(config.get("stream_output", True))
        optimize_on = bool(config.get("optimize_prompt", True))
        model = config.get("model") or _get_seedream_interface_default_model() or seedream_wrapper.DEFAULT_MODEL
        resolution = config.get("resolution") or "auto"
        if resolution == "auto":
            resolution = "2K"
        aspect_ratio = config.get("aspect_ratio", "1:1")
        num_images = int(config.get("num_images", 1) or 1)
        output_format = config.get("output_format", "png") or "png"
        watermark = bool(config.get("watermark", False))

        # 2. 参考图（支持 image1..image5 多个输入口，按实际连接组装成列表）
        refs = []
        if self.need_refs:
            for key in ("image", "image1", "image2", "image3", "image4", "image5"):
                val = inputs.get(key)
                if val:
                    refs.extend(_resolve_refs(val, task_dir))
            if not refs:
                raise ValueError("该 Seedream 能力需要参考图输入，但未获取到有效图片。")

        if callback:
            callback(10, f"Seedream 准备中（{self.capability} / {model}）...")

        # 3. 流式消息转发：进度条下方实时显示
        gen_count = [0]

        def on_progress(msg: str):
            # 同时打印到子进程 stdout -> 经 @LOG@ 协议进入前端 logLines（进度条下方滚动区）
            try:
                print(msg)
            except Exception:
                pass
            if callback:
                gen_count[0] += 1
                pct = min(95, 30 + gen_count[0] * 8)
                callback(pct, msg)

        api_key = _get_api_key_from_env_or_interface()
        kwargs = dict(
            negative_prompt="",
            resolution=resolution,
            aspect_ratio=aspect_ratio,
            num_images=num_images,
            ref_images=refs if refs else None,
            api_key=api_key,
            mode=self.capability,
            output_format=output_format,
            watermark=watermark,
            stream=stream_on,
            on_progress=on_progress,
        )
        if self.layer_decomposition:
            kwargs["layer_decomposition"] = True
            kwargs["model"] = model or "doubao-seedream-5-0-pro-260128"
        if optimize_on:
            kwargs["optimize_prompt_options_mode"] = "standard"
        else:
            kwargs["optimize_prompt_options_mode"] = None

        temp_dir = os.path.join(task_dir, "cache", "_seedream_temp", node_id)
        os.makedirs(temp_dir, exist_ok=True)
        cache_dir = os.path.join(task_dir, "cache", "images")
        os.makedirs(cache_dir, exist_ok=True)

        if callback:
            callback(20, "调用 Seedream 接口生成图片...")

        layer_detail = None
        try:
            if self.layer_decomposition:
                # 图层拆分：单次请求，返回结构化结果（底图 + 图层 + 坐标）
                detail = seedream_wrapper.generate(
                    prompt=prompt, output_dir=temp_dir, model=model,
                    raise_on_error=True, **kwargs)
                layer_detail = detail if isinstance(detail, dict) else None
                result_paths = (detail.get("images") if isinstance(detail, dict)
                                else (detail or []))
            elif self.capability == "grid":
                # 组图模式：单次请求通过 sequential_image_generation 产出多张
                result_paths = seedream_wrapper.generate(
                    prompt=prompt, output_dir=temp_dir, model=model,
                    raise_on_error=True, **kwargs)
            else:
                # 其余模式：单请求单图，按 num_images 循环多次调用
                result_paths = []
                for n in range(num_images):
                    if callback:
                        callback(20 + int(60 * n / max(1, num_images)),
                                 f"生成第 {n + 1}/{num_images} 张...")
                    part = seedream_wrapper.generate(
                        prompt=prompt, output_dir=temp_dir, model=model,
                        raise_on_error=True, **kwargs)
                    if part:
                        result_paths.extend(part if isinstance(part, list) else [])
        except Exception as e:
            raise RuntimeError(f"Seedream 生成失败: {e}") from e

        if not result_paths:
            raise RuntimeError("Seedream 未返回任何图片（请检查 API Key / 模型 / 参数）。")

        prefix = _sanitize_prefix(prompt)
        node_prefix = f"{prefix}_{node_id}"

        # 图层拆分：结构化保存 底图 / 图层列表 / 坐标 json
        if self.layer_decomposition and isinstance(layer_detail, dict):
            base_rel = _copy_seed(layer_detail.get("base"), cache_dir, f"{node_prefix}_base")
            layer_rels = []
            for li, lyr in enumerate(layer_detail.get("layers") or []):
                lp = lyr.get("path") if isinstance(lyr, dict) else lyr
                if lp:
                    layer_rels.append(_copy_seed(lp, cache_dir, f"{node_prefix}_layer_{li + 1}"))
            coords_rel = _copy_seed(layer_detail.get("coords_path"), cache_dir, f"{node_prefix}_coords")
            final_paths = [p for p in ([base_rel] + layer_rels + [coords_rel]) if p]
            if not final_paths:
                raise RuntimeError("Seedream 图层拆分成功，但产物保存失败。")
            if callback:
                callback(100, f"已保存底图 + {len(layer_rels)} 个图层 + 坐标数据到 cache/images")
            return {
                "artifacts": list(final_paths),
                "outputs": {
                    "base": base_rel,
                    "layers": layer_rels,
                    "coords": coords_rel,
                },
            }

        # 其余模式：重命名为 <提示词前15字符>_<node_id>[_<序号>].<ext>
        multi = len(result_paths) > 1
        final_paths = []
        for i, src in enumerate(result_paths):
            if not os.path.exists(src):
                continue
            ext = os.path.splitext(src)[1] or ".png"
            name = f"{node_prefix}_{i + 1}{ext}" if multi else f"{node_prefix}{ext}"
            dest = os.path.join(cache_dir, name)
            shutil.copy2(src, dest)
            final_paths.append(os.path.join("cache", "images", name))

        shutil.rmtree(temp_dir, ignore_errors=True)

        if not final_paths:
            raise RuntimeError("Seedream 生成成功，但图片保存失败。")

        if callback:
            callback(100, f"已保存 {len(final_paths)} 张图片到 cache/images")

        return {
            "artifacts": list(final_paths),
            "outputs": {
                "images": list(final_paths),
                "text": final_paths[0] if final_paths else "",
            },
        }


class S_SeedreamTxt2Img(S_SeedreamBase):
    step_id = "seedream_txt2img"
    step_name = "Seedream文生图"
    capability = "txt2img"
    need_refs = False
    layer_decomposition = False


class S_SeedreamImg2Img(S_SeedreamBase):
    step_id = "seedream_img2img"
    step_name = "Seedream图生图"
    capability = "img2img"
    need_refs = True
    layer_decomposition = False


class S_SeedreamFusion(S_SeedreamBase):
    step_id = "seedream_fusion"
    step_name = "Seedream多图融合"
    capability = "fusion"
    need_refs = True
    layer_decomposition = False


class S_SeedreamGrid(S_SeedreamBase):
    step_id = "seedream_grid"
    step_name = "Seedream组图生成"
    capability = "grid"
    need_refs = False
    layer_decomposition = False


class S_SeedreamWebSearch(S_SeedreamBase):
    step_id = "seedream_websearch"
    step_name = "Seedream联网搜索生图"
    capability = "websearch"
    need_refs = False
    layer_decomposition = False


class S_SeedreamLayer(S_SeedreamBase):
    step_id = "seedream_layer"
    step_name = "Seedream图层拆分"
    capability = "img2img"
    need_refs = True
    layer_decomposition = True

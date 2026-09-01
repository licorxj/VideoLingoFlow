"""Seedance 视频生成能力节点：每种能力一个节点，统一调用 seedance_wrapper。

节点 id 与能力映射（命名沿用「即梦」消费品牌前缀，底层为火山方舟 Seedance）：
  seedance_txt2video   即梦-文生视频（txt2video）
  seedance_img2video   即梦-图生视频（首帧，img2video）
  seedance_flf2video   即梦-图生视频（首尾帧，flf2video）
  seedance_autovideo   即梦-全模态参考生视频（autovideo：图+视频+音频）

产物统一落盘到 <task_dir>/cache/videos，文件名格式：
  <提示词前 15 字符>_<node_id>[_<序号>].<ext>

输出：
  - videos   : 生成的视频列表（相对路径）
  - video    : 首个视频路径
  - params   : 生成参数 JSON 相对路径（内含 task_id / 请求摘要 / 产物 URL）
  - task_id  : 最近一次提交的任务 id（前端「查询生成进度」按钮直接消费）

优先历史记录开关（node_config.prefer_history）：打开后，后端执行时先检查本节点是否已有
记录 JSON 且含 task_id；有则直接按 task_id 查询任务并下载产物，避免工作流重复发起请求。
"""
import os
import re
import json
import shutil
import logging
from typing import Callable, Optional

from backend.steps.base_step import BaseStep

logger = logging.getLogger(__name__)


def _read_input_as_text(value, task_dir: str = "") -> str:
    """解析文本输入：若是 .txt 文件路径则读内容，否则原样返回。"""
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
    return p or "seedance"


def _resolve_refs(value, task_dir: str = ""):
    """把参考素材输入（字符串路径 / 路径列表 / 逗号或 JSON 列表）解析为绝对路径列表。"""
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


def _get_api_key_from_env_or_interface() -> str:
    """API Key 优先级：环境变量 ARK_API_KEY > Seedance 视频接口配置（sdk_api_key / api_key）。"""
    from backend.videogen.sdk import seedance_sdk
    api_key = seedance_sdk._get_api_key("")
    if api_key:
        return api_key
    try:
        from backend.videogen.videogen_interface_manager import (
            get_videogen_interface_manager,
        )
        mgr = get_videogen_interface_manager()
        for iface in mgr.get_enabled():
            if iface.get("type") != "sdk":
                continue
            cfg = iface.get("config", {})
            module = cfg.get("sdk_module", "")
            package = cfg.get("sdk_package", "")
            if "seedance" in module.lower() or "seedance" in package.lower():
                key = cfg.get("sdk_api_key", "") or cfg.get("api_key", "")
                if key:
                    return key
    except Exception as e:
        logger.warning("读取 Seedance 接口配置失败: %s", e)
    return ""


def _history_path(task_dir: str, node_id: str) -> str:
    return os.path.join(task_dir, "cache", "seedance", f"{node_id}_params.json")


class S_SeedanceBase(BaseStep):
    step_id = "seedance_base"
    step_name = "Seedance 视频生成"
    dependencies = []
    # 子类覆盖
    capability = "txt2video"
    need_refs = False
    ref_ports = 1  # autovideo 用 image/video/audio 多类型输入口

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        d = os.path.join(task_dir, "cache", "videos")
        if not os.path.isdir(d) or not node_id:
            return False
        for f in os.listdir(d):
            if f"_{node_id}" in f:
                return True
        return False

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    # ── 优先历史记录：按已记录 task_id 查询并下载 ──────────────────────────────
    def _try_history(self, task_dir: str, node_id: str, api_key: str,
                     cache_dir: str, callback: Optional[Callable]) -> Optional[dict]:
        """若开启优先历史记录且有可用 task_id，则查询任务并复用产物。否则返回 None。"""
        config = getattr(self, "_node_config", {}) or {}
        if not config.get("prefer_history"):
            return None
        hp = _history_path(task_dir, node_id)
        if not os.path.exists(hp):
            return None
        try:
            with open(hp, "r", encoding="utf-8") as f:
                hist = json.load(f)
        except Exception as e:
            logger.warning("Seedance: 读取历史记录失败: %s", e)
            return None
        task_id = hist.get("task_id")
        if not task_id:
            return None

        from backend.videogen.sdk import seedance_sdk
        if callback:
            callback(15, f"优先历史记录：查询任务 {task_id} ...")
        try:
            task = seedance_sdk.query_task(task_id, api_key=api_key)
        except Exception as e:
            logger.warning("Seedance: 历史任务查询失败，转从头生成: %s", e)
            return None
        status = task.get("status")
        if status != "succeeded":
            logger.info("Seedance: 历史任务状态=%s（非 succeeded），转从头生成", status)
            return None

        content = task.get("content") or {}
        if not content.get("video_url") and not content.get("last_frame_url"):
            logger.warning("Seedance: 历史任务无可用产物 URL，转从头生成")
            return None

        os.makedirs(cache_dir, exist_ok=True)
        prefix = _sanitize_prefix(hist.get("prompt", ""))
        node_prefix = f"{prefix}_{node_id}"
        saved = []
        # 主视频
        if content.get("video_url"):
            try:
                path = seedance_sdk._download(content["video_url"], cache_dir, 0, "mp4")
                final = os.path.join(cache_dir, f"{node_prefix}.mp4")
                if os.path.exists(path) and path != final:
                    shutil.move(path, final)
                saved.append(os.path.join("cache", "videos", os.path.basename(final)))
            except Exception as e:
                logger.warning("Seedance: 历史视频下载失败 %s: %s", content["video_url"], e)
        # 尾帧
        if content.get("last_frame_url"):
            try:
                path = seedance_sdk._download(content["last_frame_url"], cache_dir, 1, "png")
                final = os.path.join(cache_dir, f"{node_prefix}_lastframe.png")
                if os.path.exists(path) and path != final:
                    shutil.move(path, final)
                saved.append(os.path.join("cache", "videos", os.path.basename(final)))
            except Exception as e:
                logger.warning("Seedance: 历史尾帧下载失败 %s: %s", content["last_frame_url"], e)

        if not saved:
            return None
        if callback:
            callback(100, f"优先历史记录：已复用任务 {task_id} 产物")
        return {
            "artifacts": list(saved),
            "outputs": {
                "videos": saved,
                "video": saved[0],
                "params": os.path.join("cache", "seedance", f"{node_id}_params.json"),
                "task_id": task_id,
            },
        }

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        from backend.videogen.sdk import seedance_wrapper

        node_id = getattr(self, "_node_id", "unknown")
        config = getattr(self, "_node_config", {}) or {}
        inputs = getattr(self, "_step_inputs", {}) or {}

        # 1. 提示词
        custom_enabled = bool(config.get("custom_prompt_enabled", False))
        prompt = (config.get("custom_prompt", "") or "").strip() if custom_enabled else ""
        if not prompt:
            prompt = _read_input_as_text(inputs.get("text", ""), task_dir)
        if not prompt:
            raise ValueError("提示词为空：请连接文本输入，或在面板中开启「自定义提示词」并填写。")

        model = config.get("model") or seedance_wrapper.DEFAULT_MODEL
        resolution = config.get("resolution") or "720P"
        ratio = config.get("ratio") or "16:9"
        duration = int(config.get("duration", 5) or 5)
        frames = config.get("frames")
        num_videos = int(config.get("num_videos", 1) or 1)
        output_format = config.get("output_format", "mp4") or "mp4"
        watermark = config.get("watermark")
        audio = config.get("audio", "on")
        seed = config.get("seed")
        camera_fixed = config.get("camera_fixed")
        return_last_frame = config.get("return_last_frame")
        draft = config.get("draft")
        service_tier = config.get("service_tier")
        web_search = config.get("web_search")
        priority = config.get("priority")
        safety_identifier = config.get("safety_identifier")
        callback_url = config.get("callback_url")
        poll_timeout = config.get("poll_timeout")

        # 2. 参考素材
        ref_images, ref_videos, ref_audios = [], [], []
        if self.need_refs or self.capability == "autovideo":
            if self.capability == "autovideo":
                # 参考图列表输入：把传入的列表包装成 image1、image2、… 序列，
                # 由 build_content 逐个以 reference_image 角色提交（视频/音频同理）
                ref_images = _resolve_refs(inputs.get("image"), task_dir)
                ref_videos = _resolve_refs(inputs.get("video"), task_dir)
                ref_audios = _resolve_refs(inputs.get("audio"), task_dir)
            elif self.capability in ("img2video", "flf2video"):
                # 支持 image / image1 / image2 ... 多输入口
                keys = ["image", "image1", "image2", "image3", "image4", "image5"]
                for k in keys:
                    v = inputs.get(k)
                    if v:
                        ref_images.extend(_resolve_refs(v, task_dir))
                if self.capability == "img2video" and len(ref_images) > 1:
                    ref_images = ref_images[:1]
                if self.capability == "flf2video" and len(ref_images) < 2:
                    raise ValueError("图生视频-首尾帧需要 2 张参考图（首尾帧）。")
                if self.capability == "img2video" and not ref_images:
                    raise ValueError("图生视频-首帧需要 1 张参考图。")
            else:
                # fusion 类（本实现未启用）
                ref_images = _resolve_refs(inputs.get("image"), task_dir)

        if self.capability == "autovideo" and not (ref_images or ref_videos or ref_audios):
            raise ValueError("全模态参考生视频需要至少 1 个参考素材（图/视频/音频）。")

        api_key = _get_api_key_from_env_or_interface()

        # 3. 优先历史记录
        cache_dir = os.path.join(task_dir, "cache", "videos")
        hist_result = self._try_history(task_dir, node_id, api_key, cache_dir, callback)
        if hist_result is not None:
            return hist_result

        if callback:
            callback(10, f"Seedance 准备中（{self.capability} / {model}）...")

        # 4. 进度转发
        def on_progress(msg: str):
            try:
                print(msg)
            except Exception:
                pass
            if callback:
                callback(40, msg)

        temp_dir = os.path.join(task_dir, "cache", "_seedance_temp", node_id)
        os.makedirs(temp_dir, exist_ok=True)
        os.makedirs(cache_dir, exist_ok=True)

        kwargs = dict(
            resolution=resolution,
            ratio=ratio,
            duration=duration,
            num_videos=num_videos,
            ref_images=ref_images if ref_images else None,
            ref_videos=ref_videos if ref_videos else None,
            ref_audios=ref_audios if ref_audios else None,
            audio=audio,
            api_key=api_key,
            mode=self.capability,
            output_format=output_format,
            watermark=watermark,
            on_progress=on_progress,
            return_detail=True,
        )
        for k, v in (
            ("frames", frames), ("seed", seed), ("camera_fixed", camera_fixed),
            ("return_last_frame", return_last_frame), ("draft", draft),
            ("service_tier", service_tier), ("web_search", web_search),
            ("priority", priority), ("safety_identifier", safety_identifier),
            ("callback_url", callback_url), ("poll_timeout", poll_timeout),
        ):
            if v is not None and v != "":
                kwargs[k] = v

        if callback:
            callback(20, "调用 Seedance 接口生成视频...")

        try:
            detail = seedance_wrapper.generate(
                prompt=prompt, output_dir=temp_dir, model=model,
                raise_on_error=True, **kwargs)
        except Exception as e:
            raise RuntimeError(f"Seedance 生成失败: {e}") from e

        if not detail or not detail.get("videos"):
            raise RuntimeError("Seedance 未返回任何视频（请检查 API Key / 模型 / 参数）。")

        task_id = detail.get("task_id")
        prefix = _sanitize_prefix(prompt)
        node_prefix = f"{prefix}_{node_id}"
        final_paths = []
        for i, src in enumerate(detail["videos"]):
            if not os.path.exists(src):
                continue
            ext = os.path.splitext(src)[1] or ".mp4"
            name = f"{node_prefix}_{i + 1}{ext}" if len(detail["videos"]) > 1 else f"{node_prefix}{ext}"
            dest = os.path.join(cache_dir, name)
            shutil.copy2(src, dest)
            final_paths.append(os.path.join("cache", "videos", name))

        if not final_paths:
            raise RuntimeError("Seedance 生成成功，但视频保存失败。")

        # 5. 记录生成参数 JSON（含 task_id，供「查询生成进度」按钮与优先历史记录使用）
        params = {
            "task_id": task_id,
            "node_id": node_id,
            "mode": self.capability,
            "model": model,
            "prompt": prompt,
            "resolution": resolution,
            "ratio": ratio,
            "duration": duration,
            "num_videos": num_videos,
            "output_format": output_format,
            "video_url": detail.get("video_url"),
            "last_frame_url": detail.get("last_frame_url"),
            "videos": final_paths,
            "created_at": __import__("datetime").datetime.now().isoformat(),
        }
        sd_dir = os.path.join(task_dir, "cache", "seedance")
        os.makedirs(sd_dir, exist_ok=True)
        params_path = os.path.join(sd_dir, f"{node_id}_params.json")
        with open(params_path, "w", encoding="utf-8") as f:
            json.dump(params, f, ensure_ascii=False, indent=2)

        shutil.rmtree(temp_dir, ignore_errors=True)

        if callback:
            callback(100, f"已保存 {len(final_paths)} 个视频到 cache/videos")

        return {
            "artifacts": list(final_paths) + [os.path.join("cache", "seedance", f"{node_id}_params.json")],
            "outputs": {
                "videos": final_paths,
                "video": final_paths[0],
                "params": os.path.join("cache", "seedance", f"{node_id}_params.json"),
                "task_id": task_id,
            },
        }


class S_SeedanceTxt2Video(S_SeedanceBase):
    step_id = "seedance_txt2video"
    step_name = "即梦-文生视频"
    capability = "txt2video"
    need_refs = False


class S_SeedanceImg2Video(S_SeedanceBase):
    step_id = "seedance_img2video"
    step_name = "即梦-图生视频"
    capability = "img2video"
    need_refs = True
    ref_ports = 1


class S_SeedanceFlf2Video(S_SeedanceBase):
    step_id = "seedance_flf2video"
    step_name = "即梦-图生视频(首尾帧)"
    capability = "flf2video"
    need_refs = True
    ref_ports = 2


class S_SeedanceAutoVideo(S_SeedanceBase):
    step_id = "seedance_autovideo"
    step_name = "即梦-全模态参考生视频"
    capability = "autovideo"
    need_refs = True
    ref_ports = 3

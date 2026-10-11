"""Seedance 视频生成能力节点：每种能力一个节点，统一调用 seedance_wrapper。

节点 id 与能力映射（命名沿用「即梦」消费品牌前缀，底层为火山方舟 Seedance）：
  seedance_txt2video   即梦-文生视频（txt2video）
  seedance_img2video   即梦-图生视频（首帧，img2video）
  seedance_flf2video   即梦-图生视频（首尾帧，flf2video）
  seedance_autovideo   即梦-全模态参考生视频（autovideo：图+视频+音频）

参考素材输入口（端口声明见 backend/config/builtin_node_types.py 的 _seedance_node）：
  - seedance_img2video   参考图1~4：参考图1 作首帧（first_frame），参考图2~4 作参考图（reference_image）。
                          本节点不产生尾帧；需精确指定尾帧请用 seedance_flf2video。
  - seedance_flf2video   参考图1（首帧） + 参考图2（尾帧），角色固定不可互换，多余的图忽略并告警。
                          需要额外参考图时请用 seedance_autovideo。
  - seedance_autovideo   参考图1~5 + 参考视频1~2 + 参考音频1~2（全部以 reference_* 角色提交）
  每个口都是独立的 type="image"/"video"/"audio" 端口（可接单张素材，也可接上游列表输出口）。
  后端按端口序号收集（空口跳过、保持顺序），再按实际数量决定提交形态：
  单张参考图 → 单图模式；多张 → 按 参考图1→5 的顺序组装成列表提交。

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
    """把参考素材输入（字符串路径 / 路径列表 / 逗号或 JSON 列表）解析为素材引用列表。

    解析结果与底层 SDK（``seedance_sdk._resolve_media``）的素材契约一致：
      - ``http(s)://`` / ``asset://`` / ``data:`` 远程或内联引用原样透传，由 SDK 侧处理；
      - 本地路径（绝对路径，或相对 task_dir 的产物相对路径）转为绝对路径后交给 SDK
        （本地视频会由 SDK 先上传方舟换 ``asset://`` 引用）。
    其余无法定位的条目直接丢弃并告警，不阻塞整条链路。
    """
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        items = list(value)
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        low = s.lower()
        if low.startswith(("http://", "https://", "asset://", "data:")):
            # 单值直传：远程 URL / asset:// / data URI
            # （data URI 自身含逗号，不能走下面的逗号分隔逻辑，否则会被拆坏）
            items = [s]
        elif s.startswith("[") or "," in s:
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
        low = it.lower()
        if low.startswith(("http://", "https://", "asset://", "data:")):
            resolved.append(it)
        elif os.path.isabs(it) and os.path.isfile(it):
            resolved.append(it)
        elif task_dir and os.path.isfile(os.path.join(task_dir, it)):
            resolved.append(os.path.join(task_dir, it))
        else:
            logger.warning("Seedance: 忽略无效参考素材 %s", it)
    return resolved


# 参考素材输入口 → 收集顺序（与 builtin_node_types.py 的 _seedance_node 端口声明一致）
IMAGE_PORT_KEYS = [f"image{i}" for i in range(1, 6)]    # 参考图1~5
VIDEO_PORT_KEYS = [f"video{i}" for i in range(1, 3)]    # 参考视频1~2
AUDIO_PORT_KEYS = [f"audio{i}" for i in range(1, 3)]    # 参考音频1~2
# 旧版单一列表口（type="list"，参考图 id 为 "image"）保留兼容，
# 使拆分前保存的工作流连线在重新执行时仍能取到素材（会追加在编号口之后）。
LEGACY_IMAGE_PORT_KEYS = ["image"]
LEGACY_VIDEO_PORT_KEYS = ["video"]
LEGACY_AUDIO_PORT_KEYS = ["audio"]


def _collect_refs(inputs: dict, port_keys, legacy_port_keys, task_dir: str = "") -> list:
    """按端口顺序收集参考素材：依次读 image1→image5（空口跳过）保持顺序，再补旧版列表口。

    单个端口内若接入的是列表（上游图片列表输出口），会把列表按序摊平到该口的位置，
    因此最终顺序始终是「参考图1 → 参考图2 → …」，与上游连线顺序一致。
    """
    out = []
    for key in list(port_keys) + list(legacy_port_keys):
        val = (inputs or {}).get(key)
        if not val:
            continue
        for ref in _resolve_refs(val, task_dir):
            if ref not in out:
                out.append(ref)
    return out


def _get_api_key_from_env_or_interface() -> str:
    """API Key 优先级：Seedance 接口配置（sdk_api_key / api_key，密钥库解析值）> 环境变量 ARK_API_KEY 兜底。"""
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
    from backend.videogen.sdk import seedance_sdk
    return seedance_sdk._get_api_key("")


def _get_seedance_interface_default_model() -> str:
    """当节点未显式选择模型时，回退到「火山方舟 Seedance」视频接口的默认模型设置。

    与 Seedream 侧同名函数保持一致：接口以 sdk_module 标识（id 为生成型 UUID，不硬编码），
    优先取接口配置里的 default_model，避免节点硬编码的模型被平台下线后失效。
    """
    try:
        from backend.videogen.videogen_interface_manager import (
            get_videogen_interface_manager,
        )
        mgr = get_videogen_interface_manager()
        for iface in mgr.get_enabled():
            cfg = iface.get("config", {}) or {}
            if cfg.get("sdk_module") == "backend.videogen.sdk.seedance_wrapper":
                dm = (cfg.get("default_model") or "").strip()
                if dm:
                    return dm
    except Exception as e:
        logger.warning("读取 Seedance 接口默认模型失败: %s", e)
    return ""


# 平台判定「模型 / 端点不存在或无权限」的错误特征（模型下线、账号未开通都会命中）
_MODEL_UNAVAILABLE_HINTS = (
    "InvalidEndpointOrModel.NotFound",
    "ModelNotOpen",
    "ModelNotFound",
    "does not exist or you do not have access",
)


def _is_model_unavailable(exc) -> bool:
    """判断异常是否为「模型不可用（已下线 / 无权限）」，用于自动回退到可用模型。"""
    text = str(exc or "")
    return any(hint.lower() in text.lower() for hint in _MODEL_UNAVAILABLE_HINTS)


def _next_model_candidates(current: str, tried) -> list:
    """模型不可用时按「接口默认模型 → SDK 默认模型」给出回退候选（排除已试过的）。"""
    from backend.videogen.sdk import seedance_sdk

    tried = {t for t in (list(tried) + [current or ""]) if t}
    candidates = []
    for m in (_get_seedance_interface_default_model(), seedance_sdk.DEFAULT_MODEL):
        if m and m not in tried and m not in candidates:
            candidates.append(m)
    return candidates


def _describe_seedance_api_error(exc, capability: str = "", ref_count: int = 0) -> str:
    """把 Seedance 错误翻译成可操作提示（模型不可用 / 多模态混用分别给出后续动作）。"""
    if _is_model_unavailable(exc):
        return (
            f"所选 Seedance 模型不可用（已下线或当前账号无权限）：{exc}。"
            "请在节点面板重新选择该火山方舟账号下可用的模型；"
            "若面板仍显示旧模型，请在「视频生成接口」设置中更新默认模型与模型列表。"
        )
    if capability == "img2video" and ref_count > 1:
        return (
            f"Seedance 图生视频（首帧 + {ref_count - 1} 张参考图）提交失败: {exc}。"
            "若当前模型不接受首帧与参考图混用，请改用「即梦-图生视频(首尾帧)」节点（2 张图），"
            "或改用「即梦-全模态参考生视频」节点承载多张参考图。"
        )
    return f"Seedance 生成失败: {exc}"


def _history_path(task_dir: str, node_id: str) -> str:
    return os.path.join(task_dir, "cache", "seedance", f"{node_id}_params.json")


class S_SeedanceBase(BaseStep):
    step_id = "seedance_base"
    step_name = "Seedance 视频生成"
    dependencies = []
    # 子类覆盖
    capability = "txt2video"
    need_refs = False
    # 端口数量由 backend/config/builtin_node_types.py 的 _seedance_node 声明（前端 schema 权威源），
    # Python 侧不镜像份数，只按端口 id 语义收集（见 IMAGE_PORT_KEYS 等常量）。

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

        # 模型：节点配置 > 接口配置的默认模型 > SDK 内置默认（避免节点硬编码模型被下线后失效）
        from backend.videogen.sdk import seedance_sdk
        model = (config.get("model")
                 or _get_seedance_interface_default_model()
                 or seedance_sdk.DEFAULT_MODEL)
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

        # 2. 参考素材：按端口序号收集（空口跳过、保持 参考图1→5 的顺序）
        ref_images, ref_videos, ref_audios = [], [], []
        if self.need_refs or self.capability == "autovideo":
            if self.capability == "autovideo":
                # 全模态：参考图 1~5 / 参考视频 1~2 / 参考音频 1~2，任意组合
                ref_images = _collect_refs(inputs, IMAGE_PORT_KEYS, LEGACY_IMAGE_PORT_KEYS, task_dir)
                ref_videos = _collect_refs(inputs, VIDEO_PORT_KEYS, LEGACY_VIDEO_PORT_KEYS, task_dir)
                ref_audios = _collect_refs(inputs, AUDIO_PORT_KEYS, LEGACY_AUDIO_PORT_KEYS, task_dir)
            elif self.capability in ("img2video", "flf2video"):
                # 支持 image / image1 / image2 ... 多输入口
                ref_images = _collect_refs(inputs, IMAGE_PORT_KEYS, LEGACY_IMAGE_PORT_KEYS, task_dir)
                if self.capability == "flf2video":
                    if len(ref_images) < 2:
                        raise ValueError("图生视频-首尾帧需要 2 张参考图（首帧/尾帧）。")
                    if len(ref_images) > 2:
                        logger.warning(
                            "Seedance 首尾帧仅使用前 2 张参考图（参考图1=首帧 / 参考图2=尾帧），"
                            "多余的参考图已忽略：%s；如需额外的参考图请改用「即梦-全模态参考生视频」节点。",
                            ref_images[2:])
                    ref_images = ref_images[:2]
                elif not ref_images:
                    raise ValueError("图生视频-首帧需要至少 1 张参考图。")
                # img2video 不在此处截断：首帧 + 其余参考图的角色分配由 SDK 的
                # build_content 完成（参考图1 → first_frame，参考图2~N → reference_image）
            else:
                # fusion 类（本实现未启用）
                ref_images = _collect_refs(inputs, IMAGE_PORT_KEYS, LEGACY_IMAGE_PORT_KEYS, task_dir)

        if self.capability == "autovideo":
            if not (ref_images or ref_videos or ref_audios):
                raise ValueError("全模态参考生视频需要至少 1 个参考素材（图/视频/音频）。")
            # 记录收集结果，便于排查「图接上了但没生效」类问题
            logger.info(
                "Seedance autovideo 参考素材：图 %d 张 / 视频 %d 个 / 音频 %d 个（提交形态：%s）",
                len(ref_images), len(ref_videos), len(ref_audios),
                "单图模式" if len(ref_images) == 1 else ("无参考图" if not ref_images else "按序列表"),
            )

        api_key = _get_api_key_from_env_or_interface()

        # 3. 优先历史记录
        cache_dir = os.path.join(task_dir, "cache", "videos")
        hist_result = self._try_history(task_dir, node_id, api_key, cache_dir, callback)
        if hist_result is not None:
            return hist_result

        if callback:
            ref_desc = f" / 参考图 {len(ref_images)} 张" if ref_images else ""
            if self.capability == "autovideo":
                ref_desc += f" / 参考视频 {len(ref_videos)} 个 / 参考音频 {len(ref_audios)} 个"
            callback(10, f"Seedance 准备中（{self.capability} / {model}{ref_desc}）...")

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

        detail = None
        tried_models = []  # 已尝试且判定不可用的模型
        while True:
            try:
                detail = seedance_wrapper.generate(
                    prompt=prompt, output_dir=temp_dir, model=model,
                    raise_on_error=True, **kwargs)
                break
            except Exception as e:
                # 模型已下线 / 当前账号无权限：自动回退到接口默认模型重试一次，
                # 让保存了过期模型 ID 的旧工作流能自愈，不至于整单失败
                candidates = (_next_model_candidates(model, tried_models)
                              if _is_model_unavailable(e) else [])
                if not candidates:
                    raise RuntimeError(
                        _describe_seedance_api_error(e, self.capability, len(ref_images))
                    ) from e
                failed_model = model
                tried_models.append(failed_model)
                model = candidates[0]
                logger.warning(
                    "Seedance: 模型 %s 不可用，自动回退到 %s 重试", failed_model, model)
                if callback:
                    callback(20, f"模型 {failed_model} 不可用，自动回退到 {model} 重试...")

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

        # 6. 可选：用 ffmpeg 抽取首条视频的尾帧为图片（服务层处理，不依赖模型能力）
        outputs = {
            "videos": final_paths,
            "video": final_paths[0],
            "params": os.path.join("cache", "seedance", f"{node_id}_params.json"),
            "task_id": task_id,
        }
        extra_artifacts = []
        if config.get("extract_last_frame"):
            try:
                from backend.utils.video_ops import extract_last_frame
                first_abs = os.path.join(task_dir, final_paths[0]) if not os.path.isabs(final_paths[0]) else final_paths[0]
                lf_name = f"last_frame_{node_id}.png"
                lf_path = os.path.join(cache_dir, lf_name)
                extract_last_frame(first_abs, lf_path)
                rel = os.path.join("cache", "videos", lf_name)
                outputs["last_frame"] = rel
                extra_artifacts.append(rel)
                if callback:
                    callback(100, f"已抽取尾帧：{lf_name}")
            except Exception as exc:
                logger.warning("Seedance: 抽取尾帧失败（已忽略）: %s", exc)

        return {
            "artifacts": list(final_paths) + [os.path.join("cache", "seedance", f"{node_id}_params.json")] + extra_artifacts,
            "outputs": outputs,
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


class S_SeedanceFlf2Video(S_SeedanceBase):
    step_id = "seedance_flf2video"
    step_name = "即梦-图生视频(首尾帧)"
    capability = "flf2video"
    need_refs = True


class S_SeedanceAutoVideo(S_SeedanceBase):
    step_id = "seedance_autovideo"
    step_name = "即梦-全模态参考生视频"
    capability = "autovideo"
    need_refs = True

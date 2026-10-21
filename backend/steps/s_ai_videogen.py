"""s_ai_videogen: AI video generation node, mirroring s_imagegen.

输入:
  - prompt : 提示词（文本，或 .txt 文件路径，后端自动判断读取）
  - image1~image4 : 参考图 1~4（每个口可接单张图，也可接上游图片列表输出口）
  - video1~video2 : 参考视频 1~2（全模态参考生视频用）
  - audio1~audio2 : 参考音频 1~2（全模态参考生视频用）
  - audio  : 音频（路径）；语义为「保留输入音频原声」，若连接则强制声音=keep_original
  - images : 旧版单一口（可接图片列表），保留兼容，收集时追加在 参考图1~4 之后

输出:
  - videos : 生成的视频列表（相对路径）
  - video  : 首个视频路径

提示词前缀(prompt_prefix) 会在后端执行时拼接到连线输入的提示词之前，作为最终提示词。
生成类型(mode) 可由用户显式选择，否则根据已连接的输入自动推断
（有参考视频/参考音频→autovideo，≥2 张参考图→flf2video，1 张参考图→img2video，否则 txt2video）。

参考图按 mode 匹配（_fit_images_to_mode），使各视频引擎拿到的图与模式语义一致：
  flf2video : 参考图1=首帧、参考图2=尾帧（多余忽略并告警；不足 2 张报错）
  img2video : 只取 参考图1 作首帧
  autovideo : 参考图1~4 全部作为参考图，按顺序提交
  txt2video : 不使用参考图

视频比例(ratio, 如 16:9 / 9:16)随resolution 一并下发引擎；仅 kieai / seedance 类引擎支持，
可灵(wuli)由分辨率决定画幅、不接受比例参数。

时长(duration) 支持手动输入：前端下拉首项为「手动输入」，此时 duration 可能是任意正整数
（含超出模型预设区间/ 小数取整），由 _to_positive_int 宽松解析，非法值回落5。
"""
import inspect
import os
import shutil
import logging
from typing import Callable, Optional

from backend.steps.base_step import BaseStep

logger = logging.getLogger(__name__)


class _VideogenCancelled(Exception):
    """on_progress 取消探针抛出的内部异常（与引擎真实故障区分，外层转 TaskCancelledError）。"""


def _make_cancel_probe(cancel_callback: Callable) -> Callable:
    """把协作取消探针包装成引擎 on_progress 回调。

    各 SDK 的 on_progress 签名不一（(msg) / (progress, status) / (progress)），
    统一用 *args 适配；只在检测到取消时抛 _VideogenCancelled，其余情况静默
    （不干扰引擎自身的进度上报）。探针查询异常不中断生成。
    """
    def _probe(*_args):
        try:
            cancelled = bool(cancel_callback())
        except Exception:  # noqa: BLE001 - 探针查询异常不中断生成
            return
        if cancelled:
            raise _VideogenCancelled()

    return _probe


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


def _to_positive_int(value, default: int) -> int:
    """宽松取正整数：空值 / 非法值 / 非正数均回落默认值。

    时长支持「手动输入」，节点配置里可能是字符串（如 "7"、"7.0"），
    非法内容不应让整个任务失败。
    """
    try:
        n = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default
    return n if n > 0 else default


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


# 参考素材输入口 → 收集顺序（与 builtin_node_types.py 的 ai_video_gen 端口声明一致）
IMAGE_PORT_KEYS = [f"image{i}" for i in range(1, 5)]    # 参考图1~4
VIDEO_PORT_KEYS = ["video1", "video2"]                   # 参考视频1~2
AUDIO_PORT_KEYS = ["audio1", "audio2"]                   # 参考音频1~2
# 旧版单一口（id="images"，可接图片列表）保留兼容，会追加在编号口之后，
# 使拆分前保存的工作流连线仍能取到素材。
LEGACY_IMAGE_PORT_KEYS = ["images"]
#音视频口无旧版单一口需要兼容。注意「audio」口是「保留原声」语义（声音开关），
#与参考音频口不同，**不可**作为 LEGACY_AUDIO_PORT_KEYS，否则会把原声误当参考音频。
LEGACY_VIDEO_PORT_KEYS: list = []
LEGACY_AUDIO_PORT_KEYS: list = []


def _collect_ports(inputs: dict, port_keys, legacy_port_keys, task_dir: str = "") -> list:
    """按端口顺序收集参考素材：依次读 image1→image4（空口跳过）保持顺序，再补旧版单一口。

    单个端口内若接入的是列表（上游图片列表输出口），会把列表按序摊平到该口的位置，
    因此最终顺序始终是「参考图1 → 参考图2 → …」，与上游连线顺序一致。
    """
    out = []
    for key in list(port_keys) + list(legacy_port_keys):
        val = (inputs or {}).get(key)
        if not val:
            continue
        for p in _resolve_paths(val, task_dir):
            if p not in out:
                out.append(p)
    return out


def _fit_images_to_mode(images, mode: str) -> list:
    """按生成类型裁剪参考图，使各引擎拿到的图与模式语义一致。

      flf2video : 参考图1=首帧、参考图2=尾帧（多余忽略并告警；不足 2 张报错）
      img2video : 只取 参考图1 作首帧（多余忽略并告警）
      autovideo : 全部保留，按 参考图1→4 顺序作为参考图提交
      txt2video : 无参考图（忽略并告警）
    """
    if not images:
        return []
    if mode == "flf2video":
        if len(images) < 2:
            raise ValueError(
                f"首尾帧模式需要 2 张参考图（当前只接收到 {len(images)} 张）："
                "请把 参考图1、参考图2 分别接到首帧与尾帧。"
            )
        if len(images) > 2:
            logger.warning(
                "AI生视频：首尾帧模式只使用前 2 张参考图（参考图1=首帧 / 参考图2=尾帧），"
                "多余的参考图已忽略：%s", images[2:])
        return images[:2]
    if mode == "img2video":
        if len(images) > 1:
            logger.warning(
                "AI生视频：单图模式只使用 参考图1 作为首帧，多余的参考图已忽略：%s", images[1:])
        return images[:1]
    if mode == "autovideo":
        return images
    logger.warning("AI生视频：文生视频模式不使用参考图，%d 张参考图已忽略", len(images))
    return []


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

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
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
        ratio = _first(node_config.get("ratio", "")) or "16:9"
        duration = _to_positive_int(node_config.get("duration"), 5)
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

        # --- 3. 解析参考素材 / 音频输入 ---
        # 按端口顺序收集（空口跳过、保持顺序），图片兼容旧版 images 列表口
        ref_images = _collect_ports(step_inputs, IMAGE_PORT_KEYS, LEGACY_IMAGE_PORT_KEYS, task_dir)
        ref_videos = _collect_ports(step_inputs, VIDEO_PORT_KEYS, LEGACY_VIDEO_PORT_KEYS, task_dir)
        ref_audios = _collect_ports(step_inputs, AUDIO_PORT_KEYS, LEGACY_AUDIO_PORT_KEYS, task_dir)
        # 「audio」口是保留原声语义：接听后强制 keep_original
        audio_paths = _resolve_paths(step_inputs.get("audio"), task_dir)

        # 音频输入连接时，强制保留原声
        if audio_paths:
            sound = "keep_original"

        # --- 4. 推断生成类型(mode) ---
        if not mode:
            if ref_videos or ref_audios:
                # 有参考视频/音频 → 全模态参考生视频（否则这些素材无接口可用）
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

        # 按生成类型裁剪参考图（首尾帧模式自动把 参考图1/2 匹配为首帧/尾帧）
        ref_images = _fit_images_to_mode(ref_images, mode)

        # 记录参考素材收集结果，便于排查「口接上了但请求里没带」类问题
        logger.info(
            "AI生视频 参考素材：mode=%s 图 %d 张 / 视频 %d 个 / 音频 %d 个（原声口=%s）",
            mode, len(ref_images), len(ref_videos), len(ref_audios),
            "已接" if audio_paths else "未接",
        )
        if mode != "autovideo" and (ref_videos or ref_audios):
            logger.warning(
                "AI生视频：生成类型为 %s，参考视频/音频不会被引擎提交（仅 autovideo 全模态支持）；"
                "如需使用请把生成类型切换为 autovideo。", mode,
            )

        if callback:
            ref_desc = ""
            if ref_images:
                ref_desc = (f"，参考图 {len(ref_images)} 张"
                            + ("（图1=首帧 / 图2=尾帧）" if mode == "flf2video" else ""))
            if ref_videos:
                ref_desc += f"，参考视频 {len(ref_videos)} 个"
            if ref_audios:
                ref_desc += f"，参考音频 {len(ref_audios)} 个"
            callback(20, f"生成视频（{mode}, {model or '默认'}, {resolution}, {ratio}, {duration}s{ref_desc}）...")

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

        # 协作取消：thread 域节点无法强杀，云引擎轮询最长 poll_timeout（默认 1800s），
        # 期间必须可停止。经引擎 on_progress 探针在每次进度轮询时查取消——仅当引擎
        # 签名支持（**kwargs 或显式 on_progress）时透传，避免 TypeError。
        # 注意：agnes 包装层会吞掉回调异常（仅日志），该路径的取消仍靠节点超时/进程杀兜底。
        cancel_probe = _make_cancel_probe(cancel_callback) if cancel_callback is not None else None
        if cancel_probe is not None:
            try:
                _params = inspect.signature(engine.generate).parameters
            except (TypeError, ValueError):
                _params = {}
            if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in _params.values()) or "on_progress" in _params:
                extra["on_progress"] = cancel_probe

        try:
            result_paths = engine.generate(
                prompt=final_prompt,
                output_dir=temp_dir,
                model=model,
                mode=mode,
                resolution=resolution,
                ratio=ratio,
                duration=duration,
                num_videos=num_videos,
                ref_images=ref_images if ref_images else None,
                ref_videos=ref_videos if ref_videos else None,
                ref_audios=ref_audios if ref_audios else None,
                audio=sound,
                **extra,
            )
        except _VideogenCancelled:
            from backend.control_plane.runtime import TaskCancelledError

            raise TaskCancelledError("user_requested")
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

        # --- 7. 可选：用 ffmpeg 抽取首条视频的尾帧为图片 ---
        outputs: dict = {
            "videos": final_paths,
            "video": final_paths[0] if final_paths else "",
        }
        extra_artifacts = []
        if node_config.get("extract_last_frame"):
            try:
                from backend.utils.video_ops import extract_last_frame
                first_abs = os.path.join(task_dir, final_paths[0]) if not os.path.isabs(final_paths[0]) else final_paths[0]
                lf_name = f"last_frame_{node_id}.png"
                lf_path = os.path.join(output_dir, lf_name)
                extract_last_frame(first_abs, lf_path)
                rel = f"output/{lf_name}"
                outputs["last_frame"] = rel
                extra_artifacts.append(rel)
                if callback:
                    callback(100, f"已抽取尾帧：{lf_name}")
            except Exception as exc:
                logger.warning("AI生视频：抽取尾帧失败（已忽略）: %s", exc)

        return {
            "artifacts": list(final_paths) + extra_artifacts,
            "outputs": outputs,
        }

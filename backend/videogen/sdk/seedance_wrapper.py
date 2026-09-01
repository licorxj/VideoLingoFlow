#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Seedance 适配层：将 VideoLingo 视频生成调用映射为 Seedance 原生异步任务请求体。

VideoLingo 通过 videogen_factory.SDKVideoGen 调用本模块的 ``generate(...)``，约定签名与
wuli_video_wrapper 一致，返回本地文件路径列表。

支持的 mode（能力类型，按官方文档）：
  txt2video : 文生视频（纯文本）
  img2video : 图生视频-首帧（1 张参考图, role=first_frame）
  flf2video : 图生视频-首尾帧（2 张参考图, role=first_frame/last_frame）
  autovideo : 全模态参考生视频（reference_image + reference_video + reference_audio 任意组合）

专属参数（经 kwargs / extra_args 透传）：
  ratio / duration / frames / seed / camera_fixed / watermark / generate_audio /
  output_format / omni_reference_task_type / return_last_frame / draft / service_tier /
  callback_url / priority / safety_identifier / web_search(too ls)

注意：
  - Seedance 视频任务为异步；每个任务产出 1 个视频，num_videos>1 时循环提交 N 个任务。
  - 局部能力（ratio / duration / 专属参数）会按所选模型家族自动裁剪到合法取值区间。
"""
import logging

from backend.videogen.sdk import seedance_sdk

logger = logging.getLogger(__name__)

# 各 mode 对应文档能力描述（用于接口层/前端展示能力类型）
CAPABILITY_TYPES = {
    "txt2video": "文生视频",
    "img2video": "图生视频-首帧",
    "flf2video": "图生视频-首尾帧",
    "autovideo": "全模态参考生视频（图+视频+音频）",
}


def _norm_resolution(resolution: str) -> str:
    return seedance_sdk._normalize_resolution(resolution)


def _clamp_duration(model: str, duration) -> int:
    """把 duration 裁剪到模型支持区间；非法/None 回落默认。"""
    fam = seedance_sdk._family(model)
    dmin, dmax = fam["duration"]
    try:
        d = int(duration)
    except (TypeError, ValueError):
        return dmax if fam["allow_neg1"] else dmin
    if fam["allow_neg1"] and d == -1:
        return -1
    if d < dmin:
        return dmin
    if d > dmax:
        return dmax
    return d


def _resolve_sound(audio):
    """audio -> (是否设置, 布尔)。None 表示走模型默认（不传）。"""
    if audio is None:
        return (False, None)
    if isinstance(audio, bool):
        return (True, audio)
    s = str(audio).strip().lower()
    if s in ("off", "false", "0", "no", "关闭", "model_default"):
        # model_default 视为不显式设置（跟随模型默认）
        return (False, None) if s == "model_default" else (True, False)
    return (True, True)


def _build_body(model, prompt, mode, resolution, ratio, duration, frames, api_key,
                ref_images, ref_videos, ref_audios, audio, kwargs):
    fam = seedance_sdk._family(model)
    sup = fam["supports"]

    content = seedance_sdk.build_content(
        prompt, ref_images=ref_images, ref_videos=ref_videos,
        ref_audios=ref_audios, mode=mode, api_key=api_key)
    if not content:
        raise RuntimeError("Seedance: content 为空（需要 prompt 或参考素材）")

    body = {"model": model, "content": content}

    # 分辨率
    res = _norm_resolution(resolution)
    if res in fam["resolutions"]:
        body["resolution"] = res
    else:
        # 不在支持集合内，回落到 720p（各家族均支持）
        body["resolution"] = "720p"
        logger.warning("Seedance: 模型 %s 不支持分辨率 %s，回落 720p", model, res)

    # 宽高比：图生视频-首/尾帧强制 adaptive（模型按首帧图自动适配）
    if mode in ("img2video", "flf2video"):
        body["ratio"] = "adaptive"
    else:
        body["ratio"] = ratio or fam["ratio_default"]

    # 时长 / 帧数：frames 优先级高于 duration
    if frames is not None:
        try:
            f = int(frames)
            if 29 <= f <= 289:
                body["frames"] = f
        except (TypeError, ValueError):
            pass
    if "frames" not in body:
        body["duration"] = _clamp_duration(model, duration)

    # 声音（generate_audio）
    set_audio, audio_val = _resolve_sound(audio)
    if set_audio and "generate_audio" in sup:
        body["generate_audio"] = audio_val
    elif set_audio and "generate_audio" not in sup:
        logger.warning("Seedance: 模型 %s 不支持 generate_audio，已忽略", model)

    # 水印（默认 False）
    if kwargs.get("watermark") is not None:
        body["watermark"] = bool(kwargs["watermark"])

    # 输出格式（mov 仅 2.5 支持）
    ofmt = kwargs.get("output_format") or "mp4"
    if ofmt == "mov" and "output_format_mov" in sup:
        body["output_format"] = "mov"
    elif ofmt != "mp4":
        body["output_format"] = ofmt  # 其它取值交给模型校验

    # 种子（仅 1.5/1.0 支持；2.5 无 seed 参数）
    if kwargs.get("seed") is not None and "seed" in sup:
        try:
            body["seed"] = int(kwargs["seed"])
        except (TypeError, ValueError):
            pass

    # 固定摄像头（仅 1.5/1.0 支持；参考图场景不支持）
    if kwargs.get("camera_fixed") is not None and "camera_fixed" in sup:
        body["camera_fixed"] = bool(kwargs["camera_fixed"])

    # 全模态任务类型引导（仅 2.5）
    ott = kwargs.get("omni_reference_task_type")
    if ott and "omni" in sup:
        body["omni_reference_task_type"] = ott

    # 返回尾帧
    if kwargs.get("return_last_frame") is not None and "return_last_frame" in sup:
        body["return_last_frame"] = bool(kwargs["return_last_frame"])

    # 样片模式
    if kwargs.get("draft") is not None and "draft" in sup:
        body["draft"] = bool(kwargs["draft"])

    # 服务等级（flex 离线推理，仅 1.5/1.0 支持）
    st = kwargs.get("service_tier")
    if st and (st == "flex" and "service_tier_flex" in sup or st == "default"):
        body["service_tier"] = st

    # 联网搜索工具（仅 2.5/2.0）
    if kwargs.get("web_search") and "tools_web_search" in sup:
        body["tools"] = [{"type": "web_search"}]

    # 其它透传（回调/优先级/用户标识）
    if kwargs.get("callback_url"):
        body["callback_url"] = kwargs["callback_url"]
    if kwargs.get("priority") is not None and "priority" in sup:
        try:
            body["priority"] = max(0, min(int(kwargs["priority"]), 9))
        except (TypeError, ValueError):
            pass
    if kwargs.get("safety_identifier"):
        body["safety_identifier"] = kwargs["safety_identifier"]

    return body


def generate(prompt, output_dir, model="", negative_prompt="", resolution="720P",
             ratio="16:9", duration=5, num_videos=1, ref_images=None, ref_videos=None,
             ref_audios=None, audio=None, mode="txt2video", api_key="",
             on_progress=None, raise_on_error=False, return_detail=False, **kwargs):
    """
    VideoLingo 视频生成统一入口（Seedance 适配）。

    Args:
        prompt: 文本提示词
        output_dir: 落盘目录
        model: Seedance 模型 ID（如 doubao-seedance-2-5-pro-260628）
        negative_prompt: 负向提示词（Seedance 原生不支持，忽略）
        resolution: 分辨率档位（480P/720P/1080P/4K）
        ratio: 宽高比（如 16:9；图生视频-首/尾帧强制 adaptive）
        duration: 时长（秒）
        num_videos: 生成数量（>1 时循环提交多个任务）
        ref_images: 参考图（本地路径 / URL / data URI）
        ref_videos: 参考视频（URL / asset://；本地视频需先托管）
        ref_audios: 参考音频（本地路径 / URL / data URI）
        audio: 声音开关（None 走模型默认 / True / False / "on"/"off"/"keep_original"/"model_default"）
        mode: txt2video / img2video / flf2video / autovideo
        api_key: 火山方舟 API Key（ARK_API_KEY 环境变量可兜底）
        **kwargs: frames / seed / camera_fixed / watermark / generate_audio /
                  output_format / omni_reference_task_type / return_last_frame /
                  draft / service_tier / web_search / callback_url / priority /
                  safety_identifier / poll_timeout
    Returns:
        本地视频文件路径列表
    """
    api_key = seedance_sdk._get_api_key(api_key)
    if not api_key:
        msg = "未配置 API Key（接口设置或环境变量 ARK_API_KEY）"
        if raise_on_error:
            raise RuntimeError(msg)
        logger.error("Seedance: %s", msg)
        return []

    model = model or seedance_sdk.DEFAULT_MODEL
    mode = mode or "txt2video"
    ref_images = ref_images or []
    ref_videos = ref_videos or []
    ref_audios = ref_audios or []
    num_videos = max(1, min(int(num_videos or 1), 10))

    # 能力前置校验
    if mode in ("img2video", "flf2video") and not ref_images:
        msg = f"Seedance {mode} 需要至少 1 张参考图"
        return _err(msg, raise_on_error)
    if mode == "autovideo" and not (ref_images or ref_videos or ref_audios):
        msg = "Seedance 全模态参考生视频需要至少 1 个参考素材（图/视频/音频）"
        return _err(msg, raise_on_error)

    try:
        body = _build_body(
            model, prompt, mode, resolution, ratio, duration,
            kwargs.get("frames"), api_key, ref_images, ref_videos, ref_audios,
            audio, kwargs)
    except Exception as e:
        return _err(str(e), raise_on_error)

    all_paths = []
    results = []
    poll_timeout = int(kwargs.get("poll_timeout", seedance_sdk.DEFAULT_POLL_TIMEOUT))
    for i in range(num_videos):
        if num_videos > 1 and on_progress:
            on_progress(f"正在生成第 {i + 1}/{num_videos} 个视频…")
        try:
            result = seedance_sdk.generate_video(
                body, api_key=api_key, save_dir=output_dir,
                poll_timeout=poll_timeout, on_progress=on_progress,
                raise_on_error=raise_on_error)
        except Exception as e:
            if raise_on_error:
                raise
            logger.error("Seedance: 第 %d 个视频生成失败: %s", i + 1, e)
            continue
        if result and result.get("videos"):
            all_paths.extend(result["videos"])
            results.append(result)
        else:
            logger.warning("Seedance: 第 %d 个视频无产物", i + 1)

    if not all_paths and raise_on_error:
        raise RuntimeError("Seedance: 未生成任何视频")

    # return_detail=True 时返回结构化结果（含任务 id，便于节点记录与后续查询进度）
    if return_detail:
        last = results[-1] if results else {}
        return {
            "videos": all_paths,
            "task_id": last.get("task_id"),
            "video_url": last.get("video_url"),
            "last_frame_url": last.get("last_frame_url"),
            "tasks": [r.get("task_id") for r in results if r.get("task_id")],
        }
    return all_paths


def _err(msg, raise_on_error):
    if raise_on_error:
        raise RuntimeError(msg)
    logger.error("Seedance: %s", msg)
    return []


def list_models(api_key: str = ""):
    """返回已知 Seedance 模型 ID 列表。"""
    return seedance_sdk.list_models(api_key)

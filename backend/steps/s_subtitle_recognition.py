"""s_subtitle_recognition: 调用字幕识别工具，输出 ASR 格式识别结果 JSON。

输入：视频 + 字幕区域坐标 JSON（来自「OCR字幕查找」节点）。
输出：ASR 结果格式 JSON（segments: [{id, start, end, text}]）。
运行参数：OCR 接口（模型，全局兜底）、初次抽帧间隔、字幕边界精度（毫秒）、倾角过滤阈值（度）。
"""
import json
import os
from typing import Callable, Optional

from backend.steps.base_step import BaseStep
from backend.steps.s_subtitle_position_search import _resolve_video, _build_model_options
from backend.utils.subtitle_recognition import recognize_subtitles


def _load_box_json(task_dir: str, raw: str) -> tuple:
    """读取字幕区域坐标 JSON，返回 (box dict, meta dict)。

    box 为 {"x1","y1","x2","y2"}（相对比例或像素坐标）；
    meta 含 relative / width / height / skip_head_sec / skip_tail_sec。
    兼容两种结构：{"box": {...}, ...} 或直接 {"x1","y1","x2","y2"}。
    """
    if not raw:
        raise FileNotFoundError(
            "缺少字幕区域坐标输入（json），请先连接「OCR字幕查找」节点的坐标输出"
        )
    p = raw if os.path.isabs(raw) else os.path.join(task_dir, raw)
    if not os.path.isfile(p):
        raise FileNotFoundError(f"字幕区域坐标文件不存在：{p}")
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        box = data.get("box") or {k: data.get(k) for k in ("x1", "y1", "x2", "y2")}
    else:
        box = {}
    if not box or not all(k in box for k in ("x1", "y1", "x2", "y2")):
        raise ValueError("字幕区域坐标 JSON 缺少 box 字段（需包含 x1/y1/x2/y2）")
    if isinstance(data, dict):
        meta = {
            "relative": bool(data.get("relative", False)),
            "width": data.get("width", 0),
            "height": data.get("height", 0),
            "skip_head_sec": float(data.get("skip_head_sec") or 0),
            "skip_tail_sec": float(data.get("skip_tail_sec") or 0),
        }
    else:
        meta = {"relative": False, "width": 0, "height": 0,
                "skip_head_sec": 0.0, "skip_tail_sec": 0.0}
    return box, meta


class S_SubtitleRecognition(BaseStep):
    step_id = "s_subtitle_recognition"
    step_name = "OCR字幕识别"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        return os.path.exists(os.path.join(task_dir, "cache", f"subtitle_ocr_{node_id}.json"))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        # --- 1. 解析视频路径 ---
        video_path = _resolve_video(task_dir, step_inputs)
        if not video_path:
            raise FileNotFoundError(
                "No video file found. Connect a video input or ensure input video exists in cache."
            )
        if callback:
            callback(5, f"视频：{os.path.basename(video_path)}")

        # --- 2. 解析字幕区域坐标与片头片尾数据 ---
        box, box_meta = _load_box_json(task_dir, step_inputs.get("json", ""))
        skip_head_sec = float(box_meta.get("skip_head_sec") or 0)
        skip_tail_sec = float(box_meta.get("skip_tail_sec") or 0)
        if callback:
            callback(8, f"字幕区域坐标：{box}（{'相对' if box_meta.get('relative') else '像素'}），"
                        f"片头跳过 {skip_head_sec}s，片尾跳过 {skip_tail_sec}s")

        # --- 3. 读取运行参数 ---
        model = str(node_config.get("model") or "").strip()
        model_options = _build_model_options(node_config)
        try:
            initial_interval = int(node_config.get("initial_interval") or 20)
        except (ValueError, TypeError):
            initial_interval = 20
        try:
            boundary_precision_ms = int(node_config.get("boundary_precision_ms") or 200)
        except (ValueError, TypeError):
            boundary_precision_ms = 200
        try:
            tilt_threshold_deg = float(node_config.get("tilt_threshold_deg") or 8.0)
        except (ValueError, TypeError):
            tilt_threshold_deg = 8.0

        if callback:
            callback(10, f"参数：模型={model or '全局默认'}，初检间隔={initial_interval}，"
                         f"边界精度={boundary_precision_ms}ms，倾角阈值={tilt_threshold_deg}°")

        # --- 4. 执行字幕识别（相对坐标按视频实际分辨率换算为绝对坐标） ---
        result = recognize_subtitles(
            video_path,
            box,
            model=model,
            model_options=model_options,
            initial_interval=max(1, initial_interval),
            boundary_precision_ms=max(1, boundary_precision_ms),
            tilt_threshold_deg=tilt_threshold_deg,
            skip_head_sec=skip_head_sec,
            skip_tail_sec=skip_tail_sec,
            callback=callback,
        )

        # --- 5. 落盘产物到任务缓存 ---
        cache_dir = os.path.join(task_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        json_name = f"subtitle_ocr_{node_id}.json"
        with open(os.path.join(cache_dir, json_name), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        if callback:
            callback(100, f"识别完成，共 {len(result.get('segments', []))} 条字幕")

        return {
            "artifacts": [f"cache/{json_name}"],
            "outputs": {
                "subtitle": f"cache/{json_name}",
            },
        }

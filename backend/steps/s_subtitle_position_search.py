"""s_subtitle_position_search: 定位视频字幕区域。

输入：视频。输出：标注帧图片（OCR 查找时）+ 字幕坐标 JSON（相对比例坐标）。

两种定位方式（position_mode）：
- ocr：调用字幕位置检查工具自动查找字幕区域（支持片头片尾屏蔽）；
- manual：不执行 OCR，直接使用前端手动框选的相对坐标与片头片尾数据。

运行参数：OCR 接口（模型，全局兜底）、模型版本/尺寸/自定义名、字幕方向、字幕位置、
抽帧步长、是否清理缓存、片头片尾跳过秒数。
"""
import json
import os
import shutil
from typing import Callable, Optional

from backend.steps.base_step import BaseStep
from backend.utils.subtitle_position_check import check_subtitle_position


def _build_model_options(node_config: dict) -> dict:
    """从节点配置组装 OCR 模型覆盖参数（非空字段生效，空则跟随接口默认）。"""
    options = {}
    ocr_version = str(node_config.get("ocr_version") or "").strip()
    model_type = str(node_config.get("model_type") or "").strip()
    custom_model_name = str(node_config.get("custom_model_name") or "").strip()
    if ocr_version:
        options["ocr_version"] = ocr_version
    if model_type:
        options["model_type"] = model_type
    if custom_model_name:
        options["custom_model_name"] = custom_model_name
    return options


def _resolve_video(task_dir: str, step_inputs: dict) -> str:
    """解析输入视频路径：优先节点连线输入，其次扫描任务缓存目录。"""
    raw = step_inputs.get("video", "")
    if raw:
        p = raw if os.path.isabs(raw) else os.path.join(task_dir, raw)
        if os.path.isfile(p):
            return p

    cache_dir = os.path.join(task_dir, "cache")
    if os.path.isdir(cache_dir):
        for f in sorted(os.listdir(cache_dir)):
            if f.startswith("input_video") and f.endswith(('.mp4', '.mkv', '.webm', '.avi', '.mov')):
                p = os.path.join(cache_dir, f)
                if os.path.isfile(p):
                    return p
        for f in sorted(os.listdir(cache_dir)):
            if f.endswith(('.mp4', '.mkv', '.webm', '.avi', '.mov')):
                p = os.path.join(cache_dir, f)
                if os.path.isfile(p):
                    return p
    return ""


class S_SubtitlePositionSearch(BaseStep):
    step_id = "s_subtitle_position_search"
    step_name = "OCR字幕查找"
    dependencies = []

    def check_artifact(self, task_dir: str) -> bool:
        node_id = getattr(self, "_node_id", "")
        cache_dir = os.path.join(task_dir, "cache")
        box_exists = os.path.exists(os.path.join(cache_dir, f"subtitle_box_{node_id}.json"))
        if not box_exists:
            return False
        # 手动定位模式不生成标注帧，仅需坐标 JSON
        node_config = getattr(self, "_node_config", {}) or {}
        if str(node_config.get("position_mode") or "ocr").strip() == "manual":
            return True
        return os.path.exists(os.path.join(cache_dir, f"subtitle_frame_{node_id}.png"))

    def validate_inputs(self, task_dir: str) -> bool:
        return True

    def run(self, task_dir: str, callback: Optional[Callable] = None,
            cancel_callback: Optional[Callable] = None) -> dict:
        node_id = getattr(self, "_node_id", "unknown")
        node_config = getattr(self, "_node_config", {}) or {}
        step_inputs = getattr(self, "_step_inputs", {}) or {}

        # --- 1. 读取定位方式与片头片尾跳过 ---
        position_mode = str(node_config.get("position_mode") or "ocr").strip().lower()
        if position_mode not in ("ocr", "manual"):
            position_mode = "ocr"
        try:
            skip_head_sec = max(0.0, float(node_config.get("skip_head_sec") or 0))
        except (ValueError, TypeError):
            skip_head_sec = 0.0
        try:
            skip_tail_sec = max(0.0, float(node_config.get("skip_tail_sec") or 0))
        except (ValueError, TypeError):
            skip_tail_sec = 0.0

        # --- 2. 解析视频路径（手动定位模式不强求存在） ---
        video_path = _resolve_video(task_dir, step_inputs)
        if callback:
            callback(5, f"视频：{os.path.basename(video_path) if video_path else '未解析到（手动定位可直接输出坐标）'}")

        # --- 手动定位模式：跳过 OCR 查找，直接输出相对坐标 + 片头片尾 ---
        if position_mode == "manual":
            return self._run_manual(task_dir, node_id, node_config, video_path,
                                    skip_head_sec, skip_tail_sec, callback)

        # --- 3. 读取 OCR 查找运行参数 ---
        model = str(node_config.get("model") or "").strip()
        model_options = _build_model_options(node_config)
        direction = str(node_config.get("direction") or "horizontal").strip()
        if direction not in ("horizontal", "vertical"):
            direction = "horizontal"
        position = str(node_config.get("position") or "lower").strip()
        if position not in ("upper", "lower", "ratio"):
            position = "lower"
        position_ratio = str(node_config.get("position_ratio") or "").strip()
        try:
            frame_interval = int(node_config.get("frame_interval") or 20)
        except (ValueError, TypeError):
            frame_interval = 20
        clean_cache = bool(node_config.get("clean_cache", True))

        # 位置参数：上半段/下半段 或 比例范围（如 0.6-0.8）
        region: str = position
        if position == "ratio":
            region = position_ratio if position_ratio else "0.6-0.8"

        if callback:
            callback(10, f"参数：模型={model or '全局默认'}，方向={direction}，位置={region}，"
                         f"抽帧步长={frame_interval}，片头跳过 {skip_head_sec}s，片尾跳过 {skip_tail_sec}s")

        # --- 4. 执行字幕位置检查（片头片尾时间段不抽帧识别） ---
        result = check_subtitle_position(
            video_path,
            model=model,
            model_options=model_options,
            direction=direction,
            region=region,
            frame_interval=max(1, frame_interval),
            skip_head_sec=skip_head_sec,
            skip_tail_sec=skip_tail_sec,
            keep_cache=not clean_cache,
            callback=callback,
        )

        if not result.get("success"):
            raise RuntimeError(result.get("message", "字幕位置查找失败"))

        # --- 5. 落盘产物到任务缓存 ---
        cache_dir = os.path.join(task_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)

        frame_name = f"subtitle_frame_{node_id}.png"
        json_name = f"subtitle_box_{node_id}.json"

        src_frame = result.get("frame_path", "")
        if not src_frame or not os.path.isfile(src_frame):
            raise RuntimeError("未生成字幕标注帧")
        frame_dst = os.path.join(cache_dir, frame_name)
        if os.path.abspath(src_frame) != os.path.abspath(frame_dst):
            shutil.copyfile(src_frame, frame_dst)
        else:
            frame_dst = src_frame

        box = result.get("box", {})
        payload = {
            "video": os.path.basename(video_path),
            "box": box,
            "width": result.get("width", 0),
            "height": result.get("height", 0),
            "direction": result.get("direction", direction),
            "position_mode": "ocr",
            "relative": True,
            "skip_head_sec": result.get("skip_head_sec", skip_head_sec),
            "skip_tail_sec": result.get("skip_tail_sec", skip_tail_sec),
        }
        with open(os.path.join(cache_dir, json_name), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        if callback:
            callback(100, f"字幕位置：{box}（相对比例），已输出标注帧与坐标 JSON")

        return {
            "artifacts": [f"cache/{frame_name}", f"cache/{json_name}"],
            "outputs": {
                "image": f"cache/{frame_name}",
                "json": f"cache/{json_name}",
            },
        }

    def _run_manual(self, task_dir: str, node_id: str, node_config: dict,
                    video_path: str, skip_head_sec: float, skip_tail_sec: float,
                    callback: Optional[Callable] = None) -> dict:
        """手动定位模式：不执行 OCR，直接输出前端框选的相对坐标与片头片尾数据。"""
        manual_box = node_config.get("manual_box") or {}
        try:
            box = {
                "x1": float(manual_box.get("x1", 0)),
                "y1": float(manual_box.get("y1", 0)),
                "x2": float(manual_box.get("x2", 0)),
                "y2": float(manual_box.get("y2", 0)),
            }
        except (ValueError, TypeError):
            raise ValueError("手动定位的字幕坐标无效")
        if not (0.0 <= box["x1"] < box["x2"] <= 1.0 and 0.0 <= box["y1"] < box["y2"] <= 1.0):
            raise ValueError("手动定位的字幕区域无效，请点击「打开手动定位页面」重新框选")

        # 尝试读取视频宽高（供识别节点换算），失败则留 0（识别时按实际分辨率换算）
        width = height = 0
        if video_path:
            try:
                import cv2
                cap = cv2.VideoCapture(video_path)
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                cap.release()
            except Exception:
                pass

        payload = {
            "video": os.path.basename(video_path) if video_path else "",
            "box": box,
            "width": width,
            "height": height,
            "direction": str(node_config.get("direction") or "horizontal"),
            "position_mode": "manual",
            "relative": True,
            "skip_head_sec": skip_head_sec,
            "skip_tail_sec": skip_tail_sec,
        }

        cache_dir = os.path.join(task_dir, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        json_name = f"subtitle_box_{node_id}.json"
        with open(os.path.join(cache_dir, json_name), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        if callback:
            callback(100, f"手动定位完成：字幕区域 {box}（相对比例），"
                          f"片头跳过 {skip_head_sec}s，片尾跳过 {skip_tail_sec}s")

        return {
            "artifacts": [f"cache/{json_name}"],
            "outputs": {
                "image": "",
                "json": f"cache/{json_name}",
            },
        }

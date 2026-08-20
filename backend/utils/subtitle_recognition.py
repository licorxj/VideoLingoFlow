"""视频字幕识别工具。

流程（生产者-消费者三角色 + 二分细化）：
1. 粗扫：按初次抽帧间隔对全片抽帧（必须包含尾帧），裁剪字幕区域后批量 OCR；
2. 数据分析与二分细化：相邻采样帧文本（去标点空格后）一致 → 视为同一段字幕，中间不再取值；
   不一致 → 取中间帧裁剪送 OCR，返回再分析，递归直至间隔小于阈值；
3. 边界精修：按字幕边界精度（毫秒）为步长，对每段字幕首尾向外扩展检查，得到精确起止时间；
4. 按 ASR 结果 JSON 格式返回字幕与时间轴。

执行采用生产者-消费者三角色：
- 读帧裁剪者（reader）：读取视频帧并裁剪字幕区域，放入帧队列；
- OCR 识别者（ocr worker）：从队列取裁剪帧做文字识别，放入结果队列；
- 数据分析和记录者（recorder）：消费结果，做倾角过滤、文本拼接与记录。

倾角过滤：对文本框长边计算相对水平线的倾角，超过阈值的视为非字幕。
"""
import math
import os
import queue
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional, Tuple, Union

import cv2

from backend.ocr.ocr_factory import get_ocr_engine
from backend.utils.subtitle_position_check import _resolve_interface_id, _resolve_max_workers

# ── 常量 ─────────────────────────────────────────────────────
LOG_PREFIX = "[SubtitleRecognition]"

DEFAULT_INITIAL_INTERVAL = 20        # 初次检查抽帧间隔（帧）
DEFAULT_BOUNDARY_PRECISION_MS = 200  # 字幕边界精度（毫秒）
DEFAULT_TILT_THRESHOLD_DEG = 8.0     # 字幕倾角过滤阈值（度）
REGION_PAD_PX = 5                    # 字幕区域外扩像素（提升检测召回）
MIN_BINARY_GAP_FRAMES = 2            # 二分递归停止阈值（帧间隔）
MAX_REFINE_ROUNDS = 15               # 二分细化最大轮数（防止无限循环）
MAX_EXTEND_STEPS = 600               # 边界外扩最大步数保护


def _notify(callback, percent: int, message: str):
    """打印日志并触发进度回调（遵循项目 callback(percent, message) 约定）。"""
    print(f"{LOG_PREFIX} {percent}% {message}")
    if callback:
        try:
            callback(percent, message)
        except Exception as exc:
            print(f"{LOG_PREFIX} 进度回调执行失败: {exc}")


def _normalize_text(text: str) -> str:
    """去除标点与空白（含空格、换行），仅保留字母数字与汉字，用于内容一致性比较。"""
    return re.sub(r"[\W_]+", "", text or "")


def _box_tilt_angle(box) -> float:
    """文本框长边相对水平线的倾角（度，0~90）。"""
    pts = [(float(p[0]), float(p[1])) for p in box]
    best_angle = 0.0
    best_len = -1.0
    for i in range(len(pts)):
        p1, p2 = pts[i], pts[(i + 1) % len(pts)]
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        length = math.hypot(dx, dy)
        if length > best_len:
            best_len = length
            best_angle = abs(math.degrees(math.atan2(abs(dy), abs(dx))))
    return best_angle


def _filter_and_join(txts, boxes, tilt_threshold_deg: float) -> str:
    """倾角过滤并拼接文本行：长边倾角超过阈值的框视为非字幕剔除。"""
    valid = []
    box_list = list(boxes or [])
    for idx, txt in enumerate(txts or []):
        if not txt or not txt.strip():
            continue
        box = box_list[idx] if idx < len(box_list) else None
        if box is not None and len(box) >= 2 and _box_tilt_angle(box) > tilt_threshold_deg:
            continue
        valid.append(txt.strip())
    return " ".join(valid).strip()


def _ms_to_frame(ms: float, fps: float) -> int:
    return int(round(ms / 1000.0 * fps))


# ── 生产者-消费者三角色批量识别 ────────────────────────────────
def _ocr_time_points(engine, video_path: str, box, time_points_ms: List[int],
                     max_workers: int, tilt_threshold_deg: float) -> Dict[int, str]:
    """对指定时间点批量识别（读帧裁剪者 → OCR识别者 → 数据分析和记录者）。

    返回 {time_ms: 文本}，文本已做倾角过滤与多框拼接。
    """
    results: Dict[int, str] = {}
    q_frames = queue.Queue(maxsize=max_workers * 2)
    q_ocr = queue.Queue(maxsize=max_workers * 2)

    def reader():
        """角色1：读帧裁剪者 — 读取视频帧并裁剪字幕区域入队。"""
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            for _ in range(max_workers):
                q_frames.put(None)
            return
        try:
            for t in time_points_ms:
                cap.set(cv2.CAP_PROP_POS_MSEC, float(t))
                ok, frame = cap.read()
                if not ok:
                    q_frames.put((t, None))
                    continue
                q_frames.put((t, frame[box[1]:box[3], box[0]:box[2]]))
        finally:
            cap.release()
            for _ in range(max_workers):
                q_frames.put(None)

    def ocr_worker():
        """角色2：OCR识别者 — 消费裁剪帧做识别，结果入队。"""
        while True:
            item = q_frames.get()
            if item is None:
                q_ocr.put(None)
                return
            t, img = item
            if img is None or img.size == 0:
                q_ocr.put((t, [], []))
                continue
            try:
                res = engine.recognize(img)
                q_ocr.put((t, list(res.get("txts") or []), list(res.get("boxes") or [])))
            except Exception as exc:
                print(f"{LOG_PREFIX} OCR 识别失败 t={t}ms: {exc}")
                q_ocr.put((t, [], []))

    reader_thread = threading.Thread(target=reader, daemon=True)
    reader_thread.start()

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for _ in range(max_workers):
            pool.submit(ocr_worker)

        # 角色3：数据分析和记录者（主线程）— 倾角过滤、文本拼接、记录
        done = 0
        while done < max_workers:
            item = q_ocr.get()
            if item is None:
                done += 1
                continue
            t, txts, boxes = item
            results[int(t)] = _filter_and_join(txts, boxes, tilt_threshold_deg)

    reader_thread.join()
    return results


def _ocr_single(engine, cap, t_ms: float, box, tilt_threshold_deg: float) -> str:
    """单帧识别（边界精修用）：返回倾角过滤后的文本。"""
    cap.set(cv2.CAP_PROP_POS_MSEC, float(t_ms))
    ok, frame = cap.read()
    if not ok:
        return ""
    crop = frame[box[1]:box[3], box[0]:box[2]]
    if crop.size == 0:
        return ""
    try:
        res = engine.recognize(crop)
        return _filter_and_join(res.get("txts"), res.get("boxes"), tilt_threshold_deg)
    except Exception as exc:
        print(f"{LOG_PREFIX} 单帧识别失败 t={t_ms}ms: {exc}")
        return ""


def _build_segments(points: List[Tuple[int, str]]) -> List[Tuple[int, int, str]]:
    """由采样点生成字幕段 [(start_ms, end_ms, text)]（相邻去标点空格一致视为同段）。"""
    segments = []
    i = 0
    n = len(points)
    while i < n:
        t, text = points[i]
        if not _normalize_text(text):
            i += 1
            continue
        norm = _normalize_text(text)
        j = i + 1
        while j < n and _normalize_text(points[j][1]) == norm:
            j += 1
        segments.append((points[i][0], points[j - 1][0], text))
        i = j
    return segments


def _extend_boundaries(engine, video_path: str, box, segments: List[Tuple[int, int, str]],
                       precision_ms: int, tilt_threshold_deg: float,
                       duration_ms: int, min_ms: int = 0,
                       max_ms: Optional[int] = None) -> List[Tuple[int, int, str]]:
    """按边界精度（毫秒）为步长，对字幕段首尾向外扩展检查，得到精确边界。

    min_ms / max_ms 用于限定边界扩展范围（片头片尾屏蔽段内不扩展）。
    """
    step_ms = max(1, precision_ms)
    cap = cv2.VideoCapture(video_path)
    limit_ms = duration_ms if max_ms is None else max_ms
    refined = []
    try:
        for start_ms, end_ms, text in segments:
            norm = _normalize_text(text)
            # 向前扩展首边界
            t = start_ms
            steps = 0
            while t - step_ms >= min_ms and steps < MAX_EXTEND_STEPS:
                t2 = t - step_ms
                if _ocr_single(engine, cap, t2, box, tilt_threshold_deg) == norm:
                    t = t2
                    steps += 1
                else:
                    break
            new_start = t
            # 向后扩展尾边界
            t = end_ms
            steps = 0
            while t + step_ms <= limit_ms and steps < MAX_EXTEND_STEPS:
                t2 = t + step_ms
                if _ocr_single(engine, cap, t2, box, tilt_threshold_deg) == norm:
                    t = t2
                    steps += 1
                else:
                    break
            refined.append((new_start, t, text))
    finally:
        cap.release()
    return refined


def _merge_same_text_segments(segments: List[Tuple[int, int, str]]) -> List[Tuple[int, int, str]]:
    """合并边界精修后仍相邻同文本的字幕段。"""
    if not segments:
        return []
    merged = []
    cur_start, cur_end, cur_text = segments[0]
    cur_norm = _normalize_text(cur_text)
    for s, e, text in segments[1:]:
        if _normalize_text(text) == cur_norm:
            cur_end = e
        else:
            merged.append((cur_start, cur_end, cur_text))
            cur_start, cur_end, cur_text = s, e, text
            cur_norm = _normalize_text(text)
    merged.append((cur_start, cur_end, cur_text))
    return merged


def recognize_subtitles(
    video_path: str,
    box: Union[dict, Tuple[float, float, float, float]],
    *,
    model: str = "",
    model_options: Optional[dict] = None,
    initial_interval: int = DEFAULT_INITIAL_INTERVAL,
    boundary_precision_ms: int = DEFAULT_BOUNDARY_PRECISION_MS,
    tilt_threshold_deg: float = DEFAULT_TILT_THRESHOLD_DEG,
    skip_head_sec: float = 0.0,
    skip_tail_sec: float = 0.0,
    max_workers: Optional[int] = None,
    callback: Optional[Callable] = None,
) -> dict:
    """识别视频字幕，返回 ASR 结果格式的 JSON。

    Parameters
    ----------
    video_path : str
        视频文件路径。
    box : dict | (x1, y1, x2, y2)
        字幕位置坐标，通常来自「OCR字幕查找」节点的输出 {"box": {"x1","y1","x2","y2"}}。
        支持相对比例坐标（0~1，按视频实际分辨率换算为像素）与像素坐标两种形式。
        识别前会自动外扩 5 像素并裁剪到视频范围内。
    model : str
        选用 OCR 接口 id；留空时使用全局设置 ocr.method，再兜底 rapidocr。
    model_options : dict | None
        节点级模型覆盖参数（ocr_version/model_type/custom_model_name），
        非空字段生效，空则跟随接口默认配置。
    initial_interval : int
        初次检查抽帧间隔（帧），默认 20。
    boundary_precision_ms : int
        字幕边界精度（毫秒），用于边界精细化扩展，默认 200。
    tilt_threshold_deg : float
        字幕倾角过滤阈值（度）：文本框长边倾角超过该值视为非字幕，默认 8。
    skip_head_sec : float
        片头跳过秒数，这些时间段不抽帧识别，默认 0。
    skip_tail_sec : float
        片尾跳过秒数（倒数），这些时间段不抽帧识别，默认 0。
    max_workers : Optional[int]
        并行识别线程数；不传则使用 OCR 接口配置 max_workers（默认 4）。
    callback : Optional[Callable]
        (percent: int, message: str) 进度回调。

    Returns
    -------
    dict
        ASR 结果格式：{"language": "", "segments": [{"id","start","end","text"}],
        "text": 全文}，时间为秒。
    """
    if not os.path.isfile(video_path):
        raise ValueError(f"视频文件不存在：{video_path}")

    iface_id = _resolve_interface_id(model)
    workers = _resolve_max_workers(iface_id, max_workers)

    # 视频信息
    probe = cv2.VideoCapture(video_path)
    if not probe.isOpened():
        probe.release()
        raise ValueError(f"无法打开视频文件：{video_path}")
    fps = probe.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(probe.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_ms = int(total_frames / fps * 1000)
    frame_w = int(probe.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_h = int(probe.get(cv2.CAP_PROP_FRAME_HEIGHT))
    probe.release()
    if total_frames <= 0 or frame_w <= 0 or frame_h <= 0:
        raise ValueError(f"无法读取视频信息：{video_path}")

    # 解析字幕区域：相对比例坐标（0~1）按视频实际分辨率换算为像素
    if isinstance(box, dict):
        box = (box.get("x1", 0), box.get("y1", 0), box.get("x2", 0), box.get("y2", 0))
    x1, y1, x2, y2 = (float(v) for v in box)
    if max(x1, y1, x2, y2) <= 1.0:
        x1, x2 = x1 * frame_w, x2 * frame_w
        y1, y2 = y1 * frame_h, y2 * frame_h
    x1, y1, x2, y2 = int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))
    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"非法字幕区域：{(x1, y1, x2, y2)}")

    # 片头片尾屏蔽时间范围（字幕查找与识别两个阶段均生效）
    skip_head_ms = int(max(0.0, float(skip_head_sec)) * 1000)
    skip_tail_ms = int(max(0.0, float(skip_tail_sec)) * 1000)
    active_start_ms = skip_head_ms
    active_end_ms = duration_ms - skip_tail_ms
    if active_end_ms - active_start_ms < 200:
        raise ValueError("片头/片尾跳过时间覆盖了全部视频，请减小跳过时长")
    start_frame = int(active_start_ms / 1000.0 * fps)
    end_frame = min(total_frames - 1, int(active_end_ms / 1000.0 * fps))

    # 字幕区域外扩 5 像素并裁剪到视频范围内（提升检测召回）
    x1 = max(0, x1 - REGION_PAD_PX)
    y1 = max(0, y1 - REGION_PAD_PX)
    x2 = min(frame_w, x2 + REGION_PAD_PX)
    y2 = min(frame_h, y2 + REGION_PAD_PX)

    _notify(callback, 3, f"开始字幕识别（引擎 {iface_id}，线程数 {workers}，"
                         f"区域 {(x1, y1, x2, y2)}（外扩 {REGION_PAD_PX}px），"
                         f"初检间隔 {initial_interval}，"
                         f"边界精度 {boundary_precision_ms}ms，倾角阈值 {tilt_threshold_deg}°，"
                         f"片头跳过 {skip_head_sec}s，片尾跳过 {skip_tail_sec}s）")
    _notify(callback, 5, f"视频 {fps:.2f}fps，{total_frames} 帧，时长 {duration_ms / 1000:.1f}s")

    engine = get_ocr_engine(iface_id, overrides=model_options)

    # ── 1. 粗扫：初次抽帧（覆盖片头片尾外的有效范围） + 裁剪 + 批量识别 ──
    coarse_frames = list(range(start_frame, end_frame + 1, max(1, initial_interval)))
    if not coarse_frames or coarse_frames[-1] != end_frame:
        coarse_frames.append(end_frame)
    coarse_ms = [int(f / fps * 1000) for f in coarse_frames]
    _notify(callback, 8, f"初次抽帧 {len(coarse_ms)} 个时间点（范围 {active_start_ms / 1000:.1f}s~{active_end_ms / 1000:.1f}s）")

    coarse_results = _ocr_time_points(engine, video_path, (x1, y1, x2, y2),
                                      coarse_ms, workers, tilt_threshold_deg)
    points = sorted((ms, text) for ms, text in coarse_results.items())
    _notify(callback, 35, f"粗扫完成，有效文本采样点 {sum(1 for _, t in points if _normalize_text(t))} 个")

    # ── 2. 二分细化：相邻文本不一致的区间取中间帧递归检查 ────────
    round_no = 0
    while round_no < MAX_REFINE_ROUNDS:
        round_no += 1
        mids: List[int] = []
        seen = set()
        for i in range(len(points) - 1):
            ms1, text1 = points[i]
            ms2, text2 = points[i + 1]
            if _normalize_text(text1) == _normalize_text(text2):
                continue  # 内容一致 → 同段字幕，中间不再取值
            if _ms_to_frame(ms2, fps) - _ms_to_frame(ms1, fps) <= MIN_BINARY_GAP_FRAMES:
                continue  # 间隔已小于阈值，停止细分
            mid = (ms1 + ms2) // 2
            if mid < active_start_ms or mid > active_end_ms:
                continue  # 位于片头片尾屏蔽段，不采样
            if mid not in seen and mid not in coarse_results:
                seen.add(mid)
                mids.append(mid)
        if not mids:
            break
        mid_results = _ocr_time_points(engine, video_path, (x1, y1, x2, y2),
                                       sorted(mids), workers, tilt_threshold_deg)
        points.extend((ms, text) for ms, text in mid_results.items())
        points.sort(key=lambda p: p[0])
        _notify(callback, 35 + int(30 * round_no / MAX_REFINE_ROUNDS),
                f"二分细化第 {round_no} 轮：新增采样 {len(mid_results)} 个")

    if round_no >= MAX_REFINE_ROUNDS:
        print(f"{LOG_PREFIX} 二分细化达到最大轮数 {MAX_REFINE_ROUNDS}，提前结束")

    # ── 3. 段生成 ──────────────────────────────────────────────
    segments = _build_segments(points)
    _notify(callback, 68, f"分析完成，初步字幕段 {len(segments)} 条")

    # ── 4. 边界精修：按边界精度（毫秒）步长扩展检查首尾 ──────────
    refined = _extend_boundaries(engine, video_path, (x1, y1, x2, y2),
                                 segments, boundary_precision_ms,
                                 tilt_threshold_deg, duration_ms,
                                 min_ms=active_start_ms, max_ms=active_end_ms)
    refined = _merge_same_text_segments(refined)
    _notify(callback, 92, f"边界精修完成，最终字幕 {len(refined)} 条")

    # ── 5. 组装 ASR 结果 JSON ──────────────────────────────────
    out_segments = []
    for idx, (start_ms, end_ms, text) in enumerate(refined, start=1):
        if end_ms <= start_ms:
            end_ms = start_ms + boundary_precision_ms
        out_segments.append({
            "id": idx,
            "start": round(start_ms / 1000.0, 4),
            "end": round(end_ms / 1000.0, 4),
            "text": text,
        })

    result = {
        "language": "",
        "segments": out_segments,
        "text": " ".join(seg["text"] for seg in out_segments),
    }
    _notify(callback, 100, f"字幕识别完成，共 {len(out_segments)} 条")
    return result

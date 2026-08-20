"""视频字幕位置检查工具。

流程：
1. 对视频按固定帧间隔抽帧，缓存文件保存在视频所在目录下的子目录中；
2. 按检查区域（下半段 / 上半段 / 自定义左上+右下点坐标）对帧图裁剪；
3. 多线程批量调用 rapidocr OCR 接口识别裁剪图（线程数取自 OCR 接口配置 max_workers，
   默认 4；rapidocr 无内置并行 API，因此在代码层用 ThreadPoolExecutor 并发识别）；
4. 文本行数据处理：
   - 第一轮：剔除无识别结果的帧数据；
   - 第二轮：按字幕方向筛除宽高比不符合的文本行；
   - 第三轮：同帧内重叠文本行合并为外包大框；
   - 中线聚类：对所有文本框的中线做 1D 容差聚类，取最大簇均值作为字幕中线；
   - 高度容差计数：统计中线穿过文本框的高/宽值出现次数，取排名第一、第二作为预选值，
     第二名出现次数 <= 1 时舍弃，最终取二者较大值作为字幕高度；
   - 由字幕中线 ± 高度/2 推出上下边线，取入选框的宽度坐标最小/最大作为左右边线，
     得到字幕最大外框；
5. 选取代表性帧，用粗红线绘制字幕外框，保存为视频目录下 subtitle_frame.png；
6. 将外框坐标映射回裁剪前的原视频坐标，返回标注帧路径与字幕框坐标。

整个过程的关键节点都会打印日志，并通过可选回调 callback(percent, message) 上报进度，
方便节点调用时向用户展示执行反馈。
"""
import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional, Tuple, Union

import cv2

from backend.config.config_manager import config
from backend.ocr.ocr_factory import get_ocr_engine
from backend.ocr.ocr_interface_manager import get_ocr_interface_manager

# ── 常量 ─────────────────────────────────────────────────────
DEFAULT_FRAME_INTERVAL = 20
DEFAULT_MAX_WORKERS = 4
ASPECT_RATIO_THRESHOLD = 1.5      # 方向宽高比筛选阈值（宽/高 或 高/宽 >= 该值才保留）
MIN_BOX_SIZE = 8                  # 文本行最小边长（px），过滤噪声小框
OVERLAP_EPS = 1e-3                # 重叠面积判定阈值
DRAW_COLOR = (0, 0, 255)          # BGR 粗红线
DRAW_THICKNESS = 6
FRAME_SUFFIX = ".jpg"
CROP_SUFFIX = "_crop.jpg"

LOG_PREFIX = "[SubtitleCheck]"


def _notify(callback, percent: int, message: str):
    """打印日志并触发进度回调（遵循项目 callback(percent, message) 约定）。"""
    print(f"{LOG_PREFIX} {percent}% {message}")
    if callback:
        try:
            callback(percent, message)
        except Exception as exc:  # 回调失败不影响主流程
            print(f"{LOG_PREFIX} 进度回调执行失败: {exc}")


def _box_to_aabb(box) -> Tuple[float, float, float, float]:
    """把 rapidocr 四点四边形框 (4,2) 转为轴对齐矩形 (x1, y1, x2, y2)。"""
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    return min(xs), min(ys), max(xs), max(ys)


def _intersect(a, b) -> bool:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    w = min(ax2, bx2) - max(ax1, bx1)
    h = min(ay2, by2) - max(ay1, by1)
    return w > OVERLAP_EPS and h > OVERLAP_EPS


def _merge_overlap_boxes(boxes: List[Tuple[float, float, float, float]]):
    """同帧内合并重叠文本框：两两有交集则合并为外包大框，直至互不重叠。"""
    boxes = [list(b) for b in boxes]
    changed = True
    while changed:
        changed = False
        out: List[List[float]] = []
        merged = set()
        for i in range(len(boxes)):
            if i in merged:
                continue
            cur = boxes[i]
            for j in range(i + 1, len(boxes)):
                if j in merged:
                    continue
                other = boxes[j]
                if _intersect(cur, other):
                    cur = [
                        min(cur[0], other[0]),
                        min(cur[1], other[1]),
                        max(cur[2], other[2]),
                        max(cur[3], other[3]),
                    ]
                    merged.add(j)
                    changed = True
            out.append(cur)
        boxes = out
    return boxes


def _cluster(values: List[float], tol: float) -> List[List[float]]:
    """1D 容差聚类：按排序后相邻差值 <= tol 分组。"""
    if not values:
        return []
    vals = sorted(values)
    groups = [[vals[0]]]
    for v in vals[1:]:
        if v - groups[-1][-1] <= tol:
            groups[-1].append(v)
        else:
            groups.append([v])
    return groups


def _resolve_interface_id(model: str) -> str:
    """解析 OCR 接口 id：运行参数 model > 全局设置 ocr.method > 默认 rapidocr。"""
    if model and model.strip():
        return model.strip()
    global_method = config.get("ocr.method")
    if global_method:
        return str(global_method)
    return "rapidocr"


def _resolve_max_workers(iface_id: str, override: Optional[int]) -> int:
    """解析并行线程数：运行参数覆盖 > OCR 接口配置 max_workers > 默认 4。"""
    if override and override > 0:
        return int(override)
    mgr = get_ocr_interface_manager()
    iface = mgr.get(iface_id)
    if iface:
        workers = (iface.get("config") or {}).get("max_workers")
        if workers and workers > 0:
            return int(workers)
    return DEFAULT_MAX_WORKERS


def _extract_frames(video_path: str, cache_dir: str, frame_interval: int,
                    start_frame: int = 0, end_frame: Optional[int] = None) -> List[Tuple[int, str]]:
    """抽帧：按帧间隔抽取并缓存到 cache_dir，返回 [(帧号, 帧路径)]。

    start_frame / end_frame 用于屏蔽片头片尾：仅抽取该帧范围内的帧（含两端）。
    """
    os.makedirs(cache_dir, exist_ok=True)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        cap.release()
        raise ValueError(f"无法打开视频文件：{video_path}")

    saved: List[Tuple[int, str]] = []
    idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if idx % frame_interval == 0:
            if end_frame is None or start_frame <= idx <= end_frame:
                path = os.path.join(cache_dir, f"frame_{idx:06d}{FRAME_SUFFIX}")
                cv2.imwrite(path, frame)
                saved.append((idx, path))
        idx += 1
    cap.release()

    if not saved:
        raise ValueError(f"视频未抽取到任何帧：{video_path}")
    return saved


def _resolve_region(region, frame_w: int, frame_h: int, direction: str = "horizontal") -> Tuple[int, int, int, int]:
    """解析检查区域，返回裁剪矩形 (x1, y1, x2, y2)（像素，含边界）。

    支持三种形式：
    - "lower" / None：下半段（竖直方向为右半段）
    - "upper"：上半段（竖直方向为左半段）
    - "0.6-0.8"：比例范围字符串，水平方向按 y 坐标比例、竖直方向按 x 坐标比例
    - (x1, y1, x2, y2)：左上+右下像素坐标
    """
    if region is None or region == "lower":
        if direction == "vertical":
            return frame_w // 2, 0, frame_w, frame_h
        return 0, frame_h // 2, frame_w, frame_h
    if region == "upper":
        if direction == "vertical":
            return 0, 0, frame_w // 2, frame_h
        return 0, 0, frame_w, frame_h // 2
    if isinstance(region, str):
        # 比例范围 "0.6-0.8"：水平为 y 比例，竖直为 x 比例
        parts = region.split("-")
        if len(parts) == 2:
            try:
                r1, r2 = sorted(float(p) for p in parts)
            except ValueError:
                raise ValueError(f"非法比例范围：{region}")
            if not (0.0 <= r1 < r2 <= 1.0):
                raise ValueError(f"比例范围需在 0~1 之间：{region}")
            if direction == "vertical":
                return int(frame_w * r1), 0, int(frame_w * r2), frame_h
            return 0, int(frame_h * r1), frame_w, int(frame_h * r2)
        raise ValueError(f"非法检查区域：{region}")
    if isinstance(region, dict):
        region = (region.get("x1", 0), region.get("y1", 0),
                  region.get("x2", frame_w), region.get("y2", frame_h))
    x1, y1, x2, y2 = (float(v) for v in region)
    x1, y1 = max(0, int(x1)), max(0, int(y1))
    x2, y2 = min(frame_w, int(x2)), min(frame_h, int(y2))
    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"非法检查区域：{(x1, y1, x2, y2)}")
    return x1, y1, x2, y2


def _ocr_batch(engine, image_paths: List[str], max_workers: int, callback=None) -> Dict[str, dict]:
    """多线程批量识别：共享同一引擎实例并发推理，逐个完成时上报进度。"""
    results: Dict[str, dict] = {}
    total = len(image_paths)
    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(engine.recognize, p): p for p in image_paths}
        for fut in as_completed(futures):
            path = futures[fut]
            try:
                results[path] = fut.result()
            except Exception as exc:
                print(f"{LOG_PREFIX} 识别失败 {os.path.basename(path)}: {exc}")
            done += 1
            _notify(callback, 25 + int(55 * done / total),
                    f"批量文字识别 {done}/{total}（引擎 {getattr(engine, 'iface_id', 'rapidocr')}）")
    return results


def _filter_boxes_by_direction(boxes, direction: str):
    """按字幕方向筛除宽高比不符合的文本行。

    direction=horizontal（默认）：保留宽 >= 高 * 阈值的横排文本行；
    direction=vertical：保留高 >= 宽 * 阈值的竖排文本行。
    """
    out = []
    for box in boxes:
        x1, y1, x2, y2 = box
        w, h = x2 - x1, y2 - y1
        if w < MIN_BOX_SIZE or h < MIN_BOX_SIZE:
            continue
        if direction == "vertical":
            if h >= w * ASPECT_RATIO_THRESHOLD:
                out.append(box)
        else:
            if w >= h * ASPECT_RATIO_THRESHOLD:
                out.append(box)
    return out


def _extract_box_features(box, direction: str) -> Tuple[float, float, float, float]:
    """把文本框映射为 (中线, 测量值, 跨度起点, 跨度终点)。

    direction=horizontal：中线=y 中心，测量值=高度，跨度=x 方向；
    direction=vertical：中线=x 中心，测量值=宽度，跨度=y 方向。
    """
    x1, y1, x2, y2 = box
    if direction == "vertical":
        return (x1 + x2) / 2.0, x2 - x1, y1, y2
    return (y1 + y2) / 2.0, y2 - y1, x1, x2


def check_subtitle_position(
    video_path: str,
    *,
    model: str = "",
    model_options: Optional[Dict] = None,
    direction: str = "horizontal",
    region: Optional[Union[str, Tuple[float, float, float, float], Dict[str, float]]] = None,
    frame_interval: int = DEFAULT_FRAME_INTERVAL,
    skip_head_sec: float = 0.0,
    skip_tail_sec: float = 0.0,
    keep_cache: bool = False,
    max_workers: Optional[int] = None,
    callback: Optional[Callable] = None,
) -> dict:
    """检查视频字幕位置，返回标注帧路径与字幕外框坐标（相对比例坐标）。

    Parameters
    ----------
    video_path : str
        视频文件路径。
    model : str
        选用 OCR 接口 id；留空时使用全局设置 ocr.method，再兜底 rapidocr。
    direction : str
        字幕方向：horizontal（水平，默认）/ vertical（竖直）。
    region : None | "lower" | "upper" | "0.6-0.8" | (x1, y1, x2, y2)
        检查区域：不传或 "lower" 为下半段（竖直方向为右半段），"upper" 为上半段
        （竖直方向为左半段）；比例范围字符串 "0.6-0.8" 按方向取 y/x 坐标比例；
        也可传左上+右下像素坐标（tuple/list/dict）。
    frame_interval : int
        抽帧间隔（帧），默认 20。
    skip_head_sec : float
        片头跳过秒数，这些时间段不抽帧识别，默认 0。
    skip_tail_sec : float
        片尾跳过秒数（倒数），这些时间段不抽帧识别，默认 0。
    keep_cache : bool
        是否保留抽帧缓存文件，默认 False（结束后删除）。
    max_workers : Optional[int]
        并行识别线程数；不传则使用 OCR 接口配置 max_workers（默认 4）。
    callback : Optional[Callable]
        (percent: int, message: str) 进度回调。每个关键节点都会触发并打印日志，
        节点调用时可传入以获取执行反馈。

    Returns
    -------
    dict
        {"success": True, "frame_path": subtitle_frame.png 路径,
         "box": {"x1","y1","x2","y2"}（相对比例坐标，0~1）,
         "width","height": 视频宽高（供相对坐标换算）, "direction",
         "relative": True, "skip_head_sec", "skip_tail_sec"}
        无有效字幕时 success=False 并给出 message。
    """
    if not os.path.isfile(video_path):
        raise ValueError(f"视频文件不存在：{video_path}")

    direction = direction.strip().lower()
    if direction not in ("horizontal", "vertical"):
        raise ValueError(f"不支持的字幕方向：{direction}，仅支持 horizontal / vertical")

    iface_id = _resolve_interface_id(model)
    workers = _resolve_max_workers(iface_id, max_workers)
    _notify(callback, 5,
            f"开始检查字幕位置（引擎 {iface_id}，线程数 {workers}，方向 {direction}，"
            f"抽帧间隔 {frame_interval}，片头跳过 {skip_head_sec}s，片尾跳过 {skip_tail_sec}s）")

    video_dir = os.path.dirname(os.path.abspath(video_path))
    video_stem = os.path.splitext(os.path.basename(video_path))[0]
    cache_dir = os.path.join(video_dir, f"_subtitle_check_{video_stem}")

    try:
        # ── 0. 读取视频信息，计算片头片尾跳过的抽帧范围 ────────────
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            cap.release()
            raise ValueError(f"无法打开视频文件：{video_path}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        if frame_w <= 0 or frame_h <= 0:
            raise ValueError(f"无法读取视频尺寸：{video_path}")
        if total_frames <= 0:
            raise ValueError(f"无法读取视频帧数：{video_path}")

        duration_ms = int(total_frames / fps * 1000)
        start_ms = int(max(0.0, float(skip_head_sec)) * 1000)
        end_ms = int(duration_ms - max(0.0, float(skip_tail_sec)) * 1000)
        if end_ms - start_ms < 200:
            raise ValueError("片头/片尾跳过时间覆盖了全部视频，请减小跳过时长")
        start_frame = int(start_ms / 1000.0 * fps)
        end_frame = min(total_frames - 1, int(end_ms / 1000.0 * fps))

        # ── 1. 抽帧 ──────────────────────────────────────────────
        frame_items = _extract_frames(video_path, cache_dir, frame_interval,
                                      start_frame=start_frame, end_frame=end_frame)
        _notify(callback, 12,
                f"抽帧完成，共 {len(frame_items)} 帧（间隔 {frame_interval} 帧，"
                f"范围 {start_ms / 1000:.1f}s~{end_ms / 1000:.1f}s）")

        crop = _resolve_region(region, frame_w, frame_h, direction)
        _notify(callback, 15, f"视频尺寸 {frame_w}x{frame_h}，检查区域 {crop}")

        # ── 2. 区域裁剪（写入缓存，供 OCR 读取） ──────────────────
        crop_paths: Dict[str, Tuple[int, str]] = {}
        for frame_idx, frame_path in frame_items:
            img = cv2.imread(frame_path)
            if img is None:
                print(f"{LOG_PREFIX} 警告：帧读取失败 {os.path.basename(frame_path)}")
                continue
            cropped = img[crop[1]:crop[3], crop[0]:crop[2]]
            crop_path = os.path.splitext(frame_path)[0] + CROP_SUFFIX
            cv2.imwrite(crop_path, cropped)
            crop_paths[crop_path] = (frame_idx, frame_path)

        if not crop_paths:
            print(f"{LOG_PREFIX} 抽帧裁剪后无可用图片")
            return {"success": False, "message": "抽帧裁剪后无可用图片"}
        _notify(callback, 20, f"区域裁剪完成，待识别图片 {len(crop_paths)} 张")

        # ── 3. 多线程批量文字检测 ────────────────────────────────
        engine = get_ocr_engine(iface_id, overrides=model_options)
        ocr_results = _ocr_batch(engine, list(crop_paths.keys()), workers, callback=callback)

        # ── 4. 数据处理 ──────────────────────────────────────────
        # 第一轮：剔除无识别结果的数据，转换为 AABB 框
        boxes_by_frame: Dict[str, List[Tuple[float, float, float, float]]] = {}
        for crop_path, res in ocr_results.items():
            raw_boxes = res.get("boxes") or []
            if not raw_boxes:
                continue
            aabbs = [_box_to_aabb(b) for b in raw_boxes]
            aabbs = [b for b in aabbs if b[2] > b[0] and b[3] > b[1]]
            if aabbs:
                boxes_by_frame[crop_path] = aabbs

        if not boxes_by_frame:
            print(f"{LOG_PREFIX} 所有抽帧均未识别到文本，未找到字幕区域")
            return {"success": False, "message": "所有抽帧均未识别到文本，未找到字幕区域"}

        # 第二轮：按字幕方向筛除宽高比不符合的文本行
        filtered_by_frame = {
            path: _filter_boxes_by_direction(boxes, direction)
            for path, boxes in boxes_by_frame.items()
        }
        filtered_by_frame = {p: b for p, b in filtered_by_frame.items() if b}

        if not filtered_by_frame:
            print(f"{LOG_PREFIX} 按{direction}方向宽高比筛选后无有效文本行")
            return {"success": False, "message": f"按{direction}方向宽高比筛选后无有效文本行"}

        # 第三轮：同帧内重叠文本框合并为外包大框
        merged_by_frame = {
            path: _merge_overlap_boxes(boxes)
            for path, boxes in filtered_by_frame.items()
        }
        merged_by_frame = {p: b for p, b in merged_by_frame.items() if b}

        # 中线聚类：对所有文本框中线做 1D 容差聚类
        all_features = []
        for path, boxes in merged_by_frame.items():
            for box in boxes:
                mid, measure, span1, span2 = _extract_box_features(box, direction)
                all_features.append((path, box, mid, measure, span1, span2))

        if not all_features:
            print(f"{LOG_PREFIX} 合并重叠框后无有效文本行")
            return {"success": False, "message": "合并重叠框后无有效文本行"}

        measures = [f[3] for f in all_features]
        median_measure = sorted(measures)[len(measures) // 2]
        mid_tol = max(8.0, median_measure * 0.5)  # 中线容差
        mid_groups = _cluster([f[2] for f in all_features], mid_tol)
        dominant = max(mid_groups, key=len)
        subtitle_mid = sum(dominant) / len(dominant)

        # 选中线穿过的文本框（中线落在该框跨度内容差内）
        selected = [f for f in all_features if abs(f[2] - subtitle_mid) <= mid_tol]
        if not selected:
            print(f"{LOG_PREFIX} 无法确定字幕中线，未找到字幕区域")
            return {"success": False, "message": "无法确定字幕中线，未找到字幕区域"}

        # 高度/宽度容差计数，取排名第一、第二
        measure_tol = max(4.0, median_measure * 0.3)
        measure_groups = _cluster([f[3] for f in selected], measure_tol)
        ranked = sorted(measure_groups, key=lambda g: (len(g), sum(g) / len(g)), reverse=True)

        height_candidates = []
        for group in ranked[:2]:
            if group:  # 仅保留出现次数 > 1 的候选（第二名 <= 1 次则舍弃）
                if len(group) > 1 or not height_candidates:
                    height_candidates.append(sum(group) / len(group))
        if not height_candidates:
            print(f"{LOG_PREFIX} 字幕高度容差计数无有效结果")
            return {"success": False, "message": "字幕高度容差计数无有效结果"}

        subtitle_measure = max(height_candidates)  # 取预选值中的较大者作为字幕高度
        _notify(callback, 85,
                f"数据处理完成：字幕中线 {subtitle_mid:.1f}，字幕高度 {subtitle_measure:.1f}，"
                f"入选文本行 {len(selected)} 条")

        # 上下边线（水平方向）或左右边线（竖直方向）
        low = subtitle_mid - subtitle_measure / 2.0
        high = subtitle_mid + subtitle_measure / 2.0

        # 宽度边线：入选框跨度坐标的最小/最大
        span_min = min(f[4] for f in selected)
        span_max = max(f[5] for f in selected)

        if direction == "vertical":
            box_in_crop = (low, span_min, high, span_max)
        else:
            box_in_crop = (span_min, low, span_max, high)

        # 映射回裁剪前的原视频坐标（裁剪区域左上角偏移）
        bx1, by1, bx2, by2 = box_in_crop
        final_box = (bx1 + crop[0], by1 + crop[1], bx2 + crop[0], by2 + crop[1])

        # ── 5. 选取代表性帧（贡献框数最多的帧），绘制并保存 ──────
        frame_count = {}
        for f in selected:
            frame_count[f[0]] = frame_count.get(f[0], 0) + 1
        best_crop_path = max(frame_count, key=frame_count.get)
        best_frame_path = crop_paths[best_crop_path][1]

        draw_img = cv2.imread(best_frame_path)
        if draw_img is not None:
            cv2.rectangle(
                draw_img,
                (int(final_box[0]), int(final_box[1])),
                (int(final_box[2]), int(final_box[3])),
                DRAW_COLOR,
                DRAW_THICKNESS,
            )
            out_path = os.path.join(video_dir, "subtitle_frame.png")
            cv2.imwrite(out_path, draw_img)
        else:
            out_path = ""

        if not out_path:
            print(f"{LOG_PREFIX} 警告：标注帧绘制/保存失败")
        _notify(callback, 95, f"字幕外框已标注并保存：{out_path or '（失败）'}")

        rel_box = {
            "x1": round(final_box[0] / frame_w, 6),
            "y1": round(final_box[1] / frame_h, 6),
            "x2": round(final_box[2] / frame_w, 6),
            "y2": round(final_box[3] / frame_h, 6),
        }
        result = {
            "success": True,
            "frame_path": out_path,
            "box": rel_box,
            "width": frame_w,
            "height": frame_h,
            "direction": direction,
            "relative": True,
            "skip_head_sec": max(0.0, float(skip_head_sec)),
            "skip_tail_sec": max(0.0, float(skip_tail_sec)),
        }
        _notify(callback, 100, f"字幕位置检查完成：外框 {rel_box}（相对比例坐标）")
        return result
    finally:
        # ── 6. 缓存清理 ──────────────────────────────────────────
        if not keep_cache and os.path.isdir(cache_dir):
            print(f"{LOG_PREFIX} 清理抽帧缓存：{cache_dir}")
            shutil.rmtree(cache_dir, ignore_errors=True)

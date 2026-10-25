# -*- coding: utf-8 -*-
"""快速字幕区段检测（二分法）：用 det + 二分定位字幕切换帧，代替逐帧全量 OCR。

移植自 LCWR0408/app4 的 engine/tools/subtitle_fast_detect.py，并适配本项目：
- OCR 一律走统一工厂 backend.ocr.ocr_factory.get_ocr_engine（RapidOCR / Indra 通用），
  不再直连 third-party 库；det-only 通过 `use_rec=False` 达成（Indra 无此开关会走全流程）；
- 帧以 BGR ndarray 直接送引擎，**不落盘**临时图片（原实现每帧写 jpg 再读，是主要 IO 开销）；
- 原 app4 的阈值来自 engine/config.py（YAML），这里内置常量，避免跨项目配置依赖；
- 增加取消回调；进度回调沿用项目约定的 callback(percent, message)。

流程
----
1. 区域估计（未给预选区域时）：
   ① 全程均匀撒点（最多 16 帧，覆盖首/中/尾）做全画幅检测——只看片头会被台标/
      标题把区域锁死在错误位置，导致正片字幕全被裁掉；
   ② 自动判定横/竖排（原始框里"高>宽"过半即竖排），竖排字幕在横向下会被形状
      过滤全部丢弃；
   ③ 对文本框中线（横向取 Y、竖向取 X）做一维聚类，簇内混了多行再二次拆分；
   ④ 给候选行打分（宽扁比 / 位置 / 字号 / 居中度 / 票数）挑出字幕行，再用
      "内容变化度"兜底：常驻水印逐帧完全一致，真字幕每条内容都不同；字幕位置
      可能中途改变、双行混排，所以"内容会变化"的其它行也并入 region；
   ⑤ 文字太少时回退全画幅（region="FULL"，不裁剪）。
2. 按步长建立抽帧序号队列（末尾补一帧保证覆盖到区间末端；采样范围按
   `_probe_real_last_frame` 探测的实际可解码帧数收敛），生产者线程抽帧并裁剪到
   字幕区域（长边超 960 再缩放），消费者线程做 det，分析者线程按帧号升序比较
   相邻样本——文字长度差 ≤ max(8px, 2%)、行中心偏移 ≤ 8px 且行方向重叠过半视为
   同一字幕；否则二分插入中点帧收敛出切换帧，把区间闭合在切换帧并从 b+1 开新区间；
   相邻两个样本都判空时对间隙做中点/四分点抽查，把"短于抽样步长"的字幕捞出来。
3. 全部闭合后做一次兜底合并（空区间不参与），再把每帧的框收敛到字幕行（所有有
   足够帧数支撑的行，避免把台标等其它文字行圈进擦除范围）。

结果：`{"frame_results": {帧号: [框]}, "segments": [...], "region": ..., ...}`，
帧号从 1 起，坐标为原始视频尺寸。对外只需单一区域时用 `union_box()` 取并集。
"""
import queue
import threading
import time
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import cv2

LOG_PREFIX = "[FastDetect]"

# ── 可调参数（原 app4 版来自 engine/config.py，这里内置） ─────────────
PROBE_MAX_SAMPLES = 10      # ① 预扫描全程撒点帧数上限（每帧一次全画幅 det，较贵）
SHAPE_DIFF_PX = 8           # 宽高差超过该值才判定"方向不符"（单字符/抖动容忍）
CLUSTER_TOL_AXIS = 20.0     # 中线聚类基准容差（像素），实际用 1.5×
AREA_PAD_PX = 8             # region 外扩像素，避免裁掉字幕边缘
DET_SIDE_LIMIT = 960        # 裁剪图长边上限，超出则等比缩放后再检测
MIN_BOX_SIDE = 6            # 文本框最小边长，过滤噪点
MIN_REGION_TEXT = 3         # 预扫描文字框少于该值 → 认为没有稳定文字，回退全画幅
PROBE_MAX_SIDE = 720        # 预扫描画面长边上限（只需定位行位置，无需全分辨率）

# (xmin, xmax, ymin, ymax)
Box = Tuple[float, float, float, float]


def _cluster_midlines(values: Sequence[float], gap: float) -> List[Tuple[float, int]]:
    """一维聚类（排序后相邻差值 > gap 切分），返回 [(簇均值, 成员数)]。

    不依赖 sklearn；字幕中线在多帧采样下非常集中，画面其他文字的中线分布散乱，
    按间距切簇即可区分。
    """
    if not values:
        return []
    s = sorted(values)
    clusters = [[s[0]]]
    for v in s[1:]:
        if v - clusters[-1][-1] > gap:
            clusters.append([v])
        else:
            clusters[-1].append(v)
    return [(sum(c) / len(c), len(c)) for c in clusters]


def _cluster_with_members(items: Sequence[Tuple[float, Box]], gap: float):
    """带成员的一维聚类：items 为 (中线, 框)。返回 [(簇均值, 成员数, [框...])]。

    保留每个簇**确切的成员框**：后续取行极值直接用成员，不再用"中线带宽"反查，
    否则相邻行（如底部水印行与字幕行只差 30~40px）会被吸进来，region 过高。
    """
    if not items:
        return []
    ordered = sorted(items, key=lambda t: t[0])
    groups = [[ordered[0]]]
    for it in ordered[1:]:
        if it[0] - groups[-1][-1][0] > gap:
            groups.append([it])
        else:
            groups[-1].append(it)
    out = []
    for g in groups:
        mids = [it[0] for it in g]
        out.append((sum(mids) / len(mids), len(g), [it[1] for it in g]))
    return out


class FastSubtitleDetector:
    """二分法快速字幕区段检测器。

    :param video_path: 视频路径
    :param engine: OCR 引擎实例（工厂产物，需支持 recognize(img, use_det/use_cls/use_rec)）
    :param hint_region: 预选搜索区域 (x1, y1, x2, y2) 像素；给定时只在该范围内撒点估计，
                        最终 region 也在其内（None = 全画幅）
    :param direction: "auto"（自动判断横/竖排）/ "horizontal" / "vertical"
    :param step: 抽样步长（帧）
    :param time_range: (start_sec, end_sec) 参与检测的时间区段，None 为全视频
    :param progress: 进度回调 progress(percent, message)
    :param cancel: 取消回调，返回 True 时尽快退出（结果可能不完整）
    """

    def __init__(
        self,
        video_path: str,
        engine,
        *,
        hint_region: Optional[Tuple[float, float, float, float]] = None,
        direction: str = "auto",
        step: int = 25,
        time_range: Optional[Tuple[float, float]] = None,
        progress: Optional[Callable[[int, str], None]] = None,
        cancel: Optional[Callable[[], bool]] = None,
    ):
        self.video_path = video_path
        self._engine = engine
        self.step = max(1, int(step or 25))
        self.direction_auto = str(direction).lower() in ("auto", "", "none")
        self.direction = "vertical" if str(direction).lower().startswith("v") else "horizontal"
        self.hint = tuple(float(v) for v in hint_region) if hint_region else None
        self.time_range = time_range
        self.progress = progress
        self.cancel = cancel

        # 位置/尺寸打分的参照系（预选区域内归一化）：(x0, y0, w, h)
        self._ref: Tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
        self.region = None                      # (xmin, xmax, ymin, ymax) 或 "FULL"
        self.frame_results: Dict[int, Optional[List[Box]]] = {}
        self._segments: Dict[int, dict] = {}
        self._segment_seq = 0

        self._frame_queue: "queue.Queue" = queue.Queue()   # 分析者 → 生产者：待抽帧序号
        self._det_queue: "queue.Queue" = queue.Queue()     # 生产者 → 消费者：待检测帧
        self._cv = threading.Condition()                   # frame_results 变更通知
        self._requested = set()
        self._sample_frames: List[int] = []
        self._producer_done = False
        self._stop_event = threading.Event()
        self._total_detect_frames = 0
        self._done_detect_frames = 0
        self._failed_frames = 0
        self._last_progress = -1
        self._cancelled = False
        self.fps = 25.0
        self.frame_count = 0
        self.width = 0
        self.height = 0
        self.start_no = 1
        self.end_no = 0

    # ────────────────────────────────────────────── 引擎与单帧检测
    def _det_raw(self, img) -> Optional[List[Box]]:
        """对图像做文本框检测（det-only），返回原始框（未做形状过滤）。失败返回 None。

        关键：传 limit_type="max" 让 det 限制**最长边**。RapidOCR 默认 'min' 会把
        短边放大到 limit_side_len —— 裁剪成细长条后反而被放大数倍，检测比整帧还慢
        （实测 65px 高的条带 1.9s vs 整帧 0.16s）。'max' 下裁剪才真正省时（0.05s）。
        """
        try:
            # limit_* 对不支持边限制的引擎（如 Indra）是安全的多余 kwarg，会被忽略
            result = self._engine.recognize(
                img, use_det=True, use_cls=False, use_rec=False,
                limit_type="max", limit_side_len=DET_SIDE_LIMIT)
        except Exception as exc:  # noqa: BLE001 - 单帧失败不该中断整批
            print(f"{LOG_PREFIX} 检测异常：{exc}")
            return None
        out: List[Box] = []
        for box in (result.get("boxes") or []):
            try:
                xs = [float(p[0]) for p in box]
                ys = [float(p[1]) for p in box]
            except (TypeError, ValueError, IndexError):
                continue
            xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
            if (xmax - xmin) < MIN_BOX_SIDE or (ymax - ymin) < MIN_BOX_SIDE:
                continue
            out.append((xmin, xmax, ymin, ymax))
        return out

    def _det_image(self, img, offset: Tuple[float, float] = (0.0, 0.0),
                   ) -> Optional[List[Box]]:
        """检测裁剪图并把坐标还原到原图：长边超过上限先缩放，再按比例还原。"""
        if img is None or getattr(img, "size", 0) == 0:
            return []
        h, w = img.shape[:2]
        scale = 1.0
        if max(h, w) > DET_SIDE_LIMIT:
            scale = DET_SIDE_LIMIT / float(max(h, w))
            img = cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))))
        raw = self._det_raw(img)
        if raw is None:
            return None
        ox, oy = offset
        out: List[Box] = []
        for xmin, xmax, ymin, ymax in raw:
            c = (xmin / scale + ox, xmax / scale + ox,
                 ymin / scale + oy, ymax / scale + oy)
            if self._shape_filtered(*c):
                continue
            out.append(c)
        return out

    def _shape_filtered(self, xmin: float, xmax: float, ymin: float, ymax: float) -> bool:
        """按方向做形状过滤，返回 True = 应被过滤掉。"""
        if self.direction == "vertical":
            # 竖排字幕：一列一列的，宽>高的框大概率是横排误检（台标/横幅）
            return (xmax - xmin) - (ymax - ymin) > SHAPE_DIFF_PX
        return (ymax - ymin) - (xmax - xmin) > SHAPE_DIFF_PX

    def _box_mid(self, coord: Box) -> float:
        """框在聚类轴上的中线（横向取 Y，竖向取 X）。"""
        xmin, xmax, ymin, ymax = coord
        return (ymin + ymax) / 2 if self.direction == "horizontal" else (xmin + xmax) / 2

    # ── 打分用的归一化特征（相对预选区域） ──
    def _axis_rel(self, coord: Box) -> float:
        """聚类轴中心在参照系里的归一化位置（0~1）。"""
        x0, y0, rw, rh = self._ref
        mid = self._box_mid(coord)
        origin, full = (y0, rh) if self.direction == "horizontal" else (x0, rw)
        return (mid - origin) / max(1.0, full)

    def _normal_rel(self, coord: Box) -> float:
        """法向尺寸（横向看高度、竖向看宽度）占参照系的比例。"""
        x0, y0, rw, rh = self._ref
        xmin, xmax, ymin, ymax = coord
        if self.direction == "horizontal":
            return (ymax - ymin) / max(1.0, rh)
        return (xmax - xmin) / max(1.0, rw)

    def _center_off_rel(self, coord: Box) -> float:
        """居中程度：横向取水平偏移、竖向取垂直偏移，相对参照系宽度/高度。"""
        x0, y0, rw, rh = self._ref
        xmin, xmax, ymin, ymax = coord
        if self.direction == "horizontal":
            return abs((xmin + xmax) / 2 - (x0 + rw / 2)) / max(1.0, rw)
        return abs((ymin + ymax) / 2 - (y0 + rh / 2)) / max(1.0, rh)

    def _shrink_for_probe(self, img, limit: int = PROBE_MAX_SIDE) -> Tuple[float, "np.ndarray"]:
        """预扫描用：把画面长边缩到 limit 以内，返回 (缩放比, 缩小图)。

        预扫描只为定位"字幕在哪一行"，不需要全分辨率；放大/超大分辨率视频下
        这一步能显著降低 det 耗时（坐标由调用方按缩放比还原）。
        """
        h, w = img.shape[:2]
        longest = max(h, w)
        if longest <= limit:
            return 1.0, img
        scale = limit / float(longest)
        return scale, cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))),
                                 interpolation=cv2.INTER_AREA)

    def _warmup(self) -> None:
        """预热引擎：把模型加载成本从首帧统计里剥离，并尽早暴露引擎不可用。

        RapidOCR 的权重是懒加载的，首帧 det 会连同 40s+ 的加载一起计时；不预热
        则"预扫描耗时"看起来被首帧拖爆，也会让进度条长时间停在 5%。
        """
        try:
            blank = __import__("numpy").zeros((64, 64, 3), dtype="uint8")
            self._engine.recognize(blank, use_det=True, use_cls=False, use_rec=False)
        except Exception as exc:  # noqa: BLE001 - 预热失败不应中断（后续会再报）
            print(f"{LOG_PREFIX} 引擎预热失败：{exc}")

    # ────────────────────────────────────────────── ① 区域估计
    def _estimate_region(self, cap, time_frame_range: Tuple[int, int]):
        """全程均匀撒点检测 → 聚类字幕中线 → 选出字幕行 → 外框。

        返回 None = 未检出足够文字，调用方退回全画幅。
        """
        lo, hi = time_frame_range
        total = max(1, hi - lo + 1)
        n = min(PROBE_MAX_SAMPLES, total)
        # 首帧必采（大概率处于字幕稳定区间内）
        sample_ids = [lo] + [lo + int(total * i / max(1, n - 1)) for i in range(1, n)]
        sample_ids = sorted({x for x in sample_ids if lo <= x <= hi})

        raw_boxes: List[Box] = []
        boxes_per_frame: List[List[Box]] = []
        hint = self._hint_pixels()
        for i, idx in enumerate(sample_ids):
            if self._check_cancel():
                return None
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx - 1)
            ret, frame = cap.read()
            if not ret:
                continue
            # 预扫描只需判断字幕行位置，按缩放后的画面检测即可（det 耗时随边长上升）
            if hint:
                x1, y1, x2, y2 = hint
                sub = frame[int(y1):int(y2), int(x1):int(x2)]
                scale, small = self._shrink_for_probe(sub)
                raw = self._det_raw(small)
                if raw:
                    raw = [(a / scale + x1, b / scale + x1,
                            c / scale + y1, d / scale + y1) for (a, b, c, d) in raw]
            else:
                scale, small = self._shrink_for_probe(frame)
                raw = self._det_raw(small)
                if raw:
                    raw = [(a / scale, b / scale, c / scale, d / scale)
                           for (a, b, c, d) in raw]
            if raw is None:
                continue
            raw_boxes.extend(raw)
            boxes_per_frame.append(raw)
            self._emit(5 + int(5 * (i + 1) / max(1, len(sample_ids))),
                       f"预扫描抽样 {i + 1}/{len(sample_ids)}（已检出 {len(raw_boxes)} 个文本框）")

        if len(raw_boxes) < MIN_REGION_TEXT:
            print(f"{LOG_PREFIX} 预扫描仅检出 {len(raw_boxes)} 个文本框，回退全画幅")
            return None

        self._detect_direction(raw_boxes)
        boxes = [c for c in raw_boxes if not self._shape_filtered(*c)]
        if len(boxes) < MIN_REGION_TEXT:
            print(f"{LOG_PREFIX} 形状过滤后仅剩 {len(boxes)} 个文本框，回退全画幅")
            return None

        tol = CLUSTER_TOL_AXIS * 1.5
        items = [(self._box_mid(c), c) for c in boxes]
        clusters = _cluster_with_members(items, gap=tol)
        if not clusters:
            return None
        clusters = self._split_tall_clusters(clusters, tol)
        simple = [(c[0], c[1]) for c in clusters]

        row_boxes = self._pick_subtitle_row(
            simple, clusters, boxes_per_frame=boxes_per_frame, tol=tol)
        if not row_boxes:
            return None
        xs0 = [b[0] for b in row_boxes]
        xs1 = [b[1] for b in row_boxes]
        ys0 = [b[2] for b in row_boxes]
        ys1 = [b[3] for b in row_boxes]
        region = self._clamp_region(
            min(xs0) - AREA_PAD_PX, max(xs1) + AREA_PAD_PX,
            min(ys0) - AREA_PAD_PX, max(ys1) + AREA_PAD_PX)
        print(f"{LOG_PREFIX} 自动估计字幕区域 {region}（{len(row_boxes)} 个框参与）")
        return region

    def _detect_direction(self, raw_boxes: Sequence[Box]) -> None:
        """direction="auto" 时按"高>宽"框的占比判定横/竖排。"""
        if not self.direction_auto or not raw_boxes:
            return
        tall = sum(1 for c in raw_boxes
                   if (c[3] - c[2]) - (c[1] - c[0]) > SHAPE_DIFF_PX)
        ratio = tall / len(raw_boxes)
        if ratio > 0.5:
            self.direction = "vertical"
            print(f"{LOG_PREFIX} 判定为竖排字幕（{tall}/{len(raw_boxes)} 个高>宽的框）")
        else:
            self.direction = "horizontal"
            print(f"{LOG_PREFIX} 判定为横向字幕（{len(raw_boxes) - tall}/{len(raw_boxes)} 个框）")
        self.direction_auto = False

    def _split_tall_clusters(self, clusters, tol: float):
        """把混了多行的簇按成员中线拆开（相邻两行中线只差 30~40px）。"""
        out = []
        for mean_mid, votes, boxes in clusters:
            if len(boxes) < 2:
                out.append((mean_mid, votes, boxes))
                continue
            mids = sorted(self._box_mid(b) for b in boxes)
            span = mids[-1] - mids[0]
            heights = sorted((b[3] - b[2]) if self.direction == "horizontal"
                             else (b[1] - b[0]) for b in boxes)
            med_h = max(1.0, heights[len(heights) // 2])
            if span <= max(tol, med_h * 1.6):
                out.append((mean_mid, votes, boxes))
                continue
            sub = _cluster_with_members(
                [(self._box_mid(b), b) for b in boxes], gap=tol)
            if len(sub) > 1:
                print(f"{LOG_PREFIX} 簇 mid={mean_mid:.0f} 跨 {span:.0f}px"
                      f"（{len(boxes)} 框）→ 拆成 {len(sub)} 行")
            out.extend(sub)
        return out

    def _pick_subtitle_row(self, simple, clusters, *, boxes_per_frame=None,
                           tol: float = 40.0) -> List[Box]:
        """选出字幕行的成员框（多位置字幕返回多行并集）。"""
        items = []
        for _mean, _votes, boxes in clusters:
            for b in boxes:
                items.append((self._box_mid(b), b))
        best_mid = self._pick_subtitle_midline(
            simple, boxes_by_mid=items, tol=tol, boxes_per_frame=boxes_per_frame)
        if best_mid is None:
            return []

        best_boxes = None
        extra_rows = []
        axis_full = (self._ref[3] if self.direction == "horizontal" else self._ref[2])
        for mean_mid, _votes, boxes in clusters:
            if abs(mean_mid - best_mid) < 1e-6:
                best_boxes = boxes
                continue
            if not boxes_per_frame:
                continue
            if self._content_variation(mean_mid, boxes_per_frame, tol) <= 0.2:
                continue                       # 逐帧不变 → 静态水印/台标行
            if axis_full:
                hs = [(b[3] - b[2]) if self.direction == "horizontal" else (b[1] - b[0])
                      for b in boxes]
                med_h = sorted(hs)[len(hs) // 2] / axis_full
                if not (0.012 <= med_h <= 0.20):   # 行高需落在字幕字号范围内
                    continue
            extra_rows.append(boxes)
        if best_boxes is None:
            best_boxes = min(clusters, key=lambda c: abs(c[0] - best_mid))[2]
        if extra_rows:
            merged = list(best_boxes) + [b for row in extra_rows for b in row]
            mids = [self._box_mid(b) for b in merged]
            if axis_full and (max(mids) - min(mids)) > axis_full * 0.45:
                # 并集跨度过大 = 掺进了弹幕/标题之类杂行，退回最佳行
                print(f"{LOG_PREFIX} 多行并集跨度 {max(mids) - min(mids):.0f}px 过大，"
                      f"退回最佳字幕行")
                return list(best_boxes)
            print(f"{LOG_PREFIX} 检出 {1 + len(extra_rows)} 个位置会变化的字幕行，region 取并集")
            return merged
        return list(best_boxes)

    def _pick_subtitle_midline(self, clusters, *, boxes_by_mid=None,
                               tol: float = 40.0, boxes_per_frame=None):
        """中线簇里挑出字幕所在行，返回其中线值。

        判据（综合打分）：宽扁形态 / 画面下部 / 字号适中 / 水平居中 / 票数。
        只按票数会误选常驻台标，只按"最靠下"会误选底部小字水印。
        """
        if not clusters:
            return None
        top = max(c[1] for c in clusters)
        # 票数过滤放宽到 25%：字幕可能只在部分片段出现，而常驻台标票数总是最高
        min_votes = max(1, int(top * 0.25))
        cands = [c for c in clusters if c[1] >= min_votes] or list(clusters)

        if not boxes_by_mid:
            # 没有形态信息可用：退化为"票数优先，票数相同取靠下/靠右"
            cands.sort(key=lambda c: (-c[1], -c[0]))
            return cands[0][0]

        scored = []
        for mid, votes in cands:
            scored.append((self._score_cluster(mid, votes, top, boxes_by_mid, tol),
                           votes, mid))
        scored.sort(key=lambda s: (-s[0], -s[1], -s[2]))
        best = scored[0]
        if len(scored) > 1:
            runner = scored[1]
            if best[0] - runner[0] < best[0] * 0.05:
                # 分数接近 → 票数决胜，再接近取更靠下/靠右
                if best[1] >= runner[1]:
                    best = best if best[2] >= runner[2] else runner
                else:
                    best = runner
        # 内容变化度兜底：底部常驻小字水印逐帧完全一致，真字幕每条内容都不同
        if boxes_per_frame and len(scored) > 1:
            if self._content_variation(best[2], boxes_per_frame, tol) < 0.2:
                for score, votes, mid in scored[1:]:
                    if self._content_variation(mid, boxes_per_frame, tol) > 0.2:
                        print(f"{LOG_PREFIX} 最佳候选 mid={int(best[2])} 逐帧不变（静态水印），"
                              f"改用会变化的行 mid={int(mid)}")
                        best = (score, votes, mid)
                        break
        print(f"{LOG_PREFIX} 字幕行候选：" + ", ".join(
            f"mid={int(m)}(票{v},分{s:.2f})" for s, v, m in scored[:5]))
        return best[2]

    def _score_cluster(self, mid: float, votes: int, top_votes: int,
                       boxes_by_mid, tol: float) -> float:
        """给中线簇打"像不像字幕"的分数（越高越像）。"""
        row = [c for m, c in boxes_by_mid if abs(m - mid) <= tol]
        if not row:
            return 0.0
        xs0 = min(c[0] for c in row)
        xs1 = max(c[1] for c in row)
        ys0 = min(c[2] for c in row)
        ys1 = max(c[3] for c in row)
        box_w = max(1.0, xs1 - xs0)
        box_h = max(1.0, ys1 - ys0)
        score = 0.0
        if self.direction == "horizontal":
            ratio = box_w / box_h                     # ① 宽扁比（字幕宽远大于高）
            score += 2.0 * min(1.0, max(0.0, (ratio - 1.2) / 2.0))
        else:
            ratio = box_h / box_w
            score += 2.0 * min(1.0, max(0.0, (ratio - 1.2) / 2.0))
        # ② 位置：字幕多在下部（竖向为右侧）
        pos = self._axis_rel((xs0, xs1, ys0, ys1))
        if pos >= 0.60:
            score += 2.0 * min(1.0, (pos - 0.55) / 0.35)
        else:
            score += 0.3 * max(0.0, pos / 0.60)
        # ③ 尺寸：字幕法向尺寸占参照系 1.5%~15% 合理
        size_rel = self._normal_rel((xs0, xs1, ys0, ys1))
        if 0.015 <= size_rel <= 0.15:
            score += 1.0
        elif size_rel < 0.015:
            score += 0.3 * (size_rel / 0.015)     # 太小的（联系方式小字）
        else:
            score += 0.2                          # 太大的（片头标题）
        # ④ 居中度：字幕通常居中，水印/台标多偏一边
        score += 1.0 * max(0.0, 1.0 - self._center_off_rel((xs0, xs1, ys0, ys1)) / 0.25)
        # ⑤ 票数：相对最高票的比例
        score += 1.5 * (votes / max(1, top_votes))
        return score

    def _content_variation(self, mid: float, boxes_per_frame, tol: float) -> float:
        """该行的"内容变化度"：0 = 每帧框完全一样（静态水印），1 = 每帧都不同。

        字幕每条内容不同 → 框的宽/位置会变；常驻水印/台标逐帧完全一致。
        这是区分"真字幕"和"底部常驻小字"最可靠的信号（纯几何无法区分）。
        """
        if not boxes_per_frame:
            return 1.0
        signatures = set()
        frames_with = 0
        for raw in boxes_per_frame:
            row = [c for c in raw if abs(self._box_mid(c) - mid) <= tol]
            if not row:
                continue
            frames_with += 1
            signatures.add((min(c[0] for c in row), max(c[1] for c in row),
                            min(c[2] for c in row), max(c[3] for c in row)))
        if frames_with < 2:
            return 0.5
        if len(signatures) == 1:
            return 0.0
        return min(1.0, (len(signatures) - 1) / max(1, frames_with - 1))

    # ────────────────────────────────────────────── 主流程
    def _probe_real_last_frame(self, cap, meta_count: int) -> Optional[int]:
        """探测真实可解码末帧号（1 基），None 表示探测失败不校正。

        元数据帧数由封装工具写入，剪辑/压缩导出的视频常与实际差几帧：虚高会让
        尾部样本 seek 失败被当成"无字幕"，少报则末尾不在采样范围内，两者都漏识别。
        """
        if meta_count <= 0:
            return None
        start = max(1, meta_count - 33)
        while True:
            cap.set(cv2.CAP_PROP_POS_FRAMES, start - 1)
            ret, _ = cap.read()
            if ret:
                break
            if start <= 1:
                return None
            start = max(1, start // 2)
        while True:
            ret, _ = cap.read()
            if not ret:
                break
        real = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        return real if real > 0 else None

    def _hint_pixels(self):
        """预选区域转成像素整数 (x1, y1, x2, y2)，并夹到画面内。"""
        if not self.hint:
            return None
        x1, y1, x2, y2 = self.hint
        x1, y1 = max(0, int(x1)), max(0, int(y1))
        x2, y2 = min(self.width, int(x2)), min(self.height, int(y2))
        if x2 <= x1 or y2 <= y1:
            return None
        return (x1, y1, x2, y2)

    def _clamp_region(self, xmin: float, xmax: float, ymin: float, ymax: float) -> Box:
        """把估计框夹到画面内（并限制在预选区域内）。"""
        xmin, xmax = max(0.0, xmin), min(float(self.width), xmax)
        ymin, ymax = max(0.0, ymin), min(float(self.height), ymax)
        hint = self._hint_pixels()
        if hint:
            xmin = max(xmin, float(hint[0]))
            ymin = max(ymin, float(hint[1]))
            xmax = min(xmax, float(hint[2]))
            ymax = min(ymax, float(hint[3]))
        return (xmin, xmax, ymin, ymax)

    def detect(self) -> dict:
        """执行完整检测，返回结果字典。"""
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            cap.release()
            raise RuntimeError(f"无法打开视频: {self.video_path}")
        try:
            self.fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
            meta_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if self.width <= 0 or self.height <= 0:
                raise RuntimeError(f"无法读取视频尺寸：{self.video_path}")

            # 预选区域作为位置打分的参照系
            hint = self._hint_pixels()
            if hint:
                self._ref = (float(hint[0]), float(hint[1]),
                             float(hint[2] - hint[0]), float(hint[3] - hint[1]))
            else:
                self._ref = (0.0, 0.0, float(self.width), float(self.height))

            # 元数据帧数不可信 → 按实际可解码帧数收敛采样范围
            real_last = self._probe_real_last_frame(cap, meta_count)
            frame_count = meta_count
            if real_last and real_last != meta_count:
                print(f"{LOG_PREFIX} 元数据帧数 {meta_count} 与实际可解码帧数 "
                      f"{real_last} 不一致，按实际值采样")
                frame_count = real_last
            self.frame_count = frame_count
            if frame_count <= 0:
                return self._empty_result()

            if self.time_range:
                self.start_no = max(1, int(self.time_range[0] * self.fps) + 1)
                end = self.time_range[1]
                self.end_no = min(frame_count, int(end * self.fps)) if end else frame_count
            else:
                self.start_no, self.end_no = 1, frame_count
            if self.end_no < self.start_no:
                return self._empty_result()
            time_frame_range = (self.start_no, self.end_no)

            # ① 区域估计（失败退回全画幅，不裁剪）
            self._emit(4, "初始化 OCR 引擎（首次可能需加载模型）")
            t_load = time.time()
            self._warmup()
            load_cost = time.time() - t_load
            if load_cost > 3:
                print(f"{LOG_PREFIX} 引擎加载/预热 {load_cost:.1f}s（仅首次）")
            t0 = time.time()
            self.region = self._estimate_region(cap, time_frame_range)
            if self.region is None:
                self.region = "FULL"
                print(f"{LOG_PREFIX} 预扫描未稳定命中字幕行，回退全画幅")
            print(f"{LOG_PREFIX} region={self.region} 帧范围=[{self.start_no},{self.end_no}] "
                  f"预扫描用时 {time.time() - t0:.1f}s（引擎加载 {load_cost:.1f}s 已单列）")
            if not self._region_valid():
                return self._empty_result()

            # ② 抽样 + 三线程（生产者抽帧 / 消费者 det / 分析者二分）
            samples = sorted(set(range(self.start_no, self.end_no + 1, self.step))
                             | {self.start_no, self.end_no})
            self._sample_frames = samples
            self._total_detect_frames = len(samples)
            for no in samples:
                self._requested.add(no)
                self._frame_queue.put(no)

            producer = threading.Thread(target=self._producer_loop, args=(cap,), daemon=True)
            consumer = threading.Thread(target=self._consumer_loop, daemon=True)
            analyzer = threading.Thread(target=self._analyzer_loop, daemon=True)
            producer.start()
            consumer.start()
            analyzer.start()
            # 轮询式 join：取消后要主动收尾，否则分析者可能在二分里继续跑很久
            while analyzer.is_alive():
                analyzer.join(timeout=0.5)
                if self._check_cancel():
                    break
            self._stop_event.set()
            self._frame_queue.put(None)
            self._det_queue.put(None)
            producer.join(timeout=5)
            consumer.join(timeout=5)
        finally:
            cap.release()

        self._emit(96, "合并相邻区段并收敛到字幕行")
        segments = self._merge_adjacent_segments()
        self.frame_results = self._filter_to_subtitle_line(self.frame_results)
        if self._failed_frames:
            print(f"{LOG_PREFIX} 注意：{self._failed_frames} 帧抽帧/检测失败（已按无字幕处理）")
        has_boxes = any(boxes for boxes in self.frame_results.values())
        if has_boxes:
            self._emit(100, f"检测完成：{len(segments)} 个字幕区段")
        else:
            self._emit(100, "检测完成：未检出字幕文本")
        return {
            "success": has_boxes,
            "region": self.region,
            "segments": segments,
            "frame_results": self.frame_results,
            "direction": self.direction,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "frame_count": self.frame_count,
            "start_no": self.start_no,
            "end_no": self.end_no,
            "failed_frames": self._failed_frames,
            "cancelled": self._cancelled,
        }

    def _empty_result(self) -> dict:
        return {
            "success": False, "region": self.region, "segments": [],
            "frame_results": {}, "direction": self.direction,
            "width": self.width, "height": self.height, "fps": self.fps,
            "frame_count": self.frame_count, "start_no": self.start_no,
            "end_no": self.end_no, "failed_frames": self._failed_frames,
            "cancelled": self._cancelled,
        }

    def union_box(self) -> Optional[Box]:
        """所有帧检测框的并集外框 (xmin, xmax, ymin, ymax)；无结果返回 None。"""
        boxes = [b for bs in self.frame_results.values() if bs for b in bs]
        if not boxes:
            return None
        return (min(b[0] for b in boxes), max(b[1] for b in boxes),
                min(b[2] for b in boxes), max(b[3] for b in boxes))

    # ────────────────────────────────────────────── 三线程主体
    def _producer_loop(self, cap):
        """生产者：抽帧 → 裁剪到字幕区域 → 投递检测任务。

        抽帧失败也要记账（存 None）并唤醒分析者：分析者会阻塞等这一帧的结果。
        """
        try:
            while not self._stop_event.is_set():
                try:
                    frame_no = self._frame_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                if frame_no is None:
                    break
                if self._check_cancel():
                    # 取消后不再抽帧，也不再补记结果（避免结果表被大量 None 撑满）
                    self._frame_queue.task_done()
                    break
                try:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no - 1)   # 1 基 → seek 0 基
                    ret, frame = cap.read()
                except Exception as exc:  # noqa: BLE001 - 解码异常不该拖垮线程
                    print(f"{LOG_PREFIX} 抽帧异常 frame={frame_no}: {exc}")
                    ret, frame = False, None
                if not ret or frame is None:
                    self._failed_frames += 1
                    self._store_result(frame_no, None)
                    self._frame_queue.task_done()
                    continue
                x1, y1, x2, y2 = self._crop_bounds(frame.shape)
                self._det_queue.put((frame_no, frame[y1:y2, x1:x2], (x1, y1)))
                self._frame_queue.task_done()
        finally:
            self._producer_done = True
            with self._cv:
                self._cv.notify_all()

    def _crop_bounds(self, shape) -> Tuple[int, int, int, int]:
        """region 与画面求交后的裁剪边界 (x1, y1, x2, y2)；FULL/非法退化为整幅。"""
        h, w = shape[:2]
        if self.region == "FULL" or not self.region:
            return 0, 0, w, h
        xmin, xmax, ymin, ymax = self.region
        x1 = max(0, min(int(xmin), w))
        y1 = max(0, min(int(ymin), h))
        x2 = min(w, max(0, int(xmax)))
        y2 = min(h, max(0, int(ymax)))
        if x2 <= x1 or y2 <= y1:
            return 0, 0, w, h
        return x1, y1, x2, y2

    def _store_result(self, frame_no: int, coords: Optional[List[Box]]) -> None:
        with self._cv:
            self.frame_results[frame_no] = coords
            self._cv.notify_all()

    def _consumer_loop(self):
        """消费者：对裁剪帧做 det，结果写回供分析者取用。"""
        while True:
            item = self._det_queue.get()
            if item is None:
                break
            frame_no, crop_img, offset = item
            if crop_img is None or getattr(crop_img, "size", 0) == 0:
                self._failed_frames += 1
                self._store_result(frame_no, None)
                self._det_queue.task_done()
                continue
            if frame_no in self.frame_results:      # 已有结果不重复检测
                self._det_queue.task_done()
                continue
            coords = self._det_image(crop_img, offset)
            if coords is None:
                self._failed_frames += 1
            self._store_result(frame_no, coords)
            if coords is not None:
                self._done_detect_frames += 1
                self._report_detect_progress()
            self._det_queue.task_done()

    def _analyzer_loop(self):
        """分析者：按帧号升序遍历样本，遇到"不同字幕"就二分定位切换帧。

        相邻样本同一字幕 → lo 右移；不同 → 二分收敛出切换帧 b，区间闭合在 b，
        并从 b+1 开新区间，保证帧覆盖不中断。相邻两样本都判空时对间隙抽查，
        把持续时间短于抽样步长的字幕捞出来。
        """
        samples = list(self._sample_frames)
        if not samples:
            return
        seg_start = samples[0]
        seg_id = self._new_segment(seg_start)
        lo_no = samples[0]
        lo_coords = self._resolve(lo_no) or []
        for hi_no in samples[1:]:
            if self._check_cancel():
                break
            hi_raw = self._resolve(hi_no)
            if hi_raw is None:
                # 抽帧/检测失败：沿用上一判定右移，不把失败当成"字幕消失"
                lo_no = hi_no
                continue
            hi_coords = hi_raw
            if not lo_coords and not hi_coords:
                hidden = self._find_hidden_subtitle(lo_no, hi_no)
                if hidden:
                    s_no, e_no, h_coords = hidden
                    self._close_segment(seg_id, seg_start, s_no - 1, [])
                    hid_id = self._new_segment(s_no)
                    self._close_segment(hid_id, s_no, e_no, h_coords)
                    seg_start = e_no + 1
                    seg_id = self._new_segment(seg_start)
                    lo_no, lo_coords = hi_no, hi_coords
                    continue
            if self._same_subtitle(lo_coords, hi_coords):
                lo_no, lo_coords = hi_no, hi_coords
                continue
            b_no, b_coords, hi_no, hi_coords = self._bisect(
                lo_no, lo_coords, hi_no, hi_coords)
            self._close_segment(seg_id, seg_start, b_no, b_coords)
            seg_start = b_no + 1
            seg_id = self._new_segment(seg_start)
            lo_no, lo_coords = hi_no, hi_coords
        self._close_segment(seg_id, seg_start, lo_no, lo_coords)

    def _find_hidden_subtitle(self, lo_no: int, hi_no: int):
        """两个相邻空样本的间隙里找被抽样跳过的短字幕，返回 (start, end, coords)。"""
        gap = hi_no - lo_no
        if gap < 2:
            return None
        probes = [(lo_no + hi_no) // 2]
        if gap > 4:
            probes += [lo_no + gap // 4, lo_no + 3 * gap // 4]
        hit_no, hit_coords = None, None
        for p in sorted(set(probes)):
            if p <= lo_no or p >= hi_no:
                continue
            coords = self._resolve(p)
            if coords:
                hit_no, hit_coords = p, coords
                break
        if hit_no is None:
            return None
        start_no = self._bisect_text_edge(lo_no, hit_no, from_empty=True)
        end_no = self._bisect_text_edge(hi_no, hit_no, from_empty=False)
        if end_no < start_no:
            return None
        return start_no, end_no, hit_coords

    def _bisect_text_edge(self, empty_no: int, text_no: int, *, from_empty: bool) -> int:
        """二分出"空帧段"与"有字幕段"的边界帧号。"""
        lo, hi = (empty_no, text_no) if from_empty else (text_no, empty_no)
        while hi - lo > 1:
            if self._check_cancel():
                break
            mid = (lo + hi) // 2
            has_text = bool(self._resolve(mid))
            if from_empty:
                if has_text:
                    hi = mid
                else:
                    lo = mid
            else:
                if has_text:
                    lo = mid
                else:
                    hi = mid
        return hi if from_empty else lo

    # ────────────────────────────────────────────── 区间逻辑
    def _new_segment(self, start_no: int) -> int:
        self._segment_seq += 1
        self._segments[self._segment_seq] = {"start": start_no, "end": None, "coords": []}
        return self._segment_seq

    def _resolve(self, frame_no: int) -> Optional[List[Box]]:
        """取该帧检测结果；没做过就入队并等待（失败/取消返回 None）。"""
        with self._cv:
            if self._cancelled:
                return self.frame_results.get(frame_no)
            if frame_no not in self._requested:
                self._requested.add(frame_no)
                self._total_detect_frames += 1    # 二分追加的帧也要进进度分母
                self._frame_queue.put(frame_no)
            while frame_no not in self.frame_results:
                if self._cancelled:
                    return None
                # 生产者已退出且两个队列都排空 → 这一帧永远等不到
                if self._producer_done and self._frame_queue.unfinished_tasks == 0 \
                        and self._det_queue.unfinished_tasks == 0:
                    return None
                self._cv.wait(timeout=0.5)
            return self.frame_results[frame_no]

    def _bisect(self, lo_no: int, lo_coords, hi_no: int, hi_coords):
        """在 (lo_no, hi_no) 之间二分，找出最后一个属于 lo 字幕的帧。"""
        while hi_no - lo_no > 1:
            if self._check_cancel():
                break
            mid = (lo_no + hi_no) // 2
            mid_coords = self._resolve(mid)
            if mid_coords is None:
                break
            if self._same_subtitle(lo_coords, mid_coords):
                lo_no, lo_coords = mid, mid_coords
            else:
                hi_no, hi_coords = mid, mid_coords
        return lo_no, lo_coords, hi_no, hi_coords

    def _same_subtitle(self, coords_a, coords_b) -> bool:
        """两样本是否属于同一字幕。

        都为空算同一段（连续空帧），一边有一边无为切换。判据按"文字走向长度"与
        "行位置"分开比较：长度差 > max(8px, 2%) → 换文案；行中心偏移 > 8px 或
        行方向重叠不足短边一半 → 行位置移动。旧判据（面积差 5% + IoU 0.5）对抖动
        过敏：600px 宽字幕高度抖 2px 面积就变 5%，同一句被误判成切换。
        """
        if not coords_a and not coords_b:
            return True
        if not coords_a or not coords_b:
            return False
        ra = self._coords_region(coords_a)
        rb = self._coords_region(coords_b)
        if self.direction == "horizontal":
            len_a, len_b = ra[1] - ra[0], rb[1] - rb[0]
            ca, cb = (ra[0] + ra[1]) / 2, (rb[0] + rb[1]) / 2
            ov = min(ra[3], rb[3]) - max(ra[2], rb[2])
            ov_min = min(ra[3] - ra[2], rb[3] - rb[2])
        else:
            len_a, len_b = ra[3] - ra[2], rb[3] - rb[2]
            ca, cb = (ra[2] + ra[3]) / 2, (rb[2] + rb[3]) / 2
            ov = min(ra[1], rb[1]) - max(ra[0], rb[0])
            ov_min = min(ra[1] - ra[0], rb[1] - rb[0])
        if len_a <= 0 or len_b <= 0:
            return False
        if abs(len_a - len_b) > max(8.0, 0.02 * max(len_a, len_b)):
            return False
        if abs(ca - cb) > 8.0:
            return False
        if ov_min <= 0 or ov < 0.5 * ov_min:
            return False
        return True

    def _close_segment(self, seg_id: int, f_start: int, f_end: int, coords) -> None:
        if seg_id not in self._segments:
            return
        seg = self._segments[seg_id]
        seg["start"], seg["end"] = f_start, f_end
        seg["coords"] = list(coords or [])

    @staticmethod
    def _coords_region(coords) -> Optional[Tuple[float, float, float, float]]:
        """一组框的极值 → (xmin, xmax, ymin, ymax)。"""
        if not coords:
            return None
        return (min(c[0] for c in coords), max(c[1] for c in coords),
                min(c[2] for c in coords), max(c[3] for c in coords))

    def _merge_adjacent_segments(self) -> List[dict]:
        """全部闭合后：相邻区间其实是同一条字幕时兜底合并（空区间不参与）。

        空区间并进相邻段会让字幕区域凭空多出一截，等于把没有字幕的帧也划进范围。
        """
        ordered = sorted((s for s in self._segments.values() if s["end"] is not None),
                         key=lambda s: s["start"])
        merged: List[dict] = []
        for seg in ordered:
            if merged:
                last = merged[-1]
                if last["coords"] and seg["coords"] \
                        and self._same_subtitle(last["coords"], seg["coords"]):
                    # 合并时保留多框（压成一个大外接框会把两行之间的空白也划进范围）
                    last["end"] = seg["end"]
                    last["coords"] = last["coords"] + seg["coords"]
                    continue
            merged.append(dict(seg))

        result: Dict[int, List[Box]] = {}
        for seg in merged:
            for no in range(int(seg["start"]), int(seg["end"]) + 1):
                result[no] = seg["coords"]
        return [{"start": int(s["start"]), "end": int(s["end"]),
                 "region": self._coords_region(s["coords"]),
                 "boxes": s["coords"]} for s in merged]

    def _filter_to_subtitle_line(self, result: Dict[int, List[Box]]) -> Dict[int, List[Box]]:
        """把每帧检测框收敛到"字幕行"。

        全画幅或预选范围过大时，一帧里会同时出现字幕、台标、水印等多行文字，全取
        外接框会合并成一大块，擦除范围被严重放大。这里统计全局占多数的行（中线），
        只保留贴近该行的框；没有可靠主导行时保持原样（宁多勿少）。
        """
        if not result:
            return result
        tol = CLUSTER_TOL_AXIS * 2.0
        counter: Dict[float, int] = {}
        for boxes in result.values():
            if not boxes:
                continue
            for m in {round(self._box_mid(b) / tol) * tol for b in boxes}:
                counter[m] = counter.get(m, 0) + 1
        if not counter:
            return result
        # 多行支撑：字幕位置可能中途改变/双行混排，不能只保留票数最高那一行
        min_support = max(3, int(len(result) * 0.05))
        supported = sorted(m for m, c in counter.items() if c >= min_support)
        if not supported:
            return result
        best_mid = max(counter.items(), key=lambda kv: kv[1])[0]
        out: Dict[int, List[Box]] = {}
        for no, boxes in result.items():
            if not boxes:
                out[no] = boxes
                continue
            keep = [b for b in boxes
                    if any(abs(self._box_mid(b) - m) <= tol for m in supported)]
            out[no] = keep if keep else boxes
        print(f"{LOG_PREFIX} 结果收敛到字幕行 mid=" + ", ".join(
            f"{m:.0f}(命中 {counter[m]} 帧)" for m in supported) +
            f"（主行 {best_mid:.0f}）")
        return out

    def _region_valid(self) -> bool:
        if self.region == "FULL":
            return True
        if not self.region or len(self.region) != 4:
            return False
        xmin, xmax, ymin, ymax = self.region
        return (xmax - xmin) > 0 and (ymax - ymin) > 0

    # ────────────────────────────────────────────── 进度与取消
    def _check_cancel(self) -> bool:
        if self._cancelled:
            return True
        if self.cancel:
            try:
                if self.cancel():
                    self._cancelled = True
                    print(f"{LOG_PREFIX} 收到取消请求，提前结束")
            except Exception:  # noqa: BLE001 - 取消回调异常不影响流程
                pass
        return self._cancelled

    def _report_detect_progress(self) -> None:
        done = self._done_detect_frames
        total = max(self._total_detect_frames, done)
        self._emit(10 + int(85 * done / total) if total else 95,
                   f"字幕检测 {done}/{total} 帧")

    def _emit(self, value: int, message: str = "") -> None:
        """上报进度（单调保护：二分追加帧会让分母变大，否则进度会往回跳）。"""
        value = max(0, min(100, int(value)))
        if value < self._last_progress:
            value = self._last_progress
        self._last_progress = value
        if not message:
            return
        # 逐帧消息太密：仅每 2% 或首末次打印一次
        if value != 100 and value != 5 and value - getattr(self, "_last_msg_at", -99) < 2:
            return
        self._last_msg_at = value
        print(f"{LOG_PREFIX} {value}% {message}")
        if self.progress:
            try:
                self.progress(value, message)
            except Exception:  # noqa: BLE001 - 回调失败不该中断检测
                pass

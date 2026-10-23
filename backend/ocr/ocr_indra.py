"""Indra OCR engine: local CPU document OCR via the indra-ocr package.

模型：https://huggingface.co/datalab-to/indra-ocr
（Apache-2.0 代码 + 修改版 OpenRAIL-M 权重；ONNX Runtime 推理，无需 PyTorch / GPU）

与 rapidocr 接口的差异（适配层职责）：
- indra 只接收**灰度 uint8** 图像，本项目流水线传的是 BGR 裁剪数组 → 这里统一转灰度；
- indra 不做 Det/Cls/Rec 三阶段开关，`use_det/use_cls/use_rec` 等 kwargs 忽略；
- indra 的行框是轴对齐矩形 [x0, y0, x1, y1]，转成项目约定的四点四边形 [[x,y]×4]，
  下游（倾角过滤 / 字幕定位）按四点框消费；
- 输出除 `txts/boxes/scores/elapse` 外，额外附带 `text/markdown/blocks/source` 等
  文档级信息，方便调试与后续「文档解析」类节点直接复用。
"""
import importlib.util
import os
import threading
import time
from typing import Callable, Optional

from backend.ocr.ocr_base import OCRBase
from backend.ocr.ocr_interface_manager import get_ocr_interface_manager

# 引擎说明（前端 config-fields / 设置页文案使用）
MODE_OPTIONS = [
    {"value": "auto", "label": "自动（PDF 有文本层则直读，否则 OCR）"},
    {"value": "ocr", "label": "强制 OCR（忽略 PDF 文本层）"},
    {"value": "text", "label": "强制文本层（不 OCR，仅 PDF）"},
]

MODEL_REPO = "datalab-to/indra-ocr"

_INSTALL_HINT = (
    "未检测到 indra-ocr 库，请先安装依赖：pip install indra-ocr\n"
    f"首次使用会自动下载约 76MB 模型（{MODEL_REPO}）；"
    "离线环境请先准备模型目录，并在接口配置中填写 model_dir"
    "（或设置环境变量 INDRA_OCR_MODEL_DIR）。"
)

_RAPIDOCR_ONLY_OVERRIDES = ("ocr_version", "model_type", "custom_model_name")

# ── 模型文件定位与下载 ────────────────────────────────────────
# 清单与 indra_ocr.models 保持一致（*.onnx + meta.json + lm*.npz）。
# 不用 huggingface_hub.snapshot_download：hf-mirror 不回传 x-repo-commit 等元数据，
# huggingface_hub 会直接抛 FileMetadataError；这里沿用项目既有做法
# （见 backend/asr/sherpa_models.py）走 HTTP 直链 + .part 断点续传。
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION_FALLBACK = "v1.1.0"

_BASE_FILES = (
    "det.onnx", "rec.onnx", "order.onnx", "orient.onnx", "script.onnx",
    "rec_cjk.onnx", "rec_rtl.onnx", "rec_world.onnx",
    "meta.json", "lm.npz", "lm_cjk.npz", "lm_world.npz",
)
_MATH_FILES = (
    "mathcls.onnx", "math_enc.onnx", "math_dec_init.onnx", "math_dec_step.onnx",
    "math_meta.json",
)
_REQUIRED_FILES = ("det.onnx", "rec.onnx", "meta.json")


def check_indra_dependencies() -> dict:
    """探测 indra-ocr 是否已安装（不触发 import 副作用）。"""
    return {"indra_ocr": importlib.util.find_spec("indra_ocr") is not None}


def _hf_revision() -> str:
    """模型版本：与已安装的 indra-ocr 库对齐，取不到时用兜底值。"""
    try:
        from indra_ocr.models import HF_REVISION

        return str(HF_REVISION)
    except Exception:
        return _REVISION_FALLBACK


def _hf_endpoint() -> str:
    """模型下载端点：HF_ENDPOINT 优先，默认国内镜像 hf-mirror。"""
    return (os.environ.get("HF_ENDPOINT") or "https://hf-mirror.com").rstrip("/")


def _model_cache_dir(math: bool = False) -> str:
    """缓存目录：<MODEL_CACHE_DIR 或 项目根/_model_cache>/indra-ocr[-math]/<revision>。"""
    root = os.environ.get("MODEL_CACHE_DIR") or os.path.join(_PROJECT_ROOT, "_model_cache")
    return os.path.join(root, "indra-ocr-math" if math else "indra-ocr", _hf_revision())


def _model_files(math: bool = False) -> tuple:
    return _BASE_FILES + (_MATH_FILES if math else ())


def _missing_files(folder: str, files) -> list:
    missing = []
    for name in files:
        path = os.path.join(folder, name)
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            missing.append(name)
    return missing


def _download_file(url: str, dest: str, retries: int = 3) -> None:
    """HTTP 下载单个文件到 dest（.part 断点续传 + 重试）。"""
    import requests

    part = dest + ".part"
    for attempt in range(1, retries + 1):
        try:
            resume = os.path.getsize(part) if os.path.exists(part) else 0
            headers = {"User-Agent": "VideoLingoLc/1.0 (+indra-ocr model fetch)"}
            if resume:
                headers["Range"] = f"bytes={resume}-"
            with requests.get(url, stream=True, timeout=(15, 180), headers=headers) as resp:
                if resume and resp.status_code == 416:  # 已下完，只是没改名
                    os.replace(part, dest)
                    return
                resp.raise_for_status()
                mode = "ab" if resume and resp.status_code == 206 else "wb"
                with open(part, mode) as fp:
                    for chunk in resp.iter_content(256 * 1024):
                        if chunk:
                            fp.write(chunk)
            os.replace(part, dest)
            return
        except Exception as exc:  # noqa: BLE001 网络抖动统一重试
            if attempt >= retries:
                raise RuntimeError(f"下载 {os.path.basename(dest)} 失败：{exc}") from exc
            print(f"[IndraOCR] 下载 {os.path.basename(dest)} 第 {attempt} 次失败（{exc}），重试...")
            time.sleep(1.5 * attempt)


def ensure_model_dir(
    math: bool = False,
    progress: Optional[Callable[[int, str], None]] = None,
) -> str:
    """确保本地模型目录完整（缺失文件按需下载），返回目录路径。"""
    folder = _model_cache_dir(math)
    files = _model_files(math)
    missing = _missing_files(folder, files)
    if not missing:
        return folder

    os.makedirs(folder, exist_ok=True)
    endpoint = _hf_endpoint()
    revision = _hf_revision()
    total = len(missing)
    for idx, name in enumerate(missing):
        if progress:
            progress(3 + int(7 * idx / max(1, total)),
                     f"下载 Indra OCR 模型 {name}（{idx + 1}/{total}）...")
        url = f"{endpoint}/{MODEL_REPO}/resolve/{revision}/{name}"
        print(f"[IndraOCR] 下载模型 {name} -> {folder}")
        _download_file(url, os.path.join(folder, name))

    still = _missing_files(folder, files)
    if still:
        raise RuntimeError(f"Indra OCR 模型目录不完整，缺少：{', '.join(still)}")
    return folder


def _to_gray(image):
    """把 BGR / BGRA / 灰度 ndarray 统一成连续 uint8 灰度图。"""
    import cv2
    import numpy as np

    arr = np.asarray(image)
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    if arr.ndim == 3:
        channels = arr.shape[2]
        if channels == 1:
            arr = arr[:, :, 0]
        elif channels == 4:
            arr = cv2.cvtColor(arr, cv2.COLOR_BGRA2GRAY)
        elif channels == 3:
            arr = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
        else:
            raise ValueError(f"不支持的图像通道数：{channels}")
    if arr.ndim != 2:
        raise ValueError(f"不支持的图像形状：{arr.shape}")
    return np.ascontiguousarray(arr)


def _box_to_polygon(box) -> list:
    """轴对齐矩形 [x0, y0, x1, y1] → 四点四边形（顺时针，左上起点）。"""
    x0, y0, x1, y1 = (float(v) for v in box[:4])
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


class IndraOCREngine(OCRBase):
    """Indra OCR 本地推理引擎，按接口 config 惰性构建 Converter 并缓存。"""

    def __init__(self, iface_id: str, overrides: Optional[dict] = None):
        self.iface_id = iface_id
        self._overrides = dict(overrides or {})
        self._engine = None
        self._math_loaded = None     # 已加载引擎的公式开关（recognize 的 math kwarg 变更时重建）
        self._use_cuda = False
        self._lock = threading.Lock()

    # ── 参数组装 ─────────────────────────────────────────────
    @staticmethod
    def _resolve_threads(cfg: dict) -> int:
        """线程数：-1 / 0 / 空 → 按 CPU 核心数；其余取配置值。"""
        try:
            threads = int(cfg.get("threads", 4) or 0)
        except (TypeError, ValueError):
            threads = 0
        if threads <= 0:
            return max(1, os.cpu_count() or 4)
        return threads

    @staticmethod
    def _resolve_providers(cfg: dict):
        """use_cuda 且本机 onnxruntime 带 CUDA EP 时启用 GPU，否则回退 CPU。"""
        if not bool(cfg.get("use_cuda", False)):
            return None
        try:
            import onnxruntime as ort
        except ImportError:
            return None
        if "CUDAExecutionProvider" not in ort.get_available_providers():
            print("[IndraOCR] 已启用 CUDA，但当前 onnxruntime 无 CUDAExecutionProvider，回退 CPU")
            return None
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]

    def _load_config(self) -> dict:
        mgr = get_ocr_interface_manager()
        iface = mgr.get(self.iface_id)
        if not iface:
            raise ValueError(f"OCR interface '{self.iface_id}' not found")
        return iface.get("config", {}) or {}

    # ── 引擎惰性初始化 ────────────────────────────────────────
    @staticmethod
    def _resolve_model_dir(cfg: dict, callback: Optional[Callable] = None):
        """模型目录：接口配置 model_dir > 环境变量 INDRA_OCR_MODEL_DIR > 自动下载缓存。

        自动下载失败时返回 None，交给 indra_ocr 自带的 huggingface_hub 逻辑再试一次。
        """
        explicit = str(cfg.get("model_dir") or "").strip()
        if explicit:
            if not os.path.isdir(explicit):
                raise RuntimeError(f"Indra OCR 模型目录不存在：{explicit}")
            return explicit
        env_dir = (os.environ.get("INDRA_OCR_MODEL_DIR") or "").strip()
        if env_dir:
            return env_dir
        try:
            return ensure_model_dir(bool(cfg.get("math", False)), progress=callback)
        except Exception as exc:  # noqa: BLE001 下载失败再给 hub 一次机会
            print(f"[IndraOCR] 模型自动下载失败：{exc}；回退 huggingface_hub 下载")
            return None

    def _get_engine(self, callback: Optional[Callable] = None, math: Optional[bool] = None):
        """惰性加载/复用 Converter。

        ``math`` 非 None 时覆盖接口配置的公式开关；公式模型是加载期参数
        （需额外 ~20MB 权重），与已加载引擎不一致时自动卸载重建。
        """
        if self._engine is not None and (math is None or self._math_loaded == bool(math)):
            return self._engine
        with self._lock:
            if self._engine is not None and (math is None or self._math_loaded == bool(math)):
                return self._engine
            if self._engine is not None:
                print(f"[IndraOCR] 公式开关变更为 {bool(math)}，卸载重建引擎")
                self._engine = None
            try:
                import indra_ocr
            except ImportError as exc:
                raise RuntimeError(_INSTALL_HINT) from exc

            cfg = self._load_config()
            # 节点级 overrides 目前只服务 rapidocr（版本/尺寸/自定义模型名），
            # Indra 的模型由 model_dir 决定，这里忽略这些键而不是报错。
            ignored = [k for k in self._overrides if k in _RAPIDOCR_ONLY_OVERRIDES]
            if ignored and any(self._overrides.get(k) for k in ignored):
                print(f"[IndraOCR] 节点级模型覆盖 {ignored} 不适用于 Indra，已忽略")

            want_math = bool(cfg.get("math", False)) if math is None else bool(math)
            model_dir = self._resolve_model_dir(cfg, callback)
            try:
                self._engine = indra_ocr.load(
                    path=model_dir or None,
                    threads=self._resolve_threads(cfg),
                    dpi=float(cfg.get("dpi", 200) or 200),
                    mode=str(cfg.get("mode") or "auto"),
                    image_ocr=bool(cfg.get("image_ocr", True)),
                    providers=self._resolve_providers(cfg),
                    furniture=bool(cfg.get("furniture", False)),
                    math=want_math,
                )
            except Exception as exc:
                raise RuntimeError(f"Indra OCR 引擎初始化失败：{exc}") from exc
            self._use_cuda = bool(cfg.get("use_cuda", False))
            self._math_loaded = want_math
        return self._engine

    def unload(self):
        """释放引擎实例并归还内存/显存。"""
        with self._lock:
            if self._engine is None:
                return
            self._engine = None
            self._math_loaded = None
        import gc

        gc.collect()

    # ── 识别 ─────────────────────────────────────────────────
    def _read_page(self, engine, input_path, kwargs, turn: bool = False):
        """对图片路径 / 内存图像执行识别，返回 indra Page。

        turn=True 时先用 orient.onnx 判断整页方向（整页扫描件才需要；字幕裁剪图
        是正向的，关闭可省掉一次方向推理，实测约快 2~3 倍）。
        """
        import cv2
        import numpy as np

        if isinstance(input_path, np.ndarray):
            return engine.ocr(_to_gray(input_path), turn=turn)

        path = str(input_path)
        if not os.path.isfile(path):
            raise ValueError(f"图片文件不存在：{path}")
        # 单张图片直接读灰度喂给 OrtOCR，才能按配置控制 turn；
        # cv2 读不了（多页 TIFF、加密文档等）时退回 convert（PDF/文档路径）。
        gray = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if gray is not None:
            return engine.ocr(np.ascontiguousarray(gray), turn=turn)

        max_pages = int(kwargs.get("max_pages", 1) or 1)
        last_note = ""
        for _idx, page in engine.convert(path, max_pages=max_pages):
            if getattr(page, "source", "") == "error":
                last_note = getattr(page, "note", "") or "unknown error"
                continue
            return page
        raise RuntimeError(f"Indra OCR 识别失败：{last_note or '未产生任何页面结果'}")

    def recognize(
        self,
        input_path,
        callback: Optional[Callable] = None,
        **kwargs,
    ) -> dict:
        """识别图片（文件路径或 BGR ndarray）中的文本。

        kwargs 支持 `max_pages`（退回 convert 路径时生效，默认 1）、
        `detect_orientation`（覆盖接口配置）、`math`（覆盖接口配置的公式开关，
        按需重建引擎）、`text_score`（覆盖接口配置的置信度阈值）；
        `use_det/use_cls/use_rec` 等 rapidocr 专用开关忽略。
        """
        if callback:
            callback(10, "初始化 Indra OCR 引擎...")
        engine = self._get_engine(callback, math=kwargs.get("math"))

        cfg = self._load_config()
        turn = kwargs.get("detect_orientation")
        if turn is None:
            turn = bool(cfg.get("detect_orientation", False))

        if callback:
            callback(40, "正在识别图片文本...")
        t0 = time.perf_counter()
        page = self._read_page(engine, input_path, kwargs, turn=bool(turn))
        if callback:
            callback(100, "识别完成")

        try:
            min_conf = float(kwargs.get("text_score", cfg.get("text_score", 0.0)) or 0.0)
        except (TypeError, ValueError):
            min_conf = 0.0

        txts, boxes, scores = [], [], []
        for line in page.lines or []:
            text = (line.text or "").strip()
            if not text:
                continue
            conf = float(getattr(line, "conf", 0.0) or 0.0)
            if min_conf > 0 and conf < min_conf:
                continue
            txts.append(text)
            boxes.append(_box_to_polygon(line.box))
            scores.append(conf)

        elapse = float((page.timings or {}).get("total_ms", 0.0)) / 1000.0
        if elapse <= 0:
            elapse = time.perf_counter() - t0

        return {
            "txts": txts,
            "boxes": boxes,
            "scores": scores,
            "elapse": elapse,
            # ── 文档级附加信息（不影响 rapidocr 兼容消费方）──
            "text": page.text or "",
            "markdown": page.markdown or "",
            "blocks": [
                {"label": b.get("label", ""), "bbox": list(b.get("bbox") or []), "text": b.get("text", "")}
                for b in (page.blocks or [])
            ],
            "source": getattr(page, "source", ""),
            "rotation": int(getattr(page, "rotation", 0) or 0),
            "skew": float(getattr(page, "skew", 0.0) or 0.0),
        }

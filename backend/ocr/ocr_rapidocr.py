"""RapidOCR engine: local OCR via the rapidocr library.

推理引擎约定（与设置页一致）：
- onnxruntime：CPU 默认引擎（pip install onnxruntime）
- torch：GPU 默认引擎（使用项目已安装的 PyTorch CUDA 版）
- paddle：GPU 备用引擎（默认不安装，需用户手动安装 paddlepaddle 后使用）
"""
import importlib.util
import re
import threading
from enum import Enum
from typing import Callable, Optional

from backend.ocr.ocr_base import OCRBase
from backend.ocr.ocr_interface_manager import get_ocr_interface_manager

# 各 OCR 版本支持的模型尺寸
SIZES_BY_VERSION = {
    "PP-OCRv6": ["tiny", "small", "medium"],
    "PP-OCRv5": ["mobile", "server"],
    "PP-OCRv4": ["mobile", "server"],
}

# 引擎说明（前端 config-fields / 设置页文案使用）
ENGINE_OPTIONS = [
    {"value": "onnxruntime", "label": "ONNX Runtime（CPU，推荐）", "description": "CPU 默认引擎，兼容性最好，推荐首选"},
    {"value": "torch", "label": "PyTorch（GPU）", "description": "GPU 默认引擎，使用项目已安装的 PyTorch（CUDA 版）"},
    {"value": "paddle", "label": "PaddlePaddle（GPU 备用）", "description": "GPU 备用引擎，未随项目安装，需手动安装 paddlepaddle"},
]

LANG_OPTIONS = [
    {"value": "ch", "label": "中文（中英混合）"},
    {"value": "en", "label": "英文"},
    {"value": "multi", "label": "多语言"},
]

_RAPIDOCR_IMPORT_ERROR = (
    "未检测到 rapidocr 库，请先安装依赖：pip install rapidocr onnxruntime\n"
    "如需 GPU 推理请额外安装对应引擎：pip install torch（项目已装）或 paddlepaddle-gpu（按官方文档选择 CUDA 版本）"
)


def check_ocr_dependencies() -> dict:
    """探测 OCR 相关依赖是否已安装（不触发 import 副作用）。"""
    return {
        "rapidocr": importlib.util.find_spec("rapidocr") is not None,
        "onnxruntime": importlib.util.find_spec("onnxruntime") is not None,
        "torch": importlib.util.find_spec("torch") is not None,
        "paddle": importlib.util.find_spec("paddle") is not None,
    }


def _to_enum(enum_cls, value):
    """把字符串转成 rapidocr 枚举成员；无法匹配时构造同值成员透传（保留原始字符串）。

    rapidocr 的 params 接口要求 engine_type/model_type/ocr_version 等必须是 Enum 类型
    （见 rapidocr/utils/parse_parameters.py 的 update_batch，只检查 isinstance(v, Enum)，
    后续通过 .value 解析模型名）。Python 3.11+ 禁止为已有成员的枚举扩展子类，因此对
    用户自定义模型名这类库里尚不存在的值，采用标准 _missing_ 模式直接构造原枚举成员。
    """
    try:
        return enum_cls(value)
    except ValueError:
        name = re.sub(r"[^A-Za-z0-9_]", "_", str(value)).upper() or "CUSTOM"
        existing = enum_cls._value2member_map_.get(value)
        if existing is not None:
            return existing
        member = object.__new__(enum_cls)
        member._name_ = name
        member._value_ = value
        enum_cls._value2member_map_[value] = member
        enum_cls._member_map_[name] = member
        return member


class RapidOCREngine(OCRBase):
    """RapidOCR 本地推理引擎，按接口 config 构建 RapidOCR 实例并缓存。"""

    def __init__(self, iface_id: str, overrides: Optional[dict] = None):
        self.iface_id = iface_id
        self._overrides = dict(overrides or {})  # 节点级模型覆盖参数（版本/尺寸/自定义名）
        self._engine = None
        self._lock = threading.Lock()

    # ── 参数组装 ─────────────────────────────────────────────
    @staticmethod
    def _build_params(cfg: dict, overrides: Optional[dict] = None) -> dict:
        """把接口 config 组装成 rapidocr 的点分路径参数。

        overrides 为节点级模型覆盖（非空字段生效，留空跟随接口默认）：
        - ocr_version / model_type / custom_model_name
        """
        try:
            from rapidocr import EngineType, LangDet, LangRec, ModelType, OCRVersion
        except ImportError as exc:  # pragma: no cover - 仅防御
            raise RuntimeError(_RAPIDOCR_IMPORT_ERROR) from exc

        overrides = overrides or {}
        engine_type_name = cfg.get("engine_type", "onnxruntime")
        engine_type = EngineType(engine_type_name)
        ocr_version = overrides.get("ocr_version") or cfg.get("ocr_version", "PP-OCRv6")
        model_type = overrides.get("model_type") or cfg.get("model_type", "small")
        custom_model_name = (
            overrides.get("custom_model_name")
            or cfg.get("custom_model_name")
            or ""
        ).strip()

        # 自定义模型名透传：非空时原样覆盖版本/尺寸（高级用法，需自行确保模型存在）
        if custom_model_name:
            ocr_version = custom_model_name
            model_type = custom_model_name

        lang_type = cfg.get("lang_type", "ch")

        params = {
            "Det.engine_type": engine_type,
            "Det.ocr_version": _to_enum(OCRVersion, ocr_version),
            "Det.model_type": _to_enum(ModelType, model_type),
            "Det.lang_type": _to_enum(LangDet, lang_type),
            "Det.limit_side_len": cfg.get("limit_side_len", 736),
            "Det.box_thresh": cfg.get("box_thresh", 0.5),
            "Det.unclip_ratio": cfg.get("unclip_ratio", 1.6),
            "Cls.engine_type": engine_type,
            "Rec.engine_type": engine_type,
            "Rec.ocr_version": _to_enum(OCRVersion, ocr_version),
            "Rec.model_type": _to_enum(ModelType, model_type),
            "Rec.lang_type": _to_enum(LangRec, lang_type),
            "Global.text_score": cfg.get("text_score", 0.5),
            "Global.return_word_box": cfg.get("return_word_box", False),
        }

        device_id = cfg.get("device_id", 0)
        use_cuda = bool(cfg.get("use_cuda", False))
        if engine_type_name == "onnxruntime":
            params["EngineConfig.onnxruntime.intra_op_num_threads"] = cfg.get("threads", -1)
            params["EngineConfig.onnxruntime.use_cuda"] = use_cuda
            params["EngineConfig.onnxruntime.cuda_ep_cfg.device_id"] = device_id
        elif engine_type_name == "torch":
            params["EngineConfig.torch.use_cuda"] = use_cuda
            params["EngineConfig.torch.cuda_ep_cfg.device_id"] = device_id
        elif engine_type_name == "paddle":
            params["EngineConfig.paddle.use_cuda"] = use_cuda
            params["EngineConfig.paddle.cuda_ep_cfg.device_id"] = device_id

        return params

    def _load_config(self) -> dict:
        mgr = get_ocr_interface_manager()
        iface = mgr.get(self.iface_id)
        if not iface:
            raise ValueError(f"OCR interface '{self.iface_id}' not found")
        return iface.get("config", {})

    # ── 引擎惰性初始化 ────────────────────────────────────────
    def _get_engine(self):
        if self._engine is not None:
            return self._engine
        with self._lock:
            if self._engine is not None:
                return self._engine
            try:
                from rapidocr import RapidOCR
            except ImportError as exc:
                raise RuntimeError(_RAPIDOCR_IMPORT_ERROR) from exc

            cfg = self._load_config()
            params = self._build_params(cfg, self._overrides)
            self.engine_type_name = cfg.get("engine_type", "onnxruntime")

            # 选中的引擎未安装时给出明确指引
            engine_type = cfg.get("engine_type", "onnxruntime")
            deps = check_ocr_dependencies()
            if engine_type == "paddle" and not deps["paddle"]:
                raise RuntimeError(
                    "已选择 PaddlePaddle 引擎，但未检测到 paddlepaddle。\n"
                    "请手动安装（按官方文档选择 CUDA 版本）：pip install paddlepaddle-gpu\n"
                    "参考：https://www.paddlepaddle.org.cn/install/quick"
                )
            if engine_type == "torch" and not deps["torch"]:
                raise RuntimeError("已选择 PyTorch 引擎，但未检测到 torch，请先安装 PyTorch。")

            self._engine = RapidOCR(params=params)
        return self._engine

    def _clear_engine(self):
        """配置变更后释放缓存实例，下次调用时按新配置重建。"""
        with self._lock:
            self._engine = None

    def unload(self):
        """释放引擎实例并归还内存/显存（torch 引擎额外清空显存缓存）。"""
        with self._lock:
            if self._engine is None:
                return
            try:
                if getattr(self, "engine_type_name", "") == "torch":
                    import torch
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
            except Exception:
                pass
            self._engine = None
        import gc
        gc.collect()

    # ── 识别 ─────────────────────────────────────────────────
    def recognize(
        self,
        input_path,
        callback: Optional[Callable] = None,
        **kwargs,
    ) -> dict:
        """识别图片中的文本。

        input_path 支持图片文件路径（str）或内存图片数组（ndarray，BGR），
        便于批量流水线直接传入裁剪后的字幕区域。
        """
        if callback:
            callback(10, "初始化 RapidOCR 引擎...")
        engine = self._get_engine()

        cfg = self._load_config()
        use_det = kwargs.get("use_det", cfg.get("use_det", True))
        use_cls = kwargs.get("use_cls", cfg.get("use_cls", True))
        use_rec = kwargs.get("use_rec", cfg.get("use_rec", True))

        if callback:
            callback(40, "正在识别图片文本...")
        result = engine(input_path, use_det=use_det, use_cls=use_cls, use_rec=use_rec)
        if callback:
            callback(100, "识别完成")

        return self._to_dict(result)

    @staticmethod
    def _to_dict(result) -> dict:
        """把 RapidOCROutput 转为可 JSON 序列化的 dict。"""
        txts = list(result.txts) if result.txts else []
        scores = [float(s) for s in result.scores] if result.scores else []
        elapse = float(result.elapse) if getattr(result, "elapse", None) is not None else 0.0

        boxes = []
        if result.boxes is not None:
            boxes = [[[float(coord) for coord in point] for point in box] for box in result.boxes]

        return {
            "txts": txts,
            "boxes": boxes,
            "scores": scores,
            "elapse": elapse,
        }

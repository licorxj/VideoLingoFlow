# -*- coding: utf-8 -*-
"""PDF 识别步骤：直连 Indra OCR 解析 PDF 文档（多页版面/表格/公式/Markdown）。

与接口管理器（/api/ocr-interfaces）解耦——本步骤直接 import indra_ocr 包
加载 Converter，不经过 OCR 接口选择；识别参数由节点 config 覆写。

模型目录解析顺序：节点 model_dir > 环境变量 INDRA_OCR_MODEL_DIR >
indra_ocr 接口配置 model_dir > 自动下载（ensure_model_dir，镜像重试）。

输入端口 `pdf`（any）支持：本地路径（绝对/相对）、http(s) URL（自动下载）、
data URI / 整段 base64（自动落盘）；输出类型由节点面板 `output_type` 决定
（markdown / text / json / filepath），端口类型随前端 getVisibleOutputs 联动。
"""
import base64
import binascii
import gc
import json
import os
import re
import time
import urllib.request
from typing import Callable, Dict, List, Optional

from backend.steps.base_step import BaseStep, find_artifact

_PDF_MAGIC = b"%PDF"
_INSTALL_HINT = "未安装 indra-ocr，请先执行：pip install indra-ocr"

# output_type → (文件扩展名, 说明)
OUTPUT_EXTS = {
    "markdown": ".md",
    "text": ".txt",
    "json": ".json",
    "filepath": ".md",
}


def _log(log, msg):
    if callable(log):
        try:
            log(msg)
        except Exception:
            pass


def _unwrap_input(raw):
    """把上游传入值归一成单个字符串（兼容 dict/list 包装）。"""
    if isinstance(raw, dict):
        for key in ("path", "file", "pdf", "url", "local_path", "input", "value"):
            v = raw.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        raise ValueError("输入对象中未找到 PDF 路径/URL（支持的键：path/file/pdf/url/local_path）")
    if isinstance(raw, (list, tuple)):
        for item in raw:
            if isinstance(item, str) and item.strip():
                return item.strip()
        raise ValueError("输入列表为空或未包含 PDF 路径")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    raise ValueError(f"不支持的 PDF 输入类型：{type(raw).__name__}（应为路径/URL/base64 字符串）")


def _is_abs(path: str) -> bool:
    return path.startswith(("/", "\\")) or (len(path) > 1 and path[1] == ":")


def _ensure_pdf(path: str, where: str = "PDF"):
    try:
        with open(path, "rb") as fp:
            head = fp.read(1024)
    except OSError as e:
        raise ValueError(f"无法读取{where}文件 {path}: {e}")
    if not head.lstrip().startswith(_PDF_MAGIC):
        raise ValueError(f"不是有效的 PDF 文件（文件头缺少 %PDF 签名）：{path}")


def _write_b64_pdf(payload: str, task_dir: str, node_id: str) -> str:
    try:
        data = base64.b64decode(payload.strip(), validate=False)
    except (binascii.Error, ValueError) as e:
        raise ValueError(f"base64 解码失败：{e}")
    if not data.startswith(_PDF_MAGIC):
        raise ValueError("base64 内容不是 PDF（解码后缺少 %PDF 签名）")
    dst = os.path.join(task_dir, "input")
    os.makedirs(dst, exist_ok=True)
    path = os.path.join(dst, f"{node_id}_input.pdf")
    with open(path, "wb") as fp:
        fp.write(data)
    return os.path.abspath(path)


def _download_pdf(url: str, task_dir: str, node_id: str, timeout: int = 180) -> str:
    dst = os.path.join(task_dir, "input")
    os.makedirs(dst, exist_ok=True)
    path = os.path.join(dst, f"{node_id}_input.pdf")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 VideoLingoLc/PDF-OCR"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(path, "wb") as fp:
        fp.write(resp.read())
    _ensure_pdf(path, "下载的")
    return os.path.abspath(path)


def _resolve_pdf_path(raw, task_dir: str, node_id: str, log) -> str:
    """把输入值解析为本地 PDF 绝对路径（支持路径/URL/data URI/base64）。"""
    text = _unwrap_input(raw)
    if text.lower().startswith("data:"):
        header, _, payload = text.partition(",")
        if "base64" not in header.lower():
            raise ValueError("仅支持 base64 编码的 data URI（PDF）")
        return _write_b64_pdf(payload, task_dir, node_id)
    if text.lower().startswith(("http://", "https://")):
        _log(log, f"下载 PDF: {text}")
        return _download_pdf(text, task_dir, node_id)

    candidates = [text] if _is_abs(text) else [os.path.join(task_dir, text), text]
    for cand in candidates:
        if os.path.isfile(cand):
            _ensure_pdf(cand)
            return os.path.abspath(cand)
    # 整段 base64 兜底（"%PDF" 的 base64 前缀为 "JVBER"）
    if text.startswith("JVBER"):
        return _write_b64_pdf(text, task_dir, node_id)
    raise FileNotFoundError(f"PDF 文件不存在：{text}（已尝试：{candidates}）")


def _parse_page_range(spec, total: int) -> Optional[set]:
    """解析页码范围（1 基），如 "1-5,8,11-20"；空 = 全部页。"""
    if spec is None or not str(spec).strip():
        return None
    # 先去掉所有空白（兼容 "1 - 2 , 5" 这类带空格写法），再按分隔符切分
    wanted = set()
    for part in re.split(r"[,，;；]+", re.sub(r"\s+", "", str(spec))):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)[-~](\d*)", part)
        if m:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else total
            if total and end > total:
                end = total
            if end < start:
                start, end = end, start
            wanted.update(range(max(1, start), end + 1))
        elif part.isdigit():
            wanted.add(int(part))
        else:
            raise ValueError(f"页码范围格式错误：{part}（示例：1-5,8,11-20）")
    if not wanted:
        return None
    if total:
        out_of_range = sorted(n for n in wanted if n < 1 or n > total)
        if out_of_range:
            raise ValueError(f"页码范围超出文档页数（共 {total} 页）：{out_of_range}")
    return wanted


def _count_pdf_pages(path: str) -> int:
    """读取 PDF 总页数（拿不到返回 0，表示未知）。"""
    try:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(path)
        try:
            return len(doc)
        finally:
            doc.close()
    except Exception:
        return 0


def _resolve_model_dir(node_value) -> Optional[str]:
    """模型目录：节点 model_dir > 环境变量 > indra_ocr 接口配置 > None（自动下载）。"""
    if node_value is not None and str(node_value).strip():
        return os.path.abspath(str(node_value).strip())
    env = os.environ.get("INDRA_OCR_MODEL_DIR")
    if env and env.strip():
        return os.path.abspath(env.strip())
    try:
        from backend.ocr.ocr_interface_manager import get_ocr_interface_manager

        iface = get_ocr_interface_manager().get("indra_ocr") or {}
        md = str((iface.get("config") or {}).get("model_dir") or "").strip()
        if md:
            return os.path.abspath(md)
    except Exception:
        pass
    return None


def _load_indra_engine(model_dir: Optional[str], threads: int, dpi: float, mode: str,
                       image_ocr: bool, furniture: bool, math: bool, use_cuda: bool):
    """直连 indra_ocr 包加载 Converter（不走接口管理器）。"""
    try:
        import indra_ocr
    except ImportError as e:
        raise RuntimeError(f"{_INSTALL_HINT}（{e}）")

    if model_dir is None:
        from backend.ocr.ocr_indra import ensure_model_dir

        model_dir = ensure_model_dir(math=bool(math))

    providers = None
    if use_cuda:
        try:
            import onnxruntime as ort

            if "CUDAExecutionProvider" in ort.get_available_providers():
                providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        except Exception:
            providers = None

    engine = indra_ocr.load(
        path=str(model_dir),
        threads=int(threads or 0),
        dpi=float(dpi or 200),
        mode=str(mode or "auto"),
        image_ocr=bool(image_ocr),
        providers=providers,
        furniture=bool(furniture),
        math=bool(math),
    )
    return engine, str(model_dir)


def _page_payload(page, page_no: int, text_score: float) -> Dict:
    """把 indra Page 转成可 JSON 序列化的结构（bbox 像素坐标，阅读顺序）。"""
    blocks = []
    for blk in (page.blocks or []):
        bbox = blk.get("bbox") or []
        blocks.append({
            "label": blk.get("label", "") or "",
            "bbox": [round(float(v), 2) for v in bbox],
            "text": (blk.get("text") or "").strip(),
        })
    lines = []
    for ln in (page.lines or []):
        conf = float(getattr(ln, "conf", 0.0) or 0.0)
        if text_score and conf < text_score:
            continue
        lines.append({
            "bbox": [round(float(v), 2) for v in (ln.box or [])],
            "text": ln.text,
            "conf": round(conf, 4),
        })
    return {
        "page": page_no,
        "source": getattr(page, "source", "") or "",
        "note": getattr(page, "note", "") or "",
        "rotation": int(getattr(page, "rotation", 0) or 0),
        "skew": round(float(getattr(page, "skew", 0.0) or 0.0), 4),
        "vertical": bool(getattr(page, "vertical", False)),
        "timings": getattr(page, "timings", {}) or {},
        "markdown": page.markdown or "",
        "text": page.text or "",
        "blocks": blocks,
        "lines": lines,
        "pictures": [[round(float(v), 2) for v in bbox] for bbox in (page.pictures or [])],
    }


class S_PdfOcr(BaseStep):
    """PDF 识别：直连 Indra OCR，多页解析为 Markdown / 纯文本 / 结构化 JSON / 文件。"""

    step_id = "s_pdf_ocr"
    step_name = "PDF识别"
    dependencies = []
    artifacts = []

    INPUT_EXTS = {".pdf"}
    OUTPUT_EXTS = OUTPUT_EXTS

    def check_artifact(self, task_dir: str) -> bool:
        """输出目录兜底扫描：任一受支持扩展名存在即视为有产物。"""
        out_dir = os.path.join(task_dir, "output", self._node_id)
        for ext in (".md", ".txt", ".json"):
            if find_artifact(out_dir, f"pdf_ocr{ext}"):
                return True
        return False

    def validate_inputs(self, **kwargs) -> bool:
        raw = (getattr(self, "_step_inputs", None) or {}).get("pdf")
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            raise ValueError("未提供 PDF 输入：请连接 any 类型的上游端口（或输入节点文件路径）")
        return True

    def run(self, task_dir, callback: Optional[Callable[[int, str], None]] = None,
            cancel_callback: Optional[Callable[[], bool]] = None, **kwargs):
        started = time.time()
        log = kwargs.get("log")

        def report(p: int, msg: str):
            if callback:
                try:
                    callback(p, msg)
                except Exception:
                    pass

        raw = (getattr(self, "_step_inputs", None) or {}).get("pdf")
        cfg = getattr(self, "_node_config", None) or {}
        node_id = getattr(self, "_node_id", None) or "node"

        # ── 1. 解析输入 PDF ─────────────────────────────────────
        report(2, "解析 PDF 输入")
        pdf_path = _resolve_pdf_path(raw, task_dir, node_id, log)
        pdf_name = os.path.basename(pdf_path)
        _log(log, f"PDF 输入：{pdf_path}")

        # ── 2. 识别参数 ─────────────────────────────────────────
        output_type = str(cfg.get("output_type") or "markdown").strip().lower()
        if output_type not in OUTPUT_EXTS:
            raise ValueError(f"output_type 不支持：{output_type}（可选：{'/'.join(OUTPUT_EXTS)}）")
        mode = str(cfg.get("mode") or "auto").strip().lower()
        if mode not in ("auto", "ocr", "text"):
            raise ValueError(f"mode 不支持：{mode}（可选：auto/ocr/text）")
        dpi = float(cfg.get("dpi") or 200)
        if not 36 <= dpi <= 1200:
            raise ValueError(f"dpi 超出范围（36~1200）：{dpi}")
        image_ocr = bool(cfg.get("image_ocr", True))
        furniture = bool(cfg.get("furniture", False))
        math = bool(cfg.get("math", False))
        use_cuda = bool(cfg.get("use_cuda", False))
        threads = int(cfg.get("threads") or 0)
        text_score = float(cfg.get("text_score") or 0.0)
        if not 0.0 <= text_score <= 1.0:
            raise ValueError(f"text_score 需在 0~1 之间：{text_score}")
        max_pages = int(cfg.get("max_pages") or 0)
        if max_pages < 0:
            raise ValueError(f"max_pages 不能为负：{max_pages}")
        password = str(cfg.get("pdf_password") or "") or None

        # ── 3. 页码范围（先数页再解析范围） ─────────────────────
        total_pages = _count_pdf_pages(pdf_path)
        range_spec = str(cfg.get("page_range") or "").strip()
        if not total_pages:
            # 页数仅用于范围校验与进度估算，未知时告警续跑（引擎仍可流式逐页处理）
            _log(log, f"[WARN] 无法读取 PDF 页数（按流式处理，页码范围上限不可用）：{pdf_path}")
            if range_spec:
                open_ended = any(
                    re.fullmatch(r"\d+[-~]", re.sub(r"\s+", "", part))
                    for part in re.split(r"[,，;；]+", range_spec) if part
                )
                if open_ended:
                    raise ValueError(
                        f"无法读取 PDF 页数，开放式页码范围不可用：{range_spec}"
                        "（请改为明确页码，或修复 PDF 文件）")
        wanted = _parse_page_range(cfg.get("page_range"), total_pages)
        if wanted is not None:
            _log(log, f"页码范围命中 {len(wanted)}/{total_pages or '?'} 页")
        scan_limit = max_pages or 0
        if wanted is not None and scan_limit:
            scan_limit = max(scan_limit, max(wanted))
        _log(log, f"识别参数：输出={output_type} 模式={mode} dpi={dpi:g} 页数={total_pages}"
                  f" 范围={'全部' if wanted is None else sorted(wanted)}"
                  f" 图片文字={image_ocr} 页眉页脚={furniture} 公式={math}")

        # ── 4. 加载引擎（直连 indra_ocr） ───────────────────────
        report(5, "加载 Indra OCR 模型")
        model_dir = _resolve_model_dir(cfg.get("model_dir"))
        engine, resolved_model_dir = _load_indra_engine(
            model_dir, threads, dpi, mode, image_ocr, furniture, math, use_cuda)
        _log(log, f"Indra 引擎就绪：{resolved_model_dir}"
                  f"（providers={'cuda' if use_cuda else 'cpu'}）")

        # ── 5. 逐页识别 ────────────────────────────────────────
        pages_payload: List[Dict] = []
        done = 0
        try:
            for page_no, page in engine.convert(pdf_path, max_pages=scan_limit, password=password):
                if cancel_callback and cancel_callback():
                    raise RuntimeError("任务已被用户取消")
                if wanted is not None and page_no not in wanted:
                    continue
                pages_payload.append(_page_payload(page, page_no, text_score))
                done += 1
                denom = total_pages or scan_limit or done
                report(10 + int(80 * done / max(1, denom)),
                       f"识别第 {page_no} 页" + (f"/{total_pages}" if total_pages else "")
                       + f"（{page.source or '-'}）")
        finally:
            del engine
            gc.collect()

        if not pages_payload:
            raise RuntimeError("没有识别到任何页面（页码范围或 max_pages 过滤后为空）")

        # ── 6. 组装输出 ────────────────────────────────────────
        report(92, "生成输出文件")
        markdown_text = "\n\n".join(
            (p["markdown"] or "").strip() or (p["text"] or "").strip()
            for p in pages_payload if (p["markdown"] or p["text"])
        ).strip()
        plain_text = "\n\n".join(
            (p["text"] or "").strip() or (p["markdown"] or "").strip()
            for p in pages_payload if (p["text"] or p["markdown"])
        ).strip()

        ext = OUTPUT_EXTS[output_type]
        out_dir = os.path.join(task_dir, "output", node_id)
        os.makedirs(out_dir, exist_ok=True)
        output_path = os.path.join(out_dir, f"pdf_ocr{ext}")
        with open(output_path, "w", encoding="utf-8") as fp:
            if output_type in ("markdown", "filepath"):
                fp.write(markdown_text)
            elif output_type == "text":
                fp.write(plain_text)
            else:
                json.dump({
                    "file": pdf_name,
                    "page_count": total_pages,
                    "recognized_pages": [p["page"] for p in pages_payload],
                    "mode": mode,
                    "dpi": dpi,
                    "elapsed_ms": int((time.time() - started) * 1000),
                    "pages": pages_payload,
                }, fp, ensure_ascii=False, indent=2)

        rel = os.path.relpath(output_path, task_dir)
        self.artifacts = [rel]
        elapsed = time.time() - started
        _log(log, f"PDF 识别完成：{len(pages_payload)} 页，输出 {output_path}（{elapsed:.1f}s）")
        report(100, f"完成（{len(pages_payload)} 页 / {elapsed:.1f}s）")

        return {
            "outputs": {"result": output_path},
            "artifacts": [rel],
        }

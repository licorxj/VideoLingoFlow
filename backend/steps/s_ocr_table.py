# -*- coding: utf-8 -*-
"""OCR 表格识别步骤：直连 Indra OCR 从 PDF / 图片中提取表格结构。

与接口管理器（/api/ocr-interfaces）解耦——本步骤直接 import indra_ocr 包
加载 Converter，复用 s_pdf_ocr 的引擎加载 / 模型目录 / 页码范围逻辑，
在此基础上做「表格专项提取」：

- 版面模型（order.onnx 布局头）定位 Table / Form / Table-Of-Contents 块；
- 表格结构优先取引擎 Markdown 中的 HTML ``<table>``（含跨列 colspan，
  多行单元格已由引擎合并），数量对不上时按块内文本行坐标几何重建行/列；
- 输出 Markdown 管道表格 / 结构化 JSON / CSV（utf-8-sig，Excel 直开）/ HTML。

输入端口 `document`（any）支持 PDF 与常见图片（jpg/png/bmp/tiff/webp/gif）：
本地路径（绝对/相对）、http(s) URL（自动下载）、data URI / 整段 base64（落盘）。
输出类型由节点面板 `output_type` 决定，端口类型随前端 getVisibleOutputs 联动。
"""
import base64
import binascii
import csv
import gc
import html as html_mod
import json
import os
import re
import statistics
import time
import urllib.request
from html.parser import HTMLParser
from typing import Callable, Dict, List, Optional, Tuple

from backend.steps.base_step import BaseStep, find_artifact
from backend.steps.s_pdf_ocr import (
    _count_pdf_pages,
    _load_indra_engine,
    _log,
    _parse_page_range,
    _resolve_model_dir,
    _unwrap_input,
)

_PDF_MAGIC = b"%PDF"
_INSTALL_HINT = "未安装 indra-ocr，请先执行：pip install indra-ocr"

# output_type → (文件扩展名, 说明)
OUTPUT_EXTS = {
    "markdown": ".md",
    "json": ".json",
    "csv": ".csv",
    "html": ".html",
}

# indra 版面模型输出的「网格类」块标签（Table 恒选，Form / Table-Of-Contents 可选）
GRID_LABELS = ("Table", "Form", "Table-Of-Contents")

# 常见图片文件头（长度递减匹配）
_IMG_MAGICS = (
    b"\x89PNG\r\n\x1a\n",   # PNG
    b"\xff\xd8\xff",        # JPEG
    b"GIF87a",              # GIF
    b"GIF89a",              # GIF
    b"II*\x00",             # TIFF (little-endian)
    b"MM\x00*",             # TIFF (big-endian)
    b"BM",                  # BMP
    b"RIFF",                # WEBP（需再校验 WEBP 标记）
)
_TABLE_RE = re.compile(r"(?is)<table>.*?</table>")


def _ensure_document(path: str, where: str = "输入") -> None:
    """校验本地文件是 PDF 或受支持的图片（indra_ocr.convert 两者均可处理）。"""
    try:
        with open(path, "rb") as fp:
            head = fp.read(1024)
    except OSError as e:
        raise ValueError(f"无法读取{where}文件 {path}: {e}")
    if head.lstrip().startswith(_PDF_MAGIC):
        return
    if _looks_like_image(head):
        return
    raise ValueError(
        f"不是受支持的文档（既非 PDF 也非图片）：{path}"
        "（支持 PDF / jpg / png / bmp / tiff / webp / gif）")


def _looks_like_image(head: bytes) -> bool:
    for magic in _IMG_MAGICS:
        if head.startswith(magic):
            if magic == b"RIFF":
                return b"WEBP" in head[:16]
            return True
    return False


def _is_abs(path: str) -> bool:
    return path.startswith(("/", "\\")) or (len(path) > 1 and path[1] == ":")


def _doc_ext(data: bytes) -> str:
    if data.lstrip().startswith(_PDF_MAGIC):
        return ".pdf"
    if data.startswith(b"\x89PNG"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data.startswith(b"BM"):
        return ".bmp"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return ".tiff"
    if data.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return ".webp"
    return ".bin"


def _write_b64_document(payload: str, task_dir: str, node_id: str) -> str:
    try:
        data = base64.b64decode(payload.strip(), validate=False)
    except (binascii.Error, ValueError) as e:
        raise ValueError(f"base64 解码失败：{e}")
    _ensure_document_bytes(data)
    dst = os.path.join(task_dir, "input")
    os.makedirs(dst, exist_ok=True)
    path = os.path.join(dst, f"{node_id}_input{_doc_ext(data)}")
    with open(path, "wb") as fp:
        fp.write(data)
    return os.path.abspath(path)


def _ensure_document_bytes(data: bytes) -> None:
    if data.startswith(_PDF_MAGIC) or _looks_like_image(data):
        return
    raise ValueError("base64 内容不是受支持的文档（既非 PDF 也非图片）")


def _download_document(url: str, task_dir: str, node_id: str, timeout: int = 180) -> str:
    dst = os.path.join(task_dir, "input")
    os.makedirs(dst, exist_ok=True)
    tmp = os.path.join(dst, f"{node_id}_input.bin")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 VideoLingoLc/OCR-Table"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp, "wb") as fp:
        fp.write(resp.read())
    with open(tmp, "rb") as fp:
        head = fp.read(1024)
    if not (head.lstrip().startswith(_PDF_MAGIC) or _looks_like_image(head)):
        os.remove(tmp)
        raise ValueError(f"下载的内容不是受支持的文档（既非 PDF 也非图片）：{url}")
    path = os.path.join(dst, f"{node_id}_input{_doc_ext(head)}")
    os.replace(tmp, path)
    return os.path.abspath(path)


def _resolve_document_path(raw, task_dir: str, node_id: str, log) -> str:
    """把输入值解析为本地 PDF/图片绝对路径（支持路径/URL/data URI/base64）。"""
    text = _unwrap_input(raw)
    if text.lower().startswith("data:"):
        header, _, payload = text.partition(",")
        if "base64" not in header.lower():
            raise ValueError("仅支持 base64 编码的 data URI（PDF/图片）")
        return _write_b64_document(payload, task_dir, node_id)
    if text.lower().startswith(("http://", "https://")):
        _log(log, f"下载文档: {text}")
        return _download_document(text, task_dir, node_id)

    candidates = [text] if _is_abs(text) else [os.path.join(task_dir, text), text]
    for cand in candidates:
        if os.path.isfile(cand):
            _ensure_document(cand)
            return os.path.abspath(cand)
    # 整段 base64 兜底（"%PDF" 的 base64 前缀为 "JVBER"，PNG 为 "iVBOR"）
    if text.startswith(("JVBER", "iVBOR")):
        return _write_b64_document(text, task_dir, node_id)
    raise FileNotFoundError(f"文档文件不存在：{text}（已尝试：{candidates}）")


# ── 表格提取 ─────────────────────────────────────────────────────

def _norm_space(text: str) -> str:
    return " ".join((text or "").split())


class _TableHTMLParser(HTMLParser):
    """把 indra 的 <table> HTML 解析成行/单元格（支持 colspan）。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: List[List[Dict]] = []
        self._row: Optional[List[Dict]] = None
        self._cell: Optional[Dict] = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            colspan = 1
            for k, v in attrs:
                if k.lower() == "colspan":
                    try:
                        colspan = max(1, int(v))
                    except (TypeError, ValueError):
                        colspan = 1
            self._cell = {"text": "", "colspan": colspan, "header": tag == "th"}
        elif tag == "br" and self._cell is not None:
            self._cell["text"] += " "

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("td", "th"):
            if self._cell is not None and self._row is not None:
                self._row.append(self._cell)
            self._cell = None
        elif tag == "tr":
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell["text"] += data


def _extract_html_tables(markdown: str) -> List[Tuple[Optional[str], str]]:
    """从页面 Markdown 提取 [(title, html), ...]。

    引擎把「首行大跨度」的 Table 块渲染为：标题文本 + HTML <table>，
    标题留在 <table> 之前，这里取表格前最后一条短文本作为标题找回它。
    """
    if not markdown:
        return []
    tables: List[Tuple[Optional[str], str]] = []
    last_end = 0
    for m in _TABLE_RE.finditer(markdown):
        pre = markdown[last_end:m.start()]
        last_end = m.end()
        title = None
        lines = [ln.strip() for ln in pre.splitlines() if ln.strip()]
        if lines:
            cand = lines[-1]
            if len(cand) <= 60 and cand[:1] not in ("#", "-", "*", ">", "<", "|", "["):
                title = cand
        tables.append((title, m.group(0)))
    return tables


def _parse_table_html(html: str) -> Optional[List[List[Dict]]]:
    parser = _TableHTMLParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return None
    if not parser.rows:
        return None
    return [[{"text": _norm_space(c["text"]), "colspan": c["colspan"], "header": c["header"]}
             for c in row] for row in parser.rows]


def _block_lines(page, bbox) -> list:
    """取块 bbox 内的文本行（按行中心内缩 1px，防邻块边缘侵入）。"""
    if not bbox or len(bbox) < 4:
        return []
    x0, y0, x1, y1 = (float(v) for v in bbox[:4])
    cx0, cy0, cx1, cy1 = x0 + 1, y0 + 1, x1 - 1, y1 - 1
    out = []
    for ln in (page.lines or []):
        box = getattr(ln, "box", None) or [0, 0, 0, 0]
        bx0, by0, bx1, by1 = (float(v) for v in box[:4])
        mx, my = (bx0 + bx1) / 2, (by0 + by1) / 2
        if cx0 <= mx <= cx1 and cy0 <= my <= cy1:
            out.append(ln)
    return out


def _rows_from_lines(lines) -> List[List[Dict]]:
    """几何重建：按 y 中心聚行（容差 0.6 倍行高），行内按 x 排序成单元格。"""
    if not lines:
        return []
    heights = [max(1.0, float(l.box[3]) - float(l.box[1])) for l in lines]
    tol = max(2.0, 0.6 * statistics.median(heights))
    clusters: List[List] = []  # [cy, [lines]]
    for ln in sorted(lines, key=lambda l: ((float(l.box[1]) + float(l.box[3])) / 2, float(l.box[0]))):
        cy = (float(ln.box[1]) + float(ln.box[3])) / 2
        if clusters and abs(cy - clusters[-1][0]) <= tol:
            n = len(clusters[-1][1])
            clusters[-1][0] = (clusters[-1][0] * n + cy) / (n + 1)
            clusters[-1][1].append(ln)
        else:
            clusters.append([cy, [ln]])
    rows = []
    for _, ls in clusters:
        ls.sort(key=lambda l: float(l.box[0]))
        rows.append([{"text": _norm_space(l.text), "colspan": 1, "header": False} for l in ls])
    return rows


def _page_tables(page, page_no: int, labels: set, min_rows: int, min_cols: int) -> List[Dict]:
    """从单页提取表格：HTML 优先，几何重建兜底；按最小行/列过滤误检。"""
    blocks = [b for b in (page.blocks or []) if (b.get("label") or "") in labels]
    if not blocks:
        return []
    # 只有 Table 标签的块会渲染 <table>；Form/ToC 走几何重建
    pure = [b for b in blocks if (b.get("label") or "") == "Table"]
    htmls = _extract_html_tables(page.markdown)
    html_map: Dict[int, Tuple[Optional[str], str]] = {}
    if len(htmls) == len(pure):
        for blk, th in zip(pure, htmls):
            html_map[id(blk)] = th

    tables: List[Dict] = []
    for idx, blk in enumerate(blocks, start=1):
        bbox = blk.get("bbox") or [0, 0, 0, 0]
        rows: Optional[List[List[Dict]]] = None
        title: Optional[str] = None
        paired = html_map.get(id(blk))
        if paired is not None:
            title, table_html = paired
            rows = _parse_table_html(table_html)
        if rows is None:
            rows = _rows_from_lines(_block_lines(page, bbox))
        if not rows:
            continue
        col_count = max((sum(int(c.get("colspan") or 1) for c in r) for r in rows), default=0)
        if len(rows) < min_rows or col_count < min_cols:
            continue
        tables.append({
            "page": page_no,
            "index": idx,
            "label": blk.get("label") or "Table",
            "title": title,
            "bbox": [round(float(v), 1) for v in bbox[:4]],
            "rows": rows,
            "row_count": len(rows),
            "col_count": col_count,
        })
    return tables


# ── 输出渲染 ─────────────────────────────────────────────────────

def _md_escape(text: str) -> str:
    return text.replace("|", "\\|")


def _row_cells(row: List[Dict]) -> List[str]:
    """展开 colspan：跨列单元格文本放首列，其余补空串。"""
    cells: List[str] = []
    for c in row:
        cells.append(_md_escape(_norm_space(c.get("text"))))
        cells.extend([""] * (int(c.get("colspan") or 1) - 1))
    return cells


def _md_table(rows: List[List[Dict]]) -> str:
    if not rows:
        return ""
    grid = [_row_cells(r) for r in rows]
    width = max(len(g) for g in grid)
    grid = [g + [""] * (width - len(g)) for g in grid]
    out = ["| " + " | ".join(grid[0]) + " |",
           "| " + " | ".join(["---"] * width) + " |"]
    out += ["| " + " | ".join(g) + " |" for g in grid[1:]]
    return "\n".join(out)


def _html_table(rows: List[List[Dict]]) -> str:
    out = ["<table>"]
    for r in rows:
        out.append("<tr>")
        for c in r:
            tag = "th" if c.get("header") else "td"
            span = int(c.get("colspan") or 1)
            attr = f' colspan="{span}"' if span > 1 else ""
            out.append(f"<{tag}{attr}>{html_mod.escape(_norm_space(c.get('text')))}</{tag}>")
        out.append("</tr>")
    out.append("</table>")
    return "\n".join(out)


def _csv_rows(rows: List[List[Dict]]) -> List[List[str]]:
    grid = [[_norm_space(c.get("text")) for c in _expand_row(r)] for r in rows]
    width = max((len(g) for g in grid), default=0)
    return [g + [""] * (width - len(g)) for g in grid]


def _expand_row(row: List[Dict]) -> List[Dict]:
    cells: List[Dict] = []
    for c in row:
        cells.append(c)
        cells.extend([{"text": "", "colspan": 1, "header": False}]
                     * (int(c.get("colspan") or 1) - 1))
    return cells


class S_OcrTable(BaseStep):
    """OCR 表格识别：直连 Indra OCR，从 PDF/图片提取表格，输出 MD/JSON/CSV/HTML。"""

    step_id = "s_ocr_table"
    step_name = "表格识别"
    dependencies = []
    artifacts = []

    INPUT_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp", ".gif"}
    OUTPUT_EXTS = OUTPUT_EXTS

    def check_artifact(self, task_dir: str) -> bool:
        """输出目录兜底扫描：任一受支持扩展名存在即视为有产物。"""
        out_dir = os.path.join(task_dir, "output", self._node_id)
        for ext in (".md", ".json", ".csv", ".html"):
            if find_artifact(out_dir, f"ocr_table{ext}"):
                return True
        return False

    def validate_inputs(self, **kwargs) -> bool:
        raw = (getattr(self, "_step_inputs", None) or {}).get("document")
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            raise ValueError("未提供文档输入：请连接 any 类型的上游端口（PDF/图片路径）")
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

        raw = (getattr(self, "_step_inputs", None) or {}).get("document")
        cfg = getattr(self, "_node_config", None) or {}
        node_id = getattr(self, "_node_id", None) or "node"

        # ── 1. 解析输入文档（PDF 或图片） ────────────────────────
        report(2, "解析文档输入")
        doc_path = _resolve_document_path(raw, task_dir, node_id, log)
        doc_name = os.path.basename(doc_path)
        _log(log, f"文档输入：{doc_path}")

        # ── 2. 识别参数 ─────────────────────────────────────────
        output_type = str(cfg.get("output_type") or "markdown").strip().lower()
        if output_type not in OUTPUT_EXTS:
            raise ValueError(f"output_type 不支持：{output_type}（可选：{'/'.join(OUTPUT_EXTS)}）")
        mode = str(cfg.get("mode") or "auto").strip().lower()
        if mode not in ("auto", "ocr", "text"):
            raise ValueError(f"mode 不支持：{mode}（可选：auto/ocr/text）")
        dpi = float(cfg.get("dpi") if cfg.get("dpi") is not None else 200)
        if not 36 <= dpi <= 1200:
            raise ValueError(f"dpi 超出范围（36~1200）：{dpi}")
        image_ocr = bool(cfg.get("image_ocr", True))
        furniture = bool(cfg.get("furniture", False))
        math = bool(cfg.get("math", False))
        use_cuda = bool(cfg.get("use_cuda", False))
        threads = int(cfg.get("threads") or 0)
        max_pages = int(cfg.get("max_pages") or 0)
        if max_pages < 0:
            raise ValueError(f"max_pages 不能为负：{max_pages}")
        password = str(cfg.get("pdf_password") or "") or None
        table_index = int(cfg.get("table_index") if cfg.get("table_index") is not None else 0)
        if table_index < 0:
            raise ValueError(f"table_index 不能为负：{table_index}（0=全部表格）")
        min_rows = int(cfg.get("min_rows") if cfg.get("min_rows") is not None else 2)
        min_cols = int(cfg.get("min_cols") if cfg.get("min_cols") is not None else 2)
        if min_rows < 1 or min_cols < 1:
            raise ValueError(f"min_rows/min_cols 需 ≥1（当前 {min_rows}/{min_cols}）")
        labels = {"Table"}
        if bool(cfg.get("include_form")):
            labels.add("Form")
        if bool(cfg.get("include_toc")):
            labels.add("Table-Of-Contents")

        # ── 3. 页码范围（先数页再解析范围；图片按单页处理） ──────
        total_pages = _count_pdf_pages(doc_path)
        range_spec = str(cfg.get("page_range") or "").strip()
        if not total_pages:
            # 页数仅用于范围校验与进度估算，未知时告警续跑（引擎仍可流式逐页处理）
            _log(log, f"[WARN] 无法读取文档页数（按流式处理，页码范围上限不可用）：{doc_path}")
            if range_spec:
                open_ended = any(
                    re.fullmatch(r"\d+[-~]", re.sub(r"\s+", "", part))
                    for part in re.split(r"[,，;；]+", range_spec) if part
                )
                if open_ended:
                    raise ValueError(
                        f"无法读取文档页数，开放式页码范围不可用：{range_spec}"
                        "（请改为明确页码，或更换文档）")
        wanted = _parse_page_range(cfg.get("page_range"), total_pages)
        if wanted is not None:
            _log(log, f"页码范围命中 {len(wanted)}/{total_pages or '?'} 页")
        scan_limit = max_pages or 0
        if wanted is not None and scan_limit:
            scan_limit = max(scan_limit, max(wanted))
        _log(log, f"识别参数：输出={output_type} 模式={mode} dpi={dpi:g} 页数={total_pages}"
                  f" 范围={'全部' if wanted is None else sorted(wanted)}"
                  f" 块标签={sorted(labels)} 最少 {min_rows}行/{min_cols}列"
                  f" 表格序号={table_index or '全部'}")

        # ── 4. 加载引擎（直连 indra_ocr） ────────────────────────
        report(5, "加载 Indra OCR 模型")
        model_dir = _resolve_model_dir(cfg.get("model_dir"))
        engine, resolved_model_dir = _load_indra_engine(
            model_dir, threads, dpi, mode, image_ocr, furniture, math, use_cuda)
        _log(log, f"Indra 引擎就绪：{resolved_model_dir}"
                  f"（providers={'cuda' if use_cuda else 'cpu'}）")

        # ── 5. 逐页提取表格 ─────────────────────────────────────
        tables: List[Dict] = []
        done = 0
        try:
            for page_no, page in engine.convert(doc_path, max_pages=scan_limit, password=password):
                if cancel_callback and cancel_callback():
                    raise RuntimeError("任务已被用户取消")
                if wanted is not None and page_no not in wanted:
                    continue
                if (getattr(page, "source", "") or "") == "error":
                    _log(log, f"[WARN] 第 {page_no} 页识别失败：{getattr(page, 'note', '') or '未知错误'}")
                    continue
                page_tables = _page_tables(page, page_no, labels, min_rows, min_cols)
                tables.extend(page_tables)
                done += 1
                denom = total_pages or scan_limit or done
                report(10 + int(80 * done / max(1, denom)),
                       f"扫描第 {page_no} 页" + (f"/{total_pages}" if total_pages else "")
                       + f"（累计 {len(tables)} 个表格）")
        finally:
            del engine
            gc.collect()

        if not tables:
            raise RuntimeError(
                "未识别到任何表格（可尝试：调大 dpi、mode 改为 ocr、"
                "放宽最小行/列数，或勾选包含表单 Form 块）")

        # no = 跨页连续序号（与 table_index 语义一致）；index 保留页内序号
        for no, t in enumerate(tables, start=1):
            t["no"] = no
        # table_index：0=全部；N=仅第 N 个表格（阅读顺序跨页连续编号）
        if table_index:
            if table_index > len(tables):
                raise RuntimeError(f"表格序号超出范围：{table_index}（共识别到 {len(tables)} 个表格）")
            tables = [tables[table_index - 1]]

        # ── 6. 组装输出 ────────────────────────────────────────
        report(92, "生成输出文件")
        md_parts = []
        for t in tables:
            comment = f"<!-- 表格 {t['no']} · 第 {t['page']} 页 -->"
            body = _md_table(t["rows"])
            if t.get("title"):
                body = f"**{t['title']}**\n\n{body}"
            md_parts.append(f"{comment}\n{body}")
        markdown_text = "\n\n".join(md_parts)

        ext = OUTPUT_EXTS[output_type]
        out_dir = os.path.join(task_dir, "output", node_id)
        os.makedirs(out_dir, exist_ok=True)
        output_path = os.path.join(out_dir, f"ocr_table{ext}")
        if output_type == "markdown":
            with open(output_path, "w", encoding="utf-8") as fp:
                fp.write(markdown_text)
        elif output_type == "html":
            with open(output_path, "w", encoding="utf-8") as fp:
                fp.write("\n\n".join(_html_table(t["rows"]) for t in tables))
        elif output_type == "csv":
            with open(output_path, "w", encoding="utf-8-sig", newline="") as fp:
                writer = csv.writer(fp)
                for i, t in enumerate(tables):
                    if i:
                        writer.writerow([])  # 多表格间空行分隔
                    writer.writerows(_csv_rows(t["rows"]))
        else:
            with open(output_path, "w", encoding="utf-8") as fp:
                json.dump({
                    "file": doc_name,
                    "page_count": total_pages,
                    "table_count": len(tables),
                    "mode": mode,
                    "dpi": dpi,
                    "min_rows": min_rows,
                    "min_cols": min_cols,
                    "elapsed_ms": int((time.time() - started) * 1000),
                    "tables": tables,
                }, fp, ensure_ascii=False, indent=2)

        rel = os.path.relpath(output_path, task_dir)
        self.artifacts = [rel]
        elapsed = time.time() - started
        _log(log, f"表格识别完成：{len(tables)} 个表格，输出 {output_path}（{elapsed:.1f}s）")
        report(100, f"完成（{len(tables)} 个表格 / {elapsed:.1f}s）")

        return {
            "outputs": {"result": output_path},
            "artifacts": [rel],
        }

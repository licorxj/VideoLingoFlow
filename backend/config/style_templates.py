"""风格模板（画风 / 视频风格）json 资产读写与提示词组装。

资产目录：``backend/config/style_presets/``

- ``art_styles.json``    画风风格模板（生图）
- ``video_styles.json``  视频风格模板（图生视频 / 文生视频）

模板结构参考 AI-Visual-Prompt-Cookbook（MIT）的 style.json v2.1 简化而来：
每个模板给出 ``prompt_template``（含 ``{变量槽}``）与 ``negative_prompt``，
变量槽由 ``common_variables``（文件级公共槽）+ 模板 ``variables``（覆盖 default/label）合并。

提示词优化用的 LLM 模板放在 ``backend/config/drama_prompts/``（MD + frontmatter），
本模块只负责把它们列出来供选择，正文渲染由 ``steps.s_agi_comic`` 的 ``_load_prompt`` 完成。
"""

import os
import re
import time
from typing import Optional

_DIR = os.path.dirname(os.path.abspath(__file__))
_STYLE_DIR = os.path.join(_DIR, "style_presets")
_PROMPT_DIR = os.path.join(_DIR, "drama_prompts")

_ART_FILE = "art_styles.json"
_VIDEO_FILE = "video_styles.json"

_KIND_FILES = {"art": _ART_FILE, "video": _VIDEO_FILE}

# 变量槽：{subject} / {shot_scale} ...
_VAR_RE = re.compile(r"\{(\w+)\}")
# 连续分隔符（中英文逗号）→ 单个中文逗号
_DUP_SEP_RE = re.compile(r"[，,]\s*(?:[，,]\s*)+")

_CACHE: dict = {}


def _read_json(path: str) -> dict:
    import json
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_kind(kind: str) -> dict:
    """按 kind 载入资产（按文件 mtime 缓存，改文件即生效）。"""
    filename = _KIND_FILES.get(kind)
    if not filename:
        return {}
    path = os.path.join(_STYLE_DIR, filename)
    if not os.path.isfile(path):
        return {}
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0.0
    hit = _CACHE.get(kind)
    if hit and hit.get("mtime") == mtime:
        return hit.get("data") or {}
    try:
        data = _read_json(path)
    except Exception:  # noqa: BLE001
        return hit.get("data") if hit else {}
    _CACHE[kind] = {"mtime": mtime, "data": data}
    return data


def kind_label(kind: str) -> str:
    return "画风" if kind == "art" else "视频风格"


def _merged_variables(doc: dict, tpl: dict) -> list:
    """公共变量 + 模板覆盖（按 key 合并，模板优先）。"""
    merged: dict = {}
    for v in (doc.get("common_variables") or []):
        if isinstance(v, dict) and v.get("key"):
            merged[v["key"]] = dict(v)
    for v in (tpl.get("variables") or []):
        if isinstance(v, dict) and v.get("key"):
            merged.setdefault(v["key"], {})
            merged[v["key"]].update(v)
    # 只保留模板正文里真正出现的槽 + 模板显式声明的槽，避免表单里出现无用项
    slots = set(_VAR_RE.findall(tpl.get("prompt_template") or "")) | set(merged.keys())
    out = []
    for key in slots:
        item = merged.get(key) or {"key": key}
        item.setdefault("label", key)
        item.setdefault("required", key == "subject")
        item.setdefault("default", "")
        out.append(item)
    out.sort(key=lambda x: (not x.get("required"), x.get("key") or ""))
    return out


def _public(tpl: dict, doc: dict) -> dict:
    """模板概要（列表用，不含变量表，减小响应体积）。"""
    return {
        "id": tpl.get("id") or "",
        "name": tpl.get("name") or "",
        "slug": tpl.get("slug") or "",
        "category": tpl.get("category") or "",
        "lang": tpl.get("lang") or "zh",
        "source": tpl.get("source") or "",
        "tags": tpl.get("tags") or [],
        "summary": tpl.get("summary") or "",
        "preview": tpl.get("preview") or "",
        "negative_prompt": tpl.get("negative_prompt") or "",
    }


def list_templates(kind: str, category: str = "", keyword: str = "") -> dict:
    """模板列表：可按分类/关键词（名称/摘要/标签）过滤。"""
    doc = _load_kind(kind)
    tpls = doc.get("templates") or []
    kw = (keyword or "").strip().lower()
    items = []
    for t in tpls:
        if category and (t.get("category") or "") != category:
            continue
        if kw:
            hay = " ".join([t.get("name") or "", t.get("slug") or "", t.get("summary") or "",
                            " ".join(t.get("tags") or [])]).lower()
            if kw not in hay:
                continue
        items.append(_public(t, doc))
    categories = sorted({t.get("category") or "" for t in tpls if t.get("category")})
    return {
        "kind": kind,
        "kind_label": kind_label(kind),
        "version": doc.get("version") or 1,
        "sources": doc.get("sources") or [],
        "categories": categories,
        "total": len(items),
        "templates": items,
    }


def get_template(kind: str, template_id: str) -> Optional[dict]:
    """模板详情（含变量表），供前端渲染填槽表单。"""
    doc = _load_kind(kind)
    for t in doc.get("templates") or []:
        if (t.get("id") or "") == template_id or (t.get("slug") or "") == template_id:
            return {
                **_public(t, doc),
                "prompt_template": t.get("prompt_template") or "",
                "variables": _merged_variables(doc, t),
                "fidelity_anchors": t.get("fidelity_anchors") or [],
                "avoid": t.get("avoid") or [],
            }
    return None


def _clean(text: str) -> str:
    """清理空槽留下的多余分隔符与空白。"""
    t = text or ""
    for _ in range(3):
        t = _DUP_SEP_RE.sub("，", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    # 去掉行首/行尾的孤立分隔符与空白
    lines = []
    for line in t.split("\n"):
        s = line.strip().strip("，,、；; ").strip()
        if s:
            lines.append(s)
    return "\n".join(lines).strip()


def render(kind: str, template_id: str, values: dict = None,
           style_prefix: str = "", extra_suffix: str = "") -> dict:
    """按模板 + 变量值渲染最终提示词。

    - 未提供值的槽：先用模板 default，再留空（渲染后清理多余分隔符）
    - ``style_prefix``：项目统一画风前缀（全链路画风锁定），拼在最前
    - ``extra_suffix``：追加在末尾的自由文本
    返回 ``{prompt, negative_prompt, missing, variables}``
    """
    tpl = get_template(kind, template_id)
    values = values or {}
    if not tpl:
        raise KeyError(f"风格模板不存在：kind={kind} id={template_id}")

    mapping: dict = {}
    missing: list = []
    for v in tpl.get("variables") or []:
        key = v.get("key")
        if not key:
            continue
        raw = values.get(key)
        if raw is None or str(raw).strip() == "":
            raw = v.get("default") or ""
        raw = str(raw).strip()
        if not raw and v.get("required"):
            missing.append(key)
        mapping[key] = raw

    body = tpl.get("prompt_template") or ""
    try:
        body = body.format(**{k: mapping.get(k, "") for k in set(_VAR_RE.findall(body))})
    except Exception:  # noqa: BLE001  # 模板花括号异常时原样保留
        pass
    # 模板未声明 subject 槽（纯后缀型模板）时把主体补到末尾
    if "{subject}" not in (tpl.get("prompt_template") or "") and mapping.get("subject"):
        body = f"{body} {mapping['subject']}".strip()

    parts = [p for p in (style_prefix.strip(), _clean(body), (extra_suffix or "").strip()) if p]
    return {
        "prompt": "，".join(parts) if style_prefix.strip() and len(parts) > 1 else "".join(parts),
        "negative_prompt": tpl.get("negative_prompt") or "",
        "missing": missing,
        "template": {"id": tpl.get("id"), "name": tpl.get("name"), "kind": kind},
    }


# --------------------------------------------------------------------------- #
# 提示词优化用的 LLM 模板（drama_prompts/*.md）
# --------------------------------------------------------------------------- #
_OPTIMIZE_FILES = {
    "image": "image_prompt_optimize.md",
    "video": "video_prompt_optimize.md",
}


def list_optimize_templates(kind: str = "") -> list:
    """列出可选的提示词优化 LLM 模板（读 MD 的 frontmatter 元信息）。"""
    out = []
    for k, filename in _OPTIMIZE_FILES.items():
        if kind and k != kind:
            continue
        path = os.path.join(_PROMPT_DIR, filename)
        if not os.path.isfile(path):
            continue
        meta = _read_frontmatter(path)
        out.append({
            "key": k,
            "file": filename,
            "name": meta.get("name") or filename,
            "description": meta.get("description") or "",
            "node": meta.get("node") or "",
            "target_lang": meta.get("target_lang") or "zh",
            "max_chars": meta.get("max_chars") or "",
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S",
                                        time.localtime(os.path.getmtime(path))),
        })
    return out


def _read_frontmatter(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read().lstrip()
    except Exception:  # noqa: BLE001
        return {}
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        import yaml
        meta = yaml.safe_load(parts[1]) or {}
    except Exception:  # noqa: BLE001
        return {}
    return meta if isinstance(meta, dict) else {}


def optimize_template_path(kind: str) -> str:
    """优化模板的绝对路径（不存在返回空串）。"""
    filename = _OPTIMIZE_FILES.get(kind)
    if not filename:
        return ""
    path = os.path.join(_PROMPT_DIR, filename)
    return path if os.path.isfile(path) else ""


def load_optimize_system_prompt(kind: str) -> str:
    """读取优化模板正文（剥离 frontmatter）；缺失返回空串（调用方回退内置提示）。"""
    path = optimize_template_path(kind)
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read().strip()
    except Exception:  # noqa: BLE001
        return ""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[2].strip()
    return text


def optimize_step_name(kind: str) -> str:
    """优化请求使用的 step_name（与 drama_prompts 映射、节点 id 一致，供 LLM 路由按步选模）。"""
    return "prompt_opt_video" if kind == "video" else "prompt_opt_image"

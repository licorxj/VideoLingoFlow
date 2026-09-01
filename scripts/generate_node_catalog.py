#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 VideoLingo 节点目录（Node Catalog）Markdown 文档。

数据来源与「前端节点管理器」调用后端获取节点信息的接口保持一致：
- 默认直接读取后端内置节点与自定义节点定义（与 `GET /api/node-types` 返回内容一致，
  无需启动服务 / 鉴权，最适合本地快捷生成）；
- 若设置了环境变量 VL_BACKEND_URL（以及可选的 VL_API_TOKEN），则改为调用
  `GET {VL_BACKEND_URL}/api/node-types` 实时拉取（与线上节点管理器同一接口）。

生成的文档保存为仓库根目录 `docs/node_catalog.md`，并返回其绝对路径。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ----------------------------------------------------------------------------
# 分组标签（与 frontend/src/lib/workflowTypes.ts 的 CATEGORIES 保持一致）
# ----------------------------------------------------------------------------
CATEGORY_LABELS: Dict[str, str] = {
    "io": "输入输出节点",
    "preview": "预览节点",
    "audio": "音频处理节点",
    "video": "视频处理节点",
    "ai_gen": "AI生成类节点",
    "translation": "翻译相关节点",
    "flow_control": "流程控制节点",
    "network_request": "网络请求类节点",
    "aigc": "AIGC流程链",
    "agent": "智能体",
    "utility": "工具类节点",
    "file": "文件操作类节点",
    "group_node": "组合节点",
    "input": "输入节点",
    "process": "处理节点",
    "ai": "AI 节点",
    "output": "输出节点",
    "publish": "发布节点",
}

# 期望的分组展示顺序（其余分组按字母序追加在后）
CATEGORY_ORDER: List[str] = [
    "io", "input", "output", "preview", "audio", "video",
    "ai_gen", "ai", "translation", "aigc", "agent",
    "flow_control", "network_request", "utility", "file",
    "group_node", "process", "publish",
]


# ----------------------------------------------------------------------------
# 数据获取
# ----------------------------------------------------------------------------
def _load_via_backend_modules(backend_dir: Path) -> List[Dict[str, Any]]:
    """直接读取后端模块（与 /api/node-types 同源，最可靠）。"""
    # backend 是项目根目录下的包，需把「项目根目录」加入 sys.path
    root_dir = backend_dir.parent
    if str(root_dir) not in sys.path:
        sys.path.insert(0, str(root_dir))

    from backend.config.builtin_node_types import get_builtin_node_types  # noqa: E402

    nodes: List[Dict[str, Any]] = []
    for node in get_builtin_node_types():
        item = dict(node)
        item["isBuiltIn"] = True
        nodes.append(item)

    # 自定义节点（与 backend/api/node_types.py :: _load_all_nodes 逻辑一致）
    node_types_dir = backend_dir / "config" / "node_types"
    if node_types_dir.exists():
        for f in sorted(node_types_dir.glob("*.json")):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                data["isBuiltIn"] = False
                nodes.append(data)
            except Exception:
                continue
    return nodes


def _load_via_api(base_url: str, token: Optional[str] = None) -> List[Dict[str, Any]]:
    """调用后端 `/api/node-types` 接口拉取节点信息（与前端节点管理器同一接口）。"""
    import urllib.request

    url = f"{base_url.rstrip('/')}/api/node-types"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    # 接口返回 {"nodes": [...]}
    return payload.get("nodes", [])


def fetch_nodes(root: Path) -> List[Dict[str, Any]]:
    backend_dir = root / "backend"
    api_url = os.environ.get("VL_BACKEND_URL")
    api_token = os.environ.get("VL_API_TOKEN")
    if api_url:
        print(f"[info] 通过后端接口拉取节点: {api_url}/api/node-types")
        return _load_via_api(api_url, api_token)
    if not backend_dir.exists():
        raise RuntimeError(f"未找到后端目录: {backend_dir}")
    print("[info] 直接读取后端节点定义（内置 + 自定义）")
    return _load_via_backend_modules(backend_dir)


# ----------------------------------------------------------------------------
# 渲染辅助
# ----------------------------------------------------------------------------
def _norm_ports(ports: Any) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    if not isinstance(ports, list):
        return result
    for p in ports:
        if not isinstance(p, dict):
            continue
        result.append({
            "id": p.get("id", ""),
            "label": p.get("label", p.get("id", "")),
            "type": p.get("type", ""),
            "required": p.get("required", False),
            "description": p.get("description", ""),
        })
    return result


def _ports_inline(ports: List[Dict[str, Any]]) -> str:
    """将端口列表压缩为一行可读文本，例如：名称(`id`:type); ..."""
    if not ports:
        return "—"
    cells = []
    for p in ports:
        req = "*" if p.get("required") else ""
        label = p["label"].replace("|", "\\|") if p["label"] else "—"
        cells.append(f"{label}(`{p['id']}`{req}:{p['type']})")
    return "; ".join(cells)


def _sort_categories(cats: List[str]) -> List[str]:
    ordered = [c for c in CATEGORY_ORDER if c in cats]
    rest = sorted(c for c in cats if c not in CATEGORY_ORDER)
    return ordered + rest


# ----------------------------------------------------------------------------
# 渲染主流程：每个分组一张表格
# ----------------------------------------------------------------------------
def render_markdown(nodes: List[Dict[str, Any]]) -> str:
    by_category: Dict[str, List[Dict[str, Any]]] = {}
    for node in nodes:
        cat = node.get("category") or "utility"
        by_category.setdefault(cat, []).append(node)

    # 总览统计
    overview_rows = []
    for cat in _sort_categories(list(by_category.keys())):
        label = CATEGORY_LABELS.get(cat, cat)
        overview_rows.append(f"| {label}（`{cat}`） | {len(by_category[cat])} |")

    parts: List[str] = []
    parts.append("# VideoLingo 节点目录（Node Catalog）")
    parts.append("")
    parts.append(f"> 自动生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ")
    parts.append(f"> 节点总数：{len(nodes)}　（带 `*` 的接口为必填项）")
    parts.append("")
    parts.append("## 总览")
    parts.append("")
    parts.append("| 分组 | 节点数 |")
    parts.append("|------|-------|")
    parts.extend(overview_rows)
    parts.append("")

    parts.append("## 节点详情")
    parts.append("")
    for cat in _sort_categories(list(by_category.keys())):
        label = CATEGORY_LABELS.get(cat, cat)
        parts.append(f"### {label}（`{cat}`）")
        parts.append("")
        parts.append("| 节点 | ID | 描述 | 执行域 | 输入接口 | 输出接口 |")
        parts.append("|------|----|------|-------|---------|---------|")
        # 组内按 name 排序，稳定可读
        for node in sorted(by_category[cat], key=lambda n: (n.get("name") or n.get("id") or "")):
            nid = node.get("id", "")
            name = node.get("name", nid)
            desc = (node.get("description") or "（暂无描述）").strip().replace("\n", " ")
            domain = node.get("execution_domain", "") or "—"
            inputs = _ports_inline(_norm_ports(node.get("inputs")))
            outputs = _ports_inline(_norm_ports(node.get("outputs")))
            parts.append(
                f"| {name} | `{nid}` | {desc} | {domain} | {inputs} | {outputs} |"
            )
        parts.append("")

    return "\n".join(parts)


# ----------------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------------
def generate_node_catalog(root: Optional[Path] = None) -> str:
    """生成节点目录 MD 文件，返回其绝对路径。"""
    root = (root or Path(__file__).resolve().parent.parent).resolve()
    nodes = fetch_nodes(root)
    md = render_markdown(nodes)

    docs_dir = root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    out_path = docs_dir / "node_catalog.md"
    out_path.write_text(md, encoding="utf-8")
    return str(out_path)


if __name__ == "__main__":
    path = generate_node_catalog()
    print(f"[ok] 节点目录已生成：{path}")

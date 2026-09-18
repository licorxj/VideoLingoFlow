#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成前端兜底节点注册表：frontend/src/lib/fallbackNodeTypes.ts

背景
----
前端 `getAllNodeTypes()` 的合并顺序是「FALLBACK_NODE_TYPES 打底 → 运行时 API 定义覆盖」，
正常情况下使用 `GET /api/node-types` 返回的实时定义。但后端不可用时会退回 fallback，
如果 fallback 与后端脱节，用户会看到缺失的节点与过时的配置项。

本脚本让 fallback 始终可从后端源码一键重建，避免手工同步漂移。

数据源
------
- backend/config/builtin_node_types.py（内置节点）
- backend/config/node_types/*.json（自定义节点）
（刻意只读本地源码，不使用 VL_BACKEND_URL，以保证 fallback 与仓库版本一致）

用法
----
    python scripts/generate_fallback_node_types.py            # 重新生成
    python scripts/generate_fallback_node_types.py --check    # 仅校验是否为最新（CI 用）

退出码：--check 下不一致返回 1，一致返回 0；生成模式恒为 0（除非加载失败）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

try:  # Windows 控制台默认 GBK，避免中文输出报 UnicodeEncodeError
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ----------------------------------------------------------------------------
# 字段白名单：与 frontend/src/lib/workflowTypes.ts 的 NodeTypeDef 保持一致。
# 用来剔除后端节点上的运行态/内部字段，保证 fallback 文件干净稳定。
# ----------------------------------------------------------------------------
ALLOWED_KEYS = (
    "id", "name", "category", "description", "icon", "color",
    "execution_domain", "dynamicPorts", "inputs", "outputs",
    "defaultConfig", "configFields", "dynamicConfigEndpoint",
    "isBuiltIn", "kind", "groupDefinition",
)

# ----------------------------------------------------------------------------
# 前端 TS 类型白名单（摘自 workflowTypes.ts），仅用于生成时打印「类型漂移」告警。
# 后端定义里的历史取值若不在其中，不会阻断生成（fallback 需逐字复刻后端），
# 但会被汇总提示，便于决定是补前端类型还是收敛后端定义。
# 若前端新增了类型，请同步这里（漏同步只会少报几条告警，不影响生成结果）。
# ----------------------------------------------------------------------------
TS_PORT_TYPES = {
    "video", "audio", "audio_manifest", "json", "pandas", "subtitle",
    "text", "image", "list", "url", "filepath", "any",
}
TS_CONFIG_FIELD_TYPES = {
    "text", "textarea", "select", "multiselect", "checkbox", "toggle", "chips",
    "file", "hotwords", "language-select", "api-select", "voice-select", "slider",
    "number", "datetime-local", "account-select", "audio-selector",
    "voice-target-list", "reorder-list", "date", "time", "button", "wf-io-mapping",
}
TS_CONFIG_FIELD_KEYS = {
    "key", "label", "type", "placeholder", "options", "dependsOn", "dependsValue",
    "dependsOnAny", "dependsAnyValues", "chipColor", "singleSelect", "link", "action",
    "url", "fileFilter", "apiEndpoint", "apiUrl", "followPort", "interfaceIdKey",
    "optionLabel", "optionValue", "description", "hint", "defaultValue",
    "min", "max", "step", "inline", "colSpan", "chips",
}
TS_KINDS = {"normal", "group", "loop"}
TS_CATEGORIES = {
    "io", "preview", "audio", "asset", "video", "cutia", "ai_gen", "music_gen",
    "translation", "flow_control", "network_request", "aigc", "agi_story",
    "agi_asset", "agi_shot", "agi_render", "agi_data", "agent", "utility", "file",
    "group_node", "hyperframes", "input", "ai", "output", "publish",
}

HEADER = """import type { NodeTypeDef } from './workflowTypes';

// 本文件由 scripts/generate_fallback_node_types.py 自动生成，请勿手工编辑。
// 数据源：backend/config/builtin_node_types.py（内置）+ backend/config/node_types/*.json（自定义）
// 用途：后端节点注册表（GET /api/node-types）不可用时的兜底；正常情况下会被运行时定义覆盖。
// 重新生成：python scripts/generate_fallback_node_types.py
//
// 关于结尾的 `as unknown as NodeTypeDef[]`：本文件逐字复刻后端定义，其中含个别不在前端
// TS 白名单内的历史取值（例如 configField.type="switch"、port.type="number"）。
// 若直接标注 NodeTypeDef[]，会因多余属性/联合类型检查导致前端无法编译；
// 而运行时 API 返回的定义同样含这些取值且前端可正常容错，故此处刻意不做类型收窄。
// 类型漂移由生成脚本运行时打印告警（见 scan_drift）。
export const FALLBACK_NODE_TYPES = [
"""

FOOTER = """] as unknown as NodeTypeDef[];

export const BUILTIN_NODE_TYPES = FALLBACK_NODE_TYPES;
"""


def load_nodes(root: Path) -> List[Dict[str, Any]]:
    """读取后端节点定义（内置 + 自定义），与 GET /api/node-types 同源。"""
    backend_dir = root / "backend"
    if not backend_dir.exists():
        raise RuntimeError(f"未找到后端目录: {backend_dir}")

    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from backend.config.builtin_node_types import get_builtin_node_types  # noqa: E402

    nodes: List[Dict[str, Any]] = []
    for node in get_builtin_node_types():
        item = dict(node)
        item["isBuiltIn"] = True
        nodes.append(item)

    node_types_dir = backend_dir / "config" / "node_types"
    if node_types_dir.exists():
        for f in sorted(node_types_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception as e:  # 单个自定义节点损坏不应中断整体生成
                print(f"[warn] 跳过无法解析的自定义节点 {f.name}: {e}", file=sys.stderr)
                continue
            data["isBuiltIn"] = False
            nodes.append(data)
    return nodes


def sanitize(node: Dict[str, Any]) -> Dict[str, Any]:
    """按 NodeTypeDef 字段白名单裁剪节点，剔除运行态/内部字段。"""
    return {key: node[key] for key in ALLOWED_KEYS if key in node}


def scan_drift(nodes: List[Dict[str, Any]]) -> Dict[str, Dict[str, List[str]]]:
    """扫描后端定义中不在前端 TS 白名单内的取值，返回 {维度: {取值: [节点示例]}}。"""
    issues: Dict[str, Dict[str, List[str]]] = {}

    def note(dim: str, value: Any, where: str) -> None:
        issues.setdefault(dim, {}).setdefault(str(value), [])
        if len(issues[dim][str(value)]) < 3:
            issues[dim][str(value)].append(where)

    for node in nodes:
        nid = str(node.get("id", "<unknown>"))

        category = node.get("category")
        if category and category not in TS_CATEGORIES:
            note("category", category, nid)

        kind = node.get("kind")
        if kind and kind not in TS_KINDS:
            note("kind", kind, nid)

        ports = list(node.get("inputs") or []) + list(node.get("outputs") or [])
        for port in ports:
            if not isinstance(port, dict):
                continue
            ptype = port.get("type")
            if ptype and ptype not in TS_PORT_TYPES:
                note("port.type", ptype, f"{nid}.{port.get('id')}")

        for field in node.get("configFields") or []:
            if not isinstance(field, dict):
                continue
            where = f"{nid}.{field.get('key')}"
            ftype = field.get("type")
            if ftype and ftype not in TS_CONFIG_FIELD_TYPES:
                note("configField.type", ftype, where)
            for fkey in field:
                if fkey not in TS_CONFIG_FIELD_KEYS:
                    note("configField.<key>", fkey, where)

    return issues


def report_drift(issues: Dict[str, Dict[str, List[str]]]) -> None:
    """打印类型漂移告警（仅提示，不影响生成结果）。"""
    if not issues:
        return
    print("[warn] 后端节点定义含不在前端 TS 白名单内的取值（不影响生成，仅供排查）：", file=sys.stderr)
    for dim in sorted(issues):
        for value, examples in sorted(issues[dim].items()):
            shown = ", ".join(examples)
            more = "" if len(examples) < 3 else " ..."
            print(f"  - {dim} = {value!r}（如 {shown}{more}）", file=sys.stderr)


def render(nodes: List[Dict[str, Any]]) -> str:
    """渲染 TS 文件内容：每个节点按 JSON 缩进 2 空格，整体再缩进 2 空格。"""
    blocks: List[str] = []
    for node in nodes:
        body = json.dumps(node, ensure_ascii=False, indent=2)
        blocks.append("\n".join("  " + line for line in body.splitlines()))
    return HEADER + ",\n".join(blocks) + "\n" + FOOTER


def build(root: Path) -> str:
    """加载后端定义并渲染为文件内容。"""
    nodes = load_nodes(root)
    report_drift(scan_drift(nodes))
    return render([sanitize(n) for n in nodes])


def generate(root: Path | None = None) -> str:
    """重新生成 fallbackNodeTypes.ts，返回其绝对路径。"""
    root = (root or Path(__file__).resolve().parent.parent).resolve()
    content = build(root)
    out_path = root / "frontend" / "src" / "lib" / "fallbackNodeTypes.ts"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n"：避免 Windows 下被转成 CRLF，导致 diff 变成整文件重写
    with out_path.open("w", encoding="utf-8", newline="\n") as fp:
        fp.write(content)
    print(f"[ok] 已生成兜底节点注册表：{out_path}")
    return str(out_path)


def check(root: Path | None = None) -> int:
    """校验现有文件是否与后端定义一致，返回进程退出码。"""
    root = (root or Path(__file__).resolve().parent.parent).resolve()
    out_path = root / "frontend" / "src" / "lib" / "fallbackNodeTypes.ts"
    expected = build(root)
    current = out_path.read_text(encoding="utf-8") if out_path.exists() else ""
    if current != expected:
        print(
            "[fail] fallbackNodeTypes.ts 与后端节点定义不一致，"
            "请运行：python scripts/generate_fallback_node_types.py",
            file=sys.stderr,
        )
        return 1
    print("[ok] fallbackNodeTypes.ts 已是最新")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="生成/校验前端兜底节点注册表 fallbackNodeTypes.ts")
    parser.add_argument("--check", action="store_true", help="仅校验是否为最新，不写入文件")
    args = parser.parse_args()
    if args.check:
        return check()
    generate()
    return 0


if __name__ == "__main__":
    sys.exit(main())

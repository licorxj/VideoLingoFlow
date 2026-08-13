from __future__ import annotations

import json
from pathlib import Path

from backend.config.builtin_node_types import get_builtin_node_type


NODE_TYPES_DIR = Path(__file__).parent / "config" / "node_types"
LEGACY_HANDLE_MIGRATIONS = {
    ("asr", "target", "audio"): "asr_audio",
    ("asr", "source", "asr_result"): "subtitle",
}


def _node_type(node: dict) -> str:
    return str((node.get("data") or {}).get("nodeType") or "")


def _node_definition(node_type: str) -> dict | None:
    builtin = get_builtin_node_type(node_type)
    if builtin is not None:
        return builtin
    path = NODE_TYPES_DIR / f"{node_type}.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _port_map(node_type: str, direction: str) -> dict[str, str]:
    definition = _node_definition(node_type)
    if definition is None:
        return {}
    key = "outputs" if direction == "source" else "inputs"
    return {
        str(port.get("id")): str(port.get("type"))
        for port in definition.get(key, [])
        if isinstance(port, dict) and port.get("id") and port.get("type")
    }


def _handle_port_id(handle: object, prefix: str) -> str | None:
    if not isinstance(handle, str) or not handle.startswith(prefix):
        return None
    port_id = handle[len(prefix):]
    return port_id or None


def _can_connect(source_type: str, target_type: str) -> bool:
    return source_type == "any" or target_type == "any" or source_type == target_type


def normalize_workflow_edges(nodes: list[dict], edges: list[dict]) -> tuple[list[dict], int, int]:
    node_types = {
        str(node.get("id")): _node_type(node)
        for node in nodes
        if isinstance(node, dict) and node.get("id")
    }
    normalized: list[dict] = []
    migrated = 0
    removed = 0
    for edge in edges:
        if not isinstance(edge, dict):
            removed += 1
            continue
        source_id = str(edge.get("source") or "")
        target_id = str(edge.get("target") or "")
        source_type = node_types.get(source_id)
        target_type = node_types.get(target_id)
        if not source_type or not target_type:
            removed += 1
            continue
        source_port_id = _handle_port_id(edge.get("sourceHandle"), "out-")
        target_port_id = _handle_port_id(edge.get("targetHandle"), "in-")
        if source_port_id is None or target_port_id is None:
            removed += 1
            continue
        migrated_source = LEGACY_HANDLE_MIGRATIONS.get((source_type, "source", source_port_id))
        migrated_target = LEGACY_HANDLE_MIGRATIONS.get((target_type, "target", target_port_id))
        if migrated_source is not None:
            source_port_id = migrated_source
        if migrated_target is not None:
            target_port_id = migrated_target
        source_ports = _port_map(source_type, "source")
        target_ports = _port_map(target_type, "target")
        source_port_type = source_ports.get(source_port_id)
        target_port_type = target_ports.get(target_port_id)
        if source_port_type is None or target_port_type is None or not _can_connect(source_port_type, target_port_type):
            removed += 1
            continue
        normalized_edge = dict(edge)
        next_source_handle = f"out-{source_port_id}"
        next_target_handle = f"in-{target_port_id}"
        if normalized_edge.get("sourceHandle") != next_source_handle:
            normalized_edge["sourceHandle"] = next_source_handle
            migrated += 1
        if normalized_edge.get("targetHandle") != next_target_handle:
            normalized_edge["targetHandle"] = next_target_handle
            migrated += 1
        normalized.append(normalized_edge)
    return normalized, migrated, removed


def normalize_workflow(workflow: dict) -> tuple[dict, int, int]:
    normalized = dict(workflow)
    nodes = normalized.get("nodes")
    edges = normalized.get("edges")
    if not isinstance(nodes, list):
        nodes = []
    if not isinstance(edges, list):
        edges = []
    normalized_edges, migrated, removed = normalize_workflow_edges(nodes, edges)
    # 确保每个节点都有 position（React Flow 必需字段）：缺失时按网格铺排默认位置，
    # 否则前端 setNodes 读取 node.position.x 会崩溃（Cannot read properties of undefined）。
    # 补充位置计入 migrated，触发调用方回写文件，修复存量脏数据。
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        if not isinstance(node.get("position"), dict):
            node["position"] = {"x": 80 + (index % 8) * 260, "y": 80 + (index // 8) * 160}
            migrated += 1
    normalized["nodes"] = nodes
    normalized["edges"] = normalized_edges
    return normalized, migrated, removed

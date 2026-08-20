from __future__ import annotations

import json
import re
from pathlib import Path

from backend.config.builtin_node_types import get_builtin_node_type


NODE_TYPES_DIR = Path(__file__).parent / "config" / "node_types"
NODE_TYPE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
LEGACY_HANDLE_MIGRATIONS = {
    ("asr", "target", "audio"): "asr_audio",
    ("asr", "source", "asr_result"): "subtitle",
}


def _node_type(node: dict) -> str:
    return str((node.get("data") or {}).get("nodeType") or "")


def _is_inline_group_node(node: dict) -> bool:
    data = node.get("data") or {}
    return isinstance(data, dict) and data.get("kind") == "group" and isinstance(data.get("groupMeta"), dict)


def _validate_inline_group_node(node: dict) -> None:
    meta = (node.get("data") or {}).get("groupMeta") or {}
    if meta.get("version") != 1:
        raise ValueError("Unsupported inline group version")
    internal = meta.get("internalWorkflow")
    if not isinstance(internal, dict):
        raise ValueError("Inline group internalWorkflow must be an object")
    internal_nodes = internal.get("nodes")
    internal_edges = internal.get("edges")
    if not isinstance(internal_nodes, list) or len(internal_nodes) < 2 or not isinstance(internal_edges, list):
        raise ValueError("Inline group requires internal nodes and edges")
    if any(_is_inline_group_node(item) for item in internal_nodes if isinstance(item, dict)):
        raise ValueError("Nested group nodes are not supported")
    validate_workflow_nodes(internal_nodes)
    internal_ids = {str(item.get("id") or "") for item in internal_nodes if isinstance(item, dict)}
    for mapping_key, node_key, port_key in (("inputMappings", "targetNodeId", "targetPortId"), ("outputMappings", "internalNodeId", "internalPortId")):
        mappings = meta.get(mapping_key)
        if not isinstance(mappings, list):
            raise ValueError(f"Inline group {mapping_key} must be a list")
        exposed_ids: set[str] = set()
        for mapping in mappings:
            if not isinstance(mapping, dict):
                raise ValueError(f"Invalid inline group {mapping_key} item")
            exposed_id = str(mapping.get("exposedPortId") or "")
            if not exposed_id or exposed_id in exposed_ids:
                raise ValueError(f"Inline group {mapping_key} exposedPortId must be unique")
            exposed_ids.add(exposed_id)
            if str(mapping.get(node_key) or "") not in internal_ids or not str(mapping.get(port_key) or ""):
                raise ValueError(f"Invalid inline group {mapping_key} target")


def validate_workflow_nodes(nodes: object) -> None:
    if not isinstance(nodes, list):
        raise ValueError("nodes must be a list")
    seen: set[str] = set()
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            raise ValueError(f"nodes[{index}] must be an object")
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id.strip():
            raise ValueError(f"nodes[{index}].id is required")
        if node_id in seen:
            raise ValueError(f"Duplicate node id: {node_id}")
        seen.add(node_id)
        data = node.get("data")
        if not isinstance(data, dict):
            raise ValueError(f"nodes[{index}].data must be an object")
        node_type = data.get("nodeType")
        if not isinstance(node_type, str) or not node_type.strip():
            raise ValueError(f"nodes[{index}].data.nodeType is required")
        if _is_inline_group_node(node):
            _validate_inline_group_node(node)
            continue
        if _node_definition(node_type) is None:
            raise ValueError(f"Unknown node type: {node_type}")


def _node_definition(node_type: str) -> dict | None:
    builtin = get_builtin_node_type(node_type)
    if builtin is not None:
        return builtin
    if not NODE_TYPE_ID_PATTERN.fullmatch(node_type):
        return None
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


def _port_map_for_node(node: dict, direction: str) -> dict[str, str]:
    if _is_inline_group_node(node):
        meta = (node.get("data") or {}).get("groupMeta") or {}
        mapping_key = "outputMappings" if direction == "source" else "inputMappings"
        return {
            str(item.get("exposedPortId")): str(item.get("type"))
            for item in meta.get(mapping_key, [])
            if isinstance(item, dict) and item.get("exposedPortId") and item.get("type") and (direction != "source" or item.get("enabled") is not False)
        }
    return _port_map(_node_type(node), direction)


def _handle_port_id(handle: object, prefix: str) -> str | None:
    if not isinstance(handle, str) or not handle.startswith(prefix):
        return None
    port_id = handle[len(prefix):]
    return port_id or None


def _can_connect(source_type: str, target_type: str) -> bool:
    return source_type == "any" or target_type == "any" or source_type == target_type


def normalize_workflow_edges(nodes: list[dict], edges: list[dict]) -> tuple[list[dict], int, int]:
    node_map = {
        str(node.get("id")): node
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
        source_node = node_map.get(source_id)
        target_node = node_map.get(target_id)
        if source_node is None or target_node is None:
            removed += 1
            continue
        source_port_id = _handle_port_id(edge.get("sourceHandle"), "out-")
        target_port_id = _handle_port_id(edge.get("targetHandle"), "in-")
        if source_port_id is None or target_port_id is None:
            removed += 1
            continue
        source_type = _node_type(source_node)
        target_type = _node_type(target_node)
        migrated_source = LEGACY_HANDLE_MIGRATIONS.get((source_type, "source", source_port_id)) if not _is_inline_group_node(source_node) else None
        migrated_target = LEGACY_HANDLE_MIGRATIONS.get((target_type, "target", target_port_id)) if not _is_inline_group_node(target_node) else None
        if migrated_source is not None:
            source_port_id = migrated_source
        if migrated_target is not None:
            target_port_id = migrated_target
        source_ports = _port_map_for_node(source_node, "source")
        target_ports = _port_map_for_node(target_node, "target")
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


def _expand_inline_groups(nodes: list[dict], edges: list[dict]) -> tuple[list[dict], list[dict], bool]:
    group_nodes = [node for node in nodes if _is_inline_group_node(node)]
    if not group_nodes:
        return nodes, edges, False
    expanded_nodes = [node for node in nodes if not _is_inline_group_node(node)]
    expanded_edges: list[dict] = []
    group_ids = {str(node.get("id")) for node in group_nodes}
    for group in group_nodes:
        group_id = str(group.get("id"))
        group_position = group.get("position") if isinstance(group.get("position"), dict) else {}
        group_x = group_position.get("x", 0)
        group_y = group_position.get("y", 0)
        meta = (group.get("data") or {}).get("groupMeta") or {}
        internal = meta.get("internalWorkflow") or {}
        prefix = f"{group_id}__"
        for node in internal.get("nodes", []):
            item = dict(node)
            position = item.get("position") if isinstance(item.get("position"), dict) else {}
            item["id"] = f"{prefix}{item.get('id')}"
            item["position"] = {"x": group_x + position.get("x", 0), "y": group_y + position.get("y", 0)}
            item["selected"] = False
            expanded_nodes.append(item)
        for edge in internal.get("edges", []):
            item = dict(edge)
            edge_id = item.get("id") or f"{item.get('source')}-{item.get('target')}"
            item["id"] = f"{prefix}{edge_id}"
            item["source"] = f"{prefix}{item.get('source')}"
            item["target"] = f"{prefix}{item.get('target')}"
            item["selected"] = False
            expanded_edges.append(item)
        inputs = {str(item.get("exposedPortId")): item for item in meta.get("inputMappings", []) if isinstance(item, dict)}
        outputs = {str(item.get("exposedPortId")): item for item in meta.get("outputMappings", []) if isinstance(item, dict) and item.get("enabled") is not False}
        for edge in edges:
            if edge.get("target") == group_id:
                mapping = inputs.get(_handle_port_id(edge.get("targetHandle"), "in-") or "")
                if mapping:
                    item = dict(edge)
                    item["target"] = f"{prefix}{mapping.get('targetNodeId')}"
                    item["targetHandle"] = f"in-{mapping.get('targetPortId')}"
                    expanded_edges.append(item)
            elif edge.get("source") == group_id:
                mapping = outputs.get(_handle_port_id(edge.get("sourceHandle"), "out-") or "")
                if mapping:
                    item = dict(edge)
                    item["source"] = f"{prefix}{mapping.get('internalNodeId')}"
                    item["sourceHandle"] = f"out-{mapping.get('internalPortId')}"
                    expanded_edges.append(item)
    expanded_edges.extend(edge for edge in edges if edge.get("source") not in group_ids and edge.get("target") not in group_ids)
    return expanded_nodes, expanded_edges, True


# 内置节点数据结构迁移：对齐 backend/config/builtin_node_types.py 的最新节点定义。
# - input 节点新增「文件路径」输入类型，存量工作流缺省补齐 filePath 配置键；
# - extract_audio（音频分离）已移除音频质量设置，存量工作流清理残留的质量键；
#   注意：format 现为「保存格式」设置项（s15_extract_audio 按此重编码），不可清理。
NODE_CONFIG_MIGRATIONS: dict[str, dict] = {
    "input": {"add_keys": {"filePath": "", "source_language": "auto", "target_language": "zh", "copyInputs": True}},
    "extract_audio": {"remove_keys": {"sample_rate", "bit_depth", "channels", "bitrate"}},
    "vocal_separation": {"remove_keys": {"sample_rate", "bit_depth", "channels", "bitrate"}},
    "video_preview": {"replace_values": {"fontSize": {24: 12}}},
    "sentence_split": {"add_keys": {"processing_language": "from_input"}},
    "sentence_preprocess": {"add_keys": {"processing_language": "from_input"}},
    "translate": {"add_keys": {"processing_language": "from_input", "target_language": "from_input"}},
}


def _migrate_node_configs(nodes: list[dict]) -> int:
    """按最新内置节点定义迁移存量节点 config 数据结构，返回发生变更的节点数。

    内联组合节点的内部工作流节点一并递归迁移。
    """
    migrated = 0
    for node in nodes:
        if not isinstance(node, dict):
            continue
        data = node.get("data")
        if not isinstance(data, dict):
            continue
        # 内联组合节点：递归迁移内部工作流节点
        if data.get("kind") == "group" and isinstance(data.get("groupMeta"), dict):
            internal = data["groupMeta"].get("internalWorkflow") or {}
            migrated += _migrate_node_configs(internal.get("nodes") or [])
        rule = NODE_CONFIG_MIGRATIONS.get(data.get("nodeType"))
        if not rule:
            continue
        cfg = data.get("config")
        if not isinstance(cfg, dict):
            cfg = {}
            data["config"] = cfg
        for key in rule.get("remove_keys", []):
            if key in cfg:
                del cfg[key]
                migrated += 1
        for key, default in (rule.get("add_keys") or {}).items():
            if key not in cfg:
                cfg[key] = default
                migrated += 1
        for key, replacements in (rule.get("replace_values") or {}).items():
            if key in cfg and cfg[key] in replacements:
                cfg[key] = replacements[cfg[key]]
                migrated += 1
    return migrated


def normalize_workflow(workflow: dict, expand_groups: bool = False) -> tuple[dict, int, int]:
    normalized = dict(workflow)
    nodes = normalized.get("nodes")
    edges = normalized.get("edges")
    if not isinstance(nodes, list):
        nodes = []
    if not isinstance(edges, list):
        edges = []
    expanded = False
    if expand_groups:
        nodes, edges, expanded = _expand_inline_groups(nodes, edges)
    validate_workflow_nodes(nodes)
    normalized_edges, migrated, removed = normalize_workflow_edges(nodes, edges)
    migrated += _migrate_node_configs(nodes)
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
    return normalized, migrated + int(expanded), removed

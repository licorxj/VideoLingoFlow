"""Shared node schema definitions and validation helpers."""
from __future__ import annotations


NODE_CATEGORIES = [
    {"value": "io", "label": "输入输出节点", "color": "#3b82f6", "icon": "Upload"},
    {"value": "preview", "label": "预览节点", "color": "#14b8a6", "icon": "Eye"},
    {"value": "audio", "label": "音频处理节点", "color": "#0ea5e9", "icon": "Volume2"},
    {"value": "video", "label": "视频处理节点", "color": "#ef4444", "icon": "Film"},
    {"value": "ai_gen", "label": "AI生成类节点", "color": "#10b981", "icon": "Sparkles"},
    {"value": "translation", "label": "翻译相关节点", "color": "#8b5cf6", "icon": "Languages"},
    {"value": "flow_control", "label": "流程控制节点", "color": "#6366f1", "icon": "GitBranch"},
    {"value": "network_request", "label": "网络请求类节点", "color": "#0f766e", "icon": "Globe"},
    {"value": "aigc", "label": "AIGC流程链", "color": "#22c55e", "icon": "Boxes"},
    {"value": "agent", "label": "智能体", "color": "#a855f7", "icon": "Bot"},
    {"value": "utility", "label": "工具类节点", "color": "#f59e0b", "icon": "Wrench"},
    {"value": "file", "label": "文件操作类节点", "color": "#f97316", "icon": "FolderOpen"},
    {"value": "group_node", "label": "组合节点", "color": "#64748b", "icon": "Boxes"},
    {"value": "hyperframes", "label": "HyperFrames 节点", "color": "#f43f5e", "icon": "Clapperboard"},
]

PORT_TYPES = [
    {"value": "video", "label": "视频"},
    {"value": "audio", "label": "音频"},
    {"value": "audio_manifest", "label": "音频清单"},
    {"value": "json", "label": "JSON"},
    {"value": "pandas", "label": "表格数据"},
    {"value": "subtitle", "label": "字幕"},
    {"value": "text", "label": "文本"},
    {"value": "image", "label": "图片"},
    {"value": "url", "label": "URL"},
    {"value": "filepath", "label": "文件路径"},
    {"value": "preview", "label": "预览"},
    {"value": "any", "label": "通用"},
]

CONFIG_FIELD_TYPES = [
    {"value": "text", "label": "单行文本", "supportedProperties": ["placeholder", "description", "dependsOn", "dependsValue", "dependsOnAny", "dependsAnyValues"]},
    {"value": "textarea", "label": "多行文本", "supportedProperties": ["placeholder", "description", "dependsOn", "dependsValue", "dependsOnAny", "dependsAnyValues"]},
    {"value": "select", "label": "下拉选择", "supportedProperties": ["placeholder", "options", "description", "dependsOn", "dependsValue", "dependsOnAny", "dependsAnyValues"], "requiresOptions": True},
    {"value": "multiselect", "label": "多选下拉", "supportedProperties": ["placeholder", "options", "description", "dependsOn", "dependsValue", "dependsOnAny", "dependsAnyValues"]},
    {"value": "checkbox", "label": "复选框", "supportedProperties": ["description", "dependsOn", "dependsValue", "dependsOnAny", "dependsAnyValues"]},
    {"value": "toggle", "label": "开关", "supportedProperties": ["description", "dependsOn", "dependsValue", "dependsOnAny", "dependsAnyValues"]},
    {"value": "chips", "label": "标签选择", "supportedProperties": ["options", "chipColor", "description", "dependsOn", "dependsValue", "dependsOnAny", "dependsAnyValues"], "requiresOptions": True},
    {"value": "file", "label": "文件选择", "supportedProperties": ["placeholder", "fileFilter", "description", "dependsOn", "dependsValue", "dependsOnAny", "dependsAnyValues"]},
    {"value": "language-select", "label": "语言选择", "supportedProperties": ["description", "dependsOn", "dependsValue", "dependsOnAny", "dependsAnyValues"]},
    {"value": "api-select", "label": "接口选项", "supportedProperties": ["placeholder", "apiEndpoint", "apiUrl", "optionLabel", "optionValue", "description", "dependsOn", "dependsValue", "dependsOnAny", "dependsAnyValues"]},
    {"value": "slider", "label": "滑块", "supportedProperties": ["placeholder", "min", "max", "step", "description", "dependsOn", "dependsValue", "dependsOnAny", "dependsAnyValues"]},
    {"value": "number", "label": "数字", "supportedProperties": ["placeholder", "min", "max", "step", "description", "dependsOn", "dependsValue", "dependsOnAny", "dependsAnyValues"]},
    {"value": "button", "label": "按钮", "supportedProperties": ["description", "hint", "dependsOn", "dependsValue", "dependsOnAny", "dependsAnyValues"]},
]

EXEC_TYPES = [
    {"value": "", "label": "无 (仅 UI)"},
    {"value": "python", "label": "Python 脚本"},
    {"value": "shell", "label": "Shell 命令"},
    {"value": "llm", "label": "LLM 处理"},
]

ALLOWED_NODE_CATEGORIES = {item["value"] for item in NODE_CATEGORIES}
ALLOWED_PORT_TYPES = {item["value"] for item in PORT_TYPES}
ALLOWED_CONFIG_FIELD_TYPES = {item["value"] for item in CONFIG_FIELD_TYPES}
ALLOWED_EXEC_TYPES = {item["value"] for item in EXEC_TYPES}
CONFIG_FIELD_TYPE_RULES = {item["value"]: item for item in CONFIG_FIELD_TYPES}


def get_node_schema() -> dict:
    """Return shared schema metadata for frontend consumption."""
    return {
        "categories": NODE_CATEGORIES,
        "portTypes": PORT_TYPES,
        "configFieldTypes": CONFIG_FIELD_TYPES,
        "execTypes": EXEC_TYPES,
    }


def validate_node_type_data(data: dict) -> None:
    """Validate node definition payload against the shared schema."""
    category = data.get("category", "process")
    if category not in ALLOWED_NODE_CATEGORIES:
        raise ValueError(f"Invalid node category: {category}")

    exec_type = data.get("execType", "")
    if exec_type not in ALLOWED_EXEC_TYPES:
        raise ValueError(f"Invalid execType: {exec_type}")
    if not str(data.get("id", "")).strip() or not str(data.get("name", "")).strip():
        raise ValueError("Node id and name are required")
    exec_timeout = data.get("execTimeout", 300)
    if not isinstance(exec_timeout, int) or exec_timeout < 1:
        raise ValueError("execTimeout must be a positive integer")
    if exec_type == "python" and not (str(data.get("execCode", "")).strip() or str(data.get("execFile", "")).strip()):
        raise ValueError("Python nodes require execCode or execFile")
    if exec_type in {"shell", "llm"} and not str(data.get("execCode", "")).strip():
        raise ValueError(f"{exec_type} nodes require execCode")

    kind = data.get("kind", "normal")
    if kind not in {"normal", "group", "loop"}:
        raise ValueError(f"Invalid node kind: {kind}")
    group_definition = data.get("groupDefinition")
    if kind in {"group", "loop"}:
        expected_category = "group_node" if kind == "group" else "flow_control"
        if category != expected_category:
            raise ValueError(f"{kind.capitalize()} nodes must use {expected_category} category")
        if exec_type:
            raise ValueError(f"{kind.capitalize()} nodes cannot define execType")
        # 循环体允许单节点子图；组合节点至少两个成员
        _validate_group_definition(group_definition, min_nodes=1 if kind == "loop" else 2)
    elif group_definition is not None:
        raise ValueError("groupDefinition is only supported by group/loop nodes")

    for port_kind in ("inputs", "outputs"):
        ports = data.get(port_kind) or []
        if not isinstance(ports, list):
            raise ValueError(f"{port_kind} must be a list")
        seen_port_ids: set[str] = set()
        for port in ports:
            if not isinstance(port, dict):
                raise ValueError(f"Invalid {port_kind} item")
            port_id = str(port.get("id", "")).strip()
            port_label = str(port.get("label", "")).strip()
            port_type = port.get("type", "")
            if not port_id:
                raise ValueError(f"{port_kind} port id is required")
            if port_id in seen_port_ids:
                raise ValueError(f"Duplicate {port_kind} port id: {port_id}")
            seen_port_ids.add(port_id)
            if not port_label:
                raise ValueError(f"{port_kind} port label is required")
            if port_type not in ALLOWED_PORT_TYPES:
                raise ValueError(f"Invalid {port_kind} port type: {port_type}")

    config_fields = data.get("configFields") or []
    if not isinstance(config_fields, list):
        raise ValueError("configFields must be a list")
    default_config = data.get("defaultConfig") or {}
    if not isinstance(default_config, dict):
        raise ValueError("defaultConfig must be an object")
    seen_field_keys: set[str] = set()
    for field in config_fields:
        if not isinstance(field, dict):
            raise ValueError("Invalid config field item")
        field_key = str(field.get("key", "")).strip()
        field_label = str(field.get("label", "")).strip()
        field_type = field.get("type", "")
        if not field_key:
            raise ValueError("Config field key is required")
        if not field_label:
            raise ValueError(f"Config field label is required: {field_key}")
        if field_type not in ALLOWED_CONFIG_FIELD_TYPES:
            raise ValueError(f"Invalid config field type: {field_type}")
        if field_key in seen_field_keys:
            raise ValueError(f"Duplicate config field key: {field_key}")
        seen_field_keys.add(field_key)

        rule = CONFIG_FIELD_TYPE_RULES[field_type]
        supported = set(rule.get("supportedProperties", [])) | {"key", "label", "type"}
        unsupported = sorted(k for k, v in field.items() if k not in supported and v not in (None, "", [], {}))
        if unsupported:
            raise ValueError(f"Unsupported properties for config field '{field_key}': {', '.join(unsupported)}")

        options = field.get("options")
        if rule.get("requiresOptions"):
            if not isinstance(options, list) or not options:
                raise ValueError(f"Config field '{field_key}' requires non-empty options")
        if options is not None:
            if not isinstance(options, list):
                raise ValueError(f"Config field options must be a list: {field_key}")
            for item in options:
                if not isinstance(item, dict) or not str(item.get("value", "")).strip() or not str(item.get("label", "")).strip():
                    raise ValueError(f"Invalid option item in config field: {field_key}")

        file_filter = field.get("fileFilter")
        if file_filter is not None:
            if not isinstance(file_filter, list) or not all(isinstance(item, str) and item.strip() for item in file_filter):
                raise ValueError(f"Config field fileFilter must be a string list: {field_key}")

        for array_key in ("dependsOnAny", "dependsAnyValues"):
            array_value = field.get(array_key)
            if array_value is not None and not isinstance(array_value, list):
                raise ValueError(f"Config field {array_key} must be a list: {field_key}")

        if field_type == "api-select" and not (field.get("apiEndpoint") or field.get("apiUrl")):
            raise ValueError(f"Config field '{field_key}' requires apiEndpoint or apiUrl")

        if field_type in {"slider", "number"}:
            for numeric_key in ("min", "max", "step"):
                numeric_value = field.get(numeric_key)
                if numeric_value is not None and not isinstance(numeric_value, (int, float)):
                    raise ValueError(f"Config field {numeric_key} must be numeric: {field_key}")
            min_value = field.get("min")
            max_value = field.get("max")
            if isinstance(min_value, (int, float)) and isinstance(max_value, (int, float)) and max_value < min_value:
                raise ValueError(f"Config field max must be >= min: {field_key}")


def _validate_group_definition(definition: object, min_nodes: int = 2) -> None:
    if not isinstance(definition, dict):
        raise ValueError("Group nodes require groupDefinition")
    if definition.get("version") != 1:
        raise ValueError("Unsupported groupDefinition version")
    internal = definition.get("internalWorkflow")
    if not isinstance(internal, dict):
        raise ValueError("groupDefinition.internalWorkflow must be an object")
    internal_nodes = internal.get("nodes")
    internal_edges = internal.get("edges")
    if not isinstance(internal_nodes, list) or len(internal_nodes) < min_nodes:
        raise ValueError(f"Group nodes require at least {min_nodes} internal nodes")
    if not isinstance(internal_edges, list):
        raise ValueError("groupDefinition.internalWorkflow.edges must be a list")
    node_ids = {str(node.get("id", "")) for node in internal_nodes if isinstance(node, dict)}
    if len(node_ids) != len(internal_nodes) or "" in node_ids:
        raise ValueError("Group internal node ids must be unique")
    for node in internal_nodes:
        if not isinstance(node, dict) or (node.get("data") or {}).get("kind") == "group":
            raise ValueError("Nested group nodes are not supported")
    for mapping_key, node_key, port_key in (("inputMappings", "targetNodeId", "targetPortId"), ("outputMappings", "internalNodeId", "internalPortId")):
        mappings = definition.get(mapping_key)
        if not isinstance(mappings, list):
            raise ValueError(f"groupDefinition.{mapping_key} must be a list")
        exposed_ids: set[str] = set()
        for mapping in mappings:
            if not isinstance(mapping, dict):
                raise ValueError(f"Invalid {mapping_key} item")
            exposed_id = str(mapping.get("exposedPortId", "")).strip()
            if not exposed_id or exposed_id in exposed_ids:
                raise ValueError(f"{mapping_key} exposedPortId must be unique")
            exposed_ids.add(exposed_id)
            if str(mapping.get(node_key, "")) not in node_ids or not str(mapping.get(port_key, "")).strip():
                raise ValueError(f"Invalid {mapping_key} target")
            if mapping.get("type") not in ALLOWED_PORT_TYPES:
                raise ValueError(f"Invalid {mapping_key} port type")

import { Node, Edge } from "@xyflow/react";
import { BUILTIN_NODE_TYPES, FALLBACK_NODE_TYPES } from "./fallbackNodeTypes";

// ==================== Port Types ====================
export type PortType =
  | "video"
  | "audio"
  | "audio_manifest"
  | "json"
  | "pandas"
  | "subtitle"
  | "text"
  | "image"
  | "list"
  | "url"
  | "filepath"
  | "any"
  | "preview";

export const PORT_COLORS: Record<PortType, string> = {
  video: "#3b82f6",
  audio: "#10b981",
  audio_manifest: "#22c55e",
  json: "#6366f1",
  pandas: "#0f766e",
  subtitle: "#f59e0b",
  text: "#8b5cf6",
  image: "#ec4899",
  list: "#a855f7",
  url: "#06b6d4",
  filepath: "#f97316",
  any: "#6b7280",
  preview: "#14b8a6",
};

export const PORT_LABELS: Record<PortType, string> = {
  video: "视频",
  audio: "音频",
  audio_manifest: "音频清单",
  json: "JSON",
  pandas: "表格数据",
  subtitle: "字幕",
  text: "文本",
  image: "图片",
  list: "列表",
  url: "URL",
  filepath: "文件路径",
  any: "通用",
  preview: "预览",
};

// ==================== Port Definition ====================
export interface PortDef {
  id: string;
  label: string;
  type: PortType;
  required?: boolean;
  color?: string;
}

export interface GroupInputMapping {
  exposedPortId: string;
  exposedLabel: string;
  targetNodeId: string;
  targetPortId: string;
  type: PortType;
}

export interface GroupOutputMapping {
  exposedPortId: string;
  exposedLabel: string;
  internalNodeId: string;
  internalPortId: string;
  type: PortType;
  enabled?: boolean;
}

export interface GroupWorkflowDefinition {
  version: number;
  internalWorkflow: {
    nodes: WorkflowNode[];
    edges: WorkflowEdge[];
  };
  inputMappings: GroupInputMapping[];
  outputMappings: GroupOutputMapping[];
  layout?: {
    memberPositionsRelativeToGroup?: Record<string, { x: number; y: number }>;
  };
}

/** 循环容器的迭代路由：指定「当前条目」注入到循环体内部哪个节点端口。 */
export interface LoopIteratorMapping {
  /** 迭代来源的暴露端口 id（对应 inputMappings 中的一项） */
  exposedPortId: string;
  /** 循环体内部接收当前条目的节点 id */
  targetNodeId: string;
  /** 循环体内部接收当前条目的端口 id */
  targetPortId: string;
}

/** 循环容器元信息：与组合节点同构（内部子图 + 端口映射），额外带迭代路由。 */
export interface LoopWorkflowDefinition extends GroupWorkflowDefinition {
  iterator?: LoopIteratorMapping;
}

// ==================== Config Field Definition ====================
export interface ConfigField {
  key: string;
  label: string;
  type: "text" | "textarea" | "select" | "multiselect" | "checkbox" | "toggle" | "chips" | "file" | "hotwords" | "language-select" | "api-select" | "voice-select" | "slider" | "number" | "datetime-local" | "account-select" | "audio-selector" | "date" | "time" | "button";
  placeholder?: string;
  options?: { value: string; label: string }[];
  dependsOn?: string;
  dependsValue?: any;
  dependsOnAny?: string[];
  dependsAnyValues?: any[];
  chipColor?: string;
  singleSelect?: boolean;
  /** chips 选项右侧追加的外链按钮 */
  link?: { label?: string; url: string };
  /** chips 选项右侧追加的动作按钮：点击调用后端接口（如安装即梦插件） */
  action?: { label: string; url: string; method?: "GET" | "POST"; busyLabel?: string };
  fileFilter?: string[];
  apiEndpoint?: string;
  apiUrl?: string;
  interfaceIdKey?: string;
  optionLabel?: string;
  optionValue?: string;
  description?: string;
  hint?: string;
  defaultValue?: any;
  min?: number;
  max?: number;
  step?: number;
  inline?: boolean;
  colSpan?: "half" | "full" | "third";
  chips?: { value: string; label: string }[];
}

// ==================== Node Type Definition ====================
export interface NodeTypeDef {
  id: string;
  name: string;
  category: "io" | "preview" | "audio" | "video" | "ai_gen" | "translation" | "flow_control" | "network_request" | "aigc" | "agent" | "utility" | "file" | "group_node" | "input" | "process" | "ai" | "output" | "publish";
  description: string;
  icon: string;
  color: string;
  execution_domain?: "thread" | "process" | "llm";
  dynamicPorts?: any;
  inputs: PortDef[];
  outputs: PortDef[];
  defaultConfig?: Record<string, any>;
  configFields?: ConfigField[];
  dynamicConfigEndpoint?: string;
  isBuiltIn?: boolean;
  kind?: "normal" | "group" | "loop";
  groupDefinition?: GroupWorkflowDefinition;
}

// ==================== Node/Edge for React Flow ====================
export interface WorkflowNode extends Node {
  data: {
    nodeType: string;
    label: string;
    config: Record<string, any>;
    kind?: "normal" | "group" | "loop";
    groupMeta?: GroupWorkflowDefinition & {
      groupId: string;
      name: string;
      savedNodeTypeId?: string;
    };
    loopMeta?: LoopWorkflowDefinition & {
      loopId: string;
      name: string;
      savedNodeTypeId?: string;
    };
    /** 循环执行进度快照（由后端 node_progress 事件的 loop_index/loop_total 驱动） */
    loopProgress?: { index: number; total: number; done: number; status: string };
    status?: "pending" | "running" | "waiting" | "completed" | "failed" | "skipped" | "cancelled";
    progress?: number;
    message?: string;
    [key: string]: any;
  };
}

export interface WorkflowEdge extends Edge {
  data?: {
    sourcePort: string;
    targetPort: string;
  };
}

// ==================== Workflow Definition ====================
export interface Workflow {
  id: string;
  name: string;
  description: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  createdAt: string;
  updatedAt: string;
}

let runtimeNodeTypes: NodeTypeDef[] = [];

// ==================== Category Config ====================
export const CATEGORIES = {
  io: { label: "输入输出节点", color: "#3b82f6", icon: "Upload" },
  preview: { label: "预览节点", color: "#14b8a6", icon: "Eye" },
  audio: { label: "音频处理节点", color: "#0ea5e9", icon: "Volume2" },
  video: { label: "视频处理节点", color: "#ef4444", icon: "Film" },
  ai_gen: { label: "AI生成类节点", color: "#10b981", icon: "Sparkles" },
  translation: { label: "翻译相关节点", color: "#8b5cf6", icon: "Languages" },
  flow_control: { label: "流程控制节点", color: "#6366f1", icon: "GitBranch" },
  network_request: { label: "网络请求类节点", color: "#0f766e", icon: "Globe" },
  aigc: { label: "AIGC流程链", color: "#22c55e", icon: "Boxes" },
  asset: { label: "素材库", color: "#84cc16", icon: "Library" },
  agent: { label: "智能体", color: "#a855f7", icon: "Bot" },
  utility: { label: "工具类节点", color: "#f59e0b", icon: "Wrench" },
  file: { label: "文件操作类节点", color: "#f97316", icon: "FolderOpen" },
  group_node: { label: "组合节点", color: "#64748b", icon: "Boxes" },
  hyperframes: { label: "HyperFrames 节点", color: "#f43f5e", icon: "Clapperboard" },
  input: { label: "输入节点", color: "#3b82f6", icon: "Upload" },
  process: { label: "处理节点", color: "#0ea5e9", icon: "Cog" },
  ai: { label: "AI 节点", color: "#10b981", icon: "Sparkles" },
  output: { label: "输出节点", color: "#f97316", icon: "Download" },
  publish: { label: "发布节点", color: "#ec4899", icon: "Send" },
} as const;

// ==================== Helper Functions ====================
export function registerRuntimeNodeTypes(nodeTypes: NodeTypeDef[]) {
  const deduped = new Map<string, NodeTypeDef>();
  for (const nodeType of nodeTypes) {
    if (!nodeType?.id) continue;
    deduped.set(nodeType.id, nodeType);
  }
  runtimeNodeTypes = Array.from(deduped.values());
}

export function getAllNodeTypes(): NodeTypeDef[] {
  const merged = new Map<string, NodeTypeDef>();
  for (const node of FALLBACK_NODE_TYPES) {
    merged.set(node.id, node);
  }
  for (const node of runtimeNodeTypes) {
    merged.set(node.id, node);
  }
  return Array.from(merged.values());
}

export function getNodeTypeDef(nodeType: string): NodeTypeDef | undefined {
  return getAllNodeTypes().find((n) => n.id === nodeType);
}

export function isGroupNodeData(data: Record<string, any> | undefined | null): boolean {
  return data?.kind === "group" || data?.nodeType === "group_inline";
}

/** 循环容器节点：内部子图存放在 loopMeta，执行时按迭代条目逐条展开。 */
export function isLoopNodeData(data: Record<string, any> | undefined | null): boolean {
  return data?.kind === "loop" || data?.nodeType === "loop_inline";
}

/** 容器节点（组合 / 循环）：内部子图在运行时展开，对外表现为单一节点。 */
export function isContainerNodeData(data: Record<string, any> | undefined | null): boolean {
  return isGroupNodeData(data) || isLoopNodeData(data);
}

export function buildInlineGroupTypeDef(data: Record<string, any>): NodeTypeDef | undefined {
  if (!isGroupNodeData(data) || !data?.groupMeta) return undefined;
  const meta = data.groupMeta as WorkflowNode["data"]["groupMeta"];
  const outputs = (meta?.outputMappings || []).filter((item) => item.enabled !== false);
  return {
    id: data.nodeType || "group_inline",
    name: meta?.name || data.label || "组合",
    category: "group_node",
    description: "组合节点",
    icon: "Boxes",
    color: "#6366f1",
    inputs: (meta?.inputMappings || []).map((item) => ({
      id: item.exposedPortId,
      label: item.exposedLabel,
      type: item.type,
    })),
    outputs: outputs.map((item) => ({
      id: item.exposedPortId,
      label: item.exposedLabel,
      type: item.type,
    })),
    defaultConfig: {},
    configFields: [],
    kind: "group",
    groupDefinition: meta ? {
      version: meta.version,
      internalWorkflow: meta.internalWorkflow,
      inputMappings: meta.inputMappings,
      outputMappings: meta.outputMappings,
      layout: meta.layout,
    } : undefined,
  };
}

export function buildInlineLoopTypeDef(data: Record<string, any>): NodeTypeDef | undefined {
  if (!isLoopNodeData(data) || !data?.loopMeta) return undefined;
  const meta = data.loopMeta as WorkflowNode["data"]["loopMeta"];
  const staticDef = getNodeTypeDef("loop");
  const mappedInputs = (meta?.inputMappings || []).map((item) => ({
    id: item.exposedPortId, label: item.exposedLabel, type: item.type,
  }));
  const mappedOutputs = (meta?.outputMappings || [])
    .filter((item) => item.enabled !== false)
    .map((item) => ({ id: item.exposedPortId, label: item.exposedLabel, type: item.type }));
  // 合并内建端口（产物清单 / 迭代总数），映射端口优先
  const outputs = [...mappedOutputs];
  for (const port of staticDef?.outputs || []) {
    if (!outputs.some((item) => item.id === port.id)) outputs.push(port);
  }
  return {
    id: String(data.nodeType || "loop_inline"),
    name: meta?.name || data.label || "循环",
    category: "flow_control",
    description: "循环节点",
    icon: staticDef?.icon || "Repeat",
    color: staticDef?.color || "#6366f1",
    execution_domain: "thread",
    inputs: mappedInputs,
    outputs,
    defaultConfig: staticDef?.defaultConfig || {},
    configFields: staticDef?.configFields || [],
    kind: "loop",
  };
}

export function getNodeTypeDefFromNode(node: { data?: Record<string, any> } | undefined | null): NodeTypeDef | undefined {
  if (!node?.data) return undefined;
  if (isGroupNodeData(node.data)) {
    return buildInlineGroupTypeDef(node.data) || getNodeTypeDef(String(node.data.nodeType || ""));
  }
  if (isLoopNodeData(node.data)) {
    return buildInlineLoopTypeDef(node.data) || getNodeTypeDef("loop");
  }
  return getNodeTypeDef(String(node.data.nodeType || ""));
}

export function getNodesByCategory(category: string): NodeTypeDef[] {
  return getAllNodeTypes().filter((n) => n.category === category);
}

/** 预览类节点：快速连线候选列表中排在最前面 */
export function isPreviewNode(nodeType: NodeTypeDef): boolean {
  return nodeType.category === "preview" || nodeType.id.includes("preview");
}

/** 可接收某个输出端口的下游节点候选：节点类型 + 将要接入的输入端口 */
export interface DownstreamCandidate {
  nodeType: NodeTypeDef;
  port: PortDef;
}

/**
 * 找出所有输入端口能接收 sourcePortType 的下游节点，预览类节点排在最前。
 * 每个节点类型只保留第一个可接入的输入端口。
 */
export function findDownstreamCandidates(sourcePortType: PortType): DownstreamCandidate[] {
  const candidates: DownstreamCandidate[] = [];
  for (const nodeType of getAllNodeTypes()) {
    // 没有内嵌定义（无法实例化）的组合节点类型不参与候选
    if (nodeType.kind === "group" && !nodeType.groupDefinition) continue;
    // 循环容器只能由「选中已连线节点 → 创建循环」产生，不支持从节点库/快速连线直接实例化
    if (nodeType.kind === "loop" || nodeType.id === "loop") continue;
    const inputs = getNodeInputs(nodeType, nodeType.defaultConfig || {});
    const port = inputs.find((p) => canConnect(sourcePortType, p.type));
    if (!port) continue;
    candidates.push({ nodeType, port });
  }
  return candidates.sort((a, b) => {
    const rankA = isPreviewNode(a.nodeType) ? 0 : 1;
    const rankB = isPreviewNode(b.nodeType) ? 0 : 1;
    if (rankA !== rankB) return rankA - rankB;
    return a.nodeType.name.localeCompare(b.nodeType.name, "zh-CN");
  });
}

export function canConnect(
  sourcePortType: PortType,
  targetPortType: PortType
): boolean {
  if (sourcePortType === "any" || targetPortType === "any") return true;
  // 字幕端口承载的是 ASR JSON 文件，允许连接到 JSON 输入端口
  if (sourcePortType === "subtitle" && targetPortType === "json") return true;
  // 列表（如图片列表）可接入 JSON 输入端口，用作循环的迭代对象来源
  if (sourcePortType === "list" && targetPortType === "json") return true;
  // 图片与图片列表可互连（参考图列表输入既接受单张图，也接受列表）
  if ((sourcePortType === "image" && targetPortType === "list") ||
      (sourcePortType === "list" && targetPortType === "image")) return true;
  return sourcePortType === targetPortType;
}

/** Get visible outputs for a node based on its config (for input node dynamic ports) */
export function getVisibleOutputs(nodeType: NodeTypeDef, config: Record<string, any>): PortDef[] {
  if (nodeType.kind === "group" && nodeType.groupDefinition) {
    return nodeType.groupDefinition.outputMappings
      .filter((item) => item.enabled !== false)
      .map((item) => ({ id: item.exposedPortId, label: item.exposedLabel, type: item.type }));
  }
  if (nodeType.id === "input") {
    const selectedTypes: string[] = config.selectedTypes || ["video"];
    // "不需要输入" 是常驻占位输出，不受 selectedTypes 影响
    return nodeType.outputs.filter((p) => selectedTypes.includes(p.id) || p.id === "no_input");
  }
  if (nodeType.id === "pi_agent") {
    return dynamicPorts(nodeType.outputs, config.outputCount, "output");
  }
  if (nodeType.id === "output_merge_list") {
    // 合并节点仅有一个静态 json 输出，不随端口数变化
    return nodeType.outputs;
  }
  return nodeType.outputs;
}

/** Get visible inputs for a node (pi_agent supports dynamic input ports) */
export function getNodeInputs(nodeType: NodeTypeDef, config: Record<string, any>): PortDef[] {
  if (nodeType.kind === "group" && nodeType.groupDefinition) {
    return nodeType.groupDefinition.inputMappings.map((item) => ({
      id: item.exposedPortId,
      label: item.exposedLabel,
      type: item.type,
    }));
  }
  if (nodeType.id === "pi_agent" || nodeType.id === "output_merge_list") {
    return dynamicPorts(nodeType.inputs, config.inputCount, "input");
  }
  return nodeType.inputs;
}

/** pi_agent 动态端口：按 inputCount/outputCount 生成 输入N/输出N（全部 any） */
function dynamicPorts(base: PortDef[], count: number, kind: "input" | "output"): PortDef[] {
  const n = Math.min(Math.max(Number(count) || 2, 1), 8);
  const ports: PortDef[] = [];
  for (let i = 1; i <= n; i++) {
    ports.push({ id: `${kind}_${i}`, label: `${kind === "input" ? "输入" : "输出"}${i}`, type: "any" });
  }
  return ports.length ? ports : base;
}

/** pi_agent 输出产物类型 -> 端口值类型/默认扩展名 */
export const PI_AGENT_OUTPUT_TYPES = [
  { value: "text", label: "字符串" },
  { value: "txt", label: "文本文件" },
  { value: "json", label: "json文件" },
  { value: "subtitle", label: "字幕文件" },
  { value: "image", label: "图片" },
  { value: "audio", label: "音频" },
  { value: "video", label: "视频" },
] as const;

/** Check if a config field should be visible based on dependsOn */
export function isConfigFieldVisible(field: ConfigField, config: Record<string, any>): boolean {
  if (!field.dependsOn) return true;
  const depValue = config[field.dependsOn];

  // supports chip-style array values ?check if array contains any of the dependsAnyValues
  if (field.dependsAnyValues && Array.isArray(depValue)) {
    return field.dependsAnyValues.some((v: any) => depValue.includes(v));
  }

  // If dependsValue is not set, field is visible whenever the dependency exists and is truthy
  if (field.dependsValue === undefined) {
    return !!depValue;
  }

  if (typeof field.dependsValue === "function") {
    return field.dependsValue(depValue);
  }

  // depValue is array (from chips): check if array contains the dependsValue
  if (Array.isArray(depValue)) {
    if (Array.isArray(field.dependsValue)) {
      return field.dependsValue.some((v: any) => depValue.includes(v));
    }
    return depValue.includes(field.dependsValue);
  }

  // Support dependsValue as array (field visible if depValue matches any value in array)
  if (Array.isArray(field.dependsValue)) {
    return field.dependsValue.includes(depValue);
  }

  return depValue === field.dependsValue;
}

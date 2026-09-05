import type {
  GroupInputMapping,
  GroupOutputMapping,
  GroupWorkflowDefinition,
  NodeTypeDef,
  PortDef,
  PortType,
  Workflow,
  WorkflowEdge,
  WorkflowNode,
} from "./workflowTypes";
import { getNodeTypeDefFromNode, getVisibleOutputs, isGroupNodeData } from "./workflowTypes";

const GROUP_NODE_COLOR = "#6366f1";

export function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value));
}

function groupNodeId() {
  return `group_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;
}

/** 容器节点 id 生成器（组合 / 循环共用命名规则，前缀由调用方指定）。 */
export function containerNodeId(prefix: string) {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;
}

export function portTypeOf(node: WorkflowNode | undefined, portId: string, direction: "input" | "output"): PortType {
  if (!node) return "any";
  const typeDef = getNodeTypeDefFromNode(node);
  if (!typeDef) return "any";
  const ports = direction === "input" ? typeDef.inputs : getVisibleOutputs(typeDef, node.data?.config || {});
  return (ports.find((port) => port.id === portId)?.type || "any") as PortType;
}

export function portLabelOf(node: WorkflowNode | undefined, portId: string, direction: "input" | "output") {
  if (!node) return portId;
  const typeDef = getNodeTypeDefFromNode(node);
  if (!typeDef) return portId;
  const ports = direction === "input" ? typeDef.inputs : getVisibleOutputs(typeDef, node.data?.config || {});
  return ports.find((port) => port.id === portId)?.label || portId;
}

export function stripHandlePrefix(handle: string | null | undefined, prefix: string) {
  if (!handle) return "";
  return handle.startsWith(prefix) ? handle.slice(prefix.length) : handle;
}

export function toHandle(prefix: "in-" | "out-", portId: string) {
  return `${prefix}${portId}`;
}

function getGroupTypeDef(meta: WorkflowNode["data"]["groupMeta"]): NodeTypeDef {
  return {
    id: meta?.savedNodeTypeId || "group_inline",
    name: meta?.name || "组合",
    category: "group_node",
    description: "组合节点",
    icon: "Boxes",
    color: GROUP_NODE_COLOR,
    inputs: (meta?.inputMappings || []).map((item) => ({
      id: item.exposedPortId,
      label: item.exposedLabel,
      type: item.type,
    })),
    outputs: (meta?.outputMappings || []).filter((item) => item.enabled !== false).map((item) => ({
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

export function validateGroupSelection(nodes: WorkflowNode[], edges: WorkflowEdge[], selectedIds: string[]) {
  const ids = Array.from(new Set(selectedIds));
  if (ids.length < 2) {
    return { ok: false as const, reason: "至少选择两个节点才能组合" };
  }
  const selectedSet = new Set(ids);
  const selectedNodes = nodes.filter((node) => selectedSet.has(node.id));
  if (selectedNodes.some((node) => isGroupNodeData(node.data))) {
    return { ok: false as const, reason: "首版不支持组合节点嵌套组合" };
  }
  const relatedEdges = edges.filter((edge) => selectedSet.has(edge.source) || selectedSet.has(edge.target));
  const internalEdges = relatedEdges.filter((edge) => selectedSet.has(edge.source) && selectedSet.has(edge.target));
  if (internalEdges.length === 0) {
    return { ok: false as const, reason: "所选节点之间没有连线，无法组成组合" };
  }
  const adjacency = new Map<string, Set<string>>();
  ids.forEach((id) => adjacency.set(id, new Set()));
  internalEdges.forEach((edge) => {
    adjacency.get(edge.source)?.add(edge.target);
    adjacency.get(edge.target)?.add(edge.source);
  });
  const visited = new Set<string>();
  const queue = [ids[0]];
  while (queue.length > 0) {
    const current = queue.shift();
    if (!current || visited.has(current)) continue;
    visited.add(current);
    adjacency.get(current)?.forEach((next) => {
      if (!visited.has(next)) queue.push(next);
    });
  }
  if (visited.size !== ids.length) {
    return { ok: false as const, reason: "只允许将连通子图组合，当前选区中存在不连通节点" };
  }
  return { ok: true as const };
}

export function createGroupNodeData(definition: GroupWorkflowDefinition, options?: { name?: string; groupId?: string; savedNodeTypeId?: string }) {
  const name = options?.name || "组合";
  return {
    kind: "group" as const,
    nodeType: options?.savedNodeTypeId || "group_inline",
    label: name,
    config: {},
    status: "pending" as const,
    groupMeta: {
      ...definition,
      groupId: options?.groupId || groupNodeId(),
      name,
      savedNodeTypeId: options?.savedNodeTypeId,
    },
  };
}

export function buildGroupNode(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
  selectedIds: string[],
  options?: { name?: string }
): { nodes: WorkflowNode[]; edges: WorkflowEdge[]; groupNodeId: string; outputMappings: GroupOutputMapping[] } {
  const validation = validateGroupSelection(nodes, edges, selectedIds);
  if (!validation.ok) throw new Error(validation.reason);
  const selectedSet = new Set(selectedIds);
  const selectedNodes = nodes.filter((node) => selectedSet.has(node.id));
  const selectedEdges = edges.filter((edge) => selectedSet.has(edge.source) && selectedSet.has(edge.target));
  const incomingEdges = edges.filter((edge) => !selectedSet.has(edge.source) && selectedSet.has(edge.target));
  const outgoingEdges = edges.filter((edge) => selectedSet.has(edge.source) && !selectedSet.has(edge.target));

  const minX = Math.min(...selectedNodes.map((node) => node.position.x));
  const minY = Math.min(...selectedNodes.map((node) => node.position.y));
  const maxX = Math.max(...selectedNodes.map((node) => node.position.x));
  const maxY = Math.max(...selectedNodes.map((node) => node.position.y));

  const inputMap = new Map<string, GroupInputMapping>();
  incomingEdges.forEach((edge) => {
    const targetPortId = stripHandlePrefix(edge.targetHandle, "in-");
    const targetNode = nodes.find((node) => node.id === edge.target);
    const key = `${edge.target}:${targetPortId}`;
    if (!inputMap.has(key)) {
      inputMap.set(key, {
        exposedPortId: `gin_${inputMap.size + 1}`,
        exposedLabel: `${targetNode?.data?.label || edge.target} / ${portLabelOf(targetNode, targetPortId, "input")}`,
        targetNodeId: edge.target,
        targetPortId,
        type: portTypeOf(targetNode, targetPortId, "input"),
      });
    }
  });

  const outputMap = new Map<string, GroupOutputMapping>();
  outgoingEdges.forEach((edge) => {
    const sourcePortId = stripHandlePrefix(edge.sourceHandle, "out-");
    const sourceNode = nodes.find((node) => node.id === edge.source);
    const key = `${edge.source}:${sourcePortId}`;
    if (!outputMap.has(key)) {
      outputMap.set(key, {
        exposedPortId: `gout_${outputMap.size + 1}`,
        exposedLabel: `${sourceNode?.data?.label || edge.source} / ${portLabelOf(sourceNode, sourcePortId, "output")}`,
        internalNodeId: edge.source,
        internalPortId: sourcePortId,
        type: portTypeOf(sourceNode, sourcePortId, "output"),
        enabled: true,
      });
    }
  });

  const groupId = groupNodeId();
  const internalWorkflow = {
    nodes: clone(selectedNodes.map((node) => ({
      ...node,
      selected: false,
      position: { x: node.position.x - minX, y: node.position.y - minY },
    }))),
    edges: clone(selectedEdges.map((edge) => ({ ...edge, selected: false }))),
  };
  const outputMappings = Array.from(outputMap.values());
  const groupData = createGroupNodeData({
    version: 1,
    internalWorkflow,
    inputMappings: Array.from(inputMap.values()),
    outputMappings,
    layout: {
      memberPositionsRelativeToGroup: Object.fromEntries(selectedNodes.map((node) => [
        node.id,
        { x: node.position.x - minX, y: node.position.y - minY },
      ])),
    },
  }, { name: options?.name, groupId });
  const groupNode: WorkflowNode = {
    id: groupId,
    type: "workflow",
    position: { x: (minX + maxX) / 2, y: (minY + maxY) / 2 },
    selected: true,
    data: groupData,
  } as WorkflowNode;

  const remainingNodes = nodes.filter((node) => !selectedSet.has(node.id)).map((node) => ({ ...node, selected: false })) as WorkflowNode[];
  const remainingEdges = edges.filter((edge) => !selectedSet.has(edge.source) && !selectedSet.has(edge.target)) as WorkflowEdge[];
  const nextEdges: WorkflowEdge[] = [...remainingEdges];

  incomingEdges.forEach((edge) => {
    const mapping = Array.from(inputMap.values()).find((item) => item.targetNodeId === edge.target && item.targetPortId === stripHandlePrefix(edge.targetHandle, "in-"));
    if (!mapping) return;
    nextEdges.push({
      ...edge,
      id: `${edge.id || `${edge.source}-${groupId}-${mapping.exposedPortId}`}`,
      target: groupId,
      targetHandle: toHandle("in-", mapping.exposedPortId),
      selected: false,
    });
  });

  outgoingEdges.forEach((edge) => {
    const mapping = Array.from(outputMap.values()).find((item) => item.internalNodeId === edge.source && item.internalPortId === stripHandlePrefix(edge.sourceHandle, "out-"));
    if (!mapping || mapping.enabled === false) return;
    nextEdges.push({
      ...edge,
      id: `${edge.id || `${groupId}-${edge.target}-${mapping.exposedPortId}`}`,
      source: groupId,
      sourceHandle: toHandle("out-", mapping.exposedPortId),
      selected: false,
    });
  });

  return { nodes: [...remainingNodes, groupNode], edges: nextEdges, groupNodeId: groupId, outputMappings };
}

export function updateGroupOutputMappings(nodes: WorkflowNode[], edges: WorkflowEdge[], groupNodeId: string, outputMappings: GroupOutputMapping[]) {
  const groupNode = nodes.find((node) => node.id === groupNodeId);
  if (!groupNode?.data?.groupMeta) return { nodes, edges };
  const nextNodes = nodes.map((node) => node.id === groupNodeId
    ? {
      ...node,
      data: {
        ...node.data,
        groupMeta: {
          ...node.data.groupMeta,
          outputMappings,
        },
      },
    }
    : node) as WorkflowNode[];

  const untouchedEdges = edges.filter((edge) => edge.source !== groupNodeId);
  const passthroughEdges = edges.filter((edge) => edge.source === groupNodeId);
  const rebuiltEdges = passthroughEdges.filter((edge) => {
    const exposedPortId = stripHandlePrefix(edge.sourceHandle, "out-");
    return outputMappings.some((item) => item.exposedPortId === exposedPortId && item.enabled !== false);
  });
  return { nodes: nextNodes, edges: [...untouchedEdges, ...rebuiltEdges] };
}

export function ungroupNode(nodes: WorkflowNode[], edges: WorkflowEdge[], groupNodeId: string) {
  const groupNode = nodes.find((node) => node.id === groupNodeId);
  const meta = groupNode?.data?.groupMeta;
  if (!groupNode || !meta) throw new Error("未找到可解散的组合节点");
  const internalNodes = clone(meta.internalWorkflow.nodes).map((node) => ({
    ...node,
    selected: false,
    position: {
      x: groupNode.position.x + node.position.x,
      y: groupNode.position.y + node.position.y,
    },
  })) as WorkflowNode[];
  const internalEdges = clone(meta.internalWorkflow.edges).map((edge) => ({ ...edge, selected: false })) as WorkflowEdge[];
  const remainingNodes = nodes.filter((node) => node.id !== groupNodeId) as WorkflowNode[];
  const incomingEdges = edges.filter((edge) => edge.target === groupNodeId);
  const outgoingEdges = edges.filter((edge) => edge.source === groupNodeId);
  const unrelatedEdges = edges.filter((edge) => edge.source !== groupNodeId && edge.target !== groupNodeId) as WorkflowEdge[];
  const restoredEdges: WorkflowEdge[] = [...unrelatedEdges, ...internalEdges];

  incomingEdges.forEach((edge) => {
    const exposedPortId = stripHandlePrefix(edge.targetHandle, "in-");
    const mapping = meta.inputMappings.find((item) => item.exposedPortId === exposedPortId);
    if (!mapping) return;
    restoredEdges.push({
      ...edge,
      target: mapping.targetNodeId,
      targetHandle: toHandle("in-", mapping.targetPortId),
      selected: false,
    });
  });

  outgoingEdges.forEach((edge) => {
    const exposedPortId = stripHandlePrefix(edge.sourceHandle, "out-");
    const mapping = meta.outputMappings.find((item) => item.exposedPortId === exposedPortId);
    if (!mapping || mapping.enabled === false) return;
    restoredEdges.push({
      ...edge,
      source: mapping.internalNodeId,
      sourceHandle: toHandle("out-", mapping.internalPortId),
      selected: false,
    });
  });

  return { nodes: [...remainingNodes, ...internalNodes], edges: restoredEdges };
}

export function createNodeDataFromType(nodeType: NodeTypeDef) {
  if (nodeType.kind === "group" && nodeType.groupDefinition) {
    return createGroupNodeData(nodeType.groupDefinition, {
      name: nodeType.name,
      savedNodeTypeId: nodeType.id,
    });
  }
  const config = { ...(nodeType.defaultConfig || {}) };
  if (nodeType.id === "sentence_split") {
    if (config.split_sentence_ends === undefined && config.split_clause_breaks === undefined) {
      const legacy = config.split_by_punct;
      if (legacy !== undefined) {
        config.split_sentence_ends = !!legacy;
        config.split_clause_breaks = !!legacy;
      }
    }
  }
  return {
    nodeType: nodeType.id,
    label: nodeType.name,
    config,
    status: "pending" as const,
  };
}

export function groupNodeToNodeTypeConfig(node: WorkflowNode) {
  const meta = node.data?.groupMeta;
  if (!meta) throw new Error("当前节点不是组合节点");
  const typeDef = getGroupTypeDef(meta);
  return {
    id: "",
    name: meta.name || node.data.label || "组合节点",
    version: "1.0.0",
    category: "group_node",
    description: `${meta.name || node.data.label || "组合节点"}（组合节点）`,
    icon: "Boxes",
    color: GROUP_NODE_COLOR,
    inputs: typeDef.inputs,
    outputs: typeDef.outputs,
    defaultConfig: {},
    configFields: [],
    kind: "group" as const,
    groupDefinition: {
      version: meta.version,
      internalWorkflow: clone(meta.internalWorkflow),
      inputMappings: clone(meta.inputMappings),
      outputMappings: clone(meta.outputMappings),
      layout: clone(meta.layout || {}),
    },
  };
}

export function expandGroupNodesForExecution(workflow: Pick<Workflow, "nodes" | "edges">, options?: {
  targetGroupNodeId?: string;
  targetScope?: "node" | "downstream";
}) {
  const nodes = clone(workflow.nodes || []) as WorkflowNode[];
  const edges = clone(workflow.edges || []) as WorkflowEdge[];
  const groupNodes = nodes.filter((node) => isGroupNodeData(node.data));
  if (groupNodes.length === 0) {
    return {
      nodes,
      edges,
      targetNodeId: options?.targetGroupNodeId,
    };
  }

  const expandedNodes: WorkflowNode[] = [];
  const expandedEdges: WorkflowEdge[] = [];
  const edgeBucket = [...edges];
  const targetMap = new Map<string, string[]>();

  nodes.forEach((node) => {
    if (!isGroupNodeData(node.data)) {
      expandedNodes.push(node);
    }
  });

  groupNodes.forEach((groupNode) => {
    const meta = groupNode.data.groupMeta!;
    const prefix = `${groupNode.id}__`;
    const internalNodes = clone(meta.internalWorkflow.nodes).map((node) => ({
      ...node,
      id: `${prefix}${node.id}`,
      position: {
        x: groupNode.position.x + node.position.x,
        y: groupNode.position.y + node.position.y,
      },
      selected: false,
    })) as WorkflowNode[];
    expandedNodes.push(...internalNodes);

    const internalEdges = clone(meta.internalWorkflow.edges).map((edge) => ({
      ...edge,
      id: `${prefix}${edge.id || `${edge.source}-${edge.target}`}`,
      source: `${prefix}${edge.source}`,
      target: `${prefix}${edge.target}`,
      selected: false,
    })) as WorkflowEdge[];
    expandedEdges.push(...internalEdges);

    const incomingEdges = edgeBucket.filter((edge) => edge.target === groupNode.id);
    const outgoingEdges = edgeBucket.filter((edge) => edge.source === groupNode.id);
    const internalIncomingTargets = new Set<string>();

    incomingEdges.forEach((edge) => {
      const mapping = meta.inputMappings.find((item) => item.exposedPortId === stripHandlePrefix(edge.targetHandle, "in-"));
      if (!mapping) return;
      expandedEdges.push({
        ...edge,
        id: `${edge.id || `${edge.source}-${mapping.targetNodeId}`}`,
        target: `${prefix}${mapping.targetNodeId}`,
        targetHandle: toHandle("in-", mapping.targetPortId),
        selected: false,
      });
      internalIncomingTargets.add(mapping.targetNodeId);
    });

    outgoingEdges.forEach((edge) => {
      const mapping = meta.outputMappings.find((item) => item.exposedPortId === stripHandlePrefix(edge.sourceHandle, "out-"));
      if (!mapping || mapping.enabled === false) return;
      expandedEdges.push({
        ...edge,
        id: `${edge.id || `${mapping.internalNodeId}-${edge.target}`}`,
        source: `${prefix}${mapping.internalNodeId}`,
        sourceHandle: toHandle("out-", mapping.internalPortId),
        selected: false,
      });
    });

    if (options?.targetGroupNodeId === groupNode.id) {
      const incomingTargetSet = new Set(meta.inputMappings.map((item) => item.targetNodeId));
      const entryNodes = internalNodes.filter((node) => {
        const hasInternalIncoming = internalEdges.some((edge) => edge.target === node.id);
        return !hasInternalIncoming || incomingTargetSet.has(node.id.replace(prefix, ""));
      });
      targetMap.set(groupNode.id, entryNodes.map((node) => node.id));
    }
  });

  const unrelatedEdges = edgeBucket.filter((edge) => {
    const sourceGroup = groupNodes.some((node) => node.id === edge.source);
    const targetGroup = groupNodes.some((node) => node.id === edge.target);
    return !sourceGroup && !targetGroup;
  });
  expandedEdges.push(...unrelatedEdges);

  return {
    nodes: expandedNodes,
    edges: expandedEdges,
    targetNodeId: options?.targetGroupNodeId ? (targetMap.get(options.targetGroupNodeId)?.[0] || options.targetGroupNodeId) : undefined,
    targetNodeIds: options?.targetGroupNodeId ? (targetMap.get(options.targetGroupNodeId) || []) : [],
  };
}

export function deriveGroupCandidateOutputs(node: WorkflowNode): PortDef[] {
  const meta = node.data?.groupMeta;
  if (!meta) return [];
  return meta.outputMappings.map((item) => ({
    id: item.exposedPortId,
    label: item.exposedLabel,
    type: item.type,
  }));
}

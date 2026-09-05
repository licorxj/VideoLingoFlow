import {
  getNodeTypeDef,
  isContainerNodeData,
  type GroupInputMapping,
  type GroupOutputMapping,
  type LoopWorkflowDefinition,
  type WorkflowEdge,
  type WorkflowNode,
} from "./workflowTypes";
import {
  clone,
  containerNodeId,
  portLabelOf,
  portTypeOf,
  stripHandlePrefix,
  toHandle,
} from "./groupWorkflow";

/**
 * 循环容器（Foreach）的画布侧构建/解散逻辑。
 *
 * 与组合节点（group）同构：内部子图 + inputMappings/outputMappings 端口映射，
 * 差异在于循环额外记录 ``loopMeta.iterator`` —— 指明「当前迭代条目」注入到循环体
 * 内部哪个节点端口。执行时由后端在运行期展开（迭代次数取决于运行时数据），
 * 因此这里不需要 expandGroupNodesForExecution 那样的前端展开。
 */
const LOOP_ID_PREFIX = "loop";

export function validateLoopSelection(nodes: WorkflowNode[], edges: WorkflowEdge[], selectedIds: string[]) {
  const ids = Array.from(new Set(selectedIds));
  if (ids.length < 1) {
    return { ok: false as const, reason: "至少选择一个节点才能创建循环" };
  }
  const selectedSet = new Set(ids);
  const selectedNodes = nodes.filter((node) => selectedSet.has(node.id));
  if (selectedNodes.some((node) => isContainerNodeData(node.data))) {
    return { ok: false as const, reason: "不支持在循环体内嵌套组合节点或循环节点" };
  }
  const relatedEdges = edges.filter((edge) => selectedSet.has(edge.source) || selectedSet.has(edge.target));
  if (relatedEdges.length === 0) {
    return { ok: false as const, reason: "所选节点没有任何连线，无法作为循环体" };
  }
  if (ids.length > 1) {
    const internalEdges = relatedEdges.filter((edge) => selectedSet.has(edge.source) && selectedSet.has(edge.target));
    if (internalEdges.length === 0) {
      return { ok: false as const, reason: "所选节点之间没有连线，无法作为循环体" };
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
      return { ok: false as const, reason: "只允许将连通子图创建为循环，当前选区中存在不连通节点" };
    }
  }
  return { ok: true as const };
}

export function createLoopNodeData(
  definition: LoopWorkflowDefinition,
  options?: { name?: string; loopId?: string }
) {
  const name = options?.name || "循环";
  return {
    kind: "loop" as const,
    nodeType: "loop",
    label: name,
    config: { ...(getNodeTypeDef("loop")?.defaultConfig || {}) },
    status: "pending" as const,
    loopMeta: {
      ...definition,
      loopId: options?.loopId || containerNodeId(LOOP_ID_PREFIX),
      name,
    },
  };
}

export function buildLoopNode(
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
  selectedIds: string[],
  options?: { name?: string }
): {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  loopNodeId: string;
  outputMappings: GroupOutputMapping[];
} {
  const validation = validateLoopSelection(nodes, edges, selectedIds);
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
        exposedPortId: `lin_${inputMap.size + 1}`,
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
        exposedPortId: `lout_${outputMap.size + 1}`,
        exposedLabel: `${sourceNode?.data?.label || edge.source} / ${portLabelOf(sourceNode, sourcePortId, "output")}`,
        internalNodeId: edge.source,
        internalPortId: sourcePortId,
        type: portTypeOf(sourceNode, sourcePortId, "output"),
        enabled: true,
      });
    }
  });

  const inputMappings = Array.from(inputMap.values());
  // 迭代路由：优先选 json 类型的入口（迭代对象通常是列表/JSON），否则取第一个入口
  const iteratorMapping =
    inputMappings.find((item) => item.type === "json" || item.type === "list") || inputMappings[0];

  const loopId = containerNodeId(LOOP_ID_PREFIX);
  const internalWorkflow = {
    nodes: clone(selectedNodes.map((node) => ({
      ...node,
      selected: false,
      position: { x: node.position.x - minX, y: node.position.y - minY },
    }))),
    edges: clone(selectedEdges.map((edge) => ({ ...edge, selected: false }))),
  };
  const outputMappings = Array.from(outputMap.values());
  const loopNode: WorkflowNode = {
    id: loopId,
    type: "workflow",
    position: { x: (minX + maxX) / 2, y: (minY + maxY) / 2 },
    selected: true,
    data: createLoopNodeData({
      version: 1,
      internalWorkflow,
      inputMappings,
      outputMappings,
      layout: {
        memberPositionsRelativeToGroup: Object.fromEntries(selectedNodes.map((node) => [
          node.id,
          { x: node.position.x - minX, y: node.position.y - minY },
        ])),
      },
      iterator: iteratorMapping
        ? {
            exposedPortId: iteratorMapping.exposedPortId,
            targetNodeId: iteratorMapping.targetNodeId,
            targetPortId: iteratorMapping.targetPortId,
          }
        : undefined,
    }, { name: options?.name, loopId }),
  } as WorkflowNode;

  const remainingNodes = nodes.filter((node) => !selectedSet.has(node.id)).map((node) => ({ ...node, selected: false })) as WorkflowNode[];
  const remainingEdges = edges.filter((edge) => !selectedSet.has(edge.source) && !selectedSet.has(edge.target)) as WorkflowEdge[];
  const nextEdges: WorkflowEdge[] = [...remainingEdges];

  incomingEdges.forEach((edge) => {
    const mapping = inputMappings.find(
      (item) => item.targetNodeId === edge.target && item.targetPortId === stripHandlePrefix(edge.targetHandle, "in-")
    );
    if (!mapping) return;
    nextEdges.push({
      ...edge,
      id: `${edge.id || `${edge.source}-${loopId}-${mapping.exposedPortId}`}`,
      target: loopId,
      targetHandle: toHandle("in-", mapping.exposedPortId),
      selected: false,
    });
  });

  outgoingEdges.forEach((edge) => {
    const mapping = outputMappings.find(
      (item) => item.internalNodeId === edge.source && item.internalPortId === stripHandlePrefix(edge.sourceHandle, "out-")
    );
    if (!mapping || mapping.enabled === false) return;
    nextEdges.push({
      ...edge,
      id: `${edge.id || `${loopId}-${edge.target}-${mapping.exposedPortId}`}`,
      source: loopId,
      sourceHandle: toHandle("out-", mapping.exposedPortId),
      selected: false,
    });
  });

  return { nodes: [...remainingNodes, loopNode], edges: nextEdges, loopNodeId: loopId, outputMappings };
}

export function ungroupLoopNode(nodes: WorkflowNode[], edges: WorkflowEdge[], loopNodeId: string) {
  const loopNode = nodes.find((node) => node.id === loopNodeId);
  const meta = loopNode?.data?.loopMeta;
  if (!loopNode || !meta) throw new Error("未找到可解散的循环节点");
  const internalNodes = clone(meta.internalWorkflow.nodes).map((node) => ({
    ...node,
    selected: false,
    position: {
      x: loopNode.position.x + node.position.x,
      y: loopNode.position.y + node.position.y,
    },
  })) as WorkflowNode[];
  const internalEdges = clone(meta.internalWorkflow.edges).map((edge) => ({ ...edge, selected: false })) as WorkflowEdge[];
  const remainingNodes = nodes.filter((node) => node.id !== loopNodeId) as WorkflowNode[];
  const incomingEdges = edges.filter((edge) => edge.target === loopNodeId);
  const outgoingEdges = edges.filter((edge) => edge.source === loopNodeId);
  const unrelatedEdges = edges.filter((edge) => edge.source !== loopNodeId && edge.target !== loopNodeId) as WorkflowEdge[];
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

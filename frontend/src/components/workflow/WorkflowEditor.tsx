import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { useWorkflowStore } from "@/stores/workflowStore";
import { ReactFlow, Controls, ControlButton, Background, BackgroundVariant, BezierEdge, addEdge, useNodesState, useEdgesState } from "@xyflow/react";
import type { Connection, ReactFlowInstance, OnConnectStartParams, FinalConnectionState } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import {
  type GroupOutputMapping, type WorkflowNode, type WorkflowEdge, type Workflow, type NodeTypeDef,
  getNodeTypeDefFromNode, getNodeTypeDef, getVisibleOutputs, canConnect, findDownstreamCandidates,
  PORT_COLORS, isGroupNodeData, type DownstreamCandidate,
} from "@/lib/workflowTypes";
import WorkflowNodeComponent from "./WorkflowNode";
import NodePalette from "./NodePalette";
import ContextMenu from "./ContextMenu";
import QuickConnectMenu, { type QuickConnectRequest } from "./QuickConnectMenu";
import {
  Save, FolderOpen, Play, Trash2, RotateCcw, FileText, Loader2,
  Plus, Workflow as WorkflowIcon, Clock, CheckCircle2, Pause, Square, Copy,
  ChevronDown, ChevronUp, RefreshCw, Eye, Crosshair, LocateFixed, X, Share2, Layers3, Group, Ungroup, Settings2, CornerDownRight, Spline, Minus,
} from "lucide-react";
import client from "@/api/client";
import { TaskMonitor } from "@/api/taskMonitor";
import { getWebSocketUrl } from "@/api/ws";
import { restoreLocalControlSession, saveControlWorkflow, type RevisionConflictError } from "@/api/controlPlane";
import { packWorkflow, publishPackage, type PublishResult } from "@/api/community";
import SharePackDialog, { type SharePackFields } from "@/components/community/SharePackDialog";
import { captureWorkflowCanvas } from "@/lib/snapshot";
import { buildGroupNode, createNodeDataFromType, expandGroupNodesForExecution, groupNodeToNodeTypeConfig, ungroupNode, updateGroupOutputMappings } from "@/lib/groupWorkflow";
import { useProjectStore } from "@/stores/projectStore";
import { useControlStore } from "@/stores/controlStore";
import { getSubscriptionError, isDeviceLimitError, isSubscriptionBlocked, getQuotaExhaustedMessage } from "@/api/subscription";
import { useSubscriptionStore } from "@/stores/subscriptionStore";
import ExecutionModeModal, { type ExecutionMode } from "./ExecutionModeModal";
import { createNodeType } from "@/api/nodeTypes";

const nodeTypes = { workflow: WorkflowNodeComponent };
const edgeTypes = { bezier: BezierEdge };
let nodeIdCounter = 0;
const getNextId = () => "node_" + (++nodeIdCounter) + "_" + Date.now();

const EDGE_TYPES = [
  { value: "smoothstep", label: "圆角直角线", description: "转折处使用圆角连接", icon: CornerDownRight },
  { value: "bezier", label: "贝塞尔曲线", description: "平滑弯曲的连接线", icon: Spline },
  { value: "straight", label: "直线", description: "节点间的最短直连", icon: Minus },
] as const;

type EdgeType = typeof EDGE_TYPES[number]["value"];

/**
 * 确保节点数组每个元素都有 position（React Flow 必需字段），
 * 缺失时按网格铺排默认位置，避免 setNodes 读取 node.position.x 崩溃。
 */
function ensureNodePositions(nodes: any[]): any[] {
  return (nodes || []).map((n: any, index: number) =>
    n && typeof n?.position === "object" && n.position
      ? n
      : { ...(n || {}), position: { x: 80 + (index % 8) * 260, y: 80 + Math.floor(index / 8) * 160 } }
  );
}

/** 从鼠标/触摸事件中取屏幕坐标（React Flow 的连线回调给的是原生事件） */
function getEventClientPoint(event: MouseEvent | TouchEvent): { x: number; y: number } | null {
  if (!event) return null;
  if ("touches" in event || "changedTouches" in event) {
    const touch = (event as TouchEvent).changedTouches?.[0] || (event as TouchEvent).touches?.[0];
    return touch ? { x: touch.clientX, y: touch.clientY } : null;
  }
  const mouse = event as MouseEvent;
  return { x: mouse.clientX, y: mouse.clientY };
}

function runtimeStatus(status: string | undefined) {
  return status === "succeeded" ? "completed" : status || "pending";
}

function projectGroupRuntimeState(node: any, taskNodes: Record<string, any>) {
  const meta = node.data?.groupMeta;
  if (!meta?.internalWorkflow?.nodes) return node;
  const prefix = `${node.id}__`;
  const members = meta.internalWorkflow.nodes.map((member: any) => {
    const runtime = taskNodes[`${prefix}${member.id}`];
    if (!runtime) return member;
    return {
      ...member,
      data: {
        ...member.data,
        status: runtimeStatus(runtime.status),
        progress: runtime.progress || 0,
        message: runtime.message || "",
        outputs: runtime.outputs || {},
        error: runtime.error || "",
      },
    };
  });
  const statuses = members.map((member: any) => member.data?.status || "pending");
  const failedMember = members.find((member: any) => member.data?.status === "failed");
  const runningMember = members.find((member: any) => ["running", "streaming", "waiting"].includes(member.data?.status));
  const allTerminal = statuses.length > 0 && statuses.every((status: string) => ["completed", "skipped", "cancelled"].includes(status));
  const status = failedMember ? "failed" : runningMember ? (runningMember.data.status === "waiting" ? "waiting" : "running") : allTerminal ? "completed" : "pending";
  const outputs: Record<string, any> = {};
  (meta.outputMappings || []).filter((mapping: any) => mapping.enabled !== false).forEach((mapping: any) => {
    const member = members.find((item: any) => item.id === mapping.internalNodeId);
    const value = member?.data?.outputs?.[mapping.internalPortId];
    if (value !== undefined && value !== null && value !== "") outputs[mapping.exposedPortId] = value;
  });
  const progress = members.length ? Math.round(members.reduce((sum: number, member: any) => sum + (Number(member.data?.progress) || 0), 0) / members.length) : 0;
  const activeMember = failedMember || runningMember;
  return {
    ...node,
    data: {
      ...node.data,
      status,
      progress: status === "completed" ? 100 : progress,
      message: activeMember?.data?.message || "",
      outputs,
      error: failedMember?.data?.error || "",
      groupMeta: { ...meta, internalWorkflow: { ...meta.internalWorkflow, nodes: members } },
    },
  };
}

interface SavedWorkflow {
  id: string;
  name: string;
  description: string;
  nodeCount: number;
  edgeCount: number;
  nodeTypes?: Record<string, number>;
  groupId?: string;
  updatedAt: string;
}

// 节点类型 id -> 中文显示名（用于卡片悬停详情）
const NODE_TYPE_LABELS: Record<string, string> = {
  input: "输入",
  video_preview: "视频预览",
  image_preview: "图片预览",
  image_compare: "图片对比",
  s02_asr: "语音识别",
    asr_recognize: "ASR识别",
    asr_postprocess: "ASR后处理",
  s03_sentence_split: "断句",
  s05_translate: "翻译",
  s06_subtitle_gen: "字幕生成",
  s07_subtitle_align: "字幕对齐",
  s08_dub_task: "配音任务",
  s09_tts: "语音合成",
  s10_merge_audio: "音频合并",
  s16_vocal_separation: "人声分离",
  path_to_title: "路径转标题",
  image_gen: "封面生成",
  publish: "发布",
  cutia: "剪辑",
  s_resolve_path: "路径解析",
  s_file_rename: "文件重命名",
  s_sentence_preprocess: "句预处理",
};
const nodeTypeLabel = (id: string) => NODE_TYPE_LABELS[id] || id;

// 分组标签：全部 / 未分组 / 各分组。分组标签右上角带删除键；compact 用于顶栏紧凑模式
function GroupTab({ label, active, onClick, count, onDelete, compact }: {
  label: string;
  active: boolean;
  onClick: () => void;
  count?: number;
  onDelete?: () => void;
  compact?: boolean;
}) {
  return (
    <div className="relative flex-shrink-0 group/tab">
      <button
        onClick={onClick}
        className={cn(
          "flex items-center border transition-all rounded-md",
          compact ? "gap-1 px-2 py-px text-sm font-semibold" : "gap-1.5 px-3 py-1 rounded-full text-xs font-semibold",
          active
            ? "bg-primary text-primary-foreground border-primary shadow-sm"
            : "bg-background text-muted-foreground border-border hover:text-foreground hover:border-primary/40 hover:bg-secondary"
        )}
      >
        <span className={cn("truncate", compact ? "max-w-[80px]" : "max-w-[120px]")}>{label}</span>
        {typeof count === "number" && (
          <span className={cn(
            "rounded-full leading-none",
            compact ? "px-1 py-px text-[8px]" : "px-1 py-0.5 text-[9px]",
            active ? "bg-primary-foreground/20 text-primary-foreground" : "bg-secondary text-muted-foreground"
          )}>{count}</span>
        )}
      </button>
      {onDelete && (
        <button
          onClick={(e) => { e.stopPropagation(); onDelete(); }}
          className="absolute -top-1.5 -right-1.5 w-4 h-4 flex items-center justify-center rounded-full bg-destructive text-destructive-foreground border border-background opacity-0 group-hover/tab:opacity-100 hover:scale-110 transition-all"
          title={"删除分组"}
        >
          <X className="w-2.5 h-2.5" />
        </button>
      )}
    </div>
  );
}

interface Props { workflowId?: string; taskId?: string; onExecute?: (wf: Workflow) => void; }

export default function WorkflowEditor({ workflowId, taskId, onExecute }: Props) {
  const store = useWorkflowStore();
  const currentProjectId = useProjectStore((state) => state.currentProjectId);
  const TERMINAL_TASK_STATUSES = ["completed", "succeeded", "failed", "cancelled"];
  const TERMINAL_NODE_STATUSES = ["completed", "failed", "cancelled"];
  const [nodes, setNodes, onNodesChange] = useNodesState<any>(store.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<any>(store.edges);

  // Sync nodes/edges back to store using refs to avoid infinite loops
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  useEffect(() => { nodesRef.current = nodes; }, [nodes]);
  useEffect(() => { edgesRef.current = edges; }, [edges]);
  // Sync to store only on unmount (for tab switch persistence)
  useEffect(() => {
    return () => {
      store.setNodes(nodesRef.current);
      store.setEdges(edgesRef.current);
    };
  }, []);
  const workflowName = store.workflowName;
  const workflowDesc = store.workflowDesc;
  const currentWfId = store.currentWfId;
  // 协作编辑状态上报（无在线光标，仅广播"正在编辑哪个工作流"）
  const setEditing = useControlStore((state) => state.setEditing);
  useEffect(() => {
    if (currentProjectId && currentWfId && currentWfId !== "new") {
      setEditing({ project_id: currentProjectId, workflow_key: currentWfId });
    } else {
      setEditing(null);
    }
    return () => setEditing(null, true);
  }, [currentProjectId, currentWfId, setEditing]);
  const taskMode = store.taskMode;
  const taskModeId = store.taskModeId;
  const [saving, setSaving] = useState(false);
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [reactFlowInstance, setReactFlowInstance] = useState<ReactFlowInstance<any, any> | null>(null);
  const reactFlowInstanceRef = useRef<ReactFlowInstance<any, any> | null>(null);
  // 右键菜单点选节点后的“粘附光标”放置模式：节点跟随鼠标，再次点击落入画布
  const [placingNode, setPlacingNode] = useState<NodeTypeDef | null>(null);
  const [placingPos, setPlacingPos] = useState({ x: 0, y: 0 });
  const [savedWorkflows, setSavedWorkflows] = useState<SavedWorkflow[]>([]);
  const [loadingList, setLoadingList] = useState(false);
  const [execModeModalOpen, setExecModeModalOpen] = useState(false);
  const [saveAsModalOpen, setSaveAsModalOpen] = useState(false);
  const [saveAsName, setSaveAsName] = useState("");
  const [saveAsDesc, setSaveAsDesc] = useState("");
  const [packOpen, setPackOpen] = useState(false);
  const [paletteCollapsed, setPaletteCollapsed] = useState(false);
  const [contextMenu, setContextMenu] = useState<{ visible: boolean; position: { x: number; y: number } }>({ visible: false, position: { x: 0, y: 0 } });
  const [wfListCollapsed, setWfListCollapsed] = useState(false);
  const [hoveredWf, setHoveredWf] = useState<SavedWorkflow | null>(null);
  const [groupConfigOpen, setGroupConfigOpen] = useState(false);
  const [groupConfigTargetId, setGroupConfigTargetId] = useState<string | null>(null);
  const [groupDraftName, setGroupDraftName] = useState("组合");
  const [groupSaveNodeId, setGroupSaveNodeId] = useState("");
  const [groupDraftOutputs, setGroupDraftOutputs] = useState<GroupOutputMapping[]>([]);
  const [groupSaveLoading, setGroupSaveLoading] = useState(false);
  const [canvasSettingsOpen, setCanvasSettingsOpen] = useState(false);
  const [edgeType, setEdgeType] = useState<EdgeType>("bezier");

  // 工作流分组（独立于 workflow 定义的分组索引表）
  const [groups, setGroups] = useState<{ id: string; name: string; order: number }[]>([]);
  const [activeGroup, setActiveGroup] = useState<string>("all"); // all | ungrouped | <groupId>
  const [groupModalOpen, setGroupModalOpen] = useState(false);
  const [newGroupName, setNewGroupName] = useState("");
  const [deleteGroupTarget, setDeleteGroupTarget] = useState<{ id: string; name: string } | null>(null);
  const [deleteGroupAction, setDeleteGroupAction] = useState<"delete" | "dissolve" | null>(null);
  const [groupBusy, setGroupBusy] = useState(false);
  const [moveTarget, setMoveTarget] = useState<SavedWorkflow | null>(null); // 待分配分组的工作流

  const ensureTaskAllowed = useCallback(async () => {
    const status = await useSubscriptionStore.getState().fetchStatus();
    if (status && !status.can_create_task) {
      alert(getQuotaExhaustedMessage(status));
      return false;
    }
    return true;
  }, []);

  const handleSubscriptionError = useCallback((err: any) => {
    if (!isSubscriptionBlocked(err)) return false;
    if (isDeviceLimitError(err)) {
      alert(`${getSubscriptionError(err)}\n请前往“用户和订阅”页面查看当前已绑定设备数。`);
      return true;
    }
    const status = useSubscriptionStore.getState().status;
    alert(getQuotaExhaustedMessage(status));
    return true;
  }, []);

  // 连线随机颜色
  const EDGE_COLORS = ["#6366f1", "#22d3ee", "#a78bfa", "#34d399", "#fb923c", "#f472b6", "#60a5fa", "#facc15"];
  const randomEdgeColor = useCallback(() => EDGE_COLORS[Math.floor(Math.random() * EDGE_COLORS.length)], []);

  // 自动适配视角：缩放画布使全部节点可见并居中（与工具栏适配视图按钮同效），
  // 用 ref 读取实例避免异步回调闭包捕获旧值；延迟等待节点渲染测量完成
  const fitViewToAll = useCallback((delay = 120) => {
    window.setTimeout(() => {
      reactFlowInstanceRef.current?.fitView({ padding: 0.15, duration: 300 });
    }, delay);
  }, []);

  const fetchWorkflows = useCallback(async () => {
    setLoadingList(true);
    try {
      let res;
      try {
        res = await client.get("/api/workflows");
      } catch (error: any) {
        if (Number(error?.status ?? error?.response?.status ?? 0) !== 401) throw error;
        const user = await restoreLocalControlSession();
        if (!user) throw error;
        res = await client.get("/api/workflows");
      }
      setSavedWorkflows(res.data?.workflows || []);
      setGroups(res.data?.groups || []);
    } catch (err) {
      console.error("Failed to load workflows:", err);
    }
    setLoadingList(false);
  }, []);

  // 分组操作
  const createGroup = useCallback(async (name: string) => {
    setGroupBusy(true);
    try {
      await client.post("/api/workflows/groups", { name });
      await fetchWorkflows();
    } catch (err) {
      console.error("Failed to create group:", err);
      alert("创建分组失败：" + (err as any)?.response?.data?.detail || err);
    }
    setGroupBusy(false);
    setGroupModalOpen(false);
    setNewGroupName("");
  }, [fetchWorkflows]);

  const confirmDeleteGroup = useCallback(async () => {
    if (!deleteGroupTarget || !deleteGroupAction) return;
    setGroupBusy(true);
    try {
      await client.delete(`/api/workflows/groups/${deleteGroupTarget.id}?action=${deleteGroupAction}`);
      // 若当前选中该分组，重置为全部
      if (activeGroup === deleteGroupTarget.id) setActiveGroup("all");
      await fetchWorkflows();
    } catch (err) {
      console.error("Failed to delete group:", err);
      alert("操作失败：" + (err as any)?.response?.data?.detail || err);
    }
    setGroupBusy(false);
    setDeleteGroupTarget(null);
    setDeleteGroupAction(null);
  }, [deleteGroupTarget, deleteGroupAction, activeGroup, fetchWorkflows]);

  // 将某工作流移动到指定分组（groupId 为空表示移回未分组）
  const moveWorkflowToGroup = useCallback(async (workflowId: string, groupId: string | null) => {
    try {
      await client.put("/api/workflows/groups/membership", { workflow_id: workflowId, group_id: groupId });
      await fetchWorkflows();
    } catch (err) {
      console.error("Failed to move workflow:", err);
      alert("移动失败：" + (err as any)?.response?.data?.detail || err);
    }
    setMoveTarget(null);
  }, [fetchWorkflows]);

  // Save current workflow ID to localStorage
  const saveCurrentId = useCallback((id: string | undefined) => {
    if (id) localStorage.setItem("vl_current_workflow", id);
    else localStorage.removeItem("vl_current_workflow");
  }, []);

  const deleteWorkflow = useCallback(async (wfId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm("确定要删除这个工作流吗？\n将同时删除该工作流对应的全部历史任务及其任务文件夹（运行中的任务除外）。")) return;
    try {
      await client.delete(`/api/workflows/${wfId}`);
      // 删除成功后，先刷新列表再检查
      await fetchWorkflows();
      // 检查是否是当前打开的工作流
      const currentId = store.currentWfId;
      if (currentId === wfId) {
        store.setCurrentWfId(undefined);
        store.setWorkflowName("");
        store.setWorkflowDesc("");
        saveCurrentId(undefined);
        setNodes([]);
        setEdges([]);
      }
    } catch (err) {
      console.error("Failed to delete workflow:", err);
    }
  }, [fetchWorkflows, saveCurrentId, store, setNodes, setEdges]);

  useEffect(() => { fetchWorkflows(); }, [fetchWorkflows]);

  // Load task workflow from task folder
  useEffect(() => {
    if (taskId) {
      store.setTaskMode(true);
      store.setTaskMode(true, taskId);
      setActiveTaskId(taskId);
      client.get("/api/tasks/" + taskId).then((res) => {
        const task = res.data?.task;
        if (task) {
          store.setBatchTask(!!task.is_batch);
          // 调试任务（工作流编排的固定任务）：以全局工作流模式加载画布，
          // 不显示为"一般任务"；activeTaskId 仍指向该调试任务，执行/节点执行写回同一任务。
          if (task.is_debug) {
            store.setTaskMode(false);
          }
          // Load workflow from task folder
          const wfPath = "/api/tasks/" + taskId + "/workflow";
          client.get(wfPath).then((wfRes) => {
            const wf = wfRes.data?.workflow;
            if (wf) {
              store.setWorkflowName(wf.name || task.id);
              store.setWorkflowDesc(wf.description || "");
              // 绑定任务所属工作流 id：任务模式下的执行/新建任务执行复用同一工作流
              if (wf.id && wf.id !== "new") {
                store.setCurrentWfId(wf.id);
              }
              // Merge task.json status/outputs/error into workflow nodes
              const taskNodes = task.nodes || {};
              const mergedNodes = (wf.nodes || []).map((n: any) => {
                const tn = taskNodes[n.id];
                if (tn) {
                  return {
                    ...n,
                    data: {
                      ...n.data,
                      status: tn.status || n.data?.status || "pending",
                      progress: tn.progress || 0,
                      message: tn.message || "",
                      outputs: tn.outputs || {},
                      error: tn.error || "",
                      workbench_url: tn.workbench_url || "",
                    },
                  };
                }
                return n;
              });
              setNodes(mergedNodes);
              setEdges(wf.edges || []);
              // 载入任务工作流后自动适配视角：缩放显示全部并居中
              fitViewToAll();
            }
          }).catch(() => {
            // Fallback: try to load from task.json nodes/edges
            if (task.nodes) {
              const wfNodes = Object.entries(task.nodes).map(([nid, info]: any) => ({
                id: nid,
                type: "workflow",
                data: { nodeType: info.nodeType, label: info.label, config: {}, status: info.status, outputs: info.outputs || {}, error: info.error || "" },
              }));
              setNodes(ensureNodePositions(wfNodes));
            }
            if (task.edges) setEdges(task.edges);
            fitViewToAll();
          });
        }
      }).catch(console.error);
    } else if (store.nodes.length === 0) {
      // First visit in this session: restore from localStorage
      const savedId = localStorage.getItem("vl_current_workflow");
      if (savedId) {
        loadWorkflow(savedId);
      }
    }
  }, [taskId]);

  // Load a saved workflow
  const loadWorkflow = useCallback(async (wfId: string) => {
    try {
      const res = await client.get("/api/workflows/" + wfId);
      const wf = res.data?.workflow;
      if (wf) {
        store.setTaskMode(false);
        store.setWorkflowName(wf.name || "\u672a\u547d\u540d");
        store.setWorkflowDesc(wf.description || "");
        store.setCurrentWfId(wf.id);
        setActiveTaskId(undefined);
        setTaskOutputs({});
        saveCurrentId(wf.id);
        setNodes(wf.nodes || []);
        setEdges(wf.edges || []);
        // 载入工作流后自动适配视角：缩放显示全部并居中
        fitViewToAll();

        // Warn if some edges were dropped by port mismatch normalization
        const removedEdges = Array.isArray(res.data?.removed_edges)
          ? res.data.removed_edges.length
          : (res.data?.removed_edges || 0);
        if (removedEdges > 0) {
          console.warn(`部分连线因端口不匹配被移除（${removedEdges} 条）`);
        }

        // 全局工作流绑定固定调试任务：获取（无则创建）该工作流的固定 taskid 并接管其状态，
        // 后续调试执行写回该任务，不再每次新建浪费磁盘。
        // 注意：这里保持 taskMode=false（全局编辑语义，保存写全局 json），
        // 仅把 activeTaskId 指向固定调试任务，使执行/节点执行固定到该任务边界内。
        try {
          // POST + body 传画布快照，避免把全量画布塞进 URL query（超长 URL 会 414）
          const debugRes = await client.post("/api/workflows/" + wfId + "/debug-task", {
            nodes: wf.nodes || [],
            edges: wf.edges || [],
          });
          const debugTaskId = debugRes.data?.task_id;
          if (debugTaskId) {
            setActiveTaskId(debugTaskId);
            const statusRes = await client.get("/api/workflows/" + wfId + "/status");
            const taskInfo = statusRes.data?.task;
            if (taskInfo?.id) {
              const nodeStatuses = taskInfo.nodes || {};
              setNodes((nds) =>
                nds.map((n: any) => {
                  const ns = nodeStatuses[n.id];
                  if (ns) {
                    return {
                      ...n,
                      data: {
                        ...n.data,
                        status: ns.status || n.data?.status || "pending",
                        progress: ns.progress || n.data?.progress || 0,
                        message: ns.message || n.data?.message || "",
                        outputs: ns.outputs || n.data?.outputs || {},
                        error: ns.error || n.data?.error || "",
                        workbench_url: ns.workbench_url || n.data?.workbench_url || "",
                      },
                    };
                  }
                  return n;
                })
              );
            }
          }
        } catch (e) {
          console.log("No debug task status found for workflow");
        }
      }
    } catch (err) {
      console.error("Failed to load workflow:", err);
    }
  }, [setNodes, setEdges, saveCurrentId, fitViewToAll]);

  // 新建工作流时默认放入的输入节点：落在当前视口中央，便于从它向右继续连线
  const createDefaultInputNode = useCallback((): WorkflowNode | null => {
    const def = getNodeTypeDef("input");
    if (!def) return null;
    const NODE_WIDTH = 420;
    const rect = reactFlowWrapper.current?.getBoundingClientRect();
    const instance = reactFlowInstanceRef.current;
    const center = instance && rect
      ? instance.screenToFlowPosition({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 })
      : { x: 120, y: 120 };
    return {
      id: getNextId(),
      type: "workflow",
      position: { x: Math.round(center.x - NODE_WIDTH / 2), y: Math.round(center.y - 120) },
      data: createNodeDataFromType(def),
    };
  }, []);

  // Create new workflow（默认带一个输入节点）
  const createNew = useCallback(() => {
    store.setWorkflowName("\u672a\u547d\u540d\u5de5\u4f5c\u6d41");
    store.setWorkflowDesc("");
    store.setCurrentWfId(undefined);
    store.setTaskMode(false);
    store.setTaskMode(false);
    setActiveTaskId(undefined);
    setTaskOutputs({});
    saveCurrentId(undefined);
    nodeIdCounter = 0;
    const inputNode = createDefaultInputNode();
    setNodes(inputNode ? [inputNode] : []);
    setEdges([]);
  }, [setNodes, setEdges, createDefaultInputNode]);

  const onConnect = useCallback((connection: Connection) => {
    if (!connection.source || !connection.target) return;
    const sourceNode = nodes.find((n) => n.id === connection.source);
    const targetNode = nodes.find((n) => n.id === connection.target);
    if (!sourceNode || !targetNode) return;
    const srcType = getNodeTypeDefFromNode(sourceNode as any);
    const tgtType = getNodeTypeDefFromNode(targetNode as any);
    if (!srcType || !tgtType) return;
    const srcPort = srcType.outputs.find((p) => p.id === (connection.sourceHandle || "").replace("out-", ""));
    const tgtPort = tgtType.inputs.find((p) => p.id === (connection.targetHandle || "").replace("in-", ""));
    if (!srcPort || !tgtPort) return;
    if (!canConnect(srcPort.type, tgtPort.type)) return;
    setEdges((eds) => addEdge({ ...connection, type: edgeType, animated: true, style: { stroke: randomEdgeColor(), strokeWidth: 2 } }, eds));
  }, [edgeType, nodes, setEdges]);

  // ============ 输出端点拖出连线：松手时弹出可接入的下游节点 ============
  const connectStartRef = useRef<{ nodeId: string | null; handleId: string | null; handleType: string | null; x: number; y: number } | null>(null);
  const [quickConnect, setQuickConnect] = useState<QuickConnectRequest | null>(null);

  const onConnectStart = useCallback((event: MouseEvent | TouchEvent, params: OnConnectStartParams) => {
    const point = getEventClientPoint(event);
    connectStartRef.current = {
      nodeId: params.nodeId,
      handleId: params.handleId,
      handleType: params.handleType,
      x: point?.x ?? 0,
      y: point?.y ?? 0,
    };
  }, []);

  const onConnectEnd = useCallback((event: MouseEvent | TouchEvent, state: FinalConnectionState) => {
    const start = connectStartRef.current;
    connectStartRef.current = null;
    // 仅在"从输出端点拖出且没有连上目标端点"时弹窗
    if (!start || start.handleType !== "source" || !start.nodeId) return;
    if (state?.isValid) return;
    const point = getEventClientPoint(event);
    if (!point) return;
    // 只是点了一下端点（没有真正拖动）不弹窗
    if (Math.abs(point.x - start.x) + Math.abs(point.y - start.y) < 20) return;

    const sourceNode = nodesRef.current.find((n: any) => n.id === start.nodeId);
    if (!sourceNode) return;
    const srcTypeDef = getNodeTypeDefFromNode(sourceNode as any);
    if (!srcTypeDef) return;
    const outputs = getVisibleOutputs(srcTypeDef, (sourceNode.data as any)?.config || {});
    const srcPort = outputs.find((p) => "out-" + p.id === start.handleId)
      || srcTypeDef.outputs.find((p) => "out-" + p.id === start.handleId);
    if (!srcPort) return;

    setQuickConnect({
      screen: point,
      sourceNodeId: start.nodeId,
      sourceNodeName: (sourceNode.data as any)?.label || srcTypeDef.name,
      sourceHandle: start.handleId || "",
      sourcePortLabel: srcPort.label,
      sourcePortType: srcPort.type,
      candidates: findDownstreamCandidates(srcPort.type),
    });
  }, []);

  /** 选中候选节点：在松手位置放入节点并完成连线 */
  const handleQuickConnectSelect = useCallback((candidate: DownstreamCandidate) => {
    if (!quickConnect) return;
    const id = getNextId();
    const instance = reactFlowInstanceRef.current;
    // 节点左上角落在松手位置（上移一点，避免遮住连线终点）
    const position = instance
      ? instance.screenToFlowPosition({ x: quickConnect.screen.x, y: Math.max(0, quickConnect.screen.y - 16) })
      : { x: quickConnect.screen.x, y: quickConnect.screen.y };
    setNodes((nds) => [
      ...nds,
      { id, type: "workflow", position, selected: false, data: createNodeDataFromType(candidate.nodeType) },
    ]);
    setEdges((eds) => addEdge({
      source: quickConnect.sourceNodeId,
      sourceHandle: quickConnect.sourceHandle,
      target: id,
      targetHandle: "in-" + candidate.port.id,
      type: edgeType,
      animated: true,
      style: { stroke: randomEdgeColor(), strokeWidth: 2 },
    }, eds));
    setQuickConnect(null);
  }, [quickConnect, edgeType, setNodes, setEdges, randomEdgeColor]);

  const handleEdgeTypeChange = useCallback((nextType: EdgeType) => {
    setEdgeType(nextType);
    setEdges((eds) => eds.map((edge: any) => ({ ...edge, type: nextType })));
  }, [setEdges]);

  const onDragOver = useCallback((e: React.DragEvent) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; }, []);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const data = e.dataTransfer.getData("application/reactflow");
    if (!data || !reactFlowInstance) return;
    const nodeType: NodeTypeDef = JSON.parse(data);
    // v12 的 screenToFlowPosition 直接接收屏幕坐标；节点 position 以左上角为锚点，
    // 因此落点即节点左上角落在鼠标处
    const position = reactFlowInstance.screenToFlowPosition({ x: e.clientX, y: e.clientY });
    setNodes((nds) => [...nds, { id: getNextId(), type: "workflow", position, data: createNodeDataFromType(nodeType) }]);
  }, [reactFlowInstance, setNodes]);

  const addNodeAtCenter = useCallback((nodeType: NodeTypeDef) => {
    const vp = reactFlowInstance ? reactFlowInstance.getViewport() : { x: 0, y: 0, zoom: 1 };
    const cx = (reactFlowWrapper.current?.clientWidth || 600) / 2 / (vp.zoom || 1) - (vp.x || 0);
    const cy = (reactFlowWrapper.current?.clientHeight || 400) / 2 / (vp.zoom || 1) - (vp.y || 0);
    setNodes((nds) => [...nds, { id: getNextId(), type: "workflow", position: { x: cx, y: cy }, data: createNodeDataFromType(nodeType) }]);
  }, [reactFlowInstance, setNodes]);

  const addNodeAtPosition = useCallback((nodeType: NodeTypeDef, screenX: number, screenY: number) => {
    if (!reactFlowInstance) return;
    // 直接传屏幕坐标（clientX/clientY），节点左上角落在鼠标点
    const position = reactFlowInstance.screenToFlowPosition({ x: screenX, y: screenY });
    setNodes((nds) => [...nds, { id: getNextId(), type: "workflow", position, data: createNodeDataFromType(nodeType) }]);
  }, [reactFlowInstance, setNodes]);

  // “粘附光标”放置模式：跟随鼠标移动，在画布内点击左键落下节点，Esc/右键取消
  useEffect(() => {
    if (!placingNode) return;
    const handleMove = (e: MouseEvent) => setPlacingPos({ x: e.clientX, y: e.clientY });
    const handleDown = (e: MouseEvent) => {
      if (e.button !== 0) return;
      const bounds = reactFlowWrapper.current?.getBoundingClientRect();
      if (bounds && e.clientX >= bounds.left && e.clientX <= bounds.right && e.clientY >= bounds.top && e.clientY <= bounds.bottom) {
        addNodeAtPosition(placingNode, e.clientX, e.clientY);
        setPlacingNode(null);
      }
    };
    const handleKey = (e: KeyboardEvent) => { if (e.key === "Escape") setPlacingNode(null); };
    const handleCtx = (e: MouseEvent) => { e.preventDefault(); setPlacingNode(null); };
    document.addEventListener("mousemove", handleMove);
    document.addEventListener("keydown", handleKey);
    document.addEventListener("contextmenu", handleCtx, true);
    // 延迟注册 mousedown，避免选中节点的那次点击立即触发落下
    let cleanupDown: (() => void) | null = null;
    const armTimer = window.setTimeout(() => {
      document.addEventListener("mousedown", handleDown, true);
      cleanupDown = () => document.removeEventListener("mousedown", handleDown, true);
    }, 0);
    return () => {
      window.clearTimeout(armTimer);
      cleanupDown?.();
      document.removeEventListener("mousemove", handleMove);
      document.removeEventListener("keydown", handleKey);
      document.removeEventListener("contextmenu", handleCtx, true);
    };
  }, [placingNode, addNodeAtPosition]);

  const handleCanvasContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setContextMenu({ visible: true, position: { x: e.clientX, y: e.clientY } });
  }, []);

  const deleteSelected = useCallback(() => {
    setNodes((nds) => nds.filter((n) => !n.selected));
    setEdges((eds) => eds.filter((e) => !e.selected));
  }, [setNodes, setEdges]);

  // 剪贴板：复制/粘贴节点
  const [clipboard, setClipboard] = useState<any[]>([]);
  const copySelected = useCallback(() => {
    const selected = nodes.filter((n) => n.selected);
    if (selected.length === 0) return;
    setClipboard(JSON.parse(JSON.stringify(selected)));
  }, [nodes]);
  const pasteClipboard = useCallback(() => {
    if (clipboard.length === 0) return;
    const idMap: Record<string, string> = {};
    const newNodes = clipboard.map((n) => {
      const newId = "n_" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
      idMap[n.id] = newId;
      return { ...n, id: newId, position: { x: n.position.x + 40, y: n.position.y + 40 }, selected: false };
    });
    setNodes((nds) => [...nds, ...newNodes]);
  }, [clipboard, setNodes]);
  const selectAll = useCallback(() => {
    setNodes((nds) => nds.map((n) => ({ ...n, selected: true })));
    setEdges((eds) => eds.map((e) => ({ ...e, selected: true })));
  }, [setNodes, setEdges]);

  const openGroupConfig = useCallback((groupNodeId: string) => {
    const groupNode = nodes.find((node: any) => node.id === groupNodeId);
    if (!groupNode?.data?.groupMeta) return;
    setGroupConfigTargetId(groupNodeId);
    setGroupDraftName(groupNode.data.groupMeta.name || groupNode.data.label || "组合");
    setGroupDraftOutputs(groupNode.data.groupMeta.outputMappings || []);
    setGroupConfigOpen(true);
  }, [nodes]);

  const handleGroupSelected = useCallback(() => {
    const selectedIds = nodes.filter((node: any) => node.selected).map((node: any) => node.id);
    try {
      const grouped = buildGroupNode(nodes as WorkflowNode[], edges as WorkflowEdge[], selectedIds);
      setNodes(grouped.nodes);
      setEdges(grouped.edges);
      openGroupConfig(grouped.groupNodeId);
    } catch (error) {
      alert(error instanceof Error ? error.message : "组合失败");
    }
  }, [edges, nodes, openGroupConfig, setEdges, setNodes]);

  const handleUngroupNode = useCallback((groupNodeId: string) => {
    try {
      const next = ungroupNode(nodes as WorkflowNode[], edges as WorkflowEdge[], groupNodeId);
      setNodes(next.nodes);
      setEdges(next.edges);
    } catch (error) {
      alert(error instanceof Error ? error.message : "解散组合失败");
    }
  }, [edges, nodes, setEdges, setNodes]);

  const handleSaveGroupAsNodeType = useCallback(async (groupNodeId: string) => {
    const groupNode = nodes.find((node: any) => node.id === groupNodeId) as WorkflowNode | undefined;
    if (!groupNode) return;
    const nodeName = groupDraftName.trim() || groupNode.data?.groupMeta?.name || groupNode.data?.label || "组合节点";
    const nodeId = groupSaveNodeId.trim() || `groupnode_${Date.now().toString(36)}`;
    if (!/^[A-Za-z0-9_-]+$/.test(nodeId)) {
      alert("组合节点 ID 仅支持字母、数字、_ 和 -");
      return;
    }
    try {
      setGroupSaveLoading(true);
      const outputMappings = groupDraftOutputs.map((item) => ({
        ...item,
        exposedLabel: item.exposedLabel.trim() || item.exposedPortId,
      }));
      const groupNodeForSave: WorkflowNode = {
        ...groupNode,
        data: {
          ...groupNode.data,
          label: nodeName,
          groupMeta: {
            ...groupNode.data.groupMeta,
            name: nodeName,
            outputMappings,
          } as NonNullable<WorkflowNode["data"]["groupMeta"]>,
        },
      };
      const payload = groupNodeToNodeTypeConfig(groupNodeForSave);
      payload.id = nodeId.trim();
      payload.name = nodeName.trim();
      payload.description = `${nodeName.trim()}（组合节点）`;
      await createNodeType(payload as any);
      setNodes((nds) => nds.map((node: any) => node.id === groupNodeId ? {
        ...node,
        data: {
          ...node.data,
          nodeType: payload.id,
          label: payload.name,
          groupMeta: {
            ...node.data.groupMeta,
            name: payload.name,
            savedNodeTypeId: payload.id,
          },
        },
      } : node));
      alert("组合节点已保存到节点库");
      setGroupSaveNodeId("");
    } catch (error: any) {
      alert(`保存组合节点失败：${error?.response?.data?.detail || error?.message || "未知错误"}`);
    } finally {
      setGroupSaveLoading(false);
    }
  }, [groupDraftName, groupDraftOutputs, groupSaveNodeId, nodes, setNodes]);

  const applyGroupConfigDraft = useCallback(() => {
    if (!groupConfigTargetId) return;
    const nextOutputs = groupDraftOutputs.map((item) => ({
      ...item,
      exposedLabel: item.exposedLabel.trim() || item.exposedPortId,
    }));
    setNodes((nds) => nds.map((node: any) => node.id === groupConfigTargetId ? {
      ...node,
      data: {
        ...node.data,
        label: groupDraftName.trim() || "组合",
        groupMeta: {
          ...node.data.groupMeta,
          name: groupDraftName.trim() || "组合",
          outputMappings: nextOutputs,
        },
      },
    } : node));
    const updated = updateGroupOutputMappings(nodes as WorkflowNode[], edges as WorkflowEdge[], groupConfigTargetId, nextOutputs);
    setEdges(updated.edges);
    setGroupConfigOpen(false);
    setGroupConfigTargetId(null);
  }, [edges, groupConfigTargetId, groupDraftName, groupDraftOutputs, nodes, setEdges, setNodes]);

  const collectDownstreamNodeIds = useCallback((startNodeId: string) => {
    const downstream = new Set<string>();
    const queue = [startNodeId];
    while (queue.length > 0) {
      const current = queue.shift();
      if (!current || downstream.has(current)) continue;
      downstream.add(current);
      edges.forEach((edge: any) => {
        if (edge.source === current && !downstream.has(edge.target)) {
          queue.push(edge.target);
        }
      });
    }
    return downstream;
  }, [edges]);

  const getWorkflowJSON = (): Workflow => ({
    id: currentWfId && currentWfId !== "new" ? currentWfId : undefined as any,
    name: workflowName, description: workflowDesc,
    nodes: nodes as WorkflowNode[], edges: edges as WorkflowEdge[],
    createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(),
  });

  const handleSave = async () => {
    setSaving(true);
    try {
      if (taskMode && taskModeId) {
        const wf = getWorkflowJSON();
        await client.put("/api/tasks/" + taskModeId + "/workflow", wf);
      } else {
        const wf = getWorkflowJSON();
        if (currentProjectId && currentWfId && currentWfId !== "new") {
          try {
            const saved = await saveControlWorkflow(currentProjectId, currentWfId, wf as unknown as Record<string, unknown>, workflowRevisionRef.current ?? 0);
            workflowRevisionRef.current = saved.revision;
          } catch (error) {
            const conflict = error as RevisionConflictError;
            if (conflict.code !== "revision_conflict") throw error;
            if (confirm("工作流已被其他成员修改。选择“确定”将刷新为服务器版本；选择“取消”可继续选择覆盖。")) {
              const definition = conflict.currentDefinition as Workflow | null;
              if (definition) {
                setNodes(ensureNodePositions(definition.nodes || []));
                setEdges(definition.edges || []);
              }
              workflowRevisionRef.current = conflict.actualRevision;
              return;
            }
            if (!confirm("确认覆盖其他成员的修改吗？")) return;
            const saved = await saveControlWorkflow(currentProjectId, currentWfId, wf as unknown as Record<string, unknown>, conflict.actualRevision, true);
            workflowRevisionRef.current = saved.revision;
          }
        } else if (currentWfId && currentWfId !== "new") {
          (wf as any).type = "user";
          await client.put("/api/workflows/" + currentWfId, wf);
        } else {
          (wf as any).type = "user";
          const res = await client.post("/api/workflows", wf);
          if (res.data?.id) {
            store.setCurrentWfId(res.data.id);
            saveCurrentId(res.data.id);
          }
        }
        fetchWorkflows();
      }
    } catch (err) {
      console.error("Save failed:", err);
    }
    setSaving(false);
  };

  // 全局快捷键
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      const isInput = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (e.target as HTMLElement).isContentEditable;
      if (isInput) return;
      const ctrl = e.ctrlKey || e.metaKey;
      if (e.key === "Delete" || e.key === "Backspace") { deleteSelected(); e.preventDefault(); }
      else if (ctrl && e.key.toLowerCase() === "g") { handleGroupSelected(); e.preventDefault(); }
      else if (ctrl && e.key === "c") { copySelected(); e.preventDefault(); }
      else if (ctrl && e.key === "v") { pasteClipboard(); e.preventDefault(); }
      else if (ctrl && e.shiftKey && e.key === "S") { setSaveAsModalOpen(true); e.preventDefault(); }
      else if (ctrl && e.key === "s") { handleSave(); e.preventDefault(); }
      else if (ctrl && e.key === "a") { selectAll(); e.preventDefault(); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [deleteSelected, handleGroupSelected, copySelected, pasteClipboard, handleSave, selectAll]);

  const handleSaveAs = async () => {
    setSaveAsName(workflowName || "未命名工作流");
    setSaveAsDesc(workflowDesc);
    setSaveAsModalOpen(true);
  };

  const confirmSaveAs = async () => {
    setSaving(true);
    try {
      let saveName = saveAsName.trim() || "未命名工作流";
      const saveDesc = saveAsDesc.trim();

      // Check for duplicate names
      const existingNames = savedWorkflows.map(w => w.name);
      if (existingNames.includes(saveName) && !(currentWfId && savedWorkflows.some(w => w.id === currentWfId && w.name === saveName))) {
        let baseName = saveName;
        let counter = 2;
        while (existingNames.includes(baseName + " (副本 " + counter + ")")) {
          counter++;
        }
        saveName = baseName + " (副本 " + counter + ")";
      }

      const wf = getWorkflowJSON();
      wf.name = saveName;
      wf.description = saveDesc;
      if (taskMode && taskModeId) {
        // 一般任务「另存为全局」：写入新的全局工作流，但保持当前任务编辑上下文不变
        const res = await client.post("/api/workflows/" + (currentWfId || wf.id || "new") + "/save-as-global", wf);
        const newId = res.data?.id;
        if (newId) {
          store.setWorkflowName(saveName);
          store.setWorkflowDesc(saveDesc);
          setSaveAsModalOpen(false);
          fetchWorkflows();
        }
        return;
      }
      delete (wf as any).id;  // Always create new workflow
      (wf as any).type = "user";  // Always save as public user workflow
      const res = await client.post("/api/workflows", wf);
      if (res.data?.id) {
        store.setCurrentWfId(res.data.id);
        saveCurrentId(res.data.id);
        store.setWorkflowName(saveName);
        store.setWorkflowDesc(saveDesc);
      }
      fetchWorkflows();
      setSaveAsModalOpen(false);
    } catch (err) {
      console.error("Save As failed:", err);
    }
    setSaving(false);
  };

  const [executing, setExecuting] = useState(false);
  const [executingNode, setExecutingNode] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [taskOutputs, setTaskOutputs] = useState<Record<string, any>>({});
  const [activeTaskId, setActiveTaskId] = useState<string | undefined>(taskId);
  const [trackEnabled, setTrackEnabled] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const taskMonitorRef = useRef<TaskMonitor<any> | null>(null);
  const workflowRevisionRef = useRef<number | null>(null);

  // 运行跟踪：开启时把画布聚焦到目标节点（运行中 > 报错 > 最后一个已完成）
  useEffect(() => {
    if (!trackEnabled || !reactFlowInstance) return;
    const rfNodes = reactFlowInstance.getNodes();
    if (rfNodes.length === 0) return;
    const runningNodes = rfNodes.filter((n: any) => n.data?.status === "running" || n.data?.status === "streaming");
    const failedNodes = rfNodes.filter((n: any) => n.data?.status === "failed");
    const completedNodes = rfNodes.filter((n: any) => n.data?.status === "completed");

    let target: any = null;
    if (runningNodes.length > 0) {
      target = runningNodes.find((n: any) => n.id === executingNode) || runningNodes[0];
    } else if (failedNodes.length > 0) {
      target = failedNodes[failedNodes.length - 1];
    } else if (completedNodes.length > 0) {
      target = completedNodes[completedNodes.length - 1];
    }
    if (!target) return;

    const w = target.measured?.width || target.width || 420;
    const h = target.measured?.height || target.height || 160;
    reactFlowInstance.setCenter(
      target.position.x + w / 2,
      target.position.y + h / 2,
      { zoom: Math.max(reactFlowInstance.getZoom(), 1), duration: 600 }
    );
  }, [trackEnabled, nodes, edges, executingNode, reactFlowInstance]);

  useEffect(() => {
    setActiveTaskId(taskId);
  }, [taskId]);

  // 同步 activeTaskId 到全局 store，供预览节点（视频/图片预览器）定位任务工作区解析相对产物路径
  useEffect(() => {
    store.setActiveTaskId(activeTaskId);
  }, [activeTaskId]);

  const syncTaskStateToNodes = useCallback((task: any) => {
    if (!task?.nodes) return;
    const outputs: Record<string, any> = {};
    setNodes((nds) => nds.map((n: any) => {
      if (isGroupNodeData(n.data)) {
        const projected = projectGroupRuntimeState(n, task.nodes);
        if (Object.keys(projected.data?.outputs || {}).length > 0) outputs[n.id] = { outputs: projected.data.outputs };
        return projected;
      }
      const ninfo = task.nodes?.[n.id];
      if (!ninfo) return n;
      if (ninfo.outputs && Object.keys(ninfo.outputs).length > 0) {
        outputs[n.id] = ninfo;
      }
      const status = ninfo.status === "succeeded" ? "completed" : ninfo.status;
      return {
        ...n,
        data: {
          ...n.data,
          status: status || "pending",
          // Preserve real-time WebSocket progress when the backend also shows "running"
          // but task.json has a stale/zero progress value. Intermediate progress (e.g. 30, 50, 70)
          // is only sent via WebSocket, not persisted to task.json, so task.json may lag behind.
          // When status is completed/failed/cancelled, always use backend values (authoritative).
          progress: (status === "running" && (ninfo.progress || 0) < (n.data?.progress || 0))
            ? n.data.progress
            : (ninfo.progress || 0),
          message: ninfo.message || "",
          outputs: ninfo.outputs || {},
          error: ninfo.error || "",
        },
      };
    }));
    setTaskOutputs(outputs);
  }, [setNodes]);

  const fetchTaskState = useCallback(async (nextTaskId: string) => {
    const res = await client.get("/api/tasks/" + nextTaskId);
    const task = res.data?.task;
    if (task) {
      setActiveTaskId(nextTaskId);
      syncTaskStateToNodes(task);
      if (TERMINAL_TASK_STATUSES.includes(task.status)) {
        setExecuting(false);
        setExecutingNode(null);
        setCancelling(false);
      }
    }
    return task;
  }, [syncTaskStateToNodes]);

  // Use refs so monitorWorkflowTask doesn't depend on these callbacks,
  // preventing unnecessary WebSocket reconnections when nodes update.
  const fetchTaskStateRef = useRef(fetchTaskState);
  fetchTaskStateRef.current = fetchTaskState;
  const syncTaskStateToNodesRef = useRef(syncTaskStateToNodes);
  syncTaskStateToNodesRef.current = syncTaskStateToNodes;

  const resetExecutionDisplay = useCallback((options?: { clearTaskId?: boolean }) => {
    taskMonitorRef.current?.stop();
    taskMonitorRef.current = null;
    wsRef.current?.close();
    wsRef.current = null;
    setExecutingNode(null);
    setTaskOutputs({});
    if (options?.clearTaskId) {
      setActiveTaskId(undefined);
    }
    setNodes((nds) => nds.map((n: any) => ({
      ...n,
      data: {
        ...n.data,
        status: "pending",
        progress: 0,
        message: "",
        outputs: {},
        error: "",
      },
    })));
  }, [setNodes]);

  useEffect(() => () => taskMonitorRef.current?.stop(), []);

  const hasRunningNodes = nodes.some((n: any) => n.data?.status === "running" || n.data?.status === "streaming");
  const totalNodeCount = nodes.length;
  const completedNodeCount = nodes.filter((n: any) => n.data?.status === "completed").length;
  const workflowProgress = totalNodeCount > 0 ? Math.round((completedNodeCount / totalNodeCount) * 100) : 0;
  const showWorkflowProgress = executing || !!executingNode || cancelling || hasRunningNodes;

  // 连线颜色：基于接口类型 + 运行状态叠加
  const styledEdges = useMemo(() => {
    return edges.map((e: any) => {
      const srcNode = nodes.find((n: any) => n.id === e.source);
      const tgtNode = nodes.find((n: any) => n.id === e.target);
      const srcStatus = srcNode?.data?.status || "pending";
      const tgtStatus = tgtNode?.data?.status || "pending";

      // 根据源端口类型获取颜色
      const srcNodeType = getNodeTypeDefFromNode(srcNode as any);
      const srcPort = srcNodeType?.outputs?.find((p) => p.id === (e.sourceHandle || "").replace("out-", ""));
      const portType = srcPort?.type || "any";
      let color = PORT_COLORS[portType] || "#6b7280";

      // 运行状态叠加：运行中节点（源或目标）的连线变玫红并流动，失败变红
      const isRunningEdge = srcStatus === "running" || tgtStatus === "running";
      if (srcStatus === "failed" || tgtStatus === "failed") color = "#ef4444";
      else if (isRunningEdge) color = "#ff0099";
      else if (srcStatus === "completed" && tgtStatus === "completed") color = color; // 保持接口颜色

      const animated = isRunningEdge || e.selected;
      return { ...e, style: { ...e.style, stroke: color, strokeDasharray: animated ? undefined : "6 3" }, animated };
    });
  }, [edges, nodes]);

  const handleCancelExecution = async () => {
    const targetTaskId = activeTaskId || taskModeId;
    // 没有taskId或任务不在运行中时，直接重置节点状态
    if (!targetTaskId || (!executing && !executingNode)) {
      setNodes((nds) => nds.map((n: any) =>
        n.data?.status === "running" || n.data?.status === "streaming"
          ? { ...n, data: { ...n.data, status: "pending", progress: 0, message: "", error: "" } }
          : n
      ));
      setExecutingNode(null);
      setExecuting(false);
      setCancelling(false);
      return;
    }
    if (!confirm("确认停止当前执行中的任务吗？")) return;
    setCancelling(true);
    setNodes((nds) => nds.map((n: any) =>
      n.data?.status === "running"
        ? { ...n, data: { ...n.data, message: "正在停止..." } }
        : n
    ));
    try {
      await client.post(`/api/tasks/${targetTaskId}/cancel`);
      await fetchTaskState(targetTaskId).catch(() => {});
    } catch (err) {
      console.error("Cancel failed:", err);
      setCancelling(false);
    }
  };

  const handleExecute = async () => {
    if (nodes.length === 0) return;
    setExecModeModalOpen(true);
  };

  const hasCompletedSteps = nodes.some((n: any) => n.data?.status === "completed");

  const monitorWorkflowTask = useCallback((taskId: string) => {
    taskMonitorRef.current?.stop();
    const monitor = new TaskMonitor<any>({
      taskId,
      fetchTask: async (id, signal) => (await client.get(`/api/tasks/${id}`, { signal })).data?.task,
      isTerminal: (task) => TERMINAL_TASK_STATUSES.includes(task.status),
      onTask: (task) => {
        setActiveTaskId(taskId);
        syncTaskStateToNodesRef.current(task);
        if (TERMINAL_TASK_STATUSES.includes(task.status)) {
          setExecuting(false);
          setExecutingNode(null);
          setCancelling(false);
        }
      },
      onEvent: (data: any) => {
        const stepId = typeof data.node_id === "string"
          ? data.node_id
          : typeof data.step_id === "string"
            ? data.step_id
            : typeof data.node === "string" ? data.node : "";
        const progress = typeof data.progress === "number" ? data.progress : 0;
        const message = typeof data.message === "string" ? data.message : "";
        if (stepId === "__task__") return;

        // node_log 事件：子进程转发的调试日志，追加到节点 logLines（独立于 message）
        if (data.event_type === "node_log" && stepId) {
          setNodes((nds) => nds.map((node: any) => {
            if (isGroupNodeData(node.data)) return node;
            if (node.id !== stepId) return node;
            const prevLines: string[] = Array.isArray((node.data as any)?.logLines) ? (node.data as any).logLines : [];
            const nextLines = [...prevLines, message].slice(-8); // 保留最后 8 行
            return { ...node, data: { ...node.data, logLines: nextLines } };
          }));
          return;
        }

        setNodes((nds) => {
          const taskNodes = {
            [stepId]: {
              status: data.status || (progress === -1 ? "failed" : progress >= 100 ? "succeeded" : progress > 0 ? "running" : "pending"),
              progress: Math.max(0, progress),
              message: progress === -1 && message.startsWith("ERROR: ") ? message.slice(7) : message,
              outputs: data.outputs?.outputs || data.outputs || {},
              error: typeof data.error === "string" ? data.error : progress === -1 ? message : "",
            },
          };
          return nds.map((node: any) => {
            if (isGroupNodeData(node.data)) return projectGroupRuntimeState(node, taskNodes);
            if (node.id !== stepId) return node;
            const ninfo = taskNodes[stepId];
            // 空消息不覆盖已有消息（避免进度文字一闪而过）
            const keepMessage = ninfo.message || (node.data as any)?.message || "";
            return { ...node, data: { ...node.data, status: runtimeStatus(ninfo.status), progress: ninfo.progress, message: keepMessage, outputs: ninfo.outputs, error: ninfo.error } };
          });
        });
      },
    });
    taskMonitorRef.current = monitor;
    monitor.start();
  }, [setNodes]);

  const handleExecuteNode = async (nodeId: string) => {
    const node = nodes.find((n: any) => n.id === nodeId);
    if (!node) return;

    // Check input dependencies - find edges that connect TO this node
    const incomingEdges = edges.filter((e: any) => e.target === nodeId);
    const missingInputs: string[] = [];

    for (const edge of incomingEdges) {
      const sourceNode = nodes.find((n: any) => n.id === edge.source);
      // 跳过孤儿边（源节点已被删除）
      if (!sourceNode) continue;
      if (!sourceNode.data?.outputs || Object.keys(sourceNode.data.outputs).length === 0) {
        if (sourceNode.data?.nodeType !== "input") {
          missingInputs.push(sourceNode.data?.label || edge.source);
        }
      }
    }

    if (missingInputs.length > 0) {
      alert(`以下上游节点的输出尚未准备好，请先执行：\n${missingInputs.join("\n")}`);
      return;
    }

    if (!(await ensureTaskAllowed())) return;

    let wfId = currentWfId;
    if (!wfId) {
      const wf = getWorkflowJSON();
      (wf as any).type = taskMode ? "task" : "user";
      const res = await client.post("/api/workflows", wf);
      wfId = res.data?.id;
      if (wfId) store.setCurrentWfId(wfId);
    }

    setExecutingNode(nodeId);

    setNodes((nds) => nds.map((n: any) =>
      n.id === nodeId
        ? { ...n, data: { ...n.data, status: "running", progress: 0, message: "Starting...", outputs: {}, error: "" } }
        : n
    ));

    try {
      // Use reactFlowInstance to get the latest nodes (includes unsaved config changes)
      const latestNodes = reactFlowInstance ? reactFlowInstance.getNodes() : nodes;
      const latestEdges = reactFlowInstance ? reactFlowInstance.getEdges() : edges;
      const isGroup = isGroupNodeData(node.data);
      const expanded = expandGroupNodesForExecution({ nodes: latestNodes as WorkflowNode[], edges: latestEdges as WorkflowEdge[] }, { targetGroupNodeId: nodeId, targetScope: "node" });
      const inputNode = latestNodes.find((n: any) => n.data?.nodeType === "input");
      const inputConfig = inputNode?.data?.config || {};

      const res = await client.post(`/api/workflows/${wfId}/execute-node`, {
        nodes: expanded.nodes,
        edges: expanded.edges,
        input: inputConfig,
        task_id: activeTaskId || taskModeId || "",
        node_id: isGroup ? nodeId : (expanded.targetNodeId || nodeId),
        scope: isGroup ? "group" : "node",
      });

      const taskId = res.data?.task_id;
      if (taskId) {
        setActiveTaskId(taskId);
        monitorWorkflowTask(taskId);
      }
    } catch (err) {
      setExecutingNode(null);
      if (handleSubscriptionError(err)) return;
      alert("执行失败: " + (err as Error).message);
    }
  };

  const handleExecuteFromNode = async (nodeId: string) => {
    if (!(await ensureTaskAllowed())) return;

    let wfId = currentWfId;
    if (!wfId) {
      const wf = getWorkflowJSON();
      (wf as any).type = taskMode ? "task" : "user";
      const res = await client.post("/api/workflows", wf);
      wfId = res.data?.id;
      if (wfId) store.setCurrentWfId(wfId);
    }

    const downstreamIds = collectDownstreamNodeIds(nodeId);
    setExecuting(true);
    setCancelling(false);
    setTaskOutputs({});
    setNodes((nds) => nds.map((n: any) =>
      downstreamIds.has(n.id)
        ? { ...n, data: { ...n.data, status: n.id === nodeId ? "running" : "pending", progress: 0, message: n.id === nodeId ? "Starting..." : "等待重新执行", outputs: {}, error: "" } }
        : n
    ));

    try {
      const latestNodes = reactFlowInstance ? reactFlowInstance.getNodes() : nodes;
      const latestEdges = reactFlowInstance ? reactFlowInstance.getEdges() : edges;
      const selectedNode = latestNodes.find((item: any) => item.id === nodeId);
      const isGroup = isGroupNodeData(selectedNode?.data);
      const expanded = expandGroupNodesForExecution({ nodes: latestNodes as WorkflowNode[], edges: latestEdges as WorkflowEdge[] }, { targetGroupNodeId: nodeId, targetScope: "downstream" });
      const inputNode = latestNodes.find((n: any) => n.data?.nodeType === "input");
      const inputConfig = inputNode?.data?.config || {};
      const res = await client.post(`/api/workflows/${wfId}/execute-node`, {
        nodes: expanded.nodes,
        edges: expanded.edges,
        input: inputConfig,
        task_id: activeTaskId || taskModeId || "",
        node_id: isGroup ? nodeId : (expanded.targetNodeId || nodeId),
        run_downstream: !isGroup,
        scope: isGroup ? "group_downstream" : "downstream",
      });

      const nextTaskId = res.data?.task_id;
      if (nextTaskId) {
        setActiveTaskId(nextTaskId);
        monitorWorkflowTask(nextTaskId);
      }
    } catch (err) {
      console.error("Execute from node failed:", err);
      setExecuting(false);
      setCancelling(false);
      handleSubscriptionError(err);
    }
  };

  const handleExecuteWithMode = async (mode: ExecutionMode) => {
    setExecModeModalOpen(false);
    // Use reactFlowInstance to get the latest nodes (includes unsaved config changes)
    const latestNodes = reactFlowInstance ? reactFlowInstance.getNodes() : nodes;
    const latestEdges = reactFlowInstance ? reactFlowInstance.getEdges() : edges;
    const expanded = expandGroupNodesForExecution({ nodes: latestNodes as WorkflowNode[], edges: latestEdges as WorkflowEdge[] });
    if (latestNodes.length === 0) return;

    if (!(await ensureTaskAllowed())) return;

    // Find input node config
    const inputNode = latestNodes.find((n: any) => n.data?.nodeType === "input");
    const inputConfig = inputNode?.data?.config || {};

    // Save workflow first if not saved
    let wfId = currentWfId;
    if (!wfId) {
      const wf = getWorkflowJSON();
      (wf as any).type = taskMode ? "task" : "user";
      const res = await client.post("/api/workflows", wf);
      wfId = res.data?.id;
      if (wfId) store.setCurrentWfId(wfId);
    }

    if (mode === "new") {
      // 新建任务执行：后端会创建 detached 一般任务并投递（全局调试任务保留）
      setExecuting(true);
      setCancelling(false);
      resetExecutionDisplay({ clearTaskId: true });
      try {
        const res = await client.post("/api/workflows/" + wfId + "/execute", {
          nodes: expanded.nodes, edges: expanded.edges, input: inputConfig, mode: "new",
          task_id: activeTaskId || taskModeId || "",
        });
        const newTaskId = res.data?.task_id;
        if (newTaskId) {
          window.history.pushState({}, "", "/?task=" + newTaskId);
          store.setTaskMode(true, newTaskId);
          setActiveTaskId(newTaskId);
          monitorWorkflowTask(newTaskId);
        }
      } catch (err) {
        console.error("New task creation failed:", err);
        setExecuting(false);
        setCancelling(false);
        handleSubscriptionError(err);
      }
      return;
    }

    // For resume/restart: execute on the current task (固定调试任务或一般任务)
    setExecuting(true);
    setCancelling(false);
    const previousTaskId = activeTaskId || taskModeId || "";

    if (mode === "restart") {
      resetExecutionDisplay({ clearTaskId: false });
    } else {
      setTaskOutputs({});
    }

    try {
      // restart（从头执行）→ restart_clean：后端清空 cache 全新开始
      const backendMode = mode === "restart" ? "restart_clean" : mode;
      const executeBody: any = {
        nodes: expanded.nodes, edges: expanded.edges, input: inputConfig, mode: backendMode,
        task_id: previousTaskId,
      };
      const res = await client.post("/api/workflows/" + wfId + "/execute", executeBody);
      const taskId = res.data?.task_id;

      if (taskId) {
        setActiveTaskId(taskId);
        monitorWorkflowTask(taskId);
      }
    } catch (err) {
      console.error("Execute failed:", err);
      setExecuting(false);
      setCancelling(false);
      handleSubscriptionError(err);
    }
  };

  const handlePackSubmit = async (fields: SharePackFields, preview: File | null): Promise<PublishResult> => {
    const wf = getWorkflowJSON();
    const form = new FormData();
    form.append("workflow", JSON.stringify({ ...wf, name: fields.shareName, description: fields.description }));
    form.append("shareName", fields.shareName);
    form.append("description", fields.description);
    form.append("author", fields.author);
    form.append("category", fields.category);
    form.append("tags", JSON.stringify(fields.tags));
    if (preview) form.append("preview", preview);
    const packed = await packWorkflow(form);
    return publishPackage(packed.folder);
  };

  const handleClear = () => { setNodes([]); setEdges([]); nodeIdCounter = 0; };

  const formatTime = (iso: string) => {
    if (!iso) return "";
    const d = new Date(iso);
    return (d.getMonth() + 1) + "/" + d.getDate() + " " + d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  };


  // Map nodes to include onExecuteNode callback for React Flow
  // Use refs for callbacks to keep stable references and prevent unnecessary re-renders
  const handleExecuteNodeRef = useRef(handleExecuteNode);
  handleExecuteNodeRef.current = handleExecuteNode;
  const handleExecuteFromNodeRef = useRef(handleExecuteFromNode);
  handleExecuteFromNodeRef.current = handleExecuteFromNode;
  const handleUngroupNodeRef = useRef(handleUngroupNode);
  handleUngroupNodeRef.current = handleUngroupNode;
  const handleSaveGroupAsNodeTypeRef = useRef(handleSaveGroupAsNodeType);
  handleSaveGroupAsNodeTypeRef.current = handleSaveGroupAsNodeType;
  const openGroupConfigRef = useRef(openGroupConfig);
  openGroupConfigRef.current = openGroupConfig;
  const disableExecute = executing || !!executingNode || cancelling;
  const selectedNodeCount = nodes.filter((node: any) => node.selected).length;

  const flowNodes = nodes.map(n => ({
    ...n,
    // 兜底保证使用自定义节点组件（其头部顶栏带拖拽手柄类）
    type: n.type || "workflow",
    // 只有按住节点头部顶栏（.wf-node-drag-handle）才能拖动节点，
    // 避免正文内拖选文本、拖动控件时误移动节点
    dragHandle: ".wf-node-drag-handle",
    data: {
      ...n.data,
      onExecuteNode: (id: string) => handleExecuteNodeRef.current(id),
      onExecuteFromNode: (id: string) => handleExecuteFromNodeRef.current(id),
      onUngroupNode: (id: string) => handleUngroupNodeRef.current(id),
      onSaveAsGroupNode: (id: string) => handleSaveGroupAsNodeTypeRef.current(id),
      onEditGroupNode: (id: string) => openGroupConfigRef.current(id),
      disableExecute,
    }
  }));
  return (
    <div className="flex flex-col h-full animate-fade-in-up">
      {/* === Top: Saved Workflow Cards === */}
      <div className="border-b border-border bg-card flex-shrink-0">
        <div className="flex items-center gap-2 px-3 py-1.5 min-h-[38px] bg-secondary">
          <WorkflowIcon className="w-3.5 h-3.5 text-primary" />
          <span className="text-base font-bold text-muted-foreground">{"\u5df2\u4fdd\u5b58\u5de5\u4f5c\u6d41"}</span>
          <button
            onClick={createNew}
            className="ml-1 flex items-center gap-1 px-2 py-px text-sm font-semibold text-primary border border-primary/30 hover:bg-primary/10 rounded-md transition-colors"
          >
            <Plus className="w-3 h-3" />{"\u65b0\u5efa"}
          </button>
          <button
            onClick={fetchWorkflows}
            className="text-sm font-semibold text-foreground border border-border px-1.5 py-px rounded-md hover:bg-secondary transition-colors"
            title={"\u5237\u65b0"}
          >
            {loadingList ? <Loader2 className="w-3 h-3 animate-spin" /> : "\u5237\u65b0"}
          </button>
          {/* 分组标签栏：全部 / 未分组 / 各分组 / + （紧跟刷新按钮，紧凑横排） */}
          <div className="flex items-center gap-1 px-1 ml-1 max-w-[60%] overflow-x-auto">
            <GroupTab label={"全部"} active={activeGroup === "all"} onClick={() => setActiveGroup("all")} count={savedWorkflows.length} compact />
            <GroupTab label={"未分组"} active={activeGroup === "ungrouped"} onClick={() => setActiveGroup("ungrouped")} count={savedWorkflows.filter((w) => !w.groupId).length} compact />
            {groups.map((g) => (
              <GroupTab
                key={g.id}
                label={g.name}
                active={activeGroup === g.id}
                onClick={() => setActiveGroup(g.id)}
                count={savedWorkflows.filter((w) => w.groupId === g.id).length}
                onDelete={() => setDeleteGroupTarget({ id: g.id, name: g.name })}
                compact
              />
            ))}
            <button
              onClick={() => { setNewGroupName(""); setGroupModalOpen(true); }}
              className="flex items-center justify-center w-5 h-5 rounded-md border border-dashed border-border text-muted-foreground hover:text-primary hover:border-primary/40 hover:bg-primary/5 transition-all flex-shrink-0"
              title={"新建分组"}
            >
              <Plus className="w-3 h-3" />
            </button>
          </div>
          <button
            onClick={() => setWfListCollapsed((p) => !p)}
            className="ml-auto p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary/60 transition-colors"
            title={wfListCollapsed ? "展开工作流列表" : "折叠工作流列表"}
          >
            {wfListCollapsed ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronUp className="w-3.5 h-3.5" />}
          </button>
        </div>
        {!wfListCollapsed && (
          <>
          <div className="relative flex flex-wrap gap-2 px-3 pb-2 overflow-visible">
            {(() => {
              const filtered = savedWorkflows.filter((w) => {
                if (activeGroup === "all") return true;
                if (activeGroup === "ungrouped") return !w.groupId;
                return w.groupId === activeGroup;
              });
              if (filtered.length === 0 && !loadingList) {
                return <div className="text-xs text-muted-foreground/50 py-1">{"\u8be5\u5206\u7ec4\u6682\u65e0\u5de5\u4f5c\u6d41"}</div>;
              }
              return filtered.map((wf, wfIdx) => (
            <div key={wf.id} className="relative flex-shrink-0 w-52 group">
              <button
                onClick={() => loadWorkflow(wf.id)}
                className={cn(
                  "w-full h-[112px] p-3 rounded-2xl text-left transition-all duration-300 flex flex-col overflow-hidden",
                  "border bg-gradient-to-b from-card to-card/90",
                  "shadow-[0_1px_2px_rgba(0,0,0,0.06),0_4px_12px_rgba(0,0,0,0.08),inset_0_1px_0_rgba(255,255,255,0.6)]",
                  "hover:-translate-y-0.5 hover:shadow-[0_2px_4px_rgba(0,0,0,0.08),0_10px_24px_rgba(0,0,0,0.12),inset_0_1px_0_rgba(255,255,255,0.7)]",
                  "dark:shadow-[0_1px_2px_rgba(0,0,0,0.4),0_4px_12px_rgba(0,0,0,0.5),inset_0_1px_0_rgba(255,255,255,0.08)]",
                  "dark:hover:shadow-[0_2px_4px_rgba(0,0,0,0.5),0_10px_24px_rgba(0,0,0,0.6),inset_0_1px_0_rgba(255,255,255,0.1)]",
                  currentWfId === wf.id
                    ? "border-primary/60 ring-1 ring-primary/20"
                    : "border-border/70 hover:border-primary/40"
                )}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className="w-7 h-7 rounded-xl flex items-center justify-center bg-primary/10 flex-shrink-0 shadow-[inset_0_1px_0_rgba(255,255,255,0.5)]">
                    <FileText className="w-3.5 h-3.5 text-primary" />
                  </span>
                  <span className="text-sm font-bold truncate">{wf.name}</span>
                </div>
                {wf.description && (
                  <div className="mt-1.5 text-[10px] text-muted-foreground/80 line-clamp-2 leading-snug">{wf.description}</div>
                )}
                <div className="mt-auto flex items-center gap-1.5 flex-wrap">
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-semibold bg-sky-500/10 text-sky-600 dark:text-sky-400 border border-sky-400/20">
                    <span className="w-1 h-1 rounded-full bg-sky-500" />
                    {wf.nodeCount || 0} 节点
                  </span>
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-semibold bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-400/20 ml-auto">
                    <Clock className="w-2.5 h-2.5" />
                    {formatTime(wf.updatedAt)}
                  </span>
                </div>
              </button>

              {/* 悬停弹出：节点类型分布详情（向下弹出，避免被上方组件遮挡） */}
              {/* 首张卡片左对齐、末张右对齐，避免弹窗被两侧导航/边栏遮挡 */}
              <div className={cn(
                "pointer-events-none absolute top-full mt-2 z-40 w-80 origin-top scale-95 opacity-0 group-hover:scale-100 group-hover:opacity-100 transition-all duration-200 ease-out",
                wfIdx === 0
                  ? "left-0"
                  : wfIdx === filtered.length - 1
                    ? "right-0"
                    : "left-1/2 -translate-x-1/2"
              )}>
                <div className="rounded-2xl border border-border bg-popover/95 backdrop-blur-md p-3 shadow-[0_8px_30px_rgba(0,0,0,0.18)] ring-1 ring-black/5 dark:ring-white/10">
                  <div className="flex items-center gap-1.5 mb-2">
                    <FileText className="w-4 h-4 text-primary flex-shrink-0" />
                    <span className="text-sm font-bold truncate">{wf.name}</span>
                  </div>
                  {wf.description && (
                    <div className="text-sm text-foreground mb-2 leading-snug">{wf.description}</div>
                  )}
                  <div className="grid grid-cols-2 gap-1.5 text-xs">
                    <div className="flex items-center justify-between rounded-lg bg-sky-500/10 px-2 py-1">
                      <span className="text-muted-foreground">节点</span>
                      <span className="font-bold text-sky-600 dark:text-sky-400">{wf.nodeCount || 0}</span>
                    </div>
                    <div className="flex items-center justify-between rounded-lg bg-violet-500/10 px-2 py-1">
                      <span className="text-muted-foreground">连接</span>
                      <span className="font-bold text-violet-600 dark:text-violet-400">{wf.edgeCount || 0}</span>
                    </div>
                  </div>
                  {wf.nodeTypes && Object.keys(wf.nodeTypes).length > 0 && (
                    <div className="mt-2 pt-2 border-t border-border/50">
                      <div className="text-xs font-semibold text-foreground mb-1.5">节点构成</div>
                      <div className="flex flex-wrap gap-1">
                        {Object.entries(wf.nodeTypes)
                          .sort((a, b) => b[1] - a[1])
                          .map(([nt, cnt]) => (
                            <span key={nt} className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-xs font-medium bg-secondary/80 border border-border/50">
                              {nodeTypeLabel(nt)}
                              <span className="text-primary font-bold">×{cnt}</span>
                            </span>
                          ))}
                      </div>
                    </div>
                  )}
                  <div className="mt-2 pt-2 border-t border-border/50 flex items-center gap-1 text-xs text-foreground">
                    <Clock className="w-3 h-3" />
                    更新于 {formatTime(wf.updatedAt)}
                  </div>
                </div>
                {/* 小箭头（指向上方卡片），与弹窗对齐一致 */}
                <div className={cn(
                  "absolute bottom-full -mb-1 w-2 h-2 rotate-45 bg-popover border-l border-t border-border",
                  wfIdx === 0
                    ? "left-6 -translate-x-1/2"
                    : wfIdx === filtered.length - 1
                      ? "right-6 -translate-x-1/2"
                      : "left-1/2 -translate-x-1/2"
                )} />
              </div>

              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setHoveredWf(wf);
                }}
                className="absolute top-2 right-7 p-1 rounded-md opacity-0 group-hover:opacity-100 text-muted-foreground/50 hover:text-primary hover:bg-primary/10 transition-all duration-150"
                title="查看详情"
              >
                <Eye className="w-3 h-3" />
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setMoveTarget(wf);
                }}
                className="absolute top-2 right-12 p-1 rounded-md opacity-0 group-hover:opacity-100 text-muted-foreground/50 hover:text-primary hover:bg-primary/10 transition-all duration-150"
                title="移动到分组"
              >
                <FolderOpen className="w-3 h-3" />
              </button>
              <button
                onClick={(e) => deleteWorkflow(wf.id, e)}
                className="absolute top-2 right-2 p-1 rounded-md opacity-0 group-hover:opacity-100 text-muted-foreground/50 hover:text-destructive hover:bg-destructive/10 transition-all duration-150"
                title="删除工作流"
              >
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
              ));
              })()}
            </div>
          </>
          )}
      </div>

      {/* === Bottom: Canvas + Right Sidebar === */}
      <div className="flex-1 flex min-h-0">
        {/* Left: Canvas + Toolbar */}
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {/* Toolbar */}
          <div className="flex items-center gap-2 px-3 py-2 border-b border-border bg-secondary flex-shrink-0">
            {taskMode ? (
              <span className="text-[10px] font-medium text-cyan-600 bg-cyan-500/10 px-2 py-1 rounded-md border border-cyan-500/20 flex-shrink-0">
                {store.isBatchTask ? "批量任务" : "一般任务"}
              </span>
            ) : (
              <span className="text-[10px] font-medium text-amber-600 bg-amber-500/10 px-2 py-1 rounded-md border border-amber-500/20 flex-shrink-0">
                全局工作流
              </span>
            )}
            <input type="text" value={workflowName} onChange={(e) => store.setWorkflowName(e.target.value)}
              className="text-sm font-bold text-foreground bg-transparent border-2 border-muted-foreground/40 rounded-full hover:border-primary focus:border-primary outline-none transition-colors px-2 py-1 h-8 flex-1 min-w-0"
              placeholder={"\u5de5\u4f5c\u6d41\u540d\u79f0"} />
            <input type="text" value={workflowDesc} onChange={(e) => store.setWorkflowDesc(e.target.value)}
              className="text-sm text-foreground bg-transparent border-2 border-muted-foreground/40 rounded-full hover:border-primary focus:border-primary outline-none transition-colors px-2 py-1 h-8 flex-[2] min-w-0"
              placeholder={"\u63cf\u8ff0..."} />
            <div className="flex items-center gap-1 ml-auto flex-shrink-0">
              <Btn icon={RefreshCw} label={"刷新"} onClick={() => { if (currentWfId && currentWfId !== "new") loadWorkflow(currentWfId); }} />
              <Btn icon={Copy} label={"另存为"} onClick={handleSaveAs} loading={saving} />
<Btn icon={Save} label={"\u4fdd\u5b58"} onClick={handleSave} loading={saving} />
              <Btn icon={Share2} label={"分享"} onClick={() => {
                if (!currentWfId || currentWfId === "new") {
                  if (confirm("当前工作流尚未保存，建议先保存再分享，是否现在保存？")) handleSave();
                }
                setPackOpen(true);
              }} />
              <Btn icon={RotateCcw} label={"\u6e05\u7a7a"} onClick={handleClear} />
              <button
                onClick={handleGroupSelected}
                disabled={selectedNodeCount < 2}
                className="flex items-center gap-1 px-2.5 py-2 text-sm font-bold text-violet-700 border border-violet-400/40 bg-violet-500/10 rounded-lg hover:bg-violet-500/20 active:scale-[0.97] disabled:opacity-40 transition-all"
                title="选中节点后按 Ctrl+G 组合"
              >
                <Group className="w-3 h-3" /> 组合
              </button>
              <div className="w-px h-4 bg-border/40 mx-0.5" />
              <button onClick={handleExecute} disabled={nodes.length === 0 || executing || !!executingNode || cancelling}
                className="flex items-center gap-1 px-2.5 py-2 text-sm font-bold text-primary-foreground border border-primary/60 bg-primary rounded-lg hover:shadow-lg hover:shadow-primary/30 active:scale-[0.97] disabled:opacity-40 transition-all">
                {executing || !!executingNode || cancelling
                  ? <><Loader2 className="w-3 h-3 animate-spin" />{"运行中"}</>
                  : <><Play className="w-3 h-3" />{"执行"}</>}
              </button>
              <button
                onClick={handleCancelExecution}
                disabled={(!executing && !executingNode && !hasRunningNodes) || cancelling}
                className="flex items-center gap-1 px-2.5 py-2 text-sm font-bold text-red-600 border border-red-400 bg-red-500/10 rounded-lg hover:bg-red-500/20 active:scale-[0.97] disabled:opacity-40 transition-all"
              >
                {cancelling ? <Pause className="w-3 h-3" /> : <Square className="w-3 h-3" />} {cancelling ? "停止中" : "停止"}
              </button>
            </div>
          </div>

          {/* Canvas */}
          <div ref={reactFlowWrapper} className="flex-1 relative">
            <ReactFlow nodes={flowNodes} edges={styledEdges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
              onConnect={onConnect} onConnectStart={onConnectStart} onConnectEnd={onConnectEnd}
              onInit={(inst) => { reactFlowInstanceRef.current = inst; setReactFlowInstance(inst); }} onDragOver={onDragOver} onDrop={onDrop}
              onPaneContextMenu={(e) => { e.preventDefault(); setContextMenu({ visible: true, position: { x: e.clientX, y: e.clientY } }); }}
              nodeTypes={nodeTypes} edgeTypes={edgeTypes} fitView snapToGrid snapGrid={[15, 15]}
              selectionOnDrag selectionKeyCode="Shift" multiSelectionKeyCode="Shift"
              minZoom={0.05} maxZoom={4}
              defaultEdgeOptions={{ type: edgeType, animated: true, style: { stroke: "#6366f1", strokeWidth: 2 } }}
              proOptions={{ hideAttribution: true }}>
              <Controls style={{ top: 12, left: 0, right: "auto", bottom: "auto", transform: "none" }}>
                <ControlButton
                  onClick={() => setTrackEnabled((p) => !p)}
                  title={trackEnabled ? "关闭运行跟踪（自动定位节点）" : "开启运行跟踪（自动定位节点）"}
                  style={{ order: -1, color: trackEnabled ? "#ff0099" : undefined }}
                  className={trackEnabled ? "rf-track-active" : undefined}
                >
                  {trackEnabled ? <Crosshair className="w-3.5 h-3.5 animate-pulse" /> : <LocateFixed className="w-3.5 h-3.5" />}
                </ControlButton>
                <ControlButton onClick={() => setCanvasSettingsOpen(true)} title="画布设置与快捷键">
                  <Settings2 className="w-3.5 h-3.5" />
                </ControlButton>
              </Controls>
              <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="hsl(var(--border))" />
              {showWorkflowProgress && (
                <div className="absolute bottom-4 left-1/2 z-10 w-[min(520px,calc(100%-32px))] -translate-x-1/2 rounded-xl border border-border bg-card/95 px-4 py-3 shadow-xl backdrop-blur-sm">
                  <div className="mb-2 flex items-center justify-between gap-3 text-xs">
                    <span className="font-semibold text-foreground">工作流进度</span>
                    <span className="font-mono text-muted-foreground">{completedNodeCount} / {totalNodeCount} 节点 · {workflowProgress}%</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label="工作流进度" aria-valuemin={0} aria-valuemax={totalNodeCount} aria-valuenow={completedNodeCount}>
                    <div className="h-full rounded-full bg-primary transition-[width] duration-500" style={{ width: `${workflowProgress}%` }} />
                  </div>
                </div>
              )}
              {/* Task ID indicator */}

              {(activeTaskId || taskModeId || currentWfId) && (

                <div className="absolute top-4 right-4 z-10 flex items-center gap-2 bg-card border border-border rounded-lg px-3 py-1.5 shadow-lg">

                  <span className="text-[11px] text-muted-foreground font-mono">

                    {(activeTaskId || taskModeId) ? (
                      <><span className="text-muted-foreground/60">Task:</span> {activeTaskId || taskModeId}</>
                    ) : (
                      <><span className="text-muted-foreground/60">Workflow:</span> {workflowName}</>
                    )}
                  </span>

                  <button
                    onClick={async () => {
                      const taskId = activeTaskId || taskModeId || "";
                      if (!taskId) {
                        alert("当前工作流还没有关联的执行任务，请先执行工作流");
                        return;
                      }
                      try {
                        // 打开当前任务的执行文件夹（与历史任务卡片行为一致，os.startfile 打开系统文件管理器）
                        await client.post("/api/tasks/open-file", { file_path: taskId });
                      } catch (err) {
                        console.error("Open task folder failed:", err);
                        alert("打开任务执行文件夹失败");
                      }
                    }}
                    className="p-1 rounded hover:bg-muted/50 text-muted-foreground hover:text-foreground transition-colors"
                    title="打开任务执行文件夹"
                  >
                    <FolderOpen className="w-3.5 h-3.5" />
                  </button>
                </div>

              )}
            </ReactFlow>

            {nodes.length === 0 && (
              <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                <div className="text-center space-y-2 opacity-30">
                  <div className="text-sm font-semibold text-muted-foreground">{"\u62d6\u62fd\u8282\u70b9\u5230\u6b64\u5904\u5f00\u59cb\u7f16\u6392"}</div>
                  <div className="text-xs text-muted-foreground/60">{"\u6216\u70b9\u51fb\u53f3\u4fa7\u9762\u677f\u4e2d\u7684\u8282\u70b9\u5361\u7247"}</div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right: Node Palette */}
        <NodePalette
          onAddNode={addNodeAtCenter}
          collapsed={paletteCollapsed}
          onToggleCollapse={() => setPaletteCollapsed((p) => !p)}
        />
      </div>
    
      <Dialog open={canvasSettingsOpen} onOpenChange={setCanvasSettingsOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><Settings2 className="w-4 h-4" />画布设置</DialogTitle>
            <DialogDescription>切换线型后立即刷新当前画布，并用于后续新建连接。</DialogDescription>
          </DialogHeader>
          <div className="space-y-5">
            <div className="space-y-2">
              <div className="text-xs font-medium text-muted-foreground">连线线型</div>
              <div className="grid gap-2">
                {EDGE_TYPES.map((option) => {
                  const Icon = option.icon;
                  const selected = edgeType === option.value;
                  return (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => handleEdgeTypeChange(option.value)}
                      className={cn(
                        "flex items-center gap-3 border px-3 py-2.5 text-left transition-colors rounded-lg",
                        selected ? "border-primary bg-primary/10 text-foreground" : "border-border/60 hover:bg-secondary/60"
                      )}
                    >
                      <Icon className={cn("h-4 w-4 shrink-0", selected ? "text-primary" : "text-muted-foreground")} />
                      <span className="min-w-0 flex-1">
                        <span className="block text-sm font-medium">{option.label}</span>
                        <span className="block text-xs text-muted-foreground">{option.description}</span>
                      </span>
                      <span className={cn("h-2.5 w-2.5 rounded-full border", selected ? "border-primary bg-primary" : "border-muted-foreground/50")} />
                    </button>
                  );
                })}
              </div>
            </div>
            <div className="border-t border-border/60 pt-4">
              <div className="mb-2 text-xs font-medium text-muted-foreground">快捷键</div>
              <div className="grid grid-cols-2 gap-x-5 gap-y-2 text-xs">
                <span className="text-muted-foreground">保存 <kbd className="ml-1 rounded border border-border bg-muted px-1 py-0.5 text-foreground">Ctrl/Cmd + S</kbd></span>
                <span className="text-muted-foreground">另存为 <kbd className="ml-1 rounded border border-border bg-muted px-1 py-0.5 text-foreground">Ctrl/Cmd + Shift + S</kbd></span>
                <span className="text-muted-foreground">复制 / 粘贴 <kbd className="ml-1 rounded border border-border bg-muted px-1 py-0.5 text-foreground">Ctrl/Cmd + C/V</kbd></span>
                <span className="text-muted-foreground">全选 <kbd className="ml-1 rounded border border-border bg-muted px-1 py-0.5 text-foreground">Ctrl/Cmd + A</kbd></span>
                <span className="text-muted-foreground">组合 <kbd className="ml-1 rounded border border-border bg-muted px-1 py-0.5 text-foreground">Ctrl/Cmd + G</kbd></span>
                <span className="text-muted-foreground">删除 <kbd className="ml-1 rounded border border-border bg-muted px-1 py-0.5 text-foreground">Delete / Backspace</kbd></span>
                <span className="text-muted-foreground">框选 <kbd className="ml-1 rounded border border-border bg-muted px-1 py-0.5 text-foreground">Shift + 鼠标拖拽</kbd></span>
              </div>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <ExecutionModeModal
        isOpen={execModeModalOpen}
        onConfirm={handleExecuteWithMode}
        onCancel={() => setExecModeModalOpen(false)}
        hasCompletedSteps={hasCompletedSteps}
        isBatchTask={store.isBatchTask}
      />

      <Dialog open={groupConfigOpen} onOpenChange={(open) => { setGroupConfigOpen(open); if (!open) setGroupConfigTargetId(null); }}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><Layers3 className="w-4 h-4 text-violet-500" />组合设置</DialogTitle>
            <DialogDescription>设置组合名称，并选择需要暴露到组合外部的输出端点。</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1 block">组合名称</label>
              <input
                type="text"
                value={groupDraftName}
                onChange={(e) => setGroupDraftName(e.target.value)}
                className="w-full px-3 py-2 border border-border/50 rounded-lg bg-background/50 text-sm focus:border-primary/50 focus:ring-1 focus:ring-primary/20 outline-none transition-all"
                placeholder="请输入组合名称"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1 block">组合节点 ID</label>
              <input
                type="text"
                value={groupSaveNodeId}
                onChange={(e) => setGroupSaveNodeId(e.target.value)}
                className="w-full px-3 py-2 border border-border/50 rounded-lg bg-background/50 text-sm focus:border-primary/50 focus:ring-1 focus:ring-primary/20 outline-none transition-all"
                placeholder="留空时自动生成"
              />
            </div>
            <div className="rounded-xl border border-border/60 bg-background/40">
              <div className="px-4 py-3 border-b border-border/60 text-sm font-semibold">输出暴露</div>
              <div className="max-h-[360px] overflow-y-auto divide-y divide-border/50">
                {groupDraftOutputs.length ? groupDraftOutputs.map((item, index) => (
                  <label key={item.exposedPortId} className="flex items-start gap-3 px-4 py-3 cursor-pointer hover:bg-secondary/30">
                    <input
                      type="checkbox"
                      checked={item.enabled !== false}
                      onChange={(e) => setGroupDraftOutputs((current) => current.map((entry, entryIndex) => entryIndex === index ? { ...entry, enabled: e.target.checked } : entry))}
                      className="mt-1"
                    />
                    <div className="flex-1 min-w-0 space-y-2">
                      <div className="text-xs text-muted-foreground">内部输出</div>
                      <div className="text-sm font-medium">{item.exposedLabel}</div>
                      <input
                        type="text"
                        value={item.exposedLabel}
                        onChange={(e) => setGroupDraftOutputs((current) => current.map((entry, entryIndex) => entryIndex === index ? { ...entry, exposedLabel: e.target.value } : entry))}
                        className="w-full px-2.5 py-1.5 border border-border/50 rounded-md bg-background text-xs"
                        placeholder="外部端口显示名称"
                      />
                    </div>
                  </label>
                )) : (
                  <div className="px-4 py-8 text-center text-sm text-muted-foreground">当前组合没有可暴露的输出端点。</div>
                )}
              </div>
            </div>
            <div className="flex justify-between">
              <button
                type="button"
                onClick={() => groupConfigTargetId && handleSaveGroupAsNodeType(groupConfigTargetId)}
                disabled={!groupConfigTargetId || groupSaveLoading}
                className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-medium rounded-lg border border-violet-400/30 text-violet-700 bg-violet-500/10 hover:bg-violet-500/20 disabled:opacity-40 transition-all"
              >
                {groupSaveLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Share2 className="w-3 h-3" />}
                保存为组合节点
              </button>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setGroupConfigOpen(false)}
                  className="px-4 py-2 text-xs font-medium rounded-lg border border-border/50 hover:bg-secondary/60 text-muted-foreground transition-all"
                >
                  取消
                </button>
                <button
                  type="button"
                  onClick={applyGroupConfigDraft}
                  className="px-4 py-2 text-xs font-medium rounded-lg bg-primary text-primary-foreground hover:opacity-90 transition-all"
                >
                  保存设置
                </button>
              </div>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Save As Modal */}
      {saveAsModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-card border border-border/50 rounded-2xl p-6 w-full max-w-md shadow-2xl animate-fade-in-up">
            <h3 className="text-lg font-bold mb-4">{"另存为"}</h3>
            <div className="space-y-4">
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1 block">工作流名称</label>
                <input
                  type="text"
                  value={saveAsName}
                  onChange={(e) => setSaveAsName(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") confirmSaveAs(); }}
                  className="w-full px-3 py-2 border border-border/50 rounded-lg bg-background/50 text-sm focus:border-primary/50 focus:ring-1 focus:ring-primary/20 outline-none transition-all"
                  placeholder="请输入工作流名称"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1 block">描述</label>
                <textarea
                  value={saveAsDesc}
                  onChange={(e) => setSaveAsDesc(e.target.value)}
                  rows={3}
                  className="w-full px-3 py-2 border border-border/50 rounded-lg bg-background/50 text-sm focus:border-primary/50 focus:ring-1 focus:ring-primary/20 outline-none transition-all resize-none"
                  placeholder="请输入描述"
                />
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-6">
              <button
                onClick={() => setSaveAsModalOpen(false)}
                className="px-4 py-2 text-xs font-medium rounded-lg border border-border/50 hover:bg-secondary/60 text-muted-foreground transition-all"
              >
                取消
              </button>
              <button
                onClick={confirmSaveAs}
                disabled={saving}
                className="px-4 py-2 text-xs font-medium rounded-lg bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50 transition-all flex items-center gap-1"
              >
                {saving && <Loader2 className="w-3 h-3 animate-spin" />}
                确认保存
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 新建分组弹窗 */}
      {groupModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-card border border-border/50 rounded-2xl p-6 w-full max-w-sm shadow-2xl animate-fade-in-up">
            <h3 className="text-base font-bold mb-4">{"新建分组"}</h3>
            <input
              type="text"
              autoFocus
              value={newGroupName}
              onChange={(e) => setNewGroupName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && newGroupName.trim()) createGroup(newGroupName.trim()); }}
              className="w-full px-3 py-2 border border-border/50 rounded-lg bg-background/50 text-sm focus:border-primary/50 focus:ring-1 focus:ring-primary/20 outline-none transition-all"
              placeholder="请输入分组名称"
            />
            <div className="flex justify-end gap-2 mt-6">
              <button
                onClick={() => setGroupModalOpen(false)}
                className="px-4 py-2 text-xs font-medium rounded-lg border border-border/50 hover:bg-secondary/60 text-muted-foreground transition-all"
              >
                取消
              </button>
              <button
                onClick={() => newGroupName.trim() && createGroup(newGroupName.trim())}
                disabled={groupBusy || !newGroupName.trim()}
                className="px-4 py-2 text-xs font-medium rounded-lg bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50 transition-all flex items-center gap-1"
              >
                {groupBusy && <Loader2 className="w-3 h-3 animate-spin" />}
                创建
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 删除分组确认弹窗：询问连同工作流删除还是解散分组 */}
      {deleteGroupTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-card border border-border/50 rounded-2xl p-6 w-full max-w-sm shadow-2xl animate-fade-in-up">
            <h3 className="text-base font-bold mb-2">{"删除分组"}</h3>
            <p className="text-xs text-muted-foreground leading-relaxed mb-5">
              {"确定要删除分组 "}
              <span className="font-semibold text-foreground">{deleteGroupTarget.name}</span>
              {" 吗？请选择处理方式："}
            </p>
            <div className="space-y-2">
              <button
                onClick={() => { setDeleteGroupAction("delete"); }}
                className={cn(
                  "w-full px-4 py-2.5 text-xs font-medium rounded-lg border text-left transition-all",
                  deleteGroupAction === "delete"
                    ? "border-destructive bg-destructive/10 text-destructive"
                    : "border-border hover:bg-secondary/60 text-foreground"
                )}
              >
                <div className="font-semibold">{"连同工作流一起删除"}</div>
                <div className="text-[10px] opacity-70 mt-0.5">{"删除该分组及其下所有工作流（含任务与文件）"}</div>
              </button>
              <button
                onClick={() => { setDeleteGroupAction("dissolve"); }}
                className={cn(
                  "w-full px-4 py-2.5 text-xs font-medium rounded-lg border text-left transition-all",
                  deleteGroupAction === "dissolve"
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border hover:bg-secondary/60 text-foreground"
                )}
              >
                <div className="font-semibold">{"仅解散分组"}</div>
                <div className="text-[10px] opacity-70 mt-0.5">{"保留工作流，将其移回“未分组”"}</div>
              </button>
            </div>
            <div className="flex justify-end gap-2 mt-6">
              <button
                onClick={() => { setDeleteGroupTarget(null); setDeleteGroupAction(null); }}
                className="px-4 py-2 text-xs font-medium rounded-lg border border-border/50 hover:bg-secondary/60 text-muted-foreground transition-all"
              >
                取消
              </button>
              <button
                onClick={confirmDeleteGroup}
                disabled={groupBusy || !deleteGroupAction}
                className="px-4 py-2 text-xs font-medium rounded-lg bg-destructive text-destructive-foreground hover:opacity-90 disabled:opacity-50 transition-all flex items-center gap-1"
              >
                {groupBusy && <Loader2 className="w-3 h-3 animate-spin" />}
                确认
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 移动工作流到分组弹窗 */}
      {moveTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="bg-card border border-border/50 rounded-2xl p-6 w-full max-w-sm shadow-2xl animate-fade-in-up">
            <h3 className="text-base font-bold mb-1">{"移动到分组"}</h3>
            <p className="text-xs text-muted-foreground mb-4 truncate">
              <span className="font-semibold text-foreground">{moveTarget.name}</span>
            </p>
            <div className="space-y-2 max-h-60 overflow-y-auto">
              <button
                onClick={() => moveWorkflowToGroup(moveTarget.id, null)}
                className={cn(
                  "w-full px-4 py-2.5 text-xs font-medium rounded-lg border text-left transition-all",
                  !moveTarget.groupId ? "border-primary bg-primary/10 text-primary" : "border-border hover:bg-secondary/60 text-foreground"
                )}
              >
                未分组
              </button>
              {groups.map((g) => (
                <button
                  key={g.id}
                  onClick={() => moveWorkflowToGroup(moveTarget.id, g.id)}
                  className={cn(
                    "w-full px-4 py-2.5 text-xs font-medium rounded-lg border text-left transition-all",
                    moveTarget.groupId === g.id ? "border-primary bg-primary/10 text-primary" : "border-border hover:bg-secondary/60 text-foreground"
                  )}
                >
                  {g.name}
                </button>
              ))}
              {groups.length === 0 && (
                <div className="text-xs text-muted-foreground/60 py-2 text-center">{"暂无分组，请先新建分组"}</div>
              )}
            </div>
            <div className="flex justify-end mt-6">
              <button
                onClick={() => setMoveTarget(null)}
                className="px-4 py-2 text-xs font-medium rounded-lg border border-border/50 hover:bg-secondary/60 text-muted-foreground transition-all"
              >
                取消
              </button>
            </div>
          </div>
        </div>
      )}

      <ContextMenu
        visible={contextMenu.visible}
        position={contextMenu.position}
        onClose={() => setContextMenu((p) => ({ ...p, visible: false }))}
        onSelectNode={(nodeType, screenPos) => {
          // 点选后进入“粘附光标”模式，由用户再次点击决定落点
          setContextMenu((p) => ({ ...p, visible: false }));
          if (screenPos) setPlacingPos(screenPos);
          setPlacingNode(nodeType);
        }}
      />

      {/* 从输出端点拖线松手后的"可接入下游节点"面板 */}
      <QuickConnectMenu
        visible={!!quickConnect}
        request={quickConnect}
        onSelect={handleQuickConnectSelect}
        onClose={() => setQuickConnect(null)}
      />

      {/* 粘附光标的节点预览：跟随鼠标，点击画布落下 */}
      {placingNode && (
        <div
          className="fixed z-[10000] pointer-events-none flex items-center gap-2 px-3 py-2 rounded-lg border border-primary/60 bg-card/95 shadow-xl backdrop-blur-sm"
          style={{ left: placingPos.x + 14, top: placingPos.y + 12 }}
        >
          <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: placingNode.color }} />
          <span className="text-xs font-medium whitespace-nowrap">{placingNode.name}</span>
          <span className="text-[10px] text-muted-foreground/70 whitespace-nowrap">点击画布放置 · Esc 取消</span>
        </div>
      )}

      {/* Workflow detail dialog */}
      <Dialog open={!!hoveredWf} onOpenChange={(open) => { if (!open) setHoveredWf(null); }}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <FileText className="w-4 h-4 text-primary" />
              {hoveredWf?.name}
            </DialogTitle>
            {hoveredWf?.description && (
              <DialogDescription>{hoveredWf.description}</DialogDescription>
            )}
          </DialogHeader>
          <div className="space-y-3">
            <div className="flex flex-wrap gap-1.5">
              <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-semibold bg-sky-500/10 text-sky-600 dark:text-sky-400 border border-sky-400/20">
                {hoveredWf?.nodeCount || 0} 节点
              </span>
              <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-semibold bg-violet-500/10 text-violet-600 dark:text-violet-400 border border-violet-400/20">
                {hoveredWf?.edgeCount || 0} 连接
              </span>
            </div>
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground border-t border-border/40 pt-3">
              <Clock className="w-3.5 h-3.5" />
              <span>更新于 {hoveredWf ? formatTime(hoveredWf.updatedAt) : ""}</span>
            </div>
            <div className="flex gap-2 pt-1">
              <button
                onClick={() => {
                  if (hoveredWf) loadWorkflow(hoveredWf.id);
                  setHoveredWf(null);
                }}
                className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-semibold text-primary-foreground border border-primary/60 bg-primary rounded-lg hover:shadow-lg hover:shadow-primary/30 transition-all"
              >
                <Play className="w-3.5 h-3.5" />
                加载工作流
              </button>
              <button
                onClick={() => {
                  if (hoveredWf) {
                    deleteWorkflow(hoveredWf.id, new MouseEvent("click") as any);
                  }
                  setHoveredWf(null);
                }}
                className="flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-semibold text-red-600 border border-red-400 bg-red-500/10 rounded-lg hover:bg-red-500/20 transition-all"
              >
                <Trash2 className="w-3.5 h-3.5" />
                删除
              </button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <SharePackDialog
        open={packOpen}
        onClose={() => setPackOpen(false)}
        title={"分享打包工作流"}
        initialName={workflowName || "未命名工作流"}
        initialDescription={workflowDesc}
        categories={WORKFLOW_SHARE_CATEGORIES}
        previewProvider={() => captureWorkflowCanvas(reactFlowInstance)}
        onSubmit={handlePackSubmit}
      />
    </div>
  );
}

const WORKFLOW_SHARE_CATEGORIES = [
  { value: "通用工作流", label: "通用工作流" },
  { value: "视频处理", label: "视频处理" },
  { value: "字幕处理", label: "字幕处理" },
  { value: "AI 处理", label: "AI 处理" },
  { value: "多平台发布", label: "多平台发布" },
  { value: "工具工作流", label: "工具工作流" },
];

function Btn({ icon: Icon, label, onClick, loading }: { icon: any; label: string; onClick: () => void; loading?: boolean }) {
  return (
    <button onClick={onClick} disabled={loading}
      className="flex items-center gap-1 px-2 py-2 text-xs font-semibold text-foreground border border-border rounded-md hover:bg-secondary/60 hover:border-primary/40 transition-all disabled:opacity-50"
      title={label}>
      {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Icon className="w-3 h-3" />}{label}
    </button>
  );
}

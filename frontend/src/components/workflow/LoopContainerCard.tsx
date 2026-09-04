import { useState } from "react";
import { Handle, Position } from "@xyflow/react";
import { cn } from "@/lib/utils";
import {
  getVisibleOutputs, getNodeInputs, PORT_COLORS,
  type NodeTypeDef, type PortType,
} from "@/lib/workflowTypes";
import { STATUS_CONFIG } from "./nodeStatus";
import { Repeat, ChevronDown, ChevronUp, LayoutList, Settings2 } from "lucide-react";
import LoopResultDialog from "./LoopResultDialog";

/**
 * 循环容器节点卡片。
 *
 * 与组合节点卡片同构（内部子图折叠展示），差异点：
 * - 头部展示迭代进度（由后端 node_progress 事件写入的 data.loopProgress 驱动）；
 * - 提供「产物清单」入口，打开 manifest 结果面板（产物不做物理归档，仅索引）。
 */
export default function LoopContainerCard({
  id,
  nd,
  selected,
  nodeType,
  expanded,
  setExpanded,
  updateNodeData,
  taskId,
  dragHandleClass,
}: {
  id: string;
  nd: any;
  selected: boolean;
  nodeType: NodeTypeDef;
  expanded: boolean;
  setExpanded: (value: boolean) => void;
  updateNodeData: (nodeId: string, dataUpdate: Record<string, any>) => void;
  taskId?: string;
  dragHandleClass?: string;
}) {
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState(nd.loopMeta?.name || nd.label || "循环");
  const [resultOpen, setResultOpen] = useState(false);
  const [configOpen, setConfigOpen] = useState(false);

  const visibleInputs = getNodeInputs(nodeType, nd.config || {});
  const visibleOutputs = getVisibleOutputs(nodeType, nd.config || {});
  const members = [...(nd.loopMeta?.internalWorkflow?.nodes || [])].sort(
    (a: any, b: any) => (a.position?.y || 0) - (b.position?.y || 0)
  );
  const status = nd.status || "pending";
  const statusCfg = STATUS_CONFIG[status] || STATUS_CONFIG.pending;
  const StatusIcon = statusCfg.icon;
  const loopProgress = nd.loopProgress as { index?: number; total?: number; done?: number; status?: string } | undefined;
  const config = nd.config || {};
  const iterator = nd.loopMeta?.iterator;

  const manifestPath: string = nd.outputs?.results || `cache/loop_manifest_${id}.json`;

  const setConfig = (key: string, value: any) => {
    updateNodeData(id, { config: { ...(nd.config || {}), [key]: value } });
  };

  const cfg = nd.config || {};
  const itemsSource: string = cfg.itemsSource || "upstream";
  const onError: string = cfg.onItemError || "stop";
  const concurrency: number = Math.max(1, Math.min(16, Number(cfg.iterationConcurrency) || 1));
  const maxIterations: number = Number(cfg.maxIterations) || 0;

  const handleStyle = (portType: string, idx: number, total: number) => ({
    top: ((idx + 1) / (total + 1)) * 100 + "%",
    background: PORT_COLORS[portType as PortType] || "#6366f1",
    width: 12,
    height: 12,
    border: "2px solid white",
  });

  const saveName = () => {
    const nextName = nameDraft.trim() || "循环";
    updateNodeData(id, {
      label: nextName,
      loopMeta: { ...nd.loopMeta, name: nextName },
    });
    setEditingName(false);
  };

  return (
    <div
      className={cn(
        "rounded-2xl border-[3px] bg-card text-card-foreground w-[440px] max-w-[440px] transition-all duration-300",
        selected ? "border-primary shadow-primary/20 shadow-lg scale-[1.02]" : "border-indigo-400/60 shadow-md"
      )}
    >
      {visibleInputs.map((port, i) => (
        <Handle
          key={`in-${port.id}`}
          type="target"
          position={Position.Left}
          id={`in-${port.id}`}
          style={handleStyle(port.type, i, visibleInputs.length)}
        />
      ))}
      {visibleOutputs.map((port, i) => (
        <Handle
          key={`out-${port.id}`}
          type="source"
          position={Position.Right}
          id={`out-${port.id}`}
          style={handleStyle(port.type, i, visibleOutputs.length)}
        />
      ))}

      <div
        className={cn(
          "flex items-center gap-2 px-4 py-3 rounded-t-xl bg-indigo-500/15 cursor-grab active:cursor-grabbing",
          dragHandleClass
        )}
      >
        <div className="w-9 h-9 rounded-lg flex items-center justify-center bg-indigo-500/20 text-indigo-600 dark:text-indigo-300">
          <Repeat className="w-5 h-5" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[11px] font-semibold text-indigo-600 dark:text-indigo-300">循环</div>
          {editingName ? (
            <input
              autoFocus
              value={nameDraft}
              onChange={(e) => setNameDraft(e.target.value)}
              onBlur={saveName}
              onKeyDown={(e) => {
                if (e.key === "Enter") saveName();
                if (e.key === "Escape") {
                  setNameDraft(nd.loopMeta?.name || nd.label || "循环");
                  setEditingName(false);
                }
              }}
              onClick={(e) => e.stopPropagation()}
              className="mt-0.5 w-full text-sm font-bold bg-background/80 border border-border/60 rounded-md px-2 py-1 nodrag"
            />
          ) : (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setEditingName(true);
              }}
              className="text-left text-sm font-bold truncate hover:text-primary transition-colors nodrag"
            >
              {nd.loopMeta?.name || nd.label || "循环"}
            </button>
          )}
        </div>
        <div
          className={cn("flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[10px] font-semibold nodrag", statusCfg.badgeBg, statusCfg.badgeText)}
          title={nd.message || statusCfg.label}
        >
          <StatusIcon className={cn("w-3 h-3", status === "running" && "animate-spin")} />
          {statusCfg.label}
        </div>
      </div>

      {/* 迭代进度 */}
      <div className="px-4 py-2 space-y-1.5 border-b border-border/60 bg-indigo-500/5">
        <div className="flex items-center justify-between gap-2 text-[11px]">
          <span className="text-muted-foreground">
            {loopProgress?.total
              ? `迭代进度 ${loopProgress.done ?? 0} / ${loopProgress.total}`
              : config.itemsSource === "inline_json"
                ? "迭代来源：内联 JSON 数组"
                : config.itemsSource === "directory_glob"
                  ? "迭代来源：目录文件匹配"
                  : "迭代来源：上游连线输入"}
          </span>
          <span className="text-muted-foreground">并发 {config.iterationConcurrency ?? 1}</span>
        </div>
        {loopProgress?.total ? (
          <div className="h-1.5 rounded-full bg-muted overflow-hidden">
            <div
              className="h-full bg-indigo-500 transition-all duration-300"
              style={{ width: `${Math.min(100, ((loopProgress.done ?? 0) / loopProgress.total) * 100)}%` }}
            />
          </div>
        ) : null}
        {status === "running" && nd.message ? (
          <div className="text-[11px] text-muted-foreground truncate" title={nd.message}>
            {nd.message}
          </div>
        ) : null}
      </div>

      {/* 循环体成员 */}
      <div className="px-4 py-2">
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setExpanded(!expanded);
          }}
          className="flex w-full items-center justify-between text-[11px] font-medium text-muted-foreground hover:text-foreground transition-colors nodrag"
        >
          <span>循环体（{members.length} 个节点）</span>
          {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
        </button>
        {expanded && (
          <div className="mt-1.5 space-y-1">
            {members.map((member: any) => (
              <div
                key={member.id}
                className="flex items-center gap-1.5 rounded-md border border-border/60 bg-muted/40 px-2 py-1 text-[11px]"
              >
                <span className="truncate">{member.data?.label || member.data?.nodeType || member.id}</span>
                {iterator?.targetNodeId === member.id && (
                  <span className="ml-auto shrink-0 rounded bg-indigo-500/15 px-1.5 py-0.5 text-[10px] text-indigo-600 dark:text-indigo-300">
                    迭代入口
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="px-4 pb-3 space-y-2">
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setConfigOpen(!configOpen);
          }}
          className="w-full flex items-center justify-between text-[11px] font-medium text-muted-foreground hover:text-foreground transition-colors nodrag"
        >
          <span className="flex items-center gap-1.5">
            <Settings2 className="w-3.5 h-3.5" /> 循环配置
          </span>
          {configOpen ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
        </button>

        {configOpen && (
          <div className="space-y-2.5 rounded-md border border-border/60 bg-muted/30 p-2.5">
            {/* 迭代对象来源 */}
            <div className="space-y-1">
              <label className="text-[11px] font-medium text-muted-foreground">迭代对象来源</label>
              <select
                value={itemsSource}
                onChange={(e) => setConfig("itemsSource", e.target.value)}
                className="w-full rounded-md border border-border/60 bg-background px-2 py-1 text-xs nodrag"
              >
                <option value="upstream">上游连线输入</option>
                <option value="inline_json">内联 JSON 数组</option>
                <option value="directory_glob">目录文件匹配</option>
              </select>
            </div>

            {itemsSource === "inline_json" && (
              <div className="space-y-1">
                <label className="text-[11px] font-medium text-muted-foreground">内联 JSON 数组</label>
                <textarea
                  value={String(cfg.inlineItems ?? "")}
                  onChange={(e) => setConfig("inlineItems", e.target.value)}
                  rows={3}
                  placeholder={'["a.mp4", "b.mp4"] 或 [{"path": "a.mp4"}]'}
                  className="w-full resize-y rounded-md border border-border/60 bg-background px-2 py-1 text-xs nodrag font-mono"
                />
              </div>
            )}

            {itemsSource === "directory_glob" && (
              <div className="space-y-1">
                <label className="text-[11px] font-medium text-muted-foreground">目录通配符</label>
                <input
                  value={String(cfg.globPattern ?? "")}
                  onChange={(e) => setConfig("globPattern", e.target.value)}
                  placeholder="D:/videos/*.mp4"
                  className="w-full rounded-md border border-border/60 bg-background px-2 py-1 text-xs nodrag"
                />
              </div>
            )}

            {/* 最大迭代数 */}
            <div className="space-y-1">
              <label className="text-[11px] font-medium text-muted-foreground">
                最大迭代数（0 = 不限制）
              </label>
              <input
                type="number"
                min={0}
                max={500}
                value={maxIterations}
                onChange={(e) => setConfig("maxIterations", Math.max(0, Number(e.target.value) || 0))}
                className="w-full rounded-md border border-border/60 bg-background px-2 py-1 text-xs nodrag"
              />
            </div>

            {/* 并发数（一期即支持，前端可调） */}
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <label className="text-[11px] font-medium text-muted-foreground">并发数</label>
                <span className="text-[11px] font-semibold text-indigo-600 dark:text-indigo-300">{concurrency}</span>
              </div>
              <input
                type="range"
                min={1}
                max={16}
                step={1}
                value={concurrency}
                onChange={(e) => setConfig("iterationConcurrency", Number(e.target.value))}
                className="w-full nodrag accent-indigo-500"
              />
              <p className="text-[10px] text-muted-foreground">同时处理的迭代条目数；串行请填 1。</p>
            </div>

            {/* 单项失败策略 */}
            <div className="space-y-1">
              <label className="text-[11px] font-medium text-muted-foreground">单项失败策略</label>
              <select
                value={onError}
                onChange={(e) => setConfig("onItemError", e.target.value)}
                className="w-full rounded-md border border-border/60 bg-background px-2 py-1 text-xs nodrag"
              >
                <option value="stop">立即停止</option>
                <option value="skip">跳过并继续</option>
                <option value="collect_error">记录错误后继续</option>
              </select>
            </div>

            {/* 变量别名 */}
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <label className="text-[11px] font-medium text-muted-foreground">条目变量名</label>
                <input
                  value={String(cfg.itemAlias ?? "item")}
                  onChange={(e) => setConfig("itemAlias", e.target.value)}
                  placeholder="item"
                  className="w-full rounded-md border border-border/60 bg-background px-2 py-1 text-xs nodrag"
                />
              </div>
              <div className="space-y-1">
                <label className="text-[11px] font-medium text-muted-foreground">序号变量名</label>
                <input
                  value={String(cfg.indexAlias ?? "index")}
                  onChange={(e) => setConfig("indexAlias", e.target.value)}
                  placeholder="index"
                  className="w-full rounded-md border border-border/60 bg-background px-2 py-1 text-xs nodrag"
                />
              </div>
            </div>
            <p className="text-[10px] text-muted-foreground">
              循环体节点配置中以 <code className="font-mono">{"{item}"}</code> 引用当前条目，
              <code className="font-mono">{"{index}"}</code> / <code className="font-mono">{"{index:03d}"}</code> 引用序号。
            </p>
          </div>
        )}

        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setResultOpen(true);
          }}
          className="w-full inline-flex items-center justify-center gap-1.5 rounded-md border border-border/70 bg-background px-2 py-1.5 text-xs font-medium hover:bg-muted transition-colors nodrag"
        >
          <LayoutList className="w-3.5 h-3.5" />
          查看产物清单
        </button>
      </div>

      <LoopResultDialog
        open={resultOpen}
        onOpenChange={setResultOpen}
        taskId={taskId}
        manifestPath={manifestPath}
        loopLabel={nd.loopMeta?.name || nd.label}
      />
    </div>
  );
}

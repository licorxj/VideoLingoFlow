import { memo, useState, useCallback, useEffect, useRef, useMemo } from "react";
import { createPortal } from "react-dom";
import SubtitleParser from "srt-parser-2";
import { nativeFileDialog } from "@/api/files";
import { LANGUAGE_OPTIONS } from "@/lib/languages";
import { Handle, Position, useReactFlow } from "@xyflow/react";
import type { NodeProps } from "@xyflow/react";
import { cn } from "@/lib/utils";
import client from "@/api/client";
import { useWorkflowStore } from "@/stores/workflowStore";
import {
  getNodeTypeDef, PORT_COLORS, getVisibleOutputs, getNodeInputs, isConfigFieldVisible,
  PI_AGENT_OUTPUT_TYPES, buildInlineGroupTypeDef, isGroupNodeData,
  type WorkflowNode as WFNode, type ConfigField, type PortType,
} from "@/lib/workflowTypes";
import VoiceSelectPanel from "../VoiceSelectPanel";
import AudioSelectorDialog from "@/components/AudioSelectorDialog";
import SkillMcpPickerDialog, { type PickerKind } from "@/components/workflow/SkillMcpPickerDialog";
import {
  Film, Music, Subtitles, Mic, Mic2, Scissors, Brain, Languages,
  FileText, Volume2, Merge, Clapperboard, Image, Stamp, Download,
  Upload, Wrench, CheckCircle2, Loader2, XCircle, Clock, AlertTriangle, Play,
  ChevronDown, ChevronRight, Eye, ArrowRight, Sparkles, Maximize2, HelpCircle,
  CheckSquare, Square, Users, FolderOpen, ExternalLink, FileJson,
  Layers, Captions, SlidersHorizontal, RefreshCw, Eraser, Type, PenTool,
} from "lucide-react";
import JsonEditorDialog from "./JsonEditorDialog";
import TextEditorDialog from "./TextEditorDialog";
import SubtitleEditorDialog from "./SubtitleEditorDialog";
import { LcwrNodeControls, LcwrRegionSummary, LcwrWatermarkEditor } from "./LcwrWatermarkEditor";
import { SubtitleFindEditor } from "./SubtitleFindEditor";
import { ImageMaskEditor } from "./ImageMaskEditor";
import { VideoGenNode } from "./VideoGenNode";
import { AudioAssetLibraryNode } from "./AudioAssetLibraryNode";

const ICON_MAP: Record<string, any> = {
  Film, Music, Subtitles, Mic, Mic2, Scissors, Brain, Languages,
  FileText, Volume2, Merge, Clapperboard, Image, Stamp, Download,
  Upload, Wrench, Play, Eye, Sparkles, FolderOpen, Captions, SlidersHorizontal,
  Eraser, Type,
};

/** 解析 SRT/VTT/JSON 字幕内容为 [{start, end, text}]（时间为秒），支持双语（原文/译文两行） */
function parseSubtitleEntries(content: string): { start: number; end: number; text: string }[] {
  const trimmed = content.trim();
  if (!trimmed) return [];
  // JSON（项目双语字幕格式）
  try {
    const data = JSON.parse(trimmed);
    let list: any[] = [];
    if (Array.isArray(data)) list = data;
    else if (data && typeof data === "object") {
      for (const key of ["segments", "items", "subtitles", "entries"]) {
        if (Array.isArray(data[key])) { list = data[key]; break; }
      }
    }
    if (list.length > 0) {
      return list
        .filter((item) => item && typeof item === "object" && item.start !== undefined && item.end !== undefined)
        .map((item) => {
          const original = item.text ?? item.origin ?? item.original ?? item.src ?? item.content ?? "";
          const translated = item.translation ?? item.translate ?? item.translated ?? item.tr ?? item.direct ?? item.reflect ?? "";
          const parts = [String(original).trim(), String(translated).trim()].filter(Boolean);
          return {
            start: Number(item.start) || 0,
            end: Number(item.end) || 0,
            text: parts.join("\n"),
          };
        });
    }
  } catch { /* 非 JSON，走成熟库解析 SRT */ }
  try {
    const lines = new SubtitleParser().fromSrt(trimmed);
    return lines.map((l) => ({
      start: Number(l.startSeconds) || 0,
      end: Number(l.endSeconds) || 0,
      text: String(l.text || ""),
    }));
  } catch {
    return [];
  }
}

const STATUS_CONFIG: Record<string, { icon: any; color: string; bg: string; border: string; glow: string; label: string; badgeBg: string; badgeText: string }> = {
  pending: {
    icon: Clock, color: "text-muted-foreground", bg: "bg-muted/30",
    border: "", glow: "",
    label: "等待中",
    badgeBg: "bg-muted/60", badgeText: "text-muted-foreground",
  },
  running: {
    icon: Loader2, color: "text-blue-500", bg: "bg-blue-500/5",
    border: "border-blue-400 shadow-[0_0_12px_rgba(59,130,246,0.25)]",
    glow: "ring-2 ring-blue-400/30",
    label: "执行中",
    badgeBg: "bg-blue-500/15", badgeText: "text-blue-600",
  },
  waiting: {
    icon: Clock, color: "text-amber-600", bg: "bg-amber-500/5",
    border: "border-amber-400 shadow-[0_0_12px_rgba(245,158,11,0.2)]",
    glow: "",
    label: "等待剪辑",
    badgeBg: "bg-amber-500/15", badgeText: "text-amber-700",
  },
  completed: {
    icon: CheckCircle2, color: "text-emerald-500", bg: "bg-emerald-500/5",
    border: "!border-[4px] border-emerald-400 shadow-[0_0_14px_rgba(16,185,129,0.3)]",
    glow: "",
    label: "已完成",
    badgeBg: "bg-emerald-500/15", badgeText: "text-emerald-600",
  },
  failed: {
    icon: XCircle, color: "text-red-500", bg: "bg-red-500/5",
    border: "border-red-400 shadow-[0_0_12px_rgba(239,68,68,0.25)]",
    glow: "",
    label: "失败",
    badgeBg: "bg-red-500/15", badgeText: "text-red-600",
  },
  skipped: {
    icon: Clock, color: "text-yellow-500", bg: "bg-yellow-500/5",
    border: "border-yellow-400",
    glow: "",
    label: "已跳过",
    badgeBg: "bg-yellow-500/15", badgeText: "text-yellow-600",
  },
  cancelled: {
    icon: AlertTriangle, color: "text-orange-500", bg: "bg-orange-500/5",
    border: "border-orange-400 shadow-[0_0_10px_rgba(249,115,22,0.2)]",
    glow: "",
    label: "已取消",
    badgeBg: "bg-orange-500/15", badgeText: "text-orange-600",
  },
};

const CHIP_COLORS: Record<string, string> = {
  video: "#3b82f6",
  audio: "#10b981",
  subtitle: "#f59e0b",
  url: "#06b6d4",
};

function GroupWorkflowNodeCard({
  id,
  nd,
  selected,
  nodeType,
  expanded,
  setExpanded,
  updateNodeData,
  taskId,
}: {
  id: string;
  nd: any;
  selected: boolean;
  nodeType: NonNullable<ReturnType<typeof buildInlineGroupTypeDef>>;
  expanded: boolean;
  setExpanded: (value: boolean) => void;
  updateNodeData: (id: string, dataUpdate: Record<string, any>) => void;
  taskId?: string;
}) {
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState(nd.groupMeta?.name || nd.label || "组合");
  const [activeMemberId, setActiveMemberId] = useState<string | null>(null);
  const visibleInputs = getNodeInputs(nodeType, nd.config || {});
  const visibleOutputs = getVisibleOutputs(nodeType, nd.config || {});
  const members = [...(nd.groupMeta?.internalWorkflow?.nodes || [])].sort((a: any, b: any) => (a.position?.y || 0) - (b.position?.y || 0));
  const status = nd.status || "pending";
  const statusCfg = STATUS_CONFIG[status] || STATUS_CONFIG.pending;
  const StatusIcon = statusCfg.icon;
  const outputEntries = Object.entries(nd.outputs || {}).filter(([, value]) => value !== undefined && value !== null && value !== "");
  const handleStyle = (portType: string, idx: number, total: number) => ({
    top: ((idx + 1) / (total + 1)) * 100 + "%",
    background: PORT_COLORS[portType as PortType] || "#6366f1",
    width: 12, height: 12, border: "2px solid white",
  });

  const saveName = () => {
    const nextName = nameDraft.trim() || "组合";
    updateNodeData(id, {
      label: nextName,
      groupMeta: {
        ...nd.groupMeta,
        name: nextName,
      },
    });
    setEditingName(false);
  };

  const updateMemberConfig = (memberId: string, key: string, value: any) => {
    const internalWorkflow = nd.groupMeta?.internalWorkflow;
    if (!internalWorkflow) return;
    const internalNodes = (internalWorkflow.nodes || []).map((member: any) => {
      if (member.id !== memberId) return member;
      return {
        ...member,
        data: {
          ...(member.data || {}),
          config: { ...(member.data?.config || {}), [key]: value },
        },
      };
    });
    updateNodeData(id, {
      groupMeta: {
        ...nd.groupMeta,
        internalWorkflow: { ...internalWorkflow, nodes: internalNodes },
      },
    });
  };

  return (
    <div className={cn(
      "rounded-2xl border-[3px] bg-card text-card-foreground w-[440px] max-w-[440px] transition-all duration-300",
      selected ? "border-primary shadow-primary/20 shadow-lg scale-[1.02]" : "border-violet-400/60 shadow-md"
    )}>
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

      <div className="flex items-center gap-2 px-4 py-3 rounded-t-xl bg-violet-500/15">
        <div className="w-9 h-9 rounded-lg flex items-center justify-center bg-violet-500/20 text-violet-600 dark:text-violet-300">
          <Layers className="w-5 h-5" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[11px] font-semibold text-violet-600 dark:text-violet-300">组合</div>
          {editingName ? (
            <input
              autoFocus
              value={nameDraft}
              onChange={(e) => setNameDraft(e.target.value)}
              onBlur={saveName}
              onKeyDown={(e) => {
                if (e.key === "Enter") saveName();
                if (e.key === "Escape") {
                  setNameDraft(nd.groupMeta?.name || nd.label || "组合");
                  setEditingName(false);
                }
              }}
              onClick={(e) => e.stopPropagation()}
              className="mt-0.5 w-full text-sm font-bold bg-background/80 border border-border/60 rounded-md px-2 py-1"
            />
          ) : (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); setEditingName(true); }}
              className="text-left text-sm font-bold truncate hover:text-primary transition-colors"
            >
              {nd.groupMeta?.name || nd.label || "组合"}
            </button>
          )}
        </div>
        <div className={cn("flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[10px] font-semibold", statusCfg.badgeBg, statusCfg.badgeText)} title={nd.message || statusCfg.label}>
          <StatusIcon className={cn("w-3 h-3", status === "running" && "animate-spin")} />
          {statusCfg.label}
        </div>
        <div className="flex items-center gap-1">
          {nd.onExecuteNode && (
            <button
              onClick={(e) => { e.stopPropagation(); nd.onExecuteNode(id); }}
              disabled={nd.disableExecute || nd.status === "running"}
              className="w-6 h-6 rounded-md flex items-center justify-center bg-primary/10 text-primary hover:bg-primary/20 transition-colors disabled:opacity-40"
              title="仅执行此节点"
            >
              <Play className="w-3 h-3" />
            </button>
          )}
          {nd.onExecuteFromNode && (
            <button
              onClick={(e) => { e.stopPropagation(); nd.onExecuteFromNode(id); }}
              disabled={nd.disableExecute || nd.status === "running"}
              className="w-6 h-6 rounded-md flex items-center justify-center bg-amber-500/10 text-amber-600 hover:bg-amber-500/20 transition-colors disabled:opacity-40"
              title="从此节点继续执行下游"
            >
              <ArrowRight className="w-3 h-3" />
            </button>
          )}
          {nd.onEditGroupNode && (
            <button
              onClick={(e) => { e.stopPropagation(); nd.onEditGroupNode(id); }}
              className="w-6 h-6 rounded-md flex items-center justify-center bg-violet-500/10 text-violet-600 hover:bg-violet-500/20 transition-colors"
              title="编辑组合"
            >
              <CheckSquare className="w-3 h-3" />
            </button>
          )}
          {nd.onUngroupNode && (
            <button
              onClick={(e) => { e.stopPropagation(); nd.onUngroupNode(id); }}
              className="w-6 h-6 rounded-md flex items-center justify-center bg-rose-500/10 text-rose-600 hover:bg-rose-500/20 transition-colors"
              title="解散组合"
            >
              <Square className="w-3 h-3" />
            </button>
          )}
          {nd.onSaveAsGroupNode && (
            <button
              onClick={(e) => { e.stopPropagation(); nd.onSaveAsGroupNode(id); }}
              className="w-6 h-6 rounded-md flex items-center justify-center bg-emerald-500/10 text-emerald-600 hover:bg-emerald-500/20 transition-colors"
              title="保存为组合节点"
            >
              <FileJson className="w-3 h-3" />
            </button>
          )}
          <button
            onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}
            className="w-6 h-6 rounded-md flex items-center justify-center text-muted-foreground hover:bg-foreground/10 transition-colors"
            title={expanded ? "折叠" : "展开"}
          >
            {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          </button>
        </div>
      </div>

      {(status === "running" || status === "waiting") && (
        <div className="px-3 pt-2">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-violet-100 dark:bg-violet-950/40">
            <div className="h-full rounded-full bg-violet-500 transition-all duration-500" style={{ width: `${Math.max(0, Math.min(100, Number(nd.progress) || 0))}%` }} />
          </div>
          {nd.message && <div className="mt-1 truncate text-[11px] text-violet-600 dark:text-violet-300">{nd.message}</div>}
          {Array.isArray(nd.logLines) && nd.logLines.length > 0 && (
            <div className="mt-1 max-h-20 overflow-y-auto rounded bg-gray-900/5 dark:bg-gray-900/40 px-1.5 py-1 space-y-0.5">
              {nd.logLines.map((line: string, i: number) => (
                <div key={i} className="text-[10px] font-mono text-gray-600 dark:text-gray-400 leading-tight break-all">{line}</div>
              ))}
            </div>
          )}
        </div>
      )}
      {/* 节点完成后保留显示最后一条进度消息（非 running/waiting 状态） */}
      {status !== "running" && status !== "waiting" && nd.message && (
        <div className="px-3 pt-1">
          <div className="truncate text-[11px] text-muted-foreground">{nd.message}</div>
        </div>
      )}

      <div className="px-3 py-2 border-b border-border/50 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[11px] font-semibold text-muted-foreground">外部输入</div>
          <div className="mt-1 flex flex-wrap gap-1">
            {visibleInputs.length ? visibleInputs.map((port) => (
              <span key={port.id} className="inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded-md" style={{ backgroundColor: (PORT_COLORS[port.type] || "#6366f1") + "20", color: PORT_COLORS[port.type] || "#6366f1" }}>
                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: PORT_COLORS[port.type] || "#6366f1" }} />
                {port.label}
              </span>
            )) : <span className="text-[11px] text-muted-foreground">无</span>}
          </div>
        </div>
        <div className="min-w-0 text-right">
          <div className="text-[11px] font-semibold text-muted-foreground">外部输出</div>
          <div className="mt-1 flex flex-wrap gap-1 justify-end">
            {visibleOutputs.length ? visibleOutputs.map((port) => (
              <span key={port.id} className="inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded-md" style={{ backgroundColor: (PORT_COLORS[port.type] || "#6366f1") + "20", color: PORT_COLORS[port.type] || "#6366f1" }}>
                {port.label}
                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: PORT_COLORS[port.type] || "#6366f1" }} />
              </span>
            )) : <span className="text-[11px] text-muted-foreground">无</span>}
          </div>
        </div>
      </div>

      {expanded && (
        <div className="px-3 py-3 space-y-2">
          {members.map((member: any, index: number) => {
            const memberId = String(member.id || index);
            const memberType = getNodeTypeDef(String(member.data?.nodeType || ""));
            const memberConfig = member.data?.config || {};
            const memberExpanded = activeMemberId === memberId;
            return (
              <div key={memberId} className="rounded-xl border border-border/60 bg-background/60 overflow-hidden">
                <button
                  type="button"
                  onClick={(event) => { event.stopPropagation(); setActiveMemberId(memberExpanded ? null : memberId); }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-violet-500/5 transition-colors"
                >
                  <div className="w-6 h-6 rounded-md bg-violet-500/10 text-violet-600 flex items-center justify-center text-[10px] font-bold">
                    {index + 1}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-semibold truncate">{member.data?.label || member.id}</div>
                    <div className="text-[11px] text-muted-foreground truncate">{member.data?.nodeType || "节点"}</div>
                  </div>
                  {memberType && (
                    <span className="text-[10px] text-muted-foreground">{(memberType.configFields || []).length ? `${(memberType.configFields || []).length} 项设置` : "无设置"}</span>
                  )}
                  {memberExpanded ? <ChevronDown className="w-3.5 h-3.5 text-muted-foreground" /> : <ChevronRight className="w-3.5 h-3.5 text-muted-foreground" />}
                </button>
                {memberExpanded && (
                  <div className="border-t border-border/50 px-3 py-3 bg-background/40" onClick={(event) => event.stopPropagation()}>
                    {memberType ? (
                      <ConfigForm
                        nodeType={memberType}
                        config={memberConfig}
                        onConfigChange={(key, value) => updateMemberConfig(memberId, key, value)}
                      />
                    ) : (
                      <div className="text-xs text-muted-foreground">未找到该节点的配置定义。</div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {status === "completed" && outputEntries.length > 0 && (
        <div className="border-t border-border/50 px-3 pb-3 pt-2">
          <div className="mb-1.5 flex items-center gap-1.5">
            <FileText className="w-3 h-3 text-emerald-500" />
            <span className="text-[11px] font-semibold text-emerald-600 dark:text-emerald-400">输出产物</span>
          </div>
          <div className="space-y-1">
            {outputEntries.map(([portId, value]) => {
              const path = typeof value === "string" ? value : JSON.stringify(value);
              const filename = path.replace(/\\/g, "/").split("/").pop() || path;
              return (
                <button
                  key={portId}
                  type="button"
                  onClick={(event) => { event.stopPropagation(); if (typeof value === "string") client.post("/api/tasks/open-file", { file_path: value, task_id: taskId }).catch(() => { }); }}
                  className="flex w-full items-center gap-2 rounded-md border border-emerald-500/20 bg-emerald-500/5 px-2 py-1 text-left text-[10px] transition-colors hover:bg-emerald-500/15"
                  title={path}
                >
                  <span className="font-medium text-emerald-600 dark:text-emerald-400">{visibleOutputs.find((port) => port.id === portId)?.label || portId}</span>
                  <span className="min-w-0 flex-1 truncate text-muted-foreground">{filename}</span>
                  {typeof value === "string" && <ExternalLink className="w-3 h-3 flex-shrink-0 text-emerald-600" />}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {status === "failed" && nd.error && (
        <div className="border-t border-border/50 px-3 pb-3 pt-2">
          <div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold text-red-600 dark:text-red-400"><AlertTriangle className="w-3 h-3" />执行错误</div>
          <div className="max-h-20 overflow-y-auto break-all rounded-md border border-red-500/20 bg-red-500/5 px-2 py-1.5 text-[10px] text-red-600 dark:text-red-400">{nd.error}</div>
        </div>
      )}
    </div>
  );
}

/** 生成稳定的文件流 URL，仅在 path 或 refreshKey 变化时添加新的 cache-bust 时间戳；
 *  相对产物路径需带上 task_id，让后端相对任务工作区解析（见 /api/files/stream）。 */
function useStableFileUrl(path?: string, taskId?: string, refreshKey?: string): string {
  const cacheRef = useRef<{ key: string; url: string }>({ key: "", url: "" });
  return useMemo(() => {
    if (!path) return "";
    const compositeKey = `${path}|${taskId || ""}|${refreshKey || ""}`;
    if (cacheRef.current.key === compositeKey) return cacheRef.current.url;
    const params = new URLSearchParams({ path });
    if (taskId) params.set("task_id", taskId);
    params.set("t", String(Date.now()));
    const url = `/api/files/stream?${params.toString()}`;
    cacheRef.current = { key: compositeKey, url };
    return url;
  }, [path, taskId, refreshKey]);
}

// 将上游列表输入（字符串 / JSON / 对象数组）归一化为路径数组
function normalizeListPaths(raw: any): string[] {
  if (!raw) return [];
  let arr: any = raw;
  if (typeof raw === "string") {
    try {
      arr = JSON.parse(raw);
    } catch {
      return [];
    }
  }
  if (!Array.isArray(arr)) return [];
  const paths: string[] = [];
  for (const item of arr) {
    if (typeof item === "string") paths.push(item);
    else if (item && typeof item === "object") {
      const p = item.path || item.file || item.filepath || item.src || item.url || item.value;
      if (typeof p === "string") paths.push(p);
    }
  }
  return paths;
}

function ListVideoItem({ path, taskId, refreshKey }: { path: string; taskId?: string; refreshKey?: string }) {
  const src = useStableFileUrl(path, taskId, refreshKey);
  return (
    <div className="rounded-lg overflow-hidden bg-black">
      <video src={src} controls className="w-full max-h-[200px]" />
    </div>
  );
}

function ListImageItem({ path, config, refreshKey, taskId }: { path: string; config: Record<string, any>; refreshKey?: string; taskId?: string }) {
  const src = useStableFileUrl(path, taskId, refreshKey);
  const [broken, setBroken] = useState(false);
  useEffect(() => { setBroken(false); }, [src]);
  return (
    <div className="rounded-lg overflow-hidden bg-black/5">
      {broken ? (
        <div className="grid h-[120px] place-items-center text-[11px] text-muted-foreground/70">{path || "预览文件不存在或已删除"}</div>
      ) : (
        <img
          src={src}
          alt="Preview"
          className="w-full max-h-[200px]"
          style={{ objectFit: config.fit || "contain" }}
          onError={() => setBroken(true)}
        />
      )}
    </div>
  );
}

function VideoPreview({ config, videoPath, subtitlePath, listPaths, taskId, onConfigChange, refreshKey }: { config: Record<string, any>; videoPath?: string; subtitlePath?: string; listPaths?: string[]; taskId?: string; onConfigChange?: (key: string, value: any) => void; refreshKey?: string }) {
  const [fontSize, setFontSize] = useState(config.fontSize || 12);
  const [subtitles, setSubtitles] = useState<{ start: number; end: number; text: string }[]>([]);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const videoSrc = useStableFileUrl(videoPath, taskId, refreshKey);

  // 阻止节点内输入元素的拖拽和滚轮事件冒泡到 React Flow（原生捕获阶段）
  const previewRef = useCallback((node: HTMLDivElement | null) => {
    if (!node) return;
    const stop = (e: Event) => e.stopPropagation();
    const opts: AddEventListenerOptions = { capture: true };
    for (const el of node.querySelectorAll("input, textarea, select")) {
      el.addEventListener("pointerdown", stop, opts);
      el.addEventListener("wheel", stop, opts);
    }
  }, []);

  useEffect(() => {
    setFontSize(config.fontSize || 12);
  }, [config.fontSize]);

  useEffect(() => {
    if (!subtitlePath) {
      setSubtitles([]);
      return;
    }
    client.get("/api/files/read", { params: { path: subtitlePath, task_id: taskId || undefined } }).then((res) => {
      const content = res.data?.content || "";
      const parsed = parseSRT(content);
      setSubtitles(parsed);
    }).catch(() => setSubtitles([]));
  }, [subtitlePath, taskId]);

  const parseSRT = (srt: string) => {
    const blocks = srt.trim().split(/\n\s*\n/);
    return blocks.map((block) => {
      const lines = block.trim().split("\n");
      if (lines.length < 3) return null;
      const timeMatch = lines[1].match(/(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})/);
      if (!timeMatch) return null;
      const start = parseInt(timeMatch[1]) * 3600 + parseInt(timeMatch[2]) * 60 + parseInt(timeMatch[3]) + parseInt(timeMatch[4]) / 1000;
      const end = parseInt(timeMatch[5]) * 3600 + parseInt(timeMatch[6]) * 60 + parseInt(timeMatch[7]) + parseInt(timeMatch[8]) / 1000;
      const text = lines.slice(2).join("\n");
      return { start, end, text };
    }).filter(Boolean) as { start: number; end: number; text: string }[];
  };

  const currentSub = subtitles.find((s) => currentTime >= s.start && currentTime <= s.end);

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  };

  const togglePlay = () => {
    if (!videoRef.current) return;
    if (isPlaying) {
      videoRef.current.pause();
    } else {
      videoRef.current.play();
    }
    setIsPlaying(!isPlaying);
  };

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!videoRef.current) return;
    const time = parseFloat(e.target.value);
    videoRef.current.currentTime = time;
    setCurrentTime(time);
  };

  const toggleFullscreen = () => {
    if (!containerRef.current) return;
    if (!document.fullscreenElement) {
      containerRef.current.requestFullscreen().then(() => setIsFullscreen(true)).catch(() => { });
    } else {
      document.exitFullscreen().then(() => setIsFullscreen(false)).catch(() => { });
    }
  };

  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", handleFullscreenChange);
  }, []);

  // 列表输入：竖向依次展示多个视频（即便未单独连接视频输入也生效）
  if (listPaths && listPaths.length > 0) {
    return (
      <div className="px-3 pb-3 border-t border-border/50 pt-2 space-y-3">
        <div className="text-[11px] font-medium text-muted-foreground">列表视频预览（共 {listPaths.length} 个）</div>
        {listPaths.map((p, i) => (
          <ListVideoItem key={i} path={p} taskId={taskId} refreshKey={refreshKey} />
        ))}
      </div>
    );
  }

  if (!videoPath) {
    return (
      <div className="px-3 pb-3 border-t border-border/50 pt-2">
        <div className="text-[11px] text-muted-foreground/70 text-center py-4">请连接视频输入</div>
      </div>
    );
  }

  return (
    <div ref={previewRef} className="px-3 pb-3 border-t border-border/50 pt-2 space-y-2">
      {/* 标题输入框 */}
      <div className="flex items-center gap-2">
        <label className="text-[11px] font-medium text-muted-foreground whitespace-nowrap">标题</label>
        <input
          type="text"
          value={config.title || ""}
          onChange={(e) => onConfigChange?.("title", e.target.value)}
          placeholder="输入视频标题..."
          onPointerDown={(e) => e.stopPropagation()}
          onWheel={(e) => e.stopPropagation()}
          className="flex-1 h-6 text-[11px] px-2 rounded border border-border/50 bg-background focus:border-primary/50 focus:outline-none"
        />
      </div>
      {/* 字幕设置并排显示 */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <label className="text-[11px] font-medium text-muted-foreground">字幕字号</label>
          <button
            onClick={() => setFontSize((s: number) => Math.max(12, s - 2))}
            className="px-1.5 py-0.5 text-[10px] rounded bg-secondary/50 hover:bg-secondary transition-colors"
          >A-</button>
          <span className="text-[11px] font-mono w-6 text-center">{fontSize}</span>
          <button
            onClick={() => setFontSize((s: number) => Math.min(72, s + 2))}
            className="px-1.5 py-0.5 text-[10px] rounded bg-secondary/50 hover:bg-secondary transition-colors"
          >A+</button>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-[11px] font-medium text-muted-foreground">字幕位置</label>
          <select
            value={config.subtitlePosition || "bottom"}
            onChange={(e) => onConfigChange?.("subtitlePosition", e.target.value)}
            onPointerDown={(e) => e.stopPropagation()}
            onWheel={(e) => e.stopPropagation()}
            className="h-6 text-[11px] px-1.5 rounded border border-border/50 bg-background focus:border-primary/50 focus:outline-none"
          >
            <option value="top">顶部</option>
            <option value="middle">中间</option>
            <option value="bottom">底部</option>
          </select>
        </div>
      </div>
      <div ref={containerRef} className={`relative rounded-lg overflow-hidden bg-black group ${isFullscreen ? "w-full h-full flex items-center justify-center" : ""}`}>
        <video
          ref={videoRef}
          src={videoSrc}
          className={`w-full object-contain ${isFullscreen ? "max-h-full" : "max-h-[200px]"}`}
          onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
          onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
          onPlay={() => setIsPlaying(true)}
          onPause={() => setIsPlaying(false)}
        />
        {currentSub && (
          <div
            className="absolute left-0 right-0 text-center px-2 pointer-events-none"
            style={{
              [config.subtitlePosition === "top" ? "top" : config.subtitlePosition === "middle" ? "top" : "bottom"]: config.subtitlePosition === "middle" ? "50%" : "8px",
              transform: config.subtitlePosition === "middle" ? "translateY(-50%)" : undefined,
              fontSize: `${fontSize}px`,
              color: config.fontColor || "#ffffff",
              fontFamily: config.fontFamily || "sans-serif",
              textShadow: "1px 1px 2px rgba(0,0,0,0.8)",
            }}
          >
            <span className="bg-black/60 px-2 py-0.5 rounded" style={{ whiteSpace: "pre-line" }}>{currentSub.text}</span>
          </div>
        )}
        {/* 全屏按钮 */}
        <button
          onClick={toggleFullscreen}
          className="absolute bottom-2 right-2 w-7 h-7 rounded-md flex items-center justify-center bg-black/50 text-white/80 hover:bg-black/70 hover:text-white transition-all opacity-0 group-hover:opacity-100"
          title="全屏播放"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
          </svg>
        </button>
        <div className="absolute bottom-0 left-0 right-0 flex items-center gap-2 px-3 py-2 bg-gradient-to-t from-black/80 to-transparent pt-5 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
          <button
            onClick={togglePlay}
            className="w-7 h-7 rounded-full flex items-center justify-center bg-white/15 text-white hover:bg-white/25 transition-colors"
            title={isPlaying ? "暂停" : "播放"}
            aria-label={isPlaying ? "暂停" : "播放"}
          >
            {isPlaying ? (
              <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
                <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z" />
              </svg>
            ) : (
              <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
                <path d="M8 5v14l11-7z" />
              </svg>
            )}
          </button>
          <span className="text-[10px] font-mono text-white/80 w-10">{formatTime(currentTime)}</span>
          <input
            type="range"
            min={0}
            max={duration || 0}
            step={0.1}
            value={currentTime}
            onChange={handleSeek}
            onPointerDown={(e) => e.stopPropagation()}
            onWheel={(e) => e.stopPropagation()}
            aria-label="视频播放进度"
            className="flex-1 h-1 rounded-full appearance-none cursor-pointer accent-primary bg-white/30"
          />
          <span className="text-[10px] font-mono text-white/80 w-10 text-right">{formatTime(duration)}</span>
        </div>
      </div>
      {!subtitlePath && (
        <div className="text-[10px] text-muted-foreground/70 text-center">连接字幕输入以显示字幕</div>
      )}
    </div>
  );
}

function ImagePreview({ config, imagePath, listPaths, taskId, refreshKey }: { config: Record<string, any>; imagePath?: string; listPaths?: string[]; taskId?: string; refreshKey?: string }) {
  const imageSrc = useStableFileUrl(imagePath, taskId, refreshKey);
  const [broken, setBroken] = useState(false);
  useEffect(() => { setBroken(false); }, [imageSrc]);
  // 列表输入：竖向依次展示多张图片（即便未单独连接图片输入也生效）
  if (listPaths && listPaths.length > 0) {
    return (
      <div className="px-3 pb-3 border-t border-border/50 pt-2 space-y-3">
        <div className="text-[11px] font-medium text-muted-foreground">列表图片预览（共 {listPaths.length} 张）</div>
        {listPaths.map((p, i) => (
          <ListImageItem key={i} path={p} config={config} refreshKey={refreshKey} taskId={taskId} />
        ))}
      </div>
    );
  }

  if (!imagePath) {
    return (
      <div className="px-3 pb-3 border-t border-border/50 pt-2">
        <div className="text-[11px] text-muted-foreground/70 text-center py-4">请连接图片输入</div>
      </div>
    );
  }

  return (
    <div className="px-3 pb-3 border-t border-border/50 pt-2">
      <div className="rounded-lg overflow-hidden bg-black/5">
        {broken ? (
          <div className="grid h-[120px] place-items-center text-[11px] text-muted-foreground/70">预览文件不存在或已删除</div>
        ) : (
          <img
            src={imageSrc}
            alt="Preview"
            className="w-full max-h-[200px]"
            style={{ objectFit: config.fit || "contain" }}
            onError={() => setBroken(true)}
          />
        )}
      </div>
    </div>
  );
}

function ImageCompare({ config, image1Path, image2Path, taskId, refreshKey }: { config: Record<string, any>; image1Path?: string; image2Path?: string; taskId?: string; refreshKey?: string }) {
  const [pos, setPos] = useState(50); // 分割线位置（%），默认居中，上层（图片2）显示右半部
  const containerRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef(false);

  const src1 = useStableFileUrl(image1Path, taskId, refreshKey);
  const src2 = useStableFileUrl(image2Path, taskId, refreshKey);

  const updateFromClientX = (clientX: number) => {
    const el = containerRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const p = ((clientX - rect.left) / rect.width) * 100;
    setPos(Math.max(0, Math.min(100, p)));
  };

  const onPointerDown = (e: React.PointerEvent) => {
    draggingRef.current = true;
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    updateFromClientX(e.clientX);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!draggingRef.current) return;
    updateFromClientX(e.clientX);
  };
  const onPointerUp = (e: React.PointerEvent) => {
    draggingRef.current = false;
    (e.target as HTMLElement).releasePointerCapture?.(e.pointerId);
  };

  if (!image1Path && !image2Path) {
    return (
      <div className="px-3 pb-3 border-t border-border/50 pt-2">
        <div className="text-[11px] text-muted-foreground/70 text-center py-4">请连接图片1 / 图片2 输入</div>
      </div>
    );
  }

  return (
    <div className="px-3 pb-3 border-t border-border/50 pt-2">
      <div className="text-[11px] font-medium text-muted-foreground mb-2">图片对比（图片2在上 · 拖动分割线对比）</div>
      <div
        ref={containerRef}
        className="relative w-full rounded-lg overflow-hidden bg-black/5 select-none cursor-ew-resize"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
      >
        {/* 下层：图片1 */}
        {image1Path && (
          <img src={src1} alt="图片1" className="block w-full" style={{ objectFit: config.fit || "contain" }} draggable={false} />
        )}
        {/* 上层：图片2，蒙版只显示分割线右侧 */}
        {image2Path && (
          <img
            src={src2}
            alt="图片2"
            className="absolute inset-0 w-full h-full pointer-events-none"
            style={{ objectFit: config.fit || "contain", clipPath: `inset(0 0 0 ${pos}%)` }}
            draggable={false}
          />
        )}
        {/* 分割线 + 手柄 */}
        <div className="absolute top-0 bottom-0 w-0.5 bg-white/90 pointer-events-none" style={{ left: `${pos}%` }}>
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-5 h-5 rounded-full bg-white/90 flex items-center justify-center text-[10px] text-black/70 shadow">
            ⇄
          </div>
        </div>
      </div>
    </div>
  );
}

function ApiSelectField({ field, value, config, onConfigChange }: { field: ConfigField; value: string; config: Record<string, any>; onConfigChange: (key: string, value: any) => void }) {
  const [apiOptions, setApiOptions] = useState<{ value: string; label: string; description?: string }[]>([]);
  const [apiLoading, setApiLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [hoveredOption, setHoveredOption] = useState<string | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Resolve dynamic API endpoint with parameter substitution
  const resolveEndpoint = (endpoint: string): string => {
    if (!endpoint) return "";
    return endpoint.replace(/\{(\w+)\}/g, (_, key) => {
      const val = config[key];
      // Handle array values (e.g., tts_mode is ["preset_voice"])
      if (Array.isArray(val)) {
        return val[0] || "";
      }
      return val || "";
    });
  };

  const rawEndpoint = field.apiEndpoint || field.apiUrl || "";
  const fetchKey = resolveEndpoint(rawEndpoint);
  const dependsValue = config[field.dependsOn || ""];

  useEffect(() => {
    if (fetchKey && !fetchKey.includes("{")) {
      setApiLoading(true);
      client.get(fetchKey).then((res) => {
        const resData = res.data || {};
        let allItems: { value: string; label: string; description?: string }[] = [];
        const optionLabel = field.optionLabel || "label";
        const optionValue = field.optionValue || "value";

        const mapOptionList = (items: any[]) => items.map((item) => {
          if (typeof item === "string") {
            return { value: item, label: item, description: "" };
          }
          const mappedValue = item?.[optionValue] ?? item?.value ?? item?.id ?? item?.name;
          const mappedLabel = item?.[optionLabel] ?? item?.label ?? item?.name ?? mappedValue;
          const mappedDesc = item?.description ?? "";
          return { value: String(mappedValue ?? ""), label: String(mappedLabel ?? ""), description: String(mappedDesc) };
        }).filter((item) => item.value);

        if (Array.isArray(resData)) {
          allItems = mapOptionList(resData);
        } else if (Array.isArray(resData.options)) {
          allItems = mapOptionList(resData.options);
        } else if (Array.isArray(resData.items)) {
          allItems = mapOptionList(resData.items);
        } else if (Array.isArray(resData.presets)) {
          allItems = mapOptionList(resData.presets);
        } else if (Array.isArray(resData.voices)) {
          allItems = mapOptionList(resData.voices);
        }

        // Handle { interfaces: [...] } shape (from /enabled or /asr-interfaces)
        if (!allItems.length && resData.interfaces && Array.isArray(resData.interfaces)) {
          for (const iface of resData.interfaces) {
            allItems.push({ value: iface.id, label: iface.name, description: iface.description || "" });
          }
        } else if (!allItems.length) {
          // Handle { models_by_engine: {...} } or { models: {...} } shape
          const engineKey = config[field.dependsOn || ""] || "";

          // Check for model_details_by_engine first (for separation models with descriptions)
          if (resData.model_details_by_engine && resData.model_details_by_engine[engineKey]) {
            allItems = resData.model_details_by_engine[engineKey];
          } else {
            let optionsMap = resData.models_by_engine || resData.models || resData.options || {};
            if (field.key === "compute_type" && resData.compute_types_by_engine) {
              optionsMap = resData.compute_types_by_engine;
            }
            const items: string[] = optionsMap[engineKey] || [];
            allItems = items.map((m: string) => ({ value: m, label: m, description: "" }));
            if (!engineKey) {
              const merged: Record<string, boolean> = {};
              for (const arr of Object.values(optionsMap) as string[][]) {
                for (const m of arr) { if (!merged[m]) { merged[m] = true; allItems.push({ value: m, label: m, description: "" }); } }
              }
            }
          }
        }
        const uniqueItems = Array.from(new Map(allItems.map((item) => [item.value, item])).values());
        setApiOptions(uniqueItems);

        // If current value is not in the new options, clear it
        if (value && !uniqueItems.some((opt) => opt.value === value)) {
          onConfigChange(field.key, "");
        }
      }).catch(() => { }).finally(() => setApiLoading(false));
    }
  }, [fetchKey, dependsValue, config.tts_engine]);

  const selectedLabel = apiOptions.find(opt => opt.value === value)?.label || (apiLoading ? "加载中..." : field.placeholder || "请选择");
  const hasDescriptions = apiOptions.some(opt => opt.description);

  // If no descriptions, use native select for better UX
  if (!hasDescriptions) {
    return (
      <div>
        <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
        <select
          value={value}
          onChange={(e) => onConfigChange(field.key, e.target.value)}
          onPointerDown={(e) => e.stopPropagation()}
          onWheel={(e) => e.stopPropagation()}
          className="w-full text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background focus:border-primary/50 outline-none transition-all"
        >
          <option value="">{apiLoading ? "加载中..." : field.placeholder || "请选择"}</option>
          {apiOptions.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </div>
    );
  }

  // Custom dropdown with tooltip support
  return (
    <div className="relative" ref={dropdownRef}>
      <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        onPointerDown={(e) => e.stopPropagation()}
        className="w-full text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background focus:border-primary/50 outline-none transition-all text-left flex items-center justify-between"
      >
        <span className={!value ? "text-muted-foreground/70" : ""}>{selectedLabel}</span>
        <ChevronDown className={`w-3 h-3 text-muted-foreground/70 transition-transform ${isOpen ? "rotate-180" : ""}`} />
      </button>
      {isOpen && (
        <div className="absolute z-50 w-full mt-1 bg-background border border-border/50 rounded-md shadow-lg max-h-[200px] overflow-y-auto">
          {apiOptions.map((opt) => (
            <div
              key={opt.value}
              onMouseEnter={() => setHoveredOption(opt.value)}
              onMouseLeave={() => setHoveredOption(null)}
              onClick={() => {
                onConfigChange(field.key, opt.value);
                setIsOpen(false);
              }}
              className={`px-2.5 py-1.5 text-xs cursor-pointer hover:bg-primary/10 ${opt.value === value ? "bg-primary/10 text-primary" : ""}`}
            >
              <div>{opt.label}</div>
              {hoveredOption === opt.value && opt.description && (
                <div className="text-[10px] text-muted-foreground/80 mt-1 border-t border-border/50 pt-1">{opt.description}</div>
              )}
            </div>
          ))}
          {apiOptions.length === 0 && !apiLoading && (
            <div className="px-2.5 py-1.5 text-xs text-muted-foreground/70">无可用选项</div>
          )}
        </div>
      )}
    </div>
  );
}

/** 账号选择弹窗组件 - 按平台分组，支持全选/取消全选/清空 */
function AccountSelectField({ field, value, onConfigChange }: { field: ConfigField; value: string[]; onConfigChange: (key: string, value: any) => void }) {
  const [open, setOpen] = useState(false);
  const [accounts, setAccounts] = useState<{ value: string; label: string; platform: string; name: string; type: number }[]>([]);
  const [loading, setLoading] = useState(false);
  const selected: string[] = Array.isArray(value) ? value : [];

  const fetchAccounts = () => {
    setLoading(true);
    const endpoint = field.apiEndpoint || "/api/publish/accounts/all";
    client.get(endpoint).then((res) => {
      const data = res.data || {};
      const items = data.options || data.items || data || [];
      setAccounts(Array.isArray(items) ? items : []);
    }).catch(() => setAccounts([])).finally(() => setLoading(false));
  };

  const handleOpen = () => {
    setOpen(true);
    fetchAccounts();
  };

  // 按平台分组
  const grouped = accounts.reduce<Record<string, typeof accounts>>((acc, item) => {
    const key = item.platform || "未知平台";
    (acc[key] ??= []).push(item);
    return acc;
  }, {});

  const toggleAccount = (val: string) => {
    const next = selected.includes(val) ? selected.filter((v) => v !== val) : [...selected, val];
    onConfigChange(field.key, next);
  };

  const selectAll = () => onConfigChange(field.key, accounts.map((a) => a.value));
  const deselectAll = () => onConfigChange(field.key, []);
  const togglePlatform = (platform: string) => {
    const platformVals = (grouped[platform] || []).map((a) => a.value);
    const allSelected = platformVals.every((v) => selected.includes(v));
    if (allSelected) {
      onConfigChange(field.key, selected.filter((v) => !platformVals.includes(v)));
    } else {
      const newSet = new Set([...selected, ...platformVals]);
      onConfigChange(field.key, [...newSet]);
    }
  };

  const btnLabel = selected.length > 0
    ? `已选 ${selected.length} 个账号`
    : field.placeholder || "点击选择发布账号";

  return (
    <>
      <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
      <button
        type="button"
        onClick={handleOpen}
        onPointerDown={(e) => e.stopPropagation()}
        className={cn(
          "w-full text-xs px-2.5 py-1.5 rounded-md border text-left transition-all flex items-center gap-2",
          selected.length > 0
            ? "border-primary/50 bg-primary/5 text-foreground"
            : "border-border/50 bg-background text-muted-foreground"
        )}
      >
        <Users className="w-3.5 h-3.5 flex-shrink-0" />
        <span className="truncate">{btnLabel}</span>
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onPointerDown={(e) => e.stopPropagation()}>
          <div className="bg-card border border-border/50 rounded-xl shadow-2xl w-[480px] max-h-[70vh] flex flex-col" onPointerDown={(e) => e.stopPropagation()}>
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-border/50">
              <span className="text-sm font-semibold">选择发布账号</span>
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-muted-foreground">已选 {selected.length}/{accounts.length}</span>
                <button onClick={() => setOpen(false)} className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary/60 transition-colors">
                  <XCircle className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* Action buttons */}
            <div className="flex items-center gap-2 px-4 py-2 border-b border-border/50">
              <button onClick={selectAll} className="px-2 py-1 text-[11px] rounded-md bg-primary/10 text-primary hover:bg-primary/20 transition-colors">全选</button>
              <button onClick={deselectAll} className="px-2 py-1 text-[11px] rounded-md bg-secondary/60 text-muted-foreground hover:bg-secondary transition-colors">取消全选</button>
              <button onClick={() => onConfigChange(field.key, [])} className="px-2 py-1 text-[11px] rounded-md bg-red-500/10 text-red-500 hover:bg-red-500/20 transition-colors">清空</button>
            </div>

            {/* Account list */}
            <div className="flex-1 overflow-y-auto px-4 py-2 space-y-3">
              {loading && (
                <div className="text-center py-6 text-[11px] text-muted-foreground">加载中...</div>
              )}
              {!loading && accounts.length === 0 && (
                <div className="text-center py-6 text-[11px] text-muted-foreground">请到发布标签页添加账号</div>
              )}
              {!loading && Object.entries(grouped).map(([platform, items]) => {
                const platformVals = items.map((a) => a.value);
                const allChecked = platformVals.every((v) => selected.includes(v));
                const someChecked = platformVals.some((v) => selected.includes(v));
                return (
                  <div key={platform}>
                    <div
                      className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-secondary/30 cursor-pointer hover:bg-secondary/50 transition-colors select-none"
                      onClick={() => togglePlatform(platform)}
                    >
                      {allChecked ? (
                        <CheckSquare className="w-3.5 h-3.5 text-primary" />
                      ) : someChecked ? (
                        <div className="w-3.5 h-3.5 rounded-sm border-2 border-primary bg-primary/30" />
                      ) : (
                        <Square className="w-3.5 h-3.5 text-muted-foreground/50" />
                      )}
                      <span className="text-[11px] font-semibold text-foreground">{platform}</span>
                      <span className="text-[10px] text-muted-foreground ml-auto">
                        {items.filter((a) => selected.includes(a.value)).length}/{items.length}
                      </span>
                    </div>
                    <div className="ml-4 space-y-0.5 mt-1">
                      {items.map((acc) => {
                        const checked = selected.includes(acc.value);
                        return (
                          <div
                            key={acc.value}
                            className="flex items-center gap-2 px-2 py-1 rounded-md cursor-pointer hover:bg-secondary/30 transition-colors select-none"
                            onClick={() => toggleAccount(acc.value)}
                          >
                            {checked ? (
                              <CheckSquare className="w-3.5 h-3.5 text-primary" />
                            ) : (
                              <Square className="w-3.5 h-3.5 text-muted-foreground/50" />
                            )}
                            <span className="text-[11px] text-foreground">{acc.name}</span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Footer */}
            <div className="flex justify-end px-4 py-3 border-t border-border/50">
              <button
                onClick={() => setOpen(false)}
                className="px-3 py-1.5 text-xs font-medium rounded-md bg-primary text-primary-foreground hover:opacity-90 transition-opacity"
              >
                确定
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function ConfigForm({ nodeType, config, onConfigChange, onVoiceSelect, onButtonAction }: {
  nodeType: any;
  config: Record<string, any>;
  onConfigChange: (key: string, value: any) => void;
  onVoiceSelect?: (field: ConfigField) => void;
  onButtonAction?: (field: ConfigField) => void;
}) {
  const [dynamicFields, setDynamicFields] = useState<ConfigField[]>([]);
  const [dynamicLoading, setDynamicLoading] = useState(false);
  const [expandField, setExpandField] = useState<{ key: string; label: string; value: string } | null>(null);
  const [audioSelectorOpen, setAudioSelectorOpen] = useState(false);
  const [audioSelectorField, setAudioSelectorField] = useState<{ key: string; label: string } | null>(null);
  const [actionState, setActionState] = useState<Record<string, { busy: boolean; ok?: boolean; message?: string }>>({});
  const modalTextareaRef = useRef<HTMLTextAreaElement>(null);
  const textareaRefs = useRef<Record<string, HTMLTextAreaElement | null>>({});
  const [piSkillOptions, setPiSkillOptions] = useState<{ value: string; label: string }[]>([]);
  const [piMcpOptions, setPiMcpOptions] = useState<{ value: string; label: string }[]>([]);
  const [picker, setPicker] = useState<{ kind: PickerKind; label: string; open: boolean } | null>(null);

  // pi_agent：从小π Agent 设置拉取已授权 Skill/MCP 选项
  useEffect(() => {
    if (nodeType.id !== "pi_agent") return;
    client.get("/api/pi/settings").then((res) => {
      const data = (res.data || {}) as { skills?: { name: string }[]; mcps?: { name: string }[] };
      setPiSkillOptions((data.skills || []).map((item) => ({ value: item.name, label: item.name })));
      setPiMcpOptions((data.mcps || []).map((item) => ({ value: item.name, label: item.name })));
    }).catch(() => undefined);
  }, [nodeType.id]);

  // chips 动作按钮：调用后端接口（如安装即梦插件）
  const handleChipAction = useCallback(async (field: ConfigField) => {
    const act = field.action;
    if (!act) return;
    setActionState((s) => ({ ...s, [field.key]: { busy: true } }));
    try {
      const res = (act.method || "POST").toLowerCase() === "get"
        ? await client.get(act.url)
        : await client.post(act.url);
      const data = (res.data as any) || {};
      const ok = !!data.installed;
      setActionState((s) => ({
        ...s,
        [field.key]: { busy: false, ok, message: data.message || data.detail || (ok ? "已完成" : "未完成") },
      }));
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.message || "请求失败";
      setActionState((s) => ({ ...s, [field.key]: { busy: false, ok: false, message: msg } }));
    }
  }, []);

  // 弹窗 textarea 原生事件拦截（阻止 React Flow 全局拖拽）
  useEffect(() => {
    const el = modalTextareaRef.current;
    if (!el) return;
    const stop = (e: Event) => e.stopPropagation();
    const opts: AddEventListenerOptions = { capture: true };
    el.addEventListener("pointerdown", stop, opts);
    el.addEventListener("mousedown", stop, opts);
    el.addEventListener("wheel", stop, opts);
    return () => {
      el.removeEventListener("pointerdown", stop, opts);
      el.removeEventListener("mousedown", stop, opts);
      el.removeEventListener("wheel", stop, opts);
    };
  }, [expandField]);

  // 阻止节点内输入元素的拖拽和滚轮事件冒泡到 React Flow（原生捕获阶段）
  const formRef = useCallback((node: HTMLDivElement | null) => {
    if (!node) return;
    const stop = (e: Event) => e.stopPropagation();
    const opts: AddEventListenerOptions = { capture: true };
    for (const el of node.querySelectorAll("input, textarea, select")) {
      el.addEventListener("pointerdown", stop, opts);
      el.addEventListener("wheel", stop, opts);
    }
  }, []);

  // Fetch dynamic config fields from API if nodeType has dynamicConfigEndpoint
  useEffect(() => {
    const endpoint = nodeType.dynamicConfigEndpoint;
    if (endpoint) {
      setDynamicLoading(true);
      client.get(endpoint).then((res) => {
        const data = res.data;
        // Build config fields from API response
        const fields: ConfigField[] = [];
        if (data.engine_options) {
          fields.push({ key: "engine", label: "ASR 引擎", type: "select", colSpan: "half", placeholder: "跟随全局配置", options: data.engine_options });
        }
        if (data.models_by_engine) {
          fields.push({ key: "model", label: "模型", type: "api-select", colSpan: "half", apiEndpoint: endpoint, dependsOn: "engine", placeholder: "跟随引擎默认" });
        }
        if (data.compute_types_by_engine) {
          fields.push({ key: "compute_type", label: "计算精度", type: "api-select", colSpan: "half", apiEndpoint: endpoint, dependsOn: "engine", placeholder: "跟随全局配置" });
        }
        // Common ASR fields
        fields.push({
          key: "language", label: "识别语言", type: "select", colSpan: "half", placeholder: "跟随输入节点", options: [
            { value: "from_input", label: "来自输入节点" },
            { value: "auto", label: "自动检测(auto)" },
            { value: "zh", label: "中文 (zh)" },
            { value: "en", label: "英语 (en)" },
            { value: "ja", label: "日语 (ja)" },
            { value: "ko", label: "韩语 (ko)" },
            { value: "fr", label: "法语 (fr)" },
            { value: "de", label: "德语 (de)" },
            { value: "es", label: "西班牙语 (es)" },
            { value: "pt", label: "葡萄牙语 (pt)" },
            { value: "ru", label: "俄语 (ru)" },
          ]
        });
        fields.push({ key: "batch_size", label: "批处理大小", type: "text", placeholder: "0=自动检测GPU显存" });
        fields.push({ key: "word_timestamps", label: "启用词级时间戳对齐", type: "checkbox" });
        fields.push({ key: "vad_onset", label: "VAD 起始阈值", type: "text", placeholder: "0.500" });
        fields.push({ key: "vad_offset", label: "VAD 结束阈值", type: "text", placeholder: "0.363" });
        setDynamicFields(fields);
      }).catch(() => { }).finally(() => setDynamicLoading(false));
    }
  }, []);

  const configFields = (() => {
    const base = (dynamicFields.length > 0 ? dynamicFields : nodeType.configFields) || [];
    if (nodeType.id !== "pi_agent") return base;
    return base
      .filter((field: ConfigField) => field.key !== "inputCount" && field.key !== "outputCount")
      .map((field: ConfigField) => {
        if (field.key === "skills" && piSkillOptions.length) return { ...field, options: piSkillOptions };
        if (field.key === "mcps" && piMcpOptions.length) return { ...field, options: piMcpOptions };
        return field;
      });
  })();
  // LCWR 去水印节点使用自定义编辑器（LcwrWatermarkEditor），跳过通用表单渲染
  if (nodeType.id === "lcwr_watermark_removal") return null;
  if (configFields.length === 0 && !dynamicLoading) return null;

  const fieldSpanClass = (field: ConfigField) => {
    if (field.colSpan === "half") return "col-span-3";
    if (field.colSpan === "third") return "col-span-2";
    if (nodeType.id === "asr" || nodeType.id === "audio_transcode") return "col-span-3";
    return "col-span-6";
  };

  return (
    <>
      <div ref={formRef} className="px-3 pb-3 grid grid-cols-6 gap-x-3 gap-y-2 border-t border-border/50 pt-2">
        {dynamicLoading && (
          <div className="col-span-2 text-[11px] text-muted-foreground/70 py-1">加载配置中...</div>
        )}
        {configFields.map((field: ConfigField) => {
          if (!isConfigFieldVisible(field, config)) return null;

          // Chips / toggle group
          if (field.type === "chips") {
            const selected: string[] = config[field.key] || [];
            const isSingle = field.singleSelect;
            return (
              <div key={field.key} className={fieldSpanClass(field)}>
                <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
                <div className="flex flex-wrap gap-1.5">
                  {field.options?.map((opt) => {
                    const isSelected = selected.includes(opt.value);
                    const chipColor = CHIP_COLORS[opt.value] || field.chipColor || "#6b7280";
                    return (
                      <button
                        key={opt.value}
                        type="button"
                        onClick={() => {
                          let next: string[];
                          if (isSingle) {
                            // 单选模式：直接选择当前
                            next = [opt.value];
                          } else {
                            // 多选模式
                            if (isSelected) {
                              next = selected.filter((v) => v !== opt.value);
                              if (next.length === 0) next = [opt.value]; // at least one
                            } else {
                              next = [...selected, opt.value];
                            }
                          }
                          onConfigChange(field.key, next);
                        }}
                        className={cn(
                          "px-3 py-1.5 rounded-lg text-xs font-medium border transition-all duration-150",
                          isSelected
                            ? "text-white shadow-sm"
                            : "text-muted-foreground border-border/50 bg-background hover:border-primary/25"
                        )}
                        style={isSelected ? {
                          backgroundColor: chipColor,
                          borderColor: chipColor,
                          boxShadow: `0 1px 4px ${chipColor}33`,
                        } : undefined}
                      >
                        {opt.label}
                      </button>
                    );
                  })}
                  {field.action && (() => {
                    const st = actionState[field.key];
                    return (
                      <button
                        key="__chips_action__"
                        type="button"
                        disabled={st?.busy}
                        onPointerDown={(e) => e.stopPropagation()}
                        onClick={(e) => { e.stopPropagation(); handleChipAction(field); }}
                        className={cn(
                          "inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all",
                          st?.busy
                            ? "opacity-60 cursor-wait text-purple-500 border-purple-500/40 bg-purple-500/5"
                            : st?.ok
                              ? "text-emerald-600 dark:text-emerald-400 border-emerald-500/40 bg-emerald-500/5 hover:bg-emerald-500/10"
                              : "text-purple-600 dark:text-purple-400 border-purple-500/40 bg-purple-500/5 hover:bg-purple-500/10"
                        )}
                        title={st?.message}
                      >
                        {st?.busy ? (
                          <Loader2 className="w-3 h-3 animate-spin" />
                        ) : st?.ok ? (
                          <CheckCircle2 className="w-3 h-3" />
                        ) : (
                          <Download className="w-3 h-3" />
                        )}
                        {st?.busy ? (field.action.busyLabel || "执行中...") : field.action.label}
                      </button>
                    );
                  })()}
                  {field.link && (
                    <a
                      key="__chips_link__"
                      href={field.link.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      title={field.link.url}
                      onPointerDown={(e) => e.stopPropagation()}
                      onClick={(e) => e.stopPropagation()}
                      className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium text-sky-600 dark:text-sky-400 border border-sky-500/40 bg-sky-500/5 hover:bg-sky-500/10 transition-all"
                    >
                      <ExternalLink className="w-3 h-3" />
                      {field.link.label || "访问"}
                    </a>
                  )}
                </div>
              </div>
            );
          }

          if (field.type === "button") {
            return (
              <div key={field.key} className={fieldSpanClass(field)}>
                {field.description && (
                  <p className="text-[11px] text-muted-foreground mb-1.5 leading-snug">{field.description}</p>
                )}
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); onButtonAction?.(field); }}
                  onPointerDown={(e) => e.stopPropagation()}
                  className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium rounded-md border border-primary/40 bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
                >
                  <FileJson className="w-3.5 h-3.5" />
                  {field.label}
                </button>
              </div>
            );
          }

          const value = config[field.key] ?? "";

          if (field.type === "language-select") {
            return (
              <div key={field.key} className={fieldSpanClass(field)}>
                <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
                <select
                  value={value || "auto"}
                  onChange={(e) => onConfigChange(field.key, e.target.value)}
                  onPointerDown={(e) => e.stopPropagation()}
                  onWheel={(e) => e.stopPropagation()}
                  className="w-full text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background focus:border-primary/50 outline-none transition-all"
                >
                  {LANGUAGE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>
            );
          }

          if (field.type === "file") {
            return (
              <div key={field.key} className={fieldSpanClass(field)}>
                <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
                <div className="flex gap-1">
                  <input
                    type="text"
                    value={value}
                    onChange={(e) => onConfigChange(field.key, e.target.value)}
                    placeholder={field.placeholder}
                    onPointerDown={(e) => e.stopPropagation()}
                    onWheel={(e) => e.stopPropagation()}
                    className="flex-1 text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background focus:border-primary/50 focus:ring-1 focus:ring-primary/20 outline-none transition-all"
                  />
                  <button
                    onClick={async () => {
                      // Determine if this is a folder selector (outputDir, cookie_file, etc.)
                      const isFolder = field.key === "outputDir" || (field.fileFilter && field.fileFilter.length === 0);
                      const filterArr: [string, string][] = (field.fileFilter || []).map((f: string) => [f, f] as [string, string]);
                      const path = await nativeFileDialog(
                        isFolder ? "folder" : "file",
                        field.label || "Select",
                        filterArr
                      );
                      if (path) onConfigChange(field.key, path);
                    }}
                    className="px-2 py-1 text-[10px] rounded-md bg-primary/10 text-primary hover:bg-primary/20 border border-primary/30 transition-colors flex-shrink-0"
                  >
                    Browse
                  </button>
                </div>
              </div>
            );
          }

          if (field.type === "hotwords") {
            return (
              <div key={field.key} className={fieldSpanClass(field)}>
                <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
                <div className="flex gap-1">
                  <textarea
                    value={value}
                    onChange={(e) => onConfigChange(field.key, e.target.value)}
                    placeholder={field.placeholder}
                    onPointerDown={(e) => e.stopPropagation()}
                    onWheel={(e) => e.stopPropagation()}
                    rows={2}
                    className="flex-1 text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background focus:border-primary/50 focus:ring-1 focus:ring-primary/20 outline-none transition-all resize-none"
                  />
                  <button
                    onClick={async () => {
                      const path = await nativeFileDialog("file", "选择热词文件", [["Text", "*.txt"]]);
                      if (typeof path === "string" && path) {
                        try {
                          const res = await client.get("/api/files/read", { params: { path } });
                          const content: string = res.data?.content || "";
                          // Convert newline-separated words to semicolon-separated
                          const hotwords = content.split(/\r?\n/).map(w => w.trim()).filter(Boolean).join(";");
                          onConfigChange(field.key, hotwords);
                        } catch (e) {
                          console.error("Failed to read hotwords file:", e);
                        }
                      }
                    }}
                    className="px-2 py-1 text-[10px] rounded-md bg-primary/10 text-primary hover:bg-primary/20 border border-primary/30 transition-colors flex-shrink-0 self-start mt-0.5"
                  >
                    加载文件
                  </button>
                </div>
              </div>
            );
          }

          if (field.type === "text") {
            // Special handling for path_to_title node's template field
            const isPathTemplate = nodeType.id === "path_to_title" && field.key === "template";
            const pathPlaceholders = [
              { key: "filename", label: "文件名", placeholder: "{filename}" },
              { key: "parent", label: "父文件夹", placeholder: "{parent}" },
              { key: "grandparent", label: "父父文件夹", placeholder: "{grandparent}" },
            ];

            return (
              <div key={field.key} className={fieldSpanClass(field)}>
                <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
                <div className="relative group">
                  <input
                    type="text"
                    value={value}
                    onChange={(e) => onConfigChange(field.key, e.target.value)}
                    placeholder={field.placeholder}
                    onPointerDown={(e) => e.stopPropagation()}
                    onWheel={(e) => e.stopPropagation()}
                    className="w-full text-xs px-2.5 py-1.5 pr-7 rounded-md border border-border/50 bg-background focus:border-primary/50 focus:ring-1 focus:ring-primary/20 outline-none transition-all"
                  />
                  <button
                    onPointerDown={(e) => e.stopPropagation()}
                    onClick={() => setExpandField({ key: field.key, label: field.label, value: value || "" })}
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 p-1 rounded text-muted-foreground/70 hover:text-primary opacity-0 group-hover:opacity-100 transition-opacity"
                    title="放大编辑"
                  >
                    <Maximize2 className="w-3 h-3" />
                  </button>
                </div>
                {isPathTemplate && (
                  <div className="flex flex-wrap gap-1 mt-1.5">
                    {pathPlaceholders.map((p) => (
                      <button
                        key={p.key}
                        type="button"
                        onPointerDown={(e) => e.stopPropagation()}
                        onClick={() => {
                          const newValue = (value || "") + p.placeholder;
                          onConfigChange(field.key, newValue);
                        }}
                        className="px-2 py-0.5 rounded-md text-[10px] font-medium bg-purple-500/10 text-purple-600 hover:bg-purple-500/20 border border-purple-500/30 transition-colors"
                        title={`插入 ${p.placeholder} 到模板`}
                      >
                        {p.label}
                      </button>
                    ))}
                  </div>
                )}
                {field.description && (
                  <p className="text-[10px] text-muted-foreground/70 mt-1">{field.description}</p>
                )}
              </div>
            );
          }

          if (field.type === "datetime-local") {
            return (
              <div key={field.key} className={fieldSpanClass(field)}>
                <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
                <input
                  type="datetime-local"
                  value={value}
                  onChange={(e) => onConfigChange(field.key, e.target.value)}
                  onPointerDown={(e) => e.stopPropagation()}
                  onWheel={(e) => e.stopPropagation()}
                  className="w-full text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background focus:border-primary/50 focus:ring-1 focus:ring-primary/20 outline-none transition-all"
                />
              </div>
            );
          }

          if (field.type === "date") {
            return (
              <div key={field.key} className={fieldSpanClass(field)}>
                <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
                <input
                  type="date"
                  value={value}
                  onChange={(e) => onConfigChange(field.key, e.target.value)}
                  onPointerDown={(e) => e.stopPropagation()}
                  onWheel={(e) => e.stopPropagation()}
                  className="w-full text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background focus:border-primary/50 focus:ring-1 focus:ring-primary/20 outline-none transition-all"
                />
              </div>
            );
          }

          if (field.type === "time") {
            return (
              <div key={field.key} className={fieldSpanClass(field)}>
                <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
                <input
                  type="time"
                  value={value}
                  onChange={(e) => onConfigChange(field.key, e.target.value)}
                  onPointerDown={(e) => e.stopPropagation()}
                  onWheel={(e) => e.stopPropagation()}
                  className="w-full text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background focus:border-primary/50 focus:ring-1 focus:ring-primary/20 outline-none transition-all"
                />
              </div>
            );
          }

          if (field.type === "textarea") {
            return (
              <div key={field.key} className={fieldSpanClass(field)}>
                <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
                {field.chips && field.chips.length > 0 && (
                  <div className="flex flex-wrap gap-1 mb-1.5">
                    {field.chips.map((chip) => (
                      <button
                        key={chip.value}
                        type="button"
                        onClick={() => {
                          const textarea = textareaRefs.current[field.key];
                          const cur = typeof value === "string" ? value : "";
                          const start = textarea?.selectionStart ?? cur.length;
                          const end = textarea?.selectionEnd ?? cur.length;
                          onConfigChange(field.key, cur.slice(0, start) + chip.value + cur.slice(end));
                          requestAnimationFrame(() => {
                            textarea?.focus();
                            textarea?.setSelectionRange(start + chip.value.length, start + chip.value.length);
                          });
                        }}
                        className="px-2 py-0.5 text-[10px] rounded-full border border-primary/30 bg-primary/10 text-primary hover:bg-primary/20 transition-colors cursor-pointer"
                        title={`插入 ${chip.value}`}
                      >
                        {chip.label}
                      </button>
                    ))}
                  </div>
                )}
                <div className="relative group">
                  <textarea
                    ref={(element) => { textareaRefs.current[field.key] = element; }}
                    value={value}
                    onChange={(e) => onConfigChange(field.key, e.target.value)}
                    placeholder={field.placeholder}
                    rows={3}
                    onPointerDown={(e) => e.stopPropagation()}
                    onWheel={(e) => e.stopPropagation()}
                    className="w-full text-xs px-2.5 py-1.5 pr-7 rounded-md border border-border/50 bg-background focus:border-primary/50 focus:ring-1 focus:ring-primary/20 outline-none transition-all resize-none"
                  />
                  <button
                    onPointerDown={(e) => e.stopPropagation()}
                    onClick={() => setExpandField({ key: field.key, label: field.label, value: value || "" })}
                    className="absolute right-1.5 bottom-1.5 p-1 rounded text-muted-foreground/70 hover:text-primary opacity-0 group-hover:opacity-100 transition-opacity"
                    title="放大编辑"
                  >
                    <Maximize2 className="w-3 h-3" />
                  </button>
                </div>
              </div>
            );
          }

          if (field.type === "select") {
            return (
              <div key={field.key} className={fieldSpanClass(field)}>
                <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
                <select
                  value={value}
                  onChange={(e) => onConfigChange(field.key, e.target.value)}
                  onPointerDown={(e) => e.stopPropagation()}
                  onWheel={(e) => e.stopPropagation()}
                  className="w-full text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background focus:border-primary/50 outline-none transition-all"
                >
                  {field.options?.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>
            );
          }

          if (field.type === "api-select") {
            return <div key={field.key} className={fieldSpanClass(field)}><ApiSelectField field={field} value={value} config={config} onConfigChange={onConfigChange} /></div>;
          }

          if (field.type === "multiselect") {
            const selectedValues: string[] = Array.isArray(value) ? value : (value ? [String(value)] : []);
            const options = field.options || [];
            // pi_agent 节点的 Skill/MCP：按钮拉起弹窗（左列搜索勾选 + 右列介绍），已选以卡片显示并支持快捷删除
            if (nodeType.id === "pi_agent" && (field.key === "skills" || field.key === "mcps")) {
              const pickerKind: PickerKind = field.key === "skills" ? "skills" : "mcps";
              return (
                <div key={field.key} className={fieldSpanClass(field)}>
                  <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
                  <div className="rounded-md border border-border/50 bg-background">
                    <div className="flex flex-wrap gap-1.5 px-2 py-2 min-h-[34px]">
                      {selectedValues.length === 0 && (
                        <span className="py-0.5 text-[11px] text-muted-foreground/70">{field.placeholder || "自行选择"}</span>
                      )}
                      {selectedValues.map((name) => (
                        <span key={name} className="inline-flex items-center gap-1 rounded-md bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">
                          {options.find((o) => o.value === name)?.label || name}
                          <button
                            type="button"
                            onPointerDown={(e) => e.stopPropagation()}
                            onClick={(e) => { e.stopPropagation(); onConfigChange(field.key, selectedValues.filter((v) => v !== name)); }}
                            className="hover:text-destructive"
                            title={`移除 ${name}`}
                          >×</button>
                        </span>
                      ))}
                    </div>
                    <button
                      type="button"
                      onPointerDown={(e) => e.stopPropagation()}
                      onClick={(e) => { e.stopPropagation(); setPicker({ kind: pickerKind, label: field.label, open: true }); }}
                      className="flex w-full items-center justify-center gap-1 border-t border-border/40 py-1.5 text-[11px] font-medium text-primary transition-colors hover:bg-primary/5"
                    >
                      + 选择{field.label}
                    </button>
                  </div>
                  {field.description && <p className="text-[10px] text-muted-foreground mt-1">{field.description}</p>}
                  {picker?.kind === pickerKind && picker.open && (
                    <SkillMcpPickerDialog
                      kind={pickerKind}
                      open
                      selected={selectedValues}
                      label={field.label}
                      onConfirm={(next) => { onConfigChange(field.key, next); setPicker(null); }}
                      onClose={() => setPicker(null)}
                    />
                  )}
                </div>
              );
            }
            return (
              <div key={field.key} className={fieldSpanClass(field)}>
                <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
                <div className="rounded-md border border-border/50 bg-background">
                  <div className="flex flex-wrap gap-1 px-2 py-1.5 min-h-[30px]">
                    {selectedValues.length === 0 && (
                      <span className="text-[11px] text-muted-foreground/70">{field.placeholder || "自行选择"}</span>
                    )}
                    {selectedValues.map((sv) => (
                      <span key={sv} className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-md bg-primary/10 text-primary">
                        {options.find((o) => o.value === sv)?.label || sv}
                        <button
                          type="button"
                          onPointerDown={(e) => e.stopPropagation()}
                          onClick={(e) => { e.stopPropagation(); onConfigChange(field.key, selectedValues.filter((v) => v !== sv)); }}
                          className="hover:text-destructive"
                        >×</button>
                      </span>
                    ))}
                  </div>
                  <select
                    multiple
                    value={selectedValues}
                    onChange={(e) => {
                      const next = Array.from(e.target.selectedOptions).map((o) => o.value);
                      onConfigChange(field.key, next);
                    }}
                    onPointerDown={(e) => e.stopPropagation()}
                    onWheel={(e) => e.stopPropagation()}
                    className="w-full text-[11px] px-2 py-1 border-t border-border/40 bg-background outline-none"
                  >
                    {options.map((opt) => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                </div>
                {field.description && <p className="text-[10px] text-muted-foreground mt-1">{field.description}</p>}
              </div>
            );
          }

          if (field.type === "account-select") {
            return <div key={field.key} className={fieldSpanClass(field)}><AccountSelectField field={field} value={value} onConfigChange={onConfigChange} /></div>;
          }

          if (field.type === "voice-select") {
            const selectedVoice = value || "";
            return (
              <div key={field.key} className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground">{field.label}</label>
                <button
                  type="button"
                  onClick={() => onVoiceSelect?.(field)}
                  className="w-full px-3 py-2 border border-border/50 bg-background rounded-xl text-sm text-left hover:border-primary/50 transition-colors"
                >
                  {selectedVoice || "点击选择音色..."}
                </button>
                {field.description && (
                  <p className="text-[10px] text-muted-foreground">{field.description}</p>
                )}
              </div>
            );
          }

          if (field.type === "checkbox" || field.type === "toggle") {
            const nextField = configFields[configFields.indexOf(field) + 1];
            const hasInlineNext = nextField?.inline;
            return (
              <div key={field.key} className={`${fieldSpanClass(field)} flex items-center gap-2`}>
                <input
                  type="checkbox"
                  checked={!!value}
                  onChange={(e) => onConfigChange(field.key, e.target.checked)}
                  className="w-3 h-3 rounded border-border/50 bg-background accent-primary"
                />
                <label className="text-[11px] font-medium text-muted-foreground">{field.label}</label>
                {hasInlineNext && (
                  <div className="flex items-center gap-1 ml-auto">
                    <span className="text-[11px] text-muted-foreground">{nextField.label}</span>
                    <input
                      type="number"
                      min={nextField.min}
                      max={nextField.max}
                      step={nextField.step}
                      value={config[nextField.key] ?? ""}
                      onChange={(e) => onConfigChange(nextField.key, parseInt(e.target.value) || 0)}
                      className="w-16 text-xs px-1.5 py-0.5 rounded-md border border-border/50 bg-background focus:border-primary/50 outline-none transition-all"
                    />
                  </div>
                )}
              </div>
            );
          }

          if (field.type === "slider") {
            const min = field.min ?? 0;
            const max = field.max ?? 100;
            const step = field.step ?? 1;
            return (
              <div key={field.key} className={fieldSpanClass(field)}>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-[11px] font-medium text-muted-foreground">{field.label}</label>
                  <span className="text-[11px] font-mono text-muted-foreground">{value ?? min}</span>
                </div>
                <input
                  type="range"
                  min={min}
                  max={max}
                  step={step}
                  value={value ?? min}
                  onChange={(e) => onConfigChange(field.key, parseFloat(e.target.value))}
                  onPointerDown={(e) => e.stopPropagation()}
                  onWheel={(e) => e.stopPropagation()}
                  className="w-full h-1.5 rounded-full appearance-none cursor-pointer accent-primary bg-secondary"
                />
              </div>
            );
          }

          if (field.type === "number") {
            // Skip rendering if this field is marked as inline (already rendered with previous toggle)
            if (field.inline) return null;
            return (
              <div key={field.key} className={fieldSpanClass(field)}>
                <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
                <input
                  type="number"
                  min={field.min}
                  max={field.max}
                  step={field.step}
                  value={value ?? ""}
                  onChange={(e) => onConfigChange(field.key, parseFloat(e.target.value) || 0)}
                  placeholder={field.placeholder}
                  onPointerDown={(e) => e.stopPropagation()}
                  onWheel={(e) => e.stopPropagation()}
                  className="w-full text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background focus:border-primary/50 focus:ring-1 focus:ring-primary/20 outline-none transition-all"
                />
              </div>
            );
          }

          if (field.type === "audio-selector") {
            return (
              <div key={field.key} className={fieldSpanClass(field)}>
                <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
                <div className="flex items-center gap-1.5">
                  <input
                    type="text"
                    value={value ? String(value) : ""}
                    readOnly
                    placeholder="未选择音频"
                    title={value ? String(value) : ""}
                    className="flex-1 text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background text-muted-foreground cursor-not-allowed truncate"
                  />
                  <button
                    onPointerDown={(e) => e.stopPropagation()}
                    onClick={() => setAudioSelectorField({ key: field.key, label: field.label })}
                    className="px-2.5 py-1.5 text-[11px] font-medium rounded-md border border-border/50 bg-background hover:bg-primary/10 hover:border-primary/30 text-primary transition-all flex-shrink-0"
                  >
                    <Music className="w-3 h-3 inline mr-1" />
                    选择
                  </button>
                </div>
              </div>
            );
          }

          return null;
        })}

      </div>

      {expandField && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onPointerDown={(e) => e.stopPropagation()}>
          <div className="bg-card border border-border/50 rounded-xl shadow-2xl w-[600px] max-h-[80vh] flex flex-col" onPointerDown={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-4 py-3 border-b border-border/50">
              <span className="text-sm font-semibold">{expandField.label}</span>
              <button onClick={() => setExpandField(null)} className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary/60 transition-colors">
                <XCircle className="w-4 h-4" />
              </button>
            </div>
            <div className="flex-1 p-4 overflow-auto">
              <textarea
                ref={modalTextareaRef}
                value={expandField.value}
                onChange={(e) => {
                  onConfigChange(expandField.key, e.target.value);
                  setExpandField((f) => f ? { ...f, value: e.target.value } : null);
                }}
                className="w-full h-full min-h-[300px] text-sm p-3 rounded-lg border border-border/50 bg-background resize-none outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20"
                autoFocus
              />
            </div>
            <div className="flex justify-end px-4 py-3 border-t border-border/50">
              <button
                onClick={() => setExpandField(null)}
                className="px-3 py-1.5 text-xs font-medium rounded-md bg-primary text-primary-foreground hover:opacity-90 transition-opacity"
              >
                完成
              </button>
            </div>
          </div>
        </div>
      )}

      {audioSelectorField && createPortal(
        <AudioSelectorDialog
          open={true}
          onClose={() => setAudioSelectorField(null)}
          onSelect={(path) => {
            onConfigChange(audioSelectorField.key, path);
            setAudioSelectorField(null);
          }}
        />
        , document.body
      )}
    </>
  );
}

function WorkflowNodeComponent({ data, id, selected }: NodeProps) {
  const nd = data as any;
  const nodeType = isGroupNodeData(nd) ? buildInlineGroupTypeDef(nd) : getNodeTypeDef(nd.nodeType);
  const { updateNodeData, getNodes, getEdges } = useReactFlow();
  const activeTaskId = useWorkflowStore((s) => s.activeTaskId);
  const taskModeId = useWorkflowStore((s) => s.taskModeId);
  const artifactTaskId = activeTaskId || taskModeId;
  const [expanded, setExpanded] = useState(true);
  const [jsonPreviewOpen, setJsonPreviewOpen] = useState(false);
  const [voiceSelectField, setVoiceSelectField] = useState<any>(null);
  const [showDesc, setShowDesc] = useState(false);
  const [maskOpen, setMaskOpen] = useState(false);
  const [editingNote, setEditingNote] = useState(false);
  const [noteText, setNoteText] = useState(nd.note || "");
  const [jsonEditorOpen, setJsonEditorOpen] = useState(false);
  const [editorInitialJson, setEditorInitialJson] = useState<any>({});
  const [textEditorOpen, setTextEditorOpen] = useState(false);
  const [textEditorInitialText, setTextEditorInitialText] = useState("");
  const [subtitleEditorOpen, setSubtitleEditorOpen] = useState(false);
  const [subtitleEditorEntries, setSubtitleEditorEntries] = useState<any[]>([]);
  const [subtitleEditorVideo, setSubtitleEditorVideo] = useState("");
  const [lcwrPreviewOpen, setLcwrPreviewOpen] = useState(false);
  const [onlineWmPreviewOpen, setOnlineWmPreviewOpen] = useState(false);
  const [qmMailboxes, setQmMailboxes] = useState<any[]>([]);
  const [qmMailLoading, setQmMailLoading] = useState(false);
  const [subtitleFindOpen, setSubtitleFindOpen] = useState(false);

  // Seedance 视频节点「查询生成进度」弹窗状态
  const [sdQueryOpen, setSdQueryOpen] = useState(false);
  const [sdQueryLoading, setSdQueryLoading] = useState(false);
  const [sdQueryResult, setSdQueryResult] = useState<any>(null);
  const [sdQueryError, setSdQueryError] = useState("");

  if (!nodeType) return null;
  if (isGroupNodeData(nd)) {
    return (
      <GroupWorkflowNodeCard
        id={id}
        nd={nd}
        selected={!!selected}
        nodeType={nodeType}
        expanded={expanded}
        setExpanded={setExpanded}
        updateNodeData={updateNodeData}
        taskId={artifactTaskId}
      />
    );
  }

  // Get upstream node outputs for preview nodes
  const getUpstreamOutputs = useCallback(() => {
    const edges = getEdges();
    const nodes = getNodes();
    const incomingEdges = edges.filter((e) => e.target === id);
    const outputs: Record<string, any> = {};
    const configs: Record<string, any> = {};
    const statuses: string[] = [];

    // File extension heuristics for matching output ports to actual files
    const VIDEO_EXTS = [".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv"];
    const SUBTITLE_EXTS = [".srt", ".ass", ".ssa", ".vtt", ".sub"];
    const IMAGE_EXTS = [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"];
    const isVideoFile = (p: string) => VIDEO_EXTS.some((ext) => p.toLowerCase().endsWith(ext));
    const isSubtitleFile = (p: string) => SUBTITLE_EXTS.some((ext) => p.toLowerCase().endsWith(ext));
    const isImageFile = (p: string) => IMAGE_EXTS.some((ext) => p.toLowerCase().endsWith(ext));

    for (const edge of incomingEdges) {
      const sourceNode = nodes.find((n) => n.id === edge.source);
      const targetHandle = edge.targetHandle || "";
      if (!sourceNode?.data?.outputs) continue;
      const srcOutputs = sourceNode.data.outputs as Record<string, any>;
      const srcStatus = (sourceNode.data as any)?.status;
      if (srcStatus) statuses.push(srcStatus);

      // 1. Exact key match (sourceHandle -> outputs key)
      const srcHandle = edge.sourceHandle || "";
      const srcKey = srcHandle.replace(/^out-/, "");
      const tgtKey = targetHandle.replace(/^(in|out)-/, "");
      if (srcKey && srcOutputs[srcKey] !== undefined) {
        outputs[tgtKey || targetHandle || srcHandle] = srcOutputs[srcKey];
        continue;
      }
      // Also try raw sourceHandle
      if (srcHandle && srcOutputs[srcHandle] !== undefined) {
        outputs[tgtKey || targetHandle || srcHandle] = srcOutputs[srcHandle];
        continue;
      }

      // 2. Type-based matching: find first output file matching the target port type
      const allPaths = Object.values(srcOutputs).filter(
        (v): v is string => typeof v === "string"
      );
      let matched = false;
      // Normalize targetHandle: strip in-/out- prefix for type matching and output key
      const targetType = targetHandle.replace(/^(in|out)-/, "");
      if (targetType === "video") {
        const found = allPaths.find(isVideoFile);
        if (found) { outputs[targetType] = found; matched = true; }
      } else if (["subtitle", "original", "bilingual"].includes(targetType)) {
        const found = allPaths.find(isSubtitleFile);
        if (found) { outputs[targetType] = found; matched = true; }
      } else if (targetType === "image") {
        const found = allPaths.find(isImageFile);
        if (found) { outputs[targetType] = found; matched = true; }
      }

      // 3. Last resort: take the first file path output
      if (!matched && allPaths.length > 0) {
        outputs[targetType || "first"] = allPaths[0];
      }

      // Also check config for input nodes
      if (sourceNode?.data?.config) {
        Object.assign(configs, sourceNode.data.config);
      }
    }
    return { outputs, configs, refreshKey: statuses.join("|") };
  }, [id, getNodes, getEdges]);

  // For preview nodes, get paths from upstream outputs or configs
  const { outputs: upstreamOutputs, configs: upstreamConfigs, refreshKey: upstreamRefreshKey } =
    (nodeType.id === "video_preview" || nodeType.id === "image_preview" || nodeType.id === "json_visual_editor" || nodeType.id === "text_editor" || nodeType.id === "subtitle_editor" || nodeType.id === "lcwr_watermark_removal" || nodeType.id === "online_watermark_removal" || nodeType.id === "qm_virtual_mailbox" || nodeType.id === "image_mask") ? getUpstreamOutputs() : { outputs: {}, configs: {}, refreshKey: "" };

  // 当前任务 id（调试任务 activeTaskId 或一般/批量任务 taskModeId），用于相对产物路径解析
  const storeActiveTaskId = useWorkflowStore((s) => s.activeTaskId);
  const previewTaskId = storeActiveTaskId || artifactTaskId;
  const imageMaskSrc = useStableFileUrl(String(upstreamOutputs.image || nd.imagePath || ""), previewTaskId, upstreamRefreshKey);
  const currentWfId = useWorkflowStore((s) => s.currentWfId);

  const IconComp = ICON_MAP[nodeType.icon] || Wrench;
  const status = nd.status || "pending";
  const config = nd.config || {};
  const statusCfg = STATUS_CONFIG[status] || STATUS_CONFIG.pending;
  const StatusIcon = statusCfg.icon;

  const visibleOutputs = getVisibleOutputs(nodeType, config);
  const visibleInputs = getNodeInputs(nodeType, config);
  const isPiAgent = nodeType.id === "pi_agent";
  const isSeedance = (nodeType.id || "").startsWith("seedance_");
  const isDynamicPorts = isPiAgent || nodeType.id === "output_merge_list";
  const dedupedOutputEntries = (() => {
    const seen = new Set<string>();
    const rawOutputs = nd.outputs;
    // Only process plain object with string values
    if (!rawOutputs || typeof rawOutputs !== "object" || Array.isArray(rawOutputs)) return [];
    return Object.entries(rawOutputs).filter(([key, filePath]) => {
      if (typeof key !== "string") return false;
      // Only include string or number values, skip objects/functions
      if (filePath !== null && filePath !== undefined && typeof filePath !== "string" && typeof filePath !== "number") return false;
      const dedupeKey = String(filePath);
      if (!dedupeKey || seen.has(dedupeKey)) return false;
      seen.add(dedupeKey);
      return true;
    });
  })();

  const configRef = useRef(config);
  configRef.current = config;

  const handleConfigChange = useCallback((key: string, value: any) => {
    const newConfig = { ...configRef.current, [key]: value };
    updateNodeData(id, { config: newConfig });
  }, [id, updateNodeData]);

  // JSON 可视化编辑：打开弹窗并载入输入（优先已编辑结果，其次上游 JSON 输入/配置）
  const openJsonEditor = useCallback(async () => {
    let initial: any;
    const saved = configRef.current.edited_json;
    if (saved && String(saved).trim()) {
      try { initial = JSON.parse(saved); } catch { initial = {}; }
    } else {
      initial = upstreamOutputs.json !== undefined ? upstreamOutputs.json : upstreamConfigs.json;
    }
    // 若上游值是文件路径，尝试从后端读取内容
    if (typeof initial === "string" && initial.trim() && !initial.trim().startsWith("{") && !initial.trim().startsWith("[")) {
      try {
        const params = new URLSearchParams({ path: initial.trim() });
        if (previewTaskId) params.set("task_id", previewTaskId);
        const res = await client.get(`/api/files/stream?${params.toString()}`, { responseType: "text" });
        const text = typeof res.data === "string" ? res.data : JSON.stringify(res.data);
        try { initial = JSON.parse(text); } catch { initial = text; }
      } catch { /* 读取失败时保留原值 */ }
    }
    setEditorInitialJson(initial);
    setJsonEditorOpen(true);
  }, [upstreamOutputs.json, upstreamConfigs.json, previewTaskId]);

  // 文本编辑：打开弹窗并载入输入（优先已编辑结果，其次上游文本输入/配置）
  const openTextEditor = useCallback(async () => {
    let initial = "";
    const saved = configRef.current.edited_text;
    if (saved && String(saved).trim() !== "") {
      initial = String(saved);
    } else {
      const upstream = upstreamOutputs.text !== undefined ? upstreamOutputs.text : upstreamConfigs.text;
      if (upstream === undefined || upstream === null) initial = "";
      else if (typeof upstream === "string") initial = upstream;
      else initial = String(upstream);
    }
    // 若上游值是文件路径（单行无换行），尝试从后端读取内容
    if (initial.trim() && !initial.includes("\n")) {
      try {
        const params = new URLSearchParams({ path: initial.trim() });
        if (previewTaskId) params.set("task_id", previewTaskId);
        const res = await client.get(`/api/files/stream?${params.toString()}`, { responseType: "text" });
        initial = typeof res.data === "string" ? res.data : JSON.stringify(res.data);
      } catch { /* 读取失败时保留原值 */ }
    }
    setTextEditorInitialText(initial);
    setTextEditorOpen(true);
  }, [upstreamOutputs.text, upstreamConfigs.text, previewTaskId]);

  // 字幕编辑：打开弹窗并载入输入字幕（优先已编辑结果，其次上游字幕）与输入视频
  const openSubtitleEditor = useCallback(async () => {
    let entries: any[] = [];
    let video = "";
    const saved = configRef.current.edited_subtitles;
    if (saved && String(saved).trim()) {
      try {
        const parsed = JSON.parse(saved);
        entries = Array.isArray(parsed) ? parsed : [];
      } catch { entries = []; }
    } else {
      const sub = upstreamOutputs.subtitle !== undefined ? upstreamOutputs.subtitle : upstreamConfigs.subtitlePath;
      if (typeof sub === "string" && sub.trim()) {
        try {
          const params = new URLSearchParams({ path: sub.trim() });
          if (previewTaskId) params.set("task_id", previewTaskId);
          const res = await client.get(`/api/files/stream?${params.toString()}`, { responseType: "text" });
          const content = typeof res.data === "string" ? res.data : JSON.stringify(res.data);
          entries = parseSubtitleEntries(content);
        } catch { entries = []; }
      } else if (sub && typeof sub === "object") {
        entries = Array.isArray(sub) ? sub : [];
      }
    }
    // 视频：优先上游 video 输出，其次输入节点的 videoPath
    if (upstreamOutputs.video !== undefined) video = String(upstreamOutputs.video);
    else if (upstreamConfigs.videoPath) video = String(upstreamConfigs.videoPath);
    if (!video) {
      const nodes = getNodes();
      const inputNode = nodes.find((n) => (n.data as any)?.nodeType === "input");
      const inputConfig = (inputNode?.data as any)?.config || {};
      if (inputConfig.videoPath) video = String(inputConfig.videoPath);
    }
    setSubtitleEditorEntries(entries);
    setSubtitleEditorVideo(video);
    setSubtitleEditorOpen(true);
  }, [upstreamOutputs.subtitle, upstreamOutputs.video, upstreamConfigs.subtitlePath, upstreamConfigs.videoPath, previewTaskId, getNodes]);

  // Seedance 节点「查询生成进度」：用已记录的 task_id 查询任务状态并展示
  const openSeedanceQuery = useCallback(async () => {
    const taskId = nd.outputs?.task_id;
    setSdQueryOpen(true);
    setSdQueryLoading(true);
    setSdQueryError("");
    setSdQueryResult(null);
    if (!taskId) {
      setSdQueryLoading(false);
      setSdQueryError("该节点尚未记录任务 ID，请先运行节点生成视频。");
      return;
    }
    try {
      const res = await client.post("/api/videogen-interfaces/seedance/query", { task_id: taskId });
      setSdQueryResult(res.data || null);
    } catch (e: any) {
      setSdQueryError(e?.response?.data?.detail || e?.message || "查询失败");
    } finally {
      setSdQueryLoading(false);
    }
  }, [nd.outputs?.task_id]);

  const handleStyle = (portType: string, idx: number, total: number, portColor?: string) => ({
    top: ((idx + 1) / (total + 1)) * 100 + "%",
    background: portColor || PORT_COLORS[portType as PortType] || "#6b7280",
    width: 12, height: 12, border: "2px solid white",
  });

  const hasConfig = nodeType.configFields && nodeType.configFields.length > 0;
  const nodeColor = nodeType.color || "#6b7280";

  const saveNote = (text: string) => {
    setNoteText(text);
    setEditingNote(false);
    updateNodeData(id, { note: text || undefined });
  };

  return (
    <div className={cn(
      "rounded-2xl border-[3px] bg-card text-card-foreground w-[420px] max-w-[420px] transition-all duration-300",
      selected
        ? "border-primary shadow-primary/20 shadow-lg scale-[1.02]"
        : status === "completed"
          ? "!border-[5px] border-emerald-400 shadow-[0_0_20px_6px_rgba(16,185,129,0.4),0_0_40px_12px_rgba(16,185,129,0.2)]"
          : "",
      status === "running" && "animate-node-glow",
      statusCfg.glow,
      (status === "pending" || status === "failed") && "shadow-md",
    )} style={{ borderColor: selected ? undefined : status === "completed" ? "#34d399" : nodeColor }} >
      {/* Input Handles */}
      {getNodeInputs(nodeType, config).map((port: any, i: number) => (
        <Handle
          key={"in-" + port.id}
          type="target"
          position={Position.Left}
          id={"in-" + port.id}
          style={handleStyle(port.type, i, getNodeInputs(nodeType, config).length, port.color)}
        />
      ))}

      {/* Header */}
      <div
        className={cn(
          "flex items-center gap-2 px-4 py-2.5",
          hasConfig ? "cursor-pointer rounded-t-xl" : "rounded-t-xl"
        )}
        style={{ backgroundColor: nodeType.color + "30" }}
        onClick={hasConfig ? () => setExpanded(!expanded) : undefined}
      >
        <div
          className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
          style={{ backgroundColor: nodeType.color + "40" }}
        >
          <IconComp className="w-5 h-5" style={{ color: nodeType.color }} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-bold truncate">{nd.label || nodeType.name}</div>
          <div className="text-xs text-muted-foreground truncate">{(nodeType.description || "").slice(0, 25)}</div>
        </div>
        {nodeType.id !== "input" && (
          <div className="relative">
            <button
              onClick={(e) => { e.stopPropagation(); setShowDesc((p) => !p); }}
              onMouseEnter={() => setShowDesc(true)}
              onMouseLeave={() => setShowDesc(false)}
              className="w-6 h-6 rounded-md flex items-center justify-center text-muted-foreground/70 hover:text-foreground/70 hover:bg-foreground/10 transition-colors"
            >
              <HelpCircle className="w-3 h-3" />
            </button>
            {showDesc && (
              <div
                className="absolute top-full right-0 mt-1 z-50 w-64 p-3 text-xs text-muted-foreground bg-popover border border-border/50 rounded-lg shadow-lg"
                onMouseEnter={() => setShowDesc(true)}
                onMouseLeave={() => setShowDesc(false)}
              >
                {nodeType.description}
              </div>
            )}
          </div>
        )}
        {nodeType.id !== "input" && isSeedance && (
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); openSeedanceQuery(); }}
            title={nd.outputs?.task_id ? "查询生成进度" : "请先运行该节点生成任务"}
            className="w-6 h-6 rounded-md flex items-center justify-center text-muted-foreground/70 hover:text-foreground hover:bg-foreground/10 transition-colors"
          >
            <RefreshCw className="w-3 h-3" />
          </button>
        )}
        {sdQueryOpen && createPortal(
          <div
            className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50"
            onClick={() => setSdQueryOpen(false)}
          >
            <div
              className="w-[520px] max-w-[92vw] max-h-[82vh] overflow-auto rounded-xl border border-border bg-card p-5 text-card-foreground shadow-2xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between mb-3">
                <div className="text-sm font-bold">Seedance 任务进度查询</div>
                <button
                  className="w-6 h-6 rounded-md flex items-center justify-center text-muted-foreground hover:bg-foreground/10"
                  onClick={() => setSdQueryOpen(false)}
                >
                  <XCircle className="w-4 h-4" />
                </button>
              </div>
              <div className="text-[11px] text-muted-foreground mb-3 break-all">
                任务 ID：{nd.outputs?.task_id || "—"}
              </div>
              {sdQueryLoading && <div className="text-xs text-muted-foreground">查询中…</div>}
              {sdQueryError && (
                <div className="text-xs text-red-500 whitespace-pre-wrap">{sdQueryError}</div>
              )}
              {sdQueryResult && (
                <div className="space-y-2 text-xs">
                  <div className="flex items-center gap-2">
                    <span className="text-muted-foreground">状态：</span>
                    <span
                      className={
                        "px-2 py-0.5 rounded " +
                        (sdQueryResult.status === "succeeded"
                          ? "bg-emerald-500/20 text-emerald-400"
                          : sdQueryResult.status === "failed"
                            ? "bg-red-500/20 text-red-400"
                            : "bg-amber-500/20 text-amber-400")
                      }
                    >
                      {sdQueryResult.status}
                    </span>
                  </div>
                  {sdQueryResult.content?.video_url && (
                    <div>
                      <span className="text-muted-foreground">视频：</span>
                      <a
                        className="text-primary underline break-all"
                        href={sdQueryResult.content.video_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {sdQueryResult.content.video_url}
                      </a>
                    </div>
                  )}
                  {sdQueryResult.content?.last_frame_url && (
                    <div>
                      <span className="text-muted-foreground">尾帧：</span>
                      <a
                        className="text-primary underline break-all"
                        href={sdQueryResult.content.last_frame_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {sdQueryResult.content.last_frame_url}
                      </a>
                    </div>
                  )}
                  <div>
                    <span className="text-muted-foreground">完整响应：</span>
                    <pre className="mt-1 max-h-[40vh] overflow-auto rounded bg-background/60 p-2 text-[10px] leading-relaxed whitespace-pre-wrap break-all">
                      {JSON.stringify(sdQueryResult.raw, null, 2)}
                    </pre>
                  </div>
                </div>
              )}
            </div>
          </div>,
          document.body
        )}
        {nd.onExecuteNode && (
          <div className="flex items-center gap-1">
            <button
              onClick={(e) => {
                e.stopPropagation();
                nd.onExecuteNode(id);
              }}
              disabled={nd.disableExecute || status === "running"}
              className="w-6 h-6 rounded-md flex items-center justify-center bg-primary/10 text-primary hover:bg-primary/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              title="仅执行此节点"
            >
              <Play className="w-3 h-3" />
            </button>
            {nd.onExecuteFromNode && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  nd.onExecuteFromNode(id);
                }}
                disabled={nd.disableExecute || status === "running"}
                className="w-6 h-6 rounded-md flex items-center justify-center bg-amber-500/10 text-amber-600 hover:bg-amber-500/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                title="从此节点继续执行下游"
              >
                <ArrowRight className="w-3 h-3" />
              </button>
            )}
          </div>
        )}
        {nodeType.id === "cutia" && status === "waiting" && nd.workbench_url && (
          <button
            onClick={(e) => { e.stopPropagation(); window.location.href = nd.workbench_url; }}
            className="w-6 h-6 rounded-md flex items-center justify-center bg-amber-500/10 text-amber-700 hover:bg-amber-500/20 transition-colors"
            title="打开剪辑工作台"
          >
            <Clapperboard className="w-3 h-3" />
          </button>
        )}
        <div className="flex items-center gap-1.5">
          {hasConfig && (
            expanded
              ? <ChevronDown className="w-3 h-3 text-muted-foreground/70" />
              : <ChevronRight className="w-3 h-3 text-muted-foreground/70" />
          )}
          <div className={cn("flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium", statusCfg.badgeBg, statusCfg.badgeText)}>
            <StatusIcon className={cn("w-2.5 h-2.5", status === "running" && "animate-spin")} />
            <span>{statusCfg.label}</span>
          </div>
        </div>
      </div>

      {/* Port Labels */}
      <div className="px-3 py-2 space-y-1">
        {isDynamicPorts && (
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[10px] font-semibold text-muted-foreground">输入</span>
            <button
              type="button"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => { e.stopPropagation(); const n = Math.min(Number(config.inputCount) || 2, 8); handleConfigChange("inputCount", n + 1); }}
              className="w-5 h-5 rounded flex items-center justify-center text-[11px] font-bold text-primary border border-primary/30 hover:bg-primary/10"
              title="增加输入端口"
            >+</button>
            <button
              type="button"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => { e.stopPropagation(); const n = Math.max(Number(config.inputCount) || 2, 1); handleConfigChange("inputCount", n - 1); }}
              className="w-5 h-5 rounded flex items-center justify-center text-[11px] font-bold text-muted-foreground border border-border/50 hover:bg-muted"
              title="减少输入端口"
            >−</button>
            <span className="text-[10px] text-muted-foreground">{visibleInputs.length}</span>
            {isPiAgent && (
              <>
                <span className="text-[10px] font-semibold text-muted-foreground ml-3">输出</span>
                <button
                  type="button"
                  onPointerDown={(e) => e.stopPropagation()}
                  onClick={(e) => { e.stopPropagation(); const n = Math.min(Number(config.outputCount) || 2, 8); handleConfigChange("outputCount", n + 1); }}
                  className="w-5 h-5 rounded flex items-center justify-center text-[11px] font-bold text-primary border border-primary/30 hover:bg-primary/10"
                  title="增加输出端口"
                >+</button>
                <button
                  type="button"
                  onPointerDown={(e) => e.stopPropagation()}
                  onClick={(e) => { e.stopPropagation(); const n = Math.max(Number(config.outputCount) || 2, 1); handleConfigChange("outputCount", n - 1); }}
                  className="w-5 h-5 rounded flex items-center justify-center text-[11px] font-bold text-muted-foreground border border-border/50 hover:bg-muted"
                  title="减少输出端口"
                >−</button>
                <span className="text-[10px] text-muted-foreground">{visibleOutputs.length}</span>
              </>
            )}
          </div>
        )}
        {visibleInputs.length > 0 && (
          <div className="flex items-center justify-between gap-2">
            <div className="flex flex-wrap gap-1">
              {visibleInputs.map((p: any) => (
                <span
                  key={p.id}
                  className="inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded-md"
                  style={{ backgroundColor: (p.color || PORT_COLORS[p.type as PortType]) + "20", color: p.color || PORT_COLORS[p.type as PortType] }}
                >
                  <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: p.color || PORT_COLORS[p.type as PortType] }} />
                  {p.label}
                </span>
              ))}
            </div>
            {/* Note */}
            {editingNote ? (
              <input
                autoFocus
                value={noteText}
                onChange={(e) => setNoteText(e.target.value)}
                onBlur={() => saveNote(noteText)}
                onKeyDown={(e) => { if (e.key === "Enter") saveNote(noteText); if (e.key === "Escape") { setNoteText(nd.note || ""); setEditingNote(false); } }}
                onClick={(e) => e.stopPropagation()}
                className="flex-shrink-0 w-28 text-[11px] px-2 py-0.5 rounded-md border border-border/50 bg-background outline-none"
                placeholder="输入备注..."
              />
            ) : (
              <div
                onDoubleClick={(e) => { e.stopPropagation(); setEditingNote(true); }}
                className={cn(
                  "flex-shrink-0 w-28 text-[11px] text-right px-2 py-0.5 rounded-md cursor-default select-none truncate",
                  noteText ? "bg-secondary text-muted-foreground" : "bg-secondary/60 text-muted-foreground/70"
                )}
                title={noteText || "双击添加备注"}
              >
                {noteText || "无备注"}
              </div>
            )}
          </div>
        )}
        {visibleOutputs.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {visibleOutputs.map((p) => (
              <span
                key={p.id}
                className="inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded-md"
                style={{ backgroundColor: (p.color || PORT_COLORS[p.type as PortType]) + "20", color: p.color || PORT_COLORS[p.type as PortType] }}
              >
                {p.label}
                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: p.color || PORT_COLORS[p.type as PortType] }} />
              </span>
            ))}
          </div>
        )}
      </div>
      {/* 文本输入框：卡片内大文本输入 */}
      {nodeType.id === "text_input" && (
        <div className="px-3 pb-3 pt-1">
          <textarea
            value={config.text ?? ""}
            placeholder="在此输入文本…"
            onChange={(e) => handleConfigChange("text", e.target.value)}
            onPointerDown={(e) => e.stopPropagation()}
            className="w-full h-28 resize-y rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
      )}
      {/* 文件加载：卡片内文件路径输入 + 加载按钮 */}
      {nodeType.id === "file_load" && (
        <div className="px-3 pb-3 pt-1">
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={config.filePath ?? ""}
              placeholder="文件路径，或点击右侧按钮选择"
              onChange={(e) => handleConfigChange("filePath", e.target.value)}
              onPointerDown={(e) => e.stopPropagation()}
              className="flex-1 min-w-0 rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            />
            <button
              type="button"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={async (e) => {
                e.stopPropagation();
                const p = await nativeFileDialog("file", "选择文件");
                if (p) handleConfigChange("filePath", p);
              }}
              className="inline-flex items-center gap-1 px-2 py-1.5 rounded-md text-xs font-medium bg-primary/10 text-primary hover:bg-primary/20 transition-colors shrink-0"
            >
              <FolderOpen className="w-3.5 h-3.5" /> 加载
            </button>
          </div>
        </div>
      )}
      {/* 图片蒙版：卡片内显示输入图片并打开绘制弹窗 */}
      {nodeType.id === "image_mask" && (
        <div className="px-3 pb-3 pt-1 space-y-2">
          <div className="rounded-md border overflow-hidden bg-black/40 flex items-center justify-center" style={{ minHeight: 120 }}>
            {imageMaskSrc ? (
              <img
                src={imageMaskSrc}
                alt="输入图片"
                className="max-h-48 w-full object-contain"
                onPointerDown={(e) => e.stopPropagation()}
              />
            ) : (
              <div className="text-[11px] text-muted-foreground/70 text-center py-6 px-3">
                请连接上游图片输入
              </div>
            )}
          </div>
          <div className="flex items-center justify-between gap-2">
            <button
              type="button"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => { e.stopPropagation(); setMaskOpen(true); }}
              className="inline-flex items-center gap-1 px-2 py-1.5 rounded-md text-xs font-medium bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
            >
              <PenTool className="w-3.5 h-3.5" /> 绘制蒙版
            </button>
            <span className="text-[11px] text-muted-foreground">
              笔 {(config.mask?.strokes?.length) || 0} · 框 {(config.mask?.rects?.length) || 0}
            </span>
          </div>
          <ImageMaskEditor
            open={maskOpen}
            onOpenChange={setMaskOpen}
            imagePath={upstreamOutputs.image || nd.imagePath || null}
            taskId={previewTaskId}
            refreshKey={upstreamRefreshKey}
            mask={config.mask || { strokes: [], rects: [], color: "#ff3b30", alpha: 0.5 }}
            onChange={(m) => handleConfigChange("mask", m)}
          />
        </div>
      )}
      {/* AI生视频：提示词前缀 + 接口/模型/参数级联 */}
      {nodeType.id === "ai_video_gen" && (
        <div className="px-3 pb-3 pt-1">
          <VideoGenNode config={config} onChange={(k, v) => handleConfigChange(k, v)} />
        </div>
      )}
      {/* 音频素材库：输入框 + 打开晴沐配音谷素材库按钮（嵌套弹窗） */}
      {nodeType.id === "audio_asset_library" && (
        <AudioAssetLibraryNode
          config={config}
          onChange={(k, v) => handleConfigChange(k, v)}
        />
      )}
      {/* AI字幕纠错：卡片上设置字数上限与专有名词 */}
      {nodeType.id === "ai_subtitle_correct" && (
        <div className="px-3 pb-3 pt-1 space-y-2">
          <div className="flex items-center gap-2">
            <label className="text-[11px] text-muted-foreground shrink-0">请求字数上限</label>
            <input
              type="number"
              min={200}
              step={100}
              value={config.maxChars ?? "2000"}
              placeholder="2000"
              onChange={(e) => handleConfigChange("maxChars", e.target.value)}
              onPointerDown={(e) => e.stopPropagation()}
              className="w-24 rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            />
            <span className="text-[11px] text-muted-foreground">字</span>
          </div>
          <input
            type="text"
            value={config.properNouns ?? ""}
            placeholder="专有名词（逗号分隔，如 张三,OpenAI）"
            onChange={(e) => handleConfigChange("properNouns", e.target.value)}
            onPointerDown={(e) => e.stopPropagation()}
            className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
      )}
      {nodeType.id === "lcwr_watermark_removal" && (
        <LcwrNodeControls config={config} onConfigChange={handleConfigChange} />
      )}
      {nodeType.id === "lcwr_watermark_removal" && (
        <LcwrRegionSummary config={config} />
      )}
      {nodeType.id === "lcwr_watermark_removal" && (
        <div className="px-3 pb-3 pt-1">
          <button
            type="button"
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => { e.stopPropagation(); setLcwrPreviewOpen(true); }}
            className="w-full inline-flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded-md text-[11px] font-medium text-sky-700 dark:text-sky-300 bg-sky-500/10 border border-sky-500/20 hover:bg-sky-500/20 transition-colors"
          >
            <Eye className="w-3.5 h-3.5" />
            打开预览设置
          </button>
        </div>
      )}
      {nodeType.id === "online_watermark_removal" && (
        <div className="px-3 pb-3 pt-1 space-y-2">
          {/* 水印区域设置按钮 */}
          <button
            type="button"
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => { e.stopPropagation(); setOnlineWmPreviewOpen(true); }}
            className="w-full inline-flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded-md text-[11px] font-medium text-violet-700 dark:text-violet-300 bg-violet-500/10 border border-violet-500/20 hover:bg-violet-500/20 transition-colors"
          >
            <Eye className="w-3.5 h-3.5" />
            设置水印区域
          </button>
          {/* 水印区域摘要 */}
          {Array.isArray(config.watermark_regions) && config.watermark_regions.length > 0 ? (
            <div className="text-[10px] text-muted-foreground text-center">
              已设置 {config.watermark_regions.length} 个区域
            </div>
          ) : (
            <div className="text-[10px] text-amber-600 dark:text-amber-400 text-center leading-snug">
              未设置水印区域将全屏去除，可能误伤不需要去除的元素
            </div>
          )}
          {/* 分隔线 */}
          <div className="border-t border-border/30" />
          {/* 继续查询上次任务（勾选后节点执行时自动从上次记录恢复查询） */}
          <label
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => e.stopPropagation()}
            className="flex items-center gap-2 px-1 py-1 rounded-md hover:bg-muted/50 cursor-pointer transition-colors"
            title="勾选后执行节点时将自动读取上次任务的 request_id 继续查询，无需重新提交"
          >
            {config.resume_request_id ? (
              <CheckSquare className="w-4 h-4 text-blue-500 flex-shrink-0" />
            ) : (
              <Square className="w-4 h-4 text-muted-foreground/50 flex-shrink-0" />
            )}
            <span className="text-[11px] text-muted-foreground leading-tight">
              继续查询上次任务
              {config.resume_request_id && config.resume_request_id !== "auto" && (
                <span className="ml-1 text-[10px] text-muted-foreground/60">({config.resume_request_id})</span>
              )}
            </span>
            <input
              type="checkbox"
              className="sr-only"
              checked={!!config.resume_request_id}
              onChange={(e) => {
                e.stopPropagation();
                handleConfigChange("resume_request_id", e.target.checked ? "auto" : "");
              }}
              onPointerDown={(e) => e.stopPropagation()}
            />
          </label>
          {/* 查询用量和历史：前往网页查看额度 */}
          <a
            href="https://www.licorxj.online/capability-hub"
            target="_blank"
            rel="noopener noreferrer"
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => e.stopPropagation()}
            className="w-full inline-flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded-md text-[11px] font-medium text-slate-700 dark:text-slate-300 bg-slate-500/10 border border-slate-500/20 hover:bg-slate-500/20 transition-colors"
          >
            <ExternalLink className="w-3.5 h-3.5" />
            查询用量和历史
          </a>
        </div>
      )}
      {nodeType.id === "qm_virtual_mailbox" && (
        <div className="px-3 pb-3 pt-1 space-y-2">
          {/* 第一行：前往网页设置按钮 */}
          <a
            href="https://www.licorxj.online/mail-forwarding"
            target="_blank"
            rel="noopener noreferrer"
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => e.stopPropagation()}
            className="w-full inline-flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded-md text-[11px] font-medium text-emerald-700 dark:text-emerald-300 bg-emerald-500/10 border border-emerald-500/20 hover:bg-emerald-500/20 transition-colors"
          >
            <ExternalLink className="w-3.5 h-3.5" />
            前往网页设置
          </a>

          {/* 第二行：虚拟邮箱下拉选择 + 刷新按钮 */}
          <div className="flex items-center gap-1.5">
            <select
              value={config.mailbox_id || ""}
              onChange={(e) => handleConfigChange("mailbox_id", e.target.value)}
              onPointerDown={(e) => e.stopPropagation()}
              onWheel={(e) => e.stopPropagation()}
              className="min-w-0 flex-1 text-[11px] px-2 py-1 rounded-md border border-border/50 bg-background outline-none focus:border-primary/50"
            >
              <option value="">选择虚拟邮箱...</option>
              {qmMailboxes.map((mb: any) => (
                <option key={mb.id} value={String(mb.id)}>
                  {mb.address} ({mb.status})
                </option>
              ))}
            </select>
            <button
              type="button"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => {
                e.stopPropagation();
                setQmMailLoading(true);
                client.get("/api/qm-mail/mailboxes")
                  .then((res) => {
                    setQmMailboxes(res.data?.mailboxes || []);
                  })
                  .catch(() => setQmMailboxes([]))
                  .finally(() => setQmMailLoading(false));
              }}
              className="flex-shrink-0 inline-flex items-center gap-1 text-[10px] px-1.5 py-1 rounded-md border border-border/50 hover:bg-muted transition-colors"
              title="刷新邮箱列表"
            >
              {qmMailLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
            </button>
          </div>

          {/* 转发目标选择 */}
          {config.mailbox_id && (() => {
            const selected = qmMailboxes.find((mb: any) => String(mb.id) === String(config.mailbox_id));
            if (!selected) return null;
            const targets = selected.targets || [];
            if (targets.length === 0) {
              return (
                <div className="text-[10px] text-amber-600 dark:text-amber-400 px-1">
                  该邮箱尚未设置转发目标，请前往网页设置
                </div>
              );
            }
            const verified = targets.filter((t: any) => t.verification_status === "verified");
            return (
              <div className="space-y-1">
                <select
                  value={config.target_email || ""}
                  onChange={(e) => handleConfigChange("target_email", e.target.value)}
                  onPointerDown={(e) => e.stopPropagation()}
                  onWheel={(e) => e.stopPropagation()}
                  className="w-full text-[11px] px-2 py-1 rounded-md border border-border/50 bg-background outline-none focus:border-primary/50"
                >
                  <option value="">选择转发目标（已验证）...</option>
                  {targets.map((t: any) => (
                    <option key={t.id} value={t.email} disabled={t.verification_status !== "verified"}>
                      {t.email} {t.verification_status === "verified" ? "✓" : "⚠未验证"}
                    </option>
                  ))}
                </select>
                <div className="text-[10px] text-muted-foreground/70 px-1">
                  将向选中的已验证转发目标发送内容邮件（2分钱/封）。未验证目标不可选，请先前往网页验证。
                </div>
              </div>
            );
          })()}

          {/* 邮件主题输入 */}
          <div className="space-y-1">
            <label className="text-[11px] font-medium text-muted-foreground">
              邮件主题（Subject）
            </label>
            <input
              type="text"
              value={config.subject || ""}
              onChange={(e) => handleConfigChange("subject", e.target.value)}
              onPointerDown={(e) => e.stopPropagation()}
              onWheel={(e) => e.stopPropagation()}
              placeholder="邮件主题，留空则使用默认主题"
              className="w-full text-[11px] px-2 py-1.5 rounded-md border border-border/50 bg-background outline-none focus:border-primary/50"
            />
          </div>

          {/* 内容输入框：作为前缀拼接连线文本 */}
          <div className="space-y-1">
            <label className="text-[11px] font-medium text-muted-foreground">
              内容输入（前缀）
            </label>
            <textarea
              value={config.prefix_content || ""}
              onChange={(e) => handleConfigChange("prefix_content", e.target.value)}
              onPointerDown={(e) => e.stopPropagation()}
              onWheel={(e) => e.stopPropagation()}
              placeholder="输入内容作为前缀；连线文本将拼接在其后（无连线时仅发送此处内容）"
              rows={3}
              className="w-full text-[11px] px-2 py-1.5 rounded-md border border-border/50 bg-background outline-none focus:border-primary/50 resize-none"
            />
            <div className="text-[10px] text-muted-foreground/70">
              输入框内容作为前缀，自动拼接上方 text 连线传入的文本或文本文件内容；无连线时仅发送输入框内内容。
            </div>
          </div>

          {/* 分隔线 */}
          <div className="border-t border-border/30" />

          <div className="text-[10px] text-muted-foreground px-1">
            运行节点即以虚拟邮箱身份，向所选已验证转发目标发送内容邮件（2分钱/封，云端转发处理）。主题留空用默认；拼接后的内容会记录在任务 JSON 的 content 字段中。
          </div>
        </div>
      )}
      {/* Running Progress */}
      {status === "running" && (
        <div className="px-3 pb-2">
          <div className="w-full h-1.5 bg-pink-100 dark:bg-pink-900/30 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-pink-400 to-pink-500 rounded-full transition-all duration-700 ease-out"
              style={{ width: (nd.progress || 0) + "%" }}
            />
          </div>
          {nd.message && (
            <div className="text-[11px] text-pink-600 dark:text-pink-400 mt-1 truncate flex items-center gap-1">
              <span className="inline-block w-1 h-1 rounded-full bg-pink-500 animate-pulse" />
              {nd.message}
            </div>
          )}
        </div>
      )}
      {/* 节点完成后保留显示最后一条进度消息 */}
      {status !== "running" && status !== "waiting" && nd.message && (
        <div className="px-3 pb-1">
          <div className="text-[11px] text-muted-foreground truncate">{nd.message}</div>
        </div>
      )}

      {/* Config Form (when expanded) */}
      {hasConfig && expanded && nodeType.id === "subtitle_position_search" && (() => {
        const mode = String(config.position_mode || "ocr");
        const mbox = config.manual_box && typeof config.manual_box === "object" && "x1" in config.manual_box
          ? config.manual_box as { x1: number; y1: number; x2: number; y2: number }
          : null;
        const headSec = Number(config.skip_head_sec) || 0;
        const tailSec = Number(config.skip_tail_sec) || 0;
        return (
          <div className="px-3 pb-3 pt-2 border-t border-border/50 space-y-2">
            {/* 定位方式标签页（顶部） */}
            <div className="grid grid-cols-2 gap-1 rounded-lg bg-muted/60 p-0.5">
              <button
                type="button"
                onPointerDown={(e) => e.stopPropagation()}
                onClick={(e) => { e.stopPropagation(); handleConfigChange("position_mode", "ocr"); }}
                className={cn(
                  "py-1 rounded-md text-[11px] font-medium transition-colors",
                  mode !== "manual" ? "bg-background shadow-sm text-foreground" : "text-muted-foreground hover:text-foreground/80"
                )}
              >
                OCR识别查找
              </button>
              <button
                type="button"
                onPointerDown={(e) => e.stopPropagation()}
                onClick={(e) => { e.stopPropagation(); handleConfigChange("position_mode", "manual"); }}
                className={cn(
                  "py-1 rounded-md text-[11px] font-medium transition-colors",
                  mode === "manual" ? "bg-background shadow-sm text-foreground" : "text-muted-foreground hover:text-foreground/80"
                )}
              >
                手动定位
              </button>
            </div>
            {mode === "manual" ? (
              /* 手动定位标签页：仅按钮 + 字幕框坐标显示 */
              <div className="space-y-2">
                <button
                  type="button"
                  onPointerDown={(e) => e.stopPropagation()}
                  onClick={(e) => { e.stopPropagation(); setSubtitleFindOpen(true); }}
                  className="w-full inline-flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded-md text-[11px] font-medium text-amber-700 dark:text-amber-300 bg-amber-500/10 border border-amber-500/20 hover:bg-amber-500/20 transition-colors"
                >
                  <Captions className="w-3.5 h-3.5" />
                  打开手动定位页面
                </button>
                <div className="rounded-md border border-amber-500/20 bg-amber-500/5 px-2 py-1.5 text-[10px] text-muted-foreground">
                  {mbox ? (
                    <span>
                      字幕框坐标（相对）：x {Math.min(mbox.x1, mbox.x2).toFixed(3)}~{Math.max(mbox.x1, mbox.x2).toFixed(3)} · y {Math.min(mbox.y1, mbox.y2).toFixed(3)}~{Math.max(mbox.y1, mbox.y2).toFixed(3)}
                    </span>
                  ) : (
                    <span>尚未框选字幕区域，请打开手动定位页面框选</span>
                  )}
                </div>
              </div>
            ) : (
              <ConfigForm
                nodeType={nodeType}
                config={config}
                onConfigChange={handleConfigChange}
                onVoiceSelect={setVoiceSelectField}
                onButtonAction={() => {
                  if (nodeType.id === "text_editor") openTextEditor();
                  else if (nodeType.id === "subtitle_editor") openSubtitleEditor();
                  else openJsonEditor();
                }}
              />
            )}
            {/* 片头/片尾跳过（卡片最底部，不受标签页影响，默认 0） */}
            <div className="grid grid-cols-2 gap-2 pt-1">
              <label className="flex items-center gap-1.5 text-[10px] text-muted-foreground min-w-0">
                <span className="flex-shrink-0">片头跳过</span>
                <input
                  type="number"
                  min={0}
                  step={0.5}
                  value={headSec}
                  onChange={(e) => handleConfigChange("skip_head_sec", Math.max(0, Number(e.target.value) || 0))}
                  onPointerDown={(e) => e.stopPropagation()}
                  onWheel={(e) => e.stopPropagation()}
                  className="min-w-0 flex-1 text-[11px] px-1.5 py-1 rounded-md border border-border/50 bg-background outline-none focus:border-primary/50"
                  placeholder="0"
                />
                <span className="flex-shrink-0">s</span>
              </label>
              <label className="flex items-center gap-1.5 text-[10px] text-muted-foreground min-w-0">
                <span className="flex-shrink-0">片尾跳过</span>
                <input
                  type="number"
                  min={0}
                  step={0.5}
                  value={tailSec}
                  onChange={(e) => handleConfigChange("skip_tail_sec", Math.max(0, Number(e.target.value) || 0))}
                  onPointerDown={(e) => e.stopPropagation()}
                  onWheel={(e) => e.stopPropagation()}
                  className="min-w-0 flex-1 text-[11px] px-1.5 py-1 rounded-md border border-border/50 bg-background outline-none focus:border-primary/50"
                  placeholder="0"
                />
                <span className="flex-shrink-0">s</span>
              </label>
            </div>
          </div>
        );
      })()}
      {hasConfig && expanded && nodeType.id !== "lcwr_watermark_removal" && nodeType.id !== "subtitle_position_search" && nodeType.id !== "qm_virtual_mailbox" && (
        <ConfigForm
          nodeType={nodeType}
          config={config}
          onConfigChange={handleConfigChange}
          onVoiceSelect={setVoiceSelectField}
          onButtonAction={() => {
            if (nodeType.id === "text_editor") openTextEditor();
            else if (nodeType.id === "subtitle_editor") openSubtitleEditor();
            else openJsonEditor();
          }}
        />
      )}

      {/* LCWR 预览设置弹窗 */}
      {nodeType.id === "lcwr_watermark_removal" && (
        <LcwrWatermarkEditor
          open={lcwrPreviewOpen}
          onOpenChange={setLcwrPreviewOpen}
          config={config}
          onConfigChange={handleConfigChange}
          videoPath={upstreamOutputs.video || config.video_path || config.input_video || nd.outputs?.video}
          imagePath={upstreamOutputs.image || config.image_path || config.input_image || nd.outputs?.image}
          taskId={previewTaskId}
        />
      )}

      {/* 在线去水印：水印区域设置弹窗（复用 LCWR 弹窗） */}
      {nodeType.id === "online_watermark_removal" && (
        <LcwrWatermarkEditor
          open={onlineWmPreviewOpen}
          onOpenChange={setOnlineWmPreviewOpen}
          config={{ ...config, regions: config.watermark_regions || [] }}
          onConfigChange={(key, value) => {
            if (key === "regions") {
              handleConfigChange("watermark_regions", value);
            } else {
              handleConfigChange(key, value);
            }
          }}
          videoPath={upstreamOutputs.video || config.video_path || nd.outputs?.video}
          imagePath={upstreamOutputs.image || config.image_path || nd.outputs?.image}
          taskId={previewTaskId}
        />
      )}

      {/* OCR字幕查找：手动定位弹窗 */}
      {nodeType.id === "subtitle_position_search" && (
        <SubtitleFindEditor
          open={subtitleFindOpen}
          onOpenChange={setSubtitleFindOpen}
          config={config}
          onConfigChange={handleConfigChange}
          videoPath={upstreamOutputs.video || config.video_path || config.input_video || nd.outputs?.video}
          taskId={previewTaskId}
        />
      )}

      {/* pi_agent: 输出产物设置板块 */}
      {isPiAgent && expanded && (
        <div className="px-3 pb-3 border-t border-border/50 pt-2 space-y-2">
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] font-semibold text-foreground">输出产物设置</span>
            <span className="text-[10px] text-muted-foreground">按输出端口逐条配置类型与描述</span>
          </div>
          {(() => {
            const count = Math.min(Math.max(Number(config.outputCount) || 2, 1), 8);
            const items: { port: string; type: string; desc: string }[] = Array.isArray(config.output_items)
              ? config.output_items.map((item: any, i: number) => ({
                port: String(item?.port || `输出${i + 1}`),
                type: String(item?.type || "text"),
                desc: String(item?.desc || ""),
              }))
              : [];
            const rows = Array.from({ length: count }, (_, i) => items[i] || { port: `输出${i + 1}`, type: "text", desc: "" });
            const updateItem = (index: number, patch: Partial<{ port: string; type: string; desc: string }>) => {
              const next = rows.map((row, i) => (i === index ? { ...row, ...patch } : row));
              handleConfigChange("output_items", next);
            };
            return (
              <div className="space-y-1.5">
                {rows.map((row, index) => (
                  <div key={index} className="flex items-center gap-1.5">
                    <input
                      value={row.port}
                      onChange={(e) => updateItem(index, { port: e.target.value })}
                      onPointerDown={(e) => e.stopPropagation()}
                      className="w-20 text-[11px] px-2 py-1 rounded-md border border-border/50 bg-background outline-none focus:border-primary/50"
                      placeholder={`输出${index + 1}`}
                    />
                    <select
                      value={row.type}
                      onChange={(e) => updateItem(index, { type: e.target.value })}
                      onPointerDown={(e) => e.stopPropagation()}
                      onWheel={(e) => e.stopPropagation()}
                      className="w-24 text-[11px] px-1.5 py-1 rounded-md border border-border/50 bg-background outline-none focus:border-primary/50"
                    >
                      {PI_AGENT_OUTPUT_TYPES.map((opt) => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                      ))}
                    </select>
                    <input
                      value={row.desc}
                      onChange={(e) => updateItem(index, { desc: e.target.value })}
                      onPointerDown={(e) => e.stopPropagation()}
                      className="min-w-0 flex-1 text-[11px] px-2 py-1 rounded-md border border-border/50 bg-background outline-none focus:border-primary/50"
                      placeholder={`输出${index + 1} 描述`}
                    />
                  </div>
                ))}
              </div>
            );
          })()}
        </div>
      )}

      {/* Preview Nodes */}
      {nodeType.id === "video_preview" && (
        <VideoPreview
          config={config}
          videoPath={nd.videoPath || upstreamOutputs.video || upstreamConfigs.videoPath}
          subtitlePath={nd.subtitlePath || upstreamOutputs.subtitle || upstreamOutputs.original || upstreamOutputs.bilingual || upstreamConfigs.subtitlePath}
          listPaths={normalizeListPaths(nd.listPath || upstreamOutputs.list || upstreamConfigs.listPath)}
          taskId={previewTaskId}
          onConfigChange={handleConfigChange}
          refreshKey={upstreamRefreshKey}
        />
      )}
      {nodeType.id === "image_preview" && (
        <ImagePreview config={config} imagePath={nd.imagePath || upstreamOutputs.image || upstreamConfigs.imagePath} listPaths={normalizeListPaths(nd.listPath || upstreamOutputs.list || upstreamConfigs.listPath)} taskId={previewTaskId} refreshKey={upstreamRefreshKey} />
      )}
      {nodeType.id === "image_compare" && (
        <ImageCompare
          config={config}
          image1Path={nd.image1Path || upstreamOutputs.image1 || upstreamConfigs.image1Path}
          image2Path={nd.image2Path || upstreamOutputs.image2 || upstreamConfigs.image2Path}
          taskId={previewTaskId}
          refreshKey={upstreamRefreshKey}
        />
      )}

      {/* Output Display Panel - shows results/errors after execution */}
      {status === "completed" && dedupedOutputEntries.length > 0 && (() => {
        // Separate file-based outputs from text/JSON outputs
        const fileEntries: [string, string | number][] = [];
        const jsonEntries: [string, string][] = [];
        for (const [key, val] of dedupedOutputEntries) {
          const s = String(val);
          if (key === "text" && s.trimStart().startsWith("{")) {
            jsonEntries.push([key, s]);
          } else {
            fileEntries.push([key, val as string | number]);
          }
        }
        if (fileEntries.length === 0 && jsonEntries.length === 0) return null;
        return (
          <div className="px-3 pb-3 border-t border-border/50 pt-2">
            <div className="flex items-center gap-1.5 mb-1.5">
              <FileText className="w-3 h-3 text-emerald-500" />
              <span className="text-[11px] font-semibold text-emerald-600 dark:text-emerald-400">{"输出产物"}</span>
            </div>
            <div className="space-y-1">
              {/* File-based outputs */}
              {fileEntries.map(([key, filePath]) => {
                const raw = String(filePath).replace(/\\/g, "/");
                const full = raw.split("/").pop() || String(filePath);
                const ext = full.includes(".") ? full.substring(full.lastIndexOf(".")) : "";
                const base = full.includes(".") ? full.substring(0, full.lastIndexOf(".")) : full;
                const displayName = base.length > 15 ? base.substring(0, 8) + "..." + base.substring(base.length - 5) + ext : full;
                return (
                  <button
                    key={key}
                    onClick={(e) => {
                      e.stopPropagation();
                      client.post("/api/tasks/open-file", { file_path: String(filePath), task_id: previewTaskId }).catch(() => { });
                    }}
                    className="flex items-center gap-2 text-[10px] px-2 py-1 rounded-md bg-emerald-500/5 border border-emerald-500/20 w-full text-left hover:bg-emerald-500/15 transition-colors cursor-pointer group"
                    title={full}
                  >
                    <span className="font-medium text-emerald-600 dark:text-emerald-400 flex-shrink-0">{key}</span>
                    <span className="text-muted-foreground truncate group-hover:text-foreground transition-colors">{displayName}</span>
                  </button>
                );
              })}
              {/* JSON preview outputs */}
              {jsonEntries.map(([key, jsonStr]) => {
                let parsed: any = null;
                try { parsed = JSON.parse(jsonStr); } catch { /* not valid JSON */ }
                const summary = parsed
                  ? (parsed.success !== undefined ? `${parsed.success}成功 / ${parsed.failed ?? 0}失败` : "")
                  : "";
                return (
                  <div key={key} className="rounded-md bg-emerald-500/5 border border-emerald-500/20">
                    <div className="flex items-center gap-1 text-[10px] px-2 py-1">
                      <button
                        onClick={(e) => { e.stopPropagation(); setJsonPreviewOpen(!jsonPreviewOpen); }}
                        className="flex items-center gap-1 flex-1 text-left hover:bg-emerald-500/15 transition-colors cursor-pointer rounded-sm -ml-0.5 px-0.5"
                      >
                        {jsonPreviewOpen
                          ? <ChevronDown className="w-3 h-3 text-emerald-500 flex-shrink-0" />
                          : <ChevronRight className="w-3 h-3 text-emerald-500 flex-shrink-0" />
                        }
                        <span className="font-medium text-emerald-600 dark:text-emerald-400">发布结果</span>
                        {summary && <span className="text-muted-foreground">{summary}</span>}
                      </button>
                      {parsed?.publish_params?.video_path && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            // Try to open the result JSON file from the task output directory
                            const vp = parsed.publish_params.video_path as string;
                            const taskDir = vp.substring(0, vp.lastIndexOf("/output/")) || vp.substring(0, vp.lastIndexOf("\\output\\"));
                            if (taskDir) {
                              client.post("/api/tasks/open-file", { file_path: taskDir + "/output", task_id: previewTaskId }).catch(() => { });
                            }
                          }}
                          className="text-emerald-600/60 hover:text-emerald-600 transition-colors cursor-pointer flex-shrink-0"
                          title="打开输出目录"
                        >
                          <Eye className="w-3 h-3" />
                        </button>
                      )}
                    </div>
                    {jsonPreviewOpen && parsed && (
                      <div className="px-2 pb-2 max-h-48 overflow-y-auto">
                        {/* Summary section */}
                        {parsed.publish_params && (
                          <div className="mb-1.5 space-y-0.5">
                            <div className="text-[10px] text-emerald-600/80 font-semibold">发布参数</div>
                            {Object.entries(parsed.publish_params).map(([pk, pv]) => (
                              pv ? <div key={pk} className="flex gap-1.5 text-[9px]">
                                <span className="text-muted-foreground/70 flex-shrink-0 w-24 text-right">{pk}:</span>
                                <span className="text-foreground/80 break-all">{typeof pv === "object" ? JSON.stringify(pv) : String(pv)}</span>
                              </div> : null
                            ))}
                          </div>
                        )}
                        {/* Raw JSON */}
                        <details className="mt-1">
                          <summary className="text-[9px] text-muted-foreground/70 cursor-pointer hover:text-foreground">原始 JSON</summary>
                          <pre className="text-[9px] text-foreground/70 whitespace-pre-wrap break-all mt-1 p-1.5 rounded bg-muted/30 max-h-32 overflow-y-auto">
                            {JSON.stringify(parsed, null, 2)}
                          </pre>
                        </details>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        );
      })()}

      {/* Error Display Panel - shows errors after failure */}
      {status === "failed" && nd.error && (
        <div className="px-3 pb-3 border-t border-border/50 pt-2">
          <div className="flex items-center gap-1.5 mb-1.5">
            <AlertTriangle className="w-3 h-3 text-red-500" />
            <span className="text-[11px] font-semibold text-red-600 dark:text-red-400">{"执行错误"}</span>
          </div>
          <div className="text-[10px] text-red-600/80 dark:text-red-400/80 px-2 py-1.5 rounded-md bg-red-500/5 border border-red-500/20 break-all max-h-20 overflow-y-auto">
            {nd.error}
          </div>
        </div>
      )}

      {/* Output Handles (dynamic for input node) */}
      {visibleOutputs.map((port: any, i: number) => (
        <Handle
          key={"out-" + port.id}
          type="source"
          position={Position.Right}
          id={"out-" + port.id}
          style={handleStyle(port.type, i, visibleOutputs.length, port.color)}
        />
      ))}

      {/* Voice Select Panel */}
      {voiceSelectField && (
        <VoiceSelectPanel
          interfaceId={config[voiceSelectField.interfaceIdKey] || ""}
          selected={config[voiceSelectField.key] || ""}
          onSelect={(voiceId) => {
            handleConfigChange(voiceSelectField.key, voiceId);
            setVoiceSelectField(null);
          }}
          open={!!voiceSelectField}
          onClose={() => setVoiceSelectField(null)}
        />
      )}

      {/* JSON 可视化编辑弹窗 */}
      {nodeType.id === "json_visual_editor" && (
        <JsonEditorDialog
          open={jsonEditorOpen}
          initialJson={editorInitialJson}
          onClose={() => setJsonEditorOpen(false)}
          onSave={(data) => handleConfigChange("edited_json", JSON.stringify(data, null, 2))}
          onRun={() => nd.onExecuteNode?.(id)}
        />
      )}

      {/* 文本编辑弹窗 */}
      {nodeType.id === "text_editor" && (
        <TextEditorDialog
          open={textEditorOpen}
          initialText={textEditorInitialText}
          onClose={() => setTextEditorOpen(false)}
          onSave={(text) => handleConfigChange("edited_text", text)}
          onRun={() => nd.onExecuteNode?.(id)}
        />
      )}

      {/* 字幕编辑弹窗 */}
      {nodeType.id === "subtitle_editor" && (
        <SubtitleEditorDialog
          open={subtitleEditorOpen}
          initialEntries={subtitleEditorEntries}
          initialVideo={subtitleEditorVideo}
          taskId={previewTaskId}
          onClose={() => setSubtitleEditorOpen(false)}
          onSave={(entries) => handleConfigChange("edited_subtitles", JSON.stringify(entries))}
          onRun={() => nd.onExecuteNode?.(id)}
        />
      )}
    </div>
  );
}

export default memo(WorkflowNodeComponent);
;

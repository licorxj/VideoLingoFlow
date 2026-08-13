import { useState, useEffect, useCallback } from "react";
import { ChevronDown, ChevronRight, Layers, Play, Square, RotateCcw, RefreshCw, Trash2, X, Plus, FolderOpen, Upload, FileText, Trash } from "lucide-react";
import { cn } from "@/lib/utils";
import { batchApi, BatchDetail } from "@/api/batch";
import { nativeFileDialog } from "@/api/files";
import { useAlert } from "@/components/ui/AlertProvider";
import client from "@/api/client";
import BatchTaskItem from "./BatchTaskItem";

interface SavedWorkflow {
  id: string;
  name: string;
  description: string;
  nodeCount: number;
  updatedAt: string;
}

const TYPE_CONFIG: Record<string, { key: string; label: string; filter: [string, string][] }> = {
  video: { key: "videoPath", label: "视频", filter: [["Video", "*.mp4;*.avi;*.mkv;*.mov;*.wmv;*.flv;*.webm"]] },
  audio: { key: "audioPath", label: "音频", filter: [["Audio", "*.mp3;*.wav;*.flac;*.aac;*.ogg;*.m4a"]] },
  subtitle: { key: "subtitlePath", label: "字幕", filter: [["Subtitle", "*.srt;*.ass;*.ssa;*.vtt;*.txt"]] },
  url: { key: "url", label: "URL", filter: [] },
};

interface Props {
  batch: BatchDetail;
  loading: boolean;
  onRefresh: () => void;
}

function formatTime(ts: string) {
  if (!ts) return "-";
  try {
    return ts.replace("T", " ").substring(0, 19);
  } catch {
    return ts;
  }
}

export default function BatchGroupCard({ batch, loading, onRefresh }: Props) {
  const { alert: showAlert, confirm: showConfirm } = useAlert();
  const [expanded, setExpanded] = useState(true);
  const [selectedTasks, setSelectedTasks] = useState<Set<string>>(new Set());
  const [batchActionLoading, setBatchActionLoading] = useState(false);
  const [syncModalOpen, setSyncModalOpen] = useState(false);
  const [workflows, setWorkflows] = useState<SavedWorkflow[]>([]);
  const [syncLoading, setSyncLoading] = useState(false);

  // Add tasks dialog state
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [addInputTypes, setAddInputTypes] = useState<string[]>([]);
  const [addEntries, setAddEntries] = useState<Record<string, string[]>>({});
  const [addSourceLang, setAddSourceLang] = useState("auto");
  const [addTargetLang, setAddTargetLang] = useState("zh");
  const [addLoading, setAddLoading] = useState(false);
  const [addError, setAddError] = useState("");

  const tasks = batch.tasks || [];
  const workflowNodes = batch.workflow_nodes || [];

  const completedCount = tasks.filter((t) => t.status === "completed").length;
  const failedCount = tasks.filter((t) => t.status === "failed" || t.status === "cancelled").length;
  const runningCount = tasks.filter((t) => t.status === "running").length;

  const statusBadge = (() => {
    switch (batch.status) {
      case "completed": return { label: "全部完成", cls: "bg-emerald-500/10 text-emerald-600" };
      case "running": return { label: "执行中", cls: "bg-blue-500/10 text-blue-600" };
      case "failed": return { label: "失败", cls: "bg-red-500/10 text-red-600" };
      case "partial": return { label: "部分完成", cls: "bg-amber-500/10 text-amber-600" };
      case "paused": return { label: "已暂停", cls: "bg-amber-500/10 text-amber-600" };
      default: return { label: "待执行", cls: "bg-muted text-muted-foreground" };
    }
  })();

  const handleSelectTask = (taskId: string, checked: boolean) => {
    setSelectedTasks((prev) => {
      const next = new Set(prev);
      if (checked) next.add(taskId);
      else next.delete(taskId);
      return next;
    });
  };

  const handleAction = async (action: () => Promise<any>) => {
    setBatchActionLoading(true);
    try {
      await action();
      onRefresh();
    } catch (e: any) {
      showAlert(e?.response?.data?.detail || e?.message || "操作失败");
    } finally {
      setBatchActionLoading(false);
    }
  };

  const handleSelectedAction = async (actionName: string, action: (taskId: string) => Promise<any>) => {
    if (selectedTasks.size === 0) {
      showAlert("没有选择任务，请选择之后再执行");
      return;
    }
    setBatchActionLoading(true);
    try {
      const results = await Promise.allSettled(
        Array.from(selectedTasks).map((taskId) => action(taskId))
      );
      const failed = results.filter((r) => r.status === "rejected");
      if (failed.length > 0) {
        showAlert(`${actionName}完成，但有 ${failed.length} 个任务操作失败`);
      }
      onRefresh();
    } catch (e: any) {
      showAlert(e?.response?.data?.detail || e?.message || "操作失败");
    } finally {
      setBatchActionLoading(false);
    }
  };

  const handleDeleteSelected = async () => {
    if (selectedTasks.size === 0) return;
    if (!(await showConfirm(`确定要删除选中的 ${selectedTasks.size} 个任务？`))) return;
    setBatchActionLoading(true);
    try {
      const res: any = await batchApi.deleteTasks(batch.batch_id, Array.from(selectedTasks));
      if (res?.data?.blocked?.length) {
        showAlert(`${res.data.blocked.length} 个任务正在执行或停止中，无法删除，请先停止后再操作`);
      }
      setSelectedTasks(new Set());
      onRefresh();
    } catch (e: any) {
      showAlert(e?.response?.data?.detail || e?.message || "删除失败");
    } finally {
      setBatchActionLoading(false);
    }
  };

  const handleDeleteFailed = async () => {
    const failedIds = tasks.filter((t) => t.status === "failed" || t.status === "cancelled").map((t) => t.task_id);
    if (failedIds.length === 0) return;
    if (!(await showConfirm(`确定要删除 ${failedIds.length} 个失败/已取消的任务？`))) return;
    setBatchActionLoading(true);
    try {
      const res: any = await batchApi.deleteTasks(batch.batch_id, failedIds);
      if (res?.data?.blocked?.length) {
        showAlert(`${res.data.blocked.length} 个任务正在执行或停止中，无法删除`);
      }
      onRefresh();
    } catch (e: any) {
      showAlert(e?.response?.data?.detail || e?.message || "删除失败");
    } finally {
      setBatchActionLoading(false);
    }
  };

  const handleDeleteBatch = async () => {
    if (!(await showConfirm("确定要删除整个批次？运行中的任务将不会被删除"))) return;
    setBatchActionLoading(true);
    try {
      const res: any = await batchApi.deleteBatch(batch.batch_id);
      if (res?.data?.blocked?.length) {
        showAlert(`${res.data.blocked.length} 个任务正在执行或停止中，未被删除，请先停止后再操作`);
      }
      onRefresh();
    } catch (e: any) {
      showAlert(e?.response?.data?.detail || e?.message || "删除失败");
    } finally {
      setBatchActionLoading(false);
    }
  };

  const toggleSelectAll = () => {
    if (selectedTasks.size === tasks.length) {
      setSelectedTasks(new Set());
    } else {
      setSelectedTasks(new Set(tasks.map((t) => t.task_id)));
    }
  };

  const toggleInvert = () => {
    const all = new Set(tasks.map((t) => t.task_id));
    const next = new Set([...all].filter((id) => !selectedTasks.has(id)));
    setSelectedTasks(next);
  };

  const openSyncModal = async () => {
    setSyncModalOpen(true);
    try {
      const res = await client.get("/api/workflows");
      setWorkflows(res.data?.workflows || []);
    } catch {}
  };

  const handleSyncWorkflow = async (workflowId: string) => {
    setSyncLoading(true);
    try {
      await batchApi.syncWorkflow(batch.batch_id, workflowId);
      setSyncModalOpen(false);
      onRefresh();
    } catch (e: any) {
      showAlert(e?.response?.data?.detail || e?.message || "同步失败");
    } finally {
      setSyncLoading(false);
    }
  };

  // ── Add tasks dialog ──
  const openAddModal = async () => {
    setAddModalOpen(true);
    setAddError("");
    const inputNode = (batch.workflow?.nodes || []).find((n: any) => n.data?.nodeType === "input");
    if (!inputNode) {
      setAddError("当前批次的私有工作流未包含输入节点，无法追加任务");
      return;
    }
    const cfg = inputNode.data?.config || {};
    const types = cfg.selectedTypes || ["video"];
    setAddInputTypes(types);
    const init: Record<string, string[]> = {};
    types.forEach((t: string) => { init[t] = []; });
    setAddEntries(init);
    setAddSourceLang(cfg.source_language || "auto");
    setAddTargetLang(cfg.target_language || "zh");
  };

  const addEntryItems = useCallback((type: string, paths: string[]) => {
    setAddEntries((prev) => {
      const existing = prev[type] || [];
      const newPaths = paths.filter((p) => p.trim() && !existing.includes(p));
      if (newPaths.length === 0) return prev;
      return { ...prev, [type]: [...existing, ...newPaths] };
    });
  }, []);

  const removeAddEntry = useCallback((type: string, idx: number) => {
    setAddEntries((prev) => ({ ...prev, [type]: prev[type].filter((_, i) => i !== idx) }));
  }, []);

  const pickAddFiles = async (type: string) => {
    const cfg = TYPE_CONFIG[type];
    if (!cfg || cfg.filter.length === 0) return;
    try {
      const paths = await nativeFileDialog("file", `选择${cfg.label}文件`, cfg.filter, true);
      if (Array.isArray(paths) && paths.length > 0) addEntryItems(type, paths);
    } catch {}
  };

  const handleAddTasks = async () => {
    const nonEmpty: Record<string, string[]> = {};
    for (const t of addInputTypes) {
      nonEmpty[t] = (addEntries[t] || []).filter((v) => v.trim());
    }
    const taskCount = nonEmpty[addInputTypes[0]]?.length || 0;
    if (taskCount === 0) {
      setAddError("请至少添加一个输入");
      return;
    }
    const tasks: Record<string, string>[] = [];
    for (let i = 0; i < taskCount; i++) {
      const task: Record<string, string> = {};
      for (const t of addInputTypes) {
        task[TYPE_CONFIG[t]?.key || t] = nonEmpty[t]?.[i] || "";
      }
      tasks.push(task);
    }
    setAddLoading(true);
    setAddError("");
    try {
      await batchApi.addTasks(batch.batch_id, tasks, {
        source_language: addSourceLang,
        target_language: addTargetLang,
      });
      setAddModalOpen(false);
      onRefresh();
    } catch (e: any) {
      setAddError(e?.response?.data?.detail || e?.message || "添加失败");
    } finally {
      setAddLoading(false);
    }
  };

  return (
    <>
    <div className="border border-border/50 rounded-2xl bg-card overflow-hidden">
      {/* Header */}
      <div
        className="flex items-center justify-between px-5 py-3 cursor-pointer hover:bg-accent/30 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-3">
          <button className="p-0.5">
            {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          </button>
          <Layers className="w-4 h-4 text-primary" />
          <div>
            <h3 className="text-sm font-bold">{batch.name}</h3>
            <p className="text-[11px] text-muted-foreground">
              {batch.workflow_name} · {formatTime(batch.created_at)}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className={cn("text-[10px] font-semibold px-2 py-0.5 rounded-md", statusBadge.cls)}>
            {statusBadge.label}
          </span>
          <span className="text-[11px] font-medium px-2.5 py-1 rounded-full bg-cyan-500/10 text-cyan-600 border border-cyan-500/20">
            {completedCount}/{tasks.length} 完成
            {failedCount > 0 && <span className="text-red-500"> · {failedCount} 失败</span>}
            {runningCount > 0 && <span className="text-cyan-500"> · {runningCount} 运行中</span>}
          </span>
        </div>
      </div>

      {/* Expanded content */}
      {expanded && (
        <div className="border-t border-border/40">
          {/* Batch action bar */}
          <div className="flex items-center justify-between px-5 py-2 bg-muted/20">
            <div className="flex items-center gap-2">
              <button
                onClick={(e) => { e.stopPropagation(); handleSelectedAction("恢复执行", (taskId) => batchApi.resumeTask(batch.batch_id, taskId)); }}
                disabled={batchActionLoading}
                className="flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md bg-primary/10 text-primary hover:bg-primary/20 transition-colors disabled:opacity-50"
              >
                <Play className="w-3 h-3" />开始
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); handleSelectedAction("从头执行", (taskId) => batchApi.retryTask(batch.batch_id, taskId)); }}
                disabled={batchActionLoading}
                className="flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md bg-orange-500/10 text-orange-600 hover:bg-orange-500/20 transition-colors disabled:opacity-50"
              >
                <RotateCcw className="w-3 h-3" />从头执行
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); handleSelectedAction("停止", (taskId) => batchApi.cancelTask(batch.batch_id, taskId)); }}
                disabled={batchActionLoading}
                className="flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md bg-red-500/10 text-red-600 hover:bg-red-500/20 transition-colors disabled:opacity-50"
              >
                <Square className="w-3 h-3" />停止
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); openSyncModal(); }}
                disabled={batchActionLoading}
                className="flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md bg-blue-500/10 text-blue-600 hover:bg-blue-500/20 transition-colors disabled:opacity-50"
              >
                <RefreshCw className="w-3 h-3" />同步工作流
              </button>
              <span className="w-px h-4 bg-border/60" />
              <button
                onClick={(e) => { e.stopPropagation(); openAddModal(); }}
                disabled={batchActionLoading}
                className="flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md bg-emerald-500/10 text-emerald-600 hover:bg-emerald-500/20 transition-colors disabled:opacity-50"
              >
                <Plus className="w-3 h-3" />添加任务
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); handleDeleteBatch(); }}
                disabled={batchActionLoading}
                className="flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-md hover:bg-red-50 text-muted-foreground hover:text-red-500 transition-colors disabled:opacity-50"
              >
                <Trash2 className="w-3 h-3" />删除批次
              </button>
            </div>
          </div>

          {/* Task list */}
          <div className="px-5 py-3 space-y-2">
            {/* Selection bar */}
            {tasks.length > 0 && (
              <div className="flex items-center gap-3 mb-2">
                <button
                  onClick={toggleSelectAll}
                  className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                >
                  {selectedTasks.size === tasks.length ? "取消全选" : "全选"}
                </button>
                <button
                  onClick={toggleInvert}
                  className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                >
                  反选
                </button>
                {selectedTasks.size > 0 && (
                  <>
                    <span className="w-px h-3 bg-border/60" />
                    <button
                      onClick={handleDeleteSelected}
                      className="text-xs text-red-500 hover:text-red-600 transition-colors"
                    >
                      删除选中 ({selectedTasks.size})
                    </button>
                  </>
                )}
                {failedCount > 0 && (
                  <>
                    <span className="w-px h-3 bg-border/60" />
                    <button
                      onClick={handleDeleteFailed}
                      className="text-xs text-muted-foreground hover:text-red-500 transition-colors"
                    >
                      删除失败 ({failedCount})
                    </button>
                  </>
                )}
                <span className="flex-1" />
                <span className="text-xs text-muted-foreground">
                  已选 {selectedTasks.size}/{tasks.length}
                </span>
              </div>
            )}

            {tasks.map((task) => (
              <BatchTaskItem
                key={task.task_id}
                task={task}
                batchId={batch.batch_id}
                workflowNodes={workflowNodes}
                selected={selectedTasks.has(task.task_id)}
                onSelect={handleSelectTask}
                onResume={(taskId) => handleAction(() => batchApi.resumeTask(batch.batch_id, taskId))}
                onRetry={(taskId) => handleAction(() => batchApi.retryTask(batch.batch_id, taskId))}
                onCancel={(taskId) => handleAction(() => batchApi.cancelTask(batch.batch_id, taskId))}
              />
            ))}
          </div>
        </div>
      )}
    </div>

    {/* Sync workflow modal */}
    {syncModalOpen && (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={() => setSyncModalOpen(false)}>
        <div className="bg-background border border-border/60 rounded-2xl shadow-2xl w-[min(420px,90vw)]" onClick={(e) => e.stopPropagation()}>
          <div className="flex items-center justify-between px-6 pt-5 pb-2">
            <div>
              <h3 className="text-lg font-bold">选择工作流</h3>
              <p className="text-xs text-muted-foreground mt-1">选择要同步到的目标工作流</p>
            </div>
            <button onClick={() => setSyncModalOpen(false)} className="p-1.5 rounded-lg hover:bg-secondary transition-colors">
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="px-6 py-4 max-h-[60vh] overflow-y-auto space-y-1">
            {workflows.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">暂无可用工作流</p>
            ) : (
              workflows.map((wf) => (
                <button
                  key={wf.id}
                  onClick={() => handleSyncWorkflow(wf.id)}
                  disabled={syncLoading}
                  className="w-full text-left px-4 py-3 rounded-xl border border-border/40 hover:bg-accent/50 transition-colors disabled:opacity-50"
                >
                  <div className="text-sm font-semibold">{wf.name}</div>
                  <div className="text-xs text-muted-foreground mt-0.5">{wf.description || "无描述"}</div>
                </button>
              ))
            )}
          </div>
          <div className="px-6 pb-5 pt-2 flex justify-end">
            <button onClick={() => setSyncModalOpen(false)} className="px-4 py-2 text-sm font-medium border border-border/60 rounded-xl hover:bg-secondary/70 transition-colors">取消</button>
          </div>
        </div>
      </div>
    )}

    {/* Add tasks modal */}
    {addModalOpen && (
      <div className="fixed inset-0 z-50 flex items-start justify-center pt-20 bg-black/50 backdrop-blur-sm" onClick={() => setAddModalOpen(false)}>
        <div className="bg-card border border-border/50 rounded-2xl shadow-2xl w-[600px] max-h-[70vh] flex flex-col animate-scale-in" onClick={(e) => e.stopPropagation()}>
          <div className="flex items-center justify-between px-6 py-4 border-b border-border/40 flex-shrink-0">
            <div>
              <h3 className="text-lg font-bold">添加任务到「{batch.name}」</h3>
              <p className="text-xs text-muted-foreground mt-1">工作流: {batch.workflow_name}</p>
            </div>
            <button onClick={() => setAddModalOpen(false)} className="p-1.5 rounded-lg hover:bg-muted transition-colors">
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
            {/* Language */}
            <div className="flex gap-4">
              <div className="flex-1">
                <label className="text-xs font-semibold mb-1 block">源语言</label>
                <input className="w-full px-3 py-1.5 text-sm rounded-lg border border-border/60 bg-background" value={addSourceLang} onChange={(e) => setAddSourceLang(e.target.value)} />
              </div>
              <div className="flex-1">
                <label className="text-xs font-semibold mb-1 block">目标语言</label>
                <input className="w-full px-3 py-1.5 text-sm rounded-lg border border-border/60 bg-background" value={addTargetLang} onChange={(e) => setAddTargetLang(e.target.value)} />
              </div>
            </div>

            {/* Input entries per type */}
            {addInputTypes.map((type) => {
              const cfg = TYPE_CONFIG[type];
              if (!cfg) return null;
              const items = addEntries[type] || [];
              const isUrl = type === "url";
              const validCount = items.filter((v) => v.trim()).length;

              return (
                <div key={type}>
                  <label className="text-xs font-semibold mb-1.5 block">{cfg.label} {isUrl ? "地址" : "文件"} ({validCount}个)</label>
                  <div className="flex gap-3">
                    <div className="flex-1 space-y-1 max-h-[140px] overflow-y-auto rounded-lg border border-border/40 bg-muted/20 p-2">
                      {items.length === 0 ? (
                        <p className="text-xs text-muted-foreground text-center py-3">暂无{cfg.label}，请在右侧添加</p>
                      ) : (
                        items.map((val, idx) => (
                          <div key={idx} className="flex items-center gap-2 px-1 py-0.5 rounded hover:bg-accent/50 group">
                            <span className="text-[10px] text-muted-foreground w-5 text-right flex-shrink-0">{idx + 1}</span>
                            {isUrl ? (
                              <input
                                className="flex-1 text-xs px-2 py-1 rounded border border-border/40 bg-background"
                                value={val}
                                onChange={(e) => setAddEntries((prev) => { const u = [...(prev[type] || [])]; u[idx] = e.target.value; return { ...prev, [type]: u }; })}
                              />
                            ) : (
                              <span className="text-xs truncate flex-1" title={val}>{val || "(空)"}</span>
                            )}
                            <button onClick={() => removeAddEntry(type, idx)} className="p-0.5 rounded opacity-0 group-hover:opacity-100 hover:bg-red-50 text-muted-foreground hover:text-red-500 transition-all flex-shrink-0">
                              <Trash className="w-3 h-3" />
                            </button>
                          </div>
                        ))
                      )}
                    </div>
                    <div className="flex flex-col gap-2 w-[110px] flex-shrink-0">
                      {isUrl ? (
                        <>
                          <button onClick={() => setAddEntries((prev) => ({ ...prev, [type]: [...(prev[type] || []), ""] }))} className="flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium rounded-lg border border-border/60 hover:bg-accent transition-colors">
                            <Plus className="w-3 h-3" />添加URL
                          </button>
                          <button onClick={async () => {
                            try {
                              const paths = await nativeFileDialog("file", "选择包含URL的txt文件", [["Text", "*.txt"]], false);
                              const filePath = typeof paths === "string" ? paths : (Array.isArray(paths) ? paths[0] : "");
                              if (!filePath) return;
                              const res = await client.get("/api/files/read", { params: { path: filePath } });
                              const text = res?.data?.content || res?.data?.text || "";
                              const urls = text.split(/\r?\n/).map((l: string) => l.trim()).filter((l: string) => l.length > 0);
                              if (urls.length > 0) setAddEntries((prev) => ({ ...prev, [type]: [...(prev[type] || []), ...urls] }));
                            } catch {}
                          }} className="flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium rounded-lg border border-border/60 hover:bg-accent transition-colors">
                            <FileText className="w-3 h-3" />导入txt
                          </button>
                        </>
                      ) : (
                        <button onClick={() => pickAddFiles(type)} className="flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium rounded-lg border border-border/60 hover:bg-accent transition-colors">
                          <FolderOpen className="w-3 h-3" />多选文件
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}

            {addError && (
              <p className="text-sm text-red-500">{addError}</p>
            )}
          </div>

          <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border/40 flex-shrink-0">
            <button onClick={() => setAddModalOpen(false)} className="px-4 py-2 text-sm font-medium rounded-lg border border-border/60 hover:bg-accent transition-colors">取消</button>
            <button
              onClick={handleAddTasks}
              disabled={addLoading}
              className="px-5 py-2 text-sm font-semibold rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-all active:scale-95"
            >
              {addLoading ? "添加中..." : "添加任务"}
            </button>
          </div>
        </div>
      </div>
    )}
    </>
  );
}

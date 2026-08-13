import { useState, useEffect, useRef, useCallback } from "react";
import { X, Plus, Trash2, CheckCircle, AlertCircle, FolderOpen, Upload, FileText } from "lucide-react";
import { cn } from "@/lib/utils";
import { batchApi } from "@/api/batch";
import { nativeFileDialog } from "@/api/files";
import client from "@/api/client";
import { getSubscriptionError, getQuotaExhaustedMessage, isSubscriptionBlocked } from "@/api/subscription";
import { useSubscriptionStore } from "@/stores/subscriptionStore";

interface Props {
  onClose: () => void;
  onCreated: () => void;
}

interface WorkflowSummary {
  id: string;
  name: string;
  description?: string;
  nodeCount?: number;
  updatedAt?: string;
}

interface LangOption {
  label: string;
  value: string;
}

// Map input types to their config keys and filters
const TYPE_CONFIG: Record<string, { key: string; label: string; filter: [string, string][] }> = {
  video: { key: "videoPath", label: "视频", filter: [["Video", "*.mp4;*.avi;*.mkv;*.mov;*.wmv;*.flv;*.webm"]] },
  audio: { key: "audioPath", label: "音频", filter: [["Audio", "*.mp3;*.wav;*.flac;*.aac;*.ogg;*.m4a"]] },
  subtitle: { key: "subtitlePath", label: "字幕", filter: [["Subtitle", "*.srt;*.ass;*.ssa;*.vtt;*.txt"]] },
  url: { key: "url", label: "URL", filter: [] },
};

function buildLanguageOptions(langs: Record<string, string>): LangOption[] {
  return Object.entries(langs).map(([value, label]) => ({ value, label }));
}

export default function CreateBatchDialog({ onClose, onCreated }: Props) {
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([]);
  const [selectedWfId, setSelectedWfId] = useState("");
  const [wfDetail, setWfDetail] = useState<any>(null);
  const [inputTypes, setInputTypes] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [batchName, setBatchName] = useState("");
  const [validationError, setValidationError] = useState("");
  const [validationPassed, setValidationPassed] = useState(false);
  const [languageOptions, setLanguageOptions] = useState<LangOption[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const dropRef = useRef<HTMLDivElement>(null);

  // Per-type file/url entries
  const [entries, setEntries] = useState<Record<string, string[]>>({});

  const [sourceLang, setSourceLang] = useState("auto");
  const [targetLang, setTargetLang] = useState("zh");

  // Load workflows
  useEffect(() => {
    client.get("/api/workflows").then((r) => {
      setWorkflows(r.data?.workflows || []);
    }).catch(() => setWorkflows([]));
  }, []);

  // Load language options from backend
  useEffect(() => {
    client.get("/api/files/languages").then((r) => {
      const langs = r.data?.languages || {};
      setLanguageOptions(buildLanguageOptions(langs));
    }).catch(() => {
      // Fallback
      setLanguageOptions([
        { value: "auto", label: "自动检测" },
        { value: "zh", label: "中文（普通话）" },
        { value: "en", label: "英语" },
        { value: "ja", label: "日语" },
        { value: "ko", label: "韩语" },
        { value: "fr", label: "法语" },
        { value: "de", label: "德语" },
        { value: "es", label: "西班牙语" },
        { value: "ru", label: "俄语" },
      ]);
    });
  }, []);

  // Load workflow detail when selected
  useEffect(() => {
    if (!selectedWfId) return;
    setLoading(true);
    client.get(`/api/workflows/${selectedWfId}`)
      .then((r) => {
        const wf = r.data?.workflow || r.data;
        setWfDetail(wf);
        const inputNode = (wf.nodes || []).find((n: any) => n.data?.nodeType === "input");
        if (inputNode) {
          const config: any = inputNode.data?.config || {};
          const types = config.selectedTypes || ["video"];
          setInputTypes(types);
          const init: Record<string, string[]> = {};
          types.forEach((t: string) => { init[t] = []; });
          setEntries(init);
          setSourceLang(config.source_language || "auto");
          setTargetLang(config.target_language || "zh");
        }
        setValidationPassed(false);
        setValidationError("");
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [selectedWfId]);

  // Default batch name
  useEffect(() => {
    if (!batchName) {
      const now = new Date();
      const ts = now.getFullYear() +
        String(now.getMonth() + 1).padStart(2, "0") +
        String(now.getDate()).padStart(2, "0") + "_" +
        String(now.getHours()).padStart(2, "0") +
        String(now.getMinutes()).padStart(2, "0") +
        String(now.getSeconds()).padStart(2, "0");
      setBatchName(ts);
    }
  }, []);

  // ── Entry helpers ──
  const addEntries = useCallback((type: string, paths: string[]) => {
    setEntries((prev) => {
      const existing = prev[type] || [];
      // Filter out duplicates and empties
      const newPaths = paths.filter((p) => p.trim() && !existing.includes(p));
      if (newPaths.length === 0) return prev;
      return { ...prev, [type]: [...existing, ...newPaths] };
    });
  }, []);

  const removeEntry = useCallback((type: string, idx: number) => {
    setEntries((prev) => ({
      ...prev,
      [type]: prev[type].filter((_, i) => i !== idx),
    }));
    setValidationPassed(false);
  }, []);

  // ── File dialog: multi-select ──
  const pickFiles = async (type: string) => {
    const cfg = TYPE_CONFIG[type];
    if (!cfg || cfg.filter.length === 0) return;
    try {
      const paths = await nativeFileDialog("file", `选择${cfg.label}文件`, cfg.filter, true);
      if (Array.isArray(paths) && paths.length > 0) {
        addEntries(type, paths);
      }
    } catch {}
  };

  // ── URL: import from txt ──
  const importUrlsFromTxt = async (type: string) => {
    const cfg = TYPE_CONFIG[type];
    try {
      const paths = await nativeFileDialog("file", "选择包含URL的txt文件", [["Text", "*.txt"]], false);
      const filePath = typeof paths === "string" ? paths : (Array.isArray(paths) ? paths[0] : "");
      if (!filePath) return;
      // 读取 txt 文件内容（/api/files/read 为现有文本读取端点，返回 {content, path}）
      const res = await client.get("/api/files/read", { params: { path: filePath } });
      const text = res?.data?.content || res?.data?.text || "";
      const urls = text.split(/\r?\n/).map((l: string) => l.trim()).filter((l: string) => l.length > 0);
      if (urls.length > 0) {
        setEntries((prev) => ({
          ...prev,
          [type]: [...(prev[type] || []), ...urls],
        }));
      }
    } catch (e) {
      console.error("Import txt failed:", e);
    }
  };

  // ── Drag & drop ──
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    // Get dropped file paths (Electron provides absolute paths via f.path)
    const files = e.dataTransfer.files;
    const droppedPaths: string[] = [];
    let missingPaths = false;
    for (let i = 0; i < files.length; i++) {
      const f = files[i];
      // Only use absolute filesystem path from Electron; never fall back to f.name (bare filename)
      const path = (f as any).path;
      if (path) {
        droppedPaths.push(path);
      } else {
        missingPaths = true;
      }
    }

    if (missingPaths) {
      setValidationError("拖拽无法获取文件完整路径，请使用「多选文件」按钮选择文件");
    }

    // Determine which input type this belongs to
    // For simplicity, use the first file-type input type
    const fileType = inputTypes.find((t) => TYPE_CONFIG[t]?.filter.length > 0);
    if (fileType && droppedPaths.length > 0) {
      addEntries(fileType, droppedPaths);
    }
  };

  // ── Validation ──
  const validate = () => {
    const nonEmptyPerType: Record<string, string[]> = {};
    for (const t of inputTypes) {
      nonEmptyPerType[t] = (entries[t] || []).filter((v) => v.trim());
    }

    const emptyTypes = inputTypes.filter((t) => nonEmptyPerType[t].length === 0);
    if (emptyTypes.length > 0) {
      const labels = emptyTypes.map((t) => TYPE_CONFIG[t]?.label || t).join("、");
      setValidationError(`缺少输入：${labels} 至少需要一个条目`);
      setValidationPassed(false);
      return;
    }

    // If multiple types, check count matching
    const counts = inputTypes.map((t) => nonEmptyPerType[t].length);
    const allSame = counts.every((c) => c === counts[0]);
    if (inputTypes.length > 1 && !allSame) {
      setValidationError(
        `输入数量不匹配：${inputTypes.map((t) => `${TYPE_CONFIG[t]?.label}: ${nonEmptyPerType[t].length}个`).join("，")}`
      );
      setValidationPassed(false);
      return;
    }

    setValidationError("");
    setValidationPassed(true);
  };

  // ── Create ──
  const handleCreate = async () => {
    if (!validationPassed) {
      validate();
      if (!validationPassed) return;
    }
    setCreating(true);
    try {
      const nonEmptyPerType: Record<string, string[]> = {};
      for (const t of inputTypes) {
        nonEmptyPerType[t] = (entries[t] || []).filter((v) => v.trim());
      }

      const taskCount = nonEmptyPerType[inputTypes[0]].length;
      const tasks: Record<string, string>[] = [];

      const status = await useSubscriptionStore.getState().fetchStatus();
      if (status && status.daily_limit !== null && (status.remaining_today || 0) < taskCount) {
        setValidationError(`今日剩余额度不足：需要 ${taskCount} 次，当前剩余 ${status.remaining_today || 0} 次。\n${getQuotaExhaustedMessage(status)}`);
        setCreating(false);
        return;
      }

      for (let i = 0; i < taskCount; i++) {
        const task: Record<string, string> = {};
        for (const t of inputTypes) {
          task[TYPE_CONFIG[t]?.key || t] = nonEmptyPerType[t][i] || "";
        }
        tasks.push(task);
      }

      await batchApi.create({
        workflow_id: selectedWfId,
        batch_name: batchName,
        tasks,
        common_config: {
          source_language: sourceLang,
          target_language: targetLang,
        },
      });
      onCreated();
      onClose();
    } catch (e: any) {
      if (isSubscriptionBlocked(e)) {
        const status = useSubscriptionStore.getState().status;
        setValidationError(getQuotaExhaustedMessage(status));
      } else {
        setValidationError(getSubscriptionError(e) || "创建失败");
      }
    } finally {
      setCreating(false);
    }
  };

  const inputCls = "w-full px-3 py-2 text-sm rounded-lg border border-border/60 bg-background focus:border-primary/50 focus:ring-1 focus:ring-primary/20 outline-none transition-all";
  const totalEntries = inputTypes.reduce((sum, t) => sum + (entries[t] || []).filter((v) => v.trim()).length, 0);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-20 bg-black/50 backdrop-blur-sm">
      <div className="bg-card border border-border/50 rounded-2xl shadow-2xl w-[720px] max-h-[80vh] flex flex-col animate-scale-in">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border/40 flex-shrink-0">
          <h3 className="text-lg font-bold">新建批量任务</h3>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-muted transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
          {/* Workflow selector */}
          <div>
            <label className="text-sm font-semibold mb-1.5 block">选择工作流</label>
            <select
              className={cn(inputCls, "cursor-pointer")}
              value={selectedWfId}
              onChange={(e) => {
                setSelectedWfId(e.target.value);
                setValidationPassed(false);
                setValidationError("");
              }}
            >
              <option value="">-- 请选择工作流 --</option>
              {workflows.map((w) => (
                <option key={w.id} value={w.id}>{w.name}</option>
              ))}
            </select>
          </div>

          {loading && <p className="text-sm text-muted-foreground">加载工作流信息...</p>}

          {wfDetail && inputTypes.length > 0 && (
            <>
              {/* Language (from backend) */}
              <div className="flex gap-4">
                <div className="flex-1">
                  <label className="text-sm font-semibold mb-1.5 block">源语言</label>
                  <select
                    className={cn(inputCls, "cursor-pointer")}
                    value={sourceLang}
                    onChange={(e) => setSourceLang(e.target.value)}
                  >
                    {languageOptions.map((opt) => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                </div>
                <div className="flex-1">
                  <label className="text-sm font-semibold mb-1.5 block">目标语言</label>
                  <select
                    className={cn(inputCls, "cursor-pointer")}
                    value={targetLang}
                    onChange={(e) => setTargetLang(e.target.value)}
                  >
                    {languageOptions.filter((o) => o.value !== "auto").map((opt) => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Input entries per type — left/right split layout */}
              {inputTypes.map((type) => {
                const cfg = TYPE_CONFIG[type];
                if (!cfg) return null;
                const items = entries[type] || [];
                const isUrl = type === "url";
                const validCount = items.filter((v) => v.trim()).length;

                return (
                  <div key={type}>
                    <label className="text-sm font-semibold mb-2 block">
                      {cfg.label} {isUrl ? "地址" : "文件"} ({validCount}个)
                    </label>

                    {isUrl ? (
                      /* URL mode */
                      <div className="flex gap-3">
                        {/* Left: url entries */}
                        <div className="flex-1 space-y-1.5 max-h-[140px] overflow-y-auto">
                          {items.length === 0 && (
                            <p className="text-xs text-muted-foreground py-2">暂无URL，请在右侧导入</p>
                          )}
                          {items.map((val, idx) => (
                            <div key={idx} className="flex items-center gap-2">
                              <span className="text-[10px] text-muted-foreground w-5 text-right flex-shrink-0">{idx + 1}</span>
                              <input
                                className={cn(inputCls, "flex-1 text-xs py-1.5")}
                                value={val}
                                onChange={(e) => {
                                  setEntries((prev) => {
                                    const updated = [...(prev[type] || [])];
                                    updated[idx] = e.target.value;
                                    return { ...prev, [type]: updated };
                                  });
                                }}
                                placeholder={`https://...`}
                              />
                              <button
                                onClick={() => removeEntry(type, idx)}
                                className="p-1 rounded hover:bg-red-50 dark:hover:bg-red-950 text-muted-foreground hover:text-red-500 flex-shrink-0"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            </div>
                          ))}
                        </div>
                        {/* Right: import txt */}
                        <div className="flex flex-col gap-2 w-[130px] flex-shrink-0">
                          <button
                            onClick={() => {
                              setEntries((prev) => ({
                                ...prev,
                                [type]: [...(prev[type] || []), ""],
                              }));
                            }}
                            className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg border border-border/60 hover:bg-accent transition-colors"
                          >
                            <Plus className="w-3 h-3" />添加URL
                          </button>
                          <button
                            onClick={() => importUrlsFromTxt(type)}
                            className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg border border-border/60 hover:bg-accent transition-colors"
                          >
                            <FileText className="w-3 h-3" />导入txt
                          </button>
                        </div>
                      </div>
                    ) : (
                      /* File mode: left list + right add/drop zone */
                      <div className="flex gap-3">
                        {/* Left: file list */}
                        <div className="flex-1 space-y-1 max-h-[160px] overflow-y-auto rounded-lg border border-border/40 bg-muted/20 p-2">
                          {items.length === 0 ? (
                            <p className="text-xs text-muted-foreground text-center py-4">
                              暂无文件，请在右侧添加或拖拽文件到此处
                            </p>
                          ) : (
                            items.map((val, idx) => (
                              <div
                                key={idx}
                                className="flex items-center gap-2 px-2 py-1 rounded-md hover:bg-accent/50 transition-colors group"
                              >
                                <span className="text-[10px] text-muted-foreground w-5 text-right flex-shrink-0">{idx + 1}</span>
                                <span className="text-xs truncate flex-1" title={val}>{val || "(空)"}</span>
                                <button
                                  onClick={() => removeEntry(type, idx)}
                                  className="p-0.5 rounded opacity-0 group-hover:opacity-100 hover:bg-red-50 dark:hover:bg-red-950 text-muted-foreground hover:text-red-500 transition-all flex-shrink-0"
                                >
                                  <Trash2 className="w-3 h-3" />
                                </button>
                              </div>
                            ))
                          )}
                        </div>
                        {/* Right: add button + drop zone */}
                        <div className="flex flex-col gap-2 w-[130px] flex-shrink-0">
                          <button
                            onClick={() => pickFiles(type)}
                            className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg border border-border/60 hover:bg-accent transition-colors"
                          >
                            <FolderOpen className="w-3 h-3" />多选文件
                          </button>
                          <div
                            ref={dropRef}
                            onDragOver={handleDragOver}
                            onDragLeave={handleDragLeave}
                            onDrop={handleDrop}
                            className={cn(
                              "flex-1 flex flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed transition-colors cursor-default",
                              isDragging
                                ? "border-primary/60 bg-primary/5 text-primary"
                                : "border-border/40 text-muted-foreground/50"
                            )}
                          >
                            <Upload className="w-5 h-5" />
                            <span className="text-[10px] text-center leading-tight">拖拽文件<br />到此处</span>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}

              {/* Validation + Summary */}
              <div className="flex items-center gap-3">
                <button
                  onClick={validate}
                  className="px-4 py-2 text-sm font-medium rounded-lg border border-border/60 hover:bg-accent transition-colors"
                >
                  校验输入
                </button>
                {validationPassed && (
                  <span className="flex items-center gap-1 text-sm text-emerald-600">
                    <CheckCircle className="w-4 h-4" />校验通过，共 {totalEntries} 个任务
                  </span>
                )}
                {validationError && (
                  <span className="flex items-center gap-1 text-sm text-red-500">
                    <AlertCircle className="w-4 h-4" />{validationError}
                  </span>
                )}
              </div>

              {/* Batch name */}
              <div>
                <label className="text-sm font-semibold mb-1.5 block">批次名称</label>
                <input
                  className={inputCls}
                  value={batchName}
                  onChange={(e) => setBatchName(e.target.value)}
                  placeholder="输入批次名称"
                />
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border/40 flex-shrink-0">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium rounded-lg border border-border/60 hover:bg-accent transition-colors"
          >
            取消
          </button>
          <button
            onClick={handleCreate}
            disabled={!validationPassed || creating || !selectedWfId}
            className="px-5 py-2 text-sm font-semibold rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-all active:scale-95"
          >
            {creating ? "创建中..." : "创建批量任务"}
          </button>
        </div>
      </div>
    </div>
  );
}

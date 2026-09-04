import { useEffect, useMemo, useState } from "react";
import client from "@/api/client";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import {
  Loader2, CheckCircle2, XCircle, Circle, Ban, Film, Image as ImageIcon, Music, FileText,
} from "lucide-react";

/** manifest 中每条迭代记录（结构与 backend/control_plane/loop_runtime.py 保持一致） */
export type LoopItemRecord = {
  index: number;
  item: any;
  status: "succeeded" | "failed" | "cancelled" | "pending" | string;
  outputs: Record<string, Record<string, any>>;
  artifacts: string[];
  error?: string;
  elapsed?: number;
  finished_at?: string;
};

export type LoopManifest = {
  loop_node_id: string;
  total: number;
  concurrency: number;
  onItemError: string;
  itemsSource: string;
  started_at: string;
  updated_at: string;
  succeeded?: number;
  failed?: number;
  items: LoopItemRecord[];
};

const STATUS_STYLE: Record<string, { label: string; icon: any; cls: string }> = {
  succeeded: { label: "成功", icon: CheckCircle2, cls: "text-emerald-600 dark:text-emerald-400" },
  failed: { label: "失败", icon: XCircle, cls: "text-red-600 dark:text-red-400" },
  cancelled: { label: "取消", icon: Ban, cls: "text-amber-600 dark:text-amber-400" },
  pending: { label: "待执行", icon: Circle, cls: "text-muted-foreground" },
};

const VIDEO_EXTS = [".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv"];
const IMAGE_EXTS = [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"];
const AUDIO_EXTS = [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"];

function artifactKind(path: string): "video" | "image" | "audio" | "file" {
  const lower = (path || "").toLowerCase();
  if (VIDEO_EXTS.some((ext) => lower.endsWith(ext))) return "video";
  if (IMAGE_EXTS.some((ext) => lower.endsWith(ext))) return "image";
  if (AUDIO_EXTS.some((ext) => lower.endsWith(ext))) return "audio";
  return "file";
}

function artifactUrl(path: string, taskId?: string) {
  const params = new URLSearchParams({ path });
  if (taskId) params.set("task_id", taskId);
  params.set("t", String(Date.now()));
  return `/api/files/stream?${params.toString()}`;
}

function summarizeItem(item: any): string {
  if (item === null || item === undefined) return "";
  if (typeof item === "string") return item;
  if (typeof item === "number" || typeof item === "boolean") return String(item);
  if (Array.isArray(item)) return `[${item.length} 项]`;
  if (typeof item === "object") {
    for (const key of ["path", "file", "filepath", "value", "url", "text", "name"]) {
      const value = (item as any)[key];
      if (typeof value === "string" && value) return value;
    }
    return JSON.stringify(item).slice(0, 120);
  }
  return String(item);
}

function ArtifactPreview({ path, taskId }: { path: string; taskId?: string }) {
  const kind = artifactKind(path);
  const url = artifactUrl(path, taskId);
  if (kind === "video") {
    return <video src={url} controls className="w-full max-h-56 rounded-md bg-black" />;
  }
  if (kind === "image") {
    return <img src={url} alt={path} className="w-full max-h-56 object-contain rounded-md bg-muted" />;
  }
  if (kind === "audio") {
    return <audio src={url} controls className="w-full" />;
  }
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1.5 text-xs text-primary hover:underline break-all"
    >
      <FileText className="w-3.5 h-3.5 shrink-0" />
      {path}
    </a>
  );
}

export default function LoopResultDialog({
  open,
  onOpenChange,
  taskId,
  manifestPath,
  loopLabel,
}: {
  open: boolean;
  onOpenChange: (value: boolean) => void;
  taskId?: string;
  manifestPath?: string;
  loopLabel?: string;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [manifest, setManifest] = useState<LoopManifest | null>(null);
  const [activeIndex, setActiveIndex] = useState<number | null>(null);

  useEffect(() => {
    if (!open) return;
    setManifest(null);
    setError("");
    setActiveIndex(null);
    if (!manifestPath) {
      setError("循环尚未产出产物清单，请先执行该循环节点");
      return;
    }
    let cancelled = false;
    setLoading(true);
    const params = new URLSearchParams({ path: manifestPath });
    if (taskId) params.set("task_id", taskId);
    client
      .get(`/api/files/stream?${params.toString()}`, { responseType: "text" })
      .then((res) => {
        if (cancelled) return;
        const text = typeof res.data === "string" ? res.data : JSON.stringify(res.data);
        const parsed = JSON.parse(text) as LoopManifest;
        setManifest(parsed);
        const first = (parsed.items || []).find((item) => item && item.status === "succeeded");
        setActiveIndex(first ? first.index : (parsed.items?.[0]?.index ?? null));
      })
      .catch((exc: any) => {
        if (!cancelled) setError(`读取产物清单失败：${exc?.message || exc}`);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, taskId, manifestPath]);

  const items = useMemo(() => (manifest?.items || []).filter(Boolean), [manifest]);
  const active = items.find((item) => item.index === activeIndex) || null;
  const activeArtifacts = useMemo(() => {
    if (!active) return [] as string[];
    if (active.artifacts?.length) return active.artifacts;
    // 回退：从 outputs 里兜底提取看起来像路径的值
    const found: string[] = [];
    for (const ports of Object.values(active.outputs || {})) {
      for (const value of Object.values(ports || {})) {
        if (typeof value === "string" && value && artifactKind(value) !== "file") found.push(value);
      }
    }
    return found;
  }, [active]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl w-[92vw] max-h-[84vh] flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            循环产物清单
            <span className="text-xs font-normal text-muted-foreground">{loopLabel || manifest?.loop_node_id || ""}</span>
          </DialogTitle>
        </DialogHeader>

        {loading && (
          <div className="flex items-center gap-2 py-10 justify-center text-sm text-muted-foreground">
            <Loader2 className="w-4 h-4 animate-spin" /> 正在读取产物清单…
          </div>
        )}

        {!loading && error && (
          <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </div>
        )}

        {!loading && manifest && (
          <>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <span>总条目：<b className="text-foreground">{manifest.total}</b></span>
              <span>成功：<b className="text-emerald-600">{manifest.succeeded ?? 0}</b></span>
              <span>失败：<b className="text-red-600">{manifest.failed ?? 0}</b></span>
              <span>并发：{manifest.concurrency}</span>
              <span>失败策略：{manifest.onItemError}</span>
              <span>更新于：{manifest.updated_at}</span>
            </div>

            <div className="flex-1 min-h-0 grid grid-cols-1 md:grid-cols-[300px_1fr] gap-3">
              <div className="border rounded-md overflow-auto max-h-[52vh]">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-muted/80 backdrop-blur">
                    <tr className="text-left text-muted-foreground">
                      <th className="px-2 py-1.5 font-medium">#</th>
                      <th className="px-2 py-1.5 font-medium">条目</th>
                      <th className="px-2 py-1.5 font-medium">状态</th>
                      <th className="px-2 py-1.5 font-medium">产物</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item) => {
                      const style = STATUS_STYLE[item.status] || STATUS_STYLE.pending;
                      const Icon = style.icon;
                      return (
                        <tr
                          key={item.index}
                          onClick={() => setActiveIndex(item.index)}
                          className={cn(
                            "border-t cursor-pointer transition-colors",
                            item.index === activeIndex ? "bg-primary/10" : "hover:bg-muted/60"
                          )}
                        >
                          <td className="px-2 py-1.5 tabular-nums text-muted-foreground">{item.index}</td>
                          <td className="px-2 py-1.5 max-w-[150px] truncate" title={summarizeItem(item.item)}>
                            {summarizeItem(item.item) || "—"}
                          </td>
                          <td className="px-2 py-1.5">
                            <span className={cn("inline-flex items-center gap-1", style.cls)}>
                              <Icon className="w-3.5 h-3.5" />
                              {style.label}
                            </span>
                          </td>
                          <td className="px-2 py-1.5 tabular-nums text-muted-foreground">
                            {item.artifacts?.length ?? 0}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className="border rounded-md p-3 overflow-auto max-h-[52vh] space-y-3">
                {!active && <div className="text-xs text-muted-foreground">请从左侧选择一条迭代记录</div>}
                {active && (
                  <>
                    <div className="space-y-1 text-xs">
                      <div className="font-medium">第 {active.index} 项</div>
                      <div className="text-muted-foreground break-all">{summarizeItem(active.item) || "—"}</div>
                      <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-muted-foreground">
                        <span>耗时：{active.elapsed ?? "—"}s</span>
                        <span>结束：{active.finished_at || "—"}</span>
                      </div>
                    </div>
                    {active.error && (
                      <div className="rounded-md border border-destructive/40 bg-destructive/10 px-2 py-1.5 text-xs text-destructive break-all">
                        {active.error}
                      </div>
                    )}
                    {activeArtifacts.length === 0 ? (
                      <div className="text-xs text-muted-foreground">该迭代没有可预览的产物</div>
                    ) : (
                      <div className="space-y-2">
                        {activeArtifacts.map((path) => (
                          <div key={path} className="space-y-1">
                            <ArtifactPreview path={path} taskId={taskId} />
                            <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
                              {artifactKind(path) === "video" && <Film className="w-3 h-3" />}
                              {artifactKind(path) === "image" && <ImageIcon className="w-3 h-3" />}
                              {artifactKind(path) === "audio" && <Music className="w-3 h-3" />}
                              {artifactKind(path) === "file" && <FileText className="w-3 h-3" />}
                              <span className="break-all">{path}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

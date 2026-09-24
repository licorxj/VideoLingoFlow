import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { Archive, Loader2, RefreshCw, Search, Trash2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { FILE_TRANSIT_TYPES, fileTransitApi, type FileTransitItem } from "@/api/fileTransit";

/** 阻止弹窗内交互冒泡到 React Flow 画布（缩放/平移/拖动节点）。 */
const STOP = {
  onPointerDown: (e: React.SyntheticEvent) => e.stopPropagation(),
  onMouseDown: (e: React.SyntheticEvent) => e.stopPropagation(),
  onWheel: (e: React.SyntheticEvent) => e.stopPropagation(),
};

function fmtTime(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function FileTransitPickerDialog({
  open,
  onClose,
  onSelect,
}: {
  open: boolean;
  onClose: () => void;
  onSelect: (item: FileTransitItem) => void;
}) {
  const [items, setItems] = useState<FileTransitItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [fileType, setFileType] = useState("all");
  const [activeId, setActiveId] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fileTransitApi.items({ file_type: fileType, keyword, order: "latest", limit: 200 });
      setItems(res.data?.items || []);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [fileType, keyword]);

  useEffect(() => {
    if (!open) return;
    void load();
  }, [open, load]);

  const filtered = useMemo(() => items, [items]);

  const remove = async (item: FileTransitItem) => {
    try {
      await fileTransitApi.remove(item.id);
      setItems((prev) => prev.filter((it) => it.id !== item.id));
      if (activeId === item.id) setActiveId("");
    } catch {
      /* 删除失败时保持列表不变 */
    }
  };

  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[12000] flex items-center justify-center bg-black/40 backdrop-blur-sm"
      onPointerDown={onClose}
      onMouseDown={onClose}
    >
      <div
        {...STOP}
        className="flex max-h-[min(600px,84vh)] w-[min(820px,94vw)] flex-col overflow-hidden rounded-2xl border border-white/70 bg-background/95 shadow-[0_28px_80px_hsl(215_35%_15%_/_0.35)] backdrop-blur-2xl"
      >
        <div className="flex items-center justify-between border-b border-black/[0.08] px-5 py-3">
          <div className="flex items-center gap-2">
            <span className="grid h-7 w-7 place-items-center rounded-lg bg-primary/10 text-primary">
              <Archive className="h-4 w-4" />
            </span>
            <div>
              <div className="text-sm font-semibold">从文件中转站选择</div>
              <div className="text-[10px] text-muted-foreground">只读取登记，不会移动或复制原文件</div>
            </div>
          </div>
          <button type="button" onClick={onClose} title="关闭" className="rounded-md p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex items-center gap-2 border-b border-black/[0.06] px-4 py-2.5">
          <div className="relative min-w-0 flex-1">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              placeholder="搜索文件名称或所属任务…"
              className="w-full rounded-lg border border-border/50 bg-background py-1.5 pl-8 pr-3 text-xs outline-none transition-all focus:border-primary/50 focus:ring-1 focus:ring-primary/20"
            />
          </div>
          <select
            value={fileType}
            onChange={(e) => setFileType(e.target.value)}
            className="shrink-0 rounded-lg border border-border/50 bg-background px-2 py-1.5 text-xs outline-none focus:border-primary/50"
          >
            {FILE_TRANSIT_TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            title="刷新列表"
            className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-border/50 bg-background px-2.5 py-1.5 text-[11px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary disabled:opacity-60"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
            刷新
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2 py-2">
          {loading && (
            <div className="flex items-center justify-center gap-2 py-8 text-xs text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />正在加载中转站…
            </div>
          )}
          {!loading && filtered.length === 0 && (
            <div className="py-8 text-center text-xs text-muted-foreground">
              {keyword || fileType !== "all" ? "没有匹配的素材" : "中转站还没有素材，先用「文件中转站入库」节点登记"}
            </div>
          )}
          {!loading && filtered.map((item) => (
            <div
              key={item.id}
              {...STOP}
              onClick={() => setActiveId(item.id)}
              className={cn(
                "flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left transition-colors",
                activeId === item.id ? "bg-primary/10 ring-1 ring-primary/20" : "hover:bg-muted",
              )}
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="truncate text-xs font-medium">{item.name}</span>
                  <span className="shrink-0 rounded-full bg-muted px-1.5 py-px text-[9px] text-muted-foreground">
                    {item.file_type_label || item.file_type}
                  </span>
                </div>
                <div className="mt-0.5 truncate text-[10px] text-muted-foreground">
                  任务：{item.task_name || "—"} · 入库 {fmtTime(item.created_at)}
                </div>
                <div className="truncate font-mono text-[10px] text-muted-foreground/70">{item.path}</div>
              </div>
              <button
                type="button"
                title="从登记中移除（不删除磁盘文件）"
                onClick={(e) => { e.stopPropagation(); void remove(item); }}
                className="shrink-0 rounded-md p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-black/[0.08] px-4 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-border/60 px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent"
          >
            取消
          </button>
          <button
            type="button"
            disabled={!activeId}
            onClick={() => {
              const item = filtered.find((it) => it.id === activeId);
              if (item) onSelect(item);
            }}
            className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-50"
          >
            使用选中文件
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

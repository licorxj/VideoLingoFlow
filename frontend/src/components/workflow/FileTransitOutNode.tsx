import { useEffect, useState } from "react";
import { FolderOpen, Loader2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  FILE_TRANSIT_ORDERS,
  FILE_TRANSIT_TYPES,
  fileTransitApi,
  type FileTransitItem,
} from "@/api/fileTransit";
import { FileTransitPickerDialog } from "./FileTransitPickerDialog";

/**
 * 「文件中转站取自」节点卡片。
 *
 * 两种取件方式：
 * - 自动：按 文件类型 + 排序规则（最新入库 / 最旧入库 / 排序序号 / 文件名称）取；
 * - 手动：点「选择文件」在弹窗里指定一条登记记录。
 *
 * 卡片下方实时显示「将取到」的预览结果，便于连线前确认。
 */
export function FileTransitOutNode({
  config,
  onChange,
}: {
  config: Record<string, any>;
  onChange: (key: string, value: any) => void;
}) {
  const pickMode = String(config?.pick_mode || "auto");
  const fileType = String(config?.file_type || "all");
  const order = String(config?.order || "latest");
  const index = Math.max(1, Number(config?.index || 1));
  const keyword = String(config?.keyword || "");
  const selectedPath = String(config?.selected_path || "");
  const selectedName = String(config?.selected_name || "");

  const [pickerOpen, setPickerOpen] = useState(false);
  const [preview, setPreview] = useState<FileTransitItem | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fileTransitApi
      .pick({
        file_type: fileType,
        keyword,
        order,
        index,
        path: pickMode === "manual" ? selectedPath : "",
      })
      .then((res) => {
        if (!cancelled) setPreview(res.data?.item || null);
      })
      .catch(() => {
        if (!cancelled) setPreview(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [pickMode, fileType, order, index, keyword, selectedPath]);

  return (
    <div className="min-w-0 space-y-2 border-t border-border/50 px-3 pb-3 pt-2">
      {/* 取件方式 */}
      <div className="flex items-center gap-1.5">
        <span className="shrink-0 text-[11px] text-muted-foreground">取件方式</span>
        <div className="grid grid-cols-2 gap-1 rounded-lg bg-muted/60 p-0.5">
          {(["auto", "manual"] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => {
                e.stopPropagation();
                onChange("pick_mode", mode);
              }}
              className={cn(
                "rounded-md py-1 text-[11px] font-medium transition-colors",
                pickMode === mode
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground/80",
              )}
            >
              {mode === "auto" ? "按规则自动取" : "手动指定"}
            </button>
          ))}
        </div>
      </div>

      {/* 文件类型 + 排序规则 */}
      <div className="grid grid-cols-2 gap-2">
        <label className="min-w-0 space-y-1">
          <span className="text-[10px] text-muted-foreground">文件类型</span>
          <select
            value={fileType}
            onChange={(e) => onChange("file_type", e.target.value)}
            onPointerDown={(e) => e.stopPropagation()}
            onWheel={(e) => e.stopPropagation()}
            className="w-full rounded-md border border-border/50 bg-background px-2 py-1.5 text-[11px] outline-none focus:border-primary/50"
          >
            {FILE_TRANSIT_TYPES.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        </label>
        <label className="min-w-0 space-y-1">
          <span className="text-[10px] text-muted-foreground">排序规则</span>
          <select
            value={order}
            onChange={(e) => onChange("order", e.target.value)}
            onPointerDown={(e) => e.stopPropagation()}
            onWheel={(e) => e.stopPropagation()}
            className="w-full rounded-md border border-border/50 bg-background px-2 py-1.5 text-[11px] outline-none focus:border-primary/50"
          >
            {FILE_TRANSIT_ORDERS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>
      </div>

      {/* 排序序号 / 手动指定 */}
      {order === "index" && pickMode === "auto" && (
        <div className="flex items-center gap-2">
          <span className="shrink-0 text-[10px] text-muted-foreground">第</span>
          <input
            type="number"
            min={1}
            value={index}
            onChange={(e) => onChange("index", Math.max(1, Number(e.target.value) || 1))}
            onPointerDown={(e) => e.stopPropagation()}
            onWheel={(e) => e.stopPropagation()}
            className="w-16 rounded-md border border-border/50 bg-background px-2 py-1 text-[11px] outline-none focus:border-primary/50"
          />
          <span className="text-[10px] text-muted-foreground">个入库的素材（按入库先后）</span>
        </div>
      )}

      {pickMode === "manual" && (
        <>
          <button
            type="button"
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation();
              setPickerOpen(true);
            }}
            className="inline-flex w-full items-center justify-center gap-1.5 rounded-md border border-primary/40 bg-primary/5 px-2 py-1.5 text-[11px] font-medium text-primary transition-colors hover:bg-primary/10"
          >
            <FolderOpen className="h-3.5 w-3.5" />
            选择文件
          </button>
          {selectedPath && (
            <div className="flex items-center gap-1.5 rounded-md border border-border/50 bg-background/60 px-2 py-1 text-[10px]">
              <span className="min-w-0 flex-1 truncate text-foreground/80">
                已选：<span className="font-medium">{selectedName || selectedPath}</span>
              </span>
              <button
                type="button"
                title="清除已选"
                onPointerDown={(e) => e.stopPropagation()}
                onClick={(e) => {
                  e.stopPropagation();
                  onChange("selected_path", "");
                  onChange("selected_name", "");
                }}
                className="shrink-0 rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          )}
        </>
      )}

      {/* 将取到 */}
      <div className="rounded-md border border-border/50 bg-background/60 px-2 py-1.5 text-[10px]">
        <div className="flex items-center gap-1.5">
          <span className="shrink-0 text-muted-foreground">将取到</span>
          {loading && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />}
          {!loading && (
            <span className="min-w-0 flex-1 truncate">
              {preview ? (
                <>
                  <span className="font-medium text-foreground">{preview.name}</span>
                  <span className="ml-1 text-muted-foreground">
                    （{preview.file_type_label || preview.file_type} · {preview.task_name || "—"} · {preview.created_at?.slice(0, 16).replace("T", " ")}）
                  </span>
                </>
              ) : (
                <span className="text-muted-foreground">中转站内没有匹配的素材</span>
              )}
            </span>
          )}
        </div>
        {preview && <div className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground/70">{preview.path}</div>}
      </div>

      <p className="text-[10px] leading-snug text-muted-foreground/80">
        执行时输出该素材的<b>文件路径</b>给下游（不复制文件）；入库请用「文件中转站入库」节点。
      </p>

      <FileTransitPickerDialog
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onSelect={(item) => {
          onChange("selected_path", item.path);
          onChange("selected_name", item.name);
          setPickerOpen(false);
        }}
      />
    </div>
  );
}

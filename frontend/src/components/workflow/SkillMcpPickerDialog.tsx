import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { createPortal } from "react-dom";
import { Cable, Check, FolderOpen, Loader2, RefreshCw, Search, Sparkles, X } from "lucide-react";
import client from "@/api/client";
import { cn } from "@/lib/utils";

export type PickerKind = "skills" | "mcps";

type ScanItem = {
  item_id: string;
  name: string;
  path: string;
  description?: string;
  enabled: boolean;
};

const STOP: React.DOMAttributes<Element> = { onPointerDown: (e) => e.stopPropagation(), onMouseDown: (e) => e.stopPropagation(), onWheel: (e) => e.stopPropagation() };

export default function SkillMcpPickerDialog({
  kind, open, selected, label, onConfirm, onClose,
}: {
  kind: PickerKind;
  open: boolean;
  selected: string[];
  label: string;
  onConfirm: (selected: string[]) => void;
  onClose: () => void;
}) {
  const [items, setItems] = useState<ScanItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [preview, setPreview] = useState<ScanItem | null>(null);
  const keywordRef = useRef<HTMLInputElement>(null);
  // 仅在弹窗打开时捕获一次初始选中；渲染期间同步引用，避免父组件重渲染导致勾选被重置
  const initialSelectedRef = useRef<string[]>(selected);
  if (open) initialSelectedRef.current = selected;

  // 拉取扫描结果；打开时清空关键词与预览并重置勾选，手动扫描时保留当前勾选与关键词
  const loadItems = useCallback((reset: boolean) => {
    setLoading(true);
    // 后端 scan 接口按单数 kind（skill / mcp）路由，弹窗内部用复数表示语义
    const apiKind = kind === "skills" ? "skill" : "mcp";
    client.post(`/api/pi/settings/scan/${apiKind}`)
      .then((res) => {
        const list: ScanItem[] = Array.isArray(res.data) ? res.data : [];
        setItems(list);
        if (reset) {
          setChecked(new Set(initialSelectedRef.current));
          setKeyword("");
          setPreview(null);
        }
      })
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, [kind]);

  useEffect(() => {
    if (!open) return;
    loadItems(true);
    requestAnimationFrame(() => keywordRef.current?.focus());
  }, [open, kind, loadItems]);

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    if (!kw) return items;
    return items.filter((item) =>
      item.name.toLowerCase().includes(kw) ||
      (item.description || "").toLowerCase().includes(kw) ||
      item.path.toLowerCase().includes(kw),
    );
  }, [items, keyword]);

  const toggle = (name: string) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-[12000] flex items-center justify-center bg-black/40 backdrop-blur-sm" onPointerDown={onClose} onMouseDown={onClose}>
      <div {...STOP} className="flex max-h-[min(560px,82vh)] w-[min(760px,92vw)] flex-col overflow-hidden rounded-2xl border border-white/70 bg-background/95 shadow-[0_28px_80px_hsl(215_35%_15%_/_0.35)] backdrop-blur-2xl">
        {/* 头部 */}
        <div className="flex items-center justify-between border-b border-black/[0.08] px-5 py-3">
          <div className="flex items-center gap-2">
            <span className="grid h-7 w-7 place-items-center rounded-lg bg-primary/10 text-primary">{kind === "skills" ? <Sparkles className="h-4 w-4" /> : <Cable className="h-4 w-4" />}</span>
            <span className="text-sm font-semibold">选择{label}</span>
          </div>
          <button type="button" onClick={onClose} className="rounded-md p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive" title="关闭"><X className="h-4 w-4" /></button>
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-[1.1fr_0.9fr]">
          {/* 左列：搜索 + 列表 */}
          <div className="flex min-h-0 flex-col border-r border-black/[0.06]">
            <div className="flex items-center gap-2 p-3 pb-2">
              <div className="relative min-w-0 flex-1">
                <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                <input
                  ref={keywordRef}
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  placeholder={`搜索${label}名称或介绍…`}
                  className="w-full rounded-lg border border-border/50 bg-background py-1.5 pl-8 pr-3 text-xs outline-none transition-all focus:border-primary/50 focus:ring-1 focus:ring-primary/20"
                />
              </div>
              <button
                type="button"
                onClick={() => loadItems(false)}
                disabled={loading}
                title="重新扫描常见 Skill / MCP 存放目录（项目、~/.trae、~/.agents、~/.agent、~/.claude 等）"
                className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-border/50 bg-background px-2.5 py-1.5 text-[11px] font-medium text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary disabled:opacity-60"
              >
                <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
                扫描
              </button>
            </div>
            <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2 pb-2">
              {loading && (
                <div className="flex items-center justify-center gap-2 py-8 text-xs text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />正在扫描{label}…
                </div>
              )}
              {!loading && filtered.length === 0 && (
                <div className="py-8 text-center text-xs text-muted-foreground">{keyword ? "未找到匹配项" : "暂无可用的" + label}</div>
              )}
              {!loading && filtered.map((item) => {
                const isChecked = checked.has(item.name);
                const isPreview = preview?.item_id === item.item_id;
                return (
                  <button
                    key={item.item_id}
                    type="button"
                    onClick={() => setPreview(item)}
                    className={cn("flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors", isPreview ? "bg-primary/10 ring-1 ring-primary/20" : "hover:bg-muted")}
                  >
                    <span
                      role="checkbox"
                      aria-checked={isChecked}
                      onClick={(e) => { e.stopPropagation(); toggle(item.name); }}
                      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); toggle(item.name); } }}
                      tabIndex={0}
                      className={cn("grid h-4 w-4 shrink-0 place-items-center rounded border transition-colors", isChecked ? "border-primary bg-primary text-primary-foreground" : "border-border bg-background")}
                    >
                      {isChecked && <Check className="h-3 w-3" />}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-1.5">
                        <span className="truncate text-xs font-medium">{item.name}</span>
                        {item.enabled && <span className="shrink-0 rounded-full bg-emerald-500/10 px-1.5 py-px text-[9px] font-semibold text-emerald-600">已授权</span>}
                      </span>
                      <span className="block truncate text-[10px] text-muted-foreground">{item.path}</span>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* 右列：介绍 */}
          <div className="flex min-h-0 flex-col">
            <div className="flex items-center gap-2 border-b border-black/[0.06] px-4 py-2.5">
              <FolderOpen className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-[11px] font-semibold text-muted-foreground">{label}介绍</span>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
              {!preview ? (
                <div className="py-10 text-center text-xs text-muted-foreground">点击左侧{label}查看介绍</div>
              ) : (
                <div className="space-y-2.5">
                  <div>
                    <div className="text-sm font-semibold">{preview.name}</div>
                    <div className="mt-0.5 break-all text-[10px] text-muted-foreground">{preview.path}</div>
                  </div>
                  <p className="whitespace-pre-wrap break-words text-xs leading-5 text-muted-foreground">
                    {preview.description?.trim() || "该" + label + "暂无介绍说明。"}
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* 底部操作 */}
        <div className="flex items-center justify-between border-t border-black/[0.08] px-5 py-3">
          <span className="text-[11px] text-muted-foreground">已选择 {checked.size} 项</span>
          <div className="flex items-center gap-2">
            <button type="button" onClick={onClose} className="rounded-lg border border-border/60 px-4 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted">取消</button>
            <button type="button" onClick={() => onConfirm(Array.from(checked))} className="rounded-lg bg-primary px-4 py-1.5 text-xs font-semibold text-primary-foreground shadow-sm transition-colors hover:bg-primary/90">确认</button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}

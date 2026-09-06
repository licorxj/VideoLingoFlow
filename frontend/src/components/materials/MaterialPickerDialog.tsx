import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Check, Film, Search, UserRound } from "lucide-react";
import { MaterialCharacter, MaterialImage, MaterialVideo, materialPreviewUrl, materialsApi } from "@/api/materials";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EmptyState } from "@/components/shared/EmptyState";
import { LoadingState } from "@/components/shared/LoadingState";
import { useInView } from "./useInView";

const PAGE_SIZE = 12;

export type PickerKind = "image" | "video" | "character";

const KIND_TITLE: Record<PickerKind, string> = {
  image: "选择图片素材",
  video: "选择视频素材",
  character: "选择角色",
};

const KIND_DESC: Record<PickerKind, string> = {
  image: "来自公共图片素材库,选中后把素材ID写入节点卡片,执行时回查详情。",
  video: "来自公共视频素材库,选中后把素材ID写入节点卡片,执行时回查详情。",
  character: "来自公共角色库,选中后把角色ID写入节点卡片,执行时回查角色详情与多视角图。",
};

/** 图片/视频/角色素材选择弹窗:筛选 + 分页 + 卡片懒加载预览 + 选择回传。 */
export function MaterialPickerDialog({
  kind,
  open,
  onClose,
  onPicked,
}: {
  kind: PickerKind;
  open: boolean;
  onClose: () => void;
  onPicked: (record: MaterialImage | MaterialVideo | MaterialCharacter) => void;
}) {
  const [items, setItems] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [groups, setGroups] = useState<string[]>([]);
  const [tags, setTags] = useState<string[]>([]);
  const [filters, setFilters] = useState<{ search: string; group: string; tag: string }>({ search: "", group: "", tag: "" });
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const debounceRef = useRef<number | null>(null);

  const load = useCallback(
    (nextPage = page, nextFilters = filters) => {
      setLoading(true);
      setError("");
      const params = { page: nextPage, page_size: PAGE_SIZE, search: nextFilters.search || undefined, group: nextFilters.group || undefined, tag: nextFilters.tag || undefined };
      const request = kind === "image" ? materialsApi.images(params) : kind === "video" ? materialsApi.videos(params) : materialsApi.characters(params);
      request
        .then(({ data }) => {
          setItems(data.items as any[]);
          setTotal(data.total);
          setGroups((data as any).groups || []);
          setTags((data as any).tags || []);
        })
        .catch((err) => setError(err?.message || "素材加载失败"))
        .finally(() => setLoading(false));
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [kind, page, filters],
  );

  useEffect(() => {
    if (!open) return;
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      setPage(1);
      void load(1, filters);
    }, 250);
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters, kind, open]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const showGroup = kind !== "character";

  return (
    <Dialog open={open} onOpenChange={(value) => !value && onClose()}>
      <DialogContent className="flex max-h-[85vh] w-[95vw] max-w-4xl flex-col gap-3 overflow-hidden">
        <DialogHeader>
          <DialogTitle>{KIND_TITLE[kind]}</DialogTitle>
          <DialogDescription>{KIND_DESC[kind]}</DialogDescription>
        </DialogHeader>

        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-48 flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <input
              value={filters.search}
              onChange={(event) => setFilters({ ...filters, search: event.target.value })}
              placeholder={kind === "character" ? "搜索姓名、性格或职业" : "搜索路径或描述"}
              className="voice-input pl-8"
              autoFocus
            />
          </div>
          {showGroup && (
            <select value={filters.group} onChange={(event) => setFilters({ ...filters, group: event.target.value })} className="voice-input h-10 w-32" title="分组">
              <option value="">全部分组</option>
              {groups.map((group) => <option key={group} value={group}>{group}</option>)}
            </select>
          )}
          <select value={filters.tag} onChange={(event) => setFilters({ ...filters, tag: event.target.value })} className="voice-input h-10 w-32" title="标签">
            <option value="">全部标签</option>
            {tags.map((tag) => <option key={tag} value={tag}>{tag}</option>)}
          </select>
        </div>

        {error && <p className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}

        <div className="min-h-0 flex-1 overflow-y-auto pr-1">
          {loading && !items.length ? (
            <LoadingState label="正在加载素材…" />
          ) : items.length ? (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {items.map((item) => (
                <PickerCard key={item.id} kind={kind} item={item} onPick={() => onPicked(item)} />
              ))}
            </div>
          ) : (
            <EmptyState icon={kind === "character" ? UserRound : kind === "video" ? Film : Search} title="没有匹配的素材" detail="换个关键词或标签,或先到「素材库」页面添加素材。" />
          )}
        </div>

        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">共 {total} 个素材</span>
          {totalPages > 1 && (
            <div className="flex items-center gap-2">
              <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => { const next = page - 1; setPage(next); void load(next); }}>
                <ChevronLeft className="h-4 w-4" />上一页
              </Button>
              <span className="text-sm text-muted-foreground">{page} / {totalPages}</span>
              <Button size="sm" variant="outline" disabled={page >= totalPages} onClick={() => { const next = page + 1; setPage(next); void load(next); }}>
                下一页<ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function PickerCard({ kind, item, onPick }: { kind: PickerKind; item: any; onPick: () => void }) {
  const { ref, inView } = useInView<HTMLDivElement>();
  return (
    <article className="flex flex-col overflow-hidden rounded-xl border border-border/60 bg-card transition-shadow hover:shadow-md">
      <div ref={ref} className="flex h-32 items-center justify-center overflow-hidden bg-muted/40">
        {kind === "image" ? (
          <img src={materialPreviewUrl(item.path, item.abs_path)} alt={item.description || item.path} loading="lazy" className="h-full w-full object-contain" />
        ) : kind === "video" ? (
          inView ? (
            <video src={materialPreviewUrl(item.path, item.abs_path)} preload="metadata" controls className="h-full w-full bg-black/80" />
          ) : (
            <Film className="h-8 w-8 text-muted-foreground/50" />
          )
        ) : (
          <div className="flex w-full flex-col items-start gap-1 p-3 text-left">
            <div className="flex items-center gap-2">
              <span className="grid h-8 w-8 place-items-center rounded-lg bg-amber-400/20 text-amber-500"><UserRound className="h-4 w-4" /></span>
              <span className="truncate text-sm font-semibold">{item.name}</span>
            </div>
            <p className="truncate text-[11px] text-muted-foreground">{[item.gender, item.age, item.occupation].filter(Boolean).join(" · ") || "未补充基础信息"}</p>
            {item.personality && <p className="line-clamp-2 text-[11px] text-muted-foreground">{item.personality}</p>}
          </div>
        )}
      </div>
      <div className="flex flex-1 flex-col p-2.5">
        {kind !== "character" && (
          <>
            <h4 className="truncate text-xs font-semibold" title={item.description || item.path}>{(item.path || "").split("/").pop()}</h4>
            <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
              {kind === "video"
                ? [item.duration_seconds ? `${item.duration_seconds.toFixed(1)} 秒` : "时长未识别", item.width ? `${item.width}×${item.height}` : ""].filter(Boolean).join(" · ")
                : [item.width ? `${item.width}×${item.height}` : "", item.aspect_ratio].filter(Boolean).join(" · ") || "尺寸未识别"}
            </p>
          </>
        )}
        <div className="mt-2 flex items-center justify-between gap-1">
          <div className="flex min-w-0 flex-1 flex-wrap gap-1">
            {(kind === "character" ? item.tags : [...(item.group_tags || []), ...(item.custom_tags || [])]).slice(0, 2).map((tag: string) => (
              <span key={tag} className="rounded border border-border/60 px-1 py-0.5 text-[10px] text-muted-foreground">{tag}</span>
            ))}
          </div>
          <Button size="sm" onClick={onPick}>
            <Check className="mr-1 h-3 w-3" />选择
          </Button>
        </div>
      </div>
    </article>
  );
}

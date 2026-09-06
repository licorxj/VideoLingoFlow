import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, FolderOpen, Images, Music2, Plus, RefreshCw, UserRound, Video } from "lucide-react";
import { MaterialCharacter, MaterialImage, MaterialKind, MaterialListResult, MaterialQuery, MaterialSummary, MaterialVideo, materialsApi } from "@/api/materials";
import { Button } from "@/components/ui/button";
import { PageBackground } from "@/components/shared/PageBackground";
import { PageHeader } from "@/components/shared/PageHeader";
import { EmptyState } from "@/components/shared/EmptyState";
import { LoadingState } from "@/components/shared/LoadingState";
import { AssetLibrary } from "@/components/voiceforge/assets/AssetLibrary";
import { CharacterMaterialCard, ImageMaterialCard, VideoMaterialCard } from "@/components/materials/MaterialCards";
import { UploadMaterialDialog } from "@/components/materials/UploadMaterialDialog";
import { CharacterAddDialog } from "@/components/materials/CharacterAddDialog";
import { MaterialEditDialog, EditTarget } from "@/components/materials/MaterialEditDialog";

const PAGE_SIZE = 12;

type PanelResult = MaterialListResult<MaterialImage & MaterialVideo & MaterialCharacter>;

const KIND_META: Record<MaterialKind, { label: string; icon: typeof Images; summaryKey: keyof MaterialSummary }> = {
  image: { label: "图片", icon: Images, summaryKey: "images" },
  video: { label: "视频", icon: Video, summaryKey: "videos" },
  character: { label: "角色", icon: UserRound, summaryKey: "characters" },
  audio: { label: "音频", icon: Music2, summaryKey: "audio" },
};

function errorText(error: any, fallback: string) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;
  return error?.message || fallback;
}

/** 图片/视频/角色共用面板:筛选 + 卡片网格 + 分页 + 添加/编辑/删除。音频面板直接内嵌配音谷素材库。 */
function MaterialPanel({ kind, onChanged }: { kind: Exclude<MaterialKind, "audio">; onChanged: () => void }) {
  const [result, setResult] = useState<PanelResult>({ items: [], total: 0, page: 1, page_size: PAGE_SIZE, groups: [], tags: [] });
  const [filters, setFilters] = useState<{ search: string; group: string; tag: string }>({ search: "", group: "", tag: "" });
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<EditTarget | null>(null);
  const debounceRef = useRef<number | null>(null);

  const load = useCallback(
    async (nextPage = page, nextFilters = filters) => {
      setLoading(true);
      setError("");
      try {
        const params: MaterialQuery = { page: nextPage, page_size: PAGE_SIZE, search: nextFilters.search || undefined, group: nextFilters.group || undefined, tag: nextFilters.tag || undefined };
        const request = kind === "image" ? materialsApi.images(params) : kind === "video" ? materialsApi.videos(params) : materialsApi.characters(params);
        const { data } = await request;
        setResult(data as PanelResult);
      } catch (err) {
        setError(errorText(err, "素材加载失败"));
      } finally {
        setLoading(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [kind, page, filters],
  );

  useEffect(() => {
    // 筛选条件变化时防抖 300ms 刷新
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => void load(1, filters), 300);
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters, kind]);

  const refresh = () => {
    void load(page, filters);
    onChanged();
  };

  const remove = async (id: string, name: string) => {
    if (!confirm(`删除素材“${name}”?` + (kind === "character" ? "" : "本系统上传的源文件会一并删除。"))) return;
    const request = kind === "image" ? materialsApi.deleteImage(id) : kind === "video" ? materialsApi.deleteVideo(id) : materialsApi.deleteCharacter(id);
    try {
      await request;
    } catch (err) {
      setError(errorText(err, "删除失败"));
      return;
    }
    refresh();
  };

  const totalPages = useMemo(() => Math.max(1, Math.ceil(result.total / PAGE_SIZE)), [result.total]);
  const showGroupFilter = kind !== "character";
  const addLabel = kind === "image" ? "添加图片" : kind === "video" ? "添加视频" : "添加角色";

  const cards = result.items.map((item: any) => {
    if (kind === "image") {
      return <ImageMaterialCard key={item.id} item={item} onEdit={() => setEditTarget({ kind: "image", data: item })} onDelete={() => void remove(item.id, item.path.split("/").pop() || item.id)} />;
    }
    if (kind === "video") {
      return <VideoMaterialCard key={item.id} item={item} onEdit={() => setEditTarget({ kind: "video", data: item })} onDelete={() => void remove(item.id, item.path.split("/").pop() || item.id)} />;
    }
    return <CharacterMaterialCard key={item.id} item={item} onEdit={() => setEditTarget({ kind: "character", data: item })} onDelete={() => void remove(item.id, item.name)} />;
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={() => setAddOpen(true)}>
          <Plus className="mr-1.5 h-4 w-4" />
          {addLabel}
        </Button>
        <div className="relative min-w-56 flex-1">
          <input
            value={filters.search}
            onChange={(event) => setFilters({ ...filters, search: event.target.value })}
            placeholder={kind === "character" ? "搜索角色姓名、性格或职业" : "搜索路径或描述"}
            className="voice-input"
          />
        </div>
        {showGroupFilter && (
          <select value={filters.group} onChange={(event) => setFilters({ ...filters, group: event.target.value })} className="voice-input h-10 w-36" title="分组">
            <option value="">全部分组</option>
            {(result.groups || []).map((group) => (
              <option key={group} value={group}>{group}</option>
            ))}
          </select>
        )}
        <select value={filters.tag} onChange={(event) => setFilters({ ...filters, tag: event.target.value })} className="voice-input h-10 w-36" title="标签">
          <option value="">全部标签</option>
          {(result.tags || []).map((tag) => (
            <option key={tag} value={tag}>{tag}</option>
          ))}
        </select>
        {(filters.search || filters.group || filters.tag) && (
          <Button size="sm" variant="outline" onClick={() => setFilters({ search: "", group: "", tag: "" })}>重置筛选</Button>
        )}
      </div>

      {error && <p className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}

      <div className="text-sm text-muted-foreground">共 {result.total} 个素材</div>

      <div className={loading ? "opacity-60 transition-opacity" : ""}>
        {result.items.length ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">{cards}</div>
        ) : loading ? (
          <LoadingState label="正在加载素材…" />
        ) : (
          <EmptyState
            icon={FolderOpen}
            title="暂无素材"
            detail={kind === "character" ? "点击“添加角色”建立公共角色库,供创作项目引用。" : "点击左上角按钮上传素材,文件会统一复制到 data/materials/ 目录。"}
            action={
              <Button onClick={() => setAddOpen(true)}>
                <Plus className="mr-1.5 h-4 w-4" />{addLabel}
              </Button>
            }
          />
        )}
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => { const next = page - 1; setPage(next); void load(next); }}>
            <ChevronLeft className="h-4 w-4" />上一页
          </Button>
          <span className="text-sm text-muted-foreground">{page} / {totalPages}</span>
          <Button size="sm" variant="outline" disabled={page >= totalPages} onClick={() => { const next = page + 1; setPage(next); void load(next); }}>
            下一页<ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      )}

      {kind !== "character" ? (
        <UploadMaterialDialog kind={kind} open={addOpen} onClose={() => setAddOpen(false)} onAdded={refresh} />
      ) : (
        <CharacterAddDialog open={addOpen} onClose={() => setAddOpen(false)} onAdded={refresh} />
      )}
      {editTarget && <MaterialEditDialog key={editTarget.data.id} target={editTarget} onClose={() => setEditTarget(null)} onSaved={refresh} />}
    </div>
  );
}

export default function MaterialLibrary() {
  const [kind, setKind] = useState<MaterialKind>("image");
  const [summary, setSummary] = useState({ images: 0, videos: 0, characters: 0, audio: 0 });

  const refreshSummary = useCallback(() => {
    materialsApi.summary().then(({ data }) => setSummary(data)).catch(() => undefined);
  }, []);

  useEffect(() => {
    refreshSummary();
  }, [refreshSummary, kind]);

  return (
    <PageBackground tone="voiceforge" className="mx-auto max-w-7xl space-y-5 p-1">
      <PageHeader
        icon={Images}
        title="素材库"
        detail="分类浏览与添加本地素材 · 视频与音频按需加载"
        breadcrumbs={[{ label: "素材库" }]}
        actions={
          <Button variant="outline" onClick={refreshSummary}>
            <RefreshCw className="mr-1.5 h-4 w-4" />
            刷新
          </Button>
        }
      />

      <div className="flex gap-1 border-b border-border/60">
        {(Object.keys(KIND_META) as MaterialKind[]).map((item) => {
          const { label, icon: Icon, summaryKey } = KIND_META[item];
          const isActive = item === kind;
          return (
            <button
              key={item}
              type="button"
              onClick={() => setKind(item)}
              className={`flex items-center gap-1.5 rounded-t-lg border-b-2 px-4 py-2.5 text-sm ${
                isActive ? "border-primary font-semibold text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              <Icon className="h-4 w-4" />
              <span>{label}</span>
              <span className="rounded-full bg-current/10 px-1.5 text-[11px]">{summary[summaryKey]}</span>
            </button>
          );
        })}
      </div>

      {kind === "audio" ? (
        <div className="rounded-xl border border-border/60 bg-card/40 p-3">
          <p className="mb-2 text-xs text-muted-foreground">音频素材(音效/背景音乐/环境音)由配音谷统一管理,支持在线抓取与收藏;列表按需加载,不会整页拉流。</p>
          <AssetLibrary embedded />
        </div>
      ) : (
        <MaterialPanel key={kind} kind={kind} onChanged={refreshSummary} />
      )}
    </PageBackground>
  );
}

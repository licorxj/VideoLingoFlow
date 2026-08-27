import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, FolderOpen, FolderPlus, Globe, Music2, Plus, RefreshCw, Trash2 } from "lucide-react";
import { AssetListResult, VoiceForgeAsset, VoiceForgeAssetTag, voiceForgeApi } from "@/api/voiceforge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { PageHeader } from "@/components/shared/PageHeader";
import { PageBackground } from "@/components/shared/PageBackground";
import { EmptyState } from "@/components/shared/EmptyState";
import { LoadingState } from "@/components/shared/LoadingState";
import { AssetCard } from "./AssetCard";
import { AssetFilter, AssetFilters } from "./AssetFilter";
import { AssetAddDialog } from "./AssetAddDialog";
import { AssetCategoryManager } from "./AssetCategoryManager";
import { ASSET_TYPE_LABELS, ASSET_TYPE_ORDER } from "./meta";
import OnlineAssetsModal from "./OnlineAssetsModal";

const PAGE_SIZE = 12;

function errorText(error: any, fallback: string) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;
  return error?.message || fallback;
}

export function AssetLibrary() {
  const [activeType, setActiveType] = useState("bgm");
  const [result, setResult] = useState<AssetListResult>({ assets: [], total: 0, page: 1, page_size: PAGE_SIZE, type_counts: {} });
  const [categories, setCategories] = useState<any[]>([]);
  const [tags, setTags] = useState<VoiceForgeAssetTag[]>([]);
  const [filters, setFilters] = useState<AssetFilters>({ search: "", is_favorite: false });
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [onlineOpen, setOnlineOpen] = useState(false);
  const [catOpen, setCatOpen] = useState(false);
  const [editing, setEditing] = useState<VoiceForgeAsset | null>(null);
  const debounceRef = useRef<number | null>(null);
  const [editName, setEditName] = useState("");
  const [editType, setEditType] = useState("bgm");
  const [editCategory, setEditCategory] = useState("");
  const [editTags, setEditTags] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editFavorite, setEditFavorite] = useState(false);

  const load = async (nextPage = page, nextFilters = filters, nextType = activeType) => {
    setLoading(true);
    setError("");
    try {
      const [assetsResult, categoryResult, tagsResult] = await Promise.all([
        voiceForgeApi.assets({
          asset_type: nextType,
          category: nextFilters.category,
          tag: nextFilters.tag,
          is_favorite: nextFilters.is_favorite || undefined,
          min_duration: nextFilters.min_duration,
          max_duration: nextFilters.max_duration,
          search: nextFilters.search || undefined,
          page: nextPage,
          page_size: PAGE_SIZE,
        }),
        voiceForgeApi.assetCategories(),
        voiceForgeApi.assetTags("", nextType),
      ]);
      setResult(assetsResult.data);
      setCategories(categoryResult.data.categories);
      setTags(tagsResult.data.tags);
      setSelected([]);
    } catch (err) {
      setError(errorText(err, "素材加载失败"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // 筛选条件（关键词、分类、标签、收藏、时长）或类型变化时，防抖 300ms 实时刷新
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      void load(1, filters, activeType);
    }, 300);
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters, activeType]);

  const refreshNow = () => {
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    void load(1, filters, activeType);
  };

  const totalPages = useMemo(() => Math.max(1, Math.ceil(result.total / PAGE_SIZE)), [result.total]);
  const allSelected = result.assets.length > 0 && result.assets.every((asset) => selected.includes(asset.id));

  const toggleSelect = (id: string) => {
    setSelected((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  };

  const toggleAll = () => {
    setSelected(allSelected ? [] : result.assets.map((asset) => asset.id));
  };

  const toggleFavorite = async (asset: VoiceForgeAsset) => {
    await voiceForgeApi.updateAsset(asset.id, { is_favorite: !asset.is_favorite });
    await load(page, filters, activeType);
  };

  const beginEdit = (asset: VoiceForgeAsset) => {
    setEditing(asset);
    setEditName(asset.name);
    setEditType(asset.asset_type);
    setEditCategory(asset.category || "");
    setEditTags(asset.tags.join(", "));
    setEditDescription(asset.description || "");
    setEditFavorite(Boolean(asset.is_favorite));
  };

  const saveEdit = async () => {
    if (!editing || !editName.trim()) return;
    await voiceForgeApi.updateAsset(editing.id, {
      name: editName.trim(),
      asset_type: editType,
      category: editCategory || null,
      tags: editTags.split(",").map((tag) => tag.trim()).filter(Boolean),
      description: editDescription,
      is_favorite: editFavorite,
    });
    setEditing(null);
    await load(page, filters, activeType);
  };

  const changeEditType = (value: string) => {
    setEditType(value);
    if (editCategory && !categories.some((item) => item.asset_type === value && item.name === editCategory)) {
      setEditCategory("");
    }
  };

  const remove = async (asset: VoiceForgeAsset) => {
    if (!confirm(`删除素材“${asset.name}”？仅移除记录，不会删除源文件。`)) return;
    await voiceForgeApi.deleteAsset(asset.id);
    await load(page, filters, activeType);
  };

  const removeSelected = async () => {
    if (!selected.length || !confirm(`删除选中的 ${selected.length} 个素材记录？不会删除源文件。`)) return;
    await voiceForgeApi.deleteAssets(selected);
    await load(page, filters, activeType);
  };

  return (
    <PageBackground tone="voiceforge" className="mx-auto max-w-7xl space-y-5 p-1">
      <PageHeader
        icon={Music2}
        title="素材库"
        detail="仅记录本地路径，不复制文件 · 不含视频时间线"
        hideTitle
        back={{ to: "/voiceforge", label: "配音谷" }}
        breadcrumbs={[
          { label: "晴沐配音谷", to: "/voiceforge" },
          { label: "素材库" },
        ]}
        actions={
          <>
            <Button variant="outline" onClick={() => setCatOpen(true)}>
              <FolderPlus className="mr-1.5 h-4 w-4" />
              分类管理
            </Button>
            <Button variant="outline" onClick={() => void load(page, filters, activeType)}>
              <RefreshCw className="mr-1.5 h-4 w-4" />
              刷新
            </Button>
            <Button onClick={() => setAddOpen(true)}>
              <Plus className="mr-1.5 h-4 w-4" />
              添加素材
            </Button>
            <Button variant="secondary" onClick={() => setOnlineOpen(true)}>
              <Globe className="mr-1.5 h-4 w-4" />
              在线素材
            </Button>
          </>
        }
      />

      <OnlineAssetsModal open={onlineOpen} onOpenChange={setOnlineOpen} onImported={() => void load(page, filters, activeType)} />

      <div className="flex gap-1 border-b border-border/60">
        {ASSET_TYPE_ORDER.map((type) => {
          const isActive = type === activeType;
          const toneClass = isActive ? `asset-tone-${type} asset-bg-${type}` : "text-muted-foreground hover:text-foreground";
          return (
            <button
              key={type}
              type="button"
              onClick={() => setActiveType(type)}
              className={`flex items-center gap-1.5 rounded-t-lg border-b-2 px-4 py-2.5 text-sm ${toneClass} ${
                isActive ? "border-current font-semibold" : "border-transparent"
              }`}
            >
              <span>{ASSET_TYPE_LABELS[type]}</span>
              <span className="rounded-full bg-current/10 px-1.5 text-[11px]">
                {result.type_counts[type] || 0}
              </span>
            </button>
          );
        })}
      </div>

      <AssetFilter
        filters={filters}
        categories={categories.filter((item) => item.asset_type === activeType)}
        tags={tags}
        onChange={(next) => setFilters(next)}
        onSearch={refreshNow}
      />

      {error && <p className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}

      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span>共 {result.total} 个素材{selected.length ? ` · 已选 ${selected.length} 个` : ""}</span>
        <div className="flex gap-2">
          {selected.length ? (
            <>
              <Button size="sm" variant="outline" onClick={toggleAll}>取消选择</Button>
              <Button size="sm" variant="destructive" onClick={() => void removeSelected()}>
                <Trash2 className="mr-1 h-3.5 w-3.5" />批量删除
              </Button>
            </>
          ) : (
            <Button size="sm" variant="outline" onClick={toggleAll} disabled={!result.assets.length}>全选</Button>
          )}
        </div>
      </div>

      <div className={loading ? "opacity-60 transition-opacity" : ""}>
        {result.assets.length ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {result.assets.map((asset) => (
              <AssetCard
                key={asset.id}
                asset={asset}
                selected={selected.includes(asset.id)}
                onSelect={() => toggleSelect(asset.id)}
                onToggleFavorite={() => void toggleFavorite(asset)}
                onEdit={() => beginEdit(asset)}
                onDelete={() => void remove(asset)}
              />
            ))}
          </div>
        ) : loading ? (
          <LoadingState label="正在加载素材…" />
        ) : (
          <EmptyState
            icon={FolderOpen}
            title="素材库为空"
            detail='点击右上角"添加素材"选择本地音频文件，仅记录路径、不复制文件。'
            action={
              <Button onClick={() => setAddOpen(true)}>
                <Plus className="mr-1.5 h-4 w-4" />添加第一个素材
              </Button>
            }
          />
        )}
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => { const next = page - 1; setPage(next); void load(next, filters, activeType); }}>
            <ChevronLeft className="h-4 w-4" />上一页
          </Button>
          <span className="text-sm text-muted-foreground">{page} / {totalPages}</span>
          <Button size="sm" variant="outline" disabled={page >= totalPages} onClick={() => { const next = page + 1; setPage(next); void load(next, filters, activeType); }}>
            下一页<ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      )}

      <AssetAddDialog open={addOpen} defaultType={activeType} onClose={() => setAddOpen(false)} onAdded={() => void load(page, filters, activeType)} />
      <AssetCategoryManager open={catOpen} activeType={activeType} onClose={() => setCatOpen(false)} onChanged={() => void load(page, filters, activeType)} />

      <Dialog open={editing !== null} onOpenChange={(value) => !value && setEditing(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>编辑素材</DialogTitle>
            <DialogDescription>修改元数据不会影响源文件。</DialogDescription>
          </DialogHeader>
          <div className="grid gap-3">
            <label className="text-xs font-medium text-muted-foreground">名称</label>
            <input value={editName} onChange={(event) => setEditName(event.target.value)} className="voice-input" />
            <label className="text-xs font-medium text-muted-foreground">类型</label>
            <select value={editType} onChange={(event) => changeEditType(event.target.value)} className="voice-input">
              {Object.entries(ASSET_TYPE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            <label className="text-xs font-medium text-muted-foreground">分类</label>
            <select value={editCategory} onChange={(event) => setEditCategory(event.target.value)} className="voice-input">
              <option value="">未分类</option>
              {ASSET_TYPE_ORDER.map((type) => (
                <optgroup key={type} label={ASSET_TYPE_LABELS[type]}>
                  {categories.filter((item) => item.asset_type === type).map((item) => (
                    <option key={item.id} value={item.name}>{item.label}</option>
                  ))}
                </optgroup>
              ))}
            </select>
            <label className="text-xs font-medium text-muted-foreground">标签（逗号分隔）</label>
            <input value={editTags} onChange={(event) => setEditTags(event.target.value)} className="voice-input" placeholder="如 激昂, 悬疑" />
            <label className="text-xs font-medium text-muted-foreground">说明</label>
            <textarea value={editDescription} onChange={(event) => setEditDescription(event.target.value)} className="voice-input min-h-16 resize-none" />
            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <input type="checkbox" checked={editFavorite} onChange={(event) => setEditFavorite(event.target.checked)} className="h-4 w-4" />
              标记为收藏
            </label>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditing(null)}>取消</Button>
            <Button onClick={() => void saveEdit()} disabled={!editName.trim()}>保存</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageBackground>
  );
}

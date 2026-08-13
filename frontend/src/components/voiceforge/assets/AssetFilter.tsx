import { FolderOpen, Search, Tag } from "lucide-react";
import { VoiceForgeAssetCategory, VoiceForgeAssetTag } from "@/api/voiceforge";

export type AssetFilters = {
  search: string;
  category?: string;
  tag?: string;
  is_favorite: boolean;
  min_duration?: number;
  max_duration?: number;
};

export function AssetFilter({
  filters,
  categories,
  tags,
  onChange,
  onSearch,
}: {
  filters: AssetFilters;
  categories: VoiceForgeAssetCategory[];
  tags: VoiceForgeAssetTag[];
  onChange: (filters: AssetFilters) => void;
  onSearch: () => void;
}) {
  const set = (patch: Partial<AssetFilters>) => onChange({ ...filters, ...patch });
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border/60 bg-card p-3">
      <div className="relative min-w-48 flex-1">
        <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
        <input
          value={filters.search}
          onChange={(event) => set({ search: event.target.value })}
          onKeyDown={(event) => event.key === "Enter" && onSearch()}
          placeholder="搜索素材名称、文件名或说明"
          className="voice-input pl-8"
        />
      </div>
      <select value={filters.category || ""} onChange={(event) => set({ category: event.target.value || undefined })} className="voice-input h-9 w-40" title="分类">
        <option value="">全部分类</option>
        {categories.map((item) => (
          <option key={item.id} value={item.name}>{item.label}</option>
        ))}
      </select>
      <select value={filters.tag || ""} onChange={(event) => set({ tag: event.target.value || undefined })} className="voice-input h-9 w-36" title="标签">
        <option value="">全部标签</option>
        {tags.map((item) => (
          <option key={item.id} value={item.name}>{item.name}</option>
        ))}
      </select>
      <input
        type="number" min={0} step={0.5} value={filters.min_duration ?? ""}
        onChange={(event) => set({ min_duration: event.target.value ? Number(event.target.value) : undefined })}
        placeholder="最短秒" className="voice-input h-9 w-24"
      />
      <input
        type="number" min={0} step={0.5} value={filters.max_duration ?? ""}
        onChange={(event) => set({ max_duration: event.target.value ? Number(event.target.value) : undefined })}
        placeholder="最长秒" className="voice-input h-9 w-24"
      />
      <label className="flex h-9 cursor-pointer items-center gap-1.5 rounded-md border border-border/60 px-2.5 text-sm text-muted-foreground">
        <input type="checkbox" checked={filters.is_favorite} onChange={(event) => set({ is_favorite: event.target.checked })} className="h-3.5 w-3.5" />
        仅收藏
      </label>
      <button type="button" onClick={onSearch} className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary/90">
        <Search className="h-4 w-4" />筛选
      </button>
      {(filters.category || filters.tag || filters.min_duration || filters.max_duration || filters.is_favorite) && (
        <button
          type="button"
          onClick={() => onChange({ ...filters, category: undefined, tag: undefined, min_duration: undefined, max_duration: undefined, is_favorite: false })}
          className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-border/60 px-3 text-sm text-muted-foreground hover:bg-accent"
        >
          <FolderOpen className="h-4 w-4" />重置筛选
        </button>
      )}
      <span className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
        <Tag className="h-3.5 w-3.5" />{tags.length} 个标签
      </span>
    </div>
  );
}

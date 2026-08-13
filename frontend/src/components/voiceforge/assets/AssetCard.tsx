import { useState } from "react";
import { Check, Copy, Star, StarOff, Trash2, Pencil, Music2 } from "lucide-react";
import { VoiceForgeAsset, voiceForgeApi } from "@/api/voiceforge";
import { ASSET_TYPE_COLORS } from "./meta";

function formatBytes(value?: number) {
  if (!value) return "-";
  return value >= 1024 * 1024 ? `${(value / 1024 / 1024).toFixed(1)} MB` : `${Math.round(value / 1024)} KB`;
}

export function AssetCard({
  asset,
  selected,
  onSelect,
  onToggleFavorite,
  onEdit,
  onDelete,
}: {
  asset: VoiceForgeAsset;
  selected: boolean;
  onSelect: () => void;
  onToggleFavorite: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const color = ASSET_TYPE_COLORS[asset.asset_type] || "#a29bfe";
  const [copied, setCopied] = useState(false);

  const copyPath = async () => {
    const value = asset.external_path || asset.file_name || "";
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      const textarea = document.createElement("textarea");
      textarea.value = value;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <article className="group relative flex flex-col overflow-hidden rounded-xl border border-border/60 bg-card transition-shadow hover:shadow-md" style={{ boxShadow: selected ? `0 0 0 2px ${color}66` : undefined }}>
      <div className="h-1 w-full" style={{ background: color }} />
      <div className="flex flex-1 flex-col p-4">
        <div className="flex items-start gap-2">
          <input type="checkbox" checked={selected} onChange={onSelect} className="mt-1 h-4 w-4 accent-[var(--primary)]" />
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-sm font-semibold">{asset.name}</h3>
            <p className="mt-0.5 truncate text-xs text-muted-foreground">
              <Music2 className="mr-1 inline h-3 w-3" style={{ color }} />
              {asset.file_name}
            </p>
          </div>
          <button type="button" onClick={onToggleFavorite} title={asset.is_favorite ? "取消收藏" : "收藏"} className="shrink-0 p-1 text-muted-foreground hover:text-foreground">
            {asset.is_favorite ? <Star className="h-4 w-4 fill-amber-400 text-amber-400" /> : <StarOff className="h-4 w-4" />}
          </button>
        </div>
        {asset.tags.length ? (
          <div className="mt-2 flex flex-wrap gap-1">
            {asset.tags.slice(0, 4).map((tag) => (
              <span key={tag} className="rounded border border-border/60 px-1.5 py-0.5 text-[11px] text-muted-foreground">{tag}</span>
            ))}
            {asset.tags.length > 4 && <span className="rounded border border-border/60 px-1.5 py-0.5 text-[11px] text-muted-foreground">+{asset.tags.length - 4}</span>}
          </div>
        ) : null}
        <div className="mt-2 flex items-center gap-2 text-[11px] text-muted-foreground">
          <span>{asset.duration ? `${asset.duration.toFixed(1)} 秒` : "时长未识别"}</span>
          <span>·</span>
          <span>{formatBytes(asset.file_size)}</span>
          {asset.category && <span className="ml-auto rounded bg-muted px-1.5 py-0.5">{asset.category}</span>}
        </div>
        <audio controls preload="none" src={voiceForgeApi.assetStreamUrl(asset.id)} className="mt-3 h-8 w-full" />
        <div className="mt-3 flex items-center justify-end gap-1 border-t border-border/50 pt-2">
          <button
            type="button"
            onClick={() => void copyPath()}
            title={asset.external_path || "无外部路径"}
            className="flex items-center gap-1 rounded px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            {copied ? <Check className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3" />}
            {copied ? "已复制" : "复制路径"}
          </button>
          <button type="button" onClick={onEdit} className="flex items-center gap-1 rounded px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground">
            <Pencil className="h-3 w-3" />编辑
          </button>
          <button type="button" onClick={onDelete} className="flex items-center gap-1 rounded px-2 py-1 text-xs text-destructive/80 hover:bg-destructive/10 hover:text-destructive">
            <Trash2 className="h-3 w-3" />删除
          </button>
        </div>
      </div>
    </article>
  );
}

import { useState } from "react";
import { Check, Copy, Film, Image as ImageIcon, Pencil, Trash2, UserRound } from "lucide-react";
import { MaterialCharacter, MaterialImage, MaterialVideo, materialPreviewUrl } from "@/api/materials";
import { useInView } from "./useInView";

const KIND_COLORS: Record<string, string> = {
  image: "#74b9ff",
  video: "#55efc4",
  character: "#fdcb6e",
};

function formatDuration(value?: number | null) {
  if (!value) return "时长未识别";
  return value >= 60 ? `${Math.floor(value / 60)} 分 ${Math.round(value % 60)} 秒` : `${value.toFixed(1)} 秒`;
}

function formatDims(width?: number | null, height?: number | null) {
  if (!width || !height) return "尺寸未识别";
  return `${width}×${height}`;
}

async function copyText(value: string) {
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
}

function useCopy() {
  const [copied, setCopied] = useState(false);
  const copy = (value: string) => {
    if (!value) return;
    void copyText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };
  return { copied, copy };
}

function CardShell({ color, children }: { color: string; children: React.ReactNode }) {
  return (
    <article className="group relative flex flex-col overflow-hidden rounded-xl border border-border/60 bg-card transition-shadow hover:shadow-md">
      <div className="h-1 w-full" style={{ background: color }} />
      {children}
    </article>
  );
}

function TagRow({ tags }: { tags: string[] }) {
  if (!tags.length) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1">
      {tags.slice(0, 4).map((tag) => (
        <span key={tag} className="rounded border border-border/60 px-1.5 py-0.5 text-[11px] text-muted-foreground">{tag}</span>
      ))}
      {tags.length > 4 && <span className="rounded border border-border/60 px-1.5 py-0.5 text-[11px] text-muted-foreground">+{tags.length - 4}</span>}
    </div>
  );
}

function CardActions({ path, onEdit, onDelete }: { path: string; onEdit: () => void; onDelete: () => void }) {
  const { copied, copy } = useCopy();
  return (
    <div className="mt-3 flex items-center justify-end gap-1 border-t border-border/50 pt-2">
      <button
        type="button"
        onClick={() => copy(path)}
        title={path}
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
  );
}

export function ImageMaterialCard({ item, onEdit, onDelete }: { item: MaterialImage; onEdit: () => void; onDelete: () => void }) {
  const [broken, setBroken] = useState(false);
  const color = KIND_COLORS.image;
  return (
    <CardShell color={color}>
      <div className="flex h-40 items-center justify-center overflow-hidden bg-muted/40">
        {broken ? (
          <ImageIcon className="h-10 w-10 text-muted-foreground/50" />
        ) : (
          <img
            src={materialPreviewUrl(item.path, item.abs_path)}
            alt={item.description || item.path}
            loading="lazy"
            onError={() => setBroken(true)}
            className="h-full w-full object-contain"
          />
        )}
      </div>
      <div className="flex flex-1 flex-col p-4">
        <h3 className="truncate text-sm font-semibold">{item.path.split("/").pop()}</h3>
        {item.description && <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{item.description}</p>}
        <TagRow tags={[...item.group_tags, ...item.custom_tags]} />
        <div className="mt-2 flex items-center gap-2 text-[11px] text-muted-foreground">
          <span>{formatDims(item.width, item.height)}</span>
          <span>·</span>
          <span>{item.aspect_ratio || "比例未知"}</span>
          {item.group_tags.length > 0 && <span className="ml-auto rounded bg-muted px-1.5 py-0.5">{item.group_tags[0]}</span>}
        </div>
        <CardActions path={item.abs_path || item.path} onEdit={onEdit} onDelete={onDelete} />
      </div>
    </CardShell>
  );
}

export function VideoMaterialCard({ item, onEdit, onDelete }: { item: MaterialVideo; onEdit: () => void; onDelete: () => void }) {
  const { ref, inView } = useInView<HTMLDivElement>();
  const color = KIND_COLORS.video;
  return (
    <CardShell color={color}>
      <div ref={ref} className="flex h-40 items-center justify-center overflow-hidden bg-muted/40">
        {/* 懒加载:卡片进入视口后才挂载 <video>,且只预载元数据,避免整页视频同时加载 */}
        {inView ? (
          <video src={materialPreviewUrl(item.path, item.abs_path)} preload="metadata" controls className="h-full w-full bg-black/80" />
        ) : (
          <Film className="h-10 w-10 text-muted-foreground/50" />
        )}
      </div>
      <div className="flex flex-1 flex-col p-4">
        <h3 className="truncate text-sm font-semibold">{item.path.split("/").pop()}</h3>
        {item.description && <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{item.description}</p>}
        <TagRow tags={[...item.group_tags, ...item.custom_tags]} />
        <div className="mt-2 flex items-center gap-2 text-[11px] text-muted-foreground">
          <span>{formatDuration(item.duration_seconds)}</span>
          <span>·</span>
          <span>{formatDims(item.width, item.height)}</span>
          {item.group_tags.length > 0 && <span className="ml-auto rounded bg-muted px-1.5 py-0.5">{item.group_tags[0]}</span>}
        </div>
        <CardActions path={item.abs_path || item.path} onEdit={onEdit} onDelete={onDelete} />
      </div>
    </CardShell>
  );
}

export function CharacterMaterialCard({ item, onEdit, onDelete }: { item: MaterialCharacter; onEdit: () => void; onDelete: () => void }) {
  const color = KIND_COLORS.character;
  const tags = [...item.tags, ...item.aliases];
  return (
    <CardShell color={color}>
      <div className="flex flex-1 flex-col p-4">
        <div className="flex items-start gap-2">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg" style={{ background: `${color}33` }}>
            <UserRound className="h-5 w-5" style={{ color }} />
          </span>
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-sm font-semibold">{item.name}</h3>
            <p className="mt-0.5 truncate text-xs text-muted-foreground">
              {[item.gender, item.age, item.occupation].filter(Boolean).join(" · ") || "未补充基础信息"}
            </p>
          </div>
        </div>
        {item.personality && <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">{item.personality}</p>}
        {item.voice_design && <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">音色:{item.voice_design}</p>}
        {item.voice_ref && (
          <span className="mt-2 w-fit rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground" title="音色素材引用(vf: 格式)">{item.voice_ref}</span>
        )}
        <TagRow tags={tags} />
        {/* 角色的"路径"是多视角图文件夹;无文件夹时回退音色引用 */}
        <CardActions path={item.images_dir_abs || item.images_dir || item.voice_ref || item.name} onEdit={onEdit} onDelete={onDelete} />
      </div>
    </CardShell>
  );
}

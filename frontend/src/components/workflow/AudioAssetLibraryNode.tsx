import { useEffect, useState } from "react";
import { FolderOpen, Library, Music2, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { voiceForgeApi } from "@/api/voiceforge";
import OnlineAssetsModal from "@/components/voiceforge/assets/OnlineAssetsModal";
import LocalAssetsModal from "@/components/voiceforge/assets/LocalAssetsModal";

/** 按来源类型解析试听地址:配音谷素材ID → 素材流接口;URL → 直连;本地路径 → 文件流。 */
function resolveAudioSrc(source: string): string {
  const value = source.trim();
  if (!value) return "";
  if (/^[0-9a-f]{32}$/i.test(value)) return voiceForgeApi.assetStreamUrl(value);
  if (/^https?:\/\//i.test(value)) return value;
  return voiceForgeApi.fileStreamUrl(value);
}

export function AudioAssetLibraryNode({
  config,
  onChange,
}: {
  config: Record<string, any>;
  onChange: (key: string, value: any) => void;
}) {
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [localOpen, setLocalOpen] = useState(false);
  const [streamError, setStreamError] = useState(false);
  const source = config?.source ?? "";
  const assetName = config?.asset_name ?? "";
  const looksLikeAssetId = /^[0-9a-f]{32}$/i.test(source.trim());
  const audioSrc = resolveAudioSrc(source);

  useEffect(() => {
    setStreamError(false);
  }, [audioSrc]);

  return (
    <div className="px-3 pb-3 pt-1 space-y-2">
      <div className="space-y-1">
        <label className="text-[11px] leading-tight text-muted-foreground">
          素材来源（URL / 本地路径 / 素材库素材ID）
        </label>
        <Input
          value={source}
          placeholder="粘贴素材链接、本地路径，或从本地素材库选择"
          onChange={(e) => onChange("source", e.target.value)}
          onPointerDown={(e) => e.stopPropagation()}
          className="text-xs"
        />
        {assetName && looksLikeAssetId && (
          <div className="flex items-center gap-1.5 rounded-md border border-primary/30 bg-primary/5 px-2 py-1 text-[11px]">
            <span className="truncate text-muted-foreground">
              已选素材：<span className="font-semibold text-foreground">{assetName}</span>
              <span className="ml-1 font-mono">ID {source}</span>
            </span>
            <button
              type="button"
              title="清除已选素材"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => {
                e.stopPropagation();
                onChange("source", "");
                onChange("asset_name", "");
              }}
              className="ml-auto shrink-0 rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        )}
        <p className="text-[10px] leading-snug text-muted-foreground/80">
          支持：1) 素材链接(http/https)；2) 本地文件或文件夹绝对路径；3) 从本地素材库选择素材（记录素材ID，执行时回查详情）。
        </p>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Button
          variant="outline"
          onClick={(e) => {
            e.stopPropagation();
            setLocalOpen(true);
          }}
        >
          <FolderOpen className="mr-1 size-3.5" />
          本地素材库
        </Button>
        <Button
          variant="outline"
          onClick={(e) => {
            e.stopPropagation();
            setLibraryOpen(true);
          }}
        >
          <Library className="mr-1 size-3.5" />
          在线素材库
        </Button>
      </div>

      {audioSrc ? (
        <div className="space-y-1">
          {streamError && (
            <p className="text-[10px] leading-snug text-destructive">素材无法播放，请检查来源是否有效（文件是否存在 / 链接是否可访问）。</p>
          )}
          <audio
            key={audioSrc}
            controls
            preload="none"
            src={audioSrc}
            onError={() => setStreamError(true)}
            onPointerDown={(e) => e.stopPropagation()}
            className="h-8 w-full"
          />
        </div>
      ) : (
        <div className="flex h-8 items-center gap-1.5 rounded-md border border-dashed border-border/60 px-2 text-[10px] text-muted-foreground/70">
          <Music2 className="h-3 w-3" />
          填入素材来源后可直接试听
        </div>
      )}

      <LocalAssetsModal
        open={localOpen}
        onOpenChange={setLocalOpen}
        onPick={(asset) => {
          onChange("source", asset.id);
          onChange("asset_name", asset.name);
          setLocalOpen(false);
        }}
      />

      <OnlineAssetsModal
        open={libraryOpen}
        onOpenChange={setLibraryOpen}
        onPick={(v) => {
          onChange("source", v.url);
          onChange("asset_name", "");
          setLibraryOpen(false);
        }}
      />
    </div>
  );
}

import { useState } from "react";
import { FolderOpen, Library } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import OnlineAssetsModal from "@/components/voiceforge/assets/OnlineAssetsModal";
import LocalAssetsModal from "@/components/voiceforge/assets/LocalAssetsModal";

export function AudioAssetLibraryNode({
  config,
  onChange,
}: {
  config: Record<string, any>;
  onChange: (key: string, value: any) => void;
}) {
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [localOpen, setLocalOpen] = useState(false);
  const source = config?.source ?? "";

  return (
    <div className="px-3 pb-3 pt-1 space-y-2">
      <div className="space-y-1">
        <label className="text-[11px] leading-tight text-muted-foreground">
          素材来源（URL / 本地路径 / 配音谷素材库ID）
        </label>
        <Input
          value={source}
          placeholder="粘贴素材链接、本地路径或配音谷素材库ID"
          onChange={(e) => onChange("source", e.target.value)}
          onPointerDown={(e) => e.stopPropagation()}
          className="text-xs"
        />
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

      <LocalAssetsModal open={localOpen} onOpenChange={setLocalOpen} />

      <OnlineAssetsModal
        open={libraryOpen}
        onOpenChange={setLibraryOpen}
        onPick={(v) => {
          onChange("source", v.url);
          setLibraryOpen(false);
        }}
      />
    </div>
  );
}

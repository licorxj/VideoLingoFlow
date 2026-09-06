import { useEffect, useState } from "react";
import { AudioLines, Film, FolderOpen, Image as ImageIcon, UserRound, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { voiceForgeApi } from "@/api/voiceforge";
import {
  MaterialCharacter,
  MaterialImage,
  MaterialVideo,
  MaterialVoiceRecord,
  materialPreviewUrl,
  materialsApi,
} from "@/api/materials";
import { MaterialPickerDialog } from "./MaterialPickerDialog";
import { VoicePickerDialog, voicePreviewUrlOf } from "./VoicePickerDialog";

export type NodeMaterialKind = "image" | "video" | "character" | "voice";

const ID_RE = /^[0-9a-f]{32}$/i;

const KIND_META: Record<NodeMaterialKind, { label: string; placeholder: string; icon: typeof ImageIcon }> = {
  image: { label: "素材来源（素材ID / 图片路径 / URL）", placeholder: "从本地素材库选择，或填入素材ID / 图片路径", icon: ImageIcon },
  video: { label: "素材来源（素材ID / 视频路径 / URL）", placeholder: "从本地素材库选择，或填入素材ID / 视频路径", icon: Film },
  character: { label: "素材来源（角色ID）", placeholder: "从本地素材库选择角色", icon: UserRound },
  voice: { label: "素材来源（音色ID，支持 vf:voices:<id>）", placeholder: "从本地素材库选择音色，或填入音色ID", icon: AudioLines },
};

/** 把来源解析为纯素材ID(兼容 vf:voices:<id> 引用格式)。 */
function bareIdOf(source: string): string {
  const value = source.trim();
  const match = value.match(/^vf:[a-z]+:([A-Za-z0-9_-]+)$/i);
  const candidate = match ? match[1] : value;
  return ID_RE.test(candidate) ? candidate : "";
}

function voiceRecordPreviewUrl(id: string, record: MaterialVoiceRecord): string {
  if (record.sample_storage_key?.startsWith(`voices/${id}/`)) {
    return voiceForgeApi.voiceFileUrl(id, record.sample_storage_key);
  }
  if (record.preview_storage_key) {
    return voiceForgeApi.voicePreviewUrl(record.preview_storage_key);
  }
  return "";
}

/**
 * 素材库节点通用卡片(图片/视频/角色/音色):
 * 来源输入 + 已选回显 + 本地素材库选择弹窗 + 素材预览(图片缩略图/视频播放器/音色试听)。
 * 与音频素材库节点同一套约定:卡片记录素材ID,执行时由后端步骤回查详情。
 */
export function MaterialLibraryNodeCard({
  kind,
  config,
  onChange,
}: {
  kind: NodeMaterialKind;
  config: Record<string, any>;
  onChange: (key: string, value: any) => void;
}) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const [record, setRecord] = useState<MaterialImage | MaterialVideo | MaterialCharacter | MaterialVoiceRecord | null>(null);
  const [previewError, setPreviewError] = useState(false);
  const source: string = config?.source ?? "";
  const assetName: string = config?.asset_name ?? "";
  const storedPreview: string = config?.preview ?? "";
  const meta = KIND_META[kind];
  const assetId = bareIdOf(source);

  // 手工填入素材ID时按 ID 拉取详情用于预览(选择回填的素材已带有 preview,无需请求)
  useEffect(() => {
    setRecord(null);
    setPreviewError(false);
    if (!assetId) return;
    let cancelled = false;
    const fetcher =
      kind === "voice"
        ? materialsApi.getVoiceRecord
        : kind === "image"
          ? materialsApi.getImageById
          : kind === "video"
            ? materialsApi.getVideoById
            : materialsApi.getCharacterById;
    fetcher(assetId)
      .then(({ data }) => {
        if (!cancelled) setRecord(data);
      })
      .catch(() => {
        if (!cancelled) setRecord(null);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assetId, kind]);

  let previewSrc = storedPreview;
  if (!previewSrc && record) {
    if (kind === "image" || kind === "video") {
      const row = record as MaterialImage | MaterialVideo;
      previewSrc = materialPreviewUrl(row.path, row.abs_path);
    } else if (kind === "voice") {
      previewSrc = voiceRecordPreviewUrl((record as MaterialVoiceRecord).id, record as MaterialVoiceRecord);
    }
  }
  if (!previewSrc && !assetId) {
    const value = source.trim();
    if (/^https?:\/\//i.test(value)) previewSrc = value;
    else if (/^[a-zA-Z]:[\\/]/.test(value) || value.startsWith("/")) previewSrc = voiceForgeApi.fileStreamUrl(value);
  }
  const showPreview = Boolean(previewSrc) && kind !== "character";

  const clear = () => {
    onChange("source", "");
    onChange("asset_name", "");
    onChange("preview", "");
  };

  const pickFromLibrary = (rec: any) => {
    onChange("source", rec.id);
    onChange("asset_name", rec.display_name || rec.name || "");
    let preview = "";
    if (kind === "image" || kind === "video") preview = materialPreviewUrl(rec.path, rec.abs_path);
    if (kind === "voice") preview = voicePreviewUrlOf(rec);
    onChange("preview", preview);
    setPickerOpen(false);
  };

  return (
    <div className="px-3 pb-3 pt-1 space-y-2">
      <div className="space-y-1">
        <label className="text-[11px] leading-tight text-muted-foreground">{meta.label}</label>
        <Input
          value={source}
          placeholder={meta.placeholder}
          onChange={(e) => onChange("source", e.target.value)}
          onPointerDown={(e) => e.stopPropagation()}
          className="text-xs"
        />
        {(assetName || assetId) && (
          <div className="flex items-center gap-1.5 rounded-md border border-primary/30 bg-primary/5 px-2 py-1 text-[11px]">
            <meta.icon className="h-3 w-3 shrink-0 text-primary" />
            <span className="truncate text-muted-foreground">
              已选素材：{assetName && <span className="font-semibold text-foreground">{assetName}</span>}
              {assetId && <span className="ml-1 font-mono">ID {assetId}</span>}
            </span>
            <button
              type="button"
              title="清除已选素材"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => {
                e.stopPropagation();
                clear();
              }}
              className="ml-auto shrink-0 rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        )}
      </div>

      <Button
        variant="outline"
        className="w-full"
        onClick={(e) => {
          e.stopPropagation();
          setPickerOpen(true);
        }}
      >
        <FolderOpen className="mr-1 size-3.5" />
        本地素材库
      </Button>

      {kind === "character" ? (
        record && (
          <p className="truncate rounded-md border border-dashed border-border/60 px-2 py-1.5 text-[10px] text-muted-foreground/80" title={(record as MaterialCharacter).personality || ""}>
            {(record as MaterialCharacter).personality || (record as MaterialCharacter).occupation || "角色详情将在执行时回查"}
          </p>
        )
      ) : showPreview ? (
        <div className="space-y-1">
          {previewError && <p className="text-[10px] leading-snug text-destructive">素材无法预览，请检查素材文件是否有效。</p>}
          {kind === "voice" ? (
            <audio
              key={previewSrc}
              controls
              preload="none"
              src={previewSrc}
              onError={() => setPreviewError(true)}
              onPointerDown={(e) => e.stopPropagation()}
              className="h-8 w-full"
            />
          ) : kind === "video" ? (
            <video
              key={previewSrc}
              controls
              preload="metadata"
              src={previewSrc}
              onError={() => setPreviewError(true)}
              onPointerDown={(e) => e.stopPropagation()}
              className="max-h-36 w-full rounded-lg border border-border/60 bg-black/80"
            />
          ) : (
            <img
              key={previewSrc}
              src={previewSrc}
              alt="素材预览"
              loading="lazy"
              onError={() => setPreviewError(true)}
              onPointerDown={(e) => e.stopPropagation()}
              className="max-h-36 w-full rounded-lg border border-border/60 object-contain bg-muted/30"
            />
          )}
        </div>
      ) : (
        <div className="flex h-8 items-center gap-1.5 rounded-md border border-dashed border-border/60 px-2 text-[10px] text-muted-foreground/70">
          <meta.icon className="h-3 w-3" />
          填入素材来源后可直接预览
        </div>
      )}

      {kind === "voice" ? (
        <VoicePickerDialog
          open={pickerOpen}
          onClose={() => setPickerOpen(false)}
          onSelected={(ref, voice) => pickFromLibrary({ ...voice, id: ref.replace(/^vf:voices:/, "") })}
        />
      ) : (
        <MaterialPickerDialog kind={kind} open={pickerOpen} onClose={() => setPickerOpen(false)} onPicked={pickFromLibrary} />
      )}
    </div>
  );
}

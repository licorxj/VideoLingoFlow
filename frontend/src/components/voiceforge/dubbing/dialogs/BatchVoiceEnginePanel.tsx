import { useRef } from "react";
import { Settings2, Upload, Loader2, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { VoiceForgeCapability } from "@/api/voiceforge";

interface BatchVoiceEnginePanelProps {
  capabilities: VoiceForgeCapability[];
  interfaceId: string;
  onInterfaceChange: (id: string) => void;
  mode: "voice_design" | "controllable_clone";
  onModeChange: (mode: "voice_design" | "controllable_clone") => void;
  instructTemplate: string;
  onInstructTemplateChange: (v: string) => void;
  previewText: string;
  onPreviewTextChange: (v: string) => void;
  speed: number;
  onSpeedChange: (v: number) => void;
  referenceKey: string | null;
  onUploadReference: (file: File) => Promise<void>;
  uploadingReference: boolean;
  onApplyToAll: () => void;
}

const SPEED_OPTIONS = ["0.5", "0.75", "1.0", "1.25", "1.5", "1.75", "2.0"];

export function BatchVoiceEnginePanel({
  capabilities,
  interfaceId,
  onInterfaceChange,
  mode,
  onModeChange,
  instructTemplate,
  onInstructTemplateChange,
  previewText,
  onPreviewTextChange,
  speed,
  onSpeedChange,
  referenceKey,
  onUploadReference,
  uploadingReference,
  onApplyToAll,
}: BatchVoiceEnginePanelProps) {
  const fileRef = useRef<HTMLInputElement>(null);

  const current = capabilities.find((c) => c.id === interfaceId);
  const supportedModes = Object.keys(current?.modes ?? {});
  const designSupported = supportedModes.includes("voice_design");
  const cloneSupported =
    supportedModes.includes("controllable_clone") || supportedModes.includes("clone");

  return (
    <div className="space-y-3 rounded-lg border border-border/60 bg-accent/20 p-3">
      <div className="flex items-center gap-1 text-sm font-semibold">
        <Settings2 className="h-4 w-4 text-muted-foreground" />
        引擎与参数
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            TTS 接口
          </label>
          <Select value={interfaceId} onValueChange={onInterfaceChange}>
            <SelectTrigger className="h-8 text-sm">
              <SelectValue placeholder="选择接口" />
            </SelectTrigger>
            <SelectContent>
              {capabilities.map((c) => (
                <SelectItem key={c.id} value={c.id}>
                  {c.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            生成方式
          </label>
          <Select value={mode} onValueChange={(v) => onModeChange(v as typeof mode)}>
            <SelectTrigger className="h-8 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {designSupported && (
                <SelectItem value="voice_design">音色设计</SelectItem>
              )}
              {cloneSupported && (
                <SelectItem value="controllable_clone">可控克隆</SelectItem>
              )}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            语速
          </label>
          <Select value={String(speed)} onValueChange={(v) => onSpeedChange(Number(v))}>
            <SelectTrigger className="h-8 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SPEED_OPTIONS.map((s) => (
                <SelectItem key={s} value={s}>
                  {s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {mode === "controllable_clone" && (
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              参考音频
            </label>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-8 flex-1"
                onClick={() => fileRef.current?.click()}
                disabled={uploadingReference}
              >
                {uploadingReference ? (
                  <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                ) : referenceKey ? (
                  <Check className="mr-1 h-3.5 w-3.5 text-success" />
                ) : (
                  <Upload className="mr-1 h-3.5 w-3.5" />
                )}
                {referenceKey ? "已上传" : "上传音频"}
              </Button>
              <input
                ref={fileRef}
                type="file"
                accept="audio/*"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) onUploadReference(file);
                  e.target.value = "";
                }}
              />
            </div>
          </div>
        )}
      </div>

      <div>
        <label className="mb-1 block text-xs font-medium text-muted-foreground">
          音色设计描述（模板）
        </label>
        <Textarea
          value={instructTemplate}
          onChange={(e) => onInstructTemplateChange(e.target.value)}
          placeholder="例如：一位温柔知性的年轻女性，声音清澈，语速适中，带一点点俏皮。"
          className="min-h-[60px] resize-none text-sm"
        />
      </div>

      <div>
        <label className="mb-1 block text-xs font-medium text-muted-foreground">
          试听文本
        </label>
        <Input
          value={previewText}
          onChange={(e) => onPreviewTextChange(e.target.value)}
          className="h-8 text-sm"
        />
      </div>

      <div className="flex justify-end">
        <Button type="button" variant="secondary" size="sm" onClick={onApplyToAll}>
          应用到全部角色
        </Button>
      </div>
    </div>
  );
}

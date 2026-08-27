import { Loader2, Wand2, CheckCircle2, AlertCircle, User } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { voiceForgeApi } from "@/api/voiceforge";

export interface BatchCharacterInfo {
  id: string;
  name: string;
  character_type?: string;
  voice_profile_id?: string | null;
}

export interface BatchItemStatus {
  state: "idle" | "generating" | "done" | "error";
  voiceId?: string;
  previewKey?: string;
  error?: string;
}

interface BatchVoiceItemCardProps {
  character: BatchCharacterInfo;
  instruct: string;
  onInstructChange: (v: string) => void;
  status: BatchItemStatus;
  onGenerate: () => void;
}

const GENDER_LABEL: Record<string, string> = {
  male: "男",
  female: "女",
  narrator: "旁白",
  protagonist: "主角",
  supporting: "配角",
  other: "其他",
};

function genderLabel(type?: string): string | null {
  if (!type) return null;
  if (type === "male" || type === "female") return type === "male" ? "男" : "女";
  return GENDER_LABEL[type] || type;
}

export function BatchVoiceItemCard({
  character,
  instruct,
  onInstructChange,
  status,
  onGenerate,
}: BatchVoiceItemCardProps) {
  const gender = genderLabel(character.character_type);

  return (
    <div className="rounded-lg border border-border/60 p-3">
      <div className="mb-2 flex items-center gap-2">
        <User className="h-4 w-4 text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate text-sm font-medium">
          {character.name}
        </span>
        {gender && (
          <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
            {gender}
          </span>
        )}
        {character.voice_profile_id && (
          <span className="shrink-0 rounded-full bg-success/15 px-1.5 py-0.5 text-[10px] font-medium text-success">
            已绑定
          </span>
        )}
      </div>

      <Textarea
        value={instruct}
        onChange={(e) => onInstructChange(e.target.value)}
        placeholder="该角色的音色设计描述（留空使用模板）"
        className="mb-2 min-h-[52px] resize-none text-sm"
      />

      <div className="flex items-center justify-between">
        <div className="min-w-0 flex-1">
          {status.state === "generating" && (
            <span className="flex items-center gap-1 text-xs text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />
              生成中…
            </span>
          )}
          {status.state === "done" && (
            <span className="flex items-center gap-1 text-xs text-success">
              <CheckCircle2 className="h-3 w-3" />
              已生成
            </span>
          )}
          {status.state === "error" && (
            <span className="flex items-center gap-1 truncate text-xs text-destructive">
              <AlertCircle className="h-3 w-3 shrink-0" />
              {status.error || "生成失败"}
            </span>
          )}
        </div>

        {status.state === "done" && status.previewKey ? (
          <audio
            controls
            className="h-8 max-w-[180px]"
            src={voiceForgeApi.voicePreviewUrl(status.previewKey)}
          />
        ) : (
          <Button
            size="sm"
            variant="outline"
            onClick={onGenerate}
            disabled={status.state === "generating"}
          >
            {status.state === "generating" ? (
              <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Wand2 className="mr-1 h-3.5 w-3.5" />
            )}
            生成
          </Button>
        )}
      </div>
    </div>
  );
}

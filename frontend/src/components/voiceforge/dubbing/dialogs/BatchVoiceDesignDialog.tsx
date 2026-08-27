import { useEffect, useState } from "react";
import { Loader2, Wand2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { voiceForgeApi, VoiceForgeCapability } from "@/api/voiceforge";
import { BatchVoiceEnginePanel } from "./BatchVoiceEnginePanel";
import {
  BatchVoiceItemCard,
  BatchCharacterInfo,
  BatchItemStatus,
} from "./BatchVoiceItemCard";

interface BatchVoiceDesignDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  characters: BatchCharacterInfo[];
  capabilities: VoiceForgeCapability[];
  onSuccess: () => void;
}

const DEFAULT_PREVIEW_TEXT =
  "这是一段用于测试音色的示例文本，语调自然，包含陈述与疑问。";

export function BatchVoiceDesignDialog({
  open,
  onOpenChange,
  characters,
  capabilities,
  onSuccess,
}: BatchVoiceDesignDialogProps) {
  const [interfaceId, setInterfaceId] = useState("");
  const [mode, setMode] = useState<"voice_design" | "controllable_clone">("voice_design");
  const [instructTemplate, setInstructTemplate] = useState("");
  const [previewText, setPreviewText] = useState(DEFAULT_PREVIEW_TEXT);
  const [speed, setSpeed] = useState(1.0);
  const [referenceKey, setReferenceKey] = useState<string | null>(null);
  const [uploadingReference, setUploadingReference] = useState(false);
  const [perCharInstruct, setPerCharInstruct] = useState<Record<string, string>>({});
  const [statuses, setStatuses] = useState<Record<string, BatchItemStatus>>({});
  const [generatingAll, setGeneratingAll] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setError("");
    setStatuses({});
    setReferenceKey(null);
    const designCap =
      capabilities.find((c) => c.modes?.voice_design?.enabled) ?? capabilities[0];
    if (designCap) setInterfaceId(designCap.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const setStatus = (id: string, status: BatchItemStatus) => {
    setStatuses((prev) => ({ ...prev, [id]: status }));
  };

  const handleUploadReference = async (file: File) => {
    setUploadingReference(true);
    try {
      const res = await voiceForgeApi.uploadVoiceReference(file);
      setReferenceKey(res.data.storage_key);
    } catch (err: unknown) {
      setError(
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
          "参考音频上传失败",
      );
    } finally {
      setUploadingReference(false);
    }
  };

  const applyTemplateToAll = () => {
    const next: Record<string, string> = {};
    for (const char of characters) {
      next[char.id] = instructTemplate;
    }
    setPerCharInstruct(next);
  };

  const generateOne = async (char: BatchCharacterInfo): Promise<boolean> => {
    if (!interfaceId) {
      setError("请先选择 TTS 接口");
      return false;
    }
    if (mode === "controllable_clone" && !referenceKey) {
      setError("克隆模式需要上传参考音频");
      return false;
    }
    const instruct = (perCharInstruct[char.id] ?? instructTemplate).trim();
    setStatus(char.id, { state: "generating" });
    try {
      const payload: Record<string, unknown> = {
        interface_id: interfaceId,
        mode,
        text: previewText.trim() || DEFAULT_PREVIEW_TEXT,
        speed,
        count: 1,
      };
      if (mode === "voice_design") {
        payload.voice_design = instruct || undefined;
      } else {
        payload.controllable_clone = instruct || undefined;
        payload.reference_storage_key = referenceKey || undefined;
      }

      const prevRes = await voiceForgeApi.previewVoiceBatch(payload);
      const candidate = (prevRes.data?.candidates ?? []).find(
        (c: { storage_key?: string }) => c.storage_key,
      );
      if (!candidate?.storage_key) {
        throw new Error("试听音频生成失败");
      }

      const vRes = await voiceForgeApi.createVoice({
        name: `${char.name}_${Date.now().toString(36)}`,
        display_name: `${char.name}的音色`,
        interface_id: interfaceId,
        mode,
        language: "zh-CN",
        tags: [],
        description: instruct,
        gender: char.character_type || "",
        is_cloned: mode !== "voice_design",
        design_text: mode === "voice_design" ? instruct : undefined,
        reference_storage_key:
          mode === "controllable_clone" ? referenceKey || undefined : undefined,
        preview_storage_key: candidate.storage_key,
        preview_text: previewText.trim(),
        params:
          mode === "voice_design"
            ? { voice_design: instruct }
            : { controllable_clone: instruct },
      });
      const voice = vRes.data?.voice;
      if (!voice?.id) {
        throw new Error("音色保存失败");
      }

      await voiceForgeApi.updateCharacter(char.id, { voice_profile_id: voice.id });
      setStatus(char.id, {
        state: "done",
        voiceId: voice.id,
        previewKey: candidate.storage_key,
      });
      return true;
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setStatus(char.id, {
        state: "error",
        error: typeof detail === "string" ? detail : "生成失败",
      });
      return false;
    }
  };

  const generateAll = async () => {
    setGeneratingAll(true);
    setError("");
    let successCount = 0;
    for (const char of characters) {
      const ok = await generateOne(char);
      if (ok) successCount += 1;
    }
    setGeneratingAll(false);
    if (successCount > 0) {
      onSuccess();
    }
  };

  const doneCount = Object.values(statuses).filter((s) => s.state === "done").length;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>批量音色设计</DialogTitle>
          <DialogDescription>
            为每个角色自动设计并生成专属音色，生成后自动绑定到角色。
          </DialogDescription>
        </DialogHeader>

        {characters.length === 0 ? (
          <div className="py-10 text-center text-sm text-muted-foreground">
            当前项目还没有角色，请先在「项目角色」中添加角色。
          </div>
        ) : (
          <div className="space-y-4">
            <BatchVoiceEnginePanel
              capabilities={capabilities}
              interfaceId={interfaceId}
              onInterfaceChange={setInterfaceId}
              mode={mode}
              onModeChange={setMode}
              instructTemplate={instructTemplate}
              onInstructTemplateChange={setInstructTemplate}
              previewText={previewText}
              onPreviewTextChange={setPreviewText}
              speed={speed}
              onSpeedChange={setSpeed}
              referenceKey={referenceKey}
              onUploadReference={handleUploadReference}
              uploadingReference={uploadingReference}
              onApplyToAll={applyTemplateToAll}
            />

            <div className="max-h-80 space-y-2 overflow-y-auto">
              {characters.map((char) => (
                <BatchVoiceItemCard
                  key={char.id}
                  character={char}
                  instruct={perCharInstruct[char.id] ?? instructTemplate}
                  onInstructChange={(v) =>
                    setPerCharInstruct((prev) => ({ ...prev, [char.id]: v }))
                  }
                  status={statuses[char.id] ?? { state: "idle" }}
                  onGenerate={() => generateOne(char)}
                />
              ))}
            </div>

            {error && <div className="text-xs text-destructive">{error}</div>}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            关闭
          </Button>
          <Button
            onClick={generateAll}
            disabled={generatingAll || characters.length === 0 || !interfaceId}
          >
            {generatingAll ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : (
              <Wand2 className="mr-1 h-4 w-4" />
            )}
            一键生成全部
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

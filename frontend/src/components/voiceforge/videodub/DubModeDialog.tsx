import { useEffect, useState } from "react";
import { AudioLines, Bot, Copy, Loader2, Mic2 } from "lucide-react";
import client from "@/api/client";
import { ttsInterfacesApi, TTSInterface } from "@/api/ttsInterfaces";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { useVideoDubStore } from "./store";

type ModeTab = "voice" | "clone" | "tts_interface";

const TABS: Array<{ value: ModeTab; label: string; icon: any; detail: string }> = [
  { value: "voice", label: "音色配音", icon: Mic2, detail: "使用音色库中已建立的音色档案（预置/克隆/声音设计均可），逐句合成配音。" },
  { value: "clone", label: "克隆模式", icon: Copy, detail: "取该句的原文音频片段作为参考音频，以克隆音色生成译文配音；适合翻译配音场景。" },
  { value: "tts_interface", label: "TTS 接口音色", icon: Bot, detail: "直接使用 TTS 接口自带的原生音色（不经过音色库），如 edge-tts 的 XiaoxiaoNeural。" },
];

interface TTSEngineVoice {
  voice_id: string;
  voice_name?: string;
  language?: string;
  gender?: string;
}

export function DubModeDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const dubMode = useVideoDubStore((state) => state.dubMode);
  const cloneInterfaceId = useVideoDubStore((state) => state.cloneInterfaceId);
  const ttsInterfaceId = useVideoDubStore((state) => state.ttsInterfaceId);
  const ttsVoiceId = useVideoDubStore((state) => state.ttsVoiceId);
  const setDubConfig = useVideoDubStore((state) => state.setDubConfig);
  const loadVoices = useVideoDubStore((state) => state.loadVoices);
  const voices = useVideoDubStore((state) => state.voices);
  const voicesError = useVideoDubStore((state) => state.voicesError);
  const dubVoiceId = useVideoDubStore((state) => state.dubVoiceId);

  const [tab, setTab] = useState<ModeTab>(dubMode);
  const [interfaces, setInterfaces] = useState<TTSInterface[]>([]);
  const [engineVoices, setEngineVoices] = useState<TTSEngineVoice[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingVoices, setLoadingVoices] = useState(false);

  useEffect(() => {
    if (open) {
      setTab(dubMode);
      ttsInterfacesApi
        .getEnabled()
        .then((res) => setInterfaces((res.data as { interfaces?: TTSInterface[] }).interfaces || []))
        .catch(() => setInterfaces([]));
      if (!voices.length) void loadVoices();
    }
  }, [open, dubMode, loadVoices, voices.length]);

  // 克隆模式：选接口后加载该接口音色列表
  useEffect(() => {
    if (tab !== "clone" || !cloneInterfaceId) return;
    // 克隆模式不需要音色列表（用原音作参考），但这里加载以备预览
  }, [tab, cloneInterfaceId]);

  // 接口音色模式：选接口后加载该接口的原生音色
  useEffect(() => {
    if (tab !== "tts_interface" || !ttsInterfaceId) {
      setEngineVoices([]);
      return;
    }
    setLoadingVoices(true);
    client
      .get(`/api/tts-voices/${ttsInterfaceId}`)
      .then((res) => setEngineVoices(res.data.voices || []))
      .catch(() => setEngineVoices([]))
      .finally(() => setLoadingVoices(false));
  }, [tab, ttsInterfaceId]);

  const confirm = () => {
    setDubConfig({ dubMode: tab });
    onOpenChange(false);
  };

  const selectedVoice = voices.find((v) => v.id === dubVoiceId);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[80vh] max-w-xl flex-col">
        <DialogHeader>
          <DialogTitle>配音模式设置</DialogTitle>
          <DialogDescription>选择配音生成方式，逐句 TTS 合成时会按此模式调用接口。</DialogDescription>
        </DialogHeader>

        {/* 模式卡片 */}
        <div className="grid gap-2 sm:grid-cols-3">
          {TABS.map((option) => {
            const Icon = option.icon;
            const active = tab === option.value;
            return (
              <button
                key={option.value}
                type="button"
                onClick={() => setTab(option.value)}
                className={cn(
                  "rounded-lg border p-2.5 text-left transition-colors",
                  active ? "border-primary/60 bg-primary/10" : "border-border bg-background hover:border-primary/40",
                )}
              >
                <span className={cn("flex items-center gap-1.5 text-sm font-medium", active && "text-primary")}>
                  <Icon className="h-4 w-4" />
                  {option.label}
                </span>
                <span className="mt-1 block text-[11px] leading-4 text-muted-foreground">{option.detail}</span>
              </button>
            );
          })}
        </div>

        {/* 按模式展示配置区 */}
        <div className="flex min-h-[120px] flex-1 flex-col gap-2">
          {tab === "voice" && (
            <div className="space-y-2">
              <label className="flex items-center gap-2 text-xs text-foreground/80">
                <span className="w-16 flex-none">配音音色</span>
                <select
                  value={dubVoiceId || ""}
                  onChange={(event) => setDubConfig({ dubVoiceId: event.target.value || null })}
                  className="h-8 min-w-0 flex-1 rounded-md border border-border bg-background px-2 text-xs"
                >
                  {voicesError ? (
                    <option value="">{voicesError}</option>
                  ) : !voices.length ? (
                    <option value="">加载音色中…</option>
                  ) : null}
                  {voices.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.display_name || v.name}
                      {v.interface_id ? ` (${v.interface_id})` : ""}
                    </option>
                  ))}
                </select>
              </label>
              {selectedVoice && (
                <p className="text-[11px] text-muted-foreground">
                  已选：{selectedVoice.display_name || selectedVoice.name} · 模式 {selectedVoice.mode}
                  {selectedVoice.voice_id ? ` · ${selectedVoice.voice_id}` : ""}
                </p>
              )}
            </div>
          )}

          {tab === "clone" && (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">
                克隆模式用该句的原文音频片段（原音轨上起点对齐的片段）作为参考音频，提交给 TTS 接口合成译文。请确认原音轨上有该句的原文音频（如通过 vlf 任务导入）。
              </p>
              <label className="flex items-center gap-2 text-xs text-foreground/80">
                <span className="w-16 flex-none">TTS 接口</span>
                <select
                  value={cloneInterfaceId || ""}
                  onChange={(event) => setDubConfig({ cloneInterfaceId: event.target.value || null })}
                  className="h-8 min-w-0 flex-1 rounded-md border border-border bg-background px-2 text-xs"
                >
                  <option value="">选择支持克隆模式的 TTS 接口</option>
                  {interfaces
                    .filter((i) => i.config?.modes?.clone?.enabled)
                    .map((i) => (
                      <option key={i.id} value={i.id}>
                        {i.name} ({i.type})
                      </option>
                    ))}
                </select>
              </label>
            </div>
          )}

          {tab === "tts_interface" && (
            <div className="space-y-2">
              <label className="flex items-center gap-2 text-xs text-foreground/80">
                <span className="w-16 flex-none">TTS 接口</span>
                <select
                  value={ttsInterfaceId || ""}
                  onChange={(event) => {
                    setDubConfig({ ttsInterfaceId: event.target.value || null, ttsVoiceId: null });
                  }}
                  className="h-8 min-w-0 flex-1 rounded-md border border-border bg-background px-2 text-xs"
                >
                  <option value="">选择 TTS 接口</option>
                  {interfaces.map((i) => (
                    <option key={i.id} value={i.id}>
                      {i.name} ({i.type})
                    </option>
                  ))}
                </select>
              </label>
              {ttsInterfaceId && (
                <label className="flex items-center gap-2 text-xs text-foreground/80">
                  <span className="w-16 flex-none">原生音色</span>
                  {loadingVoices ? (
                    <span className="flex items-center gap-1 text-xs text-muted-foreground">
                      <Loader2 className="h-3 w-3 animate-spin" />
                      加载音色中…
                    </span>
                  ) : (
                    <select
                      value={ttsVoiceId || ""}
                      onChange={(event) => setDubConfig({ ttsVoiceId: event.target.value || null })}
                      className="h-8 min-w-0 flex-1 rounded-md border border-border bg-background px-2 text-xs"
                    >
                      <option value="">默认音色</option>
                      {engineVoices.map((v) => (
                        <option key={v.voice_id} value={v.voice_id}>
                          {v.voice_name || v.voice_id}
                          {v.language ? ` (${v.language})` : ""}
                          {v.gender ? ` · ${v.gender}` : ""}
                        </option>
                      ))}
                    </select>
                  )}
                </label>
              )}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-border/60 pt-3">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={confirm}>确认设置</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

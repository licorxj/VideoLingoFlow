import { useEffect, useMemo, useState } from "react";
import { AudioLines, Mic, MicOff, Trash2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { VoiceForgeCapability, voiceForgeApi } from "@/api/voiceforge";
import AudioSelectorDialog from "@/components/AudioSelectorDialog";

type DesignSource = "input" | "panel";
type TtsMode = "voice_design" | "controllable_clone";

const PANEL_FIELDS: Array<{ key: string; label: string; placeholder: string; long?: boolean }> = [
  { key: "name", label: "姓名", placeholder: "如 林远" },
  { key: "age", label: "年龄", placeholder: "如 28 / 青年" },
  { key: "personality", label: "性格", placeholder: "如 外冷内热、沉稳果决", long: true },
  { key: "dialect", label: "方言描述", placeholder: "如 普通话 / 带川渝口音" },
  { key: "occupation_background", label: "职业和背景", placeholder: "如 宇航员,十年深空任务经历", long: true },
  { key: "voice_description", label: "音色描述", placeholder: "如 低沉磁性,语速偏慢,有故事感", long: true },
];

/** 判断接口是否支持给定设计模式(指令克隆可回退到普通克隆,与后端 build_request_params 的降级一致)。 */
function supportsMode(capability: VoiceForgeCapability, mode: TtsMode): boolean {
  const modes = capability.modes || {};
  if (mode === "voice_design") return Boolean(modes.voice_design?.enabled);
  return Boolean(modes.controllable_clone?.enabled || modes.clone?.enabled);
}

/** 「新建音色角色」节点卡片:设计信息来源二选一 + TTS 引擎设置 + 多情绪开关。 */
export function VoiceCharacterNode({
  config,
  onChange,
}: {
  config: Record<string, any>;
  onChange: (key: string, value: any) => void;
}) {
  const designSource: DesignSource = config?.design_source === "panel" ? "panel" : "input";
  const ttsMode: TtsMode = config?.tts_mode === "controllable_clone" ? "controllable_clone" : "voice_design";
  const interfaceId: string = config?.interface_id ?? "voxcpm";
  const referenceAudio: string = config?.reference_audio ?? "";
  const generateEmotions = Boolean(config?.generate_emotions);
  const panel = (config?.panel ?? {}) as Record<string, string>;

  const [capabilities, setCapabilities] = useState<VoiceForgeCapability[]>([]);
  const [selectorOpen, setSelectorOpen] = useState(false);

  useEffect(() => {
    voiceForgeApi
      .capabilities()
      .then(({ data }) => setCapabilities(data.capabilities || []))
      .catch(() => setCapabilities([]));
  }, []);

  const supported = useMemo(() => capabilities.filter((item) => supportsMode(item, ttsMode)), [capabilities, ttsMode]);

  // 切换设计模式时，若当前接口不支持新模式则自动切换到第一个支持的接口(优先 voxcpm)
  useEffect(() => {
    if (!supported.length) return;
    if (supported.some((item) => item.id === interfaceId)) return;
    const preferred = supported.find((item) => item.id === "voxcpm");
    onChange("interface_id", (preferred || supported[0]).id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [supported, interfaceId]);

  const setPanel = (key: string, value: string) => onChange("panel", { ...panel, [key]: value });

  return (
    <div className="space-y-2 px-3 pb-3 pt-1">
      {/* 1. 设计信息来源 */}
      <div className="space-y-1">
        <label className="text-[11px] leading-tight text-muted-foreground">设计信息来源</label>
        <div className="grid grid-cols-2 gap-1 rounded-lg border border-border/60 p-1">
          {([
            ["input", "来自输入"],
            ["panel", "面板设计"],
          ] as Array<[DesignSource, string]>).map(([value, label]) => (
            <button
              key={value}
              type="button"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => {
                e.stopPropagation();
                onChange("design_source", value);
              }}
              className={`rounded-md px-2 py-1.5 text-xs transition-colors ${designSource === value ? "bg-primary font-medium text-primary-foreground" : "text-muted-foreground hover:bg-muted"}`}
            >
              {label}
            </button>
          ))}
        </div>
        {designSource === "input" ? (
          <p className="text-[10px] leading-snug text-muted-foreground/80">
            读取左侧「角色描述文本」/「角色设计JSON」输入端口：支持纯文本、JSON（含 姓名/年龄/性格/方言/职业和背景/音色描述 字段）或文本、JSON 文件路径。
          </p>
        ) : (
          <div className="grid grid-cols-2 gap-1.5 rounded-lg border border-border/60 bg-card/60 p-2">
            {PANEL_FIELDS.map((field) => (
              <div key={field.key} className={field.long ? "col-span-2" : ""}>
                <label className="text-[10px] text-muted-foreground">{field.label}</label>
                {field.long ? (
                  <textarea
                    value={panel[field.key] ?? ""}
                    onChange={(event) => setPanel(field.key, event.target.value)}
                    placeholder={field.placeholder}
                    onPointerDown={(e) => e.stopPropagation()}
                    className="voice-input mt-0.5 min-h-12 resize-none text-xs"
                  />
                ) : (
                  <Input
                    value={panel[field.key] ?? ""}
                    onChange={(event) => setPanel(field.key, event.target.value)}
                    placeholder={field.placeholder}
                    onPointerDown={(e) => e.stopPropagation()}
                    className="mt-0.5 h-7 text-xs"
                  />
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 2. TTS 引擎设置 */}
      <div className="space-y-1 rounded-lg border border-border/60 p-2">
        <div className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground">
          <AudioLines className="h-3 w-3" />
          TTS 音色设计
        </div>
        <label className="text-[10px] text-muted-foreground">设计模式</label>
        <select
          value={ttsMode}
          onChange={(event) => onChange("tts_mode", event.target.value)}
          onPointerDown={(e) => e.stopPropagation()}
          className="voice-input h-7 text-xs"
        >
          <option value="voice_design">指令设计（无参考音频）</option>
          <option value="controllable_clone">指令克隆（需参考音频）</option>
        </select>

        {ttsMode === "controllable_clone" && (
          <div className="space-y-1 rounded-md border border-primary/30 bg-primary/5 p-1.5">
            <label className="text-[10px] text-muted-foreground">参考音频 *</label>
            {referenceAudio ? (
              <div className="flex items-center gap-1.5 rounded-md border border-border/60 bg-background px-2 py-1 text-[11px]">
                <Mic className="h-3 w-3 shrink-0 text-primary" />
                <span className="truncate" title={referenceAudio}>{referenceAudio.split(/[\\/]/).pop()}</span>
                <button
                  type="button"
                  title="清除参考音频"
                  onPointerDown={(e) => e.stopPropagation()}
                  onClick={(e) => {
                    e.stopPropagation();
                    onChange("reference_audio", "");
                  }}
                  className="ml-auto shrink-0 rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            ) : (
              <Button
                type="button"
                variant="outline"
                className="h-7 w-full text-xs"
                onPointerDown={(e) => e.stopPropagation()}
                onClick={(e) => {
                  e.stopPropagation();
                  setSelectorOpen(true);
                }}
              >
                <MicOff className="mr-1 size-3" />
                选择参考音频
              </Button>
            )}
          </div>
        )}

        <label className="text-[10px] text-muted-foreground">TTS 引擎接口（按模式自动匹配）</label>
        <select
          value={interfaceId}
          onChange={(event) => onChange("interface_id", event.target.value)}
          onPointerDown={(e) => e.stopPropagation()}
          className="voice-input h-7 text-xs"
        >
          {supported.length ? (
            supported.map((item) => (
              <option key={item.id} value={item.id}>{item.name || item.id}</option>
            ))
          ) : (
            <option value={interfaceId}>{interfaceId}（未加载到接口列表）</option>
          )}
        </select>
        {!supported.length && <p className="text-[10px] text-destructive/80">未加载到支持该模式的 TTS 接口，请检查设置的 TTS 接口配置。</p>}
      </div>

      {/* 3. 多情绪片段 */}
      <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-muted-foreground">
        <input
          type="checkbox"
          checked={generateEmotions}
          onChange={(event) => onChange("generate_emotions", event.target.checked)}
          onPointerDown={(e) => e.stopPropagation()}
          className="h-3.5 w-3.5"
        />
        生成多情绪片段（按配音谷情绪标签，指令克隆，5 线程并行）
      </label>

      <AudioSelectorDialog
        open={selectorOpen}
        onClose={() => setSelectorOpen(false)}
        onSelect={(path) => {
          onChange("reference_audio", path);
          setSelectorOpen(false);
        }}
      />
    </div>
  );
}

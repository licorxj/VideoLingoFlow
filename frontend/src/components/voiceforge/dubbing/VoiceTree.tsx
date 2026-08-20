import { useMemo, useState } from "react";
import {
  Headphones,
  Search,
  Volume2,
  Smile,
  Play,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/* ── Types ─────────────────────────────────────────────────────────── */

interface Emotion {
  name: string;
  audio_path?: string;
}

interface Voice {
  id: string;
  display_name: string;
  name: string;
  voice_group?: string;
  emotions?: Emotion[];
}

interface VoiceTreeProps {
  voices: Voice[];
  onPlayVoice: (voiceId: string, storageKey: string) => void;
}

/* ── Grouping helper ────────────────────────────────────────────────── */

interface VoiceGroup {
  label: string;
  voices: Voice[];
}

function groupVoices(voices: Voice[], filter: string): VoiceGroup[] {
  const lower = filter.toLowerCase();
  const filtered = lower
    ? voices.filter(
        (v) =>
          v.display_name.toLowerCase().includes(lower) ||
          v.name.toLowerCase().includes(lower) ||
          (v.emotions ?? []).some((e) => e.name.toLowerCase().includes(lower)),
      )
    : voices;

  const map = new Map<string, Voice[]>();
  for (const v of filtered) {
    const key = v.voice_group || "未分组";
    const arr = map.get(key) ?? [];
    arr.push(v);
    map.set(key, arr);
  }

  // Sort groups: "未分组" last
  const sorted = [...map.entries()].sort((a, b) => {
    if (a[0] === "未分组") return 1;
    if (b[0] === "未分组") return -1;
    return a[0].localeCompare(b[0]);
  });

  return sorted.map(([label, voices]) => ({ label, voices }));
}

/* ── VoiceTree Component ────────────────────────────────────────────── */

export function VoiceTree({ voices, onPlayVoice }: VoiceTreeProps) {
  const [filter, setFilter] = useState("");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const groups = useMemo(() => groupVoices(voices, filter), [voices, filter]);

  const toggleGroup = (label: string) => {
    setCollapsed((prev) => ({ ...prev, [label]: !prev[label] }));
  };

  return (
    <div className="flex min-h-[50%] flex-col">
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-border/60 px-3 py-3">
        <Headphones className="h-4 w-4 text-muted-foreground" />
        <span className="text-sm font-semibold">音色库</span>
        <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
          {voices.length}
        </span>
      </div>

      {/* Search */}
      <div className="border-b border-border/60 px-3 py-2.5">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="搜索音色..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="h-8 pl-8 text-sm"
          />
        </div>
      </div>

      {/* Voice groups */}
      <div className="flex-1 overflow-y-auto px-3 py-2">
        {groups.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
            <Headphones className="mb-2 h-8 w-8 opacity-40" />
            <span className="text-sm">
              {filter ? "未找到匹配的音色" : "暂无音色"}
            </span>
          </div>
        ) : (
          <div className="space-y-1">
            {groups.map((group) => {
              const collapsed_ = !!collapsed[group.label];
              return (
                <div key={group.label}>
                  {/* Group header */}
                  <button
                    type="button"
                    onClick={() => toggleGroup(group.label)}
                    className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent/60 hover:text-foreground"
                  >
                    {collapsed_ ? (
                      <ChevronRight className="h-3.5 w-3.5 shrink-0" />
                    ) : (
                      <ChevronDown className="h-3.5 w-3.5 shrink-0" />
                    )}
                    <span className="min-w-0 flex-1 truncate text-left">
                      {group.label}
                    </span>
                    <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                      {group.voices.length}
                    </span>
                  </button>

                  {/* Voice items */}
                  {!collapsed_ && (
                    <div className="ml-3 space-y-0.5 border-l border-border/40 pl-2">
                      {group.voices.map((voice) => (
                        <div key={voice.id}>
                          {/* Voice row */}
                          <div className="group flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-accent/60">
                            <Volume2 className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                            <span className="min-w-0 flex-1 truncate">
                              {voice.display_name || voice.name}
                            </span>
                            <Button
                              size="icon"
                              variant="ghost"
                              className="h-6 w-6 shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
                              onClick={() =>
                                onPlayVoice(voice.id, voice.name)
                              }
                              title="播放"
                            >
                              <Play className="h-3.5 w-3.5" />
                            </Button>
                          </div>

                          {/* Emotion sub-items */}
                          {voice.emotions && voice.emotions.length > 0 && (
                            <div className="ml-5 space-y-0.5 border-l border-border/30 pl-2">
                              {voice.emotions.map((emotion) => (
                                <div
                                  key={emotion.name}
                                  className="group flex items-center gap-2 rounded-md px-2 py-1 text-xs transition-colors hover:bg-accent/60"
                                >
                                  <Smile className="h-3 w-3 shrink-0 text-muted-foreground" />
                                  <span className="min-w-0 flex-1 truncate text-muted-foreground">
                                    {emotion.name}
                                  </span>
                                  {emotion.audio_path && (
                                    <Button
                                      size="icon"
                                      variant="ghost"
                                      className="h-5 w-5 shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
                                      onClick={() =>
                                        onPlayVoice(
                                          voice.id,
                                          emotion.audio_path!,
                                        )
                                      }
                                      title="播放情绪"
                                    >
                                      <Play className="h-3 w-3" />
                                    </Button>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Total count footer */}
      <div className="border-t border-border/60 px-3 py-2 text-center text-xs text-muted-foreground">
        共 {voices.length} 个音色
      </div>
    </div>
  );
}

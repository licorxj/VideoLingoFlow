import { useEffect, useMemo, useState } from "react";
import { AudioLines, RefreshCw, Search } from "lucide-react";
import { VoiceForgeVoice, voiceForgeApi } from "@/api/voiceforge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EmptyState } from "@/components/shared/EmptyState";
import { LoadingState } from "@/components/shared/LoadingState";

const LANGUAGE_LABELS: Record<string, string> = {
  "zh-CN": "中文",
  "en-US": "英语",
  "ja-JP": "日语",
  "ko-KR": "韩语",
};

/** 取音色的试听音频地址:优先设计样音(音色目录内),其次试听/参考音频。 */
export function voicePreviewUrlOf(voice: VoiceForgeVoice): string {
  if (voice.sample_storage_key?.startsWith(`voices/${voice.id}/`)) {
    return voiceForgeApi.voiceFileUrl(voice.id, voice.sample_storage_key);
  }
  if (voice.preview_storage_key) {
    return voiceForgeApi.voicePreviewUrl(voice.preview_storage_key);
  }
  if (voice.reference_storage_key?.startsWith(`voices/${voice.id}/`)) {
    return voiceForgeApi.voiceFileUrl(voice.id, voice.reference_storage_key);
  }
  return "";
}

function distinctValues(voices: VoiceForgeVoice[], pick: (voice: VoiceForgeVoice) => string) {
  return Array.from(new Set(voices.map(pick).filter(Boolean))).sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
}

/**
 * 音色选择弹窗(宽窗口):左侧分组侧栏 + 性别/年龄/语言组合筛选 + 卡片网格,
 * 试听后选择,回传 vf:voices:<id> 引用。
 */
export function VoicePickerDialog({
  open,
  onClose,
  onSelected,
}: {
  open: boolean;
  onClose: () => void;
  onSelected: (ref: string, voice: VoiceForgeVoice) => void;
}) {
  const [voices, setVoices] = useState<VoiceForgeVoice[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [group, setGroup] = useState("");
  const [gender, setGender] = useState("");
  const [age, setAge] = useState("");
  const [language, setLanguage] = useState("");
  const [playingId, setPlayingId] = useState("");

  const load = () => {
    setLoading(true);
    setError("");
    voiceForgeApi
      .voices("")
      .then(({ data }) => setVoices(Array.isArray(data) ? data : data.voices || []))
      .catch((err) => setError(err?.message || "音色加载失败"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    if (open) {
      load();
      setPlayingId("");
    }
  }, [open]);

  // 分组侧栏数据(全部 / 各分组 / 未分组)
  const groups = useMemo(() => {
    const counter = new Map<string, number>();
    for (const voice of voices) {
      const key = voice.voice_group?.trim() || "";
      counter.set(key, (counter.get(key) || 0) + 1);
    }
    const named = Array.from(counter.entries())
      .filter(([key]) => key)
      .sort((a, b) => a[0].localeCompare(b[0], "zh-Hans-CN"));
    return { named, ungrouped: counter.get("") || 0 };
  }, [voices]);

  // 筛选候选项(从全部音色统计,不随其它筛选联动收缩,保证可跨维度组合)
  const genderOptions = useMemo(() => distinctValues(voices, (voice) => voice.gender || ""), [voices]);
  const ageOptions = useMemo(() => distinctValues(voices, (voice) => voice.voice_age || ""), [voices]);
  const languageOptions = useMemo(() => distinctValues(voices, (voice) => voice.language || ""), [voices]);

  // 组合筛选:分组 + 搜索 + 性别/年龄/语言
  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return voices.filter((voice) => {
      if (group === "__ungrouped__" ? Boolean(voice.voice_group?.trim()) : group && voice.voice_group?.trim() !== group) return false;
      if (gender && voice.gender !== gender) return false;
      if (age && voice.voice_age !== age) return false;
      if (language && voice.language !== language) return false;
      if (needle) {
        const haystack = [voice.name, voice.display_name, voice.description, voice.design_text, voice.voice_group, ...(voice.tags || [])]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!haystack.includes(needle)) return false;
      }
      return true;
    });
  }, [voices, search, group, gender, age, language]);

  // 卡片网格里按分组分区展示(仅当未指定具体分组时)
  const groupedSections = useMemo(() => {
    const sections = new Map<string, VoiceForgeVoice[]>();
    for (const voice of filtered) {
      const key = voice.voice_group?.trim() || "未分组";
      if (!sections.has(key)) sections.set(key, []);
      sections.get(key)!.push(voice);
    }
    return Array.from(sections.entries()).sort((a, b) => {
      if (a[0] === "未分组") return 1;
      if (b[0] === "未分组") return -1;
      return a[0].localeCompare(b[0], "zh-Hans-CN");
    });
  }, [filtered]);

  const pick = (voice: VoiceForgeVoice) => {
    onSelected(`vf:voices:${voice.id}`, voice);
    onClose();
  };

  const hasFilters = Boolean(search || group || gender || age || language);
  const resetFilters = () => {
    setSearch("");
    setGroup("");
    setGender("");
    setAge("");
    setLanguage("");
  };

  const renderCard = (voice: VoiceForgeVoice) => {
    const preview = voicePreviewUrlOf(voice);
    const playing = playingId === voice.id;
    return (
      <article
        key={voice.id}
        className={`flex flex-col overflow-hidden rounded-xl border transition-shadow hover:shadow-md ${playing ? "border-primary/60 shadow-[0_0_0_1px] shadow-primary/30" : "border-border/60 bg-card"}`}
      >
        <div className={`h-1 w-full ${playing ? "bg-primary" : "bg-primary/30"}`} />
        <div className="flex flex-1 flex-col p-3">
          <div className="flex items-start gap-2">
            <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg ${playing ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground"}`}>
              <AudioLines className={`h-4 w-4 ${playing ? "animate-pulse" : ""}`} />
            </span>
            <div className="min-w-0 flex-1">
              <h4 className="truncate text-sm font-semibold" title={voice.display_name || voice.name}>{voice.display_name || voice.name}</h4>
              <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
                {[voice.gender, voice.voice_age, voice.voice_pitch].filter(Boolean).join(" · ") || "未标注属性"}
                {voice.is_cloned ? " · 克隆" : ""}
              </p>
            </div>
            <Button size="sm" variant="outline" onClick={() => pick(voice)}>选择</Button>
          </div>
          <div className="mt-2 flex flex-wrap gap-1">
            {[voice.gender, voice.voice_age, voice.voice_pitch, voice.dialect, LANGUAGE_LABELS[voice.language] || voice.language].filter(Boolean).map((chip, index) => (
              <span key={`${chip}-${index}`} className="rounded border border-border/60 px-1.5 py-0.5 text-[11px] text-muted-foreground">{chip}</span>
            ))}
            {(voice.tags || []).slice(0, 3).map((tag) => (
              <span key={tag} className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">{tag}</span>
            ))}
          </div>
          {(voice.design_text || voice.description) && (
            <p className="mt-2 line-clamp-2 text-xs text-muted-foreground" title={voice.design_text || voice.description}>{voice.design_text || voice.description}</p>
          )}
          {preview ? (
            <audio
              controls
              preload="none"
              src={preview}
              onPlay={() => setPlayingId(voice.id)}
              onEnded={() => setPlayingId((current) => (current === voice.id ? "" : current))}
              className="mt-3 h-8 w-full"
            />
          ) : (
            <p className="mt-3 text-[11px] text-muted-foreground">暂无试听音频</p>
          )}
        </div>
      </article>
    );
  };

  return (
    <Dialog open={open} onOpenChange={(value) => !value && onClose()}>
      <DialogContent className="max-w-5xl">
        <DialogHeader>
          <DialogTitle>选择音色</DialogTitle>
          <DialogDescription>来自晴沐配音谷音色库,支持分组浏览与性别/年龄/语言组合筛选;试听后选择,自动填入 vf:voices:&lt;id&gt; 引用。</DialogDescription>
        </DialogHeader>

        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-56 flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索音色名称、标签或描述"
              className="voice-input pl-8"
              autoFocus
            />
          </div>
          <select value={gender} onChange={(event) => setGender(event.target.value)} className="voice-input h-10 w-28" title="性别">
            <option value="">全部性别</option>
            {genderOptions.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
          <select value={age} onChange={(event) => setAge(event.target.value)} className="voice-input h-10 w-28" title="年龄">
            <option value="">全部年龄</option>
            {ageOptions.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
          <select value={language} onChange={(event) => setLanguage(event.target.value)} className="voice-input h-10 w-32" title="语言">
            <option value="">全部语言</option>
            {languageOptions.map((item) => <option key={item} value={item}>{LANGUAGE_LABELS[item] || item}</option>)}
          </select>
          {hasFilters && (
            <Button size="sm" variant="outline" onClick={resetFilters}>重置</Button>
          )}
          <Button size="sm" variant="outline" onClick={load} disabled={loading} title="重新加载音色库">
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>

        {error && <p className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}

        <div className="flex gap-3">
          {/* 分组侧栏 */}
          <div className="w-36 shrink-0 space-y-0.5 overflow-y-auto rounded-xl border border-border/60 bg-card p-1.5" style={{ maxHeight: "58vh" }}>
            <button
              type="button"
              onClick={() => setGroup("")}
              className={`flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-sm transition-colors ${group === "" ? "bg-sidebar-active font-semibold text-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground"}`}
            >
              全部音色
              <span className="text-[11px]">{voices.length}</span>
            </button>
            {groups.named.map(([name, count]) => (
              <button
                key={name}
                type="button"
                onClick={() => setGroup(name)}
                className={`flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-sm transition-colors ${group === name ? "bg-sidebar-active font-semibold text-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground"}`}
              >
                <span className="truncate" title={name}>{name}</span>
                <span className="text-[11px]">{count}</span>
              </button>
            ))}
            {groups.ungrouped > 0 && (
              <button
                type="button"
                onClick={() => setGroup("__ungrouped__")}
                className={`flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-sm transition-colors ${group === "__ungrouped__" ? "bg-sidebar-active font-semibold text-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground"}`}
              >
                未分组
                <span className="text-[11px]">{groups.ungrouped}</span>
              </button>
            )}
          </div>

          {/* 卡片网格 */}
          <div className="min-w-0 flex-1 overflow-y-auto pr-1" style={{ maxHeight: "58vh" }}>
            {loading && !voices.length ? (
              <LoadingState label="正在加载音色…" />
            ) : filtered.length ? (
              <div className="space-y-4">
                {(group ? [[group === "__ungrouped__" ? "未分组" : group, filtered] as [string, VoiceForgeVoice[]]] : groupedSections).map(([sectionName, sectionVoices]) => (
                  <div key={sectionName}>
                    {!group && (
                      <h5 className="mb-2 flex items-center gap-2 text-xs font-semibold text-muted-foreground">
                        {sectionName}
                        <span className="rounded-full bg-muted px-1.5 text-[11px] font-normal">{sectionVoices.length}</span>
                        <span className="h-px flex-1 bg-border/60" />
                      </h5>
                    )}
                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                      {sectionVoices.map(renderCard)}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState
                icon={AudioLines}
                title="没有匹配的音色"
                detail={hasFilters ? "当前筛选条件下无结果,试试放宽条件。" : "音色库为空,或到晴沐配音谷的音色库中创建新音色。"}
                action={
                  hasFilters ? (
                    <Button variant="outline" onClick={resetFilters}>重置筛选</Button>
                  ) : undefined
                }
              />
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

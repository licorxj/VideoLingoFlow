import { useState, useEffect, useMemo } from "react";
import { Search, X, Check, Mic2 } from "lucide-react";
import { cn } from "@/lib/utils";
import client from "@/api/client";

interface Voice {
  voice_id: string;
  voice_name: string;
  description: string;
  gender: string;
  age: string;
  language: string;
}

interface VoiceSelectPanelProps {
  interfaceId: string;
  selected?: string;
  onSelect: (voiceId: string, voice: Voice) => void;
  open: boolean;
  onClose: () => void;
}

const GENDER_OPTIONS = [
  { value: "", label: "全部" },
  { value: "male", label: "男" },
  { value: "female", label: "女" },
  { value: "neutral", label: "中性" },
];

const AGE_OPTIONS = [
  { value: "", label: "全部" },
  { value: "child", label: "儿童" },
  { value: "young", label: "青年" },
  { value: "adult", label: "成年" },
  { value: "senior", label: "老年" },
];

const GENDER_BADGE: Record<string, string> = {
  male: "bg-blue-100 text-blue-700",
  female: "bg-pink-100 text-pink-700",
  neutral: "bg-gray-100 text-gray-700",
};

const GENDER_LABEL: Record<string, string> = {
  male: "男",
  female: "女",
  neutral: "中性",
};

const AGE_LABEL: Record<string, string> = {
  child: "儿童",
  young: "青年",
  adult: "成年",
  senior: "老年",
};

export default function VoiceSelectPanel({
  interfaceId,
  selected,
  onSelect,
  open,
  onClose,
}: VoiceSelectPanelProps) {
  const [voices, setVoices] = useState<Voice[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [genderFilter, setGenderFilter] = useState("");
  const [ageFilter, setAgeFilter] = useState("");
  const [langFilter, setLangFilter] = useState("");
  const [selectedId, setSelectedId] = useState(selected || "");

  useEffect(() => {
    if (selected !== undefined) setSelectedId(selected);
  }, [selected]);

  useEffect(() => {
    if (!open || !interfaceId) return;
    setLoading(true);
    setSearch("");
    setGenderFilter("");
    setAgeFilter("");
    setLangFilter("");
    client
      .get(`/api/tts-voices/${interfaceId}`)
      .then((res) => setVoices(res.data.voices || []))
      .catch(() => setVoices([]))
      .finally(() => setLoading(false));
  }, [open, interfaceId]);

  const languages = useMemo(() => {
    const langs = new Set<string>();
    voices.forEach((v) => {
      if (v.language) langs.add(v.language);
    });
    return Array.from(langs).sort();
  }, [voices]);

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return voices.filter((v) => {
      if (genderFilter && v.gender !== genderFilter) return false;
      if (ageFilter && v.age !== ageFilter) return false;
      if (langFilter && v.language !== langFilter) return false;
      if (q) {
        const hay = `${v.voice_name} ${v.voice_id} ${v.description}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [voices, genderFilter, ageFilter, langFilter, search]);

  const selectedVoice = useMemo(
    () => voices.find((v) => v.voice_id === selectedId),
    [voices, selectedId]
  );

  const handleConfirm = () => {
    if (selectedVoice) {
      onSelect(selectedId, selectedVoice);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm animate-fade-in">
      <div className="bg-background rounded-2xl border border-border/50 shadow-2xl w-full max-w-2xl max-h-[80vh] flex flex-col animate-scale-in">
        {/* Header */}
        <div className="px-5 py-4 border-b border-border/40 flex items-center justify-between">
          <h3 className="text-lg font-bold">选择音色</h3>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-secondary transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Filter bar */}
        <div className="px-5 py-3 border-b border-border/30 space-y-3">
          {/* Gender & Age pills */}
          <div className="flex flex-wrap gap-4">
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-muted-foreground mr-1">性别</span>
              {GENDER_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setGenderFilter(opt.value)}
                  className={cn(
                    "px-3 py-1.5 rounded-full text-xs font-medium transition-colors",
                    genderFilter === opt.value
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted/50 text-muted-foreground hover:bg-muted"
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-muted-foreground mr-1">年龄</span>
              {AGE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setAgeFilter(opt.value)}
                  className={cn(
                    "px-3 py-1.5 rounded-full text-xs font-medium transition-colors",
                    ageFilter === opt.value
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted/50 text-muted-foreground hover:bg-muted"
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Language & Search */}
          <div className="flex items-center gap-2">
            {languages.length > 0 && (
              <select
                value={langFilter}
                onChange={(e) => setLangFilter(e.target.value)}
                className="px-3 py-2 border border-border/60 rounded-xl bg-background/50 text-xs focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none"
              >
                <option value="">全部语言</option>
                {languages.map((lang) => (
                  <option key={lang} value={lang}>
                    {lang}
                  </option>
                ))}
              </select>
            )}
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
              <input
                className="w-full pl-8 pr-3 py-2 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none"
                placeholder="搜索音色..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
          </div>
        </div>

        {/* Voice list */}
        <div className="flex-1 overflow-y-auto px-5 py-3 max-h-[400px]">
          {loading ? (
            <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
              加载中...
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <Mic2 className="w-8 h-8 mb-2 opacity-40" />
              <span className="text-sm">没有匹配的音色</span>
            </div>
          ) : (
            <div className="space-y-1.5">
              {filtered.map((v) => {
                const isActive = selectedId === v.voice_id;
                const badgeCls =
                  v.gender && GENDER_BADGE[v.gender]
                    ? GENDER_BADGE[v.gender]
                    : "bg-gray-100 text-gray-700";
                return (
                  <div
                    key={v.voice_id}
                    onClick={() => setSelectedId(v.voice_id)}
                    className={cn(
                      "flex items-center gap-3 p-3 rounded-xl border cursor-pointer transition-colors",
                      isActive
                        ? "border-primary bg-primary/5 ring-1 ring-primary/20"
                        : "border-border/30 hover:border-primary/50"
                    )}
                  >
                    {/* Icon */}
                    <div
                      className={cn(
                        "w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0",
                        v.gender === "male"
                          ? "bg-blue-100 text-blue-600"
                          : v.gender === "female"
                            ? "bg-pink-100 text-pink-600"
                            : "bg-gray-100 text-gray-600"
                      )}
                    >
                      <Mic2 className="w-5 h-5" />
                    </div>

                    {/* Info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold truncate">
                          {v.voice_name}
                        </span>
                        <span className="text-[11px] text-muted-foreground truncate">
                          {v.voice_id}
                        </span>
                      </div>
                      {v.description && (
                        <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1">
                          {v.description}
                        </p>
                      )}
                    </div>

                    {/* Tags */}
                    <div className="flex items-center gap-1 flex-shrink-0">
                      {v.gender && (
                        <span
                          className={cn(
                            "px-2 py-0.5 rounded-full text-[10px] font-medium",
                            badgeCls
                          )}
                        >
                          {GENDER_LABEL[v.gender] || v.gender}
                        </span>
                      )}
                      {v.age && (
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-muted/50 text-muted-foreground">
                          {AGE_LABEL[v.age] || v.age}
                        </span>
                      )}
                      {v.language && (
                        <span className="flex items-center gap-0.5 px-2 py-0.5 rounded-full text-[10px] font-medium bg-muted/50 text-muted-foreground">
                          {v.language}
                        </span>
                      )}
                    </div>

                    {/* Selected indicator */}
                    {isActive && (
                      <div className="w-5 h-5 rounded-full bg-primary text-primary-foreground flex items-center justify-center flex-shrink-0">
                        <Check className="w-3 h-3" strokeWidth={3} />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-border/40 flex items-center justify-between">
          <span className="text-sm text-muted-foreground">
            {selectedVoice ? (
              <>
                已选择:{" "}
                <span className="font-semibold text-foreground">
                  {selectedVoice.voice_name}
                </span>
              </>
            ) : (
              "未选择音色"
            )}
          </span>
          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium border border-border/60 rounded-xl hover:bg-secondary/70 transition-all duration-200 active:scale-[0.97]"
            >
              取消
            </button>
            <button
              onClick={handleConfirm}
              disabled={!selectedVoice}
              className="px-4 py-2 text-sm font-semibold bg-primary text-primary-foreground rounded-xl transition-all duration-200 hover:shadow-lg hover:shadow-primary/25 active:scale-[0.97] disabled:opacity-40"
            >
              确认
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

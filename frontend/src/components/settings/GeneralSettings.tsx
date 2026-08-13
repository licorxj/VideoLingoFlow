import { useState, useEffect } from "react";
import { settingsApi } from "@/api/settings";
import { Scissors, FileText, Languages } from "lucide-react";
import VideoSettings from "./VideoSettings";

const LANGS = [
  { v: "zh", l: "中文" },
  { v: "en", l: "English" },
  { v: "ja", l: "日本語" },
  { v: "ko", l: "한국어" },
  { v: "fr", l: "Français" },
  { v: "de", l: "Deutsch" },
  { v: "es", l: "Español" },
  { v: "ru", l: "Русский" },
  { v: "pt", l: "Português" },
  { v: "ar", l: "العربية" },
];

export default function GeneralSettings() {
  const [targetLang, setTargetLang] = useState("zh");
  const [sourceLang, setSourceLang] = useState("auto");
  const [maxSentLen, setMaxSentLen] = useState(100);
  const [useLlmSplit, setUseLlmSplit] = useState(true);
  const [mergeMinDuration, setMergeMinDuration] = useState(0.5);
  const [mergeMaxGap, setMergeMaxGap] = useState(0.5);
  const [pauseSplitThreshold, setPauseSplitThreshold] = useState(1.0);
  const [reflectTranslate, setReflectTranslate] = useState(true);
  const [translationStyle, setTranslationStyle] = useState('default');
  const [customStyles, setCustomStyles] = useState<Record<string, string>>({});
  const [summaryLen, setSummaryLen] = useState(3000);

  useEffect(() => {
    Promise.all([
      settingsApi.get("general.target_language"),
      settingsApi.get("general.source_language"),
      settingsApi.get("general.max_sentence_length"),
      settingsApi.get("general.use_llm_split"),
      settingsApi.get("general.summary_length"),
      settingsApi.get("general.merge_min_duration"),
      settingsApi.get("general.merge_max_gap"),
      settingsApi.get("general.pause_split_threshold"),
      settingsApi.get("general.reflect_translate"),
      settingsApi.get("general.translation_style"),
      settingsApi.get("general.custom_styles"),
    ]).then(([t, s, m, l, sm, mmd, mmg, pst, rt, ts, cs]) => {
      setTargetLang(t.data.value || "zh");
      setSourceLang(s.data.value || "auto");
      setMaxSentLen(m.data.value ?? 30);
      setUseLlmSplit(l.data.value ?? true);
      setSummaryLen(sm.data.value ?? 3000);
      setMergeMinDuration(mmd.data.value ?? 0.5);
      setMergeMaxGap(mmg.data.value ?? 0.5);
      setPauseSplitThreshold(pst.data.value ?? 1.0);
      setReflectTranslate((rt.data.value ?? true) as boolean);
      setTranslationStyle(ts.data.value || "default");
      setCustomStyles((cs.data.value || {}) as Record<string, string>);
    });
  }, []);

  const save = (k: string, v: any) => settingsApi.update(k, v);

  return (
    <div className="space-y-5 stagger-children">
      {/* 句子分割 */}
      <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Scissors className="w-4 h-4 text-primary" />
          "句子分割"
        </h3>
        <div className="grid grid-cols-3 gap-4">
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              "最大句长度（字符）"
            </label>
            <input
              type="number"
              className="w-full mt-2 px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none"
              value={maxSentLen}
              onChange={(e) => setMaxSentLen(+e.target.value)}
              onBlur={() => save("general.max_sentence_length", maxSentLen)}
            />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              合并过短句子阈值（秒）
            </label>
            <input
              type="number"
              step="0.1"
              className="w-full mt-2 px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none"
              value={mergeMinDuration}
              onChange={(e) => setMergeMinDuration(+e.target.value)}
              onBlur={() => save("general.merge_min_duration", mergeMinDuration)}
            />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              句子间隔小于*秒合并（秒）
            </label>
            <input
              type="number"
              step="0.1"
              className="w-full mt-2 px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none"
              value={mergeMaxGap}
              onChange={(e) => setMergeMaxGap(+e.target.value)}
              onBlur={() => save("general.merge_max_gap", mergeMaxGap)}
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              停顿大于*秒断句（秒）
            </label>
            <input
              type="number"
              step="0.1"
              className="w-full mt-2 px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none"
              value={pauseSplitThreshold}
              onChange={(e) => setPauseSplitThreshold(+e.target.value)}
              onBlur={() => save("general.pause_split_threshold", pauseSplitThreshold)}
            />
          </div>
          <div className="flex items-end">
            <label className="flex items-center gap-3 cursor-pointer group">
              <div className="relative">
                <input
                  type="checkbox"
                  checked={useLlmSplit}
                  onChange={(e) => {
                    setUseLlmSplit(e.target.checked);
                    save("general.use_llm_split", e.target.checked);
                  }}
                  className="peer sr-only"
                />
                <div className="w-9 h-5 bg-muted rounded-full peer-checked:bg-primary transition-colors duration-200" />
                <div className="absolute left-0.5 top-0.5 w-4 h-4 bg-background rounded-full shadow-sm peer-checked:translate-x-4 transition-transform duration-200" />
              </div>
              <span className="text-sm group-hover:text-foreground transition-colors">
                "使用 LLM 智能分句"
              </span>
            </label>
          </div>
        </div>
      </div>

      {/* 内容总结 */}
      <div className="rounded-2xl border border-border/50 bg-card/70 p-5">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <FileText className="w-4 h-4 text-primary" />
          "内容总结"
        </h3>
        <div className="w-1/3">
          <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
            "总结最大长度"
          </label>
          <input
            type="number"
            className="w-full mt-2 px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none"
            value={summaryLen}
            onChange={(e) => setSummaryLen(+e.target.value)}
            onBlur={() => save("general.summary_length", summaryLen)}
          />
        </div>
      </div>

      {/* 翻译 */}
      <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Languages className="w-4 h-4 text-primary" />
          翻译
        </h3>
        <div className="grid grid-cols-2 gap-4">
          <div className="flex items-end">
            <label className="flex items-center gap-3 cursor-pointer group">
              <div className="relative">
                <input
                  type="checkbox"
                  checked={reflectTranslate}
                  onChange={(e) => {
                    setReflectTranslate(e.target.checked);
                    save("general.reflect_translate", e.target.checked);
                  }}
                  className="peer sr-only"
                />
                <div className="w-9 h-5 bg-muted rounded-full peer-checked:bg-primary transition-colors duration-200" />
                <div className="absolute left-0.5 top-0.5 w-4 h-4 bg-background rounded-full shadow-sm peer-checked:translate-x-4 transition-transform duration-200" />
              </div>
              <span className="text-sm group-hover:text-foreground transition-colors">
                启用二次反思翻译
              </span>
            </label>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              翻译风格
            </label>
            <select
              className="w-full mt-2 px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none"
              value={translationStyle}
              onChange={(e) => {
                setTranslationStyle(e.target.value);
                save("general.translation_style", e.target.value);
              }}
            >
              <option value="default">默认风格</option>
              <option value="formal">正式书面</option>
              <option value="casual">轻松口语</option>
              <option value="literary">文学诗意</option>
              <option value="technical">专业技术</option>
              <option value="marketing">营销推广</option>
              <option value="news">新闻报道</option>
              <option value="subtitle">字幕口语</option>
              <option value="poetic">古典诗词</option>
              {Object.keys(customStyles).length > 0 &&
                Object.entries(customStyles).map(([key, desc]) => (
                  <option key={key} value={key}>{desc}</option>
                ))
              }
            </select>
          </div>
        </div>
      </div>

      <VideoSettings />
    </div>
  );
}

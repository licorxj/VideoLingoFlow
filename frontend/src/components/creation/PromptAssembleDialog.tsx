import { createPortal } from "react-dom";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import client from "@/api/client";
import {
  X, Search, Loader2, AlertTriangle, Wand2, Sparkles, Check, Layers, Palette, Film,
} from "lucide-react";

/** 风格/提示词组装弹窗：选模板 → 填槽 → 预览（可 LLM 优化）→ 应用到节点字段 */

type VarDef = {
  key: string; label: string; required?: boolean; default?: string; placeholder?: string;
};
type TplItem = {
  id: string; name: string; slug?: string; category?: string; lang?: string;
  source?: string; tags?: string[]; summary?: string; negative_prompt?: string;
};
type TplDetail = TplItem & {
  prompt_template: string; variables: VarDef[];
  fidelity_anchors?: string[]; avoid?: string[];
};
type OptTpl = { key: string; name: string; description?: string; file?: string };

type Props = {
  open: boolean;
  onClose: () => void;
  /** 初始模板类型：art=画风（生图） / video=视频风格 */
  kind?: "art" | "video";
  /** 回写字段名（仅展示用） */
  targetField?: string;
  /** 字段当前值：作为「主体与动作」等主槽的初值 */
  initialText?: string;
  /** 项目统一画风（画风锁定），作为前缀约束 */
  styleHint?: string;
  onApply: (result: { prompt: string; negative_prompt: string; template_id: string; template_name: string }) => void;
};

export default function PromptAssembleDialog({
  open, onClose, kind = "art", targetField = "", initialText = "", styleHint = "", onApply,
}: Props) {
  const [tab, setTab] = useState<"art" | "video">(kind);
  const [keyword, setKeyword] = useState("");
  const [category, setCategory] = useState("");
  const [list, setList] = useState<TplItem[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [listError, setListError] = useState("");

  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<TplDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [values, setValues] = useState<Record<string, string>>({});
  const [extraSuffix, setExtraSuffix] = useState("");
  const [useStyleHint, setUseStyleHint] = useState(true);

  const [preview, setPreview] = useState("");
  const [negative, setNegative] = useState("");
  const [missing, setMissing] = useState<string[]>([]);
  const [renderLoading, setRenderLoading] = useState(false);

  const [optTemplates, setOptTemplates] = useState<OptTpl[]>([]);
  const [optKey, setOptKey] = useState("");
  const [optBusy, setOptBusy] = useState(false);
  const [optError, setOptError] = useState("");
  const [optApplied, setOptApplied] = useState(false);

  const debounceRef = useRef<any>(null);

  // 打开时重置为节点当前值
  useEffect(() => {
    if (!open) return;
    setTab(kind);
    setKeyword("");
    setCategory("");
    setSelectedId("");
    setDetail(null);
    setExtraSuffix("");
    setUseStyleHint(true);
    setPreview(initialText || "");
    setNegative("");
    setOptApplied(false);
    setOptError("");
    setValues({});
  }, [open, kind, initialText]);

  // 模板列表
  useEffect(() => {
    if (!open) return;
    setListLoading(true);
    setListError("");
    client.get("/api/style-templates", { params: { kind: tab, category, keyword } })
      .then((res) => {
        setList(res.data?.templates || []);
        setCategories(res.data?.categories || []);
      })
      .catch((e) => setListError(e?.response?.data?.detail || e?.message || "模板加载失败"))
      .finally(() => setListLoading(false));
  }, [open, tab, category, keyword]);

  // 优化模板列表
  useEffect(() => {
    if (!open) return;
    client.get("/api/style-templates/optimize-templates")
      .then((res) => {
        const items: OptTpl[] = res.data?.templates || [];
        setOptTemplates(items);
        setOptKey((prev) => prev || (tab === "video" ? "video" : "image"));
      })
      .catch(() => setOptTemplates([]));
  }, [open, tab]);

  // 模板详情
  useEffect(() => {
    if (!open || !selectedId) { setDetail(null); return; }
    setDetailLoading(true);
    client.get(`/api/style-templates/${tab}/${selectedId}`)
      .then((res) => {
        const d: TplDetail = res.data;
        setDetail(d);
        const init: Record<string, string> = {};
        (d.variables || []).forEach((v) => {
          init[v.key] = v.key === "subject" && initialText ? initialText : (v.default || "");
        });
        setValues(init);
        setNegative(d.negative_prompt || "");
      })
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false));
  }, [open, tab, selectedId, initialText]);

  // 渲染预览（防抖）
  useEffect(() => {
    if (!open || !detail) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setRenderLoading(true);
      client.post("/api/style-templates/assemble", {
        kind: tab,
        template_id: detail.id,
        values,
        style_prefix: useStyleHint ? (styleHint || "") : "",
        extra_suffix: extraSuffix,
      })
        .then((res) => {
          setPreview(res.data?.prompt || "");
          setMissing(res.data?.missing || []);
        })
        .catch(() => { })
        .finally(() => setRenderLoading(false));
    }, 250);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [open, tab, detail, values, extraSuffix, useStyleHint, styleHint]);

  const doOptimize = useCallback(() => {
    const text = (preview || "").trim();
    if (!text) { setOptError("请先填入或组装出待优化的提示词"); return; }
    setOptBusy(true);
    setOptError("");
    client.post("/api/style-templates/optimize", {
      kind: tab,
      text,
      template: optKey,
      style_hint: styleHint || "",
    })
      .then((res) => {
        const p = String(res.data?.prompt || "").trim();
        if (p) { setPreview(p); setOptApplied(true); }
      })
      .catch((e) => setOptError(e?.response?.data?.detail || e?.message || "LLM 优化失败"))
      .finally(() => setOptBusy(false));
  }, [preview, optKey, styleHint, tab]);

  const currentName = useMemo(
    () => list.find((t) => t.id === selectedId)?.name || detail?.name || "",
    [list, selectedId, detail]);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
      onPointerDown={(e) => e.stopPropagation()}>
      <div
        className="w-[96vw] h-[88vh] rounded-2xl border border-border/60 bg-background shadow-2xl flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}>

        {/* 顶栏 */}
        <div className="flex items-center gap-2 px-4 py-3 border-b border-border/50 bg-muted/30 flex-shrink-0">
          <Layers className="w-4 h-4 text-primary" />
          <span className="text-sm font-semibold">提示词组装</span>
          <div className="ml-2 flex items-center gap-1 rounded-lg bg-muted/60 p-0.5">
            <button type="button"
              onClick={() => { setTab("art"); setSelectedId(""); setOptKey("image"); }}
              className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors ${tab === "art" ? "bg-background shadow-sm text-foreground" : "text-muted-foreground hover:text-foreground/80"}`}>
              <span className="inline-flex items-center gap-1"><Palette className="w-3 h-3" />画风</span>
            </button>
            <button type="button"
              onClick={() => { setTab("video"); setSelectedId(""); setOptKey("video"); }}
              className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors ${tab === "video" ? "bg-background shadow-sm text-foreground" : "text-muted-foreground hover:text-foreground/80"}`}>
              <span className="inline-flex items-center gap-1"><Film className="w-3 h-3" />视频风格</span>
            </button>
          </div>
          {targetField && (
            <span className="text-[11px] text-muted-foreground">→ 写入字段：{targetField}</span>
          )}
          <div className="flex-1" />
          <button type="button" onClick={onClose}
            className="p-1.5 rounded-md hover:bg-muted text-muted-foreground" title="关闭">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex flex-1 min-h-0">
          {/* 左：模板列表 */}
          <div className="w-[280px] flex-shrink-0 border-r border-border/50 flex flex-col min-h-0">
            <div className="p-2 space-y-2 border-b border-border/40">
              <div className="relative">
                <Search className="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground/70" />
                <input
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  placeholder="搜索风格名称/标签"
                  className="w-full text-[11px] pl-7 pr-2 py-1.5 rounded-md border border-border/50 bg-background outline-none focus:border-primary/50"
                />
              </div>
              <div className="flex flex-wrap gap-1">
                <button type="button" onClick={() => setCategory("")}
                  className={`px-1.5 py-0.5 rounded text-[10px] border transition-colors ${category === "" ? "border-primary/50 bg-primary/10 text-primary" : "border-border/50 text-muted-foreground hover:text-foreground"}`}>
                  全部
                </button>
                {categories.map((c) => (
                  <button key={c} type="button" onClick={() => setCategory(c)}
                    className={`px-1.5 py-0.5 rounded text-[10px] border transition-colors ${category === c ? "border-primary/50 bg-primary/10 text-primary" : "border-border/50 text-muted-foreground hover:text-foreground"}`}>
                    {c}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
              {listLoading && (
                <div className="flex items-center justify-center py-6 text-muted-foreground">
                  <Loader2 className="w-4 h-4 animate-spin" />
                </div>
              )}
              {listError && (
                <div className="flex items-center gap-1.5 text-[11px] text-amber-600 px-1 py-2">
                  <AlertTriangle className="w-3.5 h-3.5" />{listError}
                </div>
              )}
              {!listLoading && !listError && list.length === 0 && (
                <div className="text-[11px] text-muted-foreground text-center py-6">没有匹配的模板</div>
              )}
              {list.map((t) => (
                <button key={t.id} type="button"
                  onClick={() => setSelectedId(t.id)}
                  className={`w-full text-left rounded-lg border px-2 py-1.5 transition-colors ${selectedId === t.id ? "border-primary/60 bg-primary/10" : "border-border/50 hover:border-primary/30 hover:bg-muted/40"}`}>
                  <div className="flex items-center gap-1.5">
                    <span className="text-[12px] font-medium truncate">{t.name}</span>
                    {t.category && <span className="text-[10px] text-muted-foreground flex-shrink-0">· {t.category}</span>}
                  </div>
                  {t.summary && <div className="text-[10px] text-muted-foreground line-clamp-2 mt-0.5">{t.summary}</div>}
                </button>
              ))}
            </div>
          </div>

          {/* 中：变量填槽 */}
          <div className="flex-1 min-w-0 border-r border-border/50 flex flex-col min-h-0">
            {!detail ? (
              <div className="flex-1 flex items-center justify-center text-[12px] text-muted-foreground">
                {detailLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : "从左侧选择一个风格模板"}
              </div>
            ) : (
              <div className="flex-1 overflow-y-auto p-3 space-y-2.5">
                <div>
                  <div className="text-[13px] font-semibold">{detail.name}</div>
                  <div className="text-[11px] text-muted-foreground mt-0.5">{detail.summary}</div>
                </div>
                {(detail.variables || []).map((v) => (
                  <div key={v.key}>
                    <label className="text-[11px] font-medium text-muted-foreground block mb-1">
                      {v.label}
                      {v.required && <span className="text-rose-500 ml-0.5">*</span>}
                    </label>
                    <input
                      value={values[v.key] ?? ""}
                      onChange={(e) => setValues((prev) => ({ ...prev, [v.key]: e.target.value }))}
                      placeholder={v.placeholder || ""}
                      className="w-full text-[11px] px-2 py-1.5 rounded-md border border-border/50 bg-background outline-none focus:border-primary/50"
                    />
                  </div>
                ))}
                <div>
                  <label className="text-[11px] font-medium text-muted-foreground block mb-1">追加后缀（可选）</label>
                  <input
                    value={extraSuffix}
                    onChange={(e) => setExtraSuffix(e.target.value)}
                    placeholder="拼在提示词末尾的自由文本"
                    className="w-full text-[11px] px-2 py-1.5 rounded-md border border-border/50 bg-background outline-none focus:border-primary/50"
                  />
                </div>
                {styleHint && (
                  <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                    <input type="checkbox" checked={useStyleHint}
                      onChange={(e) => setUseStyleHint(e.target.checked)}
                      className="w-3 h-3 rounded border-border/50 accent-primary" />
                    前置项目统一画风：{styleHint}
                  </label>
                )}
                {detail.fidelity_anchors?.length ? (
                  <div className="rounded-md border border-border/40 bg-muted/30 px-2 py-1.5">
                    <div className="text-[10px] text-muted-foreground mb-1">风格保真锚点</div>
                    <div className="flex flex-wrap gap-1">
                      {detail.fidelity_anchors.map((a) => (
                        <span key={a} className="text-[10px] px-1.5 py-0.5 rounded bg-background border border-border/50">{a}</span>
                      ))}
                    </div>
                  </div>
                ) : null}
                {detail.avoid?.length ? (
                  <div className="rounded-md border border-amber-500/20 bg-amber-500/5 px-2 py-1.5">
                    <div className="text-[10px] text-amber-600 dark:text-amber-400 mb-1">避免</div>
                    <div className="text-[10px] text-muted-foreground">{detail.avoid.join("、")}</div>
                  </div>
                ) : null}
              </div>
            )}
          </div>

          {/* 右：预览 + 优化 */}
          <div className="w-[38%] min-w-[300px] flex flex-col min-h-0">
            <div className="flex-1 overflow-y-auto p-3 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-medium text-muted-foreground">组装结果</span>
                {renderLoading && <Loader2 className="w-3 h-3 animate-spin text-muted-foreground" />}
              </div>
              {missing.length > 0 && (
                <div className="flex items-start gap-1.5 text-[10px] text-amber-600 dark:text-amber-400">
                  <AlertTriangle className="w-3 h-3 mt-0.5 flex-shrink-0" />
                  未填写：{missing.join("、")}
                </div>
              )}
              <textarea
                value={preview}
                onChange={(e) => { setPreview(e.target.value); setOptApplied(false); }}
                className="w-full h-[220px] text-[11px] leading-relaxed px-2 py-1.5 rounded-md border border-border/50 bg-muted/20 outline-none focus:border-primary/50 resize-none"
                placeholder="选择模板并填槽后自动生成，可在此直接编辑"
              />
              <div>
                <span className="text-[11px] font-medium text-muted-foreground">反向提示词</span>
                <textarea
                  value={negative}
                  onChange={(e) => setNegative(e.target.value)}
                  className="mt-1 w-full h-[72px] text-[11px] px-2 py-1.5 rounded-md border border-border/50 bg-muted/20 outline-none focus:border-primary/50 resize-none"
                  placeholder="随模板带出，可编辑"
                />
              </div>

              <div className="rounded-lg border border-border/50 p-2 space-y-2">
                <div className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
                  <Wand2 className="w-3.5 h-3.5" />LLM 提示词优化
                </div>
                <div className="flex items-center gap-1.5">
                  <select value={optKey} onChange={(e) => setOptKey(e.target.value)}
                    className="flex-1 text-[11px] px-1.5 py-1 rounded-md border border-border/50 bg-background outline-none">
                    {optTemplates.map((t) => (
                      <option key={t.key} value={t.key}>{t.name}{t.description ? ` — ${t.description.slice(0, 18)}` : ""}</option>
                    ))}
                  </select>
                  <button type="button" onClick={doOptimize} disabled={optBusy || !preview.trim()}
                    className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium text-primary bg-primary/10 border border-primary/30 hover:bg-primary/20 disabled:opacity-50 transition-colors">
                    {optBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
                    优化
                  </button>
                </div>
                {optError && <div className="text-[10px] text-amber-600 dark:text-amber-400">{optError}</div>}
                {optApplied && !optError && (
                  <div className="flex items-center gap-1 text-[10px] text-emerald-600 dark:text-emerald-400">
                    <Check className="w-3 h-3" />已用模板改写，结果可直接编辑
                  </div>
                )}
              </div>
            </div>

            <div className="flex items-center gap-2 px-3 py-2.5 border-t border-border/50 bg-muted/20 flex-shrink-0">
              <span className="text-[10px] text-muted-foreground truncate flex-1">
                {currentName ? `模板：${currentName}` : "未选择模板"}
              </span>
              <button type="button" onClick={onClose}
                className="px-3 py-1.5 rounded-md text-[11px] border border-border/50 text-muted-foreground hover:text-foreground transition-colors">
                取消</button>
              <button type="button"
                onClick={() => {
                  onApply({
                    prompt: preview.trim(),
                    negative_prompt: negative.trim(),
                    template_id: detail?.id || "",
                    template_name: currentName,
                  });
                  onClose();
                }}
                disabled={!preview.trim()}
                className="px-3 py-1.5 rounded-md text-[11px] font-medium text-white bg-primary hover:bg-primary/90 disabled:opacity-50 transition-colors">
                应用到节点
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body);
}

import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Activity, Brain, Database, Gauge, Layers, Loader2, Mic2, Plus, RefreshCcw,
  Repeat, RotateCcw, Save, SlidersHorizontal, Sparkles, Trash2, Wand2, Zap,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { PageBackground } from "@/components/shared/PageBackground";
import { PageHeader } from "@/components/shared/PageHeader";
import { useAlert } from "@/components/ui/AlertProvider";
import { llmApi, promptApi, VOICEFORGE_PROMPT_SCOPE, type PromptTemplate } from "@/api/llm";
import { settingsApi } from "@/api/settings";
import { voiceForgeApi } from "@/api/voiceforge";

/* ── 配音谷的 AI 能力（模型选择限定在配音谷，不含主流程步骤） ────────── */

const VF_LLM_STEPS = [
  { id: "voiceforge_script_analysis", name: "剧本角色分析", desc: "分析项目文本，产出摘要与角色档案", temperature: 0.3 },
  { id: "voiceforge_sentence_split", name: "AI 智能断句", desc: "按原文切分配音句子，只切分不改写", temperature: 0.1 },
  { id: "voiceforge_dialogue_extract", name: "对话提取", desc: "从原文提取角色与对白句", temperature: 0.2 },
  { id: "voiceforge_chapter_split", name: "章节分割", desc: "将原文规划为扁平章节", temperature: 0.2 },
  { id: "voiceforge_emotion_design", name: "情绪片段设计", desc: "为音色生成各情绪的朗读文本与指令", temperature: 0.4 },
  { id: "voiceforge_voice_params", name: "音色参数设计", desc: "按设计意图生成音色参数与试听文本", temperature: 0.2 },
] as const;

const CATEGORY_OPTIONS = ["文本处理", "角色", "情绪", "音色", "自定义"];

const EXPORT_FORMATS = [
  { value: "wav", label: "WAV（无损，体积大）" },
  { value: "mp3", label: "MP3（通用，体积小）" },
  { value: "flac", label: "FLAC（无损压缩）" },
];

type PresetDraft = {
  name: string;
  description: string;
  category: string;
  system_prompt: string;
  user_prompt: string;
};

const emptyDraft = (category = "自定义"): PresetDraft => ({
  name: "", description: "", category, system_prompt: "", user_prompt: "",
});

export function VoiceForgeSettingsPanel() {
  const navigate = useNavigate();
  const { alert: showAlert, confirm: showConfirm } = useAlert();

  /* ── 配置（统一走本项目全局设置 / 大模型路由器） ─────────────────── */
  const [cfgLoading, setCfgLoading] = useState(true);
  const [stepModels, setStepModels] = useState<Record<string, string>>({});
  const [temperatures, setTemperatures] = useState<Record<string, number>>({});
  const [defaultModel, setDefaultModel] = useState("");
  const [textCfg, setTextCfg] = useState({ source_limit: 100000, max_sentence_length: 200, chapter_max_chars: 3000 });
  const [exportCfg, setExportCfg] = useState({ format: "wav", gap_seconds: 0 });
  const [synthCfg, setSynthCfg] = useState({ concurrency: 3, retry_count: 2, retry_delay: 1.0 });

  const loadConfig = useCallback(async () => {
    setCfgLoading(true);
    try {
      const res = await settingsApi.getAll();
      const cfg = res.data.config || {};
      setStepModels(cfg.llm?.step_models || {});
      setDefaultModel(cfg.llm?.step_models?.default_model || "");
      const vfLlm = cfg.voiceforge?.llm || {};
      const nextTemp: Record<string, number> = {};
      for (const step of VF_LLM_STEPS) {
        const raw = vfLlm[step.id]?.temperature;
        nextTemp[step.id] = typeof raw === "number" ? raw : step.temperature;
      }
      setTemperatures(nextTemp);
      const vfText = cfg.voiceforge?.text || {};
      setTextCfg({
        source_limit: Number(vfText.source_limit) || 100000,
        max_sentence_length: Number(vfText.max_sentence_length) || 200,
        chapter_max_chars: Number(vfText.chapter_max_chars) || 3000,
      });
      const vfExport = cfg.voiceforge?.export || {};
      setExportCfg({
        format: EXPORT_FORMATS.some((f) => f.value === vfExport.format) ? vfExport.format : "wav",
        gap_seconds: Number(vfExport.gap_seconds) || 0,
      });
      const vfSynth = cfg.voiceforge?.synthesis || {};
      setSynthCfg({
        concurrency: Number(vfSynth.concurrency) || 3,
        retry_count: Number(vfSynth.retry_count) || 2,
        retry_delay: Number(vfSynth.retry_delay) || 1.0,
      });
    } catch {
      showAlert("读取配音谷配置失败", "error");
    } finally {
      setCfgLoading(false);
    }
  }, [showAlert]);

  useEffect(() => { void loadConfig(); }, [loadConfig]);

  /* ── 模型连通性测试 ─────────────────────────────────────────────── */
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, { ok: boolean; msg: string }>>({});

  const testStep = async (stepId: string) => {
    setTesting(stepId);
    try {
      const res = await llmApi.test(stepId);
      const ok = Boolean(res.data?.success);
      setTestResult((prev) => ({
        ...prev,
        [stepId]: { ok, msg: ok ? "连通成功" : String(res.data?.error || "连通失败").slice(0, 60) },
      }));
    } catch (err: any) {
      setTestResult((prev) => ({
        ...prev,
        [stepId]: { ok: false, msg: String(err?.response?.data?.detail || err?.message || "请求失败").slice(0, 60) },
      }));
    } finally {
      setTesting(null);
    }
  };

  const saveStepModel = (stepId: string, value: string) => {
    setStepModels((prev) => ({ ...prev, [stepId]: value }));
    void settingsApi.update(`llm.step_models.${stepId}`, value);
  };

  const saveTemperature = (stepId: string, value: number) => {
    const clamped = Math.min(2, Math.max(0, value));
    setTemperatures((prev) => ({ ...prev, [stepId]: clamped }));
    void settingsApi.update(`voiceforge.llm.${stepId}.temperature`, clamped);
  };

  /* ── Prompt 预设（scope 限定在配音谷） ───────────────────────────── */
  const [presets, setPresets] = useState<PromptTemplate[]>([]);
  const [presetLoading, setPresetLoading] = useState(true);

  const loadPresets = useCallback(async () => {
    setPresetLoading(true);
    try {
      const res = await promptApi.listTemplates(VOICEFORGE_PROMPT_SCOPE);
      setPresets(res.data.templates || []);
    } catch {
      showAlert("读取 Prompt 预设失败", "error");
    } finally {
      setPresetLoading(false);
    }
  }, [showAlert]);

  useEffect(() => { void loadPresets(); }, [loadPresets]);

  const groupedPresets = useMemo(() => {
    const groups = new Map<string, PromptTemplate[]>();
    for (const preset of presets) {
      const key = preset.category || "未分类";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(preset);
    }
    return Array.from(groups.entries());
  }, [presets]);

  /* ── 预设编辑弹窗 ───────────────────────────────────────────────── */
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<PresetDraft>(emptyDraft());
  const [saving, setSaving] = useState(false);

  const openEditor = (preset?: PromptTemplate) => {
    if (preset) {
      setEditingId(preset.id);
      setDraft({
        name: preset.name || "",
        description: preset.description || "",
        category: preset.category || "自定义",
        system_prompt: preset.system_prompt || "",
        user_prompt: preset.user_prompt || "",
      });
    } else {
      setEditingId(null);
      setDraft(emptyDraft());
    }
    setEditorOpen(true);
  };

  const savePreset = async () => {
    if (!draft.name.trim()) { showAlert("请填写预设名称", "warning"); return; }
    if (!draft.user_prompt.trim()) { showAlert("请填写 Prompt 内容", "warning"); return; }
    setSaving(true);
    try {
      if (editingId) {
        await promptApi.updateTemplate(editingId, draft);
      } else {
        await promptApi.createTemplate(draft);
      }
      showAlert(editingId ? "Prompt 预设已更新" : "Prompt 预设已创建", "success");
      setEditorOpen(false);
      await loadPresets();
    } catch (err: any) {
      showAlert(String(err?.response?.data?.detail || "保存失败"), "error");
    } finally {
      setSaving(false);
    }
  };

  const removePreset = async (preset: PromptTemplate) => {
    const ok = await showConfirm(`删除 Prompt 预设「${preset.name}」？相关 AI 能力将回退到内置默认 Prompt。`, {
      type: "warning", confirmLabel: "删除",
    });
    if (!ok) return;
    try {
      await promptApi.deleteTemplate(preset.id);
      showAlert("预设已删除", "success");
      await loadPresets();
    } catch (err: any) {
      showAlert(String(err?.response?.data?.detail || "删除失败"), "error");
    }
  };

  const resetPreset = async (preset: PromptTemplate) => {
    const ok = await showConfirm(`将「${preset.name}」恢复为内置默认内容？当前修改会丢失。`, {
      type: "warning", confirmLabel: "恢复默认",
    });
    if (!ok) return;
    try {
      await promptApi.resetTemplate(preset.id);
      showAlert("已恢复为内置默认", "success");
      await loadPresets();
    } catch (err: any) {
      showAlert(String(err?.response?.data?.detail || "恢复失败"), "error");
    }
  };

  /* ── 接口状态 ───────────────────────────────────────────────────── */
  const [health, setHealth] = useState<any>(null);
  const loadHealth = async () => {
    try { setHealth((await voiceForgeApi.health()).data); } catch { setHealth(null); }
  };
  useEffect(() => { void loadHealth(); }, []);

  /* ── 文本与导出配置写入 ─────────────────────────────────────────── */
  const patchText = (key: keyof typeof textCfg, value: number) => {
    setTextCfg((prev) => ({ ...prev, [key]: value }));
    void settingsApi.update(`voiceforge.text.${key}`, value);
  };
  const patchExportFormat = (value: string) => {
    setExportCfg((prev) => ({ ...prev, format: value }));
    void settingsApi.update("voiceforge.export.format", value);
  };
  const patchExportGap = (value: number) => {
    setExportCfg((prev) => ({ ...prev, gap_seconds: value }));
    void settingsApi.update("voiceforge.export.gap_seconds", value);
  };

  const patchSynth = (key: keyof typeof synthCfg, value: number) => {
    setSynthCfg((prev) => ({ ...prev, [key]: value }));
    void settingsApi.update(`voiceforge.synthesis.${key}`, value);
  };

  const modelSuggestions = useMemo(() => {
    const set = new Set<string>();
    if (defaultModel) set.add(defaultModel);
    for (const value of Object.values(stepModels)) if (value) set.add(value);
    return Array.from(set);
  }, [defaultModel, stepModels]);

  return (
    <PageBackground tone="voiceforge" className="mx-auto max-w-5xl space-y-6 p-1">
      <PageHeader
        icon={SlidersHorizontal}
        title="配音谷设置"
        detail="模型选择、Prompt 预设与合成导出参数，全部限定在晴沐配音谷内生效"
        breadcrumbs={[{ label: "晴沐配音谷", to: "/voiceforge" }, { label: "配音谷设置" }]}
        actions={
          <Button variant="outline" onClick={() => { void loadConfig(); void loadPresets(); void loadHealth(); }} disabled={cfgLoading}>
            <RefreshCcw className="mr-1.5 h-4 w-4" />刷新
          </Button>
        }
      />

      <p className="rounded-lg border border-border/60 bg-muted/30 p-3 text-xs text-muted-foreground">
        配音接口（TTS）与 LLM 接口的密钥、地址统一由本项目全局设置与大模型路由器管理，配音谷不再单独配置接口，只选择使用哪个模型。
      </p>

      <Tabs defaultValue="models">
        <TabsList className="flex flex-wrap h-auto gap-1">
          <TabsTrigger value="models" className="gap-1.5"><Brain className="h-3.5 w-3.5" />模型选择</TabsTrigger>
          <TabsTrigger value="prompts" className="gap-1.5"><Wand2 className="h-3.5 w-3.5" />Prompt 预设</TabsTrigger>
          <TabsTrigger value="text" className="gap-1.5"><Layers className="h-3.5 w-3.5" />文本与导出</TabsTrigger>
          <TabsTrigger value="status" className="gap-1.5"><Activity className="h-3.5 w-3.5" />接口状态</TabsTrigger>
        </TabsList>

        {/* ── 模型选择 ─────────────────────────────────────────── */}
        <TabsContent value="models" className="space-y-3 pt-4">
          <div className="rounded-xl border border-border/60 bg-card/60 p-4">
            <h3 className="text-sm font-semibold flex items-center gap-2">
              <Brain className="h-4 w-4 text-primary" />配音谷各 AI 能力的模型与温度
            </h3>
            <p className="mt-1 text-xs text-muted-foreground">
              留空表示继承默认模型（当前：{defaultModel || "未设置"}）。模型名称对应大模型路由器中的策略名或自定义模型名。
            </p>
          </div>

          {VF_LLM_STEPS.map((step) => {
            const state = testResult[step.id];
            return (
              <div key={step.id} className="rounded-xl border border-border/60 bg-card/60 p-4">
                <div className="flex flex-col gap-3 md:flex-row md:items-center">
                  <div className="md:w-52 shrink-0">
                    <div className="text-sm font-medium">{step.name}</div>
                    <div className="text-[11px] text-muted-foreground">{step.desc}</div>
                    <div className="mt-0.5 font-mono text-[11px] text-muted-foreground/70">{step.id}</div>
                  </div>

                  <div className="flex-1">
                    <label className="text-xs text-muted-foreground">模型</label>
                    <Input
                      className="mt-1"
                      list="vf-model-suggestions"
                      value={stepModels[step.id] || ""}
                      placeholder={defaultModel || step.id}
                      onChange={(e) => setStepModels((prev) => ({ ...prev, [step.id]: e.target.value }))}
                      onBlur={(e) => saveStepModel(step.id, e.target.value.trim())}
                    />
                  </div>

                  <div className="w-28 shrink-0">
                    <NumberField
                      label="温度"
                      value={temperatures[step.id] ?? step.temperature}
                      min={0}
                      max={2}
                      step={0.1}
                      onCommit={(v) => saveTemperature(step.id, v)}
                    />
                  </div>

                  <Button
                    variant="outline"
                    size="sm"
                    className="shrink-0"
                    disabled={testing === step.id}
                    onClick={() => void testStep(step.id)}
                  >
                    {testing === step.id ? (
                      <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Zap className="mr-1.5 h-3.5 w-3.5" />
                    )}
                    连通测试
                  </Button>
                </div>

                {state && (
                  <p className={`mt-2 text-xs ${state.ok ? "text-emerald-500" : "text-destructive"}`}>
                    {state.msg}
                  </p>
                )}
              </div>
            );
          })}

          <datalist id="vf-model-suggestions">
            {modelSuggestions.map((item) => <option key={item} value={item} />)}
          </datalist>

          <div className="flex justify-end">
            <Button variant="outline" onClick={() => navigate("/llm-router")}>
              <Sparkles className="mr-1.5 h-4 w-4" />前往大模型路由器
            </Button>
          </div>
        </TabsContent>

        {/* ── Prompt 预设 ──────────────────────────────────────── */}
        <TabsContent value="prompts" className="space-y-4 pt-4">
          <div className="flex items-center justify-between gap-3 rounded-xl border border-border/60 bg-card/60 p-4">
            <div>
              <h3 className="text-sm font-semibold flex items-center gap-2">
                <Wand2 className="h-4 w-4 text-primary" />配音谷 Prompt 预设
              </h3>
              <p className="mt-1 text-xs text-muted-foreground">
                仅作用于晴沐配音谷的 AI 能力；删除后对应能力自动回退到内置默认 Prompt。
              </p>
            </div>
            <Button size="sm" onClick={() => openEditor()}>
              <Plus className="mr-1.5 h-4 w-4" />新建预设
            </Button>
          </div>

          {presetLoading ? (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />加载中
            </div>
          ) : presets.length === 0 ? (
            <p className="py-10 text-center text-sm text-muted-foreground">暂无配音谷 Prompt 预设</p>
          ) : (
            groupedPresets.map(([category, items]) => (
              <section key={category} className="space-y-2">
                <div className="flex items-center gap-2">
                  <Badge variant="outline">{category}</Badge>
                  <span className="text-xs text-muted-foreground">{items.length} 条</span>
                </div>
                {items.map((preset) => (
                  <div key={preset.id} className="rounded-xl border border-border/60 bg-card/60 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium">{preset.name}</span>
                          <code className="font-mono text-[11px] text-muted-foreground">{preset.id}</code>
                        </div>
                        {preset.description && (
                          <p className="mt-1 text-xs text-muted-foreground">{preset.description}</p>
                        )}
                        <p className="mt-1.5 line-clamp-2 font-mono text-[11px] text-muted-foreground/80">
                          {preset.user_prompt.slice(0, 160)}
                          {preset.user_prompt.length > 160 ? "…" : ""}
                        </p>
                      </div>
                      <div className="flex shrink-0 gap-1.5">
                        <Button size="sm" variant="ghost" onClick={() => openEditor(preset)}>编辑</Button>
                        <Button size="sm" variant="ghost" onClick={() => void resetPreset(preset)} title="恢复内置默认">
                          <RotateCcw className="h-3.5 w-3.5" />
                        </Button>
                        <Button size="sm" variant="ghost" className="text-destructive" onClick={() => void removePreset(preset)}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </div>
                  </div>
                ))}
              </section>
            ))
          )}
        </TabsContent>

        {/* ── 文本与导出 ───────────────────────────────────────── */}
        <TabsContent value="text" className="space-y-3 pt-4">
          <div className="rounded-xl border border-border/60 bg-card/60 p-4 space-y-4">
            <h3 className="text-sm font-semibold flex items-center gap-2">
              <Layers className="h-4 w-4 text-primary" />AI 文本处理
            </h3>
            <div className="grid gap-4 md:grid-cols-3">
              <NumberField
                label="单次处理字符上限"
                hint="分句 / 对话提取 / 分章 / 剧本分析的文本上限"
                value={textCfg.source_limit}
                min={1000}
                max={1000000}
                onCommit={(v) => patchText("source_limit", v)}
              />
              <NumberField
                label="默认单句长度"
                hint="AI 智能断句的默认单句字符数"
                value={textCfg.max_sentence_length}
                min={20}
                max={2000}
                onCommit={(v) => patchText("max_sentence_length", v)}
              />
              <NumberField
                label="默认每章字数"
                hint="AI 章节分割的默认每章字数"
                value={textCfg.chapter_max_chars}
                min={200}
                max={100000}
                onCommit={(v) => patchText("chapter_max_chars", v)}
              />
            </div>
          </div>

          <div className="rounded-xl border border-border/60 bg-card/60 p-4 space-y-4">
            <h3 className="text-sm font-semibold flex items-center gap-2">
              <Gauge className="h-4 w-4 text-primary" />合成并发与自动重试
            </h3>
            <p className="text-xs text-muted-foreground">
              批量合成时同一时刻在途的句子数量上限，以及单句失败后自动重试的次数与间隔。合理的并发上限可以避免瞬时打满 TTS 接口被限流。
            </p>
            <div className="grid gap-4 md:grid-cols-3">
              <NumberField
                label="并发合成上限"
                hint="全局同时运行的句子合成任务数"
                value={synthCfg.concurrency}
                min={1}
                max={32}
                onCommit={(v) => patchSynth("concurrency", v)}
              />
              <NumberField
                label="自动重试次数"
                hint="单句失败后的重试次数（不含首次）"
                value={synthCfg.retry_count}
                min={0}
                max={5}
                onCommit={(v) => patchSynth("retry_count", v)}
              />
              <NumberField
                label="重试间隔（秒）"
                hint="每次重试前的等待时间"
                value={synthCfg.retry_delay}
                min={0}
                max={30}
                step={0.5}
                onCommit={(v) => patchSynth("retry_delay", v)}
              />
            </div>
          </div>

          <div className="rounded-xl border border-border/60 bg-card/60 p-4 space-y-4">
            <h3 className="text-sm font-semibold flex items-center gap-2">
              <Mic2 className="h-4 w-4 text-primary" />导出默认值
            </h3>
            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label className="text-xs text-muted-foreground">默认音频格式</label>
                <Select value={exportCfg.format} onValueChange={patchExportFormat}>
                  <SelectTrigger className="mt-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {EXPORT_FORMATS.map((item) => (
                      <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="mt-1 text-xs text-muted-foreground">合并导出音频时使用的默认格式</p>
              </div>
              <NumberField
                label="默认句间静音（秒）"
                hint="合并音频时每句之间插入的静音，0 表示不插入"
                value={exportCfg.gap_seconds}
                min={0}
                max={3}
                step={0.05}
                onCommit={patchExportGap}
              />
            </div>
          </div>
        </TabsContent>

        {/* ── 接口状态 ─────────────────────────────────────────── */}
        <TabsContent value="status" className="space-y-4 pt-4">
          <section className="grid gap-4 md:grid-cols-2">
            {[
              { label: "数据库", value: health?.database ? "已连接" : "检查中", icon: Database },
              { label: "任务队列", value: health?.queue_mode === "celery" ? "Celery 已启用" : "本地回退执行", icon: Activity },
              { label: "可用 TTS 接口", value: `${health?.tts_interfaces ?? 0} 个`, icon: Mic2 },
              { label: "LLM 服务", value: health?.llm_configured ? "已配置" : "未配置", icon: Brain },
            ].map((item) => (
              <div key={item.label} className="rounded-xl border border-border/60 bg-card p-5">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-muted-foreground">{item.label}</span>
                  <item.icon className="h-4 w-4 text-primary" />
                </div>
                <div className="mt-2 font-semibold">{item.value}</div>
              </div>
            ))}
          </section>

          <p className="rounded-lg border border-border/60 bg-muted/30 p-4 text-sm text-muted-foreground">
            配音接口与 LLM 接口由主应用的全局设置统一管理，请前往「设置 → 大模型」或使用大模型路由器配置平台、密钥与策略；配音谷只负责选择使用哪个模型。
          </p>

          <div className="flex gap-2">
            <Button variant="outline" onClick={() => navigate("/settings")}>
              <Database className="mr-1.5 h-4 w-4" />前往全局设置
            </Button>
            <Button variant="outline" onClick={() => navigate("/llm-router")}>
              <Sparkles className="mr-1.5 h-4 w-4" />前往大模型路由器
            </Button>
          </div>
        </TabsContent>
      </Tabs>

      {/* ── 预设编辑弹窗 ─────────────────────────────────────── */}
      <Dialog open={editorOpen} onOpenChange={setEditorOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{editingId ? "编辑 Prompt 预设" : "新建 Prompt 预设"}</DialogTitle>
            <DialogDescription>
              Prompt 中使用 {"{{ 占位符 }}"} 注入变量；未提供的占位符会渲染为空。
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <label className="text-xs text-muted-foreground">预设名称</label>
                <Input
                  className="mt-1"
                  value={draft.name}
                  onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                  placeholder="如：专业配音角色提取"
                />
              </div>
              <div>
                <label className="text-xs text-muted-foreground">分类</label>
                <Select value={draft.category} onValueChange={(v) => setDraft({ ...draft, category: v })}>
                  <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {CATEGORY_OPTIONS.map((item) => (
                      <SelectItem key={item} value={item}>{item}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div>
              <label className="text-xs text-muted-foreground">说明</label>
              <Input
                className="mt-1"
                value={draft.description}
                onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                placeholder="这条预设用于什么场景"
              />
            </div>

            <div>
              <label className="text-xs text-muted-foreground">System Prompt</label>
              <Textarea
                className="mt-1 min-h-24 font-mono text-xs"
                value={draft.system_prompt}
                onChange={(e) => setDraft({ ...draft, system_prompt: e.target.value })}
              />
            </div>

            <div>
              <label className="text-xs text-muted-foreground">Prompt 内容</label>
              <Textarea
                className="mt-1 min-h-40 font-mono text-xs"
                value={draft.user_prompt}
                onChange={(e) => setDraft({ ...draft, user_prompt: e.target.value })}
                placeholder="使用 {{ 占位符 }} 注入变量"
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setEditorOpen(false)}>取消</Button>
            <Button onClick={() => void savePreset()} disabled={saving}>
              {saving ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Save className="mr-1.5 h-4 w-4" />}
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageBackground>
  );
}

function NumberField({
  label, hint, value, min, max, step = 1, onCommit,
}: {
  label: string;
  hint?: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onCommit: (value: number) => void;
}) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => { setDraft(String(value)); }, [value]);

  const commit = () => {
    const parsed = Number(draft);
    if (!Number.isFinite(parsed)) { setDraft(String(value)); return; }
    const clamped = Math.min(max, Math.max(min, parsed));
    setDraft(String(clamped));
    if (clamped !== value) onCommit(clamped);
  };

  return (
    <div>
      <label className="text-xs text-muted-foreground">{label}</label>
      <Input
        className="mt-1"
        type="number"
        min={min}
        max={max}
        step={step}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
      />
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

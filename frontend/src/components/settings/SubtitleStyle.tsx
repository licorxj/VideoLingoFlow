import { useState, useEffect, useCallback, useMemo } from "react";
import { cn } from "@/lib/utils";
import client from "@/api/client";
import {
  Type,
  Palette,
  Maximize,
  MoveVertical,
  Italic,
  Bold,
  Underline,
  Strikethrough,
  Save,
  Trash2,
  Play,
  Video,
  Layers,
  SlidersHorizontal,
  AlignCenter,
  ChevronDown,
  Bookmark,
} from "lucide-react";

// ─── Types ───────────────────────────────────────────────────────────────────

interface StyleParams {
  fontName: string;
  fontSize: number;
  primaryColour: string;
  secondaryColour: string;
  outlineColour: string;
  backColour: string;
  bold: boolean;
  italic: boolean;
  underline: boolean;
  strikeout: boolean;
  scaleX: number;
  scaleY: number;
  spacing: number;
  angle: number;
  borderStyle: number;
  outline: number;
  shadow: number;
  alignment: number;
  marginL: number;
  marginR: number;
  marginV: number;
  encoding: number;
}

interface Preset {
  name: string;
  primary: StyleParams;
  secondary: StyleParams;
  dualSubtitleEnabled: boolean;
}

// ─── Constants ───────────────────────────────────────────────────────────────

const FONTS = [
  "Arial",
  "Microsoft YaHei",
  "SimHei",
  "SimSun",
  "KaiTi",
  "FangSong",
  "STSong",
  "Noto Sans CJK SC",
  "Source Han Sans CN",
  "PingFang SC",
];

const DEFAULT_STYLE: StyleParams = {
  fontName: "Arial",
  fontSize: 48,
  primaryColour: "&H00FFFFFF",
  secondaryColour: "&H00FFFFFF",
  outlineColour: "&H00000000",
  backColour: "&H00000000",
  bold: false,
  italic: false,
  underline: false,
  strikeout: false,
  scaleX: 100,
  scaleY: 100,
  spacing: 0,
  angle: 0,
  borderStyle: 1,
  outline: 2,
  shadow: 1,
  alignment: 2,
  marginL: 10,
  marginR: 10,
  marginV: 30,
  encoding: 1,
};

const ALIGN_GRID: { value: number; label: string }[][] = [
  [
    { value: 7, label: "左上" },
    { value: 8, label: "中上" },
    { value: 9, label: "右上" },
  ],
  [
    { value: 4, label: "左中" },
    { value: 5, label: "居中" },
    { value: 6, label: "右中" },
  ],
  [
    { value: 1, label: "左下" },
    { value: 2, label: "中下" },
    { value: 3, label: "右下" },
  ],
];

const EXAMPLES = [
  { value: "zh", label: "中文" },
  { value: "en", label: "English" },
  { value: "bilingual", label: "双语" },
];

// ─── Style class patterns ────────────────────────────────────────────────────

const inputCls =
  "w-full mt-2 px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none";
const labelCls =
  "text-xs font-medium text-muted-foreground uppercase tracking-wider";

// ─── Color helpers ───────────────────────────────────────────────────────────

/** Parse ASS color "&H{AA}{BB}{GG}{RR}" → { r, g, b, a(0-255) } */
function assToRgba(ass: string): { r: number; g: number; b: number; a: number } {
  const m = ass.match(/^&H([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})([0-9A-Fa-f]{2})$/);
  if (!m) return { r: 255, g: 255, b: 255, a: 0 };
  return {
    a: parseInt(m[1], 16),
    b: parseInt(m[2], 16),
    g: parseInt(m[3], 16),
    r: parseInt(m[4], 16),
  };
}

/** Convert { r, g, b, a } → ASS string */
function rgbaToAss(r: number, g: number, b: number, a: number): string {
  const hx = (n: number) => n.toString(16).padStart(2, "0").toUpperCase();
  return `&H${hx(a)}${hx(b)}${hx(g)}${hx(r)}`;
}

/** ASS color → hex "#RRGGBB" */
function assToHex(ass: string): string {
  const { r, g, b } = assToRgba(ass);
  return `#${[r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("").toUpperCase()}`;
}

/** Hex "#RRGGBB" + alpha(0-255) → ASS color */
function hexToAss(hex: string, alpha: number): string {
  const h = hex.replace("#", "");
  const r = parseInt(h.substring(0, 2), 16);
  const g = parseInt(h.substring(2, 4), 16);
  const b = parseInt(h.substring(4, 6), 16);
  return rgbaToAss(r, g, b, alpha);
}

// ─── Sub-components ──────────────────────────────────────────────────────────

/** Color picker with ASS alpha slider */
function ColorField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (ass: string) => void;
}) {
  const { r, g, b, a } = assToRgba(value);
  const hex = `#${[r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("")}`;

  const handleColorChange = (newHex: string) => {
    onChange(hexToAss(newHex, a));
  };
  const handleAlphaChange = (newAlpha: number) => {
    onChange(hexToAss(hex, newAlpha));
  };

  return (
    <div>
      <label className={labelCls}>{label}</label>
      <div className="flex items-center gap-2.5 mt-2">
        <input
          type="color"
          value={hex}
          onChange={(e) => handleColorChange(e.target.value)}
          className="w-10 h-10 border border-border/60 rounded-lg cursor-pointer flex-shrink-0"
        />
        <div className="flex-1 space-y-1.5">
          <input
            className="w-full px-3 py-1.5 border border-border/60 rounded-lg bg-background/50 text-xs font-mono focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none"
            value={value}
            readOnly
          />
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-muted-foreground w-8">透明</span>
            <input
              type="range"
              min={0}
              max={255}
              value={a}
              onChange={(e) => handleAlphaChange(+e.target.value)}
              className="flex-1 h-1.5 accent-primary"
            />
            <span className="text-[10px] text-muted-foreground w-6 text-right">{a}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

/** ASS alignment 3×3 grid */
function AlignmentGrid({
  value,
  onChange,
}: {
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <label className={labelCls}>对齐方式</label>
      <div className="grid grid-cols-3 gap-1.5 mt-2">
        {ALIGN_GRID.flat().map((cell) => (
          <button
            key={cell.value}
            type="button"
            onClick={() => onChange(cell.value)}
            className={cn(
              "py-2 rounded-lg border text-xs font-medium transition-all duration-200",
              value === cell.value
                ? "border-primary/50 bg-primary/10 text-primary"
                : "border-border/50 text-muted-foreground hover:border-border hover:text-foreground"
            )}
          >
            {cell.label}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Reusable style form for primary / secondary */
function StyleForm({
  prefix,
  style,
  onChange,
  fonts,
}: {
  prefix: string;
  style: StyleParams;
  onChange: (patch: Partial<StyleParams>) => void;
  fonts: string[];
}) {
  const set = <K extends keyof StyleParams>(key: K, val: StyleParams[K]) =>
    onChange({ [key]: val });

  return (
    <div className="space-y-4">
      {/* Font + Decoration */}
      <div className="rounded-2xl border border-border/50 bg-card/70 p-4 space-y-3">
        <h3 className="text-xs font-semibold flex items-center gap-1.5">
          <Type className="w-3.5 h-3.5 text-primary" />
          字体设置
        </h3>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>字体</label>
            <select
              className={inputCls + " appearance-none"}
              value={style.fontName}
              onChange={(e) => set("fontName", e.target.value)}
            >
              {fonts.map((f) => (
                <option key={f} value={f}>{f}</option>
              ))}
            </select>
          </div>
          <div>
            <label className={labelCls}>字号</label>
            <input type="number" className={inputCls} value={style.fontSize} min={1}
              onChange={(e) => set("fontSize", +e.target.value)} />
          </div>
        </div>
        <div className="grid grid-cols-4 gap-2">
          {([
            { key: "bold" as const, icon: Bold, label: "粗体" },
            { key: "italic" as const, icon: Italic, label: "斜体" },
            { key: "underline" as const, icon: Underline, label: "下划线" },
            { key: "strikeout" as const, icon: Strikethrough, label: "删除线" },
          ] as const).map((item) => {
            const Icon = item.icon;
            const active = style[item.key];
            return (
              <button key={item.key} type="button" onClick={() => set(item.key, !active)}
                className={cn(
                  "flex items-center justify-center gap-1 py-1.5 rounded-lg border text-[11px] font-medium transition-all duration-200",
                  active ? "border-primary/50 bg-primary/10 text-primary" : "border-border/50 text-muted-foreground hover:border-border hover:text-foreground"
                )}>
                <Icon className="w-3.5 h-3.5" />{item.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Colors + Border & Shadow */}
      <div className="rounded-2xl border border-border/50 bg-card/70 p-4 space-y-3">
        <h3 className="text-xs font-semibold flex items-center gap-1.5">
          <Palette className="w-3.5 h-3.5 text-primary" />
          颜色与边框
        </h3>
        <div className="grid grid-cols-2 gap-3">
          <ColorField label="主颜色" value={style.primaryColour} onChange={(v) => set("primaryColour", v)} />
          <ColorField label="次要颜色" value={style.secondaryColour} onChange={(v) => set("secondaryColour", v)} />
          <ColorField label="边框颜色" value={style.outlineColour} onChange={(v) => set("outlineColour", v)} />
          <ColorField label="背景颜色" value={style.backColour} onChange={(v) => set("backColour", v)} />
        </div>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className={labelCls}>边框样式</label>
            <select className={inputCls + " appearance-none"} value={style.borderStyle}
              onChange={(e) => set("borderStyle", +e.target.value)}>
              <option value={1}>轮廓 + 阴影</option>
              <option value={3}>不透明底框</option>
            </select>
          </div>
          <div>
            <label className={labelCls}>描边宽度</label>
            <input type="number" className={inputCls} value={style.outline} step={0.5} min={0}
              onChange={(e) => set("outline", +e.target.value)} />
          </div>
          <div>
            <label className={labelCls}>阴影深度</label>
            <input type="number" className={inputCls} value={style.shadow} step={0.5} min={0}
              onChange={(e) => set("shadow", +e.target.value)} />
          </div>
        </div>
      </div>

      {/* Position + Transform */}
      <div className="rounded-2xl border border-border/50 bg-card/70 p-4 space-y-3">
        <h3 className="text-xs font-semibold flex items-center gap-1.5">
          <MoveVertical className="w-3.5 h-3.5 text-primary" />
          位置与变换
        </h3>
        <div className="grid grid-cols-2 gap-3">
          <AlignmentGrid value={style.alignment} onChange={(v) => set("alignment", v)} />
          <div className="space-y-2">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className={labelCls}>水平缩放%</label>
                <input type="number" className={inputCls} value={style.scaleX} step={1} min={1} max={1000}
                  onChange={(e) => set("scaleX", +e.target.value)} />
              </div>
              <div>
                <label className={labelCls}>垂直缩放%</label>
                <input type="number" className={inputCls} value={style.scaleY} step={1} min={1} max={1000}
                  onChange={(e) => set("scaleY", +e.target.value)} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className={labelCls}>字间距</label>
                <input type="number" className={inputCls} value={style.spacing} step={0.1} min={-10} max={50}
                  onChange={(e) => set("spacing", +e.target.value)} />
              </div>
              <div>
                <label className={labelCls}>旋转°</label>
                <input type="number" className={inputCls} value={style.angle} step={0.1} min={-360} max={360}
                  onChange={(e) => set("angle", +e.target.value)} />
              </div>
            </div>
          </div>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className={labelCls}>左边距</label>
            <input type="number" className={inputCls} value={style.marginL} min={0}
              onChange={(e) => set("marginL", +e.target.value)} />
          </div>
          <div>
            <label className={labelCls}>右边距</label>
            <input type="number" className={inputCls} value={style.marginR} min={0}
              onChange={(e) => set("marginR", +e.target.value)} />
          </div>
          <div>
            <label className={labelCls}>垂直边距</label>
            <input type="number" className={inputCls} value={style.marginV} min={0}
              onChange={(e) => set("marginV", +e.target.value)} />
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Main component ──────────────────────────────────────────────────────────

export default function SubtitleStyle() {
  // ── Style state ──
  const [primary, setPrimary] = useState<StyleParams>({ ...DEFAULT_STYLE });
  const [secondary, setSecondary] = useState<StyleParams>({ ...DEFAULT_STYLE });
  const [dualEnabled, setDualEnabled] = useState(false);

  // ── Preset state ──
  const [presets, setPresets] = useState<Preset[]>([]);
  const [selectedPreset, setSelectedPreset] = useState("");
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [newPresetName, setNewPresetName] = useState("");

  // ── System fonts ──
  const [systemFonts, setSystemFonts] = useState<string[]>([]);

  // ── Preview state ──
  const [videoUrl, setVideoUrl] = useState("");
  const [previewExample, setPreviewExample] = useState("bilingual");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [prepareLoading, setPrepareLoading] = useState(false);

  // ── Config state ──
  const [defaultPreset, setDefaultPreset] = useState("");
  const [primaryOnTop, setPrimaryOnTop] = useState(false);

  // ── Load presets + config ──
  const fetchPresets = useCallback(async () => {
    try {
      const res = await client.get("/api/subtitle-presets");
      setPresets(res.data ?? []);
    } catch {
      setPresets([]);
    }
  }, []);

  const fetchConfig = useCallback(async () => {
    try {
      const res = await client.get("/api/settings");
      const cfg = res.data?.config?.subtitle || {};
      setDefaultPreset(cfg.default_preset || "");
      setPrimaryOnTop(!!cfg.primary_on_top);
      // 如果有默认预设，自动加载
      if (cfg.default_preset) {
        setSelectedPreset(cfg.default_preset);
        const pRes = await client.get(`/api/subtitle-presets/${encodeURIComponent(cfg.default_preset)}`);
        const data = pRes.data;
        if (data.primary) setPrimary(data.primary);
        if (data.secondary) setSecondary(data.secondary);
        if (data.dualSubtitleEnabled !== undefined) setDualEnabled(data.dualSubtitleEnabled);
      }
    } catch { /* ignore */ }
  }, []);

  const fetchFonts = useCallback(async () => {
    try {
      const res = await client.get("/api/subtitle-presets/fonts");
      setSystemFonts(res.data ?? []);
    } catch {
      setSystemFonts([]);
    }
  }, []);

  // 合并默认字体与系统字体，去重后排序
  const allFonts = useMemo(() => {
    const merged = new Set<string>([...FONTS, ...systemFonts]);
    return Array.from(merged);
  }, [systemFonts]);

  useEffect(() => {
    fetchPresets();
    fetchConfig();
    fetchFonts();
  }, [fetchPresets, fetchConfig, fetchFonts]);

  // ── Config actions ──
  const handleSetDefaultPreset = async () => {
    if (!selectedPreset) return;
    try {
      await client.put("/api/settings", { key: "subtitle.default_preset", value: selectedPreset });
      setDefaultPreset(selectedPreset);
    } catch { /* ignore */ }
  };

  const handleTogglePrimaryOnTop = async () => {
    const newVal = !primaryOnTop;
    setPrimaryOnTop(newVal);
    try {
      await client.put("/api/settings", { key: "subtitle.primary_on_top", value: newVal });
    } catch { /* ignore */ }
  };

  // ── Preset actions ──
  const handleSavePreset = async () => {
    const name = newPresetName.trim();
    if (!name) return;

    const payload = {
      name,
      primary,
      secondary,
      dualSubtitleEnabled: dualEnabled,
    };
    const exists = presets.some((p) => p.name === name);

    try {
      if (exists) {
        await client.put(`/api/subtitle-presets/${encodeURIComponent(name)}`, payload);
      } else {
        await client.post("/api/subtitle-presets", payload);
      }
      setSaveDialogOpen(false);
      setNewPresetName("");
      fetchPresets();
      setSelectedPreset(name);
    } catch {
      // silently ignore
    }
  };

  const handleLoadPreset = async (name: string) => {
    if (!name) return;
    setSelectedPreset(name);
    try {
      const res = await client.get(`/api/subtitle-presets/${encodeURIComponent(name)}`);
      const data: Preset = res.data;
      if (data.primary) setPrimary(data.primary);
      if (data.secondary) setSecondary(data.secondary);
      if (data.dualSubtitleEnabled !== undefined) setDualEnabled(data.dualSubtitleEnabled);
    } catch {
      // silently ignore
    }
  };

  const handleDeletePreset = async () => {
    if (!selectedPreset) return;
    try {
      await client.delete(`/api/subtitle-presets/${encodeURIComponent(selectedPreset)}`);
      setSelectedPreset("");
      fetchPresets();
    } catch {
      // silently ignore
    }
  };

  // ── Preview actions ──
  const handlePreparePreview = async () => {
    setPrepareLoading(true);
    try {
      const res = await client.get("/api/subtitle-preview/prepare");
      if (res.data?.videoUrl) {
        setVideoUrl(res.data.videoUrl + "?t=" + Date.now());
      }
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.message || "加载预览资源失败";
      alert("加载失败: " + msg);
    } finally {
      setPrepareLoading(false);
    }
  };

  const handleGeneratePreview = async () => {
    setPreviewLoading(true);
    try {
      const res = await client.post("/api/subtitle-preview/generate", {
        example: previewExample,
        primary,
        secondary,
        dualSubtitleEnabled: dualEnabled,
        primaryOnTop: primaryOnTop,
      });
      if (res.data?.videoUrl) {
        // 添加时间戳避免浏览器缓存
        setVideoUrl(res.data.videoUrl + "?t=" + Date.now());
      }
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.message || "预览生成失败";
      alert("预览生成失败: " + msg);
    } finally {
      setPreviewLoading(false);
    }
  };

  // ── Render ──
  return (
    <div className="space-y-5 stagger-children">
      {/* ═══ 1. Preset Management Bar ═══ */}
      <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Save className="w-4 h-4 text-primary" />
          预设管理
        </h3>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => {
              setNewPresetName(selectedPreset);
              setSaveDialogOpen(true);
            }}
            className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl bg-primary/10 text-primary text-sm font-medium hover:bg-primary/15 transition-colors duration-200"
          >
            <Save className="w-3.5 h-3.5" />
            保存预设
          </button>
          <div className="relative flex-1 max-w-xs">
            <select
              className={cn(inputCls + " appearance-none pr-8", !selectedPreset && "text-muted-foreground")}
              value={selectedPreset}
              onChange={(e) => handleLoadPreset(e.target.value)}
            >
              <option value="">选择预设...</option>
              {presets.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name}
                </option>
              ))}
            </select>
            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 mt-1 w-4 h-4 text-muted-foreground pointer-events-none" />
          </div>
          {selectedPreset && (
            <button
              type="button"
              onClick={handleDeletePreset}
              className="p-2.5 rounded-xl border border-destructive/30 text-destructive hover:bg-destructive/10 transition-colors duration-200"
              title="删除预设"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          )}
          {selectedPreset && (
            <button
              type="button"
              onClick={handleSetDefaultPreset}
              className={cn(
                "flex items-center gap-1.5 px-3 py-2.5 rounded-xl border text-xs font-medium transition-colors duration-200",
                defaultPreset === selectedPreset
                  ? "border-primary/50 bg-primary/10 text-primary"
                  : "border-border/60 text-muted-foreground hover:bg-muted/50"
              )}
              title="设为默认预设"
            >
              <Bookmark className="w-3.5 h-3.5" />
              {defaultPreset === selectedPreset ? "已默认" : "设为默认"}
            </button>
          )}
          <div className="ml-auto flex items-center gap-2">
            <span className="text-xs text-muted-foreground">译文角色</span>
            <button
              type="button"
              onClick={handleTogglePrimaryOnTop}
              className={cn(
                "relative px-3 py-1.5 rounded-lg border text-xs font-medium transition-all duration-200",
                primaryOnTop
                  ? "border-primary/50 bg-primary/10 text-primary"
                  : "border-border/60 text-muted-foreground hover:bg-muted/50"
              )}
              title={primaryOnTop ? "译文使用主字幕样式(Default)" : "译文使用副字幕样式(Secondary)"}
            >
              {primaryOnTop ? "主字幕" : "副字幕"}
            </button>
          </div>
        </div>
      </div>

      {/* Save preset dialog (inline overlay) */}
      {saveDialogOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="bg-card border border-border/50 rounded-2xl p-6 w-full max-w-sm space-y-4 shadow-xl">
            <h3 className="text-base font-semibold">保存字幕预设</h3>
            <div className="space-y-3">
              <div className="relative">
                <label className={labelCls}>覆盖已有预设</label>
                <select
                  className={cn(inputCls + " appearance-none pr-8", !newPresetName && "text-muted-foreground")}
                  value={presets.some((p) => p.name === newPresetName) ? newPresetName : ""}
                  onChange={(e) => setNewPresetName(e.target.value)}
                >
                  <option value="">选择已有预设覆盖...</option>
                  {presets.map((p) => (
                    <option key={p.name} value={p.name}>
                      {p.name}
                    </option>
                  ))}
                </select>
                <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 mt-3 w-4 h-4 text-muted-foreground pointer-events-none" />
              </div>
              <div>
                <label className={labelCls}>预设名称</label>
                <input
                  type="text"
                  className={inputCls}
                  placeholder="输入新预设名称或覆盖上方已有预设..."
                  value={newPresetName}
                  onChange={(e) => setNewPresetName(e.target.value)}
                  autoFocus
                  onKeyDown={(e) => e.key === "Enter" && handleSavePreset()}
                />
              </div>
              {presets.some((p) => p.name === newPresetName.trim()) && (
                <p className="text-xs text-amber-500">该名称已存在，保存将覆盖原预设。</p>
              )}
            </div>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setSaveDialogOpen(false);
                  setNewPresetName("");
                }}
                className="px-4 py-2 rounded-xl text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                取消
              </button>
              <button
                type="button"
                onClick={handleSavePreset}
                disabled={!newPresetName.trim()}
                className="px-4 py-2 rounded-xl bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50"
              >
                保存
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ═══ 2. Primary Subtitle Style ═══ */}
      <div>
        <h2 className="text-sm font-bold mb-3 flex items-center gap-2">
          <AlignCenter className="w-4 h-4 text-primary" />
          主字幕样式
        </h2>
        <StyleForm
          prefix="primary"
          style={primary}
          onChange={(patch) => setPrimary((prev) => ({ ...prev, ...patch }))}
          fonts={allFonts}
        />
      </div>

      {/* ═══ 3. Dual Subtitle Toggle ═══ */}
      <div className="rounded-2xl border border-border/50 bg-card/70 p-5">
        <label className="flex items-center gap-3 cursor-pointer group">
          <div className="relative">
            <input
              type="checkbox"
              checked={dualEnabled}
              onChange={(e) => setDualEnabled(e.target.checked)}
              className="peer sr-only"
            />
            <div className="w-9 h-5 bg-muted rounded-full peer-checked:bg-primary transition-colors duration-200" />
            <div className="absolute left-0.5 top-0.5 w-4 h-4 bg-background rounded-full shadow-sm peer-checked:translate-x-4 transition-transform duration-200" />
          </div>
          <div>
            <span className="text-sm font-medium group-hover:text-foreground transition-colors">
              双字幕分别设置
            </span>
            <p className="text-xs text-muted-foreground mt-0.5">
              为第二字幕轨独立配置样式参数
            </p>
          </div>
        </label>
      </div>

      {/* ═══ 4. Secondary Subtitle Style (conditional) ═══ */}
      {dualEnabled && (
        <div>
          <h2 className="text-sm font-bold mb-3 flex items-center gap-2">
            <Layers className="w-4 h-4 text-primary" />
            副字幕样式
          </h2>
          <StyleForm
            prefix="secondary"
            style={secondary}
            onChange={(patch) => setSecondary((prev) => ({ ...prev, ...patch }))}
            fonts={allFonts}
          />
        </div>
      )}

      {/* ═══ 5. Preview Area ═══ */}
      <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Video className="w-4 h-4 text-primary" />
          效果预览
        </h3>

        {/* Video player */}
        <div className="aspect-video w-full rounded-xl bg-black/80 overflow-hidden flex items-center justify-center">
          {videoUrl ? (
            <video
              key={videoUrl}
              src={videoUrl}
              controls
              className="w-full h-full object-contain"
            />
          ) : (
            <span className="text-muted-foreground text-sm">
              点击下方按钮加载预览视频
            </span>
          )}
        </div>

        {/* Controls */}
        <div className="flex items-center gap-3 flex-wrap">
          <button
            type="button"
            onClick={handlePreparePreview}
            disabled={prepareLoading}
            className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl border border-border/60 text-sm font-medium hover:bg-muted/50 transition-colors duration-200 disabled:opacity-50"
          >
            <Video className="w-3.5 h-3.5" />
            {prepareLoading ? "加载中..." : "加载预览视频"}
          </button>

          <div className="relative">
            <select
              className={cn(inputCls + " appearance-none pr-8")}
              value={previewExample}
              onChange={(e) => setPreviewExample(e.target.value)}
            >
              {EXAMPLES.map((ex) => (
                <option key={ex.value} value={ex.value}>
                  {ex.label}
                </option>
              ))}
            </select>
            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 mt-1 w-4 h-4 text-muted-foreground pointer-events-none" />
          </div>

          <button
            type="button"
            onClick={handleGeneratePreview}
            disabled={previewLoading}
            className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50"
          >
            <Play className="w-3.5 h-3.5" />
            {previewLoading ? "生成中..." : "预览"}
          </button>
        </div>
      </div>
    </div>
  );
}

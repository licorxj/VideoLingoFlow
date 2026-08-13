import { useState, useEffect } from "react";
import { cn } from "@/lib/utils";
import {
  Palette,
  Sun,
  Moon,
  Monitor,
  Type,
  PanelLeftClose,
  PanelLeft,
  Sparkles,
  Languages,
  Home,
  Layers,
  History,
} from "lucide-react";

type Theme = "light" | "dark" | "system";
type FontScale = "small" | "medium" | "large";
type FontFamily = "default" | "serif" | "mono";

const FONT_SCALES: { id: FontScale; label: string; value: string }[] = [
  { id: "small", label: "小 (14px)", value: "14px" },
  { id: "medium", label: "中 (15px)", value: "15px" },
  { id: "large", label: "大 (16px)", value: "16px" },
];

const FONT_FAMILIES: { id: FontFamily; label: string; value: string }[] = [
  { id: "default", label: "Plus Jakarta Sans", value: "\"Plus Jakarta Sans\", system-ui, sans-serif" },
  { id: "serif", label: "Noto Serif", value: "\"Noto Serif\", Georgia, serif" },
  { id: "mono", label: "JetBrains Mono", value: "\"JetBrains Mono\", \"Fira Code\", monospace" },
];

const DEFAULT_PAGES = [
  { id: "/", label: "工作流编排", icon: Home },
  { id: "/batch", label: "批量工作台", icon: Layers },
  { id: "/history", label: "历史项目", icon: History },
];

function loadLocal<T>(key: string, fallback: T): T {
  try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; }
  catch { return fallback; }
}
function saveLocal(key: string, val: any) {
  localStorage.setItem(key, JSON.stringify(val));
}

export default function UISettings() {
  const [theme, setTheme] = useState<Theme>("system");
  const [fontScale, setFontScale] = useState<FontScale>("medium");
  const [fontFamily, setFontFamily] = useState<FontFamily>("default");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [reduceMotion, setReduceMotion] = useState(false);
  const [showMeshGradient, setShowMeshGradient] = useState(true);
  const [defaultPage, setDefaultPage] = useState("/");
  const [interfaceLang, setInterfaceLang] = useState("zh");

  useEffect(() => {
    setTheme(loadLocal("vl_theme", "system"));
    setFontScale(loadLocal("vl_font_scale", "medium"));
    setFontFamily(loadLocal("vl_font_family", "default"));
    setSidebarCollapsed(loadLocal("vl_sidebar_collapsed", false));
    setReduceMotion(loadLocal("vl_reduce_motion", false));
    setShowMeshGradient(loadLocal("vl_mesh_gradient", true));
    setDefaultPage(loadLocal("vl_default_page", "/"));
    setInterfaceLang(loadLocal("vl_interface_lang", "zh"));
  }, []);

  const emit = (key: string, val: any) => {
    window.dispatchEvent(new CustomEvent("vl-ui-change", { detail: { key, val } }));
  };

  const applyTheme = (t: Theme) => {
    setTheme(t);
    saveLocal("vl_theme", t);
    const root = document.documentElement;
    root.classList.remove("light", "dark");
    if (t === "system") {
      root.classList.add(window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    } else {
      root.classList.add(t);
    }
  };

  const applyFontScale = (s: FontScale) => {
    setFontScale(s);
    saveLocal("vl_font_scale", s);
    const px = FONT_SCALES.find((f) => f.id === s)?.value || "15px";
    document.documentElement.style.fontSize = px;
  };

  const applyFontFamily = (f: FontFamily) => {
    setFontFamily(f);
    saveLocal("vl_font_family", f);
    const val = FONT_FAMILIES.find((ff) => ff.id === f)?.value || "";
    document.body.style.fontFamily = val;
  };

  const applyReduceMotion = (v: boolean) => {
    setReduceMotion(v);
    saveLocal("vl_reduce_motion", v);
    document.documentElement.style.setProperty(
      "--animation-duration",
      v ? "0s" : ""
    );
  };

  const applyMeshGradient = (v: boolean) => {
    setShowMeshGradient(v);
    saveLocal("vl_mesh_gradient", v);
    document.querySelector(".gradient-mesh")?.classList.toggle("no-mesh", !v);
  };

  const applySidebarCollapsed = (v: boolean) => {
    setSidebarCollapsed(v);
    saveLocal("vl_sidebar_collapsed", v);
    emit("sidebar_collapsed", v);
  };

  const applyDefaultPage = (p: string) => {
    setDefaultPage(p);
    saveLocal("vl_default_page", p);
  };

  const applyInterfaceLang = (l: string) => {
    setInterfaceLang(l);
    saveLocal("vl_interface_lang", l);
  };

  const ToggleRow = ({
    icon: Icon,
    title,
    desc,
    checked,
    onChange,
  }: {
    icon: any;
    title: string;
    desc: string;
    checked: boolean;
    onChange: (v: boolean) => void;
  }) => (
    <div className="flex items-center justify-between py-1">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0">
          <Icon className="w-4 h-4 text-primary" />
        </div>
        <div>
          <h3 className="text-sm font-medium">{title}</h3>
          <p className="text-xs text-muted-foreground">{desc}</p>
        </div>
      </div>
      <label className="relative cursor-pointer flex-shrink-0">
        <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="peer sr-only" />
        <div className="w-9 h-5 bg-muted rounded-full peer-checked:bg-primary transition-colors duration-200" />
        <div className="absolute left-0.5 top-0.5 w-4 h-4 bg-background rounded-full shadow-sm peer-checked:translate-x-4 transition-transform duration-200" />
      </label>
    </div>
  );

  return (
    <div className="space-y-5 stagger-children">

      {/* Theme */}
      <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Palette className="w-4 h-4 text-primary" />
          "主题与外观"
        </h3>
        <div>
          <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
            "主题模式"
          </label>
          <div className="grid grid-cols-3 gap-2 mt-2">
            {([
              { id: "light" as Theme, icon: Sun, label: "亮色" },
              { id: "dark" as Theme, icon: Moon, label: "暗色" },
              { id: "system" as Theme, icon: Monitor, label: "系统" },
            ]).map((t) => {
              const Icon = t.icon;
              const active = theme === t.id;
              return (
                <button
                  key={t.id}
                  onClick={() => applyTheme(t.id)}
                  className={cn(
                    "flex items-center justify-center gap-2 py-2.5 rounded-xl border text-sm font-medium transition-all duration-200",
                    active
                      ? "border-primary/50 bg-primary/8 text-primary"
                      : "border-border/50 text-muted-foreground hover:border-border hover:text-foreground"
                  )}
                >
                  <Icon className="w-4 h-4" />
                  {t.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Font Size */}
        <div>
          <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
            "字体大小"
          </label>
          <div className="grid grid-cols-3 gap-2 mt-2">
            {FONT_SCALES.map((fs) => (
              <button
                key={fs.id}
                onClick={() => applyFontScale(fs.id)}
                className={cn(
                  "py-2.5 rounded-xl border text-sm font-medium transition-all duration-200",
                  fontScale === fs.id
                    ? "border-primary/50 bg-primary/8 text-primary"
                    : "border-border/50 text-muted-foreground hover:border-border hover:text-foreground"
                )}
              >
                {fs.label}
              </button>
            ))}
          </div>
        </div>

        {/* Font Family */}
        <div>
          <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
            <Type className="w-3 h-3" />
            "字体样式"
          </label>
          <div className="grid grid-cols-3 gap-2 mt-2">
            {FONT_FAMILIES.map((ff) => (
              <button
                key={ff.id}
                onClick={() => applyFontFamily(ff.id)}
                className={cn(
                  "py-2.5 rounded-xl border text-sm font-medium transition-all duration-200",
                  fontFamily === ff.id
                    ? "border-primary/50 bg-primary/8 text-primary"
                    : "border-border/50 text-muted-foreground hover:border-border hover:text-foreground"
                )}
                style={{ fontFamily: ff.value }}
              >
                {ff.label}
              </button>
            ))}
          </div>
        </div>

        {/* Interface Lang */}
        <div>
          <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
            <Languages className="w-3 h-3" />
            "界面语言"
          </label>
          <select
            className="w-full mt-2 px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none appearance-none"
            value={interfaceLang}
            onChange={(e) => applyInterfaceLang(e.target.value)}
          >
            <option value="zh">中文</option>
            <option value="en">English</option>
          </select>
        </div>
      </div>

      {/* Layout */}
      <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Type className="w-4 h-4 text-primary" />
          "布局设置"
        </h3>

        <ToggleRow
          icon={sidebarCollapsed ? PanelLeftClose : PanelLeft}
          title="侧栏压缩"
          desc="收起侧栏以获取更多内容区域"
          checked={sidebarCollapsed}
          onChange={applySidebarCollapsed}
        />

        <ToggleRow
          icon={Sparkles}
          title="渐变背景"
          desc="开启渐变色底景装饰，关闭可获取更平凉的界面"
          checked={showMeshGradient}
          onChange={applyMeshGradient}
        />

        <ToggleRow
          icon={Sparkles}
          title="减少动画"
          desc="关闭过渡动画和微交互效果，降低 GPU 负载"
          checked={reduceMotion}
          onChange={applyReduceMotion}
        />
      </div>

      {/* Default page */}
      <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Home className="w-4 h-4 text-primary" />
          "默认页面"
        </h3>
        <p className="text-xs text-muted-foreground">
          "启动应用时自动跳转到的页面"
        </p>
        <div className="grid grid-cols-3 gap-2">
          {DEFAULT_PAGES.map((p) => {
            const Icon = p.icon;
            const active = defaultPage === p.id;
            return (
              <button
                key={p.id}
                onClick={() => applyDefaultPage(p.id)}
                className={cn(
                  "flex items-center justify-center gap-2 py-2.5 rounded-xl border text-sm font-medium transition-all duration-200",
                  active
                    ? "border-primary/50 bg-primary/8 text-primary"
                    : "border-border/50 text-muted-foreground hover:border-border hover:text-foreground"
                )}
              >
                <Icon className="w-4 h-4" />
                {p.label}
              </button>
            );
          })}
        </div>
      </div>

    </div>
  );
}

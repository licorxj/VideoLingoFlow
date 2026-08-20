import { useState } from "react";
import { cn } from "@/lib/utils";
import { PageHeader } from "@/components/shared/PageHeader";
import { PageBackground } from "@/components/shared/PageBackground";
import LLMSettings from "@/components/settings/LLMSettings";
import ASRSettings from "@/components/settings/ASRSettings";
import TTSSettings from "@/components/settings/TTSSettings";
import OCRSettings from "@/components/settings/OCRSettings";
import ImageGenSettings from "@/components/settings/ImageGenSettings";
import SubtitleStyle from "@/components/settings/SubtitleStyle";
import VideoProcess from "@/components/settings/VideoProcess";
import GeneralSettings from "@/components/settings/GeneralSettings";
import UISettings from "@/components/settings/UISettings";
import AudioProcessingSettings from "@/components/settings/AudioProcessing";
import AigcCapabilitiesSettings from "@/components/settings/AigcCapabilitiesSettings";
import {
  Settings2,
  Brain,
  Mic,
  Volume2,
  ScanText,
  Type,
  Film,
  Palette,
  SlidersVertical,
  Image,
  Boxes,
  Sparkles,
  Layers,
} from "lucide-react";
import type { ComponentType } from "react";

type Tone = "default" | "primary" | "success" | "warning" | "info" | "ai" | "destructive";

interface TabDef {
  id: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  group: string;
  tone: Tone;
  component: ComponentType;
}

const TABS: TabDef[] = [
  { id: "ui", label: "UI 设置", icon: Palette, group: "界面", tone: "primary", component: UISettings },
  { id: "general", label: "通用设置", icon: Settings2, group: "通用", tone: "default", component: GeneralSettings },
  { id: "audio", label: "音频处理", icon: SlidersVertical, group: "媒体", tone: "info", component: AudioProcessingSettings },
  { id: "llm", label: "LLM 配置", icon: Brain, group: "模型", tone: "ai", component: LLMSettings },
  { id: "asr", label: "ASR 配置", icon: Mic, group: "模型", tone: "info", component: ASRSettings },
  { id: "tts", label: "TTS 配置", icon: Volume2, group: "模型", tone: "success", component: TTSSettings },
  { id: "ocr", label: "OCR 配置", icon: ScanText, group: "模型", tone: "info", component: OCRSettings },
  { id: "imggen", label: "图像生成", icon: Image, group: "模型", tone: "ai", component: ImageGenSettings },
  { id: "aigc", label: "其他能力接口", icon: Boxes, group: "高级", tone: "warning", component: AigcCapabilitiesSettings },
  { id: "subtitle", label: "字幕样式", icon: Type, group: "媒体", tone: "primary", component: SubtitleStyle },
  { id: "videoprocess", label: "视频合成", icon: Film, group: "媒体", tone: "warning", component: VideoProcess },
];

const GROUPS = [
  { id: "界面", icon: Palette, desc: "主题、布局与显示" },
  { id: "通用", icon: Settings2, desc: "项目级通用配置" },
  { id: "模型", icon: Brain, desc: "AI 模型与第三方接口" },
  { id: "媒体", icon: Layers, desc: "音频、字幕与视频处理" },
  { id: "高级", icon: Sparkles, desc: "实验性能力与扩展接口" },
];

const TONE_DOT: Record<Tone, string> = {
  default: "bg-muted-foreground/60",
  primary: "bg-primary",
  success: "bg-success",
  warning: "bg-warning",
  info: "bg-info",
  ai: "bg-ai",
  destructive: "bg-destructive",
};

const TONE_ACTIVE_BG: Record<Tone, string> = {
  default: "bg-muted text-foreground",
  primary: "bg-primary/10 text-foreground",
  success: "bg-success/10 text-foreground",
  warning: "bg-warning/12 text-foreground",
  info: "bg-info/10 text-foreground",
  ai: "bg-ai/10 text-foreground",
  destructive: "bg-destructive/10 text-foreground",
};

export default function Settings() {
  const [activeTab, setActiveTab] = useState("ui");
  const current = TABS.find((t) => t.id === activeTab) ?? TABS[0];
  const CurrentComponent = current.component;

  return (
    <PageBackground tone="settings" className="h-full overflow-auto">
      <div className="mx-auto flex h-full max-w-7xl flex-col gap-4 p-3 sm:p-5">
        <PageHeader
          icon={Settings2}
          title="全局设置"
          detail="全局参数设置。执行调用时的优先级：工作流中节点已设置参数 > 全局设置参数"
          sticky
          tone="default"
        />

        <div className="flex flex-1 min-h-0 gap-4 lg:gap-6">
          {/* 侧边导航 */}
          <nav className="hidden w-60 shrink-0 lg:flex flex-col gap-1 self-start sticky top-[88px] max-h-[calc(100vh-120px)] overflow-y-auto pr-1">
            {GROUPS.map((group) => {
              const items = TABS.filter((t) => t.group === group.id);
              if (items.length === 0) return null;
              const GroupIcon = group.icon;
              return (
                <div key={group.id} className="mb-3">
                  <div className="mb-1.5 flex items-center gap-2 px-2.5 py-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    <GroupIcon className="h-3.5 w-3.5" />
                    {group.id}
                  </div>
                  <div className="space-y-0.5">
                    {items.map((tab) => {
                      const Icon = tab.icon;
                      const active = tab.id === activeTab;
                      return (
                        <button
                          key={tab.id}
                          onClick={() => setActiveTab(tab.id)}
                          className={cn(
                            "group flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm transition-all duration-200",
                            active
                              ? cn("font-medium shadow-sm", TONE_ACTIVE_BG[tab.tone])
                              : "text-muted-foreground hover:bg-accent hover:text-foreground"
                          )}
                        >
                          <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full transition-all", TONE_DOT[tab.tone], active ? "scale-125" : "opacity-60 group-hover:opacity-100")} />
                          <Icon className={cn("h-4 w-4 shrink-0", active ? "text-foreground" : "")} />
                          <span className="truncate">{tab.label}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </nav>

          {/* 移动端横向 tab */}
          <div className="lg:hidden -mx-1 mb-2 flex flex-wrap gap-1.5">
            {TABS.map((tab) => {
              const Icon = tab.icon;
              const active = tab.id === activeTab;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
                    active
                      ? "border-primary/40 bg-primary/10 text-foreground"
                      : "border-border/60 bg-card/60 text-muted-foreground hover:text-foreground"
                  )}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {tab.label}
                </button>
              );
            })}
          </div>

          {/* 主内容区 */}
          <main className="min-w-0 flex-1">
            {/* 当前页提示（窄屏下用 chip 展示分组） */}
            <div className="mb-3 flex items-center gap-2 text-xs text-muted-foreground lg:hidden">
              <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5">
                <current.icon className="h-3 w-3" />
                {current.group} · {current.label}
              </span>
            </div>
            <div key={activeTab} className="animate-fade-in-up">
              <CurrentComponent />
            </div>
          </main>
        </div>
      </div>
    </PageBackground>
  );
}

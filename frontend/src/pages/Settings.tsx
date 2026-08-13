import { useState } from "react";
import { cn } from "@/lib/utils";
import LLMSettings from "@/components/settings/LLMSettings";
import ASRSettings from "@/components/settings/ASRSettings";
import TTSSettings from "@/components/settings/TTSSettings";
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
  Type,
  Film,
  Palette,
  SlidersVertical,
  Image,
  Boxes,
} from "lucide-react";

const tabs = [
  { id: "ui", label: "UI 设置", icon: Palette },
  { id: "general", label: "通用设置", icon: Settings2 },
  { id: "audio", label: "音频处理", icon: SlidersVertical },
  { id: "llm", label: "LLM 配置", icon: Brain },
  { id: "asr", label: "ASR 配置", icon: Mic },
  { id: "tts", label: "TTS 配置", icon: Volume2 },
  { id: "imggen", label: "图像生成", icon: Image },
  { id: "aigc", label: "其他能力接口", icon: Boxes },
  { id: "subtitle", label: "字幕样式", icon: Type },
  { id: "videoprocess", label: "视频合成", icon: Film },
];

export default function Settings() {
  const [activeTab, setActiveTab] = useState("ui");

  const renderTab = () => {
    switch (activeTab) {
      case "ui":
        return <UISettings />;
      case "general":
        return <GeneralSettings />;
      case "audio":
        return <AudioProcessingSettings />;
      case "llm":
        return <LLMSettings />;
      case "asr":
        return <ASRSettings />;
      case "tts":
        return <TTSSettings />;
      case "imggen":
        return <ImageGenSettings />;
      case "aigc":
        return <AigcCapabilitiesSettings />;
      case "subtitle":
        return <SubtitleStyle />;
      case "videoprocess":
        return <VideoProcess />;
      default:
        return null;
    }
  };

  return (
    <div className="max-w-6xl mx-auto space-y-6 stagger-children">
      <div>
        <h2 className="text-2xl font-extrabold tracking-tight flex items-center gap-2.5">
          <Settings2 className="w-6 h-6 text-primary" />
          "全局设置"
        </h2>
        <p className="text-sm text-muted-foreground mt-1">
          全局参数设置，执行调用的时候参数调用优先级：工作流中节点已设置参数 {'>'} 全局设置参数
        </p>
      </div>

      <div className="flex gap-1 p-1 rounded-xl bg-muted/50 border border-border/40">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const active = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "flex items-center gap-2 px-3.5 py-2 text-sm font-medium rounded-lg transition-all duration-250 relative",
                active
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground hover:bg-background/50"
              )}
            >
              <Icon
                className={cn(
                  "w-4 h-4 transition-colors",
                  active ? "text-primary" : ""
                )}
                strokeWidth={active ? 2.5 : 2}
              />
              <span className="hidden sm:inline">{tab.label}</span>
            </button>
          );
        })}
      </div>

      <div key={activeTab} className="animate-fade-in-up">
        {renderTab()}
      </div>
    </div>
  );
}

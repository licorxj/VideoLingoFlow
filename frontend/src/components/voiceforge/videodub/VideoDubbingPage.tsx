import { useState } from "react";
import { Captions, Film, FolderOpen, Import, Loader2, Save, Scan, SlidersHorizontal, Waypoints } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageBackground } from "@/components/shared/PageBackground";
import { AddSubtitleDialog } from "./AddSubtitleDialog";
import { DubModeDialog } from "./DubModeDialog";
import { ImportVlfTaskDialog } from "./ImportVlfTaskDialog";
import { SubtitlePanel } from "./SubtitlePanel";
import { Timeline } from "./Timeline";
import { TrackAudioPlayer } from "./TrackAudioPlayer";
import { VideoPreview, useVideoPick } from "./VideoPreview";
import { WorkspaceDialog } from "./WorkspaceDialog";
import { saveWorkspace } from "./persistence";
import { useVideoDubStore } from "./store";
import { formatTimecode } from "./media";

/**
 * 视频配音工作台：顶部工具栏 + 中部（视频预览 | 字幕列表）+ 底部多轨时间轴。
 * 时间指针、视频播放进度与字幕列表三方联动。
 */
export function VideoDubbingPage() {
  const [subtitleOpen, setSubtitleOpen] = useState(false);
  const [workspaceOpen, setWorkspaceOpen] = useState(false);
  const [vlfOpen, setVlfOpen] = useState(false);
  const [dubModeOpen, setDubModeOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const video = useVideoDubStore((state) => state.video);
  const pairs = useVideoDubStore((state) => state.pairs);
  const workspaceName = useVideoDubStore((state) => state.workspaceName);
  const savedAt = useVideoDubStore((state) => state.savedAt);
  const dubMode = useVideoDubStore((state) => state.dubMode);
  const alignDubToPairs = useVideoDubStore((state) => state.alignDubToPairs);
  const fitAudioToSubtitles = useVideoDubStore((state) => state.fitAudioToSubtitles);
  const extendSubtitlesToAudio = useVideoDubStore((state) => state.extendSubtitlesToAudio);
  const { input: videoInput, open: openVideo } = useVideoPick();

  const handleSave = async () => {
    setSaving(true);
    setSaveError("");
    const result = await saveWorkspace();
    setSaving(false);
    if (!result.ok) setSaveError(result.error || "保存失败");
  };

  return (
    <PageBackground tone="voiceforge" className="flex h-[calc(100%-3rem)] flex-col overflow-hidden p-2">
      <div className="flex h-10 flex-none items-center gap-2 px-1">
        <Button size="sm" onClick={openVideo}>
          <Film className="mr-1.5 h-4 w-4" />
          添加视频
        </Button>
        <Button size="sm" variant="ai-soft" onClick={() => setSubtitleOpen(true)}>
          <Captions className="mr-1.5 h-4 w-4" />
          添加字幕
        </Button>
        <span className="mx-1 h-5 w-px flex-none bg-border" />
        <Button size="sm" variant="outline" onClick={() => void handleSave()} disabled={saving} title="保存字幕、轨道布局与音频到后端">
          {saving ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Save className="mr-1.5 h-4 w-4" />}
          保存工程
        </Button>
        <Button size="sm" variant="outline" onClick={() => setWorkspaceOpen(true)}>
          <FolderOpen className="mr-1.5 h-4 w-4" />
          打开工程
        </Button>
        <Button size="sm" variant="outline" onClick={() => setVlfOpen(true)} title="从工作流历史任务导入配音任务表与视频">
          <Import className="mr-1.5 h-4 w-4" />
          导入vlf任务
        </Button>
        <span className="mx-1 h-5 w-px flex-none bg-border" />
        <Button size="sm" variant="outline" onClick={() => alignDubToPairs()} disabled={!pairs.some((pair) => pair.dubClipId)} title="一键对齐：将所有配音片段的开头对齐其所属字幕的开头">
          <Waypoints className="mr-1.5 h-4 w-4" />
          一键对齐
        </Button>
        <Button size="sm" variant="outline" onClick={() => fitAudioToSubtitles()} disabled={!pairs.some((pair) => pair.dubClipId)} title="音频对齐字幕：对配音片段做虚拟变速，让其播放时长贴合字幕时长（不重新合成）">
          <Scan className="mr-1.5 h-4 w-4" />
          音频对齐字幕
        </Button>
        <Button size="sm" variant="outline" onClick={() => extendSubtitlesToAudio()} disabled={!pairs.some((pair) => pair.dubClipId)} title="字幕对齐音频：将字幕结束时间延长至覆盖该句配音的真实音频时长">
          <Scan className="mr-1.5 h-4 w-4 -scale-x-100" />
          字幕对齐音频
        </Button>
        <Button size="sm" variant="ai-soft" onClick={() => setDubModeOpen(true)} title="设置配音模式（音色/克隆/TTS接口音色）">
          <SlidersHorizontal className="mr-1.5 h-4 w-4" />
          配音模式
        </Button>
        {saveError ? (
          <span className="max-w-[260px] truncate text-xs text-destructive" title={saveError}>
            {saveError}
          </span>
        ) : workspaceName ? (
          <span className="max-w-[320px] truncate text-xs text-muted-foreground" title={workspaceName}>
            {workspaceName}
            {pairs.length ? ` · ${pairs.length} 条字幕` : ""}
            {savedAt ? ` · 已保存 ${new Date(savedAt).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}` : ""}
          </span>
        ) : video ? (
          <span className="max-w-[320px] truncate text-xs text-muted-foreground" title={video.name}>
            {video.name}（未保存）{pairs.length ? ` · ${pairs.length} 条字幕` : ""}
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">先添加本地视频，再导入 SRT 字幕开始配音</span>
        )}
        <span className="ml-auto hidden text-xs text-muted-foreground lg:block">
          视频进度 · 时间指针 · 字幕列表三方联动
          {video?.duration ? ` · 片长 ${formatTimecode(video.duration, 1)}` : ""}
        </span>
      </div>

      <div className="flex min-h-0 flex-1 gap-2 py-2">
        <div className="min-w-0 flex-1">
          <VideoPreview />
        </div>
        <div className="w-[350px] flex-none">
          <SubtitlePanel />
        </div>
      </div>

      <Timeline />

      {/* 配音 / 背景音乐 / 音效轨的同步播放引擎（无 UI） */}
      <TrackAudioPlayer />

      {videoInput}
      <AddSubtitleDialog open={subtitleOpen} onOpenChange={setSubtitleOpen} />
      <WorkspaceDialog open={workspaceOpen} onOpenChange={setWorkspaceOpen} />
      <ImportVlfTaskDialog open={vlfOpen} onOpenChange={setVlfOpen} />
      <DubModeDialog open={dubModeOpen} onOpenChange={setDubModeOpen} />
    </PageBackground>
  );
}

import { useEffect, useMemo, useRef, useState } from "react";
import { Film, Pause, Play, RotateCcw, Video as VideoIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useVideoDubStore, activePairAt } from "./store";
import { formatTimecode } from "./media";
import { VideoInfo, uid } from "./types";

/**
 * 选择本地视频文件并写入 store。
 * 返回的 `input` 需要渲染在组件树中，`open` 触发文件选择框。
 */
export function useVideoPick() {
  const inputRef = useRef<HTMLInputElement>(null);
  const input = (
    <input
      ref={inputRef}
      type="file"
      accept="video/*"
      className="hidden"
      onChange={(event) => {
        const file = event.target.files?.[0];
        event.target.value = "";
        if (!file) return;
        const url = URL.createObjectURL(file);
        useVideoDubStore.getState().setVideo({ name: file.name, url, duration: 0, width: 0, height: 0 });
        // 换视频即视为新的未保存工程
        useVideoDubStore.setState({ videoFile: file, workspaceId: null, workspaceName: null, savedAt: null });
      }}
    />
  );
  return { input, open: () => inputRef.current?.click() };
}

export function VideoPreview() {
  const video = useVideoDubStore((state) => state.video);
  const pairs = useVideoDubStore((state) => state.pairs);
  const currentTime = useVideoDubStore((state) => state.currentTime);
  const playing = useVideoDubStore((state) => state.playing);
  const seek = useVideoDubStore((state) => state.seek);
  const setPlaying = useVideoDubStore((state) => state.setPlaying);
  const updateVideo = useVideoDubStore((state) => state.updateVideo);
  const setOriginalAudio = useVideoDubStore((state) => state.setOriginalAudio);
  const { input, open } = useVideoPick();

  const videoRef = useRef<HTMLVideoElement>(null);
  const [loadError, setLoadError] = useState("");
  const [src, setSrc] = useState("");

  useEffect(() => {
    setSrc(video?.url || "");
    setLoadError("");
  }, [video?.url]);

  const mutedOriginal = useVideoDubStore((state) => state.mutedTracks.original_audio);

  // 视频自带的音轨即「原音」：跟随原音轨的喇叭开关（载入后默认静音）
  useEffect(() => {
    const element = videoRef.current;
    if (element) element.muted = mutedOriginal;
  }, [mutedOriginal, src]);

  // 播放中用 rAF 逐帧推进时间指针，比 timeupdate（约 4Hz）更顺滑
  useEffect(() => {
    if (!playing) return;
    let frame = 0;
    const tick = () => {
      const element = videoRef.current;
      if (element) seek(element.currentTime);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, seek]);

  // 外部定位（拖时间指针 / 点字幕行 / 点轨道片段）同步到 video
  useEffect(() => {
    const element = videoRef.current;
    if (element && Math.abs(element.currentTime - currentTime) > 0.04) {
      element.currentTime = currentTime;
    }
  }, [currentTime]);

  const togglePlay = () => {
    const element = videoRef.current;
    if (!element) return;
    if (element.paused) {
      void element.play().catch(() => setPlaying(false));
      setPlaying(true);
    } else {
      element.pause();
      setPlaying(false);
    }
  };

  const restart = () => {
    const element = videoRef.current;
    if (!element) return;
    element.currentTime = 0;
    seek(0);
  };

  const handleLoadedMetadata = () => {
    const element = videoRef.current;
    if (!element || !video) return;
    const patch: Partial<VideoInfo> = { width: element.videoWidth, height: element.videoHeight };
    // 部分 mkv/webm 的 duration 会是 Infinity，此时保留已有估计值（如 vlf 导入的句尾时间）
    if (Number.isFinite(element.duration) && element.duration > 0) patch.duration = element.duration;
    updateVideo(patch);
    setOriginalAudio({ id: uid(), name: `${video.name} · 原音`, start: 0, duration: Number.isFinite(element.duration) ? element.duration : 0 });
    seek(0);
  };

  const activePair = useMemo(() => activePairAt(pairs, currentTime), [pairs, currentTime]);

  if (!video) {
    return (
      <section className="flex h-full flex-col overflow-hidden rounded-xl border border-border/60 bg-card">
        <div className="flex flex-1 flex-col items-center justify-center gap-3 border-b border-dashed border-border/60 m-3 rounded-lg text-muted-foreground">
          <VideoIcon className="h-10 w-10 opacity-50" />
          <p className="text-sm">还没有视频，先添加一个本地视频开始配音</p>
          <Button onClick={open}>
            <Film className="mr-1.5 h-4 w-4" />
            添加视频
          </Button>
          <p className="text-xs text-muted-foreground">支持 mp4 / webm / mov 等浏览器可播放的格式</p>
        </div>
        {input}
      </section>
    );
  }

  return (
    <section className="flex h-full flex-col overflow-hidden rounded-xl border border-border/60 bg-card">
      <div className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden bg-black/85" onDoubleClick={togglePlay}>
        <video
          ref={videoRef}
          src={src}
          className="max-h-full max-w-full"
          onLoadedMetadata={handleLoadedMetadata}
          onTimeUpdate={() => {
            // rAF 循环的主通道之外，timeupdate 作为兜底（后台标签页 rAF 会被节流）
            const element = videoRef.current;
            if (element) seek(element.currentTime);
          }}
          onEnded={() => setPlaying(false)}
          onError={() => setLoadError("视频无法播放，请更换文件或格式（推荐 mp4 / H.264）。")}
          onClick={togglePlay}
        />
        {loadError ? (
          <div className="absolute inset-0 flex items-center justify-center bg-black/70 p-4 text-center text-sm text-red-300">
            {loadError}
          </div>
        ) : null}
        {activePair && (activePair.text || activePair.translation) ? (
          <div className="pointer-events-none absolute inset-x-4 bottom-4 flex flex-col items-center gap-1 text-center">
            {activePair.text ? (
              <p className="rounded bg-black/55 px-3 py-1 text-base leading-6 text-white [text-shadow:0_1px_2px_rgba(0,0,0,0.9)]">
                {activePair.text}
              </p>
            ) : null}
            {activePair.translation ? (
              <p className="rounded bg-black/45 px-3 py-0.5 text-sm leading-5 text-white/85 [text-shadow:0_1px_2px_rgba(0,0,0,0.9)]">
                {activePair.translation}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
      <div className="flex h-11 flex-none items-center gap-2 border-t border-border/60 px-3">
        <Button size="icon" variant="ghost" className="h-8 w-8" onClick={restart} title="回到开头">
          <RotateCcw className="h-4 w-4" />
        </Button>
        <Button size="icon" className="h-8 w-8" onClick={togglePlay} title={playing ? "暂停" : "播放"}>
          {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
        </Button>
        <span className="ml-1 font-mono text-xs tabular-nums text-muted-foreground">
          {formatTimecode(currentTime)} / {formatTimecode(video.duration)}
        </span>
        <span className="ml-auto max-w-[45%] truncate text-xs text-muted-foreground" title={video.name}>
          {video.name}
          {video.width ? ` · ${video.width}×${video.height}` : ""}
        </span>
      </div>
      {input}
    </section>
  );
}

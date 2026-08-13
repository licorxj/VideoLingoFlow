import { useEffect, useRef, useState, useCallback } from "react";
import {
  Play,
  Pause,
  RotateCcw,
  RefreshCw,
  Music,
  Clock,
  ListOrdered,
  Volume2,
} from "lucide-react";
import { VoiceForgeSentence, voiceForgeApi } from "@/api/voiceforge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/* ── Types ─────────────────────────────────────────────────────────── */

interface PreviewSectionModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  chapterName: string;
  sentences: VoiceForgeSentence[];
  defaultGap: number;
  onRegenerateSentence?: (sentenceId: string) => Promise<void>;
}

interface TrackItem {
  sentenceId: string;
  audioUrl: string;
  startTime: number;
  endTime: number;
  duration: number;
  gap: number;
}

/* ── Helpers ────────────────────────────────────────────────────────── */

function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
}

function formatDurationChinese(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  if (mins === 0) return `${secs} 秒`;
  return `${mins} 分 ${secs} 秒`;
}

/* ── Component ─────────────────────────────────────────────────────── */

export function PreviewSectionModal({
  open,
  onOpenChange,
  projectId,
  chapterName,
  sentences,
  defaultGap,
  onRegenerateSentence,
}: PreviewSectionModalProps) {
  /* ── State ──────────────────────────────────────────────────────── */
  const [playing, setPlaying] = useState(false);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [totalDuration, setTotalDuration] = useState(0);
  const [playbackRate, setPlaybackRate] = useState(1.0);
  const [trackItems, setTrackItems] = useState<TrackItem[]>([]);
  const [isRegenerating, setIsRegenerating] = useState(false);

  /* ── Refs ───────────────────────────────────────────────────────── */
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const trackItemsRef = useRef<TrackItem[]>([]);
  const currentIndexRef = useRef(0);
  const playingRef = useRef(false);
  const pauseTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  /* ── Build track items ──────────────────────────────────────────── */
  useEffect(() => {
    if (!open || !sentences.length) {
      setTrackItems([]);
      setTotalDuration(0);
      return;
    }

    const items: TrackItem[] = [];
    let accumulated = 0;

    sentences.forEach((sentence) => {
      const audioUrl = sentence.audio_storage_key
        ? voiceForgeApi.sentenceAudioUrl(sentence.id)
        : "";
      const estimatedDuration = sentence.text.length * 0.15;
      const gap = sentence.pause_after ?? defaultGap;

      items.push({
        sentenceId: sentence.id,
        audioUrl,
        startTime: accumulated,
        endTime: accumulated + estimatedDuration,
        duration: estimatedDuration,
        gap,
      });

      accumulated += estimatedDuration + gap;
    });

    setTrackItems(items);
    trackItemsRef.current = items;
    setTotalDuration(accumulated);
    setCurrentIndex(0);
    currentIndexRef.current = 0;
    setCurrentTime(0);
    setPlaying(false);
    playingRef.current = false;
  }, [open, sentences, defaultGap]);

  /* ── Audio engine ───────────────────────────────────────────────── */
  const playSentence = useCallback(
    (index: number) => {
      if (index >= trackItemsRef.current.length) {
        setPlaying(false);
        playingRef.current = false;
        return;
      }

      const item = trackItemsRef.current[index];
      if (!item.audioUrl) {
        // Skip sentences without audio
        playSentence(index + 1);
        return;
      }

      setCurrentIndex(index);
      currentIndexRef.current = index;

      // Create or reuse audio element
      if (!audioRef.current) {
        audioRef.current = new Audio();
        audioRef.current.addEventListener("ended", () => {
          // Wait gap duration then play next
          const gap = trackItemsRef.current[currentIndexRef.current]?.gap ?? defaultGap;
          pauseTimeoutRef.current = setTimeout(() => {
            playSentence(currentIndexRef.current + 1);
          }, gap * 1000);
        });
        audioRef.current.addEventListener("timeupdate", () => {
          if (audioRef.current) {
            const item = trackItemsRef.current[currentIndexRef.current];
            if (item) {
              setCurrentTime(item.startTime + audioRef.current.currentTime);
            }
          }
        });
        audioRef.current.addEventListener("error", () => {
          // Skip on error
          playSentence(currentIndexRef.current + 1);
        });
      }

      audioRef.current.src = item.audioUrl;
      audioRef.current.playbackRate = playbackRate;
      audioRef.current.play().catch(() => {
        playSentence(index + 1);
      });
    },
    [defaultGap, playbackRate],
  );

  const handlePlay = useCallback(() => {
    setPlaying(true);
    playingRef.current = true;
    playSentence(currentIndexRef.current);
  }, [playSentence]);

  const handlePause = useCallback(() => {
    setPlaying(false);
    playingRef.current = false;
    if (audioRef.current) {
      audioRef.current.pause();
    }
    if (pauseTimeoutRef.current) {
      clearTimeout(pauseTimeoutRef.current);
      pauseTimeoutRef.current = null;
    }
  }, []);

  const handleRestart = useCallback(() => {
    handlePause();
    setCurrentIndex(0);
    currentIndexRef.current = 0;
    setCurrentTime(0);
  }, [handlePause]);

  const handleSeek = useCallback(
    (sentenceIndex: number) => {
      const wasPlaying = playingRef.current;
      handlePause();
      setCurrentIndex(sentenceIndex);
      currentIndexRef.current = sentenceIndex;
      setCurrentTime(trackItemsRef.current[sentenceIndex]?.startTime ?? 0);
      if (wasPlaying) {
        // Small delay before resuming
        setTimeout(() => {
          setPlaying(true);
          playingRef.current = true;
          playSentence(sentenceIndex);
        }, 100);
      }
    },
    [handlePause, playSentence],
  );

  const handleRegenerateCurrent = useCallback(async () => {
    if (!onRegenerateSentence || isRegenerating) return;
    const currentItem = trackItemsRef.current[currentIndexRef.current];
    if (!currentItem) return;

    setIsRegenerating(true);
    try {
      await onRegenerateSentence(currentItem.sentenceId);
    } finally {
      setIsRegenerating(false);
    }
  }, [onRegenerateSentence, isRegenerating]);

  /* ── Cleanup on close ───────────────────────────────────────────── */
  useEffect(() => {
    if (!open) {
      handlePause();
      if (audioRef.current) {
        audioRef.current.src = "";
        audioRef.current = null;
      }
      setCurrentIndex(0);
      setCurrentTime(0);
    }
  }, [open, handlePause]);

  /* ── Update playback rate ───────────────────────────────────────── */
  useEffect(() => {
    if (audioRef.current) {
      audioRef.current.playbackRate = playbackRate;
    }
  }, [playbackRate]);

  /* ── Derived values ─────────────────────────────────────────────── */
  const currentSentence = sentences[currentIndex];
  const progress = totalDuration > 0 ? (currentTime / totalDuration) * 100 : 0;
  const doneCount = sentences.filter((s) => s.status === "done").length;

  /* ── Render ─────────────────────────────────────────────────────── */
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Music className="h-5 w-5 text-primary" />
            章节音频预览
          </DialogTitle>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto space-y-4 pr-2">
          {/* ── Info Cards ──────────────────────────────────────────── */}
          <div className="grid grid-cols-3 gap-3">
            <div className="rounded-lg border border-border/50 bg-muted/30 p-3">
              <div className="flex items-center gap-2 text-xs text-muted-foreground mb-1">
                <Music className="h-3.5 w-3.5" />
                当前章节
              </div>
              <div className="text-sm font-medium truncate">{chapterName || "未命名"}</div>
            </div>
            <div className="rounded-lg border border-border/50 bg-muted/30 p-3">
              <div className="flex items-center gap-2 text-xs text-muted-foreground mb-1">
                <Clock className="h-3.5 w-3.5" />
                预计总时长
              </div>
              <div className="text-sm font-medium">{formatDurationChinese(totalDuration)}</div>
            </div>
            <div className="rounded-lg border border-border/50 bg-muted/30 p-3">
              <div className="flex items-center gap-2 text-xs text-muted-foreground mb-1">
                <ListOrdered className="h-3.5 w-3.5" />
                句子进度
              </div>
              <div className="text-sm font-medium">
                {doneCount} / {sentences.length} 已生成
              </div>
            </div>
          </div>

          {/* ── Sentence Locator Slider ─────────────────────────────── */}
          <div className="rounded-lg border border-border/50 bg-muted/20 p-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-muted-foreground">句子定位</span>
              <span className="text-xs font-medium text-primary">
                第 {currentIndex + 1} 句 · {formatDuration(currentTime)}
              </span>
            </div>
            <input
              type="range"
              min={0}
              max={Math.max(0, sentences.length - 1)}
              value={currentIndex}
              onChange={(e) => handleSeek(parseInt(e.target.value, 10))}
              className="w-full h-2 bg-muted rounded-full appearance-none cursor-pointer accent-primary"
            />
          </div>

          {/* ── Sentence Progress Bars ──────────────────────────────── */}
          <div className="space-y-1.5">
            {sentences.map((sentence, index) => {
              const item = trackItems[index];
              const isCurrent = index === currentIndex;
              const isPast = index < currentIndex;
              const barProgress = isPast
                ? 100
                : isCurrent
                  ? item
                    ? ((currentTime - item.startTime) / item.duration) * 100
                    : 0
                  : 0;

              return (
                <div
                  key={sentence.id}
                  className="group flex items-center gap-2 cursor-pointer hover:bg-muted/30 rounded px-2 py-1 transition-colors"
                  onClick={() => handleSeek(index)}
                >
                  <span className="text-xs text-muted-foreground w-6 text-right shrink-0">
                    {index + 1}
                  </span>
                  <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-purple-500 to-blue-500 transition-all duration-100"
                      style={{ width: `${Math.min(100, Math.max(0, barProgress))}%` }}
                    />
                  </div>
                  <span className="text-xs text-muted-foreground w-12 text-right shrink-0">
                    {item ? formatDuration(item.duration) : "--:--"}
                  </span>
                </div>
              );
            })}
          </div>

          {/* ── Playback Controls ───────────────────────────────────── */}
          <div className="flex items-center justify-center gap-3">
            <Button
              variant="outline"
              size="icon"
              onClick={handleRestart}
              title="从头开始"
            >
              <RotateCcw className="h-4 w-4" />
            </Button>
            {playing ? (
              <Button
                size="lg"
                onClick={handlePause}
                className="w-14 h-14 rounded-full bg-gradient-to-br from-purple-500 to-blue-500 hover:from-purple-600 hover:to-blue-600"
              >
                <Pause className="h-6 w-6" />
              </Button>
            ) : (
              <Button
                size="lg"
                onClick={handlePlay}
                className="w-14 h-14 rounded-full bg-gradient-to-br from-purple-500 to-blue-500 hover:from-purple-600 hover:to-blue-600"
              >
                <Play className="h-6 w-6 ml-1" />
              </Button>
            )}
            <Button
              variant="outline"
              size="icon"
              onClick={handleRegenerateCurrent}
              disabled={isRegenerating}
              title="重新生成当前句子"
            >
              {isRegenerating ? (
                <RefreshCw className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
            </Button>
          </div>

          {/* ── Playback Rate Selector ──────────────────────────────── */}
          <div className="flex items-center justify-center gap-2">
            <span className="text-xs text-muted-foreground mr-2">播放速度:</span>
            {[0.75, 1.0, 1.25, 1.5, 2.0].map((rate) => (
              <button
                key={rate}
                onClick={() => setPlaybackRate(rate)}
                className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                  playbackRate === rate
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground hover:bg-muted/80"
                }`}
              >
                {rate}x
              </button>
            ))}
          </div>

          {/* ── Timeline Progress Bar ───────────────────────────────── */}
          <div className="space-y-1">
            <div className="relative h-3 bg-muted rounded-full overflow-hidden">
              <div
                className="absolute inset-y-0 left-0 bg-gradient-to-r from-purple-500 to-blue-500 transition-all duration-100"
                style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
              />
            </div>
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>{formatDuration(currentTime)}</span>
              <span>{formatDuration(totalDuration)}</span>
            </div>
          </div>

          {/* ── Current Sentence Info ───────────────────────────────── */}
          {currentSentence && (
            <div className="rounded-lg border border-primary/30 bg-primary/5 p-3">
              <div className="flex items-center gap-2 mb-1">
                <Volume2 className="h-4 w-4 text-primary" />
                <span className="text-sm font-medium text-primary">
                  第 {currentIndex + 1} 句
                </span>
                {currentSentence.character_name && (
                  <span className="text-xs text-muted-foreground">
                    · {currentSentence.character_name}
                  </span>
                )}
              </div>
              <p className="text-sm text-foreground/80 line-clamp-2">
                {currentSentence.edited_text || currentSentence.text}
              </p>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

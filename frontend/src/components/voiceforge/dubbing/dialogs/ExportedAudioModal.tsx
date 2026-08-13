import { useRef, useState } from "react";
import {
  Download,
  FileAudio,
  Loader2,
  Play,
  Square,
  Trash2,
  Music,
} from "lucide-react";
import { voiceForgeApi } from "@/api/voiceforge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/* ── Types ─────────────────────────────────────────────────────────── */

interface ExportedAudioModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  exports: Array<{
    id: string;
    export_type: string;
    file_name: string;
    status: string;
    format?: string;
    task_id?: string;
  }>;
  onDelete: (id: string) => void;
}

/* ── Helpers ────────────────────────────────────────────────────────── */

function getFormatBadgeColor(format?: string) {
  switch (format?.toLowerCase()) {
    case "wav":
      return "bg-purple-500/20 text-purple-400 border-purple-500/30";
    case "mp3":
      return "bg-green-500/20 text-green-400 border-green-500/30";
    case "flac":
      return "bg-blue-500/20 text-blue-400 border-blue-500/30";
    default:
      return "bg-muted text-muted-foreground";
  }
}

function getStatusBadge(status: string) {
  switch (status) {
    case "done":
      return { className: "bg-green-500/20 text-green-400 border-green-500/30", label: "完成" };
    case "running":
      return { className: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30", label: "处理中" };
    case "failed":
      return { className: "bg-red-500/20 text-red-400 border-red-500/30", label: "失败" };
    default:
      return { className: "bg-muted text-muted-foreground", label: status };
  }
}

/* ── Component ─────────────────────────────────────────────────────── */

export function ExportedAudioModal({
  open,
  onOpenChange,
  projectId,
  exports,
  onDelete,
}: ExportedAudioModalProps) {
  const [playingId, setPlayingId] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const handlePlay = (exportItem: { id: string }) => {
    const url = voiceForgeApi.exportDownloadUrl(exportItem.id);

    if (playingId === exportItem.id) {
      // Stop playing
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
      setPlayingId(null);
      return;
    }

    // Stop previous audio
    if (audioRef.current) {
      audioRef.current.pause();
    }

    // Play new audio
    const audio = new Audio(url);
    audio.addEventListener("ended", () => {
      setPlayingId(null);
      audioRef.current = null;
    });
    audio.addEventListener("error", () => {
      setPlayingId(null);
      audioRef.current = null;
    });
    audio.play().catch(() => {
      setPlayingId(null);
      audioRef.current = null;
    });

    audioRef.current = audio;
    setPlayingId(exportItem.id);
  };

  const handleDeleteRequest = (id: string) => {
    if (window.confirm("确定要删除此导出文件吗？此操作无法撤销。")) {
      onDelete(id);
    }
  };

  const handleOpenChange = (value: boolean) => {
    if (!value) {
      // Stop audio when closing
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
      setPlayingId(null);
    }
    onOpenChange(value);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-hidden flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileAudio className="h-5 w-5 text-primary" />
            已导出的音频
          </DialogTitle>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto">
          {exports.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <Music className="h-12 w-12 mb-4 opacity-30" />
              <p className="text-sm">暂无已导出的音频</p>
              <p className="text-xs mt-1">点击"导出音频"开始创建导出任务</p>
            </div>
          ) : (
            <div className="space-y-2">
              {exports.map((exportItem) => {
                const statusInfo = getStatusBadge(exportItem.status);
                const isPlaying = playingId === exportItem.id;
                const isRunning = exportItem.status === "running";

                return (
                  <div
                    key={exportItem.id}
                    className="flex items-center gap-3 rounded-lg border border-border/50 bg-muted/20 p-3 hover:bg-muted/30 transition-colors"
                  >
                    <FileAudio className="h-5 w-5 text-muted-foreground shrink-0" />

                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">
                        {exportItem.file_name || "未命名文件"}
                      </p>
                      <div className="flex items-center gap-2 mt-1">
                        {exportItem.format && (
                          <Badge
                            variant="outline"
                            className={`text-[10px] px-1.5 py-0 ${getFormatBadgeColor(exportItem.format)}`}
                          >
                            {exportItem.format.toUpperCase()}
                          </Badge>
                        )}
                        <Badge
                          variant="outline"
                          className={`text-[10px] px-1.5 py-0 ${statusInfo.className}`}
                        >
                          {isRunning && <Loader2 className="h-3 w-3 mr-1 animate-spin" />}
                          {statusInfo.label}
                        </Badge>
                      </div>
                    </div>

                    <div className="flex items-center gap-1 shrink-0">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        onClick={() => handlePlay(exportItem)}
                        disabled={exportItem.status !== "done"}
                        title={isPlaying ? "停止播放" : "播放"}
                      >
                        {isPlaying ? (
                          <Square className="h-4 w-4" />
                        ) : (
                          <Play className="h-4 w-4" />
                        )}
                      </Button>

                      <a
                        href={voiceForgeApi.exportDownloadUrl(exportItem.id)}
                        download
                        className="inline-flex"
                      >
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          disabled={exportItem.status !== "done"}
                          title="下载"
                        >
                          <Download className="h-4 w-4" />
                        </Button>
                      </a>

                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-destructive hover:text-destructive"
                        onClick={() => handleDeleteRequest(exportItem.id)}
                        title="删除"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

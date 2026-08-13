import { useState } from "react";
import { FileDown, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

/* ── Types ─────────────────────────────────────────────────────────── */

interface ChapterExportModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onExport: (data: {
    format: string;
    bitrate: string;
    normalize_volume: boolean;
    denoise: boolean;
    global_speed: number;
  }) => void;
  busy: boolean;
}

/* ── Constants ─────────────────────────────────────────────────────── */

const FORMAT_OPTIONS = [
  { value: "wav", label: "WAV (无损)", description: "最高音质，文件较大" },
  { value: "mp3", label: "MP3", description: "常用格式，兼容性好" },
  { value: "flac", label: "FLAC (无损)", description: "无损压缩，文件适中" },
];

const BITRATE_OPTIONS = [
  { value: "128k", label: "128 kbps" },
  { value: "192k", label: "192 kbps" },
  { value: "256k", label: "256 kbps" },
  { value: "320k", label: "320 kbps (最高)" },
];

/* ── Component ─────────────────────────────────────────────────────── */

export function ChapterExportModal({
  open,
  onOpenChange,
  onExport,
  busy,
}: ChapterExportModalProps) {
  const [format, setFormat] = useState("mp3");
  const [bitrate, setBitrate] = useState("256k");
  const [globalSpeed, setGlobalSpeed] = useState(1.0);
  const [normalizeVolume, setNormalizeVolume] = useState(true);
  const [denoise, setDenoise] = useState(false);

  const handleExport = () => {
    onExport({
      format,
      bitrate,
      normalize_volume: normalizeVolume,
      denoise,
      global_speed: globalSpeed,
    });
  };

  const handleOpenChange = (value: boolean) => {
    if (!value && !busy) {
      // Reset form when closing
      setFormat("mp3");
      setBitrate("256k");
      setGlobalSpeed(1.0);
      setNormalizeVolume(true);
      setDenoise(false);
    }
    onOpenChange(value);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileDown className="h-5 w-5 text-primary" />
            导出章节音频
          </DialogTitle>
          <DialogDescription>
            配置导出参数，将当前章节的音频导出为文件
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Format Select */}
          <div>
            <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              音频格式
            </label>
            <Select value={format} onValueChange={setFormat}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {FORMAT_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    <div>
                      <div className="font-medium">{option.label}</div>
                      <div className="text-xs text-muted-foreground">{option.description}</div>
                    </div>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Bitrate Select (only for MP3) */}
          {format === "mp3" && (
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                比特率
              </label>
              <Select value={bitrate} onValueChange={setBitrate}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {BITRATE_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {/* Global Speed Slider */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-xs font-medium text-muted-foreground">
                全局速度
              </label>
              <span className="text-xs font-medium text-primary">
                {globalSpeed.toFixed(2)}x
              </span>
            </div>
            <input
              type="range"
              min={0.5}
              max={2.0}
              step={0.05}
              value={globalSpeed}
              onChange={(e) => setGlobalSpeed(parseFloat(e.target.value))}
              className="w-full h-2 bg-muted rounded-full appearance-none cursor-pointer accent-primary"
            />
            <div className="flex justify-between text-[10px] text-muted-foreground mt-1">
              <span>0.5x 慢速</span>
              <span>1.0x 正常</span>
              <span>2.0x 快速</span>
            </div>
          </div>

          {/* Checkboxes */}
          <div className="space-y-3">
            <label className="flex items-center gap-3 cursor-pointer group">
              <input
                type="checkbox"
                checked={normalizeVolume}
                onChange={(e) => setNormalizeVolume(e.target.checked)}
                className="h-4 w-4 rounded border-border accent-primary"
              />
              <div>
                <span className="text-sm font-medium group-hover:text-foreground transition-colors">
                  音量归一化
                </span>
                <p className="text-xs text-muted-foreground">
                  自动调整音量至统一水平
                </p>
              </div>
            </label>

            <label className="flex items-center gap-3 cursor-pointer group">
              <input
                type="checkbox"
                checked={denoise}
                onChange={(e) => setDenoise(e.target.checked)}
                className="h-4 w-4 rounded border-border accent-primary"
              />
              <div>
                <span className="text-sm font-medium group-hover:text-foreground transition-colors">
                  降噪处理
                </span>
                <p className="text-xs text-muted-foreground">
                  去除音频中的背景噪音
                </p>
              </div>
            </label>
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => handleOpenChange(false)}
            disabled={busy}
          >
            取消
          </Button>
          <Button onClick={handleExport} disabled={busy}>
            {busy ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : (
              <FileDown className="mr-1.5 h-4 w-4" />
            )}
            {busy ? "导出中…" : "开始导出"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

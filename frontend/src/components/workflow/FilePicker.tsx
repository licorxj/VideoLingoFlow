import { useState, useEffect } from "react";
import { browseDirectory, listDrives, type FileItem } from "@/api/files";
import {
  X, Folder, File, ChevronRight, Home, HardDrive, ArrowUp,
  FileVideo, FileAudio, FileText, RefreshCw,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface FilePickerProps {
  open: boolean;
  onClose: () => void;
  onSelect: (path: string) => void;
  title?: string;
  filter?: string[]; // file extensions to highlight
}

function formatSize(bytes?: number): string {
  if (!bytes || bytes === 0) return "";
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

function getFileIcon(item: FileItem) {
  if (item.isDir) return Folder;
  const ext = item.name.split(".").pop()?.toLowerCase() || "";
  if (["mp4", "avi", "mkv", "mov", "wmv", "flv", "webm"].includes(ext)) return FileVideo;
  if (["mp3", "wav", "flac", "aac", "ogg", "m4a", "wma"].includes(ext)) return FileAudio;
  if (["srt", "ass", "ssa", "sub", "txt", "json", "yaml", "yml"].includes(ext)) return FileText;
  return File;
}

export default function FilePicker({ open, onClose, onSelect, title = "选择文件", filter }: FilePickerProps) {
  const [currentPath, setCurrentPath] = useState("");
  const [parentPath, setParentPath] = useState<string | undefined>();
  const [items, setItems] = useState<FileItem[]>([]);
  const [drives, setDrives] = useState<{ name: string; path: string }[]>([]);
  const [loading, setLoading] = useState(false);
  const [showDrives, setShowDrives] = useState(true);
  const [manualPath, setManualPath] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (open) {
      loadDrives();
    }
  }, [open]);

  const loadDrives = async () => {
    try {
      const data = await listDrives();
      setDrives(data.drives);
      setShowDrives(true);
    } catch (e) {
      setError("加载磁盘失败");
    }
  };

  const loadDir = async (path: string) => {
    setLoading(true);
    setError("");
    try {
      const data = await browseDirectory(path);
      setCurrentPath(data.path);
      setParentPath(data.parent);
      setItems(data.items);
      setShowDrives(false);
    } catch (e: any) {
      setError(e?.response?.data?.detail || "加载目录失败");
    }
    setLoading(false);
  };

  const goUp = () => {
    if (parentPath) loadDir(parentPath);
  };

  const goHome = () => {
    loadDir("");
  };

  const selectFile = (item: FileItem) => {
    if (item.isDir) {
      loadDir(item.path);
    } else {
      onSelect(item.path);
      onClose();
    }
  };

  const handleManualSubmit = () => {
    if (manualPath.trim()) {
      onSelect(manualPath.trim());
      onClose();
    }
  };

  if (!open) return null;

  const filteredItems = filter
    ? items.filter(item => {
        if (item.isDir) return true;
        const ext = item.name.split(".").pop()?.toLowerCase() || "";
        return filter.some(f => f.toLowerCase() === ext || f.toLowerCase() === "." + ext);
      })
    : items;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="bg-background border border-border rounded-2xl shadow-2xl w-[640px] max-h-[70vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-border/50">
          <h3 className="text-sm font-bold">{title}</h3>
          <button onClick={onClose} className="p-1 rounded-lg hover:bg-muted transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Breadcrumb / path bar */}
        <div className="px-5 py-2 border-b border-border/30 flex items-center gap-2 text-xs">
          <button onClick={goHome} className="p-1 rounded hover:bg-muted" title="主页">
            <Home className="w-3.5 h-3.5" />
          </button>
          <button onClick={loadDrives} className="p-1 rounded hover:bg-muted" title="磁盘">
            <HardDrive className="w-3.5 h-3.5" />
          </button>
          {!showDrives && (
            <>
              <ChevronRight className="w-3 h-3 text-muted-foreground" />
              <div className="flex-1 truncate text-muted-foreground font-mono text-[11px]">
                {currentPath || "主页"}
              </div>
              {parentPath && (
                <button onClick={goUp} className="p-1 rounded hover:bg-muted" title="返回上级">
                  <ArrowUp className="w-3.5 h-3.5" />
                </button>
              )}
              <button onClick={() => loadDir(currentPath)} className="p-1 rounded hover:bg-muted" title="刷新">
                <RefreshCw className="w-3.5 h-3.5" />
              </button>
            </>
          )}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto min-h-0">
          {loading && (
            <div className="flex items-center justify-center py-12 text-muted-foreground text-sm">
              <RefreshCw className="w-4 h-4 animate-spin mr-2" /> 加载中...
            </div>
          )}

          {error && (
            <div className="p-4 text-sm text-red-500">{error}</div>
          )}

          {/* Drive list */}
          {!loading && showDrives && (
            <div className="p-3 space-y-1">
              {drives.map(d => (
                <button
                  key={d.path}
                  onClick={() => loadDir(d.path)}
                  className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-muted/50 transition-colors text-left"
                >
                  <HardDrive className="w-4 h-4 text-muted-foreground" />
                  <span className="text-sm font-medium">{d.name}</span>
                  <span className="text-xs text-muted-foreground ml-auto">{d.path}</span>
                </button>
              ))}
            </div>
          )}

          {/* File list */}
          {!loading && !showDrives && (
            <div className="p-2 space-y-0.5">
              {filteredItems.length === 0 && (
                <div className="py-8 text-center text-muted-foreground text-sm">未找到文件</div>
              )}
              {filteredItems.map(item => {
                const Icon = getFileIcon(item);
                return (
                  <button
                    key={item.path}
                    onClick={() => selectFile(item)}
                    className={cn(
                      "w-full flex items-center gap-3 px-3 py-2 rounded-lg transition-colors text-left",
                      item.isDir ? "hover:bg-primary/5" : "hover:bg-muted/50"
                    )}
                  >
                    <Icon className={cn("w-4 h-4 flex-shrink-0", item.isDir ? "text-primary" : "text-muted-foreground")} />
                    <span className="text-sm truncate flex-1">{item.name}</span>
                    {!item.isDir && item.size !== undefined && (
                      <span className="text-[10px] text-muted-foreground whitespace-nowrap">{formatSize(item.size)}</span>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* Manual path input */}
        <div className="px-5 py-3 border-t border-border/50 flex items-center gap-2">
          <input
            type="text"
            value={manualPath}
            onChange={e => setManualPath(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleManualSubmit()}
            placeholder="或直接输入路径..."
            className="flex-1 px-3 py-1.5 text-xs rounded-lg border border-border/50 bg-background focus:border-primary/50 outline-none font-mono"
          />
          <button
            onClick={handleManualSubmit}
            className="px-3 py-1.5 text-xs rounded-lg bg-primary text-primary-foreground hover:bg-primary/90"
          >
            确认
          </button>
        </div>
      </div>
    </div>
  );
}

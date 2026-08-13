import { useState, useEffect, useRef, useCallback } from "react";
import axios from "axios";
import WaveSurfer from "wavesurfer.js";
import RegionsPlugin from "wavesurfer.js/dist/plugins/regions.esm.js";
import {
  FolderOpen, Music, Play, Pause, Scissors, Check, X, Loader2, FolderClosed, Clock,
} from "lucide-react";

interface AudioFile {
  name: string;
  path: string;
  size: number;
}

interface Props {
  open: boolean;
  onClose: () => void;
  onSelect: (path: string) => void;
}

const RECENT_FOLDERS_KEY = "audioSelector.recentFolders";
const MAX_RECENT = 5;

function loadRecentFolders(): string[] {
  try {
    return JSON.parse(localStorage.getItem(RECENT_FOLDERS_KEY) || "[]");
  } catch { return []; }
}

function saveRecentFolder(path: string): string[] {
  const list = loadRecentFolders().filter((p) => p !== path);
  list.unshift(path);
  const trimmed = list.slice(0, MAX_RECENT);
  localStorage.setItem(RECENT_FOLDERS_KEY, JSON.stringify(trimmed));
  return trimmed;
}

export default function AudioSelectorDialog({ open, onClose, onSelect }: Props) {
  const [folderPath, setFolderPath] = useState("");
  const [recursive, setRecursive] = useState(false);
  const [recentFolders, setRecentFolders] = useState<string[]>(loadRecentFolders);
  const [files, setFiles] = useState<AudioFile[]>([]);
  const [scanning, setScanning] = useState(false);
  const [selectedFile, setSelectedFile] = useState<AudioFile | null>(null);
  const [playing, setPlaying] = useState(false);
  const [trimming, setTrimming] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  const [trimmedPath, setTrimmedPath] = useState<string | null>(null);
  const [trimmedPlaying, setTrimmedPlaying] = useState(false);
  const [trimmedCurrentTime, setTrimmedCurrentTime] = useState(0);
  const [trimmedDuration, setTrimmedDuration] = useState(0);

  const waveformRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WaveSurfer | null>(null);
  const regionsRef = useRef<RegionsPlugin | null>(null);
  const trimmedWaveformRef = useRef<HTMLDivElement>(null);
  const trimmedWsRef = useRef<WaveSurfer | null>(null);

  // 初始化 wavesurfer
  useEffect(() => {
    if (!open || !waveformRef.current) return;

    const regions = new RegionsPlugin();
    regionsRef.current = regions;

    const ws = WaveSurfer.create({
      container: waveformRef.current,
      waveColor: "hsl(var(--muted-foreground) / 0.3)",
      progressColor: "hsl(var(--primary))",
      cursorColor: "hsl(var(--primary))",
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      height: 120,
      normalize: true,
      plugins: [regions],
    });

    ws.on("play", () => setPlaying(true));
    ws.on("pause", () => setPlaying(false));
    ws.on("timeupdate", (t: number) => setCurrentTime(t));
    ws.on("decode", (d: number) => setDuration(d));
    ws.on("error", (e: any) => console.error("WaveSurfer error:", e));

    wsRef.current = ws;

    return () => {
      ws.destroy();
      wsRef.current = null;
    };
  }, [open]);

  // 裁剪音频 WaveSurfer 初始化
  useEffect(() => {
    if (!trimmedPath || !trimmedWaveformRef.current) return;

    const tw = WaveSurfer.create({
      container: trimmedWaveformRef.current,
      waveColor: "hsl(var(--amber-500) / 0.3)",
      progressColor: "hsl(var(--amber-500))",
      cursorColor: "hsl(var(--amber-500))",
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      height: 80,
      normalize: true,
    });

    tw.on("play", () => setTrimmedPlaying(true));
    tw.on("pause", () => setTrimmedPlaying(false));
    tw.on("timeupdate", (t: number) => setTrimmedCurrentTime(t));
    tw.on("decode", (d: number) => setTrimmedDuration(d));
    tw.on("error", (e: any) => console.error("Trimmed WaveSurfer error:", e));

    tw.load(`/api/files/stream?path=${encodeURIComponent(trimmedPath)}`);
    trimmedWsRef.current = tw;

    return () => {
      tw.destroy();
      trimmedWsRef.current = null;
    };
  }, [trimmedPath]);

  // 选择文件后加载波形
  const loadFile = useCallback(async (file: AudioFile) => {
    setSelectedFile(file);
    setTrimmedPath(null);
    trimmedWsRef.current?.destroy();
    trimmedWsRef.current = null;
    const ws = wsRef.current;
    if (!ws) return;
    try {
      const url = `/api/files/stream?path=${encodeURIComponent(file.path)}`;
      console.log("Loading audio - file.path:", file.path);
      console.log("Loading audio - url:", url);
      ws.load(url);
      regionsRef.current?.clearRegions();
      setPlaying(false);
      setCurrentTime(0);
      setDuration(0);
    } catch (err) {
      console.error("Load audio failed:", err);
    }
  }, []);

  // 打开文件夹选择
  const pickFolder = async () => {
    try {
      const res = await axios.post("/api/files/native-dialog", {
        type: "folder",
        title: "选择音频文件夹",
      }, { timeout: 60000 });
      if (res.data.path) {
        setFolderPath(res.data.path);
        setRecentFolders(saveRecentFolder(res.data.path));
        scanFolder(res.data.path, recursive);
      }
    } catch {
      // 用户取消
    }
  };

  // 点击最近文件夹
  const openRecentFolder = (path: string) => {
    setFolderPath(path);
    setRecentFolders(saveRecentFolder(path));
    scanFolder(path, recursive);
  };

  // 移除最近文件夹
  const removeRecentFolder = (path: string) => {
    const list = recentFolders.filter((p) => p !== path);
    localStorage.setItem(RECENT_FOLDERS_KEY, JSON.stringify(list));
    setRecentFolders(list);
  };

  // 扫描音频文件
  const scanFolder = async (path: string, rec: boolean) => {
    setScanning(true);
    try {
      const res = await axios.post("/api/files/scan-audio", { path, recursive: rec });
      console.log("scan-audio result:", res.data.files?.slice(0, 3));
      setFiles(res.data.files || []);
    } catch {
      setFiles([]);
    }
    setScanning(false);
  };

  // 递归选项变化时重新扫描
  useEffect(() => {
    if (folderPath) scanFolder(folderPath, recursive);
  }, [recursive]);

  // 播放/暂停
  const togglePlay = () => wsRef.current?.playPause();

  // 添加裁剪区域
  const addTrimRegion = () => {
    const ws = wsRef.current;
    const regions = regionsRef.current;
    if (!ws || !regions) return;
    regions.clearRegions();
    const dur = ws.getDuration();
    if (dur <= 0) return;
    const start = Math.max(0, dur * 0.1);
    const end = dur * 0.9;
    regions.addRegion({
      start,
      end,
      color: "hsl(var(--primary) / 0.2)",
      drag: true,
      resize: true,
    });
  };

  // 保存裁剪
  const saveTrim = async () => {
    const regions = regionsRef.current;
    const file = selectedFile;
    if (!regions || !file) return;
    const region = regions.getRegions()[0];
    if (!region) return;
    setTrimming(true);
    try {
      const res = await axios.post("/api/files/trim-audio", {
        source_path: file.path,
        start: region.start,
        end: region.end,
      });
      if (res.data.output_path) {
        setTrimmedPath(res.data.output_path);
        regions.clearRegions();
      }
    } catch (err) {
      console.error("Trim failed:", err);
    }
    setTrimming(false);
  };

  // 确认选择
  const confirm = () => {
    const path = trimmedPath || selectedFile?.path;
    if (path) {
      onSelect(path);
      onClose();
    }
  };

  if (!open) return null;

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  };

  const formatTime = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, "0")}`;
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onMouseDown={(e) => e.stopPropagation()}>
      <div className="bg-card border border-border/50 rounded-xl shadow-2xl w-[900px] max-h-[85vh] flex flex-col" onMouseDown={(e) => e.stopPropagation()}>
        {/* 头部 */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border/30">
          <h3 className="text-sm font-semibold flex items-center gap-2">
            <Music className="w-4 h-4 text-primary" />
            音频选择器
          </h3>
          <button onClick={onClose} className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary/60 transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* 最近访问文件夹 */}
        {recentFolders.length > 0 && (
          <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border/20 bg-secondary/10">
            <Clock className="w-3 h-3 text-muted-foreground flex-shrink-0" />
            <span className="text-[10px] text-muted-foreground flex-shrink-0">最近:</span>
            <div className="flex items-center gap-1.5 flex-1 min-w-0 overflow-x-auto">
              {recentFolders.map((fp) => {
                const isActive = fp === folderPath;
                const folderName = fp.split(/[/\\]/).filter(Boolean).pop() || fp;
                return (
                  <button
                    key={fp}
                    onClick={() => openRecentFolder(fp)}
                    title={fp}
                    className={`group relative flex items-center gap-1.5 px-2.5 py-1 text-[11px] rounded-md border transition-all flex-shrink-0 max-w-[150px] ${
                      isActive
                        ? "bg-primary/10 border-primary/30 text-primary"
                        : "bg-background/60 border-border/40 text-muted-foreground hover:bg-primary/5 hover:border-primary/30 hover:text-foreground"
                    }`}
                  >
                    <FolderOpen className="w-3 h-3 flex-shrink-0" />
                    <span className="truncate">{folderName}</span>
                    <span
                      role="button"
                      className="opacity-0 group-hover:opacity-100 -mr-1 ml-0.5 text-muted-foreground/50 hover:text-red-500 transition-all flex-shrink-0"
                      onClick={(e) => { e.stopPropagation(); removeRecentFolder(fp); }}
                    >
                      <X className="w-2.5 h-2.5" />
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* 文件夹选择 */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border/20 bg-secondary/30">
          <button
            onClick={pickFolder}
            className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium rounded-lg border border-border/50 bg-background/80 hover:bg-primary/10 hover:border-primary/30 transition-all"
          >
            <FolderOpen className="w-3.5 h-3.5" />
            选择文件夹
          </button>
          <div className="flex-1 text-xs text-muted-foreground truncate">
            {folderPath || "未选择文件夹"}
          </div>
          <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer">
            <input
              type="checkbox"
              checked={recursive}
              onChange={(e) => setRecursive(e.target.checked)}
              className="w-3.5 h-3.5 rounded border-border/60 accent-primary"
            />
            递归子目录
          </label>
        </div>

        {/* 主体：左列表 + 右预览 */}
        <div className="flex flex-1 min-h-0">
          {/* 左侧文件列表 */}
          <div className="w-[260px] border-r border-border/30 flex flex-col overflow-hidden">
            <div className="px-3 py-2 text-[11px] font-medium text-muted-foreground uppercase tracking-wider border-b border-border/20">
              音频文件 ({files.length})
            </div>
            <div className="flex-1 overflow-y-auto">
              {scanning ? (
                <div className="flex items-center justify-center py-8 text-muted-foreground">
                  <Loader2 className="w-4 h-4 animate-spin mr-2" />
                  扫描中...
                </div>
              ) : files.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-8 text-muted-foreground/60">
                  <FolderClosed className="w-8 h-8 mb-2" />
                  <span className="text-xs">选择文件夹扫描音频</span>
                </div>
              ) : (
                files.map((f, i) => (
                  <button
                    key={i}
                    onClick={() => loadFile(f)}
                    className={`w-full text-left px-3 py-2 text-xs border-b border-border/10 hover:bg-primary/5 transition-colors ${
                      selectedFile?.path === f.path ? "bg-primary/10 border-l-2 border-l-primary" : ""
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <Music className="w-3 h-3 text-muted-foreground flex-shrink-0" />
                      <span className="truncate flex-1">{f.name}</span>
                    </div>
                    <div className="text-[10px] text-muted-foreground/60 mt-0.5 ml-5">
                      {formatSize(f.size)}
                    </div>
                  </button>
                ))
              )}
            </div>
          </div>

          {/* 右侧频谱预览 */}
          <div className="flex-1 flex flex-col p-4 overflow-y-auto">
            {selectedFile && (
              <div className="text-xs font-medium text-muted-foreground mb-2 truncate">
                {selectedFile.name}
              </div>
            )}
            {/* 波形容器 - 始终渲染以便 WaveSurfer 初始化 */}
            <div ref={waveformRef} className={`w-full rounded-lg bg-secondary/30 border border-border/20 overflow-hidden ${selectedFile ? "" : "hidden"}`} />
            {!selectedFile && (
              <div className="flex-1 flex items-center justify-center text-muted-foreground/40">
                <div className="text-center">
                  <Music className="w-12 h-12 mx-auto mb-3 opacity-30" />
                  <span className="text-sm">选择左侧音频文件预览</span>
                </div>
              </div>
            )}
            {/* 控制栏 */}
            {selectedFile && (
              <div className="flex items-center gap-3 mt-3">
                <button
                  onClick={togglePlay}
                  className="w-8 h-8 rounded-lg flex items-center justify-center bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
                >
                  {playing ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
                </button>
                <span className="text-[11px] text-muted-foreground font-mono">
                  {formatTime(currentTime)} / {formatTime(duration)}
                </span>
                <div className="flex-1" />
                <button
                  onClick={addTrimRegion}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium rounded-lg border border-border/50 hover:bg-amber-500/10 hover:border-amber-500/30 hover:text-amber-600 transition-all"
                >
                  <Scissors className="w-3 h-3" />
                  裁剪
                </button>
                <button
                  onClick={saveTrim}
                  disabled={trimming || !regionsRef.current?.getRegions()?.length}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium rounded-lg border border-border/50 hover:bg-primary/10 hover:border-primary/30 hover:text-primary transition-all disabled:opacity-40"
                >
                  {trimming ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
                  保存裁剪
                </button>
              </div>
            )}
            {/* 裁剪音频预览 */}
            {trimmedPath && (
              <div className="mt-4 pt-3 border-t border-border/20">
                <div className="flex items-center gap-2 mb-2">
                  <Scissors className="w-3 h-3 text-amber-500" />
                  <span className="text-xs font-medium text-amber-600">裁剪结果预览</span>
                </div>
                <div ref={trimmedWaveformRef} className="w-full rounded-lg bg-amber-500/5 border border-amber-500/20 overflow-hidden" />
                <div className="flex items-center gap-3 mt-2">
                  <button
                    onClick={() => trimmedWsRef.current?.playPause()}
                    className="w-7 h-7 rounded-lg flex items-center justify-center bg-amber-500/10 text-amber-600 hover:bg-amber-500/20 transition-colors"
                  >
                    {trimmedPlaying ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
                  </button>
                  <span className="text-[11px] text-muted-foreground font-mono">
                    {formatTime(trimmedCurrentTime)} / {formatTime(trimmedDuration)}
                  </span>
                  <div className="flex-1" />
                  <span className="text-[10px] text-muted-foreground/60 truncate max-w-[200px]" title={trimmedPath}>
                    {trimmedPath.split(/[/\\]/).pop()}
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* 底部按钮 */}
        <div className="flex items-center justify-end gap-2 px-4 py-3 border-t border-border/30">
          <button
            onClick={onClose}
            className="px-4 py-2 text-xs font-medium rounded-lg border border-border/50 text-muted-foreground hover:bg-secondary/60 transition-colors"
          >
            取消
          </button>
          <button
            onClick={confirm}
            disabled={!selectedFile}
            className="px-4 py-2 text-xs font-medium rounded-lg bg-primary text-primary-foreground hover:opacity-90 transition-opacity disabled:opacity-40"
          >
            确认选择
          </button>
        </div>
      </div>
    </div>
  );
}

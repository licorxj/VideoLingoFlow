import { useState, useEffect, useRef, useCallback } from "react";
import { Terminal, Trash2, Download, Pause, Play, Search, ChevronDown, Wifi, WifiOff, Logs as LogsIcon } from "lucide-react";
import { getWebSocketUrl } from "@/api/ws";
import { PageHeader } from "@/components/shared/PageHeader";
import { PageBackground } from "@/components/shared/PageBackground";
import { cn } from "@/lib/utils";

interface LogEntry {
  ts: number;
  level: string;
  msg: string;
  source?: string;
}

type LogTag = "all" | "task" | "http" | "system" | "file";

const LEVEL_COLORS: Record<string, string> = {
  info: "\u001b[32m",
  error: "\u001b[31m",
  warning: "\u001b[33m",
  debug: "\u001b[36m",
};

const LEVEL_BADGE_COLORS: Record<string, string> = {
  info: "bg-success/15 text-success border-success/30",
  error: "bg-destructive/15 text-destructive border-destructive/30",
  warning: "bg-warning/15 text-warning border-warning/30",
  debug: "bg-info/15 text-info border-info/30",
};

const TAG_BADGE_COLORS: Record<Exclude<LogTag, "all">, string> = {
  task: "bg-ai/15 text-ai border-ai/30",
  http: "bg-info/15 text-info border-info/30",
  system: "bg-muted text-muted-foreground border-border/40",
  file: "bg-warning/15 text-warning border-warning/30",
};

function detectLogTags(log: LogEntry): Exclude<LogTag, "all">[] {
  const text = `${log.msg} ${log.source || ""}`.toLowerCase();
  const tags = new Set<Exclude<LogTag, "all">>();
  if (
    /\[tasktrace\]|\[scheduler\]|工作流执行|执行节点|节点完成|节点失败|节点跳过|投递任务|启动批次|停止批次|继续单任务|继续未完成任务|追加任务|注册任务|等待在途任务释放|排队|任务 |批次 /.test(text)
  ) {
    tags.add("task");
  }
  if (/http\/|uvicorn|127\.0\.0\.1|localhost|\/api\//.test(text)) {
    tags.add("http");
  }
  if ((log.source || "").toLowerCase() === "file") {
    tags.add("file");
  }
  if (tags.size === 0 || /started|initialized|loaded|drainer|redirectors|database/.test(text)) {
    tags.add("system");
  }
  return [...tags];
}

export default function Logs() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [connected, setConnected] = useState(false);
  const [paused, setPaused] = useState(false);
  const [filter, setFilter] = useState("");
  const [levelFilter, setLevelFilter] = useState<string>("all");
  const [tagFilter, setTagFilter] = useState<LogTag>("all");
  const [showToolbar, setShowToolbar] = useState(true);
  const [followTail, setFollowTail] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const connect = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState <= 1) return;
    const ws = new WebSocket(getWebSocketUrl("/ws/logs"));
    wsRef.current = ws;
    ws.onopen = () => setConnected(true);
    ws.onclose = () => {
      setConnected(false);
      setTimeout(connect, 3000);
    };
    ws.onerror = () => ws.close();
    ws.onmessage = (e) => {
      if (paused) return;
      try {
        const entry: LogEntry = JSON.parse(e.data);
        setLogs((prev) => {
          const next = [...prev, entry];
          return next.length > 5000 ? next.slice(-5000) : next;
        });
      } catch {}
    };
  }, [paused]);

  useEffect(() => {
    connect();
    return () => {
      wsRef.current?.close();
    };
  }, [connect]);

  useEffect(() => {
    const el = containerRef.current;
    if (el && followTail) {
      el.scrollTop = el.scrollHeight;
    }
  }, [logs, followTail]);

  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    setFollowTail(el.scrollHeight - el.scrollTop - el.clientHeight < 50);
  };

  const filtered = logs.filter((l) => {
    if (levelFilter !== "all" && l.level !== levelFilter) return false;
    if (tagFilter !== "all" && !detectLogTags(l).includes(tagFilter)) return false;
    if (filter && !l.msg.toLowerCase().includes(filter.toLowerCase())) return false;
    return true;
  });

  const clearLogs = () => setLogs([]);

  const exportLogs = () => {
    const text = filtered
      .map((l) => {
        const d = new Date(l.ts * 1000);
        const ts = d.toLocaleTimeString("zh-CN", { hour12: false });
        return "[" + ts + "] [" + l.level.toUpperCase() + "] " + l.msg;
      })
      .join("\n");
    const blob = new Blob([text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "videolingo_logs_" + new Date().toISOString().slice(0, 10) + ".txt";
    a.click();
    URL.revokeObjectURL(url);
  };

  const formatTime = (ts: number) => {
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString("zh-CN", {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  };

  const scrollToBottom = () => {
    const el = containerRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
      setFollowTail(true);
    }
  };

  const levelCounts = logs.reduce(
    (acc, l) => {
      acc[l.level] = (acc[l.level] || 0) + 1;
      return acc;
    },
    {} as Record<string, number>
  );

  const tagCounts = logs.reduce(
    (acc, log) => {
      for (const tag of detectLogTags(log)) {
        acc[tag] = (acc[tag] || 0) + 1;
      }
      return acc;
    },
    {} as Record<Exclude<LogTag, "all">, number>
  );

  return (
    <PageBackground tone="history" className="flex flex-col h-[calc(100vh-64px)]">
      {/* Header */}
      <PageHeader
        icon={Terminal}
        title="后台终端"
        detail="实时输出流"
        actions={
          <div className="flex items-center gap-1.5">
            <div className={cn(
              "flex items-center gap-1.5 px-2 py-1 rounded-full border text-[10px] font-medium",
              connected
                ? "border-success/30 bg-success/10 text-success"
                : "border-destructive/30 bg-destructive/10 text-destructive"
            )}>
              {connected ? <Wifi className="w-2.5 h-2.5" /> : <WifiOff className="w-2.5 h-2.5" />}
              {connected ? "已连接" : "未连接"}
            </div>
            {/* Level filter chips */}
            {(["info", "error", "warning", "debug"] as const).map((lvl) => (
              <button key={lvl} onClick={() => setLevelFilter(levelFilter === lvl ? "all" : lvl)}
                className={cn(
                  "px-2 py-0.5 text-[10px] font-semibold rounded-md border transition-all",
                  levelFilter === lvl ? LEVEL_BADGE_COLORS[lvl] : "border-border/30 text-muted-foreground/60 hover:text-muted-foreground hover:border-border/60"
                )}>
                {lvl.toUpperCase()} {levelCounts[lvl] ? <span className="opacity-60">{levelCounts[lvl]}</span> : null}
              </button>
            ))}
            <div className="w-px h-4 bg-border/30 mx-1" />
            {(["task", "http", "system", "file"] as const).map((tag) => (
              <button
                key={tag}
                onClick={() => setTagFilter(tagFilter === tag ? "all" : tag)}
                className={cn(
                  "px-2 py-0.5 text-[10px] font-semibold rounded-md border transition-all",
                  tagFilter === tag ? TAG_BADGE_COLORS[tag] : "border-border/30 text-muted-foreground/60 hover:text-muted-foreground hover:border-border/60"
                )}
                title={tag === "task" ? "任务跟踪" : tag === "http" ? "请求访问" : tag === "file" ? "日志文件" : "系统输出"}
              >
                {tag === "task" ? "任务跟踪" : tag.toUpperCase()} {tagCounts[tag] ? <span className="opacity-60">{tagCounts[tag]}</span> : null}
              </button>
            ))}
            <div className="w-px h-4 bg-border/30 mx-1" />
            <button onClick={() => setPaused(!paused)}
              className={cn(
                "p-1.5 rounded-md border transition-all",
                paused ? "border-warning/30 bg-warning/10 text-warning" : "border-border/30 text-muted-foreground hover:text-foreground hover:border-border/60"
              )} title={paused ? "继续" : "暂停"}>
              {paused ? <Play className="w-3.5 h-3.5" /> : <Pause className="w-3.5 h-3.5" />}
            </button>
            <button onClick={clearLogs}
              className="p-1.5 rounded-md border border-border/30 text-muted-foreground hover:text-foreground hover:border-border/60 transition-all"
              title="清空">
              <Trash2 className="w-3.5 h-3.5" />
            </button>
            <button onClick={exportLogs}
              className="p-1.5 rounded-md border border-border/30 text-muted-foreground hover:text-foreground hover:border-border/60 transition-all"
              title="导出">
              <Download className="w-3.5 h-3.5" />
            </button>
            <button onClick={() => setShowToolbar(!showToolbar)}
              className="p-1.5 rounded-md border border-border/30 text-muted-foreground hover:text-foreground hover:border-border/60 transition-all"
              title="搜索">
              <Search className="w-3.5 h-3.5" />
            </button>
          </div>
        }
      />

      {/* Search bar */}
      {showToolbar && (
        <div className="flex items-center gap-2 px-4 py-2 border-b border-border/30 bg-card/30 flex-shrink-0">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3 h-3 text-muted-foreground/50" />
            <input ref={inputRef} type="text" value={filter} onChange={(e) => setFilter(e.target.value)}
              placeholder={"搜索日志内容..."}
              className="w-full pl-8 pr-3 py-1 text-xs border border-border/40 rounded-md bg-background/30 focus:border-primary/50 focus:ring-1 focus:ring-primary/10 outline-none font-mono" />
          </div>
          <span className="text-[10px] text-muted-foreground/50 font-mono">
            {filtered.length === logs.length ? logs.length + " 条" : filtered.length + "/" + logs.length + " 条"}
          </span>
          <button
            onClick={() => setFollowTail((value) => !value)}
            className={cn(
              "px-2 py-1 text-[10px] rounded-md border transition-all",
              followTail
                ? "border-success/30 bg-success/10 text-success"
                : "border-border/30 text-muted-foreground hover:text-foreground hover:border-border/60"
            )}
            title="收到新日志时自动滚动到最底部"
          >
            自动滚动 {followTail ? "开" : "关"}
          </button>
          {filter && (
            <button onClick={() => setFilter("")}
              className="text-[10px] text-muted-foreground/50 hover:text-muted-foreground">
              清除筛选
            </button>
          )}
        </div>
      )}

      {/* Terminal area */}
      <div ref={containerRef} onScroll={handleScroll}
        className="flex-1 overflow-y-auto bg-white font-mono text-[14px] leading-[1.7] min-h-0">
        {filtered.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center space-y-3 opacity-30">
              <Terminal className="w-10 h-10 mx-auto text-success" />
              <div className="space-y-1">
                <p className="text-sm text-success/80 font-medium">
                  {connected ? "等待输出..." : "正在连接后端服务..."}
                </p>
                <p className="text-[10px] text-muted-foreground/40">
                  {connected ? "后端终端输出将实时显示在此处" : "尝试重连中..."}
                </p>
              </div>
            </div>
          </div>
        ) : (
          <div className="py-1">
            {filtered.map((log, i) => {
              const timeStr = formatTime(log.ts);
              const levelStr = log.level.toUpperCase().padEnd(7);
              const tags = detectLogTags(log);
              const levelColor =
                log.level === "error" ? "text-destructive" :
                log.level === "warning" ? "text-warning" :
                log.level === "debug" ? "text-info" :
                "text-success";
              const msgColor =
                log.level === "error" ? "text-destructive/90" :
                log.level === "warning" ? "text-warning/90" :
                log.level === "debug" ? "text-info/80" :
                "text-foreground/70";
              return (
                <div key={i}
                  className={cn(
                    "flex px-3 py-px hover:bg-white/[0.03] group transition-colors duration-75",
                    log.level === "error" ? "bg-destructive/[0.06]" : log.level === "warning" ? "bg-warning/[0.04]" : ""
                  )}>
                  <span className="text-muted-foreground/40 select-none flex-shrink-0 w-[16px] text-right pr-3 text-[10px] leading-[1.7] group-hover:text-muted-foreground/70">
                    {i + 1}
                  </span>
                  <span className="text-muted-foreground/50 select-none flex-shrink-0 w-[68px] leading-[1.7]">
                    {timeStr}
                  </span>
                  <span className={cn("select-none flex-shrink-0 w-[56px] font-bold leading-[1.7]", levelColor)}>
                    {levelStr}
                  </span>
                  <span className="flex-shrink-0 w-[88px] leading-[1.7] flex items-start pt-[2px]">
                    {tags.includes("task") ? (
                      <span className="inline-flex items-center gap-1 rounded border border-ai/30 bg-ai/10 px-1.5 py-0.5 text-[10px] text-ai">
                        <LogsIcon className="w-2.5 h-2.5" /> 任务
                      </span>
                    ) : tags.includes("http") ? (
                      <span className="inline-flex rounded border border-info/30 bg-info/10 px-1.5 py-0.5 text-[10px] text-info">
                        HTTP
                      </span>
                    ) : tags.includes("file") ? (
                      <span className="inline-flex rounded border border-warning/30 bg-warning/10 px-1.5 py-0.5 text-[10px] text-warning">
                        FILE
                      </span>
                    ) : (
                      <span className="inline-flex rounded border border-border/40 bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                        SYS
                      </span>
                    )}
                  </span>
                  <span className={cn("flex-1 break-all whitespace-pre-wrap leading-[1.7]", msgColor)}>
                    {log.msg}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Bottom status bar */}
      <div className="flex items-center justify-between px-4 py-1.5 border-t border-border/30 bg-card/50 flex-shrink-0 text-[10px] text-muted-foreground/50 font-mono">
        <div className="flex items-center gap-3">
          <span>输出 {logs.length} 条</span>
          {filter && <span>已筛选 {filtered.length} 条</span>}
          {paused && <span className="text-warning/70">▁▁ 已暂停</span>}
          <span className={followTail ? "text-success/70" : "text-muted-foreground/40"}>{followTail ? "跟随底部" : "已脱离底部"}</span>
        </div>
        <div className="flex items-center gap-3">
          {levelCounts.error ? <span className="text-destructive/60">错误 {levelCounts.error}</span> : null}
          {levelCounts.warning ? <span className="text-warning/60">警告 {levelCounts.warning}</span> : null}
          <button onClick={scrollToBottom}
            className="flex items-center gap-0.5 hover:text-muted-foreground transition-colors">
            <ChevronDown className="w-3 h-3" /> 到底
          </button>
        </div>
      </div>
    </PageBackground>
  );
}

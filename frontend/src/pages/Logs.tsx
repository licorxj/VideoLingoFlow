import { useState, useEffect, useRef, useCallback } from "react";
import { Terminal, Trash2, Download, Pause, Play, Search, ChevronDown, Wifi, WifiOff } from "lucide-react";
import { getWebSocketUrl } from "@/api/ws";

interface LogEntry {
  ts: number;
  level: string;
  msg: string;
  source?: string;
}

const LEVEL_COLORS: Record<string, string> = {
  info: "\u001b[32m",
  error: "\u001b[31m",
  warning: "\u001b[33m",
  debug: "\u001b[36m",
};

const LEVEL_BADGE_COLORS: Record<string, string> = {
  info: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  error: "bg-red-500/15 text-red-400 border-red-500/30",
  warning: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30",
  debug: "bg-blue-500/15 text-blue-400 border-blue-500/30",
};

export default function Logs() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [connected, setConnected] = useState(false);
  const [paused, setPaused] = useState(false);
  const [filter, setFilter] = useState("");
  const [levelFilter, setLevelFilter] = useState<string>("all");
  const [showToolbar, setShowToolbar] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const autoScrollRef = useRef(true);
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
    if (el && autoScrollRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [logs]);

  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    autoScrollRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 50;
  };

  const filtered = logs.filter((l) => {
    if (levelFilter !== "all" && l.level !== levelFilter) return false;
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
      autoScrollRef.current = true;
    }
  };

  const levelCounts = logs.reduce(
    (acc, l) => {
      acc[l.level] = (acc[l.level] || 0) + 1;
      return acc;
    },
    {} as Record<string, number>
  );

  return (
    <div className="flex flex-col h-[calc(100vh-64px)]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border/40 bg-card/50 flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
              <Terminal className="w-4 h-4 text-primary" />
            </div>
            <div>
              <h1 className="text-base font-bold tracking-tight">{"后台终端"}</h1>
              <p className="text-[10px] text-muted-foreground">{"实时输出流"}</p>
            </div>
          </div>
          <div className="flex items-center gap-1.5 px-2 py-1 rounded-full border text-[10px] font-medium" 
            style={{
              borderColor: connected ? "rgb(34 197 94 / 0.3)" : "rgb(239 68 68 / 0.3)",
              backgroundColor: connected ? "rgb(34 197 94 / 0.08)" : "rgb(239 68 68 / 0.08)",
              color: connected ? "#4ade80" : "#f87171"
            }}>
            {connected ? <Wifi className="w-2.5 h-2.5" /> : <WifiOff className="w-2.5 h-2.5" />}
            {connected ? "已连接" : "未连接"}
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          {/* Level filter chips */}
          {(["info", "error", "warning", "debug"] as const).map((lvl) => (
            <button key={lvl} onClick={() => setLevelFilter(levelFilter === lvl ? "all" : lvl)}
              className={"px-2 py-0.5 text-[10px] font-semibold rounded-md border transition-all " +
                (levelFilter === lvl ? LEVEL_BADGE_COLORS[lvl] : "border-border/30 text-muted-foreground/60 hover:text-muted-foreground hover:border-border/60")
              }>
              {lvl.toUpperCase()} {levelCounts[lvl] ? <span className="opacity-60">{levelCounts[lvl]}</span> : null}
            </button>
          ))}
          <div className="w-px h-4 bg-border/30 mx-1" />
          <button onClick={() => setPaused(!paused)}
            className={"p-1.5 rounded-md border transition-all " +
              (paused ? "border-yellow-500/30 bg-yellow-500/10 text-yellow-400" : "border-border/30 text-muted-foreground hover:text-foreground hover:border-border/60")
            } title={paused ? "继续" : "暂停"}>
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
      </div>

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
        className="flex-1 overflow-y-auto bg-[#0a0e14] font-mono text-[12px] leading-[1.7] min-h-0">
        {filtered.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center space-y-3 opacity-30">
              <Terminal className="w-10 h-10 mx-auto text-emerald-500" />
              <div className="space-y-1">
                <p className="text-sm text-emerald-400/80 font-medium">
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
              const levelColor =
                log.level === "error" ? "text-red-400" :
                log.level === "warning" ? "text-yellow-400" :
                log.level === "debug" ? "text-cyan-400" :
                "text-emerald-400";
              const msgColor =
                log.level === "error" ? "text-red-300/90" :
                log.level === "warning" ? "text-yellow-300/90" :
                log.level === "debug" ? "text-cyan-300/80" :
                "text-gray-300";
              return (
                <div key={i}
                  className={"flex px-3 py-px hover:bg-white/[0.03] group transition-colors duration-75" +
                    (log.level === "error" ? " bg-red-500/[0.04]" : log.level === "warning" ? " bg-yellow-500/[0.02]" : "")
                  }>
                  <span className="text-gray-600 select-none flex-shrink-0 w-[16px] text-right pr-3 text-[10px] leading-[1.7] group-hover:text-gray-500">
                    {i + 1}
                  </span>
                  <span className="text-gray-600 select-none flex-shrink-0 w-[68px] leading-[1.7]">
                    {timeStr}
                  </span>
                  <span className={"select-none flex-shrink-0 w-[56px] font-bold leading-[1.7] " + levelColor}>
                    {levelStr}
                  </span>
                  <span className={"flex-1 break-all whitespace-pre-wrap leading-[1.7] " + msgColor}>
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
          {paused && <span className="text-yellow-400/70">▁▁ 已暂停</span>}
        </div>
        <div className="flex items-center gap-3">
          {levelCounts.error ? <span className="text-red-400/60">错误 {levelCounts.error}</span> : null}
          {levelCounts.warning ? <span className="text-yellow-400/60">警告 {levelCounts.warning}</span> : null}
          <button onClick={scrollToBottom}
            className="flex items-center gap-0.5 hover:text-muted-foreground transition-colors">
            <ChevronDown className="w-3 h-3" /> 到底
          </button>
        </div>
      </div>
    </div>
  );
}

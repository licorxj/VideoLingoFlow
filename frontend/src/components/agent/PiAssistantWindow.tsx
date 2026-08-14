import { FormEvent, KeyboardEvent, PointerEvent, useCallback, useEffect, useRef, useState } from "react";
import { Bot, ChevronDown, ChevronLeft, ChevronRight, FileArchive, FolderTree, Grip, History, Loader2, Maximize2, Minimize2, Minus, Paperclip, Plus, Send, Settings2, Sparkles, Square, Trash2, Waypoints, Workflow, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import AgentSettings from "@/components/settings/AgentSettings";
import { normalizeApiError } from "@/api/client";
import { nativeFileDialog } from "@/api/files";
import { piRpcApi, type PiEvent, type PiHistorySession } from "@/api/piRpc";
import { cn } from "@/lib/utils";

type AssistantKind = "general" | "node" | "workflow" | "execution" | "files" | "publish" | "installer";
type ChatMessage = { role: "user" | "assistant"; text: string; thinking?: string };
type WindowPosition = { left: number; top: number };
type WindowSize = { width: number; height: number };

const ASSISTANTS: { id: AssistantKind; label: string; description: string; icon: typeof Sparkles; prompt: string }[] = [
  { id: "general", label: "通用任务", description: "分析与建议", icon: Sparkles, prompt: "你是 VideoLingo 通用任务助手。用清晰、可操作的中文协助用户分析当前工作。" },
  { id: "node", label: "节点创建助手", description: "设计节点输入输出", icon: Waypoints, prompt: "你是 VideoLingo 节点创建助手。帮助用户设计节点职责、输入、输出与配置，不修改文件。" },
  { id: "workflow", label: "工作流编排助手", description: "拆解并组织流程", icon: Workflow, prompt: "你是 VideoLingo 工作流编排助手。帮助用户规划节点顺序、依赖关系、分支与异常处理。" },
  { id: "execution", label: "任务执行助手", description: "定位运行问题", icon: Bot, prompt: "你是 VideoLingo 任务执行助手。帮助解释执行状态、定位阻塞步骤并给出下一步建议。" },
  { id: "files", label: "文件整理助手", description: "梳理素材和产物", icon: FolderTree, prompt: "你是 VideoLingo 文件整理助手。帮助用户规划素材、字幕、音频和导出文件的目录与命名。" },
  { id: "publish", label: "作品发布助手", description: "准备多平台发布", icon: FileArchive, prompt: "你是 VideoLingo 作品发布助手。帮助用户准备标题、简介、封面和多平台发布检查项。" },
  { id: "installer", label: "技能安装助手", description: "安装 Skill / MCP", icon: Sparkles, prompt: "你是 VideoLingo 技能安装助手。帮助用户从暂存目录安装 Skill 或 MCP，并在安装前询问是项目专用还是系统级别。" },
];

export default function PiAssistantWindow({ visible = true, onClose, onMinimize, onReady }: { visible?: boolean; onClose: () => void; onMinimize: () => void; onReady?: () => void }) {
  const [assistant, setAssistant] = useState<AssistantKind>("general");
  const [collapsed, setCollapsed] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [maximized, setMaximized] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("准备就绪");
  const [sessionEpoch, setSessionEpoch] = useState(0);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<PiHistorySession[]>([]);
  const [attachments, setAttachments] = useState<string[]>([]);
  const [mentionMenu, setMentionMenu] = useState<null | { kind: "integration" | "doc"; query: string }>(null);
  const [mentionOptions, setMentionOptions] = useState<{ label: string; value: string; sub: string }[]>([]);
  const mentionAnchorRef = useRef<{ kind: "integration" | "doc"; position: number } | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const inputRef = useRef("");
  const [position, setPosition] = useState<WindowPosition | null>(null);
  const [size, setSize] = useState<WindowSize | null>(null);
  const [dragging, setDragging] = useState(false);
  const [resizing, setResizing] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const sessionsRef = useRef<Partial<Record<AssistantKind, string>>>({});
  const eventSourcesRef = useRef<Partial<Record<AssistantKind, EventSource>>>({});
  const thinkingRef = useRef("");
  const lastSeqRef = useRef(0);
  const dragRef = useRef<{ offsetX: number; offsetY: number; width: number; height: number } | null>(null);
  const resizeRef = useRef<{ left: number; bottom: number } | null>(null);
  const current = ASSISTANTS.find((item) => item.id === assistant) ?? ASSISTANTS[0];
  const rootRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!visible) return;
    const el = rootRef.current;
    if (!el) return;
    // 先清除最小化/关闭动画的 fill 残留（opacity 0 / 收缩位移），避免恢复时窗口卡在透明状态
    el.getAnimations().forEach((animation) => animation.cancel());
    // 从侧栏小π按钮处（窗口左上方）为源点放大并向右移展开
    const animation = el.animate(
      [
        { transform: "translate(-36px, -220px) scale(0.2)", opacity: 0, transformOrigin: "bottom left" },
        { transform: "translate(0, 0) scale(1)", opacity: 1, transformOrigin: "bottom left" },
      ],
      { duration: 380, easing: "cubic-bezier(0.22, 1, 0.36, 1)", fill: "backwards" },
    );
    return () => animation.cancel();
  }, [visible]);

  const runExit = useCallback((kind: "minimize" | "close") => {
    const el = rootRef.current;
    const finish = () => (kind === "minimize" ? onMinimize() : onClose());
    if (!el) return finish();
    // 收缩回侧栏小π按钮处（与展开动画反向）。不带 fill，避免动画结束后残留 opacity 0
    // 导致恢复时窗口卡在透明状态（minimized 隐藏由外层 invisible 类保证）
    const animation = el.animate(
      [
        { transform: "translate(0, 0) scale(1)", opacity: 1, transformOrigin: "bottom left" },
        { transform: "translate(-36px, -220px) scale(0.2)", opacity: 0, transformOrigin: "bottom left" },
      ],
      { duration: 240, easing: "cubic-bezier(0.55, 0, 1, 0.45)" },
    );
    animation.onfinish = finish;
  }, [onClose, onMinimize]);

  const toggleMaximize = useCallback(() => {
    const el = rootRef.current;
    const from = el?.getBoundingClientRect();
    setMaximized((value) => {
      const next = !value;
      requestAnimationFrame(() => requestAnimationFrame(() => {
        if (!el) return;
        const to = el.getBoundingClientRect();
        if (from && to && (from.width !== to.width || from.height !== to.height || from.left !== to.left || from.top !== to.top)) {
          el.animate(
            [
              { transform: `translate(${from.left - to.left}px, ${from.top - to.top}px) scale(${from.width / to.width}, ${from.height / to.height})`, transformOrigin: "0 0" },
              { transform: "translate(0, 0) scale(1, 1)", transformOrigin: "0 0" },
            ],
            { duration: 320, easing: "cubic-bezier(0.22, 1, 0.36, 1)" },
          );
        }
      }));
      return next;
    });
  }, []);

  const commitThinking = useCallback(() => {
    const thinking = thinkingRef.current.trim();
    thinkingRef.current = "";
    if (!thinking) return;
    setMessages((items) => {
      const last = items[items.length - 1];
      if (last?.role === "assistant") return [...items.slice(0, -1), { ...last, thinking }];
      return [...items, { role: "assistant", text: "", thinking }];
    });
  }, []);

  const bindEventSource = useCallback((source: EventSource) => {
    source.addEventListener("pi_event", (event) => {
      const payload = JSON.parse((event as MessageEvent).data) as PiEvent;
      if (typeof payload.seq === "number") lastSeqRef.current = Math.max(lastSeqRef.current, payload.seq);
      if (payload.type === "agent_start") { setBusy(true); setStatus("正在思考"); thinkingRef.current = ""; }
      if (payload.type === "agent_end" || payload.type === "agent_settled") { setBusy(false); setStatus("已连接"); thinkingRef.current = ""; }
      if (payload.type === "pi_error") { setBusy(false); setStatus(payload.error || "Pi 运行失败"); thinkingRef.current = ""; }
      const delta = payload.assistantMessageEvent;
      if (!delta) return;
      if (delta.type === "thinking_start") { thinkingRef.current = ""; }
      else if (delta.type === "thinking_delta" && delta.delta) { thinkingRef.current += delta.delta; }
      else if (delta.type === "thinking_end") { commitThinking(); }
      else if (delta.type === "text_delta" && delta.delta) {
        const text = delta.delta;
        setMessages((items) => {
          const last = items[items.length - 1];
          if (last?.role === "assistant") return [...items.slice(0, -1), { ...last, text: last.text + text }];
          const thinking = thinkingRef.current.trim() || undefined;
          thinkingRef.current = "";
          return [...items, { role: "assistant", text, thinking }];
        });
      }
    });
    source.onerror = () => setStatus("事件连接中断");
  }, [commitThinking]);

  useEffect(() => {
    let disposed = false;
    setStatus("正在连接 Pi");
    piRpcApi.createSession(`agent-${assistant}`, current.prompt).then(({ data }) => {
      if (disposed) return;
      setSessionId(data.session_id);
      sessionIdRef.current = data.session_id;
      sessionsRef.current[assistant] = data.session_id;
      setMessages(data.messages || []);
      lastSeqRef.current = data.seq || 0;
      setStatus("已连接");
      onReady?.();
      const source = new EventSource(`${piRpcApi.eventsUrl(data.session_id)}?after=${lastSeqRef.current}`, { withCredentials: true });
      eventSourceRef.current = source;
      eventSourcesRef.current[assistant]?.close();
      eventSourcesRef.current[assistant] = source;
      bindEventSource(source);
    }).catch((error) => setStatus(normalizeApiError(error).message));
    return () => { disposed = true; };
  }, [assistant, current.prompt, onReady, sessionEpoch, bindEventSource]);

  useEffect(() => () => {
    Object.values(eventSourcesRef.current).forEach((source) => source?.close());
    Object.values(sessionsRef.current).forEach((id) => { if (id) piRpcApi.close(id).catch(() => undefined); });
  }, []);

  const chooseAssistant = async (next: AssistantKind) => {
    if (busy || next === assistant) return;
    eventSourceRef.current?.close();
    const nextSession = sessionsRef.current[next];
    if (nextSession) {
      setSessionId(nextSession);
      sessionIdRef.current = nextSession;
    }
    setMessages([]);
    setAssistant(next);
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const message = input.trim();
    if (!sessionId || !message || busy) return;
    setInput("");
    setAttachments([]);
    thinkingRef.current = "";
    setMessages((items) => [...items, { role: "user", text: message }]);
    setBusy(true);
    setStatus("正在思考");
    try { await piRpcApi.prompt(sessionId, message, undefined, attachments); } catch (error) { setBusy(false); setStatus(normalizeApiError(error).message); }
  };

  const addAttachments = async () => {
    try {
      const paths = await nativeFileDialog("file", "选择要附加给智能体的文件", [], true);
      const list = Array.isArray(paths) ? paths : (paths ? [paths] : []);
      if (list.length) setAttachments((current) => [...new Set([...current, ...list])].slice(0, 20));
    } catch (error) {
      setStatus(normalizeApiError(error).message);
    }
  };

  const openMention = (kind: "integration" | "doc") => {
    if (!mentionAnchorRef.current) {
      const position = textareaRef.current?.selectionStart ?? inputRef.current.length;
      mentionAnchorRef.current = { kind, position };
    }
    setMentionMenu({ kind, query: "" });
    if (kind === "integration") {
      piRpcApi.getSettings().then(({ data }) => {
        const items = [
          ...(data.skills || []).filter((item) => item.enabled).map((item) => ({ label: item.name, value: `@skill:${item.name}`, sub: "Skill" })),
          ...(data.mcps || []).filter((item) => item.enabled).map((item) => ({ label: item.name, value: `@mcp:${item.name}`, sub: "MCP" })),
        ];
        setMentionOptions(items);
      }).catch(() => setMentionOptions([]));
    } else {
      piRpcApi.scan("docs").then(({ data }) => {
        const items = (data as { name: string; path: string }[]).map((doc) => {
          const rel = doc.path.replace(/\\/g, "/").split("/backend/config/agent/docs/")[1];
          return { label: doc.name, value: `&doc:${rel || doc.name}`, sub: "文档" };
        });
        setMentionOptions(items);
      }).catch(() => setMentionOptions([]));
    }
  };

  const pickMention = (option: { value: string }) => {
    const anchor = mentionAnchorRef.current;
    const current = inputRef.current;
    if (anchor) {
      const before = current.slice(0, anchor.position);
      const after = current.slice(anchor.position + (mentionMenu?.query.length || 0));
      const next = before + option.value + after;
      inputRef.current = next;
      setInput(next);
    } else {
      const next = current + option.value;
      inputRef.current = next;
      setInput(next);
    }
    setMentionMenu(null);
    mentionAnchorRef.current = null;
    requestAnimationFrame(() => textareaRef.current?.focus());
  };

  const stop = async () => {
    if (!sessionId) return;
    await piRpcApi.abort(sessionId).catch(() => undefined);
    setBusy(false);
    setStatus("已停止");
  };

  const endConversation = async () => {
    if (!sessionId) return;
    eventSourceRef.current?.close();
    await piRpcApi.close(sessionId).catch(() => undefined);
    delete sessionsRef.current[assistant];
    sessionIdRef.current = null;
    setSessionId(null);
    setMessages([]);
    setStatus("对话已结束");
  };

  const createConversation = async () => {
    if (busy || !sessionId) return;
    eventSourceRef.current?.close();
    await piRpcApi.close(sessionId).catch(() => undefined);
    delete sessionsRef.current[assistant];
    sessionIdRef.current = null;
    setSessionId(null);
    setMessages([]);
    setStatus("正在新建对话");
    setSessionEpoch((value) => value + 1);
  };

  const clearContext = async () => {
    if (busy || !sessionId) return;
    await piRpcApi.clear(sessionId);
    setMessages([]);
    setStatus("上下文已清空");
  };

  const loadHistory = async () => {
    if (!sessionId) return;
    const { data } = await piRpcApi.history(sessionId);
    setHistory(data);
    setHistoryOpen((value) => !value);
  };

  const selectHistory = async (item: PiHistorySession) => {
    eventSourceRef.current?.close();
    if (sessionId) {
      const { data } = await piRpcApi.restoreHistory(sessionId, item.id);
      sessionsRef.current[assistant] = data.session_id;
      sessionIdRef.current = data.session_id;
      setSessionId(data.session_id);
      setMessages(data.messages || item.messages);
      lastSeqRef.current = data.seq || 0;
      const source = new EventSource(`${piRpcApi.eventsUrl(data.session_id)}?after=${lastSeqRef.current}`, { withCredentials: true });
      eventSourceRef.current = source;
      bindEventSource(source);
    }
    setStatus("已恢复历史会话");
    setHistoryOpen(false);
  };

  const removeHistory = async (historyId: number) => {
    if (!sessionId) return;
    try {
      const { data } = await piRpcApi.deleteHistory(sessionId, historyId);
      if (data.success) {
        setHistory((items) => items.filter((item) => item.id !== historyId));
        setStatus("历史会话已删除");
      }
    } catch (error) {
      setStatus(normalizeApiError(error).message);
    }
  };

  const handleInputKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Escape" && mentionMenu) {
      event.preventDefault();
      setMentionMenu(null);
      mentionAnchorRef.current = null;
      return;
    }
    if (event.key !== "Enter" || event.altKey) return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  };

  const handleInputChange = (event: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = event.target.value;
    const cursor = event.target.selectionStart ?? value.length;
    inputRef.current = value;
    setInput(value);
    const last = value[cursor - 1];
    if (last === "@") {
      const position = cursor - 1;
      mentionAnchorRef.current = { kind: "integration", position };
      setMentionMenu({ kind: "integration", query: "" });
      openMention("integration");
    } else if (last === "&") {
      const position = cursor - 1;
      mentionAnchorRef.current = { kind: "doc", position };
      setMentionMenu({ kind: "doc", query: "" });
      openMention("doc");
    } else if (mentionMenu) {
      const anchor = mentionAnchorRef.current;
      const query = anchor && cursor > anchor.position ? value.slice(anchor.position + 1, cursor) : "";
      setMentionMenu((menu) => (menu ? { ...menu, query } : menu));
    }
  };

  const beginDrag = (event: PointerEvent<HTMLElement>) => {
    if (maximized || event.button !== 0) return;
    const rect = event.currentTarget.parentElement?.getBoundingClientRect();
    if (!rect) return;
    dragRef.current = { offsetX: event.clientX - rect.left, offsetY: event.clientY - rect.top, width: rect.width, height: rect.height };
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragging(true);
  };

  const moveDrag = (event: PointerEvent<HTMLElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    const edge = 12;
    setPosition({
      left: Math.min(Math.max(edge, event.clientX - drag.offsetX), Math.max(edge, window.innerWidth - drag.width - edge)),
      top: Math.min(Math.max(edge, event.clientY - drag.offsetY), Math.max(edge, window.innerHeight - drag.height - edge)),
    });
  };

  const endDrag = () => { dragRef.current = null; setDragging(false); };

  const beginResize = (event: PointerEvent<HTMLButtonElement>) => {
    if (maximized || event.button !== 0) return;
    const rect = event.currentTarget.closest("section")?.getBoundingClientRect();
    if (!rect) return;
    resizeRef.current = { left: rect.left, bottom: rect.bottom };
    setResizing(true);
    event.stopPropagation();
  };

  const resizeWindow = (clientX: number, clientY: number) => {
    const resize = resizeRef.current;
    if (!resize) return;
    const edge = 12;
    const right = Math.min(Math.max(resize.left + 620, clientX), window.innerWidth - edge);
    const top = Math.min(Math.max(edge, clientY), resize.bottom - 440);
    setSize({
      width: right - resize.left,
      height: resize.bottom - top,
    });
    setPosition({ left: resize.left, top });
  };

  const endResize = () => { resizeRef.current = null; setResizing(false); };

  useEffect(() => {
    if (!resizing) return;
    const move = (event: globalThis.PointerEvent) => resizeWindow(event.clientX, event.clientY);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", endResize, { once: true });
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", endResize);
    };
  }, [resizing]);

  const windowStyle = maximized ? undefined : { ...(position || {}), ...(size || {}) };

  return <section ref={rootRef} style={windowStyle} className={cn("fixed z-[10000] overflow-hidden border border-white/70 bg-background/90 shadow-[0_28px_80px_hsl(215_35%_15%_/_0.28),0_3px_10px_hsl(215_35%_15%_/_0.12)] backdrop-blur-2xl", maximized ? "inset-3 rounded-[14px]" : cn("h-[min(680px,calc(100vh-40px))] w-[min(920px,calc(100vw-40px))] rounded-[14px]", position ? "" : "bottom-5 left-5"), !dragging && !resizing && "transition-[box-shadow] duration-200")}>
    <header onPointerDown={beginDrag} onPointerMove={moveDrag} onPointerUp={endDrag} onPointerCancel={endDrag} className={cn("relative flex h-[46px] select-none items-center border-b border-black/[0.08] bg-white/65 px-4 backdrop-blur-xl dark:bg-card/65", maximized ? "cursor-default" : "cursor-grab active:cursor-grabbing")}>
      <div className="z-10 flex items-center gap-1" onPointerDown={(event) => event.stopPropagation()}>
        <Button type="button" variant="ghost" size="icon" onClick={() => runExit("close")} title="关闭 Pi Agent" className="h-7 w-7 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"><X className="h-3.5 w-3.5" /></Button>
        <Button type="button" variant="ghost" size="icon" onClick={() => runExit("minimize")} title="最小化" className="h-7 w-7 text-muted-foreground hover:bg-warning/10"><Minus className="h-3.5 w-3.5" /></Button>
        <Button type="button" variant="ghost" size="icon" onClick={toggleMaximize} title={maximized ? "恢复窗口" : "最大化"} className="h-7 w-7 text-muted-foreground hover:bg-primary/10">{maximized ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}</Button>
      </div>
      <div className="pointer-events-none absolute inset-x-16 flex items-center justify-center gap-2"><span className="grid h-5 w-5 place-items-center rounded-md bg-primary/12"><img src="/imge/pi-lite.png" alt="Pi Agent" className="h-4 w-4 object-contain" /></span><span className="truncate text-[13px] font-semibold tracking-[0.01em]">Pi Agent</span><span className="hidden text-[11px] text-muted-foreground sm:inline">{current.label} · {status}</span></div>
      <div className="z-10 ml-auto flex items-center" onPointerDown={(event) => event.stopPropagation()}><Button type="button" variant="ghost" size="icon" title={maximized ? "最大化时不可调整大小" : "拖动右上角调节窗口大小"} disabled={maximized} onPointerDown={beginResize} className="h-7 w-7 cursor-nesw-resize text-muted-foreground disabled:cursor-default"><Grip className="h-3.5 w-3.5 -rotate-45" /></Button></div>
    </header>
    <div className="flex h-[calc(100%-3rem)] min-h-0">
      <aside className={cn("relative flex shrink-0 flex-col border-r border-black/[0.06] bg-white/45 transition-all dark:bg-card/35", collapsed ? "w-12" : "w-[180px]")}>
        <div className="flex h-10 items-center justify-end px-2"><Button variant="ghost" size="icon" title={collapsed ? "展开助手列表" : "折叠助手列表"} onClick={() => setCollapsed((value) => !value)}>{collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}</Button></div>
        <div className="space-y-1 px-2">{ASSISTANTS.map((item) => { const Icon = item.icon; const selected = item.id === assistant; return <button key={item.id} onClick={() => chooseAssistant(item.id)} disabled={busy} title={collapsed ? item.label : undefined} className={cn("flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left transition-all disabled:opacity-50", selected ? "bg-primary/12 text-primary shadow-sm ring-1 ring-primary/15" : "text-muted-foreground hover:bg-white/75 hover:text-foreground dark:hover:bg-secondary", collapsed && "justify-center px-0")}><span className={cn("grid h-6 w-6 shrink-0 place-items-center rounded-md", selected ? "bg-primary text-primary-foreground" : "bg-muted/70")}><Icon className="h-3.5 w-3.5" /></span>{!collapsed && <span className="min-w-0"><span className="block text-xs font-semibold">{item.label}</span><span className="block truncate text-[10px] text-muted-foreground">{item.description}</span></span>}</button>; })}</div>
        <div className="mt-auto border-t border-black/[0.06] p-2"><Button type="button" variant="ghost" size={collapsed ? "icon" : "sm"} onClick={() => setSettingsOpen((value) => !value)} title={settingsOpen ? "返回对话" : "Agent 设置"} className={cn("w-full text-muted-foreground", collapsed && "mx-auto")}><Settings2 className={cn("h-3.5 w-3.5", !collapsed && "mr-1.5")} />{!collapsed && (settingsOpen ? "返回对话" : "设置")}</Button></div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        {settingsOpen ? <div className="min-h-0 flex-1 overflow-y-auto bg-[linear-gradient(135deg,hsl(var(--background)),hsl(var(--muted)/0.35))] p-5"><AgentSettings /></div> : <>
        <div className="flex items-center gap-2 border-b border-black/[0.06] bg-white/35 px-5 py-3 dark:bg-card/20"><span className="grid h-7 w-7 place-items-center rounded-lg bg-primary/10 text-primary"><current.icon className="h-4 w-4" /></span><div><div className="text-sm font-semibold">{current.label}</div><div className="text-[11px] text-muted-foreground">预设提示词与知识库将在后续版本持续深化</div></div></div>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto bg-[linear-gradient(135deg,hsl(var(--background)),hsl(var(--muted)/0.35))] p-5">{messages.length === 0 && <div className="mx-auto mt-16 max-w-sm text-center"><div className="mx-auto mb-4 grid h-14 w-14 place-items-center rounded-2xl bg-primary shadow-lg shadow-primary/20"><img src="/imge/pi-lite.png" alt="Pi Agent" className="h-8 w-8 object-contain" /></div><div className="text-sm font-semibold">{current.label}已就绪</div><p className="mt-1 text-xs leading-5 text-muted-foreground">{current.description}。输入你的目标，Pi 会基于当前预设助手提供下一步建议。</p></div>}{messages.map((message, index) => <div key={`${message.role}-${index}`} className={cn("max-w-[86%] rounded-2xl px-3.5 py-2.5 text-sm leading-6 shadow-sm", message.role === "user" ? "ml-auto rounded-br-md bg-primary text-primary-foreground" : "rounded-bl-md border border-black/[0.04] bg-white/85 text-foreground dark:bg-card")}>{message.role === "assistant" && message.thinking ? <details className="mb-2 rounded-lg border border-border/45 bg-muted/25 px-2.5 py-1.5"><summary className="flex cursor-pointer select-none items-center gap-1.5 text-[11px] font-semibold text-muted-foreground"><Sparkles className="h-3 w-3 text-primary" />思考过程</summary><div className="mt-1.5 whitespace-pre-wrap break-words text-xs leading-5 text-muted-foreground">{message.thinking}</div></details> : null}<div className="whitespace-pre-wrap break-words">{message.text}</div></div>)}{busy && <div className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" />Pi 正在组织回答</div>}</div>
        <form className="relative border-t border-black/[0.06] bg-white/65 p-3.5 backdrop-blur-xl dark:bg-card/65" onSubmit={submit}><div className="mb-2 flex flex-wrap items-center gap-2"><Button type="button" variant="outline" size="sm" onClick={endConversation} disabled={!sessionId || busy} className="h-7"><X className="mr-1.5 h-3.5 w-3.5" />结束对话</Button><Button type="button" variant="outline" size="sm" onClick={createConversation} disabled={!sessionId || busy} className="h-7"><Plus className="mr-1.5 h-3.5 w-3.5" />新建对话</Button><Button type="button" variant="outline" size="sm" onClick={clearContext} disabled={!sessionId || busy} className="h-7"><Trash2 className="mr-1.5 h-3.5 w-3.5" />清空上下文</Button><Button type="button" variant="outline" size="sm" onClick={loadHistory} disabled={!sessionId || busy} className="h-7"><History className="mr-1.5 h-3.5 w-3.5" />历史会话<ChevronDown className={cn("ml-1.5 h-3.5 w-3.5 transition-transform", historyOpen && "rotate-180")} /></Button><Button type="button" variant="outline" size="sm" onClick={addAttachments} className="h-7"><Paperclip className="mr-1.5 h-3.5 w-3.5" />添加文件{attachments.length > 0 && <span className="ml-1 rounded-full bg-primary/15 px-1.5 text-[10px] font-semibold text-primary">{attachments.length}</span>}</Button><span className="ml-auto rounded-md border border-primary/20 bg-primary/5 px-2 py-1 text-[11px] font-medium text-primary">权限：{sessionId ? "已按助手设置生效" : "未连接"}</span></div>{historyOpen && <div className="mb-2 max-h-32 overflow-y-auto rounded-lg border border-border/60 bg-background/80 p-1">{history.length ? history.map((item) => <div key={item.id} className="flex items-center gap-1"><button type="button" onClick={() => selectHistory(item)} className="flex min-w-0 flex-1 items-center justify-between rounded-md px-2.5 py-2 text-left text-xs hover:bg-muted"><span className="truncate">{item.messages.find((message) => message.role === "user")?.text || "空白对话"}</span><span className="ml-3 shrink-0 text-[10px] text-muted-foreground">{item.message_count} 条</span></button><button type="button" aria-label="删除历史会话" onClick={() => removeHistory(item.id)} className="shrink-0 rounded-md p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive" title="删除该历史会话"><Trash2 className="h-3 w-3" /></button></div>) : <div className="px-2 py-3 text-center text-xs text-muted-foreground">暂无已结束历史会话</div>}</div>}{attachments.length > 0 && <div className="mb-2 flex flex-wrap gap-1.5">{attachments.map((path) => <span key={path} className="inline-flex items-center gap-1 rounded-md border border-border/60 bg-background/70 px-2 py-1 text-[11px] text-muted-foreground"><FileArchive className="h-3 w-3 shrink-0 text-primary" /><span className="max-w-56 truncate">{path}</span><button type="button" aria-label="移除附件" onClick={() => setAttachments((items) => items.filter((item) => item !== path))} className="text-muted-foreground hover:text-destructive"><X className="h-3 w-3" /></button></span>)}</div>}{mentionMenu && <div className="absolute bottom-full left-4 z-50 mb-2 max-h-52 w-72 overflow-y-auto rounded-xl border border-border/60 bg-background/95 p-1.5 shadow-xl backdrop-blur-xl"><div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{mentionMenu.kind === "integration" ? "Skill / MCP" : "知识文档"}</div>{mentionOptions.filter((option) => !mentionMenu.query || option.label.toLowerCase().includes(mentionMenu.query.toLowerCase())).map((option) => <button type="button" key={option.value} onClick={() => pickMention(option)} className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs hover:bg-muted"><span className="grid h-5 w-5 shrink-0 place-items-center rounded bg-primary/10 text-primary">{mentionMenu.kind === "integration" ? <Sparkles className="h-3 w-3" /> : <FileArchive className="h-3 w-3" />}</span><span className="min-w-0 flex-1 truncate font-medium">{option.label}</span><span className="shrink-0 text-[10px] text-muted-foreground">{option.sub}</span></button>)}</div>}<Textarea rows={3} ref={textareaRef} className="resize-none rounded-xl border-black/[0.09] bg-background/80 shadow-inner" value={input} onChange={handleInputChange} onKeyDown={handleInputKeyDown} disabled={!sessionId || busy} placeholder={`向${current.label}描述你的目标，输入 @ 引用 Skill/MCP，输入 & 引用知识文档`} /><div className="mt-2 flex justify-end gap-2">{busy && <Button type="button" variant="outline" size="sm" onClick={stop}><Square className="mr-1.5 h-3.5 w-3.5" />停止</Button>}<Button type="submit" size="sm" className="rounded-lg px-4 shadow-sm" disabled={!sessionId || !input.trim() || busy}><Send className="mr-1.5 h-3.5 w-3.5" />发送</Button></div></form>
      </>}
      </div>
    </div>
  </section>;
}

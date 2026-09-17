import { Suspense, lazy, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { Loader2 } from "lucide-react";
import Header from "./Header";
import Sidebar from "./Sidebar";
import KeepAliveOutlet from "./KeepAliveOutlet";
import { useHeaderInbox } from "@/hooks/useHeaderInbox";
import { rememberTabLocation } from "@/lib/tabMemory";

// Pi 助手只在用户主动唤起时才需要，单独拆包，不进入首屏
const PiAssistantWindow = lazy(() => import("@/components/agent/PiAssistantWindow"));

function RouteLoading() {
  return (
    <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" />
      <span>加载中…</span>
    </div>
  );
}

function readSidebarCollapsed(): boolean {
  try {
    return !!JSON.parse(localStorage.getItem("vl_sidebar_collapsed") || "false");
  } catch { return false; }
}

export default function AppLayout() {
  const location = useLocation();
  const isEditor = location.pathname === "/editing" || location.pathname === "/voiceforge/video-dub" || location.pathname === "/creation-canvas";
  const [sidebarCollapsed, setSidebarCollapsed] = useState(readSidebarCollapsed);
  const [agentState, setAgentState] = useState<"closed" | "booting" | "open" | "minimized">("closed");
  const agentWakeAtRef = useRef(0);
  const readyTimerRef = useRef<number | null>(null);
  const headerInbox = useHeaderInbox();

  // 记住每个标签页最近访问的位置，侧边栏再次点击时可回到原处
  const locationKey = `${location.pathname}${location.search}`;
  const lastLocationKeyRef = useRef("");
  const scrollMemoRef = useRef(new Map<string, number>());
  const mainRef = useRef<HTMLElement>(null);
  if (lastLocationKeyRef.current !== locationKey) {
    // 此时 DOM 仍是上一个页面，先把它在 <main> 里的滚动位置存下来
    if (lastLocationKeyRef.current) {
      scrollMemoRef.current.set(lastLocationKeyRef.current, mainRef.current?.scrollTop ?? 0);
    }
    lastLocationKeyRef.current = locationKey;
    rememberTabLocation(location.pathname, location.search);
  }

  // 回到某个页面时恢复它离开时的滚动位置（保活页面内容仍在，可立即恢复）
  useLayoutEffect(() => {
    const el = mainRef.current;
    if (!el) return;
    el.scrollTop = scrollMemoRef.current.get(locationKey) ?? 0;
  }, [locationKey]);

  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed((collapsed) => {
      const next = !collapsed;
      localStorage.setItem("vl_sidebar_collapsed", JSON.stringify(next));
      window.dispatchEvent(new CustomEvent("vl-ui-change", { detail: { key: "sidebar_collapsed", val: next } }));
      return next;
    });
  }, []);
  const handleAgentReady = useCallback(() => {
    const remaining = Math.max(0, 1500 - (Date.now() - agentWakeAtRef.current));
    if (readyTimerRef.current) window.clearTimeout(readyTimerRef.current);
    readyTimerRef.current = window.setTimeout(() => setAgentState("open"), remaining);
  }, []);

  // 导航栏 Pi 按钮：toggle。打开 ↔ 收回（minimized 保留会话，不关闭）；booting 时点击取消启动
  useEffect(() => {
    const wakeAgent = () => {
      setAgentState((state) => {
        if (state === "closed") {
          agentWakeAtRef.current = Date.now();
          return "booting";
        }
        if (state === "booting") {
          if (readyTimerRef.current) {
            window.clearTimeout(readyTimerRef.current);
            readyTimerRef.current = null;
          }
          return "closed";
        }
        return state === "open" ? "minimized" : "open";
      });
    };
    window.addEventListener("vl-pi-wake", wakeAgent);
    return () => window.removeEventListener("vl-pi-wake", wakeAgent);
  }, []);

  useEffect(() => {
    if (agentState !== "booting") return;
    const timer = window.setTimeout(() => setAgentState("open"), 3000);
    return () => window.clearTimeout(timer);
  }, [agentState]);

  useEffect(() => {
    const handleUIChange = (event: Event) => {
      if ((event as CustomEvent).detail?.key === "sidebar_collapsed") {
        setSidebarCollapsed(readSidebarCollapsed());
      }
    };
    window.addEventListener("vl-ui-change", handleUIChange);
    return () => window.removeEventListener("vl-ui-change", handleUIChange);
  }, []);

  return (
    <div className="h-screen flex flex-col gradient-mesh noise-overlay">
      <Header collapsed={sidebarCollapsed} onToggleSidebar={toggleSidebar} inbox={headerInbox} />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar collapsed={sidebarCollapsed} agentState={agentState} />
        <main
          ref={mainRef}
          className={isEditor ? "flex-1 min-h-0 overflow-hidden" : "flex-1 min-h-0 overflow-auto px-2 py-2"}
        >
          <Suspense fallback={<RouteLoading />}>
            <KeepAliveOutlet />
          </Suspense>
        </main>
      </div>
      {agentState !== "closed" && (
        <div className={agentState === "booting" || agentState === "minimized" ? "hidden" : undefined}>
          <Suspense fallback={null}>
            <PiAssistantWindow visible={agentState === "open"} onClose={() => setAgentState("closed")} onMinimize={() => setAgentState("minimized")} onReady={handleAgentReady} />
          </Suspense>
        </div>
      )}
    </div>
  );
}

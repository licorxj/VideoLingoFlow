import { useCallback, useEffect, useRef, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Bot, Loader2 } from "lucide-react";
import Header from "./Header";
import Sidebar from "./Sidebar";
import PiAssistantWindow from "@/components/agent/PiAssistantWindow";

function readSidebarCollapsed(): boolean {
  try {
    return !!JSON.parse(localStorage.getItem("vl_sidebar_collapsed") || "false");
  } catch { return false; }
}

export default function AppLayout() {
  const location = useLocation();
  const isEditor = location.pathname === "/editing";
  const [sidebarCollapsed, setSidebarCollapsed] = useState(readSidebarCollapsed);
  const [agentState, setAgentState] = useState<"closed" | "loading" | "open" | "minimized">("closed");
  const agentWakeAtRef = useRef(0);
  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed((collapsed) => {
      const next = !collapsed;
      localStorage.setItem("vl_sidebar_collapsed", JSON.stringify(next));
      window.dispatchEvent(new CustomEvent("vl-ui-change", { detail: { key: "sidebar_collapsed", val: next } }));
      return next;
    });
  }, []);
  const handleAgentReady = useCallback(() => {
    const remaining = Math.max(0, 450 - (Date.now() - agentWakeAtRef.current));
    window.setTimeout(() => setAgentState("open"), remaining);
  }, []);

  useEffect(() => {
    const wakeAgent = () => {
      agentWakeAtRef.current = Date.now();
      setAgentState("loading");
    };
    window.addEventListener("vl-pi-wake", wakeAgent);
    return () => window.removeEventListener("vl-pi-wake", wakeAgent);
  }, []);

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
      <Header collapsed={sidebarCollapsed} onToggleSidebar={toggleSidebar} />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar collapsed={sidebarCollapsed} />
        <main className={isEditor ? "flex-1 min-h-0 overflow-hidden" : "flex-1 min-h-0 overflow-auto px-2 py-2"}>
          <div key={location.pathname} className="animate-fade-in-up h-full">
            <Outlet />
          </div>
        </main>
      </div>
      {agentState === "loading" && <div className="pointer-events-none fixed bottom-5 right-5 z-[10000] flex w-72 items-center gap-3 rounded-lg border border-primary/25 bg-background px-4 py-3 shadow-xl"><div className="grid h-9 w-9 place-items-center rounded-md bg-primary/10 text-primary"><Loader2 className="h-5 w-5 animate-spin" /></div><div><div className="text-sm font-semibold">Pi 正在就位</div><div className="text-xs text-muted-foreground">加载 Agent 工作台与助手配置</div></div></div>}
      {agentState !== "closed" && <div className={agentState === "loading" || agentState === "minimized" ? "invisible pointer-events-none" : undefined}><PiAssistantWindow onClose={() => setAgentState("closed")} onMinimize={() => setAgentState("minimized")} onReady={handleAgentReady} /></div>}
      {agentState === "minimized" && <button onClick={() => setAgentState("open")} className="fixed bottom-5 right-5 z-[10000] flex items-center gap-2 rounded-lg border border-primary/30 bg-background px-3 py-2 shadow-lg transition-transform hover:-translate-y-0.5" title="恢复 Pi Agent"><span className="grid h-7 w-7 place-items-center rounded-md bg-primary text-primary-foreground"><Bot className="h-4 w-4" /></span><span className="text-xs font-medium">Pi Agent</span></button>}
    </div>
  );
}

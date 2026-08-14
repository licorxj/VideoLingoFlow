import { useCallback, useEffect, useRef, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
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
  const [agentState, setAgentState] = useState<"closed" | "booting" | "open" | "minimized">("closed");
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
    const remaining = Math.max(0, 1500 - (Date.now() - agentWakeAtRef.current));
    window.setTimeout(() => setAgentState("open"), remaining);
  }, []);

  useEffect(() => {
    const wakeAgent = () => {
      agentWakeAtRef.current = Date.now();
      setAgentState((state) => (state === "closed" ? "booting" : "open"));
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
      <Header collapsed={sidebarCollapsed} onToggleSidebar={toggleSidebar} piDockVisible={agentState === "minimized"} onPiDockClick={() => setAgentState("open")} />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar collapsed={sidebarCollapsed} agentState={agentState} />
        <main className={isEditor ? "flex-1 min-h-0 overflow-hidden" : "flex-1 min-h-0 overflow-auto px-2 py-2"}>
          <div key={location.pathname} className="animate-fade-in-up h-full">
            <Outlet />
          </div>
        </main>
      </div>
      {agentState !== "closed" && <div className={agentState === "booting" || agentState === "minimized" ? "invisible pointer-events-none" : undefined}><PiAssistantWindow visible={agentState === "open"} onClose={() => setAgentState("closed")} onMinimize={() => setAgentState("minimized")} onReady={handleAgentReady} /></div>}
    </div>
  );
}

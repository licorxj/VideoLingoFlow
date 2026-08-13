import { useState, useEffect, useCallback } from "react";
import { NavLink } from "react-router-dom";
import { cn } from "@/lib/utils";
import {
  LayoutDashboard,
  Layers,
  History,
  Settings,
  Info,
  Power,
  RefreshCw,
  Terminal,
  Share2,
  Server,
  Globe,
  Radio,
  Network,
  Users,
  Clapperboard,
  Scissors,
  Mic2,
  Bot,
  Store,
} from "lucide-react";

const NAV_GROUPS = [
  [
    { to: "/", icon: LayoutDashboard, label: "工作流编排" },
    { to: "/batch", icon: Layers, label: "批量工作台" },
    { to: "/history", icon: History, label: "历史项目" },
  ],
  [
    { to: "/editing", icon: Clapperboard, label: "剪辑工作台" },
    { to: "/voiceforge", icon: Mic2, label: "晴沐配音谷" },
    { to: "/social", icon: Share2, label: "多平台发布" },
  ],
  [
    { to: "/collaboration", icon: Users, label: "多人协作" },
    { to: "/llm-router", icon: Network, label: "大模型路由器" },
    { to: "/settings", icon: Settings, label: "全局设置" },
  ],
  [
    { to: "/logs", icon: Terminal, label: "后台日志" },
    { to: "/about", icon: Info, label: "关于" },
    { to: "/community", icon: Store, label: "共享社区" },
  ],
];

export default function Sidebar({ collapsed }: { collapsed: boolean }) {
  const [services, setServices] = useState<Record<string, { status: string; port?: number; managed?: boolean }>>({});
  const [restartingSvc, setRestartingSvc] = useState<string | null>(null);
  const [stoppingSvc, setStoppingSvc] = useState<string | null>(null);
  const navItems = NAV_GROUPS;

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch("http://localhost:18001/manager/status");
      const data = await res.json();
      setServices(data);
    } catch {
    }
  }, []);

  const restartService = useCallback(async (endpoint: string, svcKey: string) => {
    setRestartingSvc(svcKey);
    try {
      await fetch(`http://localhost:18001/${endpoint}`, { method: "POST" });
    } catch { /* ignore */ }
    // Poll until service is back up
    let attempts = 0;
    const poll = setInterval(async () => {
      attempts++;
      try {
        const res = await fetch("http://localhost:18001/manager/status");
        const data = await res.json();
        setServices(data);
        if (data[svcKey]?.status === "running") {
          clearInterval(poll);
          setRestartingSvc(null);
        }
      } catch { /* ignore */ }
      if (attempts > 30) {
        clearInterval(poll);
        setRestartingSvc(null);
      }
    }, 1000);
  }, []);

  const stopService = useCallback(async (endpoint: string, svcKey: string) => {
    setStoppingSvc(svcKey);
    try {
      await fetch(`http://localhost:18001/${endpoint}`, { method: "POST" });
    } catch { /* ignore */ }
    // Poll until service is stopped
    let attempts = 0;
    const poll = setInterval(async () => {
      attempts++;
      try {
        const res = await fetch("http://localhost:18001/manager/status");
        const data = await res.json();
        setServices(data);
        if (data[svcKey]?.status === "stopped") {
          clearInterval(poll);
          setStoppingSvc(null);
        }
      } catch { /* ignore */ }
      if (attempts > 20) {
        clearInterval(poll);
        setStoppingSvc(null);
      }
    }, 1000);
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 8000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  return (
    <aside
      className={cn(
        "bg-[hsl(var(--surface))] border-r border-[hsl(var(--surface-border))] flex flex-col py-3 relative z-10 transition-all duration-300",
        collapsed ? "w-[60px]" : "w-[11.5rem]"
      )}
    >
      <div className="mx-3 mb-1 border-t border-dashed border-cyan-400/50 shadow-[0_1px_2px_rgba(34,211,238,0.15)]" />
      <nav className="flex-1 space-y-0 px-2">
        {navItems.map((group, groupIdx) => (
          <div key={groupIdx}>
            {groupIdx > 0 && (
              <div className="my-2.5 mx-3 flex items-center">
                <div className="flex-1 border-t-[1.5px] border-dashed border-cyan-400/50 shadow-[0_1px_2px_rgba(34,211,238,0.15)]" />
              </div>
            )}
            <div className="space-y-0.5">
              {group.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === "/"}
                  className={({ isActive }) =>
                    cn(
                      "group flex items-center gap-3 rounded-xl text-sm font-medium transition-all duration-200 w-full",
                      collapsed ? "justify-center px-0 py-2.5" : "px-3 py-2.5",
                      isActive
                        ? "bg-slate-200 dark:bg-slate-700/80 text-foreground font-semibold scale-[1.01]"
                          : "text-muted-foreground hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-foreground"
                    )
                  }
                >
                  {({ isActive }) => (
                    <>
                      <item.icon
                        className={cn(
                          "w-[18px] h-[18px] transition-all duration-200 flex-shrink-0",
                          isActive ? "text-primary" : "group-hover:scale-105"
                        )}
                        strokeWidth={isActive ? 2.5 : 2}
                      />
                      {!collapsed && <span>{item.label}</span>}
                    </>
                  )}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>
      {!collapsed && (
        <div className="px-3 py-3 mt-auto space-y-2 border-t border-[hsl(var(--surface-border))]">
          <button
            onClick={() => window.dispatchEvent(new Event("vl-pi-wake"))}
            className="group relative flex w-full items-center gap-2 overflow-hidden rounded-lg border border-primary/25 bg-primary/5 px-2.5 py-2 text-left transition-colors hover:bg-primary/10"
            title="唤醒 Pi Agent"
          >
            <span className="relative grid h-8 w-8 place-items-center rounded-md bg-primary text-primary-foreground shadow-sm"><Bot className="h-4 w-4" /><span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full border-2 border-background bg-[hsl(var(--success))]" /></span>
            <span className="min-w-0"><span className="block text-xs font-semibold text-foreground">Pi Agent</span><span className="block text-[10px] text-muted-foreground">点击唤醒工作台</span></span>
            <span className="absolute inset-y-0 right-0 w-8 bg-gradient-to-l from-primary/10 to-transparent opacity-0 transition-opacity group-hover:opacity-100" />
          </button>
          <div className="flex items-center gap-1.5">
            <button
              onClick={fetchStatus}
              className="flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 text-[11px] font-medium border border-[hsl(var(--surface-border))] rounded-lg hover:bg-secondary text-muted-foreground hover:text-foreground transition-all duration-200"
              title="刷新所有状态"
            >
              <RefreshCw className="w-3 h-3" />
              刷新
            </button>
          </div>

          {/* 主后端 */}
          <ServiceRow
            icon={Server}
            label="主后端"
            port={services.main_backend?.port}
            status={services.main_backend?.status}
            restarting={restartingSvc === "main_backend"}
            stopping={stoppingSvc === "main_backend"}
            onRestart={() => restartService("manager/restart-main", "main_backend")}
            onStop={() => stopService("manager/stop-main", "main_backend")}
          />

          {/* Social 后端 */}
          <ServiceRow
            icon={Globe}
            label="Social后端"
            port={services.social_backend?.port}
            status={services.social_backend?.status}
            restarting={restartingSvc === "social_backend"}
            stopping={stoppingSvc === "social_backend"}
            onRestart={() => restartService("manager/restart-social", "social_backend")}
            onStop={() => stopService("manager/stop-social", "social_backend")}
          />

          {/* Social 前端 */}
          <ServiceRow
            icon={Globe}
            label="Social前端"
            port={services.social_frontend?.port}
            status={services.social_frontend?.status}
            restarting={restartingSvc === "social_frontend"}
            stopping={stoppingSvc === "social_frontend"}
            onRestart={() => restartService("manager/restart-social-frontend", "social_frontend")}
            onStop={() => stopService("manager/stop-social-frontend", "social_frontend")}
          />

          {/* Social MCP */}
          <ServiceRow
            icon={Radio}
            label="Social MCP"
            port={services.social_mcp?.port}
            status={services.social_mcp?.status}
            restarting={restartingSvc === "social_mcp"}
            stopping={stoppingSvc === "social_mcp"}
            onRestart={() => restartService("manager/restart-mcp", "social_mcp")}
            onStop={() => stopService("manager/stop-mcp", "social_mcp")}
          />

          {/* LLM Router */}
          <ServiceRow
            icon={Network}
            label="LLM路由"
            port={services.llm_router?.port}
            status={services.llm_router?.status}
            restarting={restartingSvc === "llm_router"}
            stopping={stoppingSvc === "llm_router"}
            onRestart={() => restartService("manager/restart-llm-router", "llm_router")}
            onStop={() => stopService("manager/stop-llm-router", "llm_router")}
          />

          <ServiceRow
            icon={Scissors}
            label="Cutia"
            port={services.cutia?.port}
            status={services.cutia?.status}
            restarting={restartingSvc === "cutia"}
            stopping={stoppingSvc === "cutia"}
            onRestart={() => restartService("manager/restart-cutia", "cutia")}
            onStop={() => stopService("manager/stop-cutia", "cutia")}
          />

          <div className="text-[10px] text-muted-foreground/60 text-center tracking-wider uppercase pt-1">
            AI Video Studio
          </div>
        </div>
      )}
      {collapsed && <button onClick={() => window.dispatchEvent(new Event("vl-pi-wake"))} className="mx-auto mb-3 grid h-9 w-9 place-items-center rounded-md border border-primary/25 bg-primary/10 text-primary" title="唤醒 Pi Agent"><Bot className="h-4 w-4" /></button>}
    </aside>
  );
}

function ServiceRow({
  icon: Icon,
  label,
  port,
  status,
  restarting,
  stopping,
  onRestart,
  onStop,
}: {
  icon: any;
  label: string;
  port?: number;
  status?: string;
  restarting: boolean;
  stopping: boolean;
  onRestart: () => void;
  onStop: () => void;
}) {
  const isRunning = status === "running";

  return (
    <div className="flex items-center gap-1.5">
      <Icon className="w-3 h-3 text-muted-foreground flex-shrink-0" />
      <span className="text-[11px] text-muted-foreground flex-shrink-0">{label}</span>
      <span className={cn(
        "w-1.5 h-1.5 rounded-full flex-shrink-0",
        status === undefined ? "bg-yellow-500 animate-pulse" :
        isRunning ? "bg-emerald-500" : "bg-red-500"
      )} />
      <span className="text-[10px] text-muted-foreground font-mono ml-auto">
        :{port || "?"}
      </span>
      <button
        onClick={onStop}
        disabled={stopping || !isRunning}
        className="flex-shrink-0 w-5 h-5 rounded flex items-center justify-center hover:bg-red-500/15 text-muted-foreground hover:text-red-500 transition-colors disabled:opacity-40"
        title={`关闭 ${label}`}
      >
        <Power className={cn("w-2.5 h-2.5", stopping && "animate-pulse text-red-500")} />
      </button>
      <button
        onClick={onRestart}
        disabled={restarting}
        className="flex-shrink-0 w-5 h-5 rounded flex items-center justify-center hover:bg-secondary text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
        title={`重启 ${label}`}
      >
        <RefreshCw className={cn("w-2.5 h-2.5", restarting && "animate-pulse text-amber-500")} />
      </button>
    </div>
  );
}

import React, { useState, useEffect, useCallback } from "react";
import { NavLink } from "react-router-dom";
import { useI18n } from "../../i18n";
import {
  LayoutDashboard, Server, GitBranch, ScrollText, Settings, MessageSquare,
  Play, Loader2,
} from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "../ui/dialog";

function useNavItems() {
  const { t } = useI18n();
  return [
    { to: "/", icon: LayoutDashboard, label: t("sidebar.dashboard") },
    { to: "/chat", icon: MessageSquare, label: t("sidebar.chat") },
    { to: "/providers", icon: Server, label: t("sidebar.providers") },
    { to: "/strategies", icon: GitBranch, label: t("sidebar.strategies") },
    { to: "/logs", icon: ScrollText, label: t("sidebar.logs") },
    { to: "/settings", icon: Settings, label: t("sidebar.settings") },
  ];
}

export default function Sidebar() {
  const navItems = useNavItems();
  const { t } = useI18n();
  const [serviceRunning, setServiceRunning] = useState<boolean | null>(null);
  const [checking, setChecking] = useState(true);
  const [starting, setStarting] = useState(false);
  const [showDialog, setShowDialog] = useState(false);

  const checkHealth = useCallback(async () => {
    try {
      const res = await fetch("/api/health", { method: "GET", signal: AbortSignal.timeout(3000) });
      setServiceRunning(res.ok);
    } catch {
      setServiceRunning(false);
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    checkHealth();
    const interval = setInterval(checkHealth, 8000);
    return () => clearInterval(interval);
  }, [checkHealth]);

  const MANAGER_PORT = 12003;

  const handleStartService = async () => {
    setStarting(true);
    // Try the standalone service manager first (always running alongside frontend)
    try {
      const mgrRes = await fetch(`http://127.0.0.1:${MANAGER_PORT}/start`, {
        method: "POST",
        signal: AbortSignal.timeout(8000),
      });
      if (mgrRes.ok) {
        // Wait for backend to come up
        let retries = 0;
        const poll = async () => {
          retries++;
          try {
            const hr = await fetch("/api/health", { signal: AbortSignal.timeout(2000) });
            if (hr.ok) { setServiceRunning(true); setStarting(false); return; }
          } catch {}
          if (retries < 10) setTimeout(poll, 1000);
          else setStarting(false);
        };
        setTimeout(poll, 1500);
        return;
      }
    } catch {
      // Service manager not reachable, try backend directly
    }
    // Fallback: try backend's own start endpoint
    try {
      const res = await fetch("/api/service/start", { method: "POST", signal: AbortSignal.timeout(5000) });
      if (res.ok) {
        setTimeout(async () => { await checkHealth(); setStarting(false); }, 3000);
        return;
      }
    } catch {}
    setStarting(false);
    setShowDialog(true);
  };

  return (
    <aside className="fixed left-0 top-0 z-40 h-screen w-60 sidebar-gradient flex flex-col">
      {/* Logo */}
      <div className="flex h-16 items-center gap-3 px-5 border-b border-border">
        <img src="/logo.png" alt="LocalRouter Logo" className="h-9 w-9 rounded-xl object-cover shadow-lg" />
        <div>
          <h1 className="text-base font-extrabold tracking-tight text-foreground">LocalRouter</h1>
          <p className="text-[9px] font-semibold tracking-[0.15em] text-cyan-700 dark:text-cyan-300 font-bold">{t("sidebar.tagline")}</p>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-4 px-3 space-y-0.5 overflow-y-auto">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            className={({ isActive }) =>
              "group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-all duration-200 " +
              (isActive
                ? "bg-primary/10 text-primary font-bold"
                : "text-foreground/70 hover:bg-black/[0.05] dark:hover:bg-white/[0.06] hover:text-foreground font-medium")
            }
          >
            {({ isActive }) => (
              <>
                {isActive && (
                  <div className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r-full bg-cyan-400 shadow-[0_0_8px_2px_hsla(199,89%,48%,0.35)]" />
                )}
                <div className={"flex h-8 w-8 items-center justify-center rounded-lg transition-all duration-200 " + (isActive ? "bg-cyan-500/10" : "group-hover:bg-black/[0.04] dark:group-hover:bg-white/[0.04]")}>
                  <item.icon className={"h-4 w-4 transition-colors " + (isActive ? "text-cyan-400" : "text-muted-foreground group-hover:text-foreground")} strokeWidth={isActive ? 2.5 : 2} />
                </div>
                <span>{item.label}</span>
                {isActive && <div className="ml-auto h-1.5 w-1.5 rounded-full bg-cyan-400 shadow-[0_0_6px_2px_hsla(199,89%,48%,0.4)] pulse-dot" />}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="border-t border-border p-4">
        {checking ? (
          <div className="flex items-center gap-2.5">
            <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
            <span className="text-sm text-muted-foreground">{t("common.loading")}</span>
          </div>
        ) : serviceRunning ? (
          <div className="flex items-center gap-2.5">
            <div className="status-led status-led-green" />
            <span className="text-sm font-medium text-foreground/80">{t("sidebar.serviceRunning")}</span>
          </div>
        ) : (
          <button
            onClick={handleStartService}
            disabled={starting}
            className="flex items-center gap-2.5 w-full group cursor-pointer disabled:opacity-60"
          >
            <div className="h-3 w-3 rounded-full bg-red-400/80 shadow-[0_0_6px_2px_rgba(248,113,113,0.3)]" />
            {starting ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-500" />
                <span className="text-sm font-medium text-amber-500">{t("sidebar.starting")}</span>
              </>
            ) : (
              <>
                <span className="text-sm font-medium text-red-500 dark:text-red-400 group-hover:underline">{t("sidebar.serviceStopped")}</span>
                <Play className="h-3.5 w-3.5 ml-auto text-red-500 dark:text-red-400" />
              </>
            )}
          </button>
        )}
        <p className="text-[11px] text-muted-foreground/50 mt-1.5 font-mono tracking-wider">v1.0.0</p>
      </div>

      <Dialog open={showDialog} onOpenChange={setShowDialog}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t("sidebar.startService")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 text-sm text-muted-foreground">
            <p>{t("sidebar.startServiceDesc")}</p>
            <div className="bg-muted rounded-lg p-3 font-mono text-xs space-y-1">
              <p className="text-foreground font-semibold">cd backend</p>
              <p className="text-foreground font-semibold">python -m uvicorn app.main:app --host 0.0.0.0 --port 12002 --reload</p>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </aside>
  );
}

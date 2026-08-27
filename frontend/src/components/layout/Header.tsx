import ThemeToggle from "@/components/shared/ThemeToggle";
import UserSubscriptionDialog from "@/components/UserSubscriptionDialog";
import { useState, useEffect } from "react";
import { Bell, CheckCircle2, Cpu, HardDrive, MemoryStick, Megaphone, MonitorCog, PanelLeft, PanelLeftClose, RefreshCw, TriangleAlert, UserRound, Users } from "lucide-react";
import { cn } from "@/lib/utils";
import { changeControlProjectMember, listControlProjectMembers, listControlProjects, removeControlProjectMember, type ControlProjectMember } from "@/api/controlPlane";
import { batchApi, type RuntimeStatus } from "@/api/batch";
import { useProjectStore } from "@/stores/projectStore";
import { useControlStore } from "@/stores/controlStore";
import { useSubscriptionStore } from "@/stores/subscriptionStore";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { RuntimeNotification, useHeaderInbox } from "@/hooks/useHeaderInbox";

type HeaderInbox = ReturnType<typeof useHeaderInbox>;

function NotificationBadge({ count, tone }: { count: number; tone: "warning" | "info" }) {
  if (count <= 0) return null;
  return (
    <span
      className={cn(
        "absolute -right-1.5 -top-1.5 min-w-[18px] h-[18px] rounded-full px-1 text-[10px] font-bold flex items-center justify-center border",
        tone === "warning"
          ? "bg-warning text-warning-foreground border-warning/30"
          : "bg-info text-info-foreground border-info/30"
      )}
    >
      {count > 99 ? "99+" : count}
    </span>
  );
}

function notificationTone(kind: RuntimeNotification["kind"]) {
  if (kind === "success") {
    return {
      card: "border-success/25 bg-success/10",
      iconWrap: "bg-success/15 text-success",
      text: "text-success",
      icon: <CheckCircle2 className="w-4 h-4" />,
    };
  }
  if (kind === "error") {
    return {
      card: "border-destructive/25 bg-destructive/10",
      iconWrap: "bg-destructive/15 text-destructive",
      text: "text-destructive",
      icon: <TriangleAlert className="w-4 h-4" />,
    };
  }
  return {
    card: "border-info/25 bg-info/10",
    iconWrap: "bg-info/15 text-info",
    text: "text-info",
    icon: <Bell className="w-4 h-4" />,
  };
}

function ResourceMetric({
  label,
  value,
  icon: Icon,
  tone,
}: {
  label: string;
  value: number | null | undefined;
  icon: typeof Cpu;
  tone: string;
}) {
  const percent = typeof value === "number" && Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : null;
  return (
    <div className="hidden xl:flex h-8 w-[72px] flex-col justify-center gap-1 px-1.5 rounded-md border border-border/50 bg-background/40" title={`${label} ${percent === null ? "不可用" : `${percent.toFixed(1)}%`}`}>
      <div className="flex items-center justify-between gap-1 leading-none">
        <span className="flex items-center gap-1 text-[9px] font-semibold text-muted-foreground">
          <Icon className={cn("h-3 w-3", tone)} />
          {label}
        </span>
        <span className="text-[10px] font-bold tabular-nums text-foreground">{percent === null ? "--" : `${Math.round(percent)}%`}</span>
      </div>
      <div className="h-1 overflow-hidden rounded-full bg-muted">
        <div className={cn("h-full rounded-full transition-[width] duration-500", tone.replace("text-", "bg-"))} style={{ width: `${percent ?? 0}%` }} />
      </div>
    </div>
  );
}

function SystemResourceMetrics() {
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);

  useEffect(() => {
    let mounted = true;
    const refresh = async () => {
      try {
        const next = await batchApi.getRuntimeStatus();
        if (mounted) setRuntime(next);
      } catch {
        if (mounted) setRuntime(null);
      }
    };
    refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, []);

  const system = runtime?.system;
  return (
    <div className="hidden xl:flex items-center gap-1.5 mr-1 rounded-lg border border-cyan-400/80 bg-cyan-400/5 px-1.5 py-1 shadow-[inset_0_0_0_1px_rgba(34,211,238,0.12),0_0_10px_rgba(34,211,238,0.12)]">
      <ResourceMetric label="CPU" value={system?.cpu_percent} icon={Cpu} tone="text-sky-500" />
      <ResourceMetric label="RAM" value={system?.ram_percent} icon={MemoryStick} tone="text-emerald-500" />
      <ResourceMetric label="GPU" value={system?.gpu_percent} icon={MonitorCog} tone="text-violet-500" />
      <ResourceMetric label="VRAM" value={system?.vram_percent} icon={HardDrive} tone="text-amber-500" />
    </div>
  );
}

export default function Header({
  collapsed,
  onToggleSidebar,
  inbox,
}: {
  collapsed: boolean;
  onToggleSidebar: () => void;
  inbox: HeaderInbox;
}) {
  const user = useControlStore((s) => s.user);
  const setUser = useControlStore((s) => s.setUser);
  const refreshSession = useControlStore((s) => s.refreshSession);
  const [membersOpen, setMembersOpen] = useState(false);
  const [members, setMembers] = useState<ControlProjectMember[]>([]);
  const [memberUsername, setMemberUsername] = useState("");
  const [memberRole, setMemberRole] = useState<"viewer" | "editor">("viewer");
  const [memberError, setMemberError] = useState("");
  const { projects, currentProjectId, setProjects, setCurrentProjectId } = useProjectStore();
  const subscriptionStatus = useSubscriptionStore((s) => s.status);
  const fetchSubscriptionStatus = useSubscriptionStore((s) => s.fetchStatus);
  const [subscriptionOpen, setSubscriptionOpen] = useState(false);
  const [announcementOpen, setAnnouncementOpen] = useState(false);
  const [notificationOpen, setNotificationOpen] = useState(false);

  useEffect(() => {
    refreshSession().then(async (session) => {
      if (session) setProjects(await listControlProjects());
    }).catch(() => setUser(null));
  }, [refreshSession, setProjects, setUser]);

  useEffect(() => {
    fetchSubscriptionStatus();
  }, [fetchSubscriptionStatus]);

  useEffect(() => {
    if (notificationOpen) inbox.markNotificationsRead();
  }, [inbox, notificationOpen]);

  const loadMembers = async () => {
    if (!currentProjectId) return;
    try {
      setMembers(await listControlProjectMembers(currentProjectId));
      setMemberError("");
    } catch (error) {
      setMemberError(error instanceof Error ? error.message : "无法加载项目成员");
    }
  };

  const openMembers = async () => {
    setMembersOpen(true);
    await loadMembers();
  };

  const saveMember = async () => {
    if (!currentProjectId || !memberUsername.trim()) return;
    try {
      await changeControlProjectMember(currentProjectId, memberUsername.trim(), memberRole);
      setMemberUsername("");
      await loadMembers();
    } catch (error) {
      setMemberError(error instanceof Error ? error.message : "成员更新失败");
    }
  };

  const removeMember = async (userId: string) => {
    if (!currentProjectId) return;
    try {
      await removeControlProjectMember(currentProjectId, userId);
      await loadMembers();
    } catch (error) {
      setMemberError(error instanceof Error ? error.message : "成员移除失败");
    }
  };

  return (
    <header className="h-14 header-gradient border-b border-[hsl(var(--surface-border))] flex items-center justify-between px-5 z-20 relative select-none">
      <div className="flex items-center gap-3">
        <button
          onClick={onToggleSidebar}
          className="flex h-9 w-9 items-center justify-center rounded-xl text-muted-foreground transition-all duration-200 hover:bg-accent hover:text-foreground active:scale-90"
          title={collapsed ? "展开侧栏" : "收起侧栏"}
          aria-label={collapsed ? "展开侧栏" : "收起侧栏"}
        >
          {collapsed ? <PanelLeft className="w-4 h-4" /> : <PanelLeftClose className="w-4 h-4" />}
        </button>
        <img src="/brand-logo.png" alt="VideoLingoFlow" className="h-9 w-auto object-contain" />
        <div className="flex items-baseline gap-2">
          <h1 className="text-lg font-extrabold tracking-tight text-foreground">
            VideoLingoFlow <span className="text-sm font-medium text-muted-foreground">（流连视听）</span>
          </h1>
          <span className="text-[10px] font-semibold text-primary bg-primary/10 px-1.5 py-0.5 rounded-md uppercase tracking-widest">
            v2.0
          </span>
        </div>
      </div>
      <div className="flex items-center gap-1.5">
        <SystemResourceMetrics />
        <button
          onClick={() => setAnnouncementOpen(true)}
          className="relative p-2 rounded-xl transition-all duration-200 hover:bg-accent text-muted-foreground hover:text-foreground active:scale-90"
          title="项目公告"
        >
          <Megaphone className="w-[18px] h-[18px]" />
          <NotificationBadge count={inbox.announcements.length} tone="warning" />
        </button>
        <button
          onClick={() => setNotificationOpen(true)}
          className="relative p-2 rounded-xl transition-all duration-200 hover:bg-accent text-muted-foreground hover:text-foreground active:scale-90"
          title="运行通知"
        >
          <Bell className="w-[18px] h-[18px]" />
          <NotificationBadge count={inbox.unreadNotificationCount} tone="info" />
        </button>
        <ThemeToggle />
        {user && projects.length > 0 && (
          <select
            value={currentProjectId || ""}
            onChange={(event) => setCurrentProjectId(event.target.value || null)}
            className="h-8 max-w-40 rounded-md border border-border bg-background px-2 text-xs text-foreground"
            aria-label="当前项目"
          >
            <option value="">未选择项目</option>
            {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
          </select>
        )}
        {user && currentProjectId && (
          <button onClick={openMembers} className="p-2 rounded-xl transition-all duration-200 hover:bg-accent text-muted-foreground hover:text-foreground" title="管理项目成员">
            <Users className="w-[18px] h-[18px]" />
          </button>
        )}
        <button
          onClick={() => setSubscriptionOpen(true)}
          className={cn(
            "flex items-center gap-2 px-2.5 py-1.5 rounded-xl transition-all duration-200 text-xs font-medium",
            "hover:bg-accent active:scale-95"
          )}
          title="用户和订阅"
        >
          <div
            className={cn(
              "w-7 h-7 rounded-full flex items-center justify-center text-[11px] font-bold transition-all duration-200",
              subscriptionStatus?.user_type === "subscribed"
                ? "bg-warning/90 text-warning-foreground shadow-sm shadow-warning/30"
                : subscriptionStatus?.user_type === "registered"
                ? "bg-info/90 text-info-foreground shadow-sm shadow-info/30"
                : "bg-muted text-muted-foreground"
            )}
          >
            <UserRound className="w-3.5 h-3.5" />
          </div>
          <span className="hidden lg:inline text-muted-foreground">
            {subscriptionStatus?.user_type === "subscribed"
              ? "订阅用户"
              : subscriptionStatus?.user_type === "registered"
              ? "注册用户"
              : "游客"}
          </span>
        </button>
      </div>
      {membersOpen && (
        <div className="absolute right-5 top-12 z-30 w-80 border border-border bg-background p-4 shadow-lg rounded-lg">
          <div className="mb-3 flex items-center justify-between text-sm font-semibold"><span>项目成员</span><button onClick={() => setMembersOpen(false)} className="text-muted-foreground">关闭</button></div>
          <div className="mb-3 max-h-48 space-y-2 overflow-y-auto">
            {members.map((member) => (
              <div key={member.user.id} className="flex items-center gap-2 text-xs">
                <span className="min-w-0 flex-1 truncate">{member.user.display_name || member.user.username}</span>
                <select value={member.role} onChange={async (event) => { if (currentProjectId) { await changeControlProjectMember(currentProjectId, member.user.username, event.target.value as "viewer" | "editor"); await loadMembers(); } }} className="rounded border border-input bg-background px-1 py-1">
                  <option value="viewer">查看者</option><option value="editor">编辑者</option>
                </select>
                <button onClick={() => removeMember(member.user.id)} className="text-destructive">移除</button>
              </div>
            ))}
          </div>
          <div className="flex gap-2">
            <input value={memberUsername} onChange={(event) => setMemberUsername(event.target.value)} className="min-w-0 flex-1 rounded border border-input bg-background px-2 py-1.5 text-xs" placeholder="用户名" />
            <select value={memberRole} onChange={(event) => setMemberRole(event.target.value as "viewer" | "editor")} className="rounded border border-input bg-background px-1 text-xs"><option value="viewer">查看者</option><option value="editor">编辑者</option></select>
            <button onClick={saveMember} className="rounded bg-primary px-2 text-xs text-primary-foreground">添加</button>
          </div>
          {memberError && <p className="mt-2 text-xs text-destructive">{memberError}</p>}
        </div>
      )}
      <UserSubscriptionDialog open={subscriptionOpen} onOpenChange={setSubscriptionOpen} />
      <Dialog open={announcementOpen} onOpenChange={setAnnouncementOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><Megaphone className="w-4 h-4 text-warning" />项目公告</DialogTitle>
          </DialogHeader>
          <div className="flex items-center justify-between rounded-xl border border-border/60 bg-accent/20 px-3 py-2 text-xs text-muted-foreground">
            <span>当前共 {inbox.announcements.length} 条公告</span>
            <button
              onClick={inbox.refreshAnnouncements}
              className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 hover:bg-accent text-foreground transition-colors"
              disabled={inbox.announcementLoading}
            >
              <RefreshCw className={cn("w-3.5 h-3.5", inbox.announcementLoading && "animate-spin")} />
              刷新
            </button>
          </div>
          <div className="max-h-[60vh] space-y-3 overflow-y-auto pr-1">
            {inbox.announcements.length ? inbox.announcements.map((item) => (
              <div key={item.id} className="rounded-2xl border border-border/60 bg-card/70 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h4 className="text-sm font-semibold text-foreground">{item.title}</h4>
                    {item.createdAt && <p className="mt-1 text-[11px] text-muted-foreground">{item.createdAt}</p>}
                  </div>
                </div>
                <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-info">{item.content}</p>
              </div>
            )) : inbox.announcementError ? (
              <p className="rounded-xl border border-destructive/25 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                公告获取失败：{inbox.announcementError}
              </p>
            ) : (
              <p className="rounded-xl border border-border/60 bg-card/50 px-4 py-6 text-center text-sm text-muted-foreground">
                暂无公告。
              </p>
            )}
          </div>
        </DialogContent>
      </Dialog>
      <Dialog open={notificationOpen} onOpenChange={setNotificationOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><Bell className="w-4 h-4 text-info" />运行通知</DialogTitle>
          </DialogHeader>
          <div className="flex items-center justify-between rounded-xl border border-border/60 bg-accent/20 px-3 py-2 text-xs text-muted-foreground">
            <span>未读 {inbox.unreadNotificationCount} 条，共 {inbox.notifications.length} 条</span>
            <button
              onClick={inbox.markNotificationsRead}
              className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 hover:bg-accent text-foreground transition-colors"
            >
              <CheckCircle2 className="w-3.5 h-3.5" />
              标记已读
            </button>
          </div>
          <div className="max-h-[60vh] space-y-3 overflow-y-auto pr-1">
            {inbox.notifications.length ? inbox.notifications.map((item) => {
              const tone = notificationTone(item.kind);
              return (
                <div
                  key={item.id}
                  className={cn(
                    "rounded-2xl border p-4 transition-colors",
                    tone.card,
                    !item.read && "ring-1 ring-info/20"
                  )}
                >
                  <div className="flex items-start gap-3">
                    <span className={cn("mt-0.5 rounded-xl p-2", tone.iconWrap)}>{tone.icon}</span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-3">
                        <p className={cn("text-sm font-semibold", tone.text)}>{item.title}</p>
                        <span className="shrink-0 text-[11px] text-muted-foreground">
                          {new Date(item.createdAt).toLocaleTimeString("zh-CN", { hour12: false })}
                        </span>
                      </div>
                      <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-foreground/90">{item.description}</p>
                    </div>
                  </div>
                </div>
              );
            }) : (
              <p className="rounded-xl border border-border/60 bg-card/50 px-4 py-6 text-center text-sm text-muted-foreground">
                当前会话暂无运行通知。
              </p>
            )}
          </div>
        </DialogContent>
      </Dialog>
      <div className="pointer-events-none fixed right-5 top-16 z-50 flex w-[360px] max-w-[calc(100vw-2rem)] flex-col gap-2">
        {inbox.toastQueue.map((item) => {
          const tone = notificationTone(item.kind);
          return (
            <div
              key={item.id}
              className={cn(
                "pointer-events-auto rounded-2xl border px-4 py-3 shadow-xl backdrop-blur-md animate-in slide-in-from-top-3 fade-in-0",
                tone.card
              )}
            >
              <div className="flex items-start gap-3">
                <span className={cn("mt-0.5 rounded-xl p-2", tone.iconWrap)}>{tone.icon}</span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-3">
                    <p className={cn("text-sm font-semibold", tone.text)}>{item.title}</p>
                    <button
                      onClick={() => inbox.dismissToast(item.id)}
                      className="text-[11px] text-muted-foreground hover:text-foreground transition-colors"
                    >
                      收起
                    </button>
                  </div>
                  <p className="mt-1 text-sm leading-5 text-foreground/90">{item.description}</p>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </header>
  );
}

import ThemeToggle from "@/components/shared/ThemeToggle";
import UserSubscriptionDialog from "@/components/UserSubscriptionDialog";
import { useState, useEffect } from "react";
import { LogOut, PanelLeft, PanelLeftClose, UserRound, Users } from "lucide-react";
import { cn } from "@/lib/utils";
import { changeControlProjectMember, listControlProjectMembers, listControlProjects, removeControlProjectMember, type ControlProjectMember } from "@/api/controlPlane";
import { useProjectStore } from "@/stores/projectStore";
import { useControlStore } from "@/stores/controlStore";
import { useSubscriptionStore } from "@/stores/subscriptionStore";

export default function Header({ collapsed, onToggleSidebar }: { collapsed: boolean; onToggleSidebar: () => void }) {
  const user = useControlStore((s) => s.user);
  const setUser = useControlStore((s) => s.setUser);
  const refreshSession = useControlStore((s) => s.refreshSession);
  const controlLogout = useControlStore((s) => s.logout);
  const [membersOpen, setMembersOpen] = useState(false);
  const [members, setMembers] = useState<ControlProjectMember[]>([]);
  const [memberUsername, setMemberUsername] = useState("");
  const [memberRole, setMemberRole] = useState<"viewer" | "editor">("viewer");
  const [memberError, setMemberError] = useState("");
  const { projects, currentProjectId, setProjects, setCurrentProjectId } = useProjectStore();
  const subscriptionStatus = useSubscriptionStore((s) => s.status);
  const fetchSubscriptionStatus = useSubscriptionStore((s) => s.fetchStatus);
  const [subscriptionOpen, setSubscriptionOpen] = useState(false);

  useEffect(() => {
    refreshSession().then(async (session) => {
      if (session) setProjects(await listControlProjects());
    }).catch(() => setUser(null));
  }, [refreshSession, setProjects, setUser]);

  useEffect(() => {
    fetchSubscriptionStatus();
  }, [fetchSubscriptionStatus]);

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
    <header className="h-14 bg-[hsl(var(--surface))] border-b border-[hsl(var(--surface-border))] flex items-center justify-between px-5 z-20 relative select-none">
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
            VideoLingoFlow
          </h1>
          <span className="text-[10px] font-semibold text-primary bg-primary/10 px-1.5 py-0.5 rounded-md uppercase tracking-widest">
            v2.0
          </span>
        </div>
      </div>
      <div className="flex items-center gap-1.5">
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
                ? "bg-amber-400/90 text-amber-950 shadow-sm shadow-amber-400/30"
                : subscriptionStatus?.user_type === "registered"
                ? "bg-sky-400/90 text-sky-950 shadow-sm shadow-sky-400/30"
                : "bg-slate-300 dark:bg-slate-600 text-slate-600 dark:text-slate-300"
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
        {user && (
          <button onClick={() => controlLogout().finally(() => { setProjects([]); setCurrentProjectId(null); })} className="p-2 rounded-xl transition-all duration-200 hover:bg-accent text-muted-foreground hover:text-foreground" title={`退出 ${user.username}`}>
            <LogOut className="w-[18px] h-[18px]" />
          </button>
        )}
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
    </header>
  );
}

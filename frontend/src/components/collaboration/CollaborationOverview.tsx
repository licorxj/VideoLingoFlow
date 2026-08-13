import { useCallback, useEffect, useState } from "react";
import { Check, Eye, EyeOff, KeyRound, LogIn, ShieldCheck, UserPlus, Users, Wifi, WifiOff, X } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useAlert } from "@/components/ui/AlertProvider";
import { useControlStore } from "@/stores/controlStore";
import { loginControlSession } from "@/api/controlPlane";
import {
  applyJoin, approveApplication, assignControlUserRole, changeOwnCredentials, getApplyStatus,
  listApplications, listControlUsers, rejectApplication, setUserActive,
  type ControlUserFull, type JoinApplicationItem, type PresenceMember,
} from "@/api/collaboration";

/* ------------------------------------------------------------------ */
/* 通用小组件                                                            */
/* ------------------------------------------------------------------ */

function PasswordField({ value, onChange, placeholder, autoComplete }: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  autoComplete?: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <Input
        type={show ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete={autoComplete}
        className="h-8 pr-8"
      />
      <button
        type="button"
        onClick={() => setShow((v) => !v)}
        className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
        title={show ? "隐藏密码" : "显示密码"}
      >
        {show ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
      </button>
    </div>
  );
}

function formatRelative(iso: string | null): string {
  if (!iso) return "从未活跃";
  const time = new Date(iso).getTime();
  if (Number.isNaN(time)) return "从未活跃";
  const diff = Date.now() - time;
  if (diff < 60_000) return "刚刚";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`;
  return `${Math.floor(diff / 86_400_000)} 天前`;
}

/* ------------------------------------------------------------------ */
/* 团队成员卡片                                                          */
/* ------------------------------------------------------------------ */

const ROLE_GROUPS: { role: string; label: string; color: string }[] = [
  { role: "admin", label: "管理员", color: "bg-amber-500/15 text-amber-600 dark:text-amber-400" },
  { role: "editor", label: "编辑者", color: "bg-sky-500/15 text-sky-600 dark:text-sky-400" },
  { role: "viewer", label: "查看者", color: "bg-slate-500/15 text-slate-600 dark:text-slate-400" },
];

function groupByRole(presence: PresenceMember[]) {
  const map = new Map<string, PresenceMember[]>();
  for (const member of presence) {
    const role = member.roles.includes("admin") ? "管理员" : member.roles.includes("editor") ? "编辑者" : "查看者";
    const list = map.get(role) ?? [];
    list.push(member);
    map.set(role, list);
  }
  return map;
}

function TeamMemberCards() {
  const { user, presence, refreshPresence } = useControlStore();
  useEffect(() => {
    refreshPresence();
    const timer = window.setInterval(() => refreshPresence(), 15000);
    return () => window.clearInterval(timer);
  }, [refreshPresence]);

  const grouped = groupByRole(presence);
  const onlineCount = presence.filter((m) => m.online).length;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center justify-between text-base">
          <span className="flex items-center gap-2"><Users className="h-4 w-4 text-primary" />团队架构</span>
          <span className="text-xs text-muted-foreground">{onlineCount}/{presence.length} 在线</span>
        </CardTitle>
        <CardDescription>按角色分组显示团队成员与在线状态</CardDescription>
      </CardHeader>
      <CardContent>
        {presence.length === 0 ? (
          <p className="py-6 text-center text-xs text-muted-foreground">登录后查看团队成员</p>
        ) : (
          <div className="grid gap-4 md:grid-cols-3">
            {ROLE_GROUPS.map((group) => {
              const members = grouped.get(group.label) ?? [];
              return (
                <div key={group.role}>
                  <div className="mb-2 flex items-center justify-between">
                    <Badge className={group.color}>{group.label}</Badge>
                    <span className="text-xs text-muted-foreground">{members.length} 人</span>
                  </div>
                  <div className="space-y-2">
                    {members.length === 0 && <p className="text-xs text-muted-foreground">暂无成员</p>}
                    {members.map((member) => (
                      <div key={member.user_id} className="flex items-center gap-2 rounded-lg border border-border px-2 py-1.5">
                        <div className={`flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full text-xs font-semibold ${member.online ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400" : "bg-muted text-muted-foreground"}`}>
                          {(member.display_name || member.username).slice(0, 1).toUpperCase()}
                        </div>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium">
                            {member.display_name || member.username}
                            {member.user_id === user?.id && <span className="ml-1 text-[10px] text-primary">（你）</span>}
                          </p>
                          <p className="truncate text-[11px] text-muted-foreground">
                            {member.online ? "在线" : formatRelative(member.last_seen_at)}
                            {member.editing?.workflow_key && ` · 编辑 ${member.editing.workflow_key}`}
                          </p>
                        </div>
                        {member.online ? <Wifi className="h-3.5 w-3.5 text-emerald-500" /> : <WifiOff className="h-3.5 w-3.5 text-muted-foreground/50" />}
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/* 管理员卡片（仅管理员/主机显示，含登录与修改账号信息）                           */
/* ------------------------------------------------------------------ */

function AdminCard() {
  const { alert } = useAlert();
  const { user, refreshSession } = useControlStore();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin123456");
  const [busy, setBusy] = useState(false);
  const [credOpen, setCredOpen] = useState(false);
  const [credForm, setCredForm] = useState({ current_password: "", new_username: "", new_password: "" });
  const [credBusy, setCredBusy] = useState(false);

  const handleLogin = async () => {
    if (!username.trim() || !password) return;
    setBusy(true);
    try {
      await loginControlSession(username, password);
      await refreshSession();
      alert("登录成功", "success");
    } catch (error: any) {
      alert(error?.message || "用户名或密码错误", "error");
    } finally {
      setBusy(false);
    }
  };

  const openCredDialog = () => {
    setCredForm({ current_password: "", new_username: user?.username ?? "", new_password: "" });
    setCredOpen(true);
  };

  const handleCredChange = async () => {
    if (!credForm.current_password) return;
    setCredBusy(true);
    try {
      await changeOwnCredentials({
        current_password: credForm.current_password,
        new_username: credForm.new_username.trim() || undefined,
        new_password: credForm.new_password || undefined,
      });
      alert("账号信息已更新", "success");
      setCredOpen(false);
      await refreshSession();
    } catch (error: any) {
      alert(error?.message || "修改失败", "error");
    } finally {
      setCredBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader className="pb-1.5">
        <CardTitle className="flex items-center gap-2 text-base"><ShieldCheck className="h-4 w-4 text-primary" />管理员</CardTitle>
        <CardDescription>
          {user ? `当前账号：${user.display_name || user.username}` : "默认账号 admin / admin123456（登录后可自行修改）"}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {user ? (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border p-2 text-sm">
            <Badge variant={user.roles.includes("admin") ? "default" : "secondary"}>
              {user.roles.includes("admin") ? "管理员" : user.roles.includes("editor") ? "编辑者" : "查看者"}
            </Badge>
            <span className="font-mono">@{user.username}</span>
            <Button variant="outline" size="sm" className="ml-auto" onClick={openCredDialog}>
              <KeyRound className="h-3.5 w-3.5" />修改管理员信息
            </Button>
          </div>
        ) : (
          <>
            {/* 用户名 + 密码 合并为一行两列 */}
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <Label className="text-xs">用户名</Label>
                <Input className="h-8" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">密码</Label>
                <PasswordField value={password} onChange={setPassword} autoComplete="current-password" />
              </div>
            </div>
            <Button className="w-full" size="sm" onClick={handleLogin} disabled={busy}>
              <LogIn className="h-4 w-4" />{busy ? "登录中..." : "登录"}
            </Button>
          </>
        )}
      </CardContent>

      {/* 修改管理员信息弹窗 */}
      <Dialog open={credOpen} onOpenChange={(open) => !open && setCredOpen(false)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><KeyRound className="h-4 w-4" />修改管理员信息</DialogTitle>
            <DialogDescription>验证当前密码后，可修改用户名和密码（至少修改一项）</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label>当前密码</Label>
            <PasswordField value={credForm.current_password} onChange={(v) => setCredForm((f) => ({ ...f, current_password: v }))} placeholder="当前密码" />
            <Label>新用户名</Label>
            <Input value={credForm.new_username} onChange={(e) => setCredForm((f) => ({ ...f, new_username: e.target.value }))} placeholder="新用户名" />
            <Label>新密码（留空则不修改）</Label>
            <PasswordField value={credForm.new_password} onChange={(v) => setCredForm((f) => ({ ...f, new_password: v }))} placeholder="新密码（至少8位）" />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCredOpen(false)}>取消</Button>
            <Button onClick={handleCredChange} disabled={credBusy || !credForm.current_password}>{credBusy ? "保存中..." : "保存"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/* 成员卡片（仅成员/非主机显示，含申请加入）                                    */
/* ------------------------------------------------------------------ */

function MemberCard() {
  const { alert } = useAlert();
  const { user, refreshSession } = useControlStore();
  const [mode, setMode] = useState<"login" | "apply">("login");
  const [loginForm, setLoginForm] = useState({ username: "", password: "" });
  const [loginBusy, setLoginBusy] = useState(false);
  const [form, setForm] = useState({ username: "", password: "", display_name: "", reason: "" });
  const [busy, setBusy] = useState(false);
  const [applicationId, setApplicationId] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    if (!applicationId) return;
    const timer = window.setInterval(async () => {
      try {
        const result = await getApplyStatus(applicationId);
        setStatus(result.status);
        if (result.status === "approved") setMode("login");
        if (result.status !== "pending") window.clearInterval(timer);
      } catch {
        /* 忽略轮询失败 */
      }
    }, 5000);
    return () => window.clearInterval(timer);
  }, [applicationId]);

  const handleLogin = async () => {
    if (!loginForm.username.trim() || !loginForm.password) return;
    setLoginBusy(true);
    try {
      await loginControlSession(loginForm.username, loginForm.password);
      await refreshSession();
      alert("登录成功", "success");
    } catch (error: any) {
      alert(error?.message || "用户名或密码错误", "error");
    } finally {
      setLoginBusy(false);
    }
  };

  const handleApply = async () => {
    if (!form.username.trim() || !form.password) return;
    setBusy(true);
    try {
      const result = await applyJoin(form);
      setApplicationId(result.application_id);
      setStatus("pending");
      alert("申请已提交，等待管理员审批", "success");
    } catch (error: any) {
      alert(error?.message || "申请提交失败", "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader className="pb-1.5">
        <CardTitle className="flex items-center gap-2 text-base"><UserPlus className="h-4 w-4 text-primary" />成员</CardTitle>
        <CardDescription>
          {user
            ? `已登录：${user.display_name || user.username}`
            : mode === "login"
              ? "已获批准后，使用申请时的账号密码登录协作"
              : "提交注册申请，管理员审批后加入协作"}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {user ? (
          <p className="rounded-lg border border-border p-2 text-center text-sm text-muted-foreground">已登录为协作成员</p>
        ) : (
          <>
            {/* 登录 / 申请加入 切换 */}
            <div className="grid grid-cols-2 gap-1 rounded-lg border border-border p-1">
              <Button variant={mode === "login" ? "default" : "ghost"} size="sm" className="h-7" onClick={() => setMode("login")}>
                <LogIn className="h-3.5 w-3.5" />登录
              </Button>
              <Button variant={mode === "apply" ? "default" : "ghost"} size="sm" className="h-7" onClick={() => setMode("apply")}>
                <UserPlus className="h-3.5 w-3.5" />申请加入
              </Button>
            </div>

            {mode === "login" ? (
              <div className="space-y-2">
                {status === "approved" && (
                  <p className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-2 text-center text-xs text-emerald-600 dark:text-emerald-400">
                    申请已通过，请使用申请时的账号密码登录
                  </p>
                )}
                {status === "rejected" && (
                  <p className="rounded-lg border border-destructive/30 bg-destructive/10 p-2 text-center text-xs text-destructive">
                    申请已被拒绝，请切换到「申请加入」重新提交
                  </p>
                )}
                {/* 用户名 + 密码 合并为一行两列 */}
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <Label className="text-xs">用户名</Label>
                    <Input className="h-8" value={loginForm.username} onChange={(e) => setLoginForm((f) => ({ ...f, username: e.target.value }))} placeholder="3-128位" autoComplete="username" />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">密码</Label>
                    <PasswordField value={loginForm.password} onChange={(v) => setLoginForm((f) => ({ ...f, password: v }))} autoComplete="current-password" />
                  </div>
                </div>
                <Button className="w-full" size="sm" onClick={handleLogin} disabled={loginBusy}>
                  <LogIn className="h-4 w-4" />{loginBusy ? "登录中..." : "登录"}
                </Button>
              </div>
            ) : applicationId ? (
              <div className="space-y-2 rounded-lg border border-border p-3 text-center">
                <p className="text-sm font-medium">申请已提交</p>
                <p className="font-mono text-xs text-muted-foreground">申请编号：{applicationId.slice(0, 8)}…</p>
                <Badge variant={status === "approved" ? "default" : status === "rejected" ? "destructive" : "secondary"}>
                  {status === "approved" ? "已通过，请登录" : status === "rejected" ? "已拒绝" : "等待管理员审批..."}
                </Badge>
                {status === "rejected" && (
                  <Button variant="outline" size="sm" className="w-full" onClick={() => { setApplicationId(null); setStatus(null); }}>
                    重新申请
                  </Button>
                )}
              </div>
            ) : (
              <>
                {/* 用户名 + 显示名 一行两列 */}
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <Label className="text-xs">用户名</Label>
                    <Input className="h-8" value={form.username} onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))} placeholder="3-128位" />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">显示名</Label>
                    <Input className="h-8" value={form.display_name} onChange={(e) => setForm((f) => ({ ...f, display_name: e.target.value }))} placeholder="可选" />
                  </div>
                </div>
                {/* 密码 + 申请理由 一行两列 */}
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <Label className="text-xs">密码</Label>
                    <PasswordField value={form.password} onChange={(v) => setForm((f) => ({ ...f, password: v }))} placeholder="至少8位" />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">申请理由</Label>
                    <Input className="h-8" value={form.reason} onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))} placeholder="可选" />
                  </div>
                </div>
                <Button className="w-full" size="sm" onClick={handleApply} disabled={busy}>
                  <UserPlus className="h-4 w-4" />{busy ? "提交中..." : "提交申请"}
                </Button>
              </>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/* 申请审批列表（仅管理员显示）                                              */
/* ------------------------------------------------------------------ */

function ApprovalList() {
  const { alert, confirm } = useAlert();
  const [applications, setApplications] = useState<JoinApplicationItem[]>([]);
  const [rejectTarget, setRejectTarget] = useState<JoinApplicationItem | null>(null);
  const [rejectNote, setRejectNote] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setApplications(await listApplications());
    } catch {
      /* 忽略 */
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const pending = applications.filter((a) => a.status === "pending");

  const handleApprove = async (application: JoinApplicationItem) => {
    if (!(await confirm(`确认通过成员「${application.username}」的注册申请？`))) return;
    setBusyId(application.id);
    try {
      await approveApplication(application.id);
      alert("已通过申请", "success");
      await load();
    } catch (error: any) {
      alert(error?.message || "操作失败", "error");
    } finally {
      setBusyId(null);
    }
  };

  const handleReject = async () => {
    if (!rejectTarget) return;
    setBusyId(rejectTarget.id);
    try {
      await rejectApplication(rejectTarget.id, rejectNote);
      alert("已拒绝申请", "success");
      setRejectTarget(null);
      setRejectNote("");
      await load();
    } catch (error: any) {
      alert(error?.message || "操作失败", "error");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <Card>
      <CardHeader className="pb-1.5">
        <CardTitle className="flex items-center gap-2 text-base">
          <UserPlus className="h-4 w-4 text-primary" />申请审批
          {pending.length > 0 && <Badge variant="destructive">{pending.length} 待处理</Badge>}
        </CardTitle>
        <CardDescription>新成员注册申请，需审批后生效</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {pending.length === 0 ? (
          <p className="py-4 text-center text-xs text-muted-foreground">暂无待审批的注册申请</p>
        ) : (
          pending.map((application) => (
            <div key={application.id} className="flex items-center gap-2 rounded-lg border border-border px-2.5 py-1.5">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">
                  {application.display_name || application.username}
                  <span className="ml-2 font-mono text-xs text-muted-foreground">@{application.username}</span>
                </p>
                <p className="truncate text-[11px] text-muted-foreground">
                  {application.reason || "（未填写申请理由）"} · {new Date(application.created_at).toLocaleString()}
                </p>
              </div>
              <Button size="sm" onClick={() => handleApprove(application)} disabled={busyId === application.id}>
                <Check className="h-4 w-4" />通过
              </Button>
              <Button size="sm" variant="outline" onClick={() => { setRejectTarget(application); setRejectNote(""); }} disabled={busyId === application.id}>
                <X className="h-4 w-4" />拒绝
              </Button>
            </div>
          ))
        )}
      </CardContent>

      <Dialog open={!!rejectTarget} onOpenChange={(open) => !open && setRejectTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>拒绝注册申请</DialogTitle>
            <DialogDescription>拒绝「{rejectTarget?.username}」的注册申请（可选填写原因）</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label>拒绝原因</Label>
            <Input value={rejectNote} onChange={(e) => setRejectNote(e.target.value)} placeholder="如：信息不全、名额已满等" />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRejectTarget(null)}>取消</Button>
            <Button variant="destructive" onClick={handleReject} disabled={busyId === rejectTarget?.id}>确认拒绝</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/* 底部：管理员与协作者列表（含启用/禁用开关）                                  */
/* ------------------------------------------------------------------ */

function UserListSection() {
  const { alert } = useAlert();
  const { user, roles, presence } = useControlStore();
  const isAdmin = roles.includes("admin");
  const [users, setUsers] = useState<ControlUserFull[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!isAdmin) return;
    try {
      setUsers(await listControlUsers());
    } catch {
      /* 忽略 */
    }
  }, [isAdmin]);

  useEffect(() => {
    load();
  }, [load]);

  const handleRoleChange = async (target: ControlUserFull, role: string) => {
    try {
      await assignControlUserRole(target.id, role);
      alert(`已将「${target.username}」设为${role === "admin" ? "管理员" : role === "editor" ? "编辑者" : "查看者"}`, "success");
      await load();
    } catch (error: any) {
      alert(error?.message || "角色更新失败", "error");
    }
  };

  const handleActiveToggle = async (target: ControlUserFull, active: boolean) => {
    setBusyId(target.id);
    try {
      await setUserActive(target.id, active);
      alert(active ? `已启用「${target.username}」` : `已禁用「${target.username}」`, "success");
      await load();
    } catch (error: any) {
      alert(error?.message || "操作失败", "error");
    } finally {
      setBusyId(null);
    }
  };

  const presenceMap = new Map(presence.map((m) => [m.user_id, m]));
  const rows: (ControlUserFull & { online: boolean })[] = isAdmin
    ? users.map((u) => ({ ...u, online: presenceMap.get(u.id)?.online ?? false }))
    : presence.map((m) => ({
        id: m.user_id, username: m.username, display_name: m.display_name, roles: m.roles, is_active: true, online: m.online,
      }));

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center justify-between text-base">
          <span className="flex items-center gap-2"><Users className="h-4 w-4 text-primary" />管理员与协作者</span>
          {isAdmin && <span className="text-xs text-muted-foreground">可在此启用/禁用成员、调整角色</span>}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="py-4 text-center text-xs text-muted-foreground">暂无成员，登录或提交注册申请后显示</p>
        ) : (
          <div className="space-y-2">
            {rows.map((row) => (
              <div key={row.id} className="flex items-center gap-3 rounded-lg border border-border px-3 py-2">
                <div className={`flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full text-xs font-semibold ${row.online ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400" : "bg-muted text-muted-foreground"}`}>
                  {(row.display_name || row.username).slice(0, 1).toUpperCase()}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">
                    {row.display_name || row.username}
                    {row.id === user?.id && <span className="ml-1 text-[10px] text-primary">（你）</span>}
                    {row.online && <Wifi className="ml-1 inline h-3 w-3 text-emerald-500" />}
                  </p>
                  <p className="truncate font-mono text-[11px] text-muted-foreground">
                    @{row.username} · {row.is_active ? "启用" : "禁用"} · {row.online ? "在线" : "离线"}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-1">
                  {row.roles.map((role) => (
                    <Badge key={role} variant={role === "admin" ? "default" : "secondary"}>{role}</Badge>
                  ))}
                </div>
                {isAdmin && row.id !== user?.id ? (
                  <div className="flex items-center gap-2">
                    <Select value={row.roles.includes("admin") ? "admin" : row.roles.includes("editor") ? "editor" : "viewer"} onValueChange={(role) => handleRoleChange(row, role)}>
                      <SelectTrigger className="h-8 w-28 text-xs"><SelectValue placeholder="角色" /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="viewer">查看者</SelectItem>
                        <SelectItem value="editor">编辑者</SelectItem>
                        <SelectItem value="admin">管理员</SelectItem>
                      </SelectContent>
                    </Select>
                    <Switch
                      checked={row.is_active}
                      disabled={busyId === row.id}
                      onCheckedChange={(checked) => handleActiveToggle(row, checked)}
                      title={row.is_active ? "禁用该成员" : "启用该成员"}
                    />
                  </div>
                ) : (
                  <Badge variant="secondary">{row.id === user?.id ? "当前账号" : "只读"}</Badge>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/* 协作总览页                                                            */
/* ------------------------------------------------------------------ */

export default function CollaborationOverview() {
  const { user, roles } = useControlStore();
  const isAdmin = roles.includes("admin");
  const isHostMachine = ["localhost", "127.0.0.1", ""].includes(window.location.hostname);
  // 管理员：仅显示管理员卡片（+ 申请审批列表）；成员：仅显示成员卡片
  const showAdminCard = isAdmin || (!user && isHostMachine);
  const showMemberCard = !showAdminCard;

  return (
    <div className="space-y-4">
      {/* 人员卡片（管理员/成员/审批）置顶 */}
      <div className={isAdmin ? "grid gap-4 lg:grid-cols-2" : "space-y-4"}>
        {showAdminCard && <AdminCard />}
        {isAdmin && <ApprovalList />}
        {showMemberCard && <MemberCard />}
      </div>
      <TeamMemberCards />
      {user && <UserListSection />}
    </div>
  );
}

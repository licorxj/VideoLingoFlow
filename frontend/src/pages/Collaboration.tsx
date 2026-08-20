import { useEffect, useState } from "react";
import { BookOpen, FolderOpen, LayoutDashboard, Users } from "lucide-react";
import { marked } from "marked";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { useAlert } from "@/components/ui/AlertProvider";
import { useControlStore } from "@/stores/controlStore";
import { useSubscriptionStore } from "@/stores/subscriptionStore";
import { getLanMode, setLanMode, getRemoteMode, setRemoteMode, bootstrapAdmin } from "@/api/collaboration";
import CollaborationOverview from "@/components/collaboration/CollaborationOverview";
import ResourceCenter from "@/components/collaboration/ResourceCenter";
import { PageHeader } from "@/components/shared/PageHeader";
import { PageBackground } from "@/components/shared/PageBackground";

function isHostMachine(): boolean {
  const hostname = window.location.hostname;
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "";
}

/* 顶栏右侧：局域网协作开关 */
function LanModeSwitch({ isSubscribed }: { isSubscribed: boolean }) {
  const { alert, confirm } = useAlert();
  const [enabled, setEnabled] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getLanMode()
      .then((data) => {
        setEnabled(data.enabled);
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, []);

  const handleToggle = async (value: boolean) => {
    if (value && !isSubscribed) {
      alert("多人协作功能仅对订阅用户开放，请先订阅后再开启。", "warning");
      return;
    }
    if (!(await confirm(`确认${value ? "开启" : "关闭"}局域网协作？\n修改配置后需要重启管理器才能生效。`))) return;
    setBusy(true);
    try {
      await setLanMode(value);
      setEnabled(value);
      alert(`已${value ? "开启" : "关闭"}局域网协作，重启管理器后生效`, "success");
    } catch (error: any) {
      alert(error?.message || "修改失败（需要管理员权限）", "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="text-muted-foreground">局域网协作</span>
      <Switch checked={enabled} disabled={busy || !loaded} onCheckedChange={handleToggle} />
    </label>
  );
}

/* 顶栏右侧：远程网络协作开关 */
function RemoteModeSwitch({ isSubscribed }: { isSubscribed: boolean }) {
  const { alert, confirm } = useAlert();
  const [enabled, setEnabled] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getRemoteMode()
      .then((data) => {
        setEnabled(data.enabled);
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, []);

  const handleToggle = async (value: boolean) => {
    if (value && !isSubscribed) {
      alert("多人协作功能仅对订阅用户开放，请先订阅后再开启。", "warning");
      return;
    }
    if (!(await confirm(value
      ? "确认开启远程网络协作？\n开启后公网域名（如 https://vlflow.licorai.dpdns.org）可访问本机，需配合 Cloudflare Tunnel。\n立即生效，无需重启。"
      : "确认关闭远程网络协作？\n关闭后公网域名立即无法访问本机（立即生效，无需重启）。"))) return;
    setBusy(true);
    try {
      const data = await setRemoteMode(value);
      setEnabled(value);
      if (!value) {
        alert("已关闭远程网络协作（立即生效）", "success");
        return;
      }
      const cf = data.cloudflared;
      if (!cf) {
        alert("已开启远程网络协作（立即生效）", "success");
        return;
      }
      if (!cf.installed) {
        alert(cf.message, "warning");
      } else if (!cf.running) {
        alert(`${cf.message}\n隧道未运行，公网域名暂时无法访问。`, "warning");
      } else {
        alert(cf.message, "success");
      }
    } catch (error: any) {
      alert(error?.message || "修改失败（需要管理员权限）", "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="text-muted-foreground">远程网络协作</span>
      <Switch checked={enabled} disabled={busy || !loaded} onCheckedChange={handleToggle} />
    </label>
  );
}

/* 云协作安装指南弹窗：加载 docs/cloud-collab-guide.md 并渲染显示 */
function CloudGuideDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [html, setHtml] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    fetch("/docs/cloud-collab-guide.md")
      .then((res) => {
        if (!res.ok) throw new Error(`加载失败（HTTP ${res.status}）`);
        return res.text();
      })
      .then(async (text) => {
        const rendered = await marked.parse(text);
        if (!cancelled) setHtml(rendered);
      })
      .catch((error: any) => {
        if (!cancelled) setHtml(`<p class="text-destructive">安装指南加载失败：${error?.message ?? "未知错误"}</p>`);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onOpenChange(false)}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><BookOpen className="h-4 w-4" />云协作安装指南</DialogTitle>
          <DialogDescription>公网远程协作（云控）的实现方法、先决条件与 Cloudflare 全流程说明</DialogDescription>
        </DialogHeader>
        <div className="max-h-[70vh] overflow-y-auto pr-1">
          {loading && !html && <p className="py-8 text-center text-sm text-muted-foreground">加载中...</p>}
          {html && <div className="markdown-body text-sm" dangerouslySetInnerHTML={{ __html: html }} />}
        </div>
      </DialogContent>
    </Dialog>
  );
}

export default function Collaboration() {
  const { user, roles, refreshSession } = useControlStore();
  const subscriptionStatus = useSubscriptionStore((state) => state.status);
  const fetchSubscriptionStatus = useSubscriptionStore((state) => state.fetchStatus);
  const [tab, setTab] = useState<"overview" | "resources">("overview");
  const [guideOpen, setGuideOpen] = useState(false);
  const isAdmin = roles.includes("admin");
  // 自动判断本机角色：主机（localhost/127.0.0.1 或管理员）→ 管理员，否则 → 协作组
  const youAre = isAdmin || isHostMachine() ? "管理员" : "协作组";
  const isSubscribed = subscriptionStatus?.user_type === "subscribed";

  useEffect(() => {
    refreshSession();
  }, [refreshSession]);

  useEffect(() => {
    if (!subscriptionStatus) fetchSubscriptionStatus();
  }, [fetchSubscriptionStatus, subscriptionStatus]);

  // 未注册时自动用默认账号初始化管理员，避免每次登录都提示"未注册"
  useEffect(() => {
    if (!user) {
      bootstrapAdmin({ username: "admin", password: "admin123456" }).catch(() => {
        /* 已初始化（409）或网络错误时静默忽略 */
      });
    }
  }, [user]);

  const tabs = [
    { key: "overview" as const, label: "协作总览", icon: LayoutDashboard },
    { key: "resources" as const, label: "资源中心", icon: FolderOpen },
  ];

  return (
    <PageBackground tone="collab" className="max-w-4xl mx-auto space-y-4 p-1">
      <PageHeader
        icon={Users}
        title="多人协作"
        detail="以本机为中心的局域网团队协作"
        actions={
          <>
            <LanModeSwitch isSubscribed={isSubscribed} />
            <RemoteModeSwitch isSubscribed={isSubscribed} />
          </>
        }
      />

      {/* 第二行：本机角色 */}
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border bg-muted/40 px-4 py-2.5">
        <span className="text-sm text-muted-foreground">你是：</span>
        <span className={cn("text-sm font-semibold", youAre === "管理员" ? "text-primary" : "text-info")}>
          {youAre}
        </span>
        {user && (
          <span className="text-xs text-muted-foreground">
            · 当前登录：{user.display_name || user.username}
            {isAdmin && <span className="ml-1 text-primary">（管理员）</span>}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => setGuideOpen(true)}>
            <BookOpen className="mr-1.5 h-4 w-4" />云协作安装指南
          </Button>
          <span className="hidden text-xs text-muted-foreground sm:inline">
            {isHostMachine() ? "本机为协作主机" : "本机为局域网成员机"}
          </span>
        </div>
      </div>

      {/* 页内导航 */}
      <div className="flex gap-1.5 border-b border-border pb-2">
        {tabs.map((item) => {
          const Icon = item.icon;
          const active = item.key === tab;
          return (
            <button
              key={item.key}
              onClick={() => setTab(item.key)}
              className={cn(
                "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-all",
                active ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              <Icon className="h-4 w-4" />
              {item.label}
            </button>
          );
        })}
      </div>

      {tab === "overview" ? <CollaborationOverview /> : <ResourceCenter />}

      <CloudGuideDialog open={guideOpen} onOpenChange={setGuideOpen} />
    </PageBackground>
  );
}

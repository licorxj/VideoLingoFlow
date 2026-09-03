import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import {
  Bell,
  CheckCircle2,
  Gem,
  Info,
  LayoutGrid,
  Library,
  Mic,
  PlayCircle,
  Settings,
  Sparkles,
  TriangleAlert,
  Video,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useNotificationStore, type NotificationItem, type NotificationKind } from "@/stores/notificationStore";

type NavItem = {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  end?: boolean;
  matchProjects?: boolean;
};

const LAST_VF_PROJECT_KEY = "vl_last_voiceforge_project";

const items: NavItem[] = [
  { to: "/voiceforge", label: "项目管理", icon: LayoutGrid, end: true },
  { to: "/voiceforge/voices", label: "音色库", icon: Mic },
  { to: "/voiceforge", label: "配音台", icon: PlayCircle, matchProjects: true },
  { to: "/voiceforge/video-dub", label: "视频配音", icon: Video },
  { to: "/voiceforge/scene-design", label: "场景设计", icon: Sparkles },
  { to: "/voiceforge/assets", label: "素材库", icon: Library },
  { to: "/voiceforge/settings", label: "设置", icon: Settings },
];

/* ── Notification visual tone ─────────────────────────────────────────── */
function toneOf(kind: NotificationKind) {
  switch (kind) {
    case "error":
      return {
        card: "border-destructive/30 bg-destructive/10",
        text: "text-destructive",
        wrap: "bg-destructive/15 text-destructive",
        icon: TriangleAlert,
      };
    case "warning":
      return {
        card: "border-warning/30 bg-warning/10",
        text: "text-warning",
        wrap: "bg-warning/15 text-warning",
        icon: TriangleAlert,
      };
    case "success":
      return {
        card: "border-success/30 bg-success/10",
        text: "text-success",
        wrap: "bg-success/15 text-success",
        icon: CheckCircle2,
      };
    default:
      return {
        card: "border-info/30 bg-info/10",
        text: "text-info",
        wrap: "bg-info/15 text-info",
        icon: Info,
      };
  }
}

function NotificationRow({ item, onDismiss }: { item: NotificationItem; onDismiss: (id: string) => void }) {
  const t = toneOf(item.kind);
  const Icon = t.icon;
  return (
    <li className={cn("rounded-lg border p-3 transition-colors", t.card, !item.read && "ring-1 ring-info/25")}>
      <div className="flex items-start gap-2">
        <span className={cn("mt-0.5 shrink-0 rounded p-1.5", t.wrap)}>
          <Icon className="h-3.5 w-3.5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <p className={cn("text-xs font-semibold break-words", t.text)}>{item.title}</p>
            <button
              onClick={() => onDismiss(item.id)}
              className="shrink-0 text-[10px] text-zinc-500 hover:text-zinc-200 transition-colors"
              title="收起此条"
            >
              收起
            </button>
          </div>
          <p className="mt-1 whitespace-pre-wrap text-xs leading-5 text-zinc-200 break-words">{item.description}</p>
          <p className="mt-1 text-[10px] text-zinc-500">
            {new Date(item.createdAt).toLocaleString("zh-CN", { hour12: false })}
            {item.source && (
              <span className="ml-1.5 rounded bg-white/10 px-1 py-0.5 text-zinc-400">{item.source}</span>
            )}
          </p>
        </div>
      </div>
    </li>
  );
}

function NotificationPanel({ onClose }: { onClose: () => void }) {
  const notifications = useNotificationStore((s) => s.notifications);
  const markAllRead = useNotificationStore((s) => s.markAllRead);
  const dismiss = useNotificationStore((s) => s.dismiss);
  const clear = useNotificationStore((s) => s.clear);
  const unreadCount = useNotificationStore((s) => s.unreadCount);
  const panelRef = useRef<HTMLDivElement | null>(null);

  // 打开时一键标已读；点击外部自动关闭
  useEffect(() => {
    if (unreadCount > 0) markAllRead();
  }, [unreadCount, markAllRead]);

  useEffect(() => {
    const onMouseDown = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", onMouseDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onMouseDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  return (
    <div
      ref={panelRef}
      role="dialog"
      aria-label="运行通知"
      className="absolute right-0 top-[calc(100%+6px)] z-50 w-[380px] max-w-[calc(100vw-1rem)] overflow-hidden rounded-xl border border-white/10 bg-zinc-900/95 shadow-2xl backdrop-blur-md"
    >
      <div className="flex items-center justify-between gap-2 border-b border-white/5 px-3 py-2">
        <div className="flex items-center gap-2 text-xs text-zinc-300">
          <Bell className="h-3.5 w-3.5 text-info" />
          <span className="font-semibold">运行通知</span>
          <span className="text-[10px] text-zinc-500">
            {notifications.length === 0 ? "暂无通知" : `共 ${notifications.length} 条`}
          </span>
        </div>
        <div className="flex items-center gap-0.5 text-xs">
          {notifications.length > 0 && (
            <>
              <button
                onClick={clear}
                className="rounded px-1.5 py-1 text-zinc-400 transition-colors hover:bg-white/5 hover:text-zinc-100"
                title="清空全部"
              >
                清空
              </button>
            </>
          )}
          <button
            onClick={onClose}
            className="rounded p-1 text-zinc-400 transition-colors hover:bg-white/5 hover:text-zinc-100"
            title="关闭"
            aria-label="关闭通知面板"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      <div className="max-h-[60vh] overflow-y-auto px-2 py-2">
        {notifications.length === 0 ? (
          <p className="rounded-lg border border-white/5 bg-white/5 px-3 py-6 text-center text-xs text-zinc-500">
            暂无通知
          </p>
        ) : (
          <ul className="space-y-2">
            {notifications.map((item) => (
              <NotificationRow key={item.id} item={item} onDismiss={dismiss} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export function VoiceForgeTopNav() {
  const { pathname } = useLocation();
  const lastProjectId =
    typeof window !== "undefined" ? localStorage.getItem(LAST_VF_PROJECT_KEY) : null;
  const [notifOpen, setNotifOpen] = useState(false);
  const unreadCount = useNotificationStore((s) => s.unreadCount);

  const isActive = (it: NavItem) => {
    if (it.matchProjects) return pathname.startsWith("/voiceforge/projects/");
    if (it.end) return pathname === it.to;
    return pathname === it.to || pathname.startsWith(it.to + "/");
  };

  // “配音台”需要进入某个项目的配音工作区；无历史项目时回退到项目管理首页。
  const linkTo = (it: NavItem) =>
    it.matchProjects && lastProjectId ? `/voiceforge/projects/${lastProjectId}` : it.to;

  return (
    <header className="sticky top-0 z-40 flex h-12 items-center gap-1 border-b border-white/10 bg-zinc-950/90 px-4 text-zinc-300 backdrop-blur">
      <Link
        to="/voiceforge"
        className="mr-4 flex items-center gap-1.5 text-sm font-semibold text-white"
      >
        <Gem className="h-4 w-4 text-violet-400" />
        <span>VoiceForge</span>
      </Link>
      <nav className="flex items-center gap-1">
        {items.map((it) => {
          const Icon = it.icon;
          const active = isActive(it);
          return (
            <Link
              key={it.label}
              to={linkTo(it)}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm transition-colors hover:text-white",
                active ? "bg-violet-500/25 text-violet-100" : "text-zinc-300"
              )}
            >
              <Icon className="h-4 w-4" />
              {it.label}
            </Link>
          );
        })}
      </nav>

      {/* 右侧：统一通知入口（铃铛 + 抽屉） */}
      <div className="ml-auto flex items-center">
        <div className="relative">
          <button
            type="button"
            onClick={() => setNotifOpen((o) => !o)}
            className={cn(
              "relative flex h-8 w-8 items-center justify-center rounded-md transition-colors",
              notifOpen
                ? "bg-white/10 text-white"
                : "text-zinc-300 hover:bg-white/5 hover:text-white"
            )}
            title="运行通知"
            aria-label="运行通知"
            aria-expanded={notifOpen}
            aria-haspopup="dialog"
          >
            <Bell className="h-4 w-4" />
            {unreadCount > 0 && (
              <span
                className={cn(
                  "absolute -right-0.5 -top-0.5 min-w-[16px] h-[16px] rounded-full px-1 text-[10px] font-bold flex items-center justify-center border",
                  "bg-info text-info-foreground border-info/40"
                )}
                aria-label={`${unreadCount} 条未读通知`}
              >
                {unreadCount > 99 ? "99+" : unreadCount}
              </span>
            )}
          </button>
          {notifOpen && <NotificationPanel onClose={() => setNotifOpen(false)} />}
        </div>
      </div>
    </header>
  );
}
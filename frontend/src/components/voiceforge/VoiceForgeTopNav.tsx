import { Link, useLocation } from "react-router-dom";
import {
  Gem,
  LayoutGrid,
  Library,
  Mic,
  PlayCircle,
  Sparkles,
  Video,
} from "lucide-react";
import { cn } from "@/lib/utils";

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
];

export function VoiceForgeTopNav() {
  const { pathname } = useLocation();
  const lastProjectId = typeof window !== "undefined" ? localStorage.getItem(LAST_VF_PROJECT_KEY) : null;

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
                active
                  ? "bg-violet-500/25 text-violet-100"
                  : "text-zinc-300"
              )}
            >
              <Icon className="h-4 w-4" />
              {it.label}
            </Link>
          );
        })}
      </nav>
    </header>
  );
}

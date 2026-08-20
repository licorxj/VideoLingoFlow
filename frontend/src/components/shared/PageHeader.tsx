import { cn } from "@/lib/utils";
import { ChevronLeft } from "lucide-react";
import { Link } from "react-router-dom";

export type PageHeaderTone = "default" | "primary" | "success" | "warning" | "info" | "ai" | "destructive";

interface BreadcrumbItem {
  label: string;
  to?: string;
}

interface PageHeaderProps {
  icon?: React.ComponentType<{ className?: string }>;
  title: React.ReactNode;
  detail?: React.ReactNode;
  actions?: React.ReactNode;
  back?: { to: string; label?: string };
  breadcrumbs?: BreadcrumbItem[];
  sticky?: boolean;
  /** 顶栏装饰色调，影响左侧 icon 背景色 */
  tone?: PageHeaderTone;
  className?: string;
  /** 紧凑模式：减小高度与字号（适合工具型子页面） */
  compact?: boolean;
  hideTitle?: boolean;
}

const TONE_BG: Record<PageHeaderTone, string> = {
  default: "bg-muted text-muted-foreground",
  primary: "bg-primary/12 text-primary",
  success: "tone-success-soft",
  warning: "tone-warning-soft",
  info: "tone-info-soft",
  ai: "tone-ai-soft",
  destructive: "tone-danger-soft",
};

const TONE_ICON: Record<PageHeaderTone, string> = {
  default: "text-muted-foreground",
  primary: "text-primary",
  success: "text-success",
  warning: "text-warning",
  info: "text-info",
  ai: "text-ai",
  destructive: "text-destructive",
};

export function PageHeader({
  icon: Icon,
  title,
  detail,
  actions,
  back,
  breadcrumbs,
  sticky = false,
  tone = "primary",
  className,
  compact = false,
  hideTitle = false,
}: PageHeaderProps) {
  return (
    <div
      className={cn(
        sticky && "topbar-sticky",
        hideTitle ? "px-1 py-1 sm:px-2 sm:py-1" : "px-1 py-3 sm:px-2 sm:py-4",
        className,
      )}
    >
      <div className={cn("flex flex-col", hideTitle ? "gap-1" : "gap-3", !compact && "sm:flex-row sm:items-start sm:justify-between")}>
        <div className="min-w-0 flex-1">
          {(back || (breadcrumbs && breadcrumbs.length > 1)) && (
            <div className={cn("flex items-center gap-1.5 text-xs text-muted-foreground", !hideTitle && "mb-2")}>
              {back && (
                <Link
                  to={back.to}
                  className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 transition-colors hover:bg-accent hover:text-foreground"
                >
                  <ChevronLeft className="h-3.5 w-3.5" />
                  {back.label || "返回"}
                </Link>
              )}
              {breadcrumbs && breadcrumbs.length > 0 && (
                <>
                  {breadcrumbs.map((b, i) => (
                    <span key={i} className="inline-flex items-center gap-1.5">
                      {i > 0 && <span className="text-muted-foreground/50">/</span>}
                      {b.to ? (
                        <Link to={b.to} className="hover:text-foreground transition-colors">
                          {b.label}
                        </Link>
                      ) : (
                        <span className={i === breadcrumbs.length - 1 ? "text-foreground font-medium" : ""}>
                          {b.label}
                        </span>
                      )}
                    </span>
                  ))}
                </>
              )}
            </div>
          )}
          {!hideTitle && (
            <div className="flex items-center gap-2.5">
              {Icon && (
                <div
                  className={cn(
                    "flex items-center justify-center rounded-xl shrink-0",
                    compact ? "h-9 w-9" : "h-10 w-10",
                    TONE_BG[tone],
                  )}
                >
                  <Icon className={cn(compact ? "h-4.5 w-4.5" : "h-5 w-5", TONE_ICON[tone])} />
                </div>
              )}
              <div className="min-w-0">
                <h2
                  className={cn(
                    "flex items-center gap-2 font-extrabold tracking-tight text-foreground",
                    compact ? "text-lg" : "text-2xl",
                  )}
                >
                  {title}
                </h2>
                {detail && (
                  <p className="mt-1 text-sm text-muted-foreground">{detail}</p>
                )}
              </div>
            </div>
          )}
        </div>
        {actions && (
          <div className="flex flex-wrap items-center gap-2 shrink-0 empty:hidden">{actions}</div>
        )}
      </div>
    </div>
  );
}

export default PageHeader;

import { cn } from "@/lib/utils";

export type PageTone =
  | "default"
  | "workbench"
  | "batch"
  | "history"
  | "editing"
  | "voiceforge"
  | "collab"
  | "llm"
  | "settings";

interface PageBackgroundProps {
  tone?: PageTone;
  className?: string;
  children: React.ReactNode;
}

/**
 * 页面背景层：在容器内提供低饱和的角落装饰渐变。
 * tone="default" 时不应用个性化 tint，仅跟随父级 .gradient-mesh。
 * noPageBg=true 时整体隐藏装饰渐变（用户偏好关闭）。
 */
export function PageBackground({ tone = "default", className, children }: PageBackgroundProps) {
  const toneClass = tone === "default" ? "" : `page-tone-${tone}`;
  return (
    <div className={cn("page-bg", toneClass, className)}>
      {children}
    </div>
  );
}

export default PageBackground;

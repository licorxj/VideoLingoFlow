import { Inbox } from "lucide-react";
import { cn } from "@/lib/utils";

interface EmptyStateProps {
  icon?: React.ComponentType<{ className?: string }>;
  title: string;
  detail?: string;
  className?: string;
  action?: React.ReactNode;
}

export function EmptyState({ icon: Icon = Inbox, title, detail, className, action }: EmptyStateProps) {
  return (
    <div className={cn("flex flex-col items-center justify-center px-6 py-16 text-center", className)}>
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-muted text-muted-foreground/70">
        <Icon className="h-6 w-6" />
      </div>
      <p className="mt-4 font-medium text-muted-foreground">{title}</p>
      {detail && <p className="mt-1 max-w-sm text-sm text-muted-foreground/80">{detail}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export default EmptyState;

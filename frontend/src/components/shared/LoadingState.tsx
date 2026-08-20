import { Loader2, Inbox } from "lucide-react";
import { cn } from "@/lib/utils";

interface LoadingStateProps {
  className?: string;
  label?: string;
  icon?: React.ComponentType<{ className?: string }>;
}

export function LoadingState({ className, label, icon: Icon = Loader2 }: LoadingStateProps) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-2 px-6 py-16 text-center", className)}>
      <Icon className="h-7 w-7 animate-spin text-primary/70" />
      {label && <p className="text-sm text-muted-foreground">{label}</p>}
    </div>
  );
}

export default LoadingState;

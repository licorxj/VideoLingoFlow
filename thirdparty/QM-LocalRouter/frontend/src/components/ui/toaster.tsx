import React from "react";
import { useToastStore } from "../../stores/toast";
import { X, CheckCircle, AlertCircle } from "lucide-react";

export function Toaster() {
  const { toasts, removeToast } = useToastStore();

  if (toasts.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2 max-w-sm">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={
            "flex items-start gap-3 rounded-lg border p-4 shadow-lg backdrop-blur-sm animate-in slide-in-from-bottom-5 fade-in-0 " +
            (t.variant === "destructive"
              ? "border-red-500/30 bg-red-950/90 text-red-200"
              : t.variant === "success"
              ? "border-green-500/30 bg-green-950/90 text-green-200"
              : "border-border bg-card/95 text-foreground")
          }
        >
          <div className="pt-0.5">
            {t.variant === "destructive" ? (
              <AlertCircle className="h-4 w-4 text-red-400" />
            ) : t.variant === "success" ? (
              <CheckCircle className="h-4 w-4 text-green-400" />
            ) : null}
          </div>
          <div className="flex-1 min-w-0">
            {t.title && <p className="text-sm font-medium">{t.title}</p>}
            {t.description && <p className="text-xs opacity-80 mt-0.5">{t.description}</p>}
          </div>
          <button onClick={() => removeToast(t.id)} className="opacity-60 hover:opacity-100 transition-opacity">
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
    </div>
  );
}

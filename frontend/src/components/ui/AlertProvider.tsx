import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";
import { AlertTriangle, Info, XCircle, CheckCircle2 } from "lucide-react";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */
type AlertType = "info" | "warning" | "error" | "success";

interface AlertContextValue {
  alert: (msg: string, type?: AlertType, title?: string) => void;
  confirm: (msg: string, opts?: { type?: AlertType; title?: string; confirmLabel?: string; cancelLabel?: string }) => Promise<boolean>;
}

const AlertContext = createContext<AlertContextValue>({
  alert: () => {},
  confirm: () => Promise.resolve(false),
});

export const useAlert = () => useContext(AlertContext);

/* ------------------------------------------------------------------ */
/*  Config                                                             */
/* ------------------------------------------------------------------ */
const TYPE_CONFIG: Record<AlertType, {
  icon: typeof AlertTriangle;
  iconClass: string;
  iconBgClass: string;
  borderClass: string;
  btnClass: string;
}> = {
  info:    { icon: Info,         iconClass: "text-blue-500",    iconBgClass: "bg-blue-500/10",    borderClass: "border-blue-500/20",    btnClass: "bg-blue-500 hover:bg-blue-600" },
  warning: { icon: AlertTriangle, iconClass: "text-amber-500",   iconBgClass: "bg-amber-500/10",   borderClass: "border-amber-500/20",   btnClass: "bg-amber-500 hover:bg-amber-600" },
  error:   { icon: XCircle,      iconClass: "text-red-500",     iconBgClass: "bg-red-500/10",     borderClass: "border-red-500/20",     btnClass: "bg-red-500 hover:bg-red-600" },
  success: { icon: CheckCircle2, iconClass: "text-emerald-500", iconBgClass: "bg-emerald-500/10", borderClass: "border-emerald-500/20", btnClass: "bg-emerald-500 hover:bg-emerald-600" },
};

const ALERT_TITLE: Record<AlertType, string> = {
  info: "提示", warning: "警告", error: "错误", success: "成功",
};

const SVG_ICONS: Record<AlertType, string> = {
  info:    '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>',
  warning: '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>',
  error:   '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/></svg>',
  success: '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="m9 11 3 3L22 4"/></svg>',
};

/* ------------------------------------------------------------------ */
/*  Detect theme (light / dark)                                        */
/* ------------------------------------------------------------------ */
function isDark() {
  return document.documentElement.classList.contains("dark");
}

/* ------------------------------------------------------------------ */
/*  Shared CSS for the vanilla-DOM modal                               */
/* ------------------------------------------------------------------ */
const MODAL_CSS = `
  @keyframes avl-fade-in { from { opacity: 0 } to { opacity: 1 } }
  @keyframes avl-scale-in { from { opacity: 0; transform: scale(0.95) } to { opacity: 1; transform: scale(1) } }
  #avl-alert-overlay {
    position: fixed; inset: 0; z-index: 99999;
    display: flex; align-items: center; justify-content: center; padding: 1rem;
  }
  #avl-alert-backdrop {
    position: absolute; inset: 0;
    background: rgba(0,0,0,0.45); backdrop-filter: blur(4px); -webkit-backdrop-filter: blur(4px);
    animation: avl-fade-in 0.15s ease-out;
  }
  #avl-alert-card {
    position: relative; width: 100%; max-width: 24rem;
    border-radius: 1rem; overflow: hidden; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25);
    animation: avl-scale-in 0.2s ease-out;
  }
  #avl-alert-header { display: flex; align-items: flex-start; gap: 0.75rem; padding: 1.25rem 1.25rem 0.75rem; }
  #avl-alert-icon-wrap { flex-shrink: 0; width: 2.25rem; height: 2.25rem; border-radius: 0.75rem; display: flex; align-items: center; justify-content: center; }
  #avl-alert-icon-wrap svg { width: 1.25rem; height: 1.25rem; }
  #avl-alert-title { font-size: 0.875rem; font-weight: 700; line-height: 1.4; }
  #avl-alert-msg { font-size: 0.8125rem; line-height: 1.6; margin-top: 0.375rem; white-space: pre-wrap; word-break: break-word; }
  #avl-alert-footer { display: flex; align-items: center; justify-content: flex-end; gap: 0.5rem; padding: 0.25rem 1.25rem 1rem; }
  #avl-alert-footer button {
    padding: 0.375rem 1rem; font-size: 0.8125rem; font-weight: 600; border-radius: 0.5rem;
    border: none; cursor: pointer; transition: all 0.15s ease; outline: none;
  }
  #avl-alert-footer button:active { transform: scale(0.97); }
`;

function injectStyles() {
  if (document.getElementById("avl-alert-styles")) return;
  const style = document.createElement("style");
  style.id = "avl-alert-styles";
  style.textContent = MODAL_CSS;
  document.head.appendChild(style);
}

/* ------------------------------------------------------------------ */
/*  Detect alert type from message text                                */
/* ------------------------------------------------------------------ */
function detectAlertType(text: string): AlertType {
  const lower = text.toLowerCase();
  if (lower.includes("失败") || lower.includes("错误") || lower.includes("error") || lower.includes("fail"))
    return "error";
  if (lower.includes("成功") || lower.includes("success"))
    return "success";
  return "info";
}

function detectConfirmType(text: string): AlertType {
  const lower = text.toLowerCase();
  if (lower.includes("删除") || lower.includes("清空") || lower.includes("停止") || lower.includes("覆盖") || lower.includes("不可撤销"))
    return "warning";
  return "info";
}

/* ------------------------------------------------------------------ */
/*  Get icon SVG string by type                                        */
/* ------------------------------------------------------------------ */
function getIconSvg(type: AlertType): string {
  return SVG_ICONS[type];
}

function getIconColorClass(type: AlertType): string {
  const map: Record<AlertType, string> = {
    info: "color:#3b82f6", warning: "color:#f59e0b", error: "color:#ef4444", success: "color:#10b981",
  };
  return map[type];
}

function getIconBgClass(type: AlertType): string {
  const map: Record<AlertType, string> = {
    info: "background:rgba(59,130,246,0.1)",
    warning: "background:rgba(245,158,11,0.1)",
    error: "background:rgba(239,68,68,0.1)",
    success: "background:rgba(16,185,129,0.1)",
  };
  return map[type];
}

function getBtnColor(type: AlertType, isConfirmDanger: boolean): string {
  if (isConfirmDanger) return "background:#ef4444; color:#fff;";
  const map: Record<AlertType, string> = {
    info: "background:#3b82f6; color:#fff;",
    warning: "background:#f59e0b; color:#fff;",
    error: "background:#ef4444; color:#fff;",
    success: "background:#10b981; color:#fff;",
  };
  return map[type];
}

function getBtnHoverColor(type: AlertType, isConfirmDanger: boolean): string {
  if (isConfirmDanger) return "background:#dc2626;";
  const map: Record<AlertType, string> = {
    info: "background:#2563eb;",
    warning: "background:#d97706;",
    error: "background:#dc2626;",
    success: "background:#059669;",
  };
  return map[type];
}

function getBorderColor(type: AlertType): string {
  const map: Record<AlertType, string> = {
    info: "rgba(59,130,246,0.2)", warning: "rgba(245,158,11,0.2)",
    error: "rgba(239,68,68,0.2)", success: "rgba(16,185,129,0.2)",
  };
  return map[type];
}

function getThemeColors() {
  const dark = isDark();
  return {
    cardBg: dark ? "#1e293b" : "#ffffff",
    cardBorder: dark ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.06)",
    titleColor: dark ? "#f1f5f9" : "#0f172a",
    msgColor: dark ? "#94a3b8" : "#64748b",
    cancelBg: dark ? "rgba(255,255,255,0.08)" : "#f1f5f9",
    cancelColor: dark ? "#cbd5e1" : "#475569",
    cancelHoverBg: dark ? "rgba(255,255,255,0.12)" : "#e2e8f0",
  };
}

/* ------------------------------------------------------------------ */
/*  Render modal via vanilla DOM (works even when main thread blocked) */
/* ------------------------------------------------------------------ */
function renderModal(opts: {
  type: AlertType;
  title: string;
  message: string;
  isConfirm: boolean;
  confirmLabel: string;
  cancelLabel: string;
  onResult: (v: boolean) => void;
}) {
  injectStyles();
  removeModal();

  const t = getThemeColors();
  const isDanger = opts.isConfirm && opts.type === "warning";

  const overlay = document.createElement("div");
  overlay.id = "avl-alert-overlay";

  const close = (result: boolean) => {
    overlay.remove();
    opts.onResult(result);
  };

  overlay.innerHTML = `
    <div id="avl-alert-backdrop"></div>
    <div id="avl-alert-card" style="background:${t.cardBg}; border:1px solid ${t.cardBorder};">
      <div id="avl-alert-header">
        <div id="avl-alert-icon-wrap" style="${getIconBgClass(opts.type)}">
          <span style="${getIconColorClass(opts.type)}">${getIconSvg(opts.type)}</span>
        </div>
        <div style="flex:1;min-width:0;padding-top:2px">
          <div id="avl-alert-title" style="color:${t.titleColor}">${opts.title}</div>
          <div id="avl-alert-msg" style="color:${t.msgColor}">${opts.message.replace(/</g, "&lt;").replace(/>/g, "&gt;")}</div>
        </div>
      </div>
      <div id="avl-alert-footer">
        ${opts.isConfirm ? `<button id="avl-alert-cancel" style="background:${t.cancelBg};color:${t.cancelColor}">${opts.cancelLabel}</button>` : ""}
        <button id="avl-alert-confirm" style="${getBtnColor(opts.type, isDanger)}">${opts.isConfirm ? opts.confirmLabel : "知道了"}</button>
      </div>
    </div>
  `;

  document.body.appendChild(overlay);

  /* ---- event wiring ---- */
  const confirmBtn = overlay.querySelector<HTMLButtonElement>("#avl-alert-confirm")!;
  const cancelBtn = overlay.querySelector<HTMLButtonElement>("#avl-alert-cancel");
  const backdrop = overlay.querySelector<HTMLDivElement>("#avl-alert-backdrop")!;

  confirmBtn.onmouseenter = () => { confirmBtn.style.cssText += getBtnHoverColor(opts.type, isDanger); };
  confirmBtn.onmouseleave = () => { confirmBtn.style.cssText = `${getBtnColor(opts.type, isDanger)} padding:0.375rem 1rem;font-size:0.8125rem;font-weight:600;border-radius:0.5rem;border:none;cursor:pointer;transition:all 0.15s ease;outline:none;`; };
  confirmBtn.onclick = () => close(true);

  if (cancelBtn) {
    cancelBtn.onmouseenter = () => (cancelBtn.style.background = t.cancelHoverBg);
    cancelBtn.onmouseleave = () => (cancelBtn.style.background = t.cancelBg);
    cancelBtn.onclick = () => close(false);
    backdrop.onclick = () => close(false);
  }

  const keyHandler = (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      close(e.key === "Enter");
      document.removeEventListener("keydown", keyHandler, true);
    }
  };
  document.addEventListener("keydown", keyHandler, true);

  /* Focus confirm button */
  setTimeout(() => confirmBtn.focus(), 0);
}

function removeModal() {
  document.getElementById("avl-alert-overlay")?.remove();
}

/* ------------------------------------------------------------------ */
/*  Provider                                                           */
/* ------------------------------------------------------------------ */
export default function AlertProvider({ children }: { children: ReactNode }) {
  /* -- React-level state for non-blocking alert (rendered via portal) */
  const [alertState, setAlertState] = useState<{
    open: boolean; type: AlertType; title: string; message: string;
  }>({ open: false, type: "info", title: "", message: "" });

  const closeAlert = useCallback(() => setAlertState((s) => ({ ...s, open: false })), []);

  /* -- override window.alert & window.confirm ----------------------- */
  useEffect(() => {
    const origAlert = window.alert.bind(window);
    const origConfirm = window.confirm.bind(window);

    /* alert: non-blocking, renders via React portal */
    window.alert = (msg: unknown) => {
      const text = String(msg ?? "");
      const type = detectAlertType(text);
      setAlertState({ open: true, type, title: ALERT_TITLE[type], message: text });
    };

    /* confirm: keep native (synchronous) for code that expects sync return */
    window.confirm = (msg: unknown) => origConfirm(String(msg ?? ""));

    return () => { window.alert = origAlert; window.confirm = origConfirm; };
  }, []);

  /* -- keyboard for React-rendered alert ---------------------------- */
  useEffect(() => {
    if (!alertState.open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Enter" || e.key === "Escape") {
        e.preventDefault();
        closeAlert();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [alertState.open, closeAlert]);

  const cfg = TYPE_CONFIG[alertState.type];
  const Icon = cfg.icon;

  const alertModal = alertState.open ? (
    <div id="avl-alert-overlay" className="pointer-events-auto fixed inset-0 z-[99999] flex items-center justify-center p-4" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm animate-fade-in" onClick={closeAlert} />
      <div className={cn(
        "relative w-full max-w-sm bg-card border rounded-2xl shadow-2xl p-0 overflow-hidden",
        "animate-[scale-in_0.2s_ease-out]",
        cfg.borderClass,
      )}>
        <div className="flex items-start gap-3 px-5 pt-5 pb-3">
          <div className={cn("flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center", cfg.iconBgClass)}>
            <Icon className={cn("w-5 h-5", cfg.iconClass)} />
          </div>
          <div className="flex-1 min-w-0 pt-0.5">
            <h3 className="text-sm font-bold text-foreground">{alertState.title}</h3>
            <p className="text-[13px] text-muted-foreground mt-1.5 leading-relaxed whitespace-pre-wrap break-words">
              {alertState.message}
            </p>
          </div>
        </div>
        <div className="flex items-center justify-end px-5 pb-4 pt-1">
          <button onClick={closeAlert}
            className={cn("px-4 py-1.5 text-[13px] font-bold rounded-lg text-white transition-colors", cfg.btnClass)}
            autoFocus>
            知道了
          </button>
        </div>
      </div>
    </div>
  ) : null;

  return (
    <AlertContext.Provider value={{
      alert: (msg, type = "info", title) => {
        const t = type;
        setAlertState({ open: true, type: t, title: title ?? ALERT_TITLE[t], message: msg });
      },
      confirm: (msg, opts) => {
        return new Promise<boolean>((resolve) => {
          const t = opts?.type ?? detectConfirmType(msg);
          const isDanger = t === "warning";
          renderModal({
            type: t,
            title: opts?.title ?? (isDanger ? "确认操作" : "确认"),
            message: msg,
            isConfirm: true,
            confirmLabel: opts?.confirmLabel ?? (isDanger ? "确认执行" : "确定"),
            cancelLabel: opts?.cancelLabel ?? "取消",
            onResult: (v) => resolve(v),
          });
        });
      },
    }}>
      {children}
      {createPortal(alertModal, document.body)}
    </AlertContext.Provider>
  );
}

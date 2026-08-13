import { useState, useEffect } from "react";
import { createPortal } from "react-dom";
import { ttsInterfacesApi, TTSInterface } from "@/api/ttsInterfaces";
import { settingsApi } from "@/api/settings";
import TTSInterfaceEditor from "./TTSInterfaceEditor";
import TTSInterfaceTestModal from "./TTSInterfaceTestModal";
import { cn } from "@/lib/utils";
import {
  Volume2,
  Plus,
  Pencil,
  Trash2,
  Shield,
  Zap,
  CheckCircle2,
  FlaskConical,
  RefreshCw,
  ExternalLink,
} from "lucide-react";

const TYPE_LABELS: Record<string, string> = {
  local: "Local API",
  online: "OpenAI Format",
  sdk: "SDK",
};

export default function TTSSettings() {
  const [interfaces, setInterfaces] = useState<TTSInterface[]>([]);
  const [activeEngine, setActiveEngine] = useState("edge_tts");
  const [editing, setEditing] = useState<TTSInterface | null>(null);
  const [showEditor, setShowEditor] = useState(false);
  const [testingIface, setTestingIface] = useState<TTSInterface | null>(null);

  const load = async () => {
    const [ifaceRes, engineRes] = await Promise.all([
      ttsInterfacesApi.list(),
      settingsApi.get("tts.method"),
    ]);
    setInterfaces(ifaceRes.data.interfaces || []);
    setActiveEngine(engineRes.data.value || "edge_tts");
  };

  useEffect(() => {
    load();
  }, []);

  const handleSelect = async (id: string) => {
    setActiveEngine(id);
    await settingsApi.update("tts.method", id);
  };

  const handleToggle = async (id: string, enabled: boolean) => {
    await ttsInterfacesApi.toggle(id, enabled);
    load();
  };

  const handleDelete = async (id: string) => {
    if (!confirm("确定要删除此接口吗？")) return;
    await ttsInterfacesApi.delete(id);
    load();
  };

  const handleEdit = (iface: TTSInterface) => {
    setEditing(iface);
    setShowEditor(true);
  };
  const handleAdd = () => {
    setEditing(null);
    setShowEditor(true);
  };
  const handleRefresh = async () => {
    await ttsInterfacesApi.reload();
    load();
  };
  const handleSaved = () => {
    setShowEditor(false);
    setEditing(null);
    load();
  };

  return (
    <div className="space-y-5 stagger-children">
      <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-3">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Zap className="w-4 h-4 text-primary" />
          当前 TTS 引擎
        </h3>
        <select
          className="w-full px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none appearance-none"
          value={activeEngine}
          onChange={(e) => handleSelect(e.target.value)}
        >
          {interfaces
            .filter((i) => i.enabled)
            .map((i) => (
              <option key={i.id} value={i.id}>
                {i.name}
              </option>
            ))}
        </select>
      </div>

      <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold flex items-center gap-2">
            <Volume2 className="w-4 h-4 text-primary" />
            接口列表
          </h3>
          <div className="flex items-center gap-2">
            <button
              onClick={handleRefresh}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border border-border/60 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent/60 transition-all duration-200 active:scale-[0.97]"
              title="刷新接口数据"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              刷新
            </button>
            <button
              onClick={handleAdd}
              className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold bg-primary text-primary-foreground rounded-lg transition-all duration-200 hover:shadow-lg hover:shadow-primary/25 active:scale-[0.97]"
            >
              <Plus className="w-3.5 h-3.5" />
              添加接口
            </button>
          </div>
        </div>

        <div className="space-y-2">
          {interfaces.map((iface) => {
            const isActive = activeEngine === iface.id;
            return (
              <div
                key={iface.id}
                className={cn(
                  "flex items-center gap-3 p-4 rounded-xl border transition-all duration-200",
                  isActive
                    ? "border-primary/40 bg-primary/5"
                    : "border-border/40 hover:border-border/60"
                )}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold text-sm">{iface.name}</span>
                    <span className="text-[11px] px-2 py-0.5 rounded-md bg-muted text-muted-foreground font-medium">
                      {TYPE_LABELS[iface.type] || iface.type}
                    </span>
                    {iface.builtin && (
                      <span className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-md bg-blue-500/10 text-blue-500 font-medium">
                        <Shield className="w-3 h-3" />
                        内置
                      </span>
                    )}
                    {isActive && (
                      <span className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-500 font-medium">
                        <CheckCircle2 className="w-3 h-3" />
                        当前
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">
                    {iface.description || "No description"}
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <label className="relative cursor-pointer flex items-center gap-1.5">
                    <input
                      type="checkbox"
                      checked={iface.enabled}
                      onChange={(e) => handleToggle(iface.id, e.target.checked)}
                      className="peer sr-only"
                    />
                    <div className="w-8 h-[18px] bg-muted rounded-full peer-checked:bg-primary transition-colors duration-200" />
                    <div className="absolute left-0.5 top-0.5 w-3.5 h-3.5 bg-background rounded-full shadow-sm peer-checked:translate-x-[14px] transition-transform duration-200" />
                  </label>
                  <button
                    onClick={() => setTestingIface(iface)}
                    className="p-1.5 rounded-lg border border-border/40 hover:bg-emerald-500/10 text-muted-foreground hover:text-emerald-500 transition-all duration-200"
                    title="测试接口"
                  >
                    <FlaskConical className="w-3.5 h-3.5" />
                  </button>
                  {iface.api_source_url && (
                    <a
                      href={iface.api_source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="p-1.5 rounded-lg border border-border/40 hover:bg-blue-500/10 text-muted-foreground hover:text-blue-500 transition-all duration-200"
                      title="API 获取地址"
                    >
                      <ExternalLink className="w-3.5 h-3.5" />
                    </a>
                  )}
                  <button
                    onClick={() => handleEdit(iface)}
                    className="p-1.5 rounded-lg border border-border/40 hover:bg-accent/60 text-muted-foreground hover:text-foreground transition-all duration-200"
                    title="编辑"
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                  {!iface.builtin && (
                    <button
                      onClick={() => handleDelete(iface.id)}
                      className="p-1.5 rounded-lg border border-border/40 hover:bg-red-500/10 text-muted-foreground hover:text-red-500 transition-all duration-200"
                      title="删除"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {showEditor && (
        createPortal(
          <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 backdrop-blur-sm animate-fade-in overflow-y-auto py-10 px-4">
            <div className="bg-background border border-border/60 rounded-2xl shadow-2xl w-[min(880px,92vw)] animate-scale-in">
              <TTSInterfaceEditor
                iface={editing}
                onSaved={handleSaved}
                onCancel={() => setShowEditor(false)}
              />
            </div>
          </div>,
          document.body
        )
      )}

      {testingIface && (
        <TTSInterfaceTestModal
          iface={testingIface}
          onClose={() => setTestingIface(null)}
        />
      )}
    </div>
  );
}
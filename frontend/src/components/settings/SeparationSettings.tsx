import { useState, useEffect } from "react";
import { createPortal } from "react-dom";
import {
  separationInterfacesApi,
  SeparationInterface,
} from "@/api/separationInterfaces";
import { settingsApi } from "@/api/settings";
import SeparationInterfaceEditor from "./SeparationInterfaceEditor";
import { cn } from "@/lib/utils";
import {
  Mic2,
  Plus,
  Pencil,
  Trash2,
  Shield,
  Zap,
  CheckCircle2,
  RefreshCw,
  Music,
} from "lucide-react";

const TYPE_LABELS: Record<string, string> = {
  local: "Local API",
  online: "Online API",
  sdk: "SDK",
};

interface ModelDetail {
  name: string;
  description: string;
}

export default function SeparationSettings() {
  const [interfaces, setInterfaces] = useState<SeparationInterface[]>([]);
  const [activeEngine, setActiveEngine] = useState("");
  const [activeModel, setActiveModel] = useState("");
  const [editing, setEditing] = useState<SeparationInterface | null>(null);
  const [showEditor, setShowEditor] = useState(false);

  const load = async () => {
    const [ifaceRes, engineRes, modelRes] = await Promise.all([
      separationInterfacesApi.list(),
      settingsApi.get("separation.method"),
      settingsApi.get("separation.model"),
    ]);
    const list = ifaceRes.data.interfaces || [];
    setInterfaces(list);
    const engine = engineRes.data.value || "";
    setActiveEngine(engine);
    const model = modelRes.data.value || "";
    const activeIface = list.find((i: SeparationInterface) => i.id === engine);
    if (activeIface) {
      setActiveModel(model || activeIface.config?.model || "");
    } else {
      setActiveModel(model);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const handleSelectEngine = async (id: string) => {
    setActiveEngine(id);
    await settingsApi.update("separation.method", id);
    const iface = interfaces.find((i) => i.id === id);
    const defaultModel = iface?.config?.model || "";
    setActiveModel(defaultModel);
    await settingsApi.update("separation.model", defaultModel);
  };

  const handleSelectModel = async (model: string) => {
    setActiveModel(model);
    await settingsApi.update("separation.model", model);
  };

  const handleToggle = async (id: string, enabled: boolean) => {
    await separationInterfacesApi.toggle(id, enabled);
    load();
  };

  const handleDelete = async (id: string) => {
    if (!confirm("确定要删除此接口吗？")) return;
    await separationInterfacesApi.delete(id);
    load();
  };

  const handleEdit = (iface: SeparationInterface) => {
    setEditing(iface);
    setShowEditor(true);
  };
  const handleAdd = () => {
    setEditing(null);
    setShowEditor(true);
  };
  const handleRefresh = async () => {
    await separationInterfacesApi.reload();
    load();
  };
  const handleSaved = () => {
    setShowEditor(false);
    setEditing(null);
    load();
  };

  // 默认模型下拉的候选项来自当前接口配置
  const modelOptions = interfaces.find((i) => i.id === activeEngine)?.config?.model_options || [];

  return (
    <div className="space-y-4 stagger-children">
      {/* Default Interface & Model */}
      <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Zap className="w-4 h-4 text-primary" />
          默认音轨分离设置
        </h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1 block">
              默认接口
            </label>
            <select
              className="w-full px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none appearance-none"
              value={activeEngine}
              onChange={(e) => handleSelectEngine(e.target.value)}
            >
              <option value="">未选择</option>
              {interfaces
                .filter((i) => i.enabled)
                .map((i) => (
                  <option key={i.id} value={i.id}>
                    {i.name}
                  </option>
                ))}
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1 block">
              默认模型
            </label>
            <select
              className="w-full px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none appearance-none"
              value={activeModel}
              onChange={(e) => handleSelectModel(e.target.value)}
              disabled={modelOptions.length === 0}
            >
              <option value="">使用接口默认</option>
              {modelOptions.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Interface List */}
      <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold flex items-center gap-2">
            <Mic2 className="w-4 h-4 text-primary" />
            音轨分离接口列表
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
                  <div className="flex items-center gap-3 mt-1">
                    <p className="text-xs text-muted-foreground">
                      {iface.description || "No description"}
                    </p>
                    {iface.config?.model_options && iface.config.model_options.length > 0 && (
                      <span className="text-[10px] text-muted-foreground/70 flex items-center gap-1">
                        <Music className="w-3 h-3" />
                        {iface.config.model_options.length} 模型
                      </span>
                    )}
                  </div>
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

      {showEditor &&
        createPortal(
          <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 backdrop-blur-sm animate-fade-in overflow-y-auto py-6 px-4">
            <div className="bg-background border-2 border-primary/40 ring-1 ring-primary/10 rounded-2xl shadow-2xl shadow-primary/10 w-[min(1056px,92vw)] animate-scale-in">
              <SeparationInterfaceEditor
                iface={editing}
                onSaved={handleSaved}
                onCancel={() => setShowEditor(false)}
              />
            </div>
          </div>,
          document.body
        )}
    </div>
  );
}

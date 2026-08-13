import { useState, useEffect } from "react";
import { createPortal } from "react-dom";
import { imagegenInterfacesApi, ImageGenInterface } from "@/api/imagegenInterfaces";
import { settingsApi } from "@/api/settings";
import ImageGenInterfaceEditor from "./ImageGenInterfaceEditor";
import { cn } from "@/lib/utils";
import {
  Image,
  Plus,
  Pencil,
  Trash2,
  Shield,
  Zap,
  CheckCircle2,
  RefreshCw,
  ExternalLink,
  Wallet,
  BookOpen,
} from "lucide-react";

const TYPE_LABELS: Record<string, string> = {
  sdk: "SDK",
  openai_compatible: "OpenAI Compatible",
};

export default function ImageGenSettings() {
  const [interfaces, setInterfaces] = useState<ImageGenInterface[]>([]);
  const [activeEngine, setActiveEngine] = useState("");
  const [defaultT2IModel, setDefaultT2IModel] = useState("");
  const [defaultI2IModel, setDefaultI2IModel] = useState("");
  const [editing, setEditing] = useState<ImageGenInterface | null>(null);
  const [showEditor, setShowEditor] = useState(false);
  const [refreshingBalance, setRefreshingBalance] = useState<string | null>(null);

  const load = async () => {
    const [ifaceRes, engineRes, t2iRes, i2iRes] = await Promise.all([
      imagegenInterfacesApi.list(),
      settingsApi.get("imagegen.method").catch(() => ({ data: { value: "" } })),
      settingsApi.get("imagegen.default_t2i_model").catch(() => ({ data: { value: "" } })),
      settingsApi.get("imagegen.default_i2i_model").catch(() => ({ data: { value: "" } })),
    ]);
    setInterfaces(Array.isArray(ifaceRes.data) ? ifaceRes.data : ifaceRes.data?.interfaces || []);
    setActiveEngine(engineRes.data.value || "");
    setDefaultT2IModel(t2iRes.data.value || "");
    setDefaultI2IModel(i2iRes.data.value || "");
  };

  useEffect(() => {
    load();
  }, []);

  const handleSelect = async (id: string) => {
    setActiveEngine(id);
    await settingsApi.update("imagegen.method", id);
    // Clear model selections when interface changes
    setDefaultT2IModel("");
    setDefaultI2IModel("");
    await settingsApi.update("imagegen.default_t2i_model", "");
    await settingsApi.update("imagegen.default_i2i_model", "");
  };

  const handleSelectT2IModel = async (model: string) => {
    setDefaultT2IModel(model);
    await settingsApi.update("imagegen.default_t2i_model", model);
  };

  const handleSelectI2IModel = async (model: string) => {
    setDefaultI2IModel(model);
    await settingsApi.update("imagegen.default_i2i_model", model);
  };

  // Get the active interface's models filtered by mode
  const activeIface = interfaces.find((i) => i.id === activeEngine);
  const t2iModels = (activeIface?.config.model_options || []).filter((m) => {
    const meta = activeIface?.config.model_metadata?.[m];
    return meta?.modes?.includes("t2i") ?? true; // default show if no metadata
  });
  const i2iModels = (activeIface?.config.model_options || []).filter((m) => {
    const meta = activeIface?.config.model_metadata?.[m];
    return meta?.modes?.includes("i2i") ?? true;
  });

  const handleToggle = async (id: string, enabled: boolean) => {
    await imagegenInterfacesApi.toggle(id, enabled);
    load();
  };

  const handleDelete = async (id: string) => {
    if (!confirm("确定要删除此接口吗？")) return;
    await imagegenInterfacesApi.delete(id);
    load();
  };

  const handleEdit = (iface: ImageGenInterface) => {
    setEditing(iface);
    setShowEditor(true);
  };

  const handleAdd = () => {
    setEditing(null);
    setShowEditor(true);
  };

  const handleRefresh = async () => {
    await imagegenInterfacesApi.reload();
    load();
  };

  const handleSaved = () => {
    setShowEditor(false);
    setEditing(null);
    load();
  };

  const handleRefreshBalance = async (id: string) => {
    setRefreshingBalance(id);
    try {
      await imagegenInterfacesApi.refreshBalance(id);
      load();
    } catch (e: any) {
      alert("刷新余额失败: " + (e.response?.data?.detail || e.message));
    } finally {
      setRefreshingBalance(null);
    }
  };

  const formatBalance = (balance: number | string | null | undefined) => {
    if (balance === null || balance === undefined || balance === "") return null;
    if (typeof balance === "number") return `¥${balance.toFixed(2)}`;
    return String(balance);
  };

  return (
    <div className="space-y-5 stagger-children">
      <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-3">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Zap className="w-4 h-4 text-primary" />
          默认生成配置
        </h3>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="text-xs font-medium text-muted-foreground block mb-1.5">默认接口</label>
            <select
              className="w-full px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none appearance-none"
              value={activeEngine}
              onChange={(e) => handleSelect(e.target.value)}
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
            <label className="text-xs font-medium text-muted-foreground block mb-1.5">默认文生图模型</label>
            <select
              className="w-full px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none appearance-none disabled:opacity-50"
              value={defaultT2IModel}
              onChange={(e) => handleSelectT2IModel(e.target.value)}
              disabled={!activeEngine}
            >
              <option value="">{activeEngine ? "未选择" : "请先选择接口"}</option>
              {t2iModels.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground block mb-1.5">默认图生图模型</label>
            <select
              className="w-full px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none appearance-none disabled:opacity-50"
              value={defaultI2IModel}
              onChange={(e) => handleSelectI2IModel(e.target.value)}
              disabled={!activeEngine}
            >
              <option value="">{activeEngine ? "未选择" : "请先选择接口"}</option>
              {i2iModels.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold flex items-center gap-2">
            <Image className="w-4 h-4 text-primary" />
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
          {interfaces.length === 0 && (
            <div className="text-center py-8 text-muted-foreground text-sm">
              暂无图像生成接口，点击"添加接口"创建
            </div>
          )}
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
                  {formatBalance(iface.balance) !== null && (
                    <div className="flex items-center gap-1.5 mt-1.5">
                      <Wallet className="w-3 h-3 text-emerald-500" />
                      <span className="text-xs font-medium text-emerald-600">
                        {formatBalance(iface.balance)}
                      </span>
                      <button
                        onClick={() => handleRefreshBalance(iface.id)}
                        disabled={refreshingBalance === iface.id}
                        className="p-0.5 rounded hover:bg-accent/60 text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
                        title="刷新余额"
                      >
                        <RefreshCw className={cn("w-3 h-3", refreshingBalance === iface.id && "animate-spin")} />
                      </button>
                    </div>
                  )}
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
                  {iface.model_docs_url && (
                    <a
                      href={iface.model_docs_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="p-1.5 rounded-lg border border-border/40 hover:bg-violet-500/10 text-muted-foreground hover:text-violet-500 transition-all duration-200"
                      title="查看支持模型"
                    >
                      <BookOpen className="w-3.5 h-3.5" />
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

      {showEditor &&
        createPortal(
          <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 backdrop-blur-sm animate-fade-in overflow-y-auto py-10 px-4">
            <div className="bg-background border border-border/60 rounded-2xl shadow-2xl w-[min(880px,92vw)] animate-scale-in">
              <ImageGenInterfaceEditor
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

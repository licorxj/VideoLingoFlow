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
  Star,
  X,
  Save,
  Check,
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

  // Model management state
  const [showModelPanel, setShowModelPanel] = useState(false);
  const [editingModel, setEditingModel] = useState<{ name: string; newName: string; newDesc: string } | null>(null);
  const [addingModel, setAddingModel] = useState<{ name: string; description: string }>({ name: "", description: "" });
  const [savingModel, setSavingModel] = useState(false);

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

  // Model management handlers
  const activeIface = interfaces.find((i) => i.id === activeEngine);
  const modelDetails = activeIface?.config?.model_details || {};
  const modelOptions = activeIface?.config?.model_options || [];

  const handleSaveModelDetail = async (modelName: string) => {
    if (!activeEngine) return;
    setSavingModel(true);
    try {
      const detail = editingModel;
      await separationInterfacesApi.setModelDetail(activeEngine, modelName, {
        name: detail?.newName || modelName,
        description: detail?.newDesc || "",
      });
      setEditingModel(null);
      await load();
    } catch (e: any) {
      alert("保存失败: " + (e?.response?.data?.detail || e?.message || String(e)));
    } finally {
      setSavingModel(false);
    }
  };

  const handleDeleteModelDetail = async (modelName: string) => {
    if (!activeEngine || !confirm(`确定要删除模型 "${modelName}" 的详情吗？`)) return;
    try {
      await separationInterfacesApi.deleteModelDetail(activeEngine, modelName);
      if (activeModel === modelName) {
        const iface = interfaces.find((i) => i.id === activeEngine);
        const defaultModel = iface?.config?.model || "";
        setActiveModel(defaultModel);
        await settingsApi.update("separation.model", defaultModel);
      }
      await load();
    } catch (e: any) {
      alert("删除失败: " + (e?.response?.data?.detail || e?.message || String(e)));
    }
  };

  const handleSetDefaultModel = async (modelName: string) => {
    if (!activeEngine) return;
    try {
      await separationInterfacesApi.setModelAsDefault(activeEngine, modelName);
      setActiveModel(modelName);
      await settingsApi.update("separation.model", modelName);
      await load();
    } catch (e: any) {
      alert("设置失败: " + (e?.response?.data?.detail || e?.message || String(e)));
    }
  };

  const handleAddNewModel = async () => {
    if (!activeEngine || !addingModel.name.trim()) return;
    setSavingModel(true);
    try {
      await separationInterfacesApi.setModelDetail(activeEngine, addingModel.name, {
        name: addingModel.name,
        description: addingModel.description,
      });
      setAddingModel({ name: "", description: "" });
      await load();
    } catch (e: any) {
      alert("添加失败: " + (e?.response?.data?.detail || e?.message || String(e)));
    } finally {
      setSavingModel(false);
    }
  };

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

      {/* Model Management Panel */}
      {activeEngine && (
        <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold flex items-center gap-2">
              <Music className="w-4 h-4 text-primary" />
              {activeIface?.name} 模型管理
            </h3>
            <button
              onClick={() => setShowModelPanel(!showModelPanel)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border border-border/60 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent/60 transition-all duration-200"
            >
              {showModelPanel ? "收起" : "展开"}
              <svg className="w-3.5 h-3.5 transition-transform duration-200" style={{ transform: showModelPanel ? "rotate(180deg)" : "none" }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </button>
          </div>

          {showModelPanel && (
            <div className="space-y-4">
              {/* Model list */}
              {modelOptions.length > 0 ? (
                <div className="space-y-2">
                  {modelOptions.map((modelName) => {
                    const detail = modelDetails[modelName] || { name: modelName, description: "" };
                    const isDefault = activeModel === modelName;
                    const isEditing = editingModel?.name === modelName;

                    return (
                      <div
                        key={modelName}
                        className={cn(
                          "flex items-start gap-3 p-3 rounded-xl border transition-all duration-200",
                          isDefault ? "border-primary/40 bg-primary/5" : "border-border/40"
                        )}
                      >
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-semibold text-sm">{detail.name || modelName}</span>
                            {isDefault && (
                              <span className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-500 font-medium">
                                <Star className="w-3 h-3 fill-current" />
                                默认
                              </span>
                            )}
                          </div>
                          {isEditing ? (
                            <textarea
                              className="w-full mt-2 px-3 py-2 border border-border/60 rounded-lg bg-background/50 text-xs focus:border-primary/50 outline-none resize-none"
                              rows={2}
                              value={editingModel.newDesc}
                              onChange={(e) => setEditingModel({ ...editingModel, newDesc: e.target.value })}
                            />
                          ) : (
                            <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                              {detail.description || "暂无描述"}
                            </p>
                          )}
                        </div>

                        <div className="flex items-center gap-1.5 flex-shrink-0">
                          {isEditing ? (
                            <>
                              <button
                                onClick={() => handleSaveModelDetail(modelName)}
                                disabled={savingModel}
                                className="p-1.5 rounded-lg border border-border/40 hover:bg-emerald-500/10 text-muted-foreground hover:text-emerald-500 transition-all duration-200"
                                title="保存"
                              >
                                <Check className="w-3.5 h-3.5" />
                              </button>
                              <button
                                onClick={() => setEditingModel(null)}
                                className="p-1.5 rounded-lg border border-border/40 hover:bg-red-500/10 text-muted-foreground hover:text-red-500 transition-all duration-200"
                                title="取消"
                              >
                                <X className="w-3.5 h-3.5" />
                              </button>
                            </>
                          ) : (
                            <>
                              <button
                                onClick={() => handleSetDefaultModel(modelName)}
                                className={cn(
                                  "p-1.5 rounded-lg border border-border/40 transition-all duration-200",
                                  isDefault
                                    ? "bg-yellow-500/10 text-yellow-500"
                                    : "hover:bg-yellow-500/10 text-muted-foreground hover:text-yellow-500"
                                )}
                                title="设为默认"
                              >
                                <Star className="w-3.5 h-3.5" />
                              </button>
                              <button
                                onClick={() => setEditingModel({ name: modelName, newName: modelName, newDesc: detail.description })}
                                className="p-1.5 rounded-lg border border-border/40 hover:bg-accent/60 text-muted-foreground hover:text-foreground transition-all duration-200"
                                title="编辑"
                              >
                                <Pencil className="w-3.5 h-3.5" />
                              </button>
                              {!activeIface?.builtin && (
                                <button
                                  onClick={() => handleDeleteModelDetail(modelName)}
                                  className="p-1.5 rounded-lg border border-border/40 hover:bg-red-500/10 text-muted-foreground hover:text-red-500 transition-all duration-200"
                                  title="删除"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              )}
                            </>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">该接口暂无模型配置</p>
              )}

              {/* Add new model */}
              <div className="pt-2 border-t border-border/40">
                <h4 className="text-xs font-semibold text-muted-foreground mb-2">手动添加模型</h4>
                <div className="space-y-2">
                  <div className="flex gap-2">
                    <input
                      type="text"
                      placeholder="模型名称"
                      className="flex-1 px-3 py-2 border border-border/60 rounded-lg bg-background/50 text-xs outline-none focus:border-primary/50"
                      value={addingModel.name}
                      onChange={(e) => setAddingModel({ ...addingModel, name: e.target.value })}
                    />
                    <button
                      onClick={handleAddNewModel}
                      disabled={!addingModel.name.trim() || savingModel}
                      className="px-3 py-2 text-xs font-medium bg-primary text-primary-foreground rounded-lg transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      添加
                    </button>
                  </div>
                  <textarea
                    placeholder="模型说明（可选）"
                    className="w-full px-3 py-2 border border-border/60 rounded-lg bg-background/50 text-xs outline-none focus:border-primary/50 resize-none"
                    rows={2}
                    value={addingModel.description}
                    onChange={(e) => setAddingModel({ ...addingModel, description: e.target.value })}
                  />
                </div>
              </div>
            </div>
          )}
        </div>
      )}

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
          <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 backdrop-blur-sm animate-fade-in overflow-y-auto py-10 px-4">
            <div className="bg-background border border-border/60 rounded-2xl shadow-2xl w-[min(880px,92vw)] animate-scale-in">
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

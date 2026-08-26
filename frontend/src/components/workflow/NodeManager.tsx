import { useState, useEffect, useRef } from "react";
import {
  listNodeTypes, createNodeType, deleteNodeType,
  exportNodeType, importNodeType,
  getNodeTypesSchema,
  type NodeTypeConfig,
  type NodeTypeBackupEntry,
  type NodeTypesSchema,
  type NodePackageValidationResult,
  listNodeTypeBackups,
  restoreNodeTypeBackup,
  validateNodeTypePackage,
} from "@/api/nodeTypes";
import { CATEGORIES } from "@/lib/workflowTypes";
import { packNode, publishPackage, type PublishResult } from "@/api/community";
import SharePackDialog, { type SharePackFields } from "@/components/community/SharePackDialog";
import { captureNodeCard } from "@/lib/snapshot";
import { useAlert } from "@/components/ui/AlertProvider";
import {
  X, Plus, Trash2, Share2, Upload, Download, Settings2,
  Search, Package, AlertCircle, CheckCircle2, FileArchive,
  Code, Terminal, Brain, History, RotateCcw, Film, Music, Subtitles, Mic, Mic2, Scissors,
  Languages, FileText, Volume2, Merge, Clapperboard, Image, Stamp, Wrench, Eye, Sparkles,
  FolderOpen, Download as DownloadIcon, Globe, Bot, Boxes, XCircle,
} from "lucide-react";

interface NodeManagerProps {
  open: boolean;
  onClose: () => void;
}

type VersionComparisonStatus = "new" | "upgrade" | "downgrade" | "same" | "different";
type ImportResultState = {
  files: string[];
  install: string;
  warnings: string[];
  backupPath?: string;
  versionComparison?: NodePackageValidationResult["versionComparison"];
};

const NODE_ICON_OPTIONS = [
  { name: "Wrench", icon: Wrench }, { name: "Film", icon: Film }, { name: "Music", icon: Music },
  { name: "Subtitles", icon: Subtitles }, { name: "Mic", icon: Mic }, { name: "Mic2", icon: Mic2 },
  { name: "Scissors", icon: Scissors }, { name: "Languages", icon: Languages }, { name: "FileText", icon: FileText },
  { name: "Volume2", icon: Volume2 }, { name: "Merge", icon: Merge }, { name: "Clapperboard", icon: Clapperboard },
  { name: "Image", icon: Image }, { name: "Stamp", icon: Stamp }, { name: "Upload", icon: Upload },
  { name: "Download", icon: DownloadIcon }, { name: "Eye", icon: Eye }, { name: "Sparkles", icon: Sparkles },
  { name: "FolderOpen", icon: FolderOpen }, { name: "Globe", icon: Globe }, { name: "Bot", icon: Bot }, { name: "Boxes", icon: Boxes },
];

export default function NodeManager({ open, onClose }: NodeManagerProps) {
  const { confirm: confirmAction } = useAlert();
  const defaultSchema: NodeTypesSchema = {
    categories: Object.entries(CATEGORIES).map(([value, meta]) => ({ value, label: meta.label, color: meta.color, icon: meta.icon })),
    portTypes: [
      { value: "video", label: "视频" },
      { value: "audio", label: "音频" },
      { value: "audio_manifest", label: "音频清单" },
      { value: "json", label: "JSON" },
      { value: "pandas", label: "表格数据" },
      { value: "subtitle", label: "字幕" },
      { value: "text", label: "文本" },
      { value: "image", label: "图片" },
      { value: "url", label: "URL" },
      { value: "preview", label: "预览" },
      { value: "any", label: "通用" },
    ],
    configFieldTypes: [
      { value: "text", label: "单行文本", supportedProperties: ["placeholder", "description", "dependsOn", "dependsValue", "dependsOnAny", "dependsAnyValues"] },
      { value: "textarea", label: "多行文本", supportedProperties: ["placeholder", "description", "dependsOn", "dependsValue", "dependsOnAny", "dependsAnyValues"] },
      { value: "select", label: "下拉选择", supportedProperties: ["placeholder", "options", "description", "dependsOn", "dependsValue", "dependsOnAny", "dependsAnyValues"], requiresOptions: true },
      { value: "multiselect", label: "多选下拉", supportedProperties: ["placeholder", "options", "description", "dependsOn", "dependsValue", "dependsOnAny", "dependsAnyValues"] },
      { value: "checkbox", label: "复选框", supportedProperties: ["description", "dependsOn", "dependsValue", "dependsOnAny", "dependsAnyValues"] },
      { value: "toggle", label: "开关", supportedProperties: ["description", "dependsOn", "dependsValue", "dependsOnAny", "dependsAnyValues"] },
      { value: "chips", label: "标签选择", supportedProperties: ["options", "chipColor", "description", "dependsOn", "dependsValue", "dependsOnAny", "dependsAnyValues"], requiresOptions: true },
      { value: "file", label: "文件选择", supportedProperties: ["placeholder", "fileFilter", "description", "dependsOn", "dependsValue", "dependsOnAny", "dependsAnyValues"] },
      { value: "language-select", label: "语言选择", supportedProperties: ["description", "dependsOn", "dependsValue", "dependsOnAny", "dependsAnyValues"] },
      { value: "api-select", label: "接口选项", supportedProperties: ["placeholder", "apiEndpoint", "apiUrl", "optionLabel", "optionValue", "description", "dependsOn", "dependsValue", "dependsOnAny", "dependsAnyValues"] },
      { value: "slider", label: "滑块", supportedProperties: ["placeholder", "min", "max", "step", "description", "dependsOn", "dependsValue", "dependsOnAny", "dependsAnyValues"] },
      { value: "number", label: "数字", supportedProperties: ["placeholder", "min", "max", "step", "description", "dependsOn", "dependsValue", "dependsOnAny", "dependsAnyValues"] },
    ],
    execTypes: [
      { value: "", label: "无 (仅 UI)" },
      { value: "python", label: "Python 脚本" },
      { value: "shell", label: "Shell 命令" },
      { value: "llm", label: "LLM 处理" },
    ],
  };
  const [nodeRegistry, setNodeRegistry] = useState<NodeTypeConfig[]>([]);
  const [nodeSchema, setNodeSchema] = useState<NodeTypesSchema>(defaultSchema);
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState<"list" | "create" | "share" | "import">("list");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState<{ msg: string; type: "ok" | "err" } | null>(null);
  const [importResult, setImportResult] = useState<ImportResultState | null>(null);
  const [packageValidation, setPackageValidation] = useState<NodePackageValidationResult | null>(null);
  const [validatingPackage, setValidatingPackage] = useState(false);
  const [allowOverwrite, setAllowOverwrite] = useState(false);
  const [createBackup, setCreateBackup] = useState(false);
  const [renameMode, setRenameMode] = useState(false);
  const [renameTo, setRenameTo] = useState("");
  const [nodeBackups, setNodeBackups] = useState<NodeTypeBackupEntry[]>([]);
  const [loadingBackups, setLoadingBackups] = useState(false);
  const [restoringBackupId, setRestoringBackupId] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [packOpen, setPackOpen] = useState(false);
  const [iconPickerOpen, setIconPickerOpen] = useState(false);

  const emptyForm: Partial<NodeTypeConfig> = {
    id: "", name: "", category: "utility", description: "",
    icon: "Wrench", color: "#6b7280",
    inputs: [], outputs: [], defaultConfig: {}, configFields: [],
    execType: "", execCode: "", execFile: "", execTimeout: 300,
  };
  const [form, setForm] = useState<Partial<NodeTypeConfig>>(emptyForm);

  const [shareName, setShareName] = useState("");
  const [shareDesc, setShareDesc] = useState("");
  const [shareAuthor, setShareAuthor] = useState("");
  const [shareSourceUrl, setShareSourceUrl] = useState("");
  const [shareTags, setShareTags] = useState("");

  const getVersionComparisonTone = (status?: VersionComparisonStatus) => {
    if (status === "upgrade") return "text-emerald-600 bg-emerald-500/5 border-emerald-500/20";
    if (status === "downgrade") return "text-amber-600 bg-amber-500/5 border-amber-500/20";
    if (status === "same" || status === "different") return "text-orange-600 bg-orange-500/5 border-orange-500/20";
    return "text-blue-600 bg-blue-500/5 border-blue-500/20";
  };

  const parseKeyValueOptions = (value: string) =>
    value
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const [rawValue, ...labelParts] = line.split(":");
        const optionValue = rawValue?.trim() || "";
        const optionLabel = (labelParts.join(":").trim() || optionValue);
        return optionValue ? { value: optionValue, label: optionLabel } : null;
      })
      .filter(Boolean) as { value: string; label: string }[];

  const stringifyKeyValueOptions = (options: any[] | undefined) =>
    (options || []).map((item) => `${item.value}:${item.label}`).join("\n");

  const parseCommaList = (value: string) =>
    value.split(",").map((item) => item.trim()).filter(Boolean);

  const stringifyCommaList = (items: any[] | undefined) =>
    (items || []).join(", ");

  const allNodes = nodeRegistry;
  const filtered = allNodes.filter(n =>
    n.name.toLowerCase().includes(search.toLowerCase()) || n.id.toLowerCase().includes(search.toLowerCase())
  );
  const selectedNode = allNodes.find(n => n.id === selected);

  useEffect(() => {
    if (open) {
      loadNodeRegistry();
      loadNodeSchema();
      setTab("list");
      setSelected(null);
      setImportResult(null);
      setPackageValidation(null);
      setAllowOverwrite(false);
      setCreateBackup(false);
      setRenameMode(false);
      setRenameTo("");
      setNodeBackups([]);
      setRestoringBackupId(null);
    }
  }, [open]);

  useEffect(() => {
    if (!open || !selectedNode || selectedNode.isBuiltIn || tab !== "list") {
      setNodeBackups([]);
      setLoadingBackups(false);
      return;
    }
    void loadNodeBackups(selectedNode.id);
  }, [open, selectedNode?.id, selectedNode?.isBuiltIn, tab]);

  const loadNodeRegistry = async () => {
    setLoading(true);
    try { setNodeRegistry(await listNodeTypes()); } catch { showToast("加载节点注册表失败", "err"); }
    setLoading(false);
  };

  const loadNodeSchema = async () => {
    try {
      setNodeSchema(await getNodeTypesSchema());
    } catch {
      setNodeSchema(defaultSchema);
      showToast("加载节点 schema 失败，已使用本地兜底", "err");
    }
  };

  const showToast = (msg: string, type: "ok" | "err") => {
    setToast({ msg, type }); setTimeout(() => setToast(null), 3000);
  };

  const formatDateTime = (value?: string) => {
    if (!value) return "未知时间";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
  };

  const handleCreate = async () => {
    if (!form.id || !form.name) { showToast("ID 和名称不能为空", "err"); return; }
    if (!/^[A-Za-z0-9_-]{1,80}$/.test(form.id)) { showToast("节点 ID 仅支持字母、数字、_ 和 -", "err"); return; }
    const duplicatePortId = ["inputs", "outputs"].some((kind) => {
      const ids = (form[kind as "inputs"] || []).map((port) => port.id?.trim());
      return ids.some((id) => !id) || new Set(ids).size !== ids.length;
    });
    if (duplicatePortId) { showToast("端口 ID 不能为空且同一方向不能重复", "err"); return; }
    const execType = form.execType || "";
    if (execType === "python" && !String(form.execCode || "").trim() && !String(form.execFile || "").trim()) {
      showToast("Python 节点需要内联代码或入口文件", "err"); return;
    }
    if (["shell", "llm"].includes(execType) && !String(form.execCode || "").trim()) {
      showToast(`${execType === "shell" ? "Shell 命令" : "LLM 提示词模板"}不能为空`, "err"); return;
    }
    const payload = { ...form };
    // 执行层优先 execFile；内联代码非空时清空 execFile，确保内联代码生效
    if (payload.execType === "python" && String(payload.execCode || "").trim()) {
      payload.execFile = "";
    }
    try {
      await createNodeType(payload as NodeTypeConfig);
      showToast("节点已创建", "ok");
      await loadNodeRegistry(); setTab("list");
    } catch (e: any) { showToast(e?.response?.data?.detail || "创建失败", "err"); }
  };

  const handleDelete = async (nodeId: string) => {
    const node = nodeRegistry.find((item) => item.id === nodeId);
    const confirmed = await confirmAction(
      `确定彻底删除节点“${node?.name || nodeId}”吗？此操作不可撤销；引用该节点的工作流将无法继续执行。`,
      { type: "warning", title: "删除节点", confirmLabel: "删除", cancelLabel: "取消" }
    );
    if (!confirmed) return;
    try {
      await deleteNodeType(nodeId);
      showToast("已删除", "ok");
      if (selected === nodeId) setSelected(null);
      await loadNodeRegistry();
    } catch (e: any) { showToast(e?.response?.data?.detail || "删除失败", "err"); }
  };

  const loadNodeBackups = async (nodeId: string) => {
    setLoadingBackups(true);
    try {
      setNodeBackups(await listNodeTypeBackups(nodeId));
    } catch (e: any) {
      setNodeBackups([]);
      showToast(e?.response?.data?.detail || "加载节点备份失败", "err");
    } finally {
      setLoadingBackups(false);
    }
  };

  const handleRestoreBackup = async (nodeId: string, backup: NodeTypeBackupEntry) => {
    const confirmed = confirm(
      `确认将节点回滚到备份 ${backup.id} 吗？\n\n恢复前会先为当前节点再创建一份保护性备份。`
    );
    if (!confirmed) return;

    setRestoringBackupId(backup.id);
    try {
      const result = await restoreNodeTypeBackup(nodeId, backup.id, { createBackup: true });
      showToast(`已恢复节点: ${result.node.name}`, "ok");
      await loadNodeRegistry();
      await loadNodeBackups(nodeId);
      if (selected === nodeId) {
        setSelected(nodeId);
      }
      if (result.currentBackupPath) {
        setImportResult({
          files: [],
          install: "",
          warnings: [],
          backupPath: result.currentBackupPath,
        });
      }
    } catch (e: any) {
      showToast(e?.response?.data?.detail || "恢复备份失败", "err");
    } finally {
      setRestoringBackupId(null);
    }
  };

  const handleShare = async () => {
    if (!selected || !shareName.trim()) { showToast("请输入名称", "err"); return; }
    try {
      const result = await exportNodeType(
        selected,
        shareName,
        shareDesc,
        shareAuthor,
        shareSourceUrl,
        parseCommaList(shareTags)
      );
      showToast("已导出: " + result.fileName, "ok");
    } catch (e: any) { showToast(e?.response?.data?.detail || "导出失败", "err"); }
  };

  const handleExport = async () => {
    if (!selected || !selectedNode) return;
    try {
      const result = await exportNodeType(
        selected,
        selectedNode.name || selected,
        selectedNode.description || "",
        "",
        "",
        []
      );
      showToast("已导出: " + result.fileName + " → share/", "ok");
    } catch (e: any) { showToast(e?.response?.data?.detail || "导出失败", "err"); }
  };

  const handlePackSubmit = async (fields: SharePackFields, preview: File | null): Promise<PublishResult> => {
    if (!selectedNode) throw new Error("未选择节点");
    const form = new FormData();
    form.append("nodeId", selectedNode.id);
    form.append("shareName", fields.shareName);
    form.append("description", fields.description);
    form.append("author", fields.author);
    form.append("category", fields.category);
    form.append("tags", JSON.stringify(fields.tags));
    if (preview) form.append("preview", preview);
    const packed = await packNode(form);
    return publishPackage(packed.folder);
  };

  const handleImport = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) { showToast("请选择 ZIP 文件", "err"); return; }
    if (packageValidation && !packageValidation.valid) { showToast("节点包预检未通过，无法导入", "err"); return; }
    if (renameMode) {
      if (!renameTo.trim()) { showToast("请输入新的节点 ID", "err"); return; }
      if (renameTo.trim() === packageValidation?.node?.id) { showToast("新 ID 不能与包内节点 ID 相同", "err"); return; }
    } else if (packageValidation?.localNode && !allowOverwrite) {
      showToast("检测到同名节点，请确认允许覆盖或选择重命名导入", "err");
      return;
    }
    if (!renameMode && packageValidation?.versionComparison?.requiresConfirmation) {
      const confirmed = confirm(
        `${packageValidation.versionComparison.message}\n\n这是高风险覆盖操作，确认继续导入吗？`
      );
      if (!confirmed) return;
    }
    try {
      const result = await importNodeType(file, renameMode
        ? { renameTo: renameTo.trim() }
        : {
            allowOverwrite: !!packageValidation?.localNode && allowOverwrite,
            createBackup: !!packageValidation?.localNode && createBackup,
          });
      setImportResult({
        files: result.extractedFiles || [],
        install: result.installResult || "",
        warnings: result.packageWarnings || [],
        backupPath: result.backupPath,
        versionComparison: result.versionComparison,
      });
      showToast("已导入: " + result.node.name, "ok");
      await loadNodeRegistry(); setTab("list");
    } catch (e: any) {
      if (e?.response?.status === 409) {
        setAllowOverwrite(true);
      }
      showToast(e?.response?.data?.detail || "导入失败", "err");
    }
  };

  const handleSelectImportFile = async () => {
    fileRef.current?.click();
  };

  const handleImportFileChanged = async (file?: File) => {
    setImportResult(null);
    setPackageValidation(null);
    setAllowOverwrite(false);
    setCreateBackup(false);
    setRenameMode(false);
    setRenameTo("");
    if (!file) return;
    setValidatingPackage(true);
    try {
      const result = await validateNodeTypePackage(file);
      setPackageValidation(result);
      setAllowOverwrite(false);
      setCreateBackup(!!result.versionComparison?.recommendedBackup);
      if (result.valid) {
        if (result.localNode) {
          // 同名节点：预填重命名建议 id，供用户切换重命名导入
          setRenameTo(`${result.localNode.id}_copy`);
        }
        showToast("节点包预检通过", "ok");
      }
      else showToast(result.errors[0] || "节点包预检失败", "err");
    } catch (e: any) {
      setRenameMode(false);
      setRenameTo("");
      setPackageValidation({
        ok: false,
        valid: false,
        errors: [e?.response?.data?.detail || "节点包预检失败"],
        warnings: [],
        packageFiles: [],
      });
      showToast(e?.response?.data?.detail || "节点包预检失败", "err");
    } finally {
      setValidatingPackage(false);
    }
  };

  const addInputPort = () => setForm(f => ({ ...f, inputs: [...(f.inputs || []), { id: "input_" + ((f.inputs || []).length + 1), label: "输入端口", type: "any", required: false }] }));
  const addOutputPort = () => setForm(f => ({ ...f, outputs: [...(f.outputs || []), { id: "output_" + ((f.outputs || []).length + 1), label: "输出端口", type: "any" }] }));
  const removePort = (which: "inputs" | "outputs", idx: number) => setForm(f => ({ ...f, [which]: (f[which] || []).filter((_: any, i: number) => i !== idx) }));
  const addConfigField = () => setForm(f => ({ ...f, configFields: [...(f.configFields || []), { key: "field_" + Date.now(), label: "新字段", type: "text" }] }));
  const removeConfigField = (idx: number) => setForm(f => ({ ...f, configFields: (f.configFields || []).filter((_: any, i: number) => i !== idx) }));
  const updateConfigField = (idx: number, patch: Record<string, any>) => setForm((f) => {
    const next = [...(f.configFields || [])];
    next[idx] = { ...next[idx], ...patch };
    return { ...f, configFields: next };
  });

  const getFieldTypeSchema = (type: string) =>
    nodeSchema.configFieldTypes.find((item) => item.value === type);
  const normalizeConfigFieldType = (field: Record<string, any>, nextType: string) => {
    const nextSchema = nodeSchema.configFieldTypes.find((item) => item.value === nextType);
    const allowed = new Set(["key", "label", "type", ...(nextSchema?.supportedProperties || [])]);
    return Object.fromEntries(
      Object.entries({ ...field, type: nextType }).filter(([key, value]) => {
        if (!allowed.has(key)) return false;
        return value !== undefined;
      })
    );
  };

  if (!open) return null;

  const inputCls = "w-full px-3 py-2 text-sm rounded-lg border border-border/50 bg-background focus:border-primary/50 outline-none transition-all";
  const labelCls = "text-xs font-medium text-muted-foreground block mb-1";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="bg-background border border-border rounded-2xl shadow-2xl w-[950px] max-h-[85vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border/50">
          <div className="flex items-center gap-2">
            <Settings2 className="w-5 h-5 text-primary" />
            <h2 className="text-lg font-bold">节点管理器</h2>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => { setTab("create"); setForm({ ...emptyForm }); }}
              className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-lg bg-primary/10 text-primary hover:bg-primary/20 transition-colors">
              <Plus className="w-3 h-3" /> 自定义节点
            </button>
            <button onClick={() => setTab("import")}
              className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-lg bg-blue-500/10 text-blue-500 hover:bg-blue-500/20 transition-colors">
              <Upload className="w-3 h-3" /> 导入节点
            </button>
            <button onClick={onClose} className="p-1 rounded-lg hover:bg-muted transition-colors">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Toast */}
        {toast && (
          <div className={`mx-6 mt-3 px-4 py-2 rounded-lg text-sm flex items-center gap-2 ${toast.type === "ok" ? "bg-emerald-500/10 text-emerald-600" : "bg-red-500/10 text-red-600"}`}>
            {toast.type === "ok" ? <CheckCircle2 className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
            {toast.msg}
          </div>
        )}

        <div className="flex flex-1 min-h-0">
          {/* Left: Node List */}
          <div className="w-72 border-r border-border/50 flex flex-col">
            <div className="p-3 border-b border-border/30">
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
                <input value={search} onChange={e => setSearch(e.target.value)} placeholder="搜索节点..."
                  className="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg border border-border/50 bg-background focus:border-primary/50 outline-none" />
              </div>
            </div>
            <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
              {filtered.map(n => {
                const isCustom = !n.isBuiltIn;
                return (
                  <button key={n.id} onClick={() => { setSelected(n.id); setTab("list"); }}
                    className={`w-full text-left px-3 py-2 rounded-lg text-xs transition-all ${selected === n.id ? "bg-primary/10 border border-primary/30" : "hover:bg-muted/50 border border-transparent"}`}>
                    <div className="flex items-center gap-2">
                      <div className="w-2 h-2 rounded-full" style={{ backgroundColor: n.color }} />
                      <span className="font-medium truncate">{n.name}</span>
                      {isCustom && <span className="ml-auto text-[9px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-500">自定义</span>}
                    </div>
                    <div className="text-[10px] text-muted-foreground mt-0.5 truncate">{n.description || n.id}</div>
                  </button>
                );
              })}
              {filtered.length === 0 && <p className="text-xs text-muted-foreground/50 text-center py-4">无匹配节点</p>}
            </div>
          </div>

          {/* Right: Detail / Forms */}
          <div className="flex-1 overflow-y-auto p-6">
            {/* List tab: show selected node detail */}
            {tab === "list" && selectedNode && (
              <div className="space-y-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ backgroundColor: selectedNode.color + "20" }}>
                    <div className="w-5 h-5 rounded" style={{ backgroundColor: selectedNode.color }} />
                  </div>
                  <div>
                    <h3 className="text-base font-bold">{selectedNode.name}</h3>
                    <p className="text-xs text-muted-foreground">{selectedNode.id} / {selectedNode.category}</p>
                  </div>
                  <button onClick={() => handleDelete(selectedNode.id)} title="彻底删除节点"
                    className="ml-auto flex items-center gap-1 px-3 py-1.5 text-xs rounded-lg bg-red-500/10 text-red-500 hover:bg-red-500/20 transition-colors">
                    <Trash2 className="w-3 h-3" /> 删除节点
                  </button>
                  <button onClick={handleExport} title="导出到根目录 share/ 文件夹"
                    className="flex items-center gap-1 px-3 py-1.5 text-xs rounded-lg bg-emerald-500/10 text-emerald-600 hover:bg-emerald-500/20 transition-colors">
                    <Download className="w-3 h-3" /> 导出 ZIP
                  </button>
                  <button onClick={() => setPackOpen(true)} title="打包并发布到共享社区"
                    className="ml-2 flex items-center gap-1 px-3 py-1.5 text-xs rounded-lg bg-violet-500/10 text-violet-600 hover:bg-violet-500/20 transition-colors">
                    <Share2 className="w-3 h-3" /> 分享打包
                  </button>
                </div>
                <p className="text-sm text-muted-foreground">{selectedNode.description}</p>

                {/* Ports */}
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <h4 className="text-xs font-bold text-muted-foreground mb-2">输入端口</h4>
                    {selectedNode.inputs.map((p, i) => (
                      <div key={i} className="flex items-center gap-2 text-xs py-1">
                        <span className="w-2 h-2 rounded-full bg-blue-500" />
                        <span>{p.label}</span>
                        <span className="text-muted-foreground">({p.type})</span>
                      </div>
                    ))}
                  </div>
                  <div>
                    <h4 className="text-xs font-bold text-muted-foreground mb-2">输出端口</h4>
                    {selectedNode.outputs.map((p, i) => (
                      <div key={i} className="flex items-center gap-2 text-xs py-1">
                        <span className="w-2 h-2 rounded-full bg-emerald-500" />
                        <span>{p.label}</span>
                        <span className="text-muted-foreground">({p.type})</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Execution Info */}
                {selectedNode.execType && (
                  <div className="bg-muted/30 rounded-xl p-4">
                    <h4 className="text-xs font-bold text-muted-foreground mb-2 flex items-center gap-1.5">
                      <Code className="w-3 h-3" /> 执行配置
                    </h4>
                    <div className="text-xs space-y-1">
                      <div>类型: <span className="font-mono bg-primary/10 px-1.5 py-0.5 rounded">{selectedNode.execType}</span></div>
                      {selectedNode.execFile && <div>入口: <span className="font-mono">{selectedNode.execFile}</span></div>}
                      {selectedNode.execTimeout && <div>超时: {selectedNode.execTimeout}s</div>}
                    </div>
                  </div>
                )}

                {/* Actions */}
                {!selectedNode.isBuiltIn && (
                  <div className="flex gap-2">
                    <button onClick={() => { setShareName(selectedNode.name); setShareDesc(selectedNode.description); setTab("share"); }}
                      className="flex items-center gap-1 px-3 py-1.5 text-xs rounded-lg bg-blue-500/10 text-blue-500 hover:bg-blue-500/20 transition-colors">
                      <Share2 className="w-3 h-3" /> 分享
                    </button>
                    <button onClick={() => loadNodeBackups(selectedNode.id)}
                      className="flex items-center gap-1 px-3 py-1.5 text-xs rounded-lg bg-amber-500/10 text-amber-600 hover:bg-amber-500/20 transition-colors">
                      <History className="w-3 h-3" /> 刷新备份
                    </button>
                  </div>
                )}

                {!selectedNode.isBuiltIn && (
                  <div className="border border-border/50 rounded-xl p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <h4 className="text-xs font-bold text-muted-foreground flex items-center gap-1.5">
                        <History className="w-3 h-3" /> 备份历史
                      </h4>
                      {loadingBackups && <span className="text-[11px] text-muted-foreground">加载中...</span>}
                    </div>
                    {nodeBackups.length === 0 ? (
                      <p className="text-xs text-muted-foreground">当前节点还没有可恢复的本地备份。</p>
                    ) : (
                      <div className="space-y-2">
                        {nodeBackups.map((backup) => (
                          <div key={backup.id} className="rounded-lg border border-border/40 bg-muted/20 p-3">
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0 space-y-1">
                                <p className="text-xs font-medium break-all">{backup.id}</p>
                                <p className="text-[11px] text-muted-foreground">
                                  时间: {formatDateTime(backup.createdAt)}
                                  {backup.node.version ? ` / 版本: ${backup.node.version}` : ""}
                                  {backup.hasCode ? " / 含代码目录" : " / 仅配置"}
                                </p>
                                <p className="text-[11px] text-muted-foreground break-all">{backup.path}</p>
                              </div>
                              <button
                                onClick={() => handleRestoreBackup(selectedNode.id, backup)}
                                disabled={restoringBackupId === backup.id}
                                className="shrink-0 flex items-center gap-1 px-3 py-1.5 text-xs rounded-lg bg-amber-500/10 text-amber-600 hover:bg-amber-500/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                              >
                                <RotateCcw className="w-3 h-3" />
                                {restoringBackupId === backup.id ? "恢复中..." : "回滚到此备份"}
                              </button>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {tab === "list" && !selectedNode && (
              <div className="flex items-center justify-center h-full text-muted-foreground/50">
                <div className="text-center space-y-2">
                  <Package className="w-10 h-10 mx-auto" />
                  <p className="text-sm">选择节点查看详情</p>
                  <p className="text-xs">共 {allNodes.length} 个节点 ({allNodes.filter((n) => !n.isBuiltIn).length} 个自定义)</p>
                </div>
              </div>
            )}

            {/* Create Form */}
            {tab === "create" && (
              <div className="space-y-5">
                <h3 className="text-base font-bold">创建自定义节点</h3>

                {/* Basic Info */}
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className={labelCls}>节点 ID *</label>
                    <input value={form.id || ""} onChange={e => setForm(f => ({ ...f, id: e.target.value }))}
                      className={inputCls} placeholder="my_custom_node" />
                  </div>
                  <div>
                    <label className={labelCls}>显示名称 *</label>
                    <input value={form.name || ""} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                      className={inputCls} placeholder="自定义节点" />
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-4">
                  <div>
                    <label className={labelCls}>分类</label>
                    <select value={form.category || "process"} onChange={e => setForm(f => ({ ...f, category: e.target.value }))}
                      className={inputCls}>
                      {nodeSchema.categories.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className={labelCls}>图标</label>
                    <button type="button" onClick={() => setIconPickerOpen(true)} className={inputCls + " flex items-center gap-2 text-left hover:border-primary/50"}>
                      {(() => {
                        const option = NODE_ICON_OPTIONS.find((item) => item.name === form.icon) || NODE_ICON_OPTIONS[0];
                        const Icon = option.icon;
                        return <><Icon className="w-4 h-4" style={{ color: form.color || "#6b7280" }} /><span>{option.name}</span></>;
                      })()}
                    </button>
                  </div>
                  <div>
                    <label className={labelCls}>颜色</label>
                    <div className="flex gap-2">
                      <input type="color" value={form.color || "#6b7280"}
                        onChange={e => setForm(f => ({ ...f, color: e.target.value }))}
                        className="w-10 h-10 rounded-lg border border-border/50 cursor-pointer" />
                      <input value={form.color || ""} onChange={e => setForm(f => ({ ...f, color: e.target.value }))}
                        className={inputCls} />
                    </div>
                  </div>
                </div>
                <div>
                  <label className={labelCls}>描述</label>
                  <input value={form.description || ""} onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                    className={inputCls} placeholder="节点功能描述" />
                </div>

                {/* Ports */}
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <h4 className="text-xs font-bold text-muted-foreground">输入端口</h4>
                      <button onClick={addInputPort} className="text-[10px] text-primary hover:underline">+ 添加</button>
                    </div>
                    {(form.inputs || []).map((p, i) => (
                      <div key={p.id || i} className="flex items-center gap-1.5 mb-1.5">
                        <input value={p.id} onChange={e => { const inp = [...(form.inputs || [])]; inp[i] = { ...inp[i], id: e.target.value }; setForm(f => ({ ...f, inputs: inp })); }}
                          className="w-24 px-2 py-1 text-xs font-mono rounded border border-border/50 bg-background" placeholder="input_id" />
                        <input value={p.label} onChange={e => { const inp = [...(form.inputs || [])]; inp[i] = { ...inp[i], label: e.target.value }; setForm(f => ({ ...f, inputs: inp })); }}
                          className="flex-1 px-2 py-1 text-xs rounded border border-border/50 bg-background" placeholder="标签" />
                        <select value={p.type} onChange={e => { const inp = [...(form.inputs || [])]; inp[i] = { ...inp[i], type: e.target.value }; setForm(f => ({ ...f, inputs: inp })); }}
                          className="px-2 py-1 text-xs rounded border border-border/50 bg-background">
                          {nodeSchema.portTypes.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                        </select>
                        <label title="必需输入" className="flex items-center gap-1 text-[10px] text-muted-foreground whitespace-nowrap">
                          <input type="checkbox" checked={!!p.required} onChange={e => { const inp = [...(form.inputs || [])]; inp[i] = { ...inp[i], required: e.target.checked }; setForm(f => ({ ...f, inputs: inp })); }} /> 必需
                        </label>
                        <button onClick={() => removePort("inputs", i)} className="text-red-400 hover:text-red-600"><Trash2 className="w-3 h-3" /></button>
                      </div>
                    ))}
                  </div>
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <h4 className="text-xs font-bold text-muted-foreground">输出端口</h4>
                      <button onClick={addOutputPort} className="text-[10px] text-primary hover:underline">+ 添加</button>
                    </div>
                    {(form.outputs || []).map((p, i) => (
                      <div key={p.id || i} className="flex items-center gap-1.5 mb-1.5">
                        <input value={p.id} onChange={e => { const out = [...(form.outputs || [])]; out[i] = { ...out[i], id: e.target.value }; setForm(f => ({ ...f, outputs: out })); }}
                          className="w-24 px-2 py-1 text-xs font-mono rounded border border-border/50 bg-background" placeholder="output_id" />
                        <input value={p.label} onChange={e => { const out = [...(form.outputs || [])]; out[i] = { ...out[i], label: e.target.value }; setForm(f => ({ ...f, outputs: out })); }}
                          className="flex-1 px-2 py-1 text-xs rounded border border-border/50 bg-background" placeholder="标签" />
                        <select value={p.type} onChange={e => { const out = [...(form.outputs || [])]; out[i] = { ...out[i], type: e.target.value }; setForm(f => ({ ...f, outputs: out })); }}
                          className="px-2 py-1 text-xs rounded border border-border/50 bg-background">
                          {nodeSchema.portTypes.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                        </select>
                        <button onClick={() => removePort("outputs", i)} className="text-red-400 hover:text-red-600"><Trash2 className="w-3 h-3" /></button>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Execution Config */}
                <div className="border border-border/50 rounded-xl p-4 space-y-3">
                  <h4 className="text-xs font-bold text-muted-foreground flex items-center gap-1.5">
                    <Code className="w-3 h-3" /> 执行配置
                  </h4>
                  <div className="grid grid-cols-3 gap-4">
                    <div>
                      <label className={labelCls}>执行类型</label>
                      <select value={form.execType || ""} onChange={e => setForm(f => ({ ...f, execType: e.target.value }))}
                        className={inputCls}>
                        {nodeSchema.execTypes.map((item) => <option key={item.value || "__empty"} value={item.value}>{item.label}</option>)}
                      </select>
                    </div>
                    {form.execType === "python" && (
                    <div>
                      <label className={labelCls}>入口文件</label>
                      <input value={form.execFile || ""} onChange={e => setForm(f => ({ ...f, execFile: e.target.value }))}
                        className={inputCls} placeholder="run.py" />
                    </div>)}
                    <div>
                      <label className={labelCls}>超时 (秒)</label>
                      <input type="number" value={form.execTimeout || 300} onChange={e => setForm(f => ({ ...f, execTimeout: parseInt(e.target.value) || 300 }))}
                        className={inputCls} />
                    </div>
                  </div>
                  {form.execType && form.execType !== "python" && (
                    <div>
                      <label className={labelCls}>{form.execType === "shell" ? "Shell 命令" : "LLM 提示词模板"}</label>
                      <textarea value={form.execCode || ""} onChange={e => setForm(f => ({ ...f, execCode: e.target.value }))}
                        className={inputCls + " font-mono text-xs"} rows={4}
                        placeholder={form.execType === "shell" ? "ffmpeg -i {input_video} {output_path}" : "翻译以下文本: {input_text}"} />
                    </div>
                  )}
                  {form.execType === "python" && (
                    <div className="space-y-3">
                      <div>
                        <label className={labelCls}>内联 Python 代码（留空则从入口文件执行）</label>
                        <textarea value={form.execCode || ""} onChange={e => setForm(f => ({ ...f, execCode: e.target.value }))}
                          className={inputCls + " font-mono text-xs"} rows={4}
                          placeholder={"# 可用变量: task_dir, cache_dir, node_config, step_inputs, produced\nproduced['output'] = os.path.join(cache_dir, 'result.txt')"} />
                      </div>
                      <div className="bg-muted/30 rounded-lg p-3 text-xs text-muted-foreground space-y-1">
                        <p>填写内联代码时优先执行内联代码（入口文件字段会自动置空）；入口文件由 ZIP 导入时自动部署到 <code className="text-primary">backend/nodes/&lt;id&gt;/</code>。</p>
                        <p>可用变量: <code>task_dir</code>, <code>cache_dir</code>, <code>node_config</code>, <code>step_inputs</code>, <code>produced</code></p>
                        <p>外部脚本环境变量: <code>TASK_DIR</code>, <code>CACHE_DIR</code>, <code>NODE_ID</code>, <code>OUTPUTS_JSON_PATH</code></p>
                      </div>
                    </div>
                  )}
                </div>

                {/* Config Fields */}
                <div className="border border-border/50 rounded-xl p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <h4 className="text-xs font-bold text-muted-foreground flex items-center gap-1.5">
                      <Brain className="w-3 h-3" /> 配置字段
                    </h4>
                    <button onClick={addConfigField} className="text-[10px] text-primary hover:underline">+ 添加字段</button>
                  </div>
                  {(form.configFields || []).length === 0 && (
                    <p className="text-xs text-muted-foreground">未定义配置字段，节点设置面板将为空。</p>
                  )}
                  {(form.configFields || []).map((field: any, i: number) => {
                    const fieldSchema = getFieldTypeSchema(field.type || "text");
                    const supported = new Set(fieldSchema?.supportedProperties || []);
                    return (
                      <div key={i} className="rounded-lg border border-border/50 p-3 space-y-3 bg-muted/20">
                        <div className="grid grid-cols-3 gap-3">
                          <div>
                            <label className={labelCls}>字段 Key *</label>
                            <input value={field.key || ""} onChange={(e) => updateConfigField(i, { key: e.target.value })}
                              className={inputCls} placeholder="quality" />
                          </div>
                          <div>
                            <label className={labelCls}>字段标签 *</label>
                            <input value={field.label || ""} onChange={(e) => updateConfigField(i, { label: e.target.value })}
                              className={inputCls} placeholder="输出质量" />
                          </div>
                          <div>
                            <label className={labelCls}>字段类型</label>
                            <div className="flex gap-2">
                              <select value={field.type || "text"} onChange={(e) => updateConfigField(i, normalizeConfigFieldType(field, e.target.value))}
                                className={inputCls}>
                                {nodeSchema.configFieldTypes.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                              </select>
                              <button onClick={() => removeConfigField(i)} className="px-3 rounded-lg border border-red-500/20 text-red-500 hover:bg-red-500/10">
                                <Trash2 className="w-3 h-3" />
                              </button>
                            </div>
                          </div>
                        </div>

                        <div className="grid grid-cols-2 gap-3">
                          <div>
                            <label className={labelCls}>默认值</label>
                            <input
                              value={(form.defaultConfig || {})[field.key] ?? ""}
                              onChange={(e) => setForm((current) => ({ ...current, defaultConfig: { ...(current.defaultConfig || {}), [field.key]: e.target.value } }))}
                              className={inputCls}
                              placeholder="节点初始值"
                            />
                          </div>
                          {supported.has("placeholder") && (
                            <div>
                              <label className={labelCls}>占位提示</label>
                              <input value={field.placeholder || ""} onChange={(e) => updateConfigField(i, { placeholder: e.target.value })}
                                className={inputCls} placeholder="请输入..." />
                            </div>
                          )}
                          {supported.has("chipColor") && (
                            <div>
                              <label className={labelCls}>标签颜色</label>
                              <input value={field.chipColor || ""} onChange={(e) => updateConfigField(i, { chipColor: e.target.value })}
                                className={inputCls} placeholder="#3b82f6" />
                            </div>
                          )}
                          {supported.has("apiEndpoint") && (
                            <div>
                              <label className={labelCls}>API Endpoint</label>
                              <input value={field.apiEndpoint || ""} onChange={(e) => updateConfigField(i, { apiEndpoint: e.target.value })}
                                className={inputCls} placeholder="/api/options" />
                            </div>
                          )}
                          {supported.has("apiUrl") && (
                            <div>
                              <label className={labelCls}>API URL</label>
                              <input value={field.apiUrl || ""} onChange={(e) => updateConfigField(i, { apiUrl: e.target.value })}
                                className={inputCls} placeholder="http://localhost:8000/api/options" />
                            </div>
                          )}
                          {supported.has("optionLabel") && (
                            <div>
                              <label className={labelCls}>选项标签字段</label>
                              <input value={field.optionLabel || ""} onChange={(e) => updateConfigField(i, { optionLabel: e.target.value })}
                                className={inputCls} placeholder="name" />
                            </div>
                          )}
                          {supported.has("optionValue") && (
                            <div>
                              <label className={labelCls}>选项值字段</label>
                              <input value={field.optionValue || ""} onChange={(e) => updateConfigField(i, { optionValue: e.target.value })}
                                className={inputCls} placeholder="id" />
                            </div>
                          )}
                          {supported.has("min") && (
                            <div>
                              <label className={labelCls}>最小值</label>
                              <input type="number" value={field.min ?? ""} onChange={(e) => updateConfigField(i, { min: e.target.value === "" ? undefined : Number(e.target.value) })}
                                className={inputCls} />
                            </div>
                          )}
                          {supported.has("max") && (
                            <div>
                              <label className={labelCls}>最大值</label>
                              <input type="number" value={field.max ?? ""} onChange={(e) => updateConfigField(i, { max: e.target.value === "" ? undefined : Number(e.target.value) })}
                                className={inputCls} />
                            </div>
                          )}
                          {supported.has("step") && (
                            <div>
                              <label className={labelCls}>步长</label>
                              <input type="number" value={field.step ?? ""} onChange={(e) => updateConfigField(i, { step: e.target.value === "" ? undefined : Number(e.target.value) })}
                                className={inputCls} />
                            </div>
                          )}
                          {supported.has("dependsOn") && (
                            <div>
                              <label className={labelCls}>依赖字段</label>
                              <input value={field.dependsOn || ""} onChange={(e) => updateConfigField(i, { dependsOn: e.target.value })}
                                className={inputCls} placeholder="selectedTypes" />
                            </div>
                          )}
                          {supported.has("dependsValue") && (
                            <div>
                              <label className={labelCls}>依赖值</label>
                              <input value={field.dependsValue ?? ""} onChange={(e) => updateConfigField(i, { dependsValue: e.target.value })}
                                className={inputCls} placeholder="video" />
                            </div>
                          )}
                        </div>

                        {supported.has("description") && (
                          <div>
                            <label className={labelCls}>描述</label>
                            <textarea value={field.description || ""} onChange={(e) => updateConfigField(i, { description: e.target.value })}
                              className={inputCls} rows={2} placeholder="字段用途说明" />
                          </div>
                        )}

                        {supported.has("options") && (
                          <div>
                            <label className={labelCls}>选项列表</label>
                            <textarea
                              value={stringifyKeyValueOptions(field.options)}
                              onChange={(e) => updateConfigField(i, { options: parseKeyValueOptions(e.target.value) })}
                              className={inputCls + " font-mono text-xs"}
                              rows={4}
                              placeholder={"high:高\nmedium:中\nlow:低"}
                            />
                            <p className="text-[11px] text-muted-foreground mt-1">每行一个选项，格式为 value:label</p>
                          </div>
                        )}

                        {supported.has("fileFilter") && (
                          <div>
                            <label className={labelCls}>文件过滤</label>
                            <input
                              value={stringifyCommaList(field.fileFilter)}
                              onChange={(e) => updateConfigField(i, { fileFilter: parseCommaList(e.target.value) })}
                              className={inputCls}
                              placeholder="mp4, mov, mkv"
                            />
                            <p className="text-[11px] text-muted-foreground mt-1">多个扩展名用逗号分隔</p>
                          </div>
                        )}

                        {supported.has("dependsOnAny") && (
                          <div>
                            <label className={labelCls}>依赖任一字段</label>
                            <input
                              value={stringifyCommaList(field.dependsOnAny)}
                              onChange={(e) => updateConfigField(i, { dependsOnAny: parseCommaList(e.target.value) })}
                              className={inputCls}
                              placeholder="selectedTypes, enabledFeatures"
                            />
                          </div>
                        )}

                        {supported.has("dependsAnyValues") && (
                          <div>
                            <label className={labelCls}>依赖任一值</label>
                            <input
                              value={stringifyCommaList(field.dependsAnyValues)}
                              onChange={(e) => updateConfigField(i, { dependsAnyValues: parseCommaList(e.target.value) })}
                              className={inputCls}
                              placeholder="video, audio"
                            />
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>

                <div className="flex gap-2 justify-end">
                  <button onClick={() => setTab("list")} className="px-4 py-2 text-sm rounded-lg border border-border/50 hover:bg-muted">取消</button>
                  <button onClick={handleCreate} className="px-4 py-2 text-sm rounded-lg bg-primary text-primary-foreground hover:bg-primary/90">创建</button>
                </div>
                {iconPickerOpen && (
                  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onMouseDown={() => setIconPickerOpen(false)}>
                    <div className="w-full max-w-md rounded-lg border border-border bg-card p-4 shadow-2xl" onMouseDown={(event) => event.stopPropagation()}>
                      <div className="mb-3 flex items-center justify-between">
                        <h4 className="text-sm font-semibold">选择节点图标</h4>
                        <button type="button" onClick={() => setIconPickerOpen(false)} className="p-1 text-muted-foreground hover:text-foreground" title="关闭"><XCircle className="w-4 h-4" /></button>
                      </div>
                      <div className="grid grid-cols-6 gap-2">
                        {NODE_ICON_OPTIONS.map((option) => {
                          const Icon = option.icon;
                          const active = form.icon === option.name;
                          return <button key={option.name} type="button" title={option.name} onClick={() => { setForm((current) => ({ ...current, icon: option.name })); setIconPickerOpen(false); }} className={`flex aspect-square items-center justify-center rounded-md border transition-colors ${active ? "border-primary bg-primary/10 text-primary" : "border-border/60 text-muted-foreground hover:border-primary/50 hover:text-foreground"}`}><Icon className="w-4 h-4" /></button>;
                        })}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Share */}
            {tab === "share" && selectedNode && (
              <div className="space-y-4">
                <div className="flex items-center gap-3">
                  <FileArchive className="w-8 h-8 text-blue-500" />
                  <div>
                    <h3 className="text-base font-bold">分享节点</h3>
                    <p className="text-sm text-muted-foreground">将 "{selectedNode.name}" 导出为 ZIP 包</p>
                  </div>
                </div>
                <div className="bg-muted/30 rounded-xl p-4 text-sm text-muted-foreground">
                  ZIP 包含以下内容：
                  <ul className="mt-2 space-y-1 list-disc list-inside text-xs">
                    <li><b>node_config.json</b> - 节点定义和配置</li>
                    <li><b>share_meta.json</b> - 分享元数据（名称、描述、作者、来源、标签、版本）</li>
                    {selectedNode.execType === "python" && <li><b>run.py + 代码文件</b> - 执行脚本和依赖</li>}
                  </ul>
                  <p className="mt-2">输出目录: <code className="text-primary">share/</code></p>
                </div>
                <div>
                  <label className={labelCls}>分享名称 *</label>
                  <input value={shareName} onChange={e => setShareName(e.target.value)}
                    className={inputCls} placeholder="我的节点" />
                </div>
                <div>
                  <label className={labelCls}>描述</label>
                  <input value={shareDesc} onChange={e => setShareDesc(e.target.value)}
                    className={inputCls} placeholder="节点功能说明" />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className={labelCls}>作者</label>
                    <input value={shareAuthor} onChange={e => setShareAuthor(e.target.value)}
                      className={inputCls} placeholder="你的名字或团队名" />
                  </div>
                  <div>
                    <label className={labelCls}>来源链接</label>
                    <input value={shareSourceUrl} onChange={e => setShareSourceUrl(e.target.value)}
                      className={inputCls} placeholder="https://example.com/project" />
                  </div>
                </div>
                <div>
                  <label className={labelCls}>标签</label>
                  <input value={shareTags} onChange={e => setShareTags(e.target.value)}
                    className={inputCls} placeholder="audio, tts, subtitle" />
                  <p className="text-[11px] text-muted-foreground mt-1">多个标签用逗号分隔</p>
                </div>
                <div className="flex gap-2 justify-end">
                  <button onClick={() => setTab("list")} className="px-4 py-2 text-sm rounded-lg border border-border/50 hover:bg-muted">取消</button>
                  <button onClick={handleShare}
                    className="px-4 py-2 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 flex items-center gap-1.5">
                    <Download className="w-4 h-4" /> 导出 ZIP
                  </button>
                </div>
              </div>
            )}

            {/* Import */}
            {tab === "import" && (
              <div className="space-y-4">
                <h3 className="text-base font-bold">导入节点</h3>
                <p className="text-sm text-muted-foreground">从共享 ZIP 文件导入自定义节点。ZIP 中的 Python 代码和依赖将自动安装。</p>
                <div className="border-2 border-dashed border-border/50 rounded-xl p-8 text-center">
                  <Upload className="w-10 h-10 mx-auto mb-3 text-muted-foreground" />
                  <p className="text-sm text-muted-foreground mb-3">选择节点 ZIP 文件</p>
                  <input ref={fileRef} type="file" accept=".zip" className="hidden" onChange={(e) => handleImportFileChanged(e.target.files?.[0])} />
                  <button onClick={handleSelectImportFile}
                    className="px-4 py-2 text-sm rounded-lg bg-primary/10 text-primary hover:bg-primary/20 transition-colors">
                    选择文件
                  </button>
                  {fileRef.current?.files?.[0] && (
                    <p className="text-sm mt-2 text-primary">{fileRef.current.files[0].name}</p>
                  )}
                </div>
                {validatingPackage && (
                  <div className="bg-blue-500/5 border border-blue-500/20 rounded-xl p-4 text-xs text-blue-600">
                    正在预检节点包...
                  </div>
                )}
                {packageValidation && (
                  <div className={`rounded-xl p-4 space-y-2 border ${
                    packageValidation.valid
                      ? "bg-blue-500/5 border-blue-500/20"
                      : "bg-red-500/5 border-red-500/20"
                  }`}>
                    <h4 className={`text-xs font-bold flex items-center gap-1.5 ${
                      packageValidation.valid ? "text-blue-600" : "text-red-600"
                    }`}>
                      {packageValidation.valid ? <CheckCircle2 className="w-3 h-3" /> : <AlertCircle className="w-3 h-3" />}
                      预检结果
                    </h4>
                    {packageValidation.node && (
                      <div className="text-xs text-muted-foreground space-y-1">
                        <div>节点: <span className="font-mono">{packageValidation.node.name} ({packageValidation.node.id})</span></div>
                        {packageValidation.node.version && <div>包版本: <span className="font-mono">{packageValidation.node.version}</span></div>}
                        <div>分类: <span className="font-mono">{packageValidation.node.category}</span></div>
                        <div>执行类型: <span className="font-mono">{packageValidation.node.execType || "无"}</span></div>
                        {packageValidation.node.execFile && <div>入口文件: <span className="font-mono">{packageValidation.node.execFile}</span></div>}
                        {packageValidation.node.schemaVersion && <div>Schema 版本: <span className="font-mono">{packageValidation.node.schemaVersion}</span></div>}
                      </div>
                    )}
                    {packageValidation.versionComparison && (
                      <div className={`rounded-lg border p-3 text-xs ${getVersionComparisonTone(packageValidation.versionComparison.status)}`}>
                        <p className="font-medium mb-1">版本比较</p>
                        <p>{packageValidation.versionComparison.message}</p>
                        {packageValidation.versionComparison.requiresConfirmation && (
                          <p className="mt-1 text-orange-600">该覆盖场景需要二次确认后才能继续导入。</p>
                        )}
                        {packageValidation.versionComparison.recommendedBackup && (
                          <p className="mt-1 text-muted-foreground">建议在覆盖前创建备份，便于回滚到旧版本。</p>
                        )}
                        {packageValidation.localNode && (
                          <p className="mt-1">
                            本地节点: <span className="font-mono">{packageValidation.localNode.name} ({packageValidation.localNode.id})</span>
                            {packageValidation.localNode.version ? ` / ${packageValidation.localNode.version}` : ""}
                          </p>
                        )}
                      </div>
                    )}
                    {packageValidation.shareMeta && (
                      <div className="text-xs text-muted-foreground space-y-1">
                        <p className="font-medium mb-1">来源信息：</p>
                        {packageValidation.shareMeta.shareName && <div>分享名: <span className="font-mono">{packageValidation.shareMeta.shareName}</span></div>}
                        {packageValidation.shareMeta.author && <div>作者: <span className="font-mono">{packageValidation.shareMeta.author}</span></div>}
                        {packageValidation.shareMeta.sourceUrl && <div>来源: <span className="font-mono break-all">{packageValidation.shareMeta.sourceUrl}</span></div>}
                        {packageValidation.shareMeta.version && <div>版本: <span className="font-mono">{packageValidation.shareMeta.version}</span></div>}
                        {packageValidation.shareMeta.exportedAt && <div>导出时间: <span className="font-mono">{packageValidation.shareMeta.exportedAt}</span></div>}
                        {!!packageValidation.shareMeta.tags?.length && <div>标签: <span className="font-mono">{packageValidation.shareMeta.tags.join(", ")}</span></div>}
                      </div>
                    )}
                    {packageValidation.errors.length > 0 && (
                      <div className="text-xs text-red-600">
                        <p className="font-medium mb-1">错误：</p>
                        {packageValidation.errors.map((error, i) => <div key={i}>• {error}</div>)}
                      </div>
                    )}
                    {packageValidation.warnings.length > 0 && (
                      <div className="text-xs text-amber-600">
                        <p className="font-medium mb-1">告警：</p>
                        {packageValidation.warnings.map((warning, i) => <div key={i}>• {warning}</div>)}
                      </div>
                    )}
                    {packageValidation.packageFiles.length > 0 && (
                      <div className="text-xs text-muted-foreground">
                        <p className="font-medium mb-1">包内文件：</p>
                        <div className="max-h-28 overflow-auto space-y-1">
                          {packageValidation.packageFiles.map((pkgFile, i) => <div key={i} className="font-mono text-[11px]">• {pkgFile}</div>)}
                        </div>
                      </div>
                    )}
                    {packageValidation.valid && packageValidation.localNode && (
                      <div className="rounded-lg border border-orange-500/20 bg-orange-500/5 p-3 text-xs space-y-3">
                        <div className="space-y-1">
                          <p className="font-medium text-orange-600">处理方式</p>
                          <p className="text-muted-foreground">检测到本地已存在同 ID 节点，默认不会静默覆盖。</p>
                        </div>
                        <label className="flex items-start gap-2">
                          <input
                            type="checkbox"
                            checked={allowOverwrite}
                            onChange={(e) => { setAllowOverwrite(e.target.checked); if (e.target.checked) setRenameMode(false); }}
                            className="mt-0.5"
                          />
                          <span>
                            <span className="font-medium text-foreground">覆盖已有节点</span>
                            <span className="block text-muted-foreground">用导入的包覆盖本地同名节点（可勾选下方备份）。</span>
                          </span>
                        </label>
                        <label className="flex items-start gap-2">
                          <input
                            type="checkbox"
                            checked={renameMode}
                            onChange={(e) => { setRenameMode(e.target.checked); if (e.target.checked) setAllowOverwrite(false); }}
                            className="mt-0.5"
                          />
                          <span>
                            <span className="font-medium text-foreground">重命名导入（保留本地节点）</span>
                            <span className="block text-muted-foreground">以新 ID 安装为全新节点，本地同名节点不受影响。</span>
                          </span>
                        </label>
                        {renameMode && (
                          <div>
                            <label className="block mb-1 text-muted-foreground">新节点 ID *</label>
                            <input
                              value={renameTo}
                              onChange={(e) => setRenameTo(e.target.value)}
                              className="w-full px-2.5 py-1.5 rounded-lg border border-border/50 bg-background focus:border-primary/50 outline-none"
                              placeholder="my_node_copy"
                            />
                            <p className="text-[11px] text-muted-foreground mt-1">不能与内置或现有自定义节点 ID 重复。</p>
                          </div>
                        )}
                        {allowOverwrite && (
                          <label className="flex items-start gap-2">
                            <input
                              type="checkbox"
                              checked={createBackup}
                              onChange={(e) => setCreateBackup(e.target.checked)}
                              className="mt-0.5"
                            />
                            <span>
                              <span className="font-medium text-foreground">覆盖前创建备份</span>
                              <span className="block text-muted-foreground">备份会保存旧版配置和代码目录，便于回滚。</span>
                            </span>
                          </label>
                        )}
                      </div>
                    )}
                  </div>
                )}
                {importResult && (
                  <div className="bg-emerald-500/5 border border-emerald-500/20 rounded-xl p-4 space-y-2">
                    <h4 className="text-xs font-bold text-emerald-600 flex items-center gap-1.5">
                      <CheckCircle2 className="w-3 h-3" /> 导入结果
                    </h4>
                    {importResult.files.length > 0 && (
                      <div className="text-xs text-muted-foreground">
                        <p className="font-medium mb-1">提取的文件：</p>
                        {importResult.files.map((f, i) => <div key={i} className="font-mono text-[11px]">• {f}</div>)}
                      </div>
                    )}
                    {importResult.install && (
                      <div className="text-xs text-muted-foreground">
                        <p className="font-medium mb-1">依赖安装：</p>
                        <p className="font-mono text-[11px] whitespace-pre-wrap">{importResult.install}</p>
                      </div>
                    )}
                    {importResult.warnings.length > 0 && (
                      <div className="text-xs text-amber-600">
                        <p className="font-medium mb-1">包告警：</p>
                        {importResult.warnings.map((warning, i) => <div key={i}>• {warning}</div>)}
                      </div>
                    )}
                    {importResult.versionComparison && (
                      <div className={`rounded-lg border p-3 text-xs ${getVersionComparisonTone(importResult.versionComparison.status)}`}>
                        <p className="font-medium mb-1">本次导入</p>
                        <p>{importResult.versionComparison.message}</p>
                      </div>
                    )}
                    {importResult.backupPath && (
                      <div className="text-xs text-muted-foreground">
                        <p className="font-medium mb-1">备份目录：</p>
                        <p className="font-mono text-[11px] break-all">{importResult.backupPath}</p>
                      </div>
                    )}
                  </div>
                )}
                <div className="flex gap-2 justify-end">
                  <button onClick={() => setTab("list")} className="px-4 py-2 text-sm rounded-lg border border-border/50 hover:bg-muted">取消</button>
                  <button onClick={handleImport}
                    disabled={
                      validatingPackage ||
                      (!!packageValidation && !packageValidation.valid) ||
                      (!!packageValidation?.localNode && !allowOverwrite && !renameMode) ||
                      (renameMode && !renameTo.trim())
                    }
                    className="px-4 py-2 text-sm rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed">
                    <Upload className="w-4 h-4" /> {renameMode ? "重命名并导入" : packageValidation?.localNode ? "确认导入并覆盖" : "导入"}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>

        <SharePackDialog
          open={packOpen}
          onClose={() => setPackOpen(false)}
          title={"分享打包节点：" + (selectedNode?.name || "")}
          initialName={selectedNode?.name || ""}
          initialDescription={selectedNode?.description || ""}
          initialCategory={selectedNode?.category}
          categories={Object.entries(CATEGORIES).map(([value, meta]) => ({ value, label: meta.label }))}
          previewProvider={() => captureNodeCard(selectedNode)}
          onSubmit={handlePackSubmit}
        />
      </div>
    </div>
  );
}

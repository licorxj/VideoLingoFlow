import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Bot,
  Brain,
  Download,
  ExternalLink,
  FileText,
  FolderSearch,
  Loader2,
  PlugZap,
  ShieldCheck,
  Sparkles,
  Wrench,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  piRpcApi,
  type PiAgentSettings,
  type PiIntegration,
} from "@/api/piRpc";
import { normalizeApiError } from "@/api/client";

const assistants = [
  ["general", "通用任务"],
  ["node", "节点创建助手"],
  ["workflow", "工作流编排助手"],
  ["execution", "任务执行助手"],
  ["files", "文件整理助手"],
  ["publish", "作品发布助手"],
  ["installer", "技能安装助手"],
] as const;

const emptySettings: PiAgentSettings = {
  model_mode: "router",
  custom_base_url: "",
  custom_api_key: "",
  custom_model: "",
  base_docs_paths: [],
  read_blacklist: [],
  write_blacklist: [],
  skills: [],
  mcps: [],
  assistants: {},
};

type SettingsTab = "general" | "model" | "permission" | "skill" | "mcp" | "assistant";

const settingTabs: { id: SettingsTab; label: string; icon: typeof Brain }[] = [
  { id: "general", label: "通用", icon: Bot },
  { id: "model", label: "模型", icon: Brain },
  { id: "permission", label: "通用权限", icon: ShieldCheck },
  { id: "skill", label: "Skill", icon: Sparkles },
  { id: "mcp", label: "MCP", icon: PlugZap },
  { id: "assistant", label: "助手", icon: ShieldCheck },
];

export default function AgentSettings() {
  const navigate = useNavigate();
  const [settings, setSettings] = useState<PiAgentSettings>(emptySettings);
  const [selected, setSelected] = useState<string>("general");
  const [docs, setDocs] = useState<{ name: string; path: string }[]>([]);
  const [scanning, setScanning] = useState<"skill" | "mcp" | null>(null);
  const [saving, setSaving] = useState(false);
  const [activeTab, setActiveTab] = useState<SettingsTab>("model");
  const [staging, setStaging] = useState<{ name: string; path: string }[]>([]);
  const [stagingLoading, setStagingLoading] = useState(false);
  const [installLevel, setInstallLevel] = useState<"project" | "system">("project");
  const [installing, setInstalling] = useState<string | null>(null);
  const [installNotice, setInstallNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [modelCatalog, setModelCatalog] = useState<
    { id: string; name: string; api: string; provider: string; baseUrl: string; reasoning: boolean; contextWindow: number; maxTokens: number }[]
  >([]);
  const [modelProvider, setModelProvider] = useState("openai");
  const [modelSearch, setModelSearch] = useState("");

  const load = () =>
    piRpcApi
      .getSettings()
      .then(({ data }) => setSettings({ ...emptySettings, ...data }));
  useEffect(() => {
    load();
    piRpcApi
      .scan("docs")
      .then(({ data }) => setDocs(data as { name: string; path: string }[]))
      .catch(() => undefined);
    piRpcApi
      .models()
      .then(({ data }) => setModelCatalog(data))
      .catch(() => undefined);
  }, []);

  const loadStaging = async () => {
    setStagingLoading(true);
    try {
      const { data } = await piRpcApi.staging();
      setStaging(data as { name: string; path: string }[]);
    } catch (error) {
      setInstallNotice({ kind: "error", text: normalizeApiError(error).message });
    } finally {
      setStagingLoading(false);
    }
  };
  useEffect(() => {
    if (activeTab === "skill" || activeTab === "mcp") loadStaging();
  }, [activeTab]);

  const installFromStaging = async (kind: "skill" | "mcp", name: string, sourceDir: string) => {
    setInstalling(name);
    setInstallNotice(null);
    try {
      const { data } = await piRpcApi.install(kind, name, installLevel, sourceDir);
      setInstallNotice({
        kind: "ok",
        text: data.enabled
          ? `已安装到项目（${name}）并自动授权。`
          : `已安装到系统目录（${name}），请在下方列表中开启授权后生效。`,
      });
      await scan(kind);
    } catch (error) {
      setInstallNotice({ kind: "error", text: normalizeApiError(error).message });
    } finally {
      setInstalling(null);
    }
  };

  const update = async (values: Partial<PiAgentSettings>) => {
    const next = { ...settings, ...values };
    setSettings(next);
    await piRpcApi.updateSettings(values);
  };
  const scan = async (kind: "skill" | "mcp") => {
    setScanning(kind);
    try {
      const { data } = await piRpcApi.scan(kind);
      setSettings((current) => ({
        ...current,
        [kind === "skill" ? "skills" : "mcps"]: data as PiIntegration[],
      }));
    } finally {
      setScanning(null);
    }
  };
  const toggle = async (kind: "skill" | "mcp", item: PiIntegration) => {
    await piRpcApi.toggleIntegration(kind, item.item_id, !item.enabled);
    setSettings((current) => ({
      ...current,
      [kind === "skill" ? "skills" : "mcps"]: (kind === "skill"
        ? current.skills
        : current.mcps
      ).map((entry) =>
        entry.item_id === item.item_id
          ? { ...entry, enabled: !entry.enabled }
          : entry,
      ),
    }));
  };
  const assistant = settings.assistants[selected] || {};
  const paths = (value: string) =>
    value
      .split("\n")
      .map((item) => item.trim())
      .filter(Boolean);
  const saveAssistant = async (values: Record<string, unknown>) => {
    setSaving(true);
    try {
      const { data } = await piRpcApi.updateAssistant(selected, {
        ...assistant,
        ...values,
      });
      setSettings((current) => ({
        ...current,
        assistants: { ...current.assistants, [selected]: data },
      }));
    } finally {
      setSaving(false);
    }
  };

  const integrations = (
    kind: "skill" | "mcp",
    title: string,
    icon: typeof Sparkles,
  ) => {
    const Icon = icon;
    const items = kind === "skill" ? settings.skills : settings.mcps;
    return (
      <div className="rounded-xl border border-border/55 bg-card/75 p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="flex items-center gap-2 text-sm font-semibold">
              <Icon className="h-4 w-4 text-primary" />
              {title}
            </h3>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              扫描已安装资源，只有已启用项目会被授权给 Agent。
            </p>
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={() => scan(kind)}
            disabled={scanning === kind}
          >
            {scanning === kind ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <FolderSearch className="mr-1.5 h-3.5 w-3.5" />
            )}
            扫描
          </Button>
        </div>
        <div className="mt-4 divide-y divide-border/45 rounded-lg border border-border/50">
          {items.length ? (
            items.map((item) => (
              <div
                key={item.item_id}
                className="flex items-center gap-3 px-3 py-2.5"
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">
                    {item.name}
                  </div>
                  <div className="truncate text-[11px] text-muted-foreground">
                    {item.path}
                  </div>
                </div>
                <button
                  type="button"
                  aria-label={`切换 ${item.name}`}
                  onClick={() => toggle(kind, item)}
                  className={`relative h-5 w-9 rounded-full transition-colors ${item.enabled ? "bg-primary" : "bg-muted-foreground/30"}`}
                >
                  <span
                    className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${item.enabled ? "translate-x-4" : "translate-x-0.5"}`}
                  />
                </button>
              </div>
            ))
          ) : (
            <div className="px-3 py-6 text-center text-xs text-muted-foreground">
              尚未扫描到可用资源
            </div>
          )}
        </div>
        <div className="mt-4 rounded-lg border border-dashed border-border/60 p-4">
          <div className="flex items-center justify-between">
            <div>
              <h4 className="flex items-center gap-2 text-xs font-semibold">
                <Download className="h-3.5 w-3.5 text-primary" />
                从暂存目录安装
              </h4>
              <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
                将安装包目录放入 data/workspace/pi-install-staging/ 后即可安装。
                项目专用默认自动授权；系统级需在下方列表手动放行。
              </p>
            </div>
            <Button size="sm" variant="ghost" onClick={loadStaging} disabled={stagingLoading}>
              {stagingLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FolderSearch className="h-3.5 w-3.5" />}
            </Button>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className="text-[11px] text-muted-foreground">安装级别</span>
            <button type="button" onClick={() => setInstallLevel("project")} className={`rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors ${installLevel === "project" ? "bg-primary text-primary-foreground" : "bg-muted/60 text-muted-foreground hover:bg-muted"}`}>项目专用</button>
            <button type="button" onClick={() => setInstallLevel("system")} className={`rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors ${installLevel === "system" ? "bg-primary text-primary-foreground" : "bg-muted/60 text-muted-foreground hover:bg-muted"}`}>系统级别</button>
          </div>
          <div className="mt-3 space-y-2">
            {staging.length ? staging.map((pkg) => (
              <div key={pkg.name} className="flex items-center gap-2 rounded-md border border-border/45 bg-background/50 px-2.5 py-2">
                <span className="min-w-0 flex-1 truncate text-xs font-medium">{pkg.name}</span>
                <span className="shrink-0 text-[10px] text-muted-foreground">{installLevel === "project" ? "项目" : "系统"}</span>
                <Button size="sm" variant="outline" onClick={() => installFromStaging(kind, pkg.name, pkg.path)} disabled={installing === pkg.name} className="h-7">
                  {installing === pkg.name ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <Download className="mr-1 h-3 w-3" />}
                  安装
                </Button>
              </div>
            )) : (
              <div className="px-2 py-3 text-center text-[11px] text-muted-foreground">
                暂存目录为空，先将安装包放入 data/workspace/pi-install-staging/
              </div>
            )}
          </div>
          {installNotice && (
            <div className={`mt-3 rounded-md px-2.5 py-2 text-[11px] leading-4 ${installNotice.kind === "ok" ? "bg-primary/10 text-primary" : "bg-destructive/10 text-destructive"}`}>
              {installNotice.text}
            </div>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <div>
        <h3 className="flex items-center gap-2 text-xl font-bold">
          <Bot className="h-5 w-5 text-primary" />
          Agent 设置
        </h3>
        <p className="mt-1 text-sm text-muted-foreground">
          模型、扩展授权和各助手能力边界会持久化到本地 Pi
          数据库，并在新会话创建时生效。
        </p>
      </div>
      <div
        role="tablist"
        aria-label="Agent 设置分类"
        className="flex items-center gap-1 overflow-x-auto rounded-lg border border-border/55 bg-muted/35 p-1"
      >
        {settingTabs.map(({ id, label, icon: TabIcon }) => {
          const active = activeTab === id;
          return (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setActiveTab(id)}
              className={`flex shrink-0 items-center gap-1.5 rounded-md px-3 py-2 text-xs font-medium transition-colors ${active ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:bg-background/60 hover:text-foreground"}`}
            >
              <TabIcon className="h-3.5 w-3.5" />
              {label}
            </button>
          );
        })}
      </div>
      {activeTab === "general" && (
        <div className="space-y-5">
          <div className="rounded-xl border border-border/55 bg-card/75 p-5">
            <div className="flex items-center gap-2">
              <Bot className="h-4 w-4 text-primary" />
              <h3 className="text-sm font-semibold">基础项目知识文档</h3>
            </div>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              全局默认人设为内置固定身份与权限边界，无需也不可在此修改。选中的知识文档会在每个新会话创建时按项目根目录加载正文。
            </p>
            <div className="mt-4 space-y-2 rounded-lg border border-border/50 p-3">
              {docs.map((doc) => {
                const checked = settings.base_docs_paths.includes(doc.path);
                return (
                  <label key={doc.path} className="flex cursor-pointer items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => update({
                        base_docs_paths: checked
                          ? settings.base_docs_paths.filter((path) => path !== doc.path)
                          : [...settings.base_docs_paths, doc.path],
                      })}
                    />
                    <span className="truncate">{doc.name}</span>
                  </label>
                );
              })}
            </div>
          </div>
        </div>
      )}
      {activeTab === "model" && (
        <div className="rounded-xl border border-border/55 bg-card/75 p-5">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <Brain className="h-4 w-4 text-primary" />
            智能体模型
          </h3>
          <div className="mt-4 flex w-fit rounded-lg border border-border/50 bg-muted/35 p-1">
            <button
              onClick={() => update({ model_mode: "router" })}
              className={`rounded-md px-3 py-1.5 text-sm ${settings.model_mode === "router" ? "bg-background font-medium shadow-sm" : "text-muted-foreground"}`}
            >
              沿用大模型路由器
            </button>
            <button
              onClick={() => update({ model_mode: "custom" })}
              className={`rounded-md px-3 py-1.5 text-sm ${settings.model_mode === "custom" ? "bg-background font-medium shadow-sm" : "text-muted-foreground"}`}
            >
              专用大模型
            </button>
          </div>
          {settings.model_mode === "router" ? (
            <div className="mt-4 flex items-center justify-between rounded-lg border border-primary/20 bg-primary/5 p-3">
              <p className="text-sm text-muted-foreground">
                使用 LLM 路由器的 Agent 路由和模型策略。
              </p>
              <Button
                size="sm"
                variant="outline"
                onClick={() => navigate("/llm-router")}
              >
                <ExternalLink className="mr-1.5 h-3.5 w-3.5" />
                打开路由器
              </Button>
            </div>
          ) : (
            <>
            <div className="mt-4 rounded-lg border border-border/55 bg-muted/25 p-4">
              <div className="flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-primary" />
                <h4 className="text-sm font-semibold">从 Pi 模型数据库选择</h4>
              </div>
              <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
                沿用 Pi 内置模型目录（{modelCatalog.length ? `${modelCatalog.length} 个模型` : "加载中…"}）。选择 Provider 与模型后自动填充
                Base URL 与模型名，你只需填入对应平台的 API Key 即可。
              </p>
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                <label className="text-xs font-medium text-muted-foreground">
                  Provider
                  <select
                    className="mt-1.5 w-full rounded-lg border border-border/60 bg-background px-3 py-2 text-sm text-foreground"
                    value={modelProvider}
                    onChange={(event) => { setModelProvider(event.target.value); setModelSearch(""); }}
                  >
                    {[...new Set(modelCatalog.map((item) => item.provider))].sort().map((provider) => (
                      <option key={provider} value={provider}>{provider}</option>
                    ))}
                  </select>
                </label>
                <label className="text-xs font-medium text-muted-foreground">
                  搜索模型
                  <input
                    type="text"
                    className="mt-1.5 w-full rounded-lg border border-border/60 bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
                    value={modelSearch}
                    placeholder="输入模型 ID 或名称过滤"
                    onChange={(event) => setModelSearch(event.target.value)}
                  />
                </label>
              </div>
              <div className="mt-2 max-h-48 overflow-y-auto rounded-lg border border-border/50 bg-background/60 p-1">
                {modelCatalog
                  .filter((item) => item.provider === modelProvider)
                  .filter((item) => !modelSearch || item.id.toLowerCase().includes(modelSearch.toLowerCase()) || item.name.toLowerCase().includes(modelSearch.toLowerCase()))
                  .slice(0, 60)
                  .map((item) => {
                    const selected = settings.custom_model === item.id;
                    return (
                      <button
                        key={`${item.provider}-${item.id}`}
                        type="button"
                        onClick={() => update({ custom_base_url: item.baseUrl, custom_model: item.id })}
                        className={`flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-xs transition-colors ${selected ? "bg-primary text-primary-foreground" : "text-foreground hover:bg-muted"}`}
                      >
                        <span className="min-w-0 flex-1 truncate font-medium">{item.name}</span>
                        {item.reasoning && <span className="shrink-0 rounded bg-primary/10 px-1 py-0.5 text-[9px] font-semibold text-primary">推理</span>}
                        <span className="shrink-0 text-[10px] text-muted-foreground">{item.contextWindow ? `${(item.contextWindow / 1000).toFixed(0)}K` : ""}</span>
                      </button>
                    );
                  })}
                {!modelCatalog.some((item) => item.provider === modelProvider) && <div className="px-2 py-3 text-center text-xs text-muted-foreground">该 Provider 暂无模型</div>}
              </div>
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-3">
              {[
                [
                  "custom_base_url",
                  "API Base URL",
                  "https://api.example.com/v1",
                ],
                ["custom_api_key", "API Key", "登录对应平台获取并粘贴到此处"],
                ["custom_model", "模型名称", "model-id"],
              ].map(([key, label, placeholder]) => (
                <label
                  key={key}
                  className="text-xs font-medium text-muted-foreground"
                >
                  {label}
                  <input
                    type={key === "custom_api_key" ? "password" : "text"}
                    className="mt-1.5 w-full rounded-lg border border-border/60 bg-background px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
                    value={settings[key as keyof PiAgentSettings] as string}
                    placeholder={placeholder}
                    onChange={(event) =>
                      setSettings({ ...settings, [key]: event.target.value })
                    }
                    onBlur={(event) =>
                      update({
                        [key]: event.target.value,
                      } as Partial<PiAgentSettings>)
                    }
                  />
                </label>
              ))}
            </div>
            </>
          )}
        </div>
      )}
      {activeTab === "permission" && (
        <div className="rounded-xl border border-border/55 bg-card/75 p-5">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-semibold">通用路径权限</h3>
          </div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            黑名单会与每个助手的私有黑名单合并。命中的目录及其子目录会被 Pi
            文件工具拒绝访问。可输入相对项目根目录的路径，例如 backend/config。
          </p>
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <label className="block text-xs font-medium text-muted-foreground">
              通用读取目录黑名单（每行一个）
              <textarea
                className="mt-1.5 min-h-36 w-full rounded-lg border border-border/60 bg-background p-3 text-sm text-foreground outline-none focus:border-primary"
                defaultValue={settings.read_blacklist.join("\n")}
                onBlur={(event) =>
                  update({ read_blacklist: paths(event.target.value) })
                }
                placeholder=".git"
              />
            </label>
            <label className="block text-xs font-medium text-muted-foreground">
              通用写入目录黑名单（每行一个）
              <textarea
                className="mt-1.5 min-h-36 w-full rounded-lg border border-border/60 bg-background p-3 text-sm text-foreground outline-none focus:border-primary"
                defaultValue={settings.write_blacklist.join("\n")}
                onBlur={(event) =>
                  update({ write_blacklist: paths(event.target.value) })
                }
                placeholder="backend/config"
              />
            </label>
          </div>
        </div>
      )}
      {activeTab === "skill" && integrations("skill", "Skill 授权", Sparkles)}
      {activeTab === "mcp" && integrations("mcp", "MCP 授权", PlugZap)}
      {activeTab === "assistant" && (
        <div className="rounded-xl border border-border/55 bg-card/75 p-5">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-semibold">助手能力边界</h3>
          </div>
          <div className="mt-4 grid gap-5 lg:grid-cols-[190px_1fr]">
            <div className="space-y-1">
              {assistants.map(([id, label]) => (
                <button
                  key={id}
                  onClick={() => setSelected(id)}
                  className={`w-full rounded-lg px-3 py-2 text-left text-sm ${selected === id ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted"}`}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="space-y-4">
              <label className="block text-xs font-medium text-muted-foreground">
                人设设定
                <textarea
                  className="mt-1.5 min-h-28 w-full rounded-lg border border-border/60 bg-background p-3 text-sm text-foreground outline-none focus:border-primary"
                  defaultValue={assistant.persona || ""}
                  onBlur={(event) =>
                    saveAssistant({ persona: event.target.value })
                  }
                  placeholder="定义助手角色、任务范围和回答风格"
                />
              </label>
              <label className="block text-xs font-medium text-muted-foreground">
                业务能力文档
                <select
                  className="mt-1.5 w-full rounded-lg border border-border/60 bg-background px-3 py-2 text-sm text-foreground"
                  value={assistant.docs_path || ""}
                  onChange={(event) =>
                    saveAssistant({ docs_path: event.target.value })
                  }
                >
                  <option value="">不绑定文档</option>
                  {docs.map((doc) => (
                    <option key={doc.path} value={doc.path}>
                      {doc.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-xs font-medium text-muted-foreground">
                私有读取目录黑名单（每行一个）
                <textarea
                  className="mt-1.5 min-h-20 w-full rounded-lg border border-border/60 bg-background p-3 text-sm text-foreground"
                  defaultValue={(assistant.read_blacklist || []).join("\n")}
                  onBlur={(event) =>
                    saveAssistant({
                      read_blacklist: paths(event.target.value),
                    })
                  }
                  placeholder="backend/config"
                />
              </label>
              <label className="block text-xs font-medium text-muted-foreground">
                私有写入目录黑名单（每行一个）
                <textarea
                  className="mt-1.5 min-h-20 w-full rounded-lg border border-border/60 bg-background p-3 text-sm text-foreground"
                  defaultValue={(assistant.write_blacklist || []).join("\n")}
                  onBlur={(event) =>
                    saveAssistant({
                      write_blacklist: paths(event.target.value),
                    })
                  }
                  placeholder="backend/config"
                />
              </label>
              <div className="flex justify-end">
                <Button size="sm" disabled={saving}>
                  <Wrench className="mr-1.5 h-3.5 w-3.5" />
                  {saving ? "保存中" : "边界已自动保存"}
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

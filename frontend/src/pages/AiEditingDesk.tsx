import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  ExternalLink,
  Eye,
  EyeOff,
  FileKey2,
  FolderTree,
  Link2,
  Loader2,
  PackagePlus,
  Play,
  Power,
  RefreshCw,
  Save,
  Scissors,
  Server,
  Settings2,
  SlidersHorizontal,
  Video,
  Volume2,
  Image as ImageIcon,
  Hash,
  type LucideIcon,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageBackground } from "@/components/shared/PageBackground";
import { PageHeader } from "@/components/shared/PageHeader";
import { cn } from "@/lib/utils";
import { toast } from "@/pages/llm-router/toast";
import {
  openchatcutApi,
  type OpenChatCutConfig,
  type OpenChatCutImageOption,
  type OpenChatCutStatus,
  type OpenChatCutTtsOption,
} from "@/api/openchatcut";

const MANAGER_BASE = "http://localhost:18001";

type Section = "llm" | "image" | "tts" | "video";
type TabKey = Section | "runtime";

const SECTION_META: Record<TabKey, { title: string; desc: string; icon: LucideIcon }> = {
  runtime: {
    title: "运行与产物路径",
    desc: "剪辑台服务的监听地址、端口与媒体文件落盘位置",
    icon: SlidersHorizontal,
  },
  image: {
    title: "图像生成",
    desc: "桥接端按请求是否带参考图，自动在 文生图 / 图生图 模型间切换；请求经本项目桥接端转发，密钥由系统自动生成注入",
    icon: ImageIcon,
  },
  tts: {
    title: "语音合成",
    desc: "配音能力经本项目桥接端路由到已配置的 TTS 接口与模型，与生图共用同一桥接端 Base URL",
    icon: Volume2,
  },
  llm: {
    title: "Agent 大模型",
    desc: "剪辑台内置 Agent 的对话模型，默认直连本项目 LLM 路由器 http://localhost:8800/v1（默认模型 vlf-agent）",
    icon: Bot,
  },
  video: {
    title: "视频生成",
    desc: "由剪辑台直连第三方端点（不经本项目桥接），需填写该平台的真实 Key；留空则不注入",
    icon: Video,
  },
};

// Tab 展示顺序：先配置运行参数，再按能力分组
const TAB_ORDER: TabKey[] = ["runtime", "image", "tts", "llm", "video"];

/** 统一的字段标题样式 */
function FieldLabel({ children, hint }: { children: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <span className="flex items-baseline justify-between gap-2">
      <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{children}</span>
      {hint && <span className="text-[10px] text-muted-foreground/70">{hint}</span>}
    </span>
  );
}

function Field({
  label,
  hint,
  value,
  onChange,
  placeholder,
  secret,
  mono,
}: {
  label: string;
  hint?: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  secret?: boolean;
  mono?: boolean;
}) {
  const [reveal, setReveal] = useState(false);
  const masked = !!secret && !reveal;
  return (
    <label className="block space-y-1.5">
      <FieldLabel>{label}</FieldLabel>
      <span className="relative block">
        <input
          type={masked ? "password" : "text"}
          value={value}
          placeholder={placeholder}
          spellCheck={false}
          onChange={(event) => onChange(event.target.value)}
          className={cn(
            "h-10 w-full rounded-lg border border-border/70 bg-background/80 px-3 text-sm shadow-sm outline-none transition-all",
            "placeholder:text-muted-foreground/50 focus:border-primary/70 focus:ring-2 focus:ring-primary/15",
            mono && "font-mono text-[13px]",
            masked && "pr-10",
          )}
        />
        {secret && (
          <button
            type="button"
            onClick={() => setReveal((v) => !v)}
            title={reveal ? "隐藏内容" : "显示内容"}
            className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            {reveal ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
          </button>
        )}
      </span>
      {hint && <span className="block text-[11px] leading-relaxed text-muted-foreground/80">{hint}</span>}
    </label>
  );
}

const AUTO_VALUE = "__auto__";

function SelectField({
  label,
  value,
  onChange,
  options,
  placeholder = "请选择",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  placeholder?: string;
}) {
  const current = value || AUTO_VALUE;
  // 当前保存值不在可选列表里（接口模型已下架等）时，保留显示而不是空值
  const items = options.some((opt) => (opt.value || AUTO_VALUE) === current)
    ? options
    : [{ value: value, label: `${value}（当前配置）` }, ...options];
  return (
    <label className="block space-y-1.5">
      <FieldLabel>{label}</FieldLabel>
      <Select value={current} onValueChange={(v) => onChange(v === AUTO_VALUE ? "" : v)}>
        <SelectTrigger className="h-10 w-full rounded-lg border-border/70 bg-background/80 text-sm shadow-sm transition-all focus:border-primary/70 focus:ring-2 focus:ring-primary/15">
          <SelectValue placeholder={placeholder} />
        </SelectTrigger>
        <SelectContent>
          {items.map((opt) => (
            <SelectItem key={opt.value || AUTO_VALUE} value={opt.value || AUTO_VALUE}>
              {opt.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </label>
  );
}

/** 面板底部的说明条 */
function SectionNote({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-lg border border-border/50 bg-muted/30 px-3 py-2.5 text-[11px] leading-relaxed text-muted-foreground">
      {children}
    </p>
  );
}

/** 服务状态指标卡 */
function StatusTile({
  ok,
  label,
  detail,
  icon: Icon,
}: {
  ok: boolean;
  label: string;
  detail: string;
  icon: LucideIcon;
}) {
  return (
    <div
      className={cn(
        "flex items-start gap-2.5 rounded-xl border p-3 transition-colors",
        ok ? "border-success/25 bg-success/5" : "border-destructive/25 bg-destructive/5",
      )}
    >
      <span className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-lg", ok ? "tone-success-soft" : "tone-danger-soft")}>
        <Icon className={cn("h-3.5 w-3.5", ok ? "text-success" : "text-destructive")} />
      </span>
      <span className="min-w-0">
        <span className={cn("block text-xs font-semibold", ok ? "text-success" : "text-destructive")}>{label}</span>
        <span className="mt-0.5 block truncate text-[11px] text-muted-foreground" title={detail}>
          {detail}
        </span>
      </span>
    </div>
  );
}

export default function AiEditingDesk() {
  const [config, setConfig] = useState<OpenChatCutConfig | null>(null);
  const [draft, setDraft] = useState<OpenChatCutConfig | null>(null);
  const [status, setStatus] = useState<OpenChatCutStatus | null>(null);
  const [imageOptions, setImageOptions] = useState<OpenChatCutImageOption[]>([]);
  const [ttsOptions, setTtsOptions] = useState<OpenChatCutTtsOption[]>([]);
  const [optionsFailed, setOptionsFailed] = useState(false);
  const [envPreview, setEnvPreview] = useState<Record<string, string> | null>(null);
  const [saving, setSaving] = useState(false);
  const [applying, setApplying] = useState(false);
  const [serviceBusy, setServiceBusy] = useState<"" | "start" | "stop" | "restart">("");
  const [installing, setInstalling] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [tab, setTab] = useState<TabKey>("runtime");
  const bootPollRef = useRef<number | null>(null);
  const installPollRef = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      const [cfgRes, statusRes, imgOptRes, ttsOptRes] = await Promise.all([
        openchatcutApi.getConfig(),
        openchatcutApi.status(),
        openchatcutApi.imageOptions().catch(() => null),
        openchatcutApi.ttsOptions().catch(() => null),
      ]);
      setConfig(cfgRes.data.config);
      setDraft(cfgRes.data.config);
      setStatus(statusRes.data);
      setImageOptions(imgOptRes?.data.interfaces ?? []);
      setTtsOptions(ttsOptRes?.data.interfaces ?? []);
      setOptionsFailed(!imgOptRes || !ttsOptRes);
      setDirty(false);
    } catch (error: any) {
      toast({ title: "加载失败", description: error?.message || "无法读取 AI剪辑台配置", variant: "destructive" });
    }
  }, []);

  useEffect(() => {
    load();
    return () => {
      if (bootPollRef.current) window.clearInterval(bootPollRef.current);
      if (installPollRef.current) window.clearInterval(installPollRef.current);
    };
  }, [load]);

  const patchSection = (section: Section, key: string, value: string) => {
    setDraft((prev) => {
      if (!prev) return prev;
      return { ...prev, [section]: { ...prev[section], [key]: value } } as OpenChatCutConfig;
    });
    setDirty(true);
  };

  const patchTop = (key: "enabled" | "host" | "port" | "agent_import_roots" | "media_dir", value: string | boolean | number) => {
    setDraft((prev) => (prev ? ({ ...prev, [key]: value } as OpenChatCutConfig) : prev));
    setDirty(true);
  };

  const sectionValue = (section: Section, key: string): string => {
    const sec = draft?.[section] as unknown as Record<string, string> | undefined;
    return sec?.[key] ?? "";
  };

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      const res = await openchatcutApi.updateConfig({
        enabled: draft.enabled,
        host: draft.host,
        port: Number(draft.port) || 5199,
        llm: draft.llm,
        image: draft.image,
        tts: draft.tts,
        video: draft.video,
        mcp: draft.mcp,
        agent_import_roots: draft.agent_import_roots,
        media_dir: draft.media_dir,
      });
      setConfig(res.data.config);
      setDraft(res.data.config);
      setDirty(false);
      toast({
        title: "已保存并注入配置",
        description: `参数已写入 OpenChatCut 的 .env.local（${res.data.env_keys.length} 项），重启剪辑台后生效。`,
        variant: "success",
        duration: 6000,
      });
    } catch (error: any) {
      toast({ title: "保存失败", description: error?.message || "写入配置失败", variant: "destructive", duration: 6000 });
    } finally {
      setSaving(false);
    }
  };

  const applyEnv = async () => {
    setApplying(true);
    try {
      const res = await openchatcutApi.applyEnv();
      toast({ title: "已重新生成 .env.local", description: `注入 ${res.data.env_keys.length} 项环境参数`, variant: "success" });
      const preview = await openchatcutApi.envPreview();
      setEnvPreview(preview.data.env);
      const statusRes = await openchatcutApi.status();
      setStatus(statusRes.data);
    } catch (error: any) {
      toast({ title: "注入失败", description: error?.message || "生成 .env.local 失败", variant: "destructive", duration: 6000 });
    } finally {
      setApplying(false);
    }
  };

  const toggleEnvPreview = async () => {
    if (envPreview) {
      setEnvPreview(null);
      return;
    }
    try {
      const res = await openchatcutApi.envPreview();
      setEnvPreview(res.data.env);
    } catch (error: any) {
      toast({ title: "预览失败", description: error?.message || "读取环境变量失败", variant: "destructive" });
    }
  };

  const installDesk = async () => {
    if (installing) return;
    // 前置提醒：未检测到 Node.js 时直接提示安装，不发起后台安装
    if (status && status.node_ok === false) {
      toast({
        title: "未检测到 Node.js",
        description:
          "安装剪辑台需要 Node.js 24.x。请先到 https://nodejs.org 下载安装（建议 LTS），完成后重启主程序或刷新本页再试。",
        variant: "destructive",
        duration: 12000,
      });
      return;
    }
    setInstalling(true);
    toast({
      title: "开始安装剪辑台",
      description: "正在后台执行：拉取项目 → 安装依赖 → 构建前端（首次安装约 10-20 分钟，完成后状态自动更新）。",
      duration: 8000,
    });
    try {
      const res = await openchatcutApi.install();
      if (res.data?.error === "node_missing") {
        toast({ title: "未检测到 Node.js", description: res.data.message, variant: "destructive", duration: 12000 });
        setInstalling(false);
        return;
      }
      if (res.data?.error === "git_missing") {
        toast({ title: "未检测到 git", description: res.data.message, variant: "destructive", duration: 12000 });
        setInstalling(false);
        return;
      }
    } catch (error: any) {
      toast({ title: "安装启动失败", description: error?.message || "无法调用安装接口", variant: "destructive", duration: 6000 });
      setInstalling(false);
      return;
    }
    if (installPollRef.current) window.clearInterval(installPollRef.current);
    installPollRef.current = window.setInterval(async () => {
      try {
        const res = await openchatcutApi.status();
        setStatus(res.data);
        if (!res.data.installing) {
          if (installPollRef.current) window.clearInterval(installPollRef.current);
          installPollRef.current = null;
          setInstalling(false);
          if (res.data.deps) {
            toast({ title: "剪辑台安装完成", description: "OpenChatCut 项目与依赖已就绪，可以启动剪辑台了。", variant: "success" });
          } else {
            let detail = "安装未成功，请查看后端日志或手动执行安装脚本。";
            try {
              const s = await openchatcutApi.installStatus();
              const tail = (s.data.log || []).slice(-2).join(" / ");
              if (tail) detail = tail;
            } catch {
              /* 忽略，用默认提示 */
            }
            toast({ title: "剪辑台安装失败", description: detail, variant: "destructive", duration: 8000 });
          }
        }
      } catch {
        /* 忽略瞬时错误，继续轮询 */
      }
    }, 2000);
  };

  const controlService = async (action: "start" | "stop" | "restart") => {
    setServiceBusy(action);
    try {
      await fetch(`${MANAGER_BASE}/manager/${action}-openchatcut`, { method: "POST" });
      toast({ title: `已发送${action === "start" ? "启动" : action === "stop" ? "停止" : "重启"}指令`, description: "剪辑台服务正在处理，状态会自动刷新。", variant: "default" });
    } catch {
      toast({ title: "操作失败", description: "无法连接本地进程管理器（18001）", variant: "destructive" });
    } finally {
      window.setTimeout(() => setServiceBusy(""), 1200);
    }
  };

  const openDesk = async () => {
    if (!status) return;
    if (status.running) {
      window.open(status.editor_url, "_blank", "noopener,noreferrer");
      return;
    }
    toast({ title: "剪辑台未运行", description: "正在自动拉起服务，启动完成后将自动打开…", variant: "default", duration: 5000 });
    try {
      await fetch(`${MANAGER_BASE}/manager/start-openchatcut`, { method: "POST" });
    } catch {
      toast({ title: "启动失败", description: "无法连接本地进程管理器（18001）", variant: "destructive" });
      return;
    }
    if (bootPollRef.current) window.clearInterval(bootPollRef.current);
    let attempts = 0;
    bootPollRef.current = window.setInterval(async () => {
      attempts += 1;
      try {
        const res = await openchatcutApi.status();
        setStatus(res.data);
        if (res.data.running) {
          if (bootPollRef.current) window.clearInterval(bootPollRef.current);
          bootPollRef.current = null;
          toast({ title: "剪辑台已就绪", description: "已在新标签页打开。", variant: "success" });
          window.open(res.data.editor_url, "_blank", "noopener,noreferrer");
        }
      } catch {
        /* 忽略瞬时错误，继续轮询 */
      }
      if (attempts >= 45) {
        if (bootPollRef.current) window.clearInterval(bootPollRef.current);
        bootPollRef.current = null;
        toast({ title: "启动超时", description: "服务仍未就绪，可尝试点击「安装剪辑台」完成部署后重试。", variant: "destructive", duration: 8000 });
      }
    }, 2000);
  };

  const running = !!status?.running;
  const depsReady = !!status?.deps;

  // 下拉选项：接口选择后，模型清单跟随该接口；「自动选择」时展示首个已启用接口的清单
  const activeImageOption =
    imageOptions.find((opt) => opt.id === draft?.image.interface_id) ?? imageOptions[0];
  const activeTtsOption =
    ttsOptions.find((opt) => opt.id === draft?.tts.interface_id) ?? ttsOptions[0];

  return (
    <PageBackground tone="editing" className="h-full overflow-auto">
      <div className="mx-auto flex max-w-5xl flex-col gap-4 p-3 sm:p-5">
        <PageHeader
          icon={Scissors}
          title="AI 剪辑台"
          detail="桥接开源项目 OpenChatCut，强大的 AI 剪辑能力。配置下方接口并保存注入，即可对接 VLF 的全部接口能力。"
          tone="ai"
          actions={
            <Button variant="ai" size="sm" onClick={openDesk}>
              <ExternalLink className="mr-1.5 h-3.5 w-3.5" />
              打开剪辑台
            </Button>
          }
        />

        {/* 服务状态 */}
        <section className="animate-in overflow-hidden rounded-2xl border border-border/60 bg-card/70 shadow-sm">
          <div className="flex flex-col gap-4 border-b border-border/60 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
            <div className="flex items-center gap-3">
              <span className={cn("relative flex h-11 w-11 shrink-0 items-center justify-center rounded-xl", running ? "tone-success-soft" : "tone-danger-soft")}>
                <Server className={cn("h-5 w-5", running ? "text-success" : "text-destructive")} />
                {running && <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 animate-pulse-glow rounded-full bg-success ring-2 ring-card" />}
              </span>
              <div className="min-w-0">
                <h2 className="text-sm font-bold tracking-tight">剪辑台服务</h2>
                <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                  <span className={cn("inline-flex items-center gap-1.5 font-medium", running ? "text-success" : "text-destructive")}>
                    <span className={cn("h-1.5 w-1.5 rounded-full", running ? "bg-success" : "bg-destructive")} />
                    {running ? "运行中" : "未运行"}
                  </span>
                  <span className="text-muted-foreground/40">|</span>
                  <span className="inline-flex items-center gap-1">
                    <Hash className="h-3 w-3" />
                    {status?.port ?? 5199}
                  </span>
                  {status?.mcp_url && (
                    <>
                      <span className="text-muted-foreground/40">|</span>
                      <span className="font-mono text-[11px]">{status.mcp_url}</span>
                    </>
                  )}
                </p>
              </div>
            </div>
            <div className="flex shrink-0 flex-wrap items-center gap-2">
              <Button
                variant={depsReady && !installing ? "outline" : "ai"}
                size="sm"
                className={cn(!depsReady && !installing && "animate-pulse-glow")}
                disabled={installing}
                onClick={installDesk}
              >
                {installing ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <PackagePlus className="mr-1.5 h-3.5 w-3.5" />}
                {installing ? "安装中…" : "安装剪辑台"}
              </Button>
              <Button variant="success-soft" size="sm" disabled={serviceBusy !== "" || running} onClick={() => controlService("start")}>
                {serviceBusy === "start" ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Play className="mr-1.5 h-3.5 w-3.5" />}
                启动
              </Button>
              <Button variant="danger-soft" size="sm" disabled={serviceBusy !== "" || !running} onClick={() => controlService("stop")}>
                {serviceBusy === "stop" ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Power className="mr-1.5 h-3.5 w-3.5" />}
                停止
              </Button>
              <Button variant="outline" size="sm" disabled={serviceBusy !== ""} onClick={() => controlService("restart")}>
                {serviceBusy === "restart" ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="mr-1.5 h-3.5 w-3.5" />}
                重启
              </Button>
            </div>
          </div>

          <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4 sm:p-5">
            <StatusTile
              ok={!!status?.repo}
              label="项目已部署"
              detail={status?.repo ? "thirdparty/openchatcut 已就位" : "未拉取，点击「安装剪辑台」自动获取"}
              icon={FolderTree}
            />
            <StatusTile
              ok={depsReady}
              label={depsReady ? "依赖已安装" : "依赖未安装"}
              detail={
                !depsReady
                  ? "点击「安装剪辑台」自动拉取并安装"
                  : status?.build
                    ? "npm install + 前端构建产物已就绪"
                    : "依赖已装但前端未构建，启动走 dev 模式"
              }
              icon={CheckCircle2}
            />
            <StatusTile
              ok={!!status?.env_file}
              label="配置已注入"
              detail={status?.env_file ? ".env.local 已生成" : "尚未生成 .env.local"}
              icon={FileKey2}
            />
            <StatusTile
              ok={running}
              label="访问地址"
              detail={status?.editor_url ?? "http://127.0.0.1:5199/"}
              icon={Link2}
            />
          </div>

          {status && status.node_ok === false && (
            <div className="mx-4 mb-4 flex items-start gap-2.5 rounded-xl border border-warning/30 bg-warning/10 p-3 text-xs text-warning sm:mx-5 sm:mb-5">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <p className="leading-relaxed">
                未检测到 Node.js，无法安装/启动剪辑台。请先到{" "}
                <a href="https://nodejs.org" target="_blank" rel="noreferrer" className="font-medium underline underline-offset-2">
                  nodejs.org
                </a>{" "}
                安装 Node.js <b>24.x</b>（建议 LTS），完成后重启主程序或刷新本页。
              </p>
            </div>
          )}
          {!depsReady && status && (
            <div className="mx-4 mb-4 flex items-start gap-2.5 rounded-xl border border-warning/30 bg-warning/10 p-3 text-xs text-warning sm:mx-5 sm:mb-5">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <p className="leading-relaxed">
                {status.repo
                  ? "尚未安装剪辑台依赖。点击右上角「安装剪辑台」按钮（执行 "
                  : "尚未拉取剪辑台项目。点击右上角「安装剪辑台」按钮，将自动从上游拉取 OpenChatCut 源码（执行 "}
                <code className="rounded bg-warning/15 px-1 py-0.5 font-mono">thirdparty/install_openchatcut.py</code>
                {status.repo
                  ? "）完成 npm install 与前端构建，或在该目录手动执行 npm install。"
                  : "：git clone → npm install → 前端构建），完成后即可启动。"}
              </p>
            </div>
          )}
        </section>

        {/* 接口与大模型设置 */}
        <section className="pb-6">
          <div className="mb-3 flex items-center gap-2.5 px-1">
            <span className="tone-ai-soft flex h-8 w-8 shrink-0 items-center justify-center rounded-lg">
              <Settings2 className="h-4 w-4 text-ai" />
            </span>
            <div className="min-w-0">
              <h2 className="text-sm font-bold tracking-tight">接口与大模型设置</h2>
              <p className="text-[11px] text-muted-foreground">保存后自动注入 .env.local，重启剪辑台生效</p>
            </div>
          </div>

          {!draft ? (
            <div className="flex items-center justify-center gap-2 rounded-2xl border border-border/60 bg-card/60 py-16 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />加载配置中…
            </div>
          ) : (
            <>
              <Tabs value={tab} onValueChange={(value) => setTab(value as TabKey)} className="w-full">
                {/* 吸顶操作区：同步状态 + 保存注入 + 分组切换 */}
                <div className="sticky top-0 z-20 flex flex-col gap-2 rounded-2xl border border-border/60 bg-background/85 p-2.5 shadow-sm backdrop-blur-md">
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="mr-auto">
                      {dirty ? (
                        <Badge variant="warning" className="gap-1">
                          <AlertTriangle className="h-3 w-3" />
                          有未保存的修改
                        </Badge>
                      ) : (
                        <Badge variant="success" className="gap-1">
                          <CheckCircle2 className="h-3 w-3" />
                          配置已同步
                        </Badge>
                      )}
                    </div>
                    <Button variant="ai" disabled={saving || !dirty} onClick={save}>
                      {saving ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Save className="mr-1.5 h-3.5 w-3.5" />}
                      保存并注入配置
                    </Button>
                    <Button variant="outline" disabled={applying} onClick={applyEnv}>
                      {applying ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <FileKey2 className="mr-1.5 h-3.5 w-3.5" />}
                      重新生成 .env.local
                    </Button>
                    <Button variant="ghost" size="sm" onClick={toggleEnvPreview}>
                      <FileKey2 className="mr-1.5 h-3.5 w-3.5" />
                      {envPreview ? "收起预览" : "预览环境变量"}
                    </Button>
                  </div>
                  <TabsList className="h-auto w-full justify-start gap-1 overflow-x-auto rounded-xl bg-muted/40 p-1">
                    {TAB_ORDER.map((key) => {
                      const TabIcon = SECTION_META[key].icon;
                      return (
                        <TabsTrigger
                          key={key}
                          value={key}
                          className="gap-1.5 rounded-lg px-3 py-1.5 text-xs data-[state=active]:bg-card data-[state=active]:text-ai data-[state=active]:shadow-sm"
                        >
                          <TabIcon className="h-3.5 w-3.5" />
                          {SECTION_META[key].title}
                        </TabsTrigger>
                      );
                    })}
                  </TabsList>
                </div>

                {TAB_ORDER.map((key) => {
                  const PanelIcon = SECTION_META[key].icon;
                  return (
                    <TabsContent key={key} value={key} className="mt-4">
                      <div className="animate-fade-in rounded-2xl border border-border/60 bg-card/70 p-4 shadow-sm sm:p-5">
                        <div className="mb-4 flex items-start gap-3">
                          <span className="tone-ai-soft flex h-9 w-9 shrink-0 items-center justify-center rounded-xl">
                            <PanelIcon className="h-4 w-4 text-ai" />
                          </span>
                          <div className="min-w-0">
                            <h3 className="text-sm font-bold tracking-tight">{SECTION_META[key].title}</h3>
                            <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">{SECTION_META[key].desc}</p>
                          </div>
                        </div>

                        {key === "runtime" ? (
                          <div className="space-y-4">
                            <div className="grid gap-4 sm:grid-cols-2">
                              <Field label="监听 Host" mono value={draft.host} onChange={(v) => patchTop("host", v)} placeholder="127.0.0.1" />
                              <Field label="端口" mono value={String(draft.port)} onChange={(v) => patchTop("port", v)} placeholder="5199" />
                              <Field
                                label="Agent 媒体导入根目录"
                                mono
                                value={draft.agent_import_roots}
                                onChange={(v) => patchTop("agent_import_roots", v)}
                                placeholder="默认控制面工作区目录"
                              />
                              <Field
                                label="媒体目录（可选）"
                                mono
                                value={draft.media_dir}
                                onChange={(v) => patchTop("media_dir", v)}
                                placeholder="留空用剪辑台默认目录"
                              />
                            </div>
                            <div className="flex items-start justify-between gap-4 rounded-xl border border-border/60 bg-muted/30 p-3.5">
                              <div className="min-w-0">
                                <p className="text-xs font-semibold">随主程序自动启动剪辑台服务</p>
                                <p className="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
                                  关闭后剪辑台不会随主程序自动拉起，只能在本页手动启动。
                                </p>
                              </div>
                              <Switch checked={draft.enabled} onCheckedChange={(checked) => patchTop("enabled", checked)} />
                            </div>
                          </div>
                        ) : key === "image" ? (
                          <div className="space-y-4">
                            {(optionsFailed || imageOptions.length === 0) && (
                              <p className="flex flex-wrap items-center gap-1 rounded-lg border border-warning/30 bg-warning/10 p-2.5 text-[11px] text-warning">
                                <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                                {optionsFailed
                                  ? "接口列表加载失败（后端可能未重启到最新版本）。"
                                  : "暂无已启用的生图接口，请先在「全局设置 → 接口管理」中启用。"}
                                <button type="button" className="underline hover:no-underline" onClick={load}>
                                  重试加载
                                </button>
                              </p>
                            )}
                            <div className="grid gap-4 sm:grid-cols-3">
                              <SelectField
                                label="接口"
                                value={draft.image.interface_id}
                                onChange={(v) => patchSection("image", "interface_id", v)}
                                options={[
                                  { value: "", label: "自动选择（按已启用顺序）" },
                                  ...imageOptions.map((opt) => ({ value: opt.id, label: opt.name })),
                                ]}
                              />
                              <SelectField
                                label="文生图模型（无参考图）"
                                value={draft.image.txt2img_model}
                                onChange={(v) => patchSection("image", "txt2img_model", v)}
                                options={[
                                  { value: "", label: "跟随接口默认" },
                                  ...(activeImageOption?.txt2img_models ?? []).map((m) => ({ value: m, label: m })),
                                ]}
                              />
                              <SelectField
                                label="图生图模型（有参考图）"
                                value={draft.image.img2img_model}
                                onChange={(v) => patchSection("image", "img2img_model", v)}
                                options={[
                                  { value: "", label: "跟随接口默认" },
                                  ...(activeImageOption?.img2img_models ?? []).map((m) => ({ value: m, label: m })),
                                ]}
                              />
                            </div>
                            <Field
                              label="Base URL"
                              mono
                              value={draft.image.base_url}
                              onChange={(v) => patchSection("image", "base_url", v)}
                              placeholder="http://127.0.0.1:11001/api/openchatcut-bridge/v1"
                            />
                            <SectionNote>
                              桥接端按请求是否带参考图自动在 文生图 / 图生图 模型间切换；请求经本项目桥接端转发，密钥由系统自动生成注入，无需填写。
                            </SectionNote>
                          </div>
                        ) : key === "tts" ? (
                          <div className="space-y-4">
                            {(optionsFailed || ttsOptions.length === 0) && (
                              <p className="flex flex-wrap items-center gap-1 rounded-lg border border-warning/30 bg-warning/10 p-2.5 text-[11px] text-warning">
                                <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                                {optionsFailed
                                  ? "接口列表加载失败（后端可能未重启到最新版本）。"
                                  : "暂无已启用的 TTS 接口，请先在「全局设置 → 接口管理」中启用。"}
                                <button type="button" className="underline hover:no-underline" onClick={load}>
                                  重试加载
                                </button>
                              </p>
                            )}
                            <div className="grid gap-4 sm:grid-cols-2">
                              <SelectField
                                label="接口"
                                value={draft.tts.interface_id}
                                onChange={(v) => patchSection("tts", "interface_id", v)}
                                options={[
                                  { value: "", label: "自动选择（按已启用顺序）" },
                                  ...ttsOptions.map((opt) => ({ value: opt.id, label: opt.name })),
                                ]}
                              />
                              <SelectField
                                label="合成模型"
                                value={draft.tts.model}
                                onChange={(v) => patchSection("tts", "model", v)}
                                options={[
                                  { value: "", label: "跟随接口默认" },
                                  ...(activeTtsOption?.models ?? []).map((m) => ({ value: m, label: m })),
                                ]}
                              />
                            </div>
                            <SectionNote>
                              与生图共用同一桥接端 Base URL（OpenChatCut 服务端约定）；密钥由系统自动生成注入，无需填写。
                            </SectionNote>
                          </div>
                        ) : (
                          <div className="space-y-4">
                            <div className="grid gap-4 sm:grid-cols-2">
                              <Field
                                label="Base URL"
                                mono
                                value={sectionValue(key, "base_url")}
                                onChange={(v) => patchSection(key, "base_url", v)}
                                placeholder={
                                  key === "llm"
                                    ? "http://localhost:8800/v1"
                                    : "https://ark.cn-beijing.volces.com/api/v3"
                                }
                              />
                              {key === "video" && (
                                <Field
                                  label="API Key"
                                  secret
                                  mono
                                  value={sectionValue(key, "api_key")}
                                  onChange={(v) => patchSection(key, "api_key", v)}
                                  placeholder="直连第三方的真实 Key（非桥接）"
                                />
                              )}
                              <Field
                                label="模型"
                                mono
                                value={sectionValue(key, "model")}
                                onChange={(v) => patchSection(key, "model", v)}
                                placeholder={key === "llm" ? "默认 vlf-agent" : "留空 = 接口默认模型"}
                              />
                            </div>
                            {key === "llm" ? (
                              <SectionNote>
                                Provider 固定为 <code className="rounded bg-muted px-1 py-0.5 font-mono">openai</code>（OpenAI 兼容 chat 模式）；请求经本项目桥接端转发，密钥由系统自动生成注入，无需填写。
                              </SectionNote>
                            ) : (
                              <SectionNote>
                                视频生成由剪辑台直连第三方端点（不经本项目桥接），需填写该平台的真实 Key；留空则不注入该组环境变量。
                              </SectionNote>
                            )}
                          </div>
                        )}
                      </div>
                    </TabsContent>
                  );
                })}
              </Tabs>

              {envPreview && (
                <div className="animate-fade-in mt-4 overflow-hidden rounded-2xl border border-border/60 bg-card/70 shadow-sm">
                  <div className="flex flex-wrap items-center gap-2 border-b border-border/60 px-4 py-3">
                    <FileKey2 className="h-4 w-4 text-ai" />
                    <span className="text-xs font-semibold">将注入 OpenChatCut 的环境变量</span>
                    <Badge variant="secondary" className="ml-auto">
                      {Object.keys(envPreview).length} 项 · 密钥已脱敏
                    </Badge>
                  </div>
                  <div className="max-h-72 overflow-auto px-4 py-3">
                    <div className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 font-mono text-[11px] leading-relaxed">
                      {Object.entries(envPreview).map(([envKey, envValue]) => (
                        <div key={envKey} className="contents">
                          <span className="whitespace-nowrap text-ai">{envKey}</span>
                          <span className="truncate text-muted-foreground" title={envValue}>
                            {envValue || '""'}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </PageBackground>
  );
}

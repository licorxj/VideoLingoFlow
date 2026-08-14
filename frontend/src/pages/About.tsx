import { useEffect, useState } from "react";
import { marked } from "marked";
import {
  ArrowUpRight,
  BookOpen,
  CheckCircle2,
  CloudDownload,
  FileText,
  Github,
  Globe,
  Info,
  Layers,
  Loader2,
  Mail,
  Megaphone,
  MessageSquareText,
  Plug,
  Puzzle,
  QrCode,
  RefreshCw,
  Rocket,
  Share2,
  Sparkles,
  Users,
  Workflow,
  ExternalLink,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

const GITHUB_URL = "https://github.com/licorxj/VideoLingoFlow.git";

const highlights = [
  [Workflow, "节点式工作流", "拖拽即搭建：40+ 内置节点任意连线组合，保存、复用、批量重跑，把创意沉淀成可复用的流水线。"],
  [MessageSquareText, "Agent 聊天式执行", "开口即指挥：让小 Pi 帮你配置接口、创造节点、编排流程、安排任务，自然语言驱动整条生产流水线。"],
  [Puzzle, "Agent 即节点", "把智能体拖进画布，与能力节点自由连线——对话与编排两种范式无缝融合，Agent 既是助手也是流水线的一环。"],
  [Globe, "多语言出海", "翻译、配音、双语字幕一次完成，本地化到全球，让一部作品走遍世界。"],
  [Rocket, "批量生产", "批量导入、并行调度、限流重试，规模化交付，单条视频成本摊薄到接近零。"],
  [Plug, "能力无限扩展", "ASR / TTS / 生图 / 分离 / AIGC 接口域即插即用，注册一个新接口，全部工作流立刻可用。"],
  [Share2, "共享社区", "节点与工作流一键上传云端社区，一键导入他人成熟流程，复用即用，全网共享。"],
  [Users, "多人协同", "局域网 / 互联网远程协作 + 实时编辑 + 资源中心 + 审计日志，异地办公也高效。"],
] as const;

const guides = [
  ["快速开始", "从零搭建运行环境，几分钟跑起第一张工作流", "快速开始.md", Rocket],
  ["工作流编排", "掌握 DAG 画布、端口连线与节点清单，随心编排百变任务", "工作流编排指南.md", Workflow],
  ["自定义节点", "按「四件套」规范新建专属节点，扩展属于自己的能力单元", "节点新建规范指南.md", Puzzle],
  ["能力接口扩展", "注册新接口域 / Provider，能力即插即用，编排层零改动", "接口添加指南.md", Plug],
  ["多人协作", "了解权限体系、资源中心与远程协作，开启团队共创", "多人协作功能介绍.md", Users],
  ["剪辑工作台", "自动化剪辑节点与人工精修无缝衔接，机器效率 + 人的审美", "剪辑工作台联动说明.md", Layers],
  ["依赖与环境", "三大系统依赖声明与平台适配说明，环境排障必备", "依赖清单.md", BookOpen],
] as const;

type PublicInfo = {
  local_version?: string;
  update?: Record<string, any> | null;
  announcements?: Record<string, any>[];
  update_error?: string | null;
  announcement_error?: string | null;
};

function versionParts(version: string) {
  return String(version || "0").replace(/^v/i, "").split(/[.-]/).map((part) => Number(part) || 0);
}

function isNewer(remote: string, local: string) {
  const remoteParts = versionParts(remote);
  const localParts = versionParts(local);
  for (let index = 0; index < Math.max(remoteParts.length, localParts.length); index += 1) {
    if ((remoteParts[index] || 0) !== (localParts[index] || 0)) return (remoteParts[index] || 0) > (localParts[index] || 0);
  }
  return false;
}

function pickValue(source: Record<string, any> | null | undefined, keys: string[]) {
  if (!source) return "";
  for (const key of keys) {
    if (source[key] !== undefined && source[key] !== null && source[key] !== "") return String(source[key]);
  }
  return "";
}

// 公告 created_at 为 UTC ISO 字符串，展示前转成本地时间
function formatLocalTime(iso: string | undefined | null) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function GuideDialog({ guide, open, onOpenChange }: { guide: (typeof guides)[number] | null; open: boolean; onOpenChange: (open: boolean) => void }) {
  const [html, setHtml] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || !guide) return;
    let cancelled = false;
    setLoading(true);
    setHtml("");
    fetch(`/docs/${encodeURIComponent(guide[2])}`)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.text();
      })
      .then(async (text) => {
        const rendered = await marked.parse(text);
        if (!cancelled) setHtml(rendered);
      })
      .catch((error: any) => {
        if (!cancelled) setHtml(`<p>文档加载失败：${error?.message || "未知错误"}</p>`);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [guide, open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><BookOpen className="h-4 w-4 text-primary" />{guide?.[0]}</DialogTitle>
          <DialogDescription>{guide?.[1]}</DialogDescription>
        </DialogHeader>
        <div className="markdown-body max-h-[70vh] overflow-y-auto pr-2 text-sm leading-7">
          {loading && <div className="flex items-center justify-center gap-2 py-12 text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />正在读取说明</div>}
          {!loading && html && <div dangerouslySetInnerHTML={{ __html: html }} />}
        </div>
      </DialogContent>
    </Dialog>
  );
}

const heroChips = ["40+ 内置节点", "6 大能力域", "3 大协作能力", "跨平台运行"];

export default function About() {
  const [guide, setGuide] = useState<(typeof guides)[number] | null>(null);
  const [info, setInfo] = useState<PublicInfo>({ announcements: [] });
  const [checking, setChecking] = useState(false);
  const [message, setMessage] = useState("尚未检查");
  const [downloadDialogOpen, setDownloadDialogOpen] = useState(false);
  const [downloadUrl, setDownloadUrl] = useState("");
  const [downloadError, setDownloadError] = useState("");
  const [downloadFetching, setDownloadFetching] = useState(false);
  const [updateDialogOpen, setUpdateDialogOpen] = useState(false);
  const [updateStatus, setUpdateStatus] = useState<{ status: string; message: string; log: string[] }>({ status: "idle", message: "", log: [] });
  const [updatePolling, setUpdatePolling] = useState(false);
  const [announcementRefreshing, setAnnouncementRefreshing] = useState(false);
  const [qrPreview, setQrPreview] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/public-info")
      .then((response) => response.ok ? response.json() as Promise<PublicInfo> : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then((data) => setInfo(data))
      .catch(() => undefined);
  }, []);

  const checkUpdate = async () => {
    setChecking(true);
    setMessage("正在连接云端...");
    try {
      const response = await fetch("/api/public-info");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json() as PublicInfo;
      setInfo(data);
      const remoteVersion = pickValue(data.update, ["version", "latest_version", "release_version"]);
      setMessage(remoteVersion && data.local_version && isNewer(remoteVersion, data.local_version) ? `发现新版本 v${remoteVersion}` : "当前已是最新版本");
    } catch (error: any) {
      setMessage(`检查失败：${error?.message || "请检查网络连接"}`);
    } finally {
      setChecking(false);
    }
  };

  const fetchDownloadUrl = async () => {
    setDownloadFetching(true);
    setDownloadError("");
    try {
      const response = await fetch("/api/public-info/download-url");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      setDownloadUrl(data.download_url || "");
      if (!data.download_url) throw new Error("云端未返回下载地址");
      setDownloadDialogOpen(true);
    } catch (error: any) {
      setDownloadUrl("");
      setDownloadError(error?.message || "获取下载地址失败");
      setDownloadDialogOpen(true);
    } finally {
      setDownloadFetching(false);
    }
  };

  const refreshAnnouncements = async () => {
    setAnnouncementRefreshing(true);
    try {
      const response = await fetch("/api/public-info/announcements");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      setInfo((prev) => ({ ...prev, announcements: data.announcements || [], announcement_error: data.error || null }));
    } catch (error: any) {
      setInfo((prev) => ({ ...prev, announcement_error: error?.message || "刷新公告失败" }));
    } finally {
      setAnnouncementRefreshing(false);
    }
  };

  const remoteVersion = pickValue(info.update, ["version", "latest_version", "release_version"]);
  const announcements = info.announcements || [];
  const localVersion = info.local_version || "-";
  const announcementError = info.announcement_error || info.update_error || "";

  const startGithubUpdate = async () => {
    setUpdateDialogOpen(true);
    setUpdateStatus({ status: "starting", message: "正在启动更新任务...", log: [] });
    setUpdatePolling(true);
    try {
      const response = await fetch("/api/github-update/run", { method: "POST" });
      if (!response.ok) {
        const errData = await response.json().catch(() => null);
        throw new Error(errData?.detail || `HTTP ${response.status}`);
      }
      const data = await response.json();
      if (data?.ok === false) {
        setUpdateStatus({ status: "error", message: data.message || "更新任务启动失败", log: [] });
        setUpdatePolling(false);
        return;
      }
      pollUpdateStatus();
    } catch (error: any) {
      setUpdateStatus({ status: "error", message: error?.message || "启动更新任务失败", log: [] });
      setUpdatePolling(false);
    }
  };

  const pollUpdateStatus = async () => {
    try {
      const response = await fetch("/api/github-update/status");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      setUpdateStatus({ status: data.status, message: data.message, log: data.log || [] });
      if (data.status === "updating") {
        setTimeout(pollUpdateStatus, 2000);
      } else {
        setUpdatePolling(false);
      }
    } catch {
      setTimeout(pollUpdateStatus, 3000);
    }
  };

  return (
    <div className="mx-auto max-w-[77.76rem] space-y-5 stagger-children">
      {/* ===== 页头 ===== */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-2.5">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-primary to-indigo-500 text-white shadow-lg shadow-primary/20">
              <Sparkles className="h-5 w-5" />
            </span>
            <h2 className="bg-gradient-to-r from-primary via-indigo-500 to-primary bg-clip-text text-2xl font-extrabold tracking-tight text-transparent">
              关于 VideoLingoFlow
            </h2>
          </div>
          <p className="mt-1.5 text-sm text-muted-foreground">流连视听 · AI 视频创作与出海本地化工作台 —— 节点、接口、Agent，自由组合，百变任务</p>
        </div>
        <span className="animate-pulse-glow rounded-full border border-primary/30 bg-primary/10 px-3 py-1 text-xs font-semibold text-primary">v{localVersion}</span>
      </div>

      <div className="grid gap-4 lg:grid-cols-[45fr_55fr]">
        {/* ===== 品牌主卡 ===== */}
        <section className="relative overflow-hidden rounded-2xl border border-border/60 bg-card/90 p-8 shadow-lg lg:min-h-[420px]">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_15%_15%,hsl(var(--primary)/0.14),transparent_45%),radial-gradient(circle_at_88%_75%,hsl(var(--primary)/0.10),transparent_40%)]" />
          <div className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-primary/10 blur-3xl" />
          <div className="pointer-events-none absolute -bottom-28 -left-20 h-72 w-72 rounded-full bg-indigo-500/10 blur-3xl" />
          <div className="pointer-events-none absolute inset-0 opacity-[0.05] bg-[linear-gradient(hsl(var(--foreground))_1px,transparent_1px),linear-gradient(90deg,hsl(var(--foreground))_1px,transparent_1px)] bg-[size:28px_28px]" />
          <div className="relative flex h-full flex-col items-center justify-center gap-5 text-center">
            <div className="grid h-20 grid-rows-5 place-items-center">
              <img src="/vlf-long-logo.png" alt="VideoLingoFlow" className="row-span-5 row-start-1 h-20 w-auto max-w-none object-contain" />
            </div>
            <div className="flex flex-col items-center gap-1.5">
              <p className="text-xs font-semibold uppercase tracking-[0.22em] text-primary">VideoLingoFlow</p>
              <h3 className="text-xl font-extrabold">流连视听 <span className="text-base font-semibold text-muted-foreground">v{localVersion}</span></h3>
              <p className="text-sm text-muted-foreground">出品方：晴沐智坊</p>
            </div>
            <div className="flex flex-wrap items-center justify-center gap-2">
              {heroChips.map((chip) => (
                <span key={chip} className="rounded-full border border-border/60 bg-background/60 px-3 py-1 text-[11px] font-medium text-muted-foreground backdrop-blur">{chip}</span>
              ))}
            </div>
            <div className="flex flex-col items-center justify-center gap-3">
              <div className="flex flex-wrap items-center justify-center gap-3">
                <Button onClick={checkUpdate} disabled={checking}><RefreshCw className={`mr-2 h-4 w-4 ${checking ? "animate-spin" : ""}`} />检查版本更新</Button>
              </div>
              <span className="text-xs text-muted-foreground">{message}</span>
            </div>
            {remoteVersion && localVersion !== "-" && isNewer(remoteVersion, localVersion) && <div className="flex flex-wrap items-center justify-center gap-3 rounded-xl border border-primary/20 bg-primary/5 p-3 text-sm"><CheckCircle2 className="h-4 w-4 text-primary" /><span>云端版本 v{remoteVersion} 已发布</span><Button size="sm" variant="outline" onClick={fetchDownloadUrl} disabled={downloadFetching}><CloudDownload className="mr-2 h-4 w-4" />{downloadFetching ? "获取中..." : "获取下载地址"}</Button></div>}
          </div>
        </section>

        {/* ===== 软件亮点 ===== */}
        <section className="rounded-2xl border border-border/60 bg-card/90 p-6 shadow-lg lg:min-h-[300px]">
          <div className="mb-5 flex items-center gap-3">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-primary to-indigo-500 text-white shadow-md shadow-primary/20"><Sparkles className="h-4 w-4" /></span>
            <div>
              <h3 className="font-bold">软件亮点</h3>
              <p className="text-[11px] text-muted-foreground">把创意变成流水线，把流水线变成资产</p>
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {highlights.map(([Icon, title, text]) => (
              <div key={title} className="group flex gap-3 rounded-xl border border-border/50 bg-card p-3.5 transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-lg">
                <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-primary/85 to-indigo-500/85 text-white shadow-md shadow-primary/20 transition-transform group-hover:scale-105"><Icon className="h-5 w-5" /></div>
                <div>
                  <p className="text-sm font-bold">{title}</p>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">{text}</p>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="grid gap-4 lg:grid-cols-[55fr_45fr]">
        {/* ===== 配置说明 ===== */}
        <section className="rounded-2xl border border-border/60 bg-card/90 p-6 shadow-lg lg:min-h-[300px]">
          <div className="mb-5 flex items-center gap-3">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-indigo-500 to-violet-500 text-white shadow-md shadow-indigo-500/20"><FileText className="h-4 w-4" /></span>
            <div>
              <h3 className="font-bold">配置说明</h3>
              <p className="text-[11px] text-muted-foreground">从入门到进阶，动手之前先读它</p>
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {guides.map(([title, desc, file, Icon]) => (
              <button key={file} type="button" onClick={() => setGuide([title, desc, file, Icon] as (typeof guides)[number])} className="group flex items-start justify-between gap-3 rounded-xl border border-border/50 bg-card p-4 text-left transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-lg">
                <span className="flex items-start gap-3">
                  <span className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-accent text-primary transition-colors group-hover:bg-primary group-hover:text-primary-foreground"><Icon className="h-4 w-4" /></span>
                  <span>
                    <span className="block text-sm font-semibold">{title}</span>
                    <span className="mt-1 block text-xs leading-5 text-muted-foreground">{desc}</span>
                  </span>
                </span>
                <ArrowUpRight className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
              </button>
            ))}
          </div>
        </section>

        {/* ===== 项目公告 ===== */}
        <section className="rounded-2xl border border-border/60 bg-card/90 p-6 shadow-lg lg:min-h-[390px]">
          <div className="mb-5 flex items-center justify-between gap-2">
            <div className="flex items-center gap-3">
              <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-amber-500 to-orange-500 text-white shadow-md shadow-amber-500/20"><Megaphone className="h-4 w-4" /></span>
              <h3 className="font-bold">项目公告</h3>
            </div>
            <Button size="icon" variant="ghost" onClick={refreshAnnouncements} disabled={announcementRefreshing} title="刷新公告"><RefreshCw className={`h-4 w-4 ${announcementRefreshing ? "animate-spin" : ""}`} /></Button>
          </div>
          <div className="space-y-3">
            {announcements.length ? announcements.slice(0, 4).map((item, index) => (
              <div key={index} className="rounded-r-lg border-l-2 border-primary/60 bg-accent/30 py-2.5 pl-3 pr-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-sm font-semibold">{pickValue(item, ["title", "name"]) || "项目公告"}</p>
                  {formatLocalTime(pickValue(item, ["created_at", "publish_at"])) && <span className="shrink-0 text-[10px] text-muted-foreground">{formatLocalTime(pickValue(item, ["created_at", "publish_at"]))}</span>}
                </div>
                <p className="mt-1 line-clamp-2 text-xs leading-5 text-blue-600 dark:text-blue-400">{pickValue(item, ["content", "description", "body"])}</p>
              </div>
            )) : announcementError ? <p className="text-sm text-destructive">公告获取失败：{announcementError}</p> : <p className="text-sm leading-6 text-muted-foreground">暂无公告。</p>}
          </div>
          <div className="mt-6 flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => window.open(GITHUB_URL, "_blank", "noopener,noreferrer")}><Github className="mr-2 h-4 w-4" />项目 GitHub</Button>
            <Button size="sm" variant="outline" onClick={startGithubUpdate} disabled={updatePolling}><Github className="mr-2 h-4 w-4" />{updatePolling ? "更新中..." : "从GitHub更新"}</Button>
          </div>
        </section>
      </div>

      <div className="grid gap-4">
        {/* ===== 联系我们 ===== */}
        <section className="rounded-2xl border border-border/60 bg-card/90 p-6 shadow-lg">
          <div className="mb-5 flex items-center gap-3">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-emerald-500 to-teal-500 text-white shadow-md shadow-emerald-500/20"><QrCode className="h-4 w-4" /></span>
            <div>
              <h3 className="font-bold">联系我们</h3>
              <p className="text-[11px] text-muted-foreground">一起碰撞灵感，或把繁琐任务交给我们</p>
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-border/60 bg-card p-4 text-center transition-all hover:border-primary/40 hover:shadow-lg">
              <Button variant="outline" size="sm" onClick={() => window.open("https://www.licorxj.online/home", "_blank", "noopener,noreferrer")}><ExternalLink className="mr-2 h-4 w-4" />访问晴沐智坊</Button>
              <p className="text-xs text-muted-foreground">官方网站 🌐</p>
            </div>
            <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-border/60 bg-card p-4 text-center transition-all hover:border-primary/40 hover:shadow-lg">
              <button type="button" onClick={() => setQrPreview("/imge/qqun.png")} title="点击放大企鹅群二维码" className="transition-transform hover:scale-105">
                <img src="/imge/qqun.png" alt="企鹅群二维码" className="h-24 w-24 rounded-lg border border-border object-contain" />
              </button>
              <p className="text-xs text-muted-foreground">企鹅群 🐧</p>
            </div>
            <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-border/60 bg-card p-4 text-center transition-all hover:border-primary/40 hover:shadow-lg">
              <button type="button" onClick={() => setQrPreview("/imge/licor.png")} title="点击放大开发者微信二维码" className="transition-transform hover:scale-105">
                <img src="/imge/licor.png" alt="开发者微信二维码" className="h-24 w-24 rounded-lg border border-border object-contain" />
              </button>
              <p className="text-xs text-muted-foreground">开发者微信 💬</p>
            </div>
            <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-border/60 bg-card p-4 text-center transition-all hover:border-primary/40 hover:shadow-lg">
              <a href="mailto:727909969@qq.com" className="inline-flex items-center gap-2 text-sm font-medium text-primary hover:underline"><Mail className="h-4 w-4" />727909969@qq.com</a>
              <p className="text-xs text-muted-foreground">企业邮箱 📧</p>
            </div>
          </div>
          <p className="mt-6 text-center text-lg font-bold leading-7 text-muted-foreground">温馨提示：除了在分享社区找工作流，你也可以找我定制工作流哦～ 😉 甚至可以把这些无聊的任务甩给我们来包办！🚀✨</p>
        </section>
      </div>
      <GuideDialog guide={guide} open={Boolean(guide)} onOpenChange={(open) => !open && setGuide(null)} />
      <Dialog open={downloadDialogOpen} onOpenChange={setDownloadDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><CloudDownload className="h-4 w-4 text-primary" />下载地址</DialogTitle>
            <DialogDescription>{downloadUrl ? `最新版本 v${remoteVersion} 的下载地址如下` : "获取下载地址失败"}</DialogDescription>
          </DialogHeader>
          {downloadUrl ? <div className="flex flex-col gap-3">
            <div className="break-all rounded-lg border border-border bg-accent/50 p-3 text-sm leading-6">{downloadUrl}</div>
            <Button onClick={() => window.open(downloadUrl, "_blank", "noopener,noreferrer")}><CloudDownload className="mr-2 h-4 w-4" />打开下载地址</Button>
          </div> : <p className="text-sm text-destructive">{downloadError || "请稍后重试"}</p>}
        </DialogContent>
      </Dialog>
      <Dialog open={updateDialogOpen} onOpenChange={(open) => !open && !updatePolling && setUpdateDialogOpen(false)}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><Github className="h-4 w-4 text-primary" />从 GitHub 更新</DialogTitle>
            <DialogDescription>拉取 GitHub 最新代码并执行项目安装脚本</DialogDescription>
          </DialogHeader>
          <div className="flex items-start gap-2 text-sm">
            {updateStatus.status === "updating" || updateStatus.status === "starting"
              ? <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-primary" />
              : updateStatus.status === "success"
                ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-green-600" />
                : updateStatus.status === "error"
                  ? <span className="mt-0.5 text-red-600">✕</span>
                  : <Info className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />}
            <span className={updateStatus.status === "error" ? "text-red-600" : ""}>{updateStatus.message || "正在准备..."}</span>
          </div>
          <pre className="max-h-[50vh] overflow-y-auto rounded-lg border border-border bg-accent/40 p-3 text-xs leading-5">
            {updateStatus.log.length ? updateStatus.log.join("\n") : "暂无输出..."}
          </pre>
          {updateStatus.status !== "updating" && updateStatus.status !== "starting" && (
            <Button variant="outline" onClick={() => setUpdateDialogOpen(false)}>关闭</Button>
          )}
        </DialogContent>
      </Dialog>
      <Dialog open={Boolean(qrPreview)} onOpenChange={(open) => !open && setQrPreview(null)}>
        <DialogContent className="max-w-xs">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><QrCode className="h-4 w-4 text-primary" />扫码添加</DialogTitle>
          </DialogHeader>
          <img src={qrPreview || ""} alt="二维码" className="mx-auto w-full max-w-[240px] rounded-lg border border-border object-contain" />
        </DialogContent>
      </Dialog>
    </div>
  );
}

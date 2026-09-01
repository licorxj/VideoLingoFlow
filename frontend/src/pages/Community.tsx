import { useCallback, useEffect, useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import {
  getCommunityBaseUrl,
  listResources, likeResource, unlikeResource, downloadResource, deleteCommunityResource,
  workerPreviewUrl, blobToFile,
  type CommunityResource, type ResourceListResult, type CommunityUser,
} from "@/api/community";
import { getDeviceId } from "@/lib/deviceId";
import { CATEGORIES } from "@/lib/workflowTypes";
import { useAlert } from "@/components/ui/AlertProvider";
import { useSubscriptionStore } from "@/stores/subscriptionStore";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { validateNodeTypePackage, importNodeType, type NodePackageValidationResult } from "@/api/nodeTypes";
import MyResourcesDialog from "@/components/community/MyResourcesDialog";
import WorkflowImportPanel from "@/components/community/WorkflowImportPanel";
import IdentityDialog from "@/components/community/IdentityDialog";
import { PageBackground } from "@/components/shared/PageBackground";
import {
  Store, Search, Heart, Download, Loader2, Box, Workflow as WorkflowIcon,
  User, Tag, Clock, CheckCircle2, XCircle, AlertCircle, Package, AlertTriangle, ShieldAlert,
  UserRound, ShieldCheck, Trash2, RefreshCw, Maximize,
} from "lucide-react";

const WORKFLOW_CATEGORIES = ["通用工作流", "视频处理", "字幕处理", "AI 处理", "多平台发布", "工具工作流"];

/* 身份与管理员登录的本地持久化 */
const USER_KEY = "vl_community_user";
const ADMIN_KEY = "vl_community_admin_token";
function loadStoredUser(): CommunityUser | null {
  try {
    const s = localStorage.getItem(USER_KEY);
    return s ? JSON.parse(s) : null;
  } catch {
    return null;
  }
}
function loadStoredAdminToken(): string {
  try {
    return localStorage.getItem(ADMIN_KEY) || "";
  } catch {
    return "";
  }
}

const TYPE_META: Record<string, { label: string; color: string; icon: any }> = {
  node: { label: "节点", color: "#8b5cf6", icon: Box },
  workflow: { label: "工作流", color: "#6366f1", icon: WorkflowIcon },
};

type SortKey = "new" | "likes" | "downloads";
type TabKey = "all" | "node" | "workflow";

export default function Community() {
  const { alert } = useAlert();
  const subscriptionStatus = useSubscriptionStore((state) => state.status);
  const fetchSubscriptionStatus = useSubscriptionStore((state) => state.fetchStatus);
  const deviceId = useMemo(() => getDeviceId(), []);
  const baseUrl = useMemo(() => getCommunityBaseUrl(), []);

  const [tab, setTab] = useState<TabKey>("all");
  const [category, setCategory] = useState("");
  const [q, setQ] = useState("");
  const [qInput, setQInput] = useState("");
  const [sort, setSort] = useState<SortKey>("new");
  const [page, setPage] = useState(1);
  const [list, setList] = useState<ResourceListResult | null>(null);
  const [loading, setLoading] = useState(false);

  const [detail, setDetail] = useState<CommunityResource | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [likingId, setLikingId] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [importState, setImportState] = useState<{
    phase: "validate" | "ready" | "importing" | "done";
    validation: NodePackageValidationResult | null;
    file: File | null;
    error: string;
  }>({ phase: "validate", validation: null, file: null, error: "" });
  const [myResOpen, setMyResOpen] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [renameMode, setRenameMode] = useState(false);
  const [renameTo, setRenameTo] = useState("");
  /* 身份与管理员登录 */
  const [user, setUser] = useState<CommunityUser | null>(() => loadStoredUser());
  const [adminToken, setAdminToken] = useState<string>(() => loadStoredAdminToken());
  const [identityOpen, setIdentityOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const isSubscribed = subscriptionStatus?.user_type === "subscribed";

  const requireSubscription = () => {
    if (isSubscribed) return true;
    alert("社区资源下载和安装仅对订阅用户开放，请先订阅后再使用。", "warning");
    return false;
  };

  useEffect(() => {
    if (!subscriptionStatus) fetchSubscriptionStatus();
  }, [fetchSubscriptionStatus, subscriptionStatus]);

  const categories = useMemo(() => {
    if (tab === "node") return Object.entries(CATEGORIES).map(([value, meta]) => ({ value, label: meta.label }));
    if (tab === "workflow") return WORKFLOW_CATEGORIES.map((value) => ({ value, label: value }));
    return [];
  }, [tab]);

  const fetchList = useCallback(async (p: number, append: boolean) => {
    if (!baseUrl) return;
    setLoading(true);
    try {
      const res = await listResources(baseUrl, {
        type: tab === "all" ? "" : tab,
        category: category || undefined,
        q: q || undefined,
        page: p,
        pageSize: 12,
        sort,
        deviceId,
      });
      setList((prev) => {
        if (!prev || !append) return res;
        return { ...res, items: [...prev.items, ...res.items] };
      });
    } catch (e: any) {
      alert(e?.message || "加载失败", "error");
    } finally {
      setLoading(false);
    }
  }, [baseUrl, tab, category, q, sort, deviceId, alert]);

  useEffect(() => {
    setPage(1);
    setList(null);
    if (baseUrl) fetchList(1, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseUrl, tab, category, sort]);

  const loadMore = () => {
    const next = page + 1;
    setPage(next);
    fetchList(next, true);
  };

  const handleRefresh = () => {
    setPage(1);
    setList(null);
    fetchList(1, false);
  };

  /* ---------- 点赞 ---------- */
  const applyLike = useCallback((id: string, likeCount: number, liked: boolean) => {
    setList((prev) => prev ? {
      ...prev,
      items: prev.items.map((it) => it.id === id ? { ...it, likeCount, liked } : it),
    } : prev);
    setDetail((prev) => prev && prev.id === id ? { ...prev, likeCount, liked } : prev);
  }, []);

  const handleLike = async (res: CommunityResource) => {
    if (!baseUrl || likingId) return;
    setLikingId(res.id);
    try {
      const next = res.liked
        ? await unlikeResource(baseUrl, res.id, deviceId)
        : await likeResource(baseUrl, res.id, deviceId);
      applyLike(res.id, next.likeCount, next.liked);
    } catch (e: any) {
      alert(e?.message || "操作失败", "error");
    } finally {
      setLikingId(null);
    }
  };

  /* ---------- 详情 ---------- */
  const openDetail = async (res: CommunityResource) => {
    setDetail(res);
    if (!baseUrl) return;
    setDetailLoading(true);
    try {
      const full = await fetch(`${baseUrl.replace(/\/+$/, "")}/api/resources/${res.id}?deviceId=${encodeURIComponent(deviceId)}`);
      if (full.ok) setDetail(await full.json());
    } catch { /* 使用列表数据 */ } finally {
      setDetailLoading(false);
    }
  };

  /* ---------- 节点导入 ---------- */
  const startNodeImport = async () => {
    if (!requireSubscription()) return;
    if (!baseUrl || !detail) return;
    setImporting(true);
    setRenameMode(false);
    setRenameTo("");
    setImportState({ phase: "validate", validation: null, file: null, error: "" });
    try {
      const blob = await downloadResource(baseUrl, detail.id);
      const file = blobToFile(blob, `node_${detail.name}.zip`);
      const validation = await validateNodeTypePackage(file);
      if (!validation.valid) {
        setImportState({ phase: "ready", validation, file, error: (validation.errors || []).join("；") });
        return;
      }
      setImportState({ phase: "ready", validation, file, error: "" });
    } catch (e: any) {
      setImportState({ phase: "ready", validation: null, file: null, error: e?.message || "下载或校验失败" });
    } finally {
      setImporting(false);
    }
  };

  const toggleRenameMode = (on: boolean) => {
    setRenameMode(on);
    if (on) {
      const base = importState.validation?.node?.id || detail?.sourceId || "node";
      setRenameTo(`${base}_import`);
    }
  };

  const confirmNodeImport = async () => {
    if (!requireSubscription()) return;
    const { file, validation } = importState;
    if (!file) return;
    if (renameMode) {
      const tid = renameTo.trim();
      const origId = validation?.node?.id || detail?.sourceId || "";
      if (!tid) {
        setImportState((s) => ({ ...s, error: "请输入新的节点 id" }));
        return;
      }
      if (tid === origId) {
        setImportState((s) => ({ ...s, error: "新 id 不能与原节点 id 相同" }));
        return;
      }
      setImportState((s) => ({ ...s, phase: "importing", error: "" }));
      try {
        await importNodeType(file, { renameTo: tid });
        setImportState((s) => ({ ...s, phase: "done" }));
        alert("节点已改名导入（新 id: " + tid + "）", "success");
      } catch (e: any) {
        setImportState((s) => ({ ...s, phase: "ready", error: e?.message || "改名导入失败" }));
      }
      return;
    }
    setImportState((s) => ({ ...s, phase: "importing", error: "" }));
    try {
      await importNodeType(file, { allowOverwrite: true, createBackup: true });
      setImportState((s) => ({ ...s, phase: "done" }));
      alert("节点导入成功", "success");
    } catch (e: any) {
      setImportState((s) => ({ ...s, phase: "ready", error: e?.message || "导入失败" }));
    }
  };

  /* ---------- 工作流导入（由 WorkflowImportPanel 完成分析与安装） ---------- */
  const startWorkflowImport = async () => {
    if (!requireSubscription()) return;
    if (!baseUrl || !detail) return;
    setRenameMode(false);
    setRenameTo("");
    setImportState({ phase: "ready", validation: null, file: null, error: "" });
  };

  const handleWorkflowImportSuccess = (msg: string) => {
    setImportState({ phase: "done", validation: null, file: null, error: "" });
    alert(msg, "success");
  };

  /* ---------- 仅下载（不导入） ---------- */
  const handleDownloadOnly = async () => {
    if (!requireSubscription()) return;
    if (!baseUrl || !detail) return;
    setDownloading(true);
    try {
      const blob = await downloadResource(baseUrl, detail.id);
      const filename = `社区_${detail.name}.zip`.replace(/[\\/:*?"<>|]/g, "_");
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
      alert("文件已下载，可自行进行安全检测", "success");
    } catch (e: any) {
      alert(e?.message || "下载失败", "error");
    } finally {
      setDownloading(false);
    }
  };

  /* ---------- 身份注册 / 管理员登录（localStorage 持久化） ---------- */
  const handleRegistered = (u: CommunityUser) => {
    setUser(u);
    try { localStorage.setItem(USER_KEY, JSON.stringify(u)); } catch { /* 忽略 */ }
  };
  const handleAdminChange = (token: string) => {
    setAdminToken(token);
    try {
      if (token) localStorage.setItem(ADMIN_KEY, token);
      else localStorage.removeItem(ADMIN_KEY);
    } catch { /* 忽略 */ }
  };

  /* ---------- 管理员删除资源 ---------- */
  const handleAdminDelete = async (res: CommunityResource) => {
    if (!adminToken || !baseUrl) return;
    if (!window.confirm(`确认删除资源「${res.name}」？删除后不可恢复。`)) return;
    setDeleting(true);
    try {
      await deleteCommunityResource(baseUrl, res.id, adminToken);
      alert("资源已删除", "success");
      setDetail(null);
      setList(null);
      fetchList(1, false);
    } catch (e: any) {
      const msg = String(e?.message || "删除失败");
      // 管理员令牌失效（常见于社区 Worker 重新部署 / 更换 ADMIN_TOKEN 后，
      // 本地 localStorage 仍缓存旧令牌，页面显示「管理员」但实际已不匹配）。
      if (adminToken && /admin token/i.test(msg)) {
        handleAdminChange(""); // 清除失效的本地管理员状态
        alert("管理密钥已失效，已清除本地管理员状态。请重新在「设置身份」中登录管理员后再删除。", "error");
      } else {
        alert(msg, "error");
      }
    } finally {
      setDeleting(false);
    }
  };

  /* ---------- 渲染 ---------- */
  return (
    <PageBackground tone="collab" className="h-full flex flex-col min-h-0">
      {/* 顶部 */}
      <div className="flex items-center gap-3 px-5 py-3 border-b border-border/60 flex-shrink-0">
        <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-ai to-primary flex items-center justify-center shadow-lg shadow-ai/20">
          <Store className="w-5 h-5 text-white" />
        </div>
        <div>
          <h2 className="text-base font-extrabold tracking-tight flex items-center gap-2">共享社区</h2>
          <p className="text-xs text-muted-foreground">浏览云端节点与工作流，一键点赞、下载导入,依托cloudflare,需要开全球网络.</p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => setIdentityOpen(true)}>
            <UserRound className="w-3.5 h-3.5 mr-1.5" /> {user ? user.name : "设置身份"}
          </Button>
          {adminToken && (
            <span className="flex items-center gap-1 text-[11px] px-2 py-1 rounded-md border border-ai/30 text-ai bg-ai/10">
              <ShieldCheck className="w-3 h-3" /> 管理员
            </span>
          )}
          <Button variant="outline" size="sm" onClick={() => setMyResOpen(true)}>
            <Package className="w-3.5 h-3.5 mr-1.5" /> 分享我的资源
          </Button>
          <span className={cn(
            "text-[11px] px-2 py-1 rounded-md border",
            baseUrl ? "text-success bg-success/10 border-success/25" : "text-warning bg-warning/10 border-warning/25"
          )}>
            {baseUrl ? "已连接" : "未配置"}
          </span>
        </div>
      </div>

      {!baseUrl ? (
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="max-w-md w-full text-center space-y-4">
            <AlertCircle className="w-12 h-12 text-warning mx-auto" />
            <div className="text-sm font-semibold">共享社区尚未启用</div>
            <p className="text-xs text-muted-foreground leading-relaxed">
              本构建未包含社区服务地址。部署时在
              <code className="font-mono">frontend/.env</code> 中设置
              <code className="font-mono">VITE_COMMUNITY_API_URL</code>（指向已部署的 Cloudflare Worker）
              后重新构建即可，分发给用户后无需任何配置。
            </p>
          </div>
        </div>
      ) : (
        <>
          {/* 工具栏 */}
          <div className="px-5 py-3 flex flex-wrap items-center gap-2 border-b border-border/60 flex-shrink-0">
            <div className="flex rounded-lg bg-muted p-1">
              {([["all", "全部"], ["node", "节点"], ["workflow", "工作流"]] as [TabKey, string][]).map(([key, label]) => (
                <button
                  key={key}
                  onClick={() => { setTab(key); setCategory(""); }}
                  className={cn(
                    "px-3 py-1.5 text-xs font-medium rounded-md transition-colors",
                    tab === key ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  {label}
                </button>
              ))}
            </div>

            {categories.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5">
                <button
                  onClick={() => setCategory("")}
                  className={cn(
                    "px-2.5 py-1 text-[11px] rounded-full border transition-colors",
                    !category ? "border-primary/50 bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground"
                  )}
                >全部</button>
                {categories.map((c) => (
                  <button
                    key={c.value}
                    onClick={() => setCategory(category === c.value ? "" : c.value)}
                    className={cn(
                      "px-2.5 py-1 text-[11px] rounded-full border transition-colors",
                      category === c.value ? "border-primary/50 bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground"
                    )}
                  >{c.label}</button>
                ))}
              </div>
            )}

            <div className="ml-auto flex items-center gap-2">
              <Button
                variant="ghost"
                size="icon"
                onClick={handleRefresh}
                disabled={loading}
                title="刷新列表"
                className="h-8 w-8"
              >
                <RefreshCw className={cn("w-3.5 h-3.5", loading && "animate-spin")} />
              </Button>
              <form
                className="flex items-center gap-1.5 rounded-lg border border-border bg-background px-2.5 py-1.5"
                onSubmit={(e) => { e.preventDefault(); setQ(qInput); }}
              >
                <Search className="w-3.5 h-3.5 text-muted-foreground/60" />
                <input
                  value={qInput}
                  onChange={(e) => setQInput(e.target.value)}
                  placeholder="搜索名称/描述/作者…"
                  className="bg-transparent text-xs outline-none placeholder:text-muted-foreground/40 w-40"
                />
              </form>
              <Select value={sort} onValueChange={(v) => setSort(v as SortKey)}>
                <SelectTrigger className="w-[110px] h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="new">最新发布</SelectItem>
                  <SelectItem value="likes">点赞最多</SelectItem>
                  <SelectItem value="downloads">下载最多</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* 列表 */}
          <div className="flex-1 overflow-y-auto p-5">
            {list && list.items.length > 0 ? (
              <>
                <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))" }}>
                  {list.items.map((res) => <ResourceCard key={res.id} res={res} baseUrl={baseUrl} liking={likingId === res.id} onLike={handleLike} onOpen={openDetail} />)}
                </div>
                {list.items.length < list.total && (
                  <div className="flex justify-center mt-5">
                    <Button variant="outline" size="sm" onClick={loadMore} disabled={loading}>
                      {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
                      加载更多（{list.items.length}/{list.total}）
                    </Button>
                  </div>
                )}
              </>
            ) : loading ? (
              <div className="flex justify-center py-20"><Loader2 className="w-6 h-6 animate-spin text-primary" /></div>
            ) : (
              <div className="text-center py-20 text-sm text-muted-foreground">暂无资源</div>
            )}
          </div>
        </>
      )}

      {/* 详情弹窗 */}
      <DetailDialog
        detail={detail}
        baseUrl={baseUrl}
        loading={detailLoading}
        liking={likingId === detail?.id}
        downloading={downloading}
        onClose={() => setDetail(null)}
        onLike={handleLike}
        onDownloadOnly={handleDownloadOnly}
        importing={importing}
        importState={importState}
        renameMode={renameMode}
        renameTo={renameTo}
        onRenameModeChange={toggleRenameMode}
        onRenameToChange={setRenameTo}
        onStartNodeImport={startNodeImport}
        onConfirmNodeImport={confirmNodeImport}
        onStartWorkflowImport={startWorkflowImport}
        onWorkflowSuccess={handleWorkflowImportSuccess}
        onResetImport={() => setImportState({ phase: "validate", validation: null, file: null, error: "" })}
        adminToken={adminToken}
        deleting={deleting}
        onAdminDelete={handleAdminDelete}
      />

      {/* 身份设置 + 管理员登录 */}
      <IdentityDialog
        open={identityOpen}
        baseUrl={baseUrl}
        user={user}
        adminToken={adminToken}
        onClose={() => setIdentityOpen(false)}
        onRegistered={handleRegistered}
        onAdminChange={handleAdminChange}
      />

      {/* 我的资源（打包入口） */}
      <MyResourcesDialog open={myResOpen} onClose={() => setMyResOpen(false)} user={user} />
    </PageBackground>
  );
}

/* ================================================================ */
/* 卡片                                                               */
/* ================================================================ */
function ResourceCard({ res, baseUrl, liking, onLike, onOpen }: {
  res: CommunityResource;
  baseUrl: string;
  liking: boolean;
  onLike: (r: CommunityResource) => void;
  onOpen: (r: CommunityResource) => void;
}) {
  const meta = TYPE_META[res.type] || TYPE_META.node;
  const Icon = meta.icon;
  return (
    <div
      className="group rounded-2xl border border-border/60 bg-card/70 overflow-hidden hover:shadow-lg hover:shadow-primary/5 hover:border-primary/30 transition-all duration-200 cursor-pointer"
      onClick={() => onOpen(res)}
    >
      <div className="relative aspect-video bg-muted/40 overflow-hidden">
        <img
          src={workerPreviewUrl(baseUrl, res)}
          alt={res.name}
          loading="lazy"
          className="w-full h-full object-cover"
          onError={(e) => { (e.target as HTMLImageElement).style.opacity = "0.3"; }}
        />
        <span
          className="absolute top-2 left-2 flex items-center gap-1 text-[10px] font-semibold text-white px-2 py-0.5 rounded-md"
          style={{ backgroundColor: meta.color + "cc" }}
        >
          <Icon className="w-3 h-3" /> {meta.label}
        </span>
        {res.scanWarnings && res.scanWarnings.length > 0 && (
          <span
            className="absolute top-2 right-2 flex items-center gap-1 text-[10px] font-semibold text-white px-2 py-0.5 rounded-md bg-warning"
            title={"云端安全扫描提醒：" + res.scanWarnings.join("、")}
          >
            <AlertTriangle className="w-3 h-3" /> 待确认
          </span>
        )}
      </div>
      <div className="p-3 space-y-1.5">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <div className="text-sm font-bold truncate">{res.name}</div>
            <div className="text-xs text-muted-foreground line-clamp-1">{res.description || "暂无描述"}</div>
          </div>
        </div>
        <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
          {res.author && <span className="flex items-center gap-1 min-w-0"><User className="w-3 h-3 flex-shrink-0" /><span className="truncate">{res.author}</span></span>}
          {res.category && <span className="px-1.5 py-0.5 rounded bg-primary/10 text-primary flex-shrink-0">{res.category}</span>}
          <span className="ml-auto flex items-center gap-2 flex-shrink-0">
            <span className="flex items-center gap-0.5" title="下载"><Download className="w-3 h-3" />{res.downloads}</span>
          </span>
        </div>
        <div className="flex items-center justify-between pt-1 border-t border-border/40">
          <button
            onClick={(e) => { e.stopPropagation(); onLike(res); }}
            disabled={liking}
            className={cn(
              "flex items-center gap-1 text-xs font-medium rounded-md px-2 py-1 transition-colors",
              res.liked ? "text-destructive bg-destructive/10" : "text-muted-foreground hover:text-destructive hover:bg-destructive/5"
            )}
          >
            <Heart className={cn("w-3.5 h-3.5", res.liked && "fill-current")} />
            {res.likeCount}
          </button>
          <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
            <Clock className="w-3 h-3" />{formatDate(res.createdAt)}
          </span>
        </div>
      </div>
    </div>
  );
}

function formatDate(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.getFullYear() + "/" + (d.getMonth() + 1) + "/" + d.getDate();
}

/* ================================================================ */
/* 详情弹窗                                                           */
/* ================================================================ */
function DetailDialog(props: {
  detail: CommunityResource | null;
  baseUrl: string;
  loading: boolean;
  liking: boolean;
  downloading: boolean;
  onClose: () => void;
  onLike: (r: CommunityResource) => void;
  onDownloadOnly: () => void;
  importing: boolean;
  importState: { phase: "validate" | "ready" | "importing" | "done"; validation: NodePackageValidationResult | null; file: File | null; error: string };
  renameMode: boolean;
  renameTo: string;
  onRenameModeChange: (v: boolean) => void;
  onRenameToChange: (v: string) => void;
  onStartNodeImport: () => void;
  onConfirmNodeImport: () => void;
  onStartWorkflowImport: () => void;
  onWorkflowSuccess: (msg: string) => void;
  onResetImport: () => void;
  adminToken: string;
  deleting: boolean;
  onAdminDelete: (r: CommunityResource) => void;
}) {
  const { detail, baseUrl } = props;
  const meta = detail ? TYPE_META[detail.type] || TYPE_META.node : null;
  const Icon = meta?.icon;

  const isNode = detail?.type === "node";
  const vc = props.importState.validation?.versionComparison;
  const ready = props.importState.phase === "ready" || props.importState.phase === "importing";

  return (
    <Dialog open={!!detail} onOpenChange={(o) => { if (!o) { props.onClose(); props.onResetImport(); } }}>
      <DialogContent className="max-w-lg">
        {detail && meta && (
          <>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <Icon className="w-4 h-4" style={{ color: meta.color }} />
                {detail.name}
                <span className="text-[10px] font-medium px-1.5 py-0.5 rounded" style={{ backgroundColor: meta.color + "20", color: meta.color }}>
                  {meta.label} · v{detail.version}
                </span>
              </DialogTitle>
              <DialogDescription>{detail.description || "暂无描述"}</DialogDescription>
            </DialogHeader>

            <div className="relative rounded-xl overflow-hidden border border-border bg-muted/40">
              <img src={workerPreviewUrl(baseUrl, detail)} alt={detail.name} className="w-full aspect-video object-cover" />
              <button
                onClick={() => window.open(workerPreviewUrl(baseUrl, detail), "_blank")}
                title="全屏打开预览图"
                className="absolute top-2 right-2 flex items-center gap-1 text-[11px] font-medium text-white bg-black/50 hover:bg-black/70 rounded-md px-2 py-1 backdrop-blur transition-colors"
              >
                <Maximize className="w-3.5 h-3.5" /> 全屏
              </button>
            </div>

            <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
              {detail.author && <span className="flex items-center gap-1"><User className="w-3 h-3" />{detail.author}</span>}
              {detail.category && <span className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-primary/10 text-primary"><Tag className="w-3 h-3" />{detail.category}</span>}
              {detail.tags.map((t) => (
                <span key={t} className="px-1.5 py-0.5 rounded bg-muted">{t}</span>
              ))}
              <span className="ml-auto flex items-center gap-1"><Download className="w-3 h-3" />{detail.downloads} 下载</span>
            </div>

            {props.loading && <div className="text-xs text-muted-foreground flex items-center gap-1.5"><Loader2 className="w-3 h-3 animate-spin" />加载详情…</div>}

            {/* 云端安全扫描告警 */}
            {detail.scanWarnings && detail.scanWarnings.length > 0 && (
              <div className="flex items-start gap-2 text-xs text-warning bg-warning/10 border border-warning/25 rounded-lg px-3 py-2">
                <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                <div>
                  <div className="font-semibold">云端安全扫描提醒</div>
                  <div className="mt-0.5">该资源包含以下可疑代码模式，导入前请确认来源可信：{detail.scanWarnings.join("、")}</div>
                </div>
              </div>
            )}

            {/* 导入区 */}
            <div className="border-t border-border/50 pt-3 space-y-2.5">
              {/* 安全免责声明 */}
              <div className="flex items-start gap-2 text-xs text-warning bg-warning/10 border border-warning/25 rounded-lg px-3 py-2">
                <ShieldAlert className="w-4 h-4 flex-shrink-0 mt-0.5" />
                <div>
                  <div className="font-semibold">安全提示</div>
                  <div className="mt-0.5">
                    共享资源不保证没有安全隐患，可能存在恶意代码注入。建议下载后先进行安全检测，确认安全后再导入；由此产生的后果本软件不承担任何法律责任。
                  </div>
                </div>
              </div>

              {props.importState.phase === "done" ? (
                <div className="flex items-center gap-2 text-xs text-success bg-success/10 border border-success/25 rounded-lg px-3 py-2">
                  <CheckCircle2 className="w-4 h-4" /> 已成功导入
                </div>
              ) : isNode ? (
                ready ? (
                  <div className="rounded-lg border border-border bg-muted/30 p-3 space-y-2">
                    <div className="text-xs">
                      <div>名称：<span className="font-semibold">{props.importState.validation?.node?.name || detail.name}</span>（v{props.importState.validation?.node?.version || detail.version}）</div>
                      {vc && <div className="mt-1 text-[11px] text-muted-foreground">{vc.message}</div>}
                      {props.importState.validation?.warnings?.map((w, i) => (
                        <div key={i} className="text-[11px] text-warning flex items-center gap-1 mt-0.5"><AlertCircle className="w-3 h-3" />{w}</div>
                      ))}
                      {props.importState.validation?.shareMeta?.shareName && (
                        <div className="text-[11px] text-muted-foreground mt-1">来源分享名：{props.importState.validation.shareMeta.shareName}</div>
                      )}
                    </div>
                    {props.importState.error && (
                      <div className="text-[11px] text-destructive flex items-center gap-1"><XCircle className="w-3 h-3" />{props.importState.error}</div>
                    )}
                    {/* 改名导入兜底：以新 id 安装，避免覆盖本地节点 */}
                    <div className="flex items-center gap-1.5 pt-0.5">
                      <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground cursor-pointer select-none">
                        <input
                          type="checkbox"
                          checked={props.renameMode}
                          onChange={(e) => props.onRenameModeChange(e.target.checked)}
                          className="accent-primary"
                        />
                        改名导入（以新 id 安装，避免覆盖本地节点）
                      </label>
                    </div>
                    {props.renameMode && (
                      <Input
                        value={props.renameTo}
                        onChange={(e) => props.onRenameToChange(e.target.value)}
                        placeholder="新节点 id（不能与原 id 相同）"
                        className="h-8 text-xs font-mono"
                      />
                    )}
                    <div className="flex gap-2">
                      <Button size="sm" variant="outline" onClick={props.onResetImport}>取消</Button>
                      <Button
                        size="sm"
                        onClick={props.onConfirmNodeImport}
                        disabled={props.importState.phase === "importing" || (props.renameMode && !props.renameTo.trim())}
                      >
                        {props.importState.phase === "importing" && <Loader2 className="w-3 h-3 mr-1 animate-spin" />}
                        {props.renameMode ? "确认改名导入" : "确认导入（自动备份）"}
                      </Button>
                    </div>
                  </div>
                ) : (
                  <Button size="sm" onClick={props.onStartNodeImport} disabled={props.importing}>
                    {props.importing ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Download className="w-3 h-3 mr-1" />}
                    下载并导入节点
                  </Button>
                )
              ) : ready ? (
                <WorkflowImportPanel
                  resource={detail}
                  baseUrl={baseUrl}
                  onSuccess={props.onWorkflowSuccess}
                  onCancel={props.onResetImport}
                />
              ) : (
                <Button size="sm" onClick={props.onStartWorkflowImport}><Download className="w-3 h-3 mr-1" />下载并导入工作流</Button>
              )}
            </div>

            <div className="flex justify-end gap-2 pt-1">
              {props.adminToken && (
                <Button
                  variant="danger-soft"
                  size="sm"
                  onClick={() => props.onAdminDelete(detail)}
                  disabled={props.deleting}
                  title="管理员删除该资源"
                >
                  {props.deleting ? <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" /> : <Trash2 className="w-3.5 h-3.5 mr-1" />}
                  删除
                </Button>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={props.onDownloadOnly}
                disabled={props.downloading}
                title="仅下载文件，不执行导入"
              >
                {props.downloading ? <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" /> : <Download className="w-3.5 h-3.5 mr-1" />}
                仅下载
              </Button>
              <Button
                variant={detail.liked ? "destructive" : "outline"}
                size="sm"
                onClick={() => props.onLike(detail)}
                disabled={props.liking}
              >
                <Heart className={cn("w-3.5 h-3.5 mr-1", detail.liked && "fill-current")} />
                {detail.liked ? "已赞" : "点赞"} · {detail.likeCount}
              </Button>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

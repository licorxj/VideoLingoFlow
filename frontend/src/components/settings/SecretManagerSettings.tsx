import { useCallback, useEffect, useState } from "react";
import { credentialsApi, Credential } from "@/api/credentials";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  KeyRound,
  Plus,
  Search,
  RefreshCw,
  Loader2,
  Pencil,
  Trash2,
  Eye,
  EyeOff,
  ShieldCheck,
  AlertTriangle,
  Copy,
  Check,
  RotateCw,
  ExternalLink,
} from "lucide-react";
import { cn } from "@/lib/utils";

const inputCls =
  "h-9 rounded-lg border border-border/60 bg-background/60 px-3 text-sm outline-none transition-colors placeholder:text-muted-foreground/60 focus:border-primary/60";

type FormState = { id?: string; name: string; value: string; purpose: string; register_url: string; rotate: boolean };

const EMPTY_FORM: FormState = { name: "", value: "", purpose: "", register_url: "", rotate: true };

export default function SecretManagerSettings() {
  const [items, setItems] = useState<Credential[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [revealed, setRevealed] = useState<Record<string, string>>({});
  const [revealLoading, setRevealLoading] = useState("");

  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  const [deleteTarget, setDeleteTarget] = useState<Credential | null>(null);
  const [usage, setUsage] = useState<string[] | null>(null);
  const [deleting, setDeleting] = useState(false);

  const [toast, setToast] = useState<{ type: "ok" | "err"; msg: string } | null>(null);
  const [copied, setCopied] = useState("");

  const notify = (type: "ok" | "err", msg: string) => setToast({ type, msg });

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const res = await credentialsApi.list();
      setItems(res.data.credentials || []);
      setRevealed({});
    } catch (e: any) {
      notify("err", "加载密钥失败：" + (e?.message || e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3500);
    return () => clearTimeout(t);
  }, [toast]);

  const filtered = items.filter((i) => {
    const kw = keyword.trim().toLowerCase();
    if (!kw) return true;
    return i.name.toLowerCase().includes(kw) || (i.purpose || "").toLowerCase().includes(kw);
  });

  const openCreate = () => {
    setForm(EMPTY_FORM);
    setFormOpen(true);
  };

  const openEdit = async (item: Credential) => {
    try {
      const res = await credentialsApi.get(item.id, true);
      setForm({
        id: item.id,
        name: res.data.credential.name,
        value: res.data.credential.value || "",
        purpose: res.data.credential.purpose || "",
        register_url: res.data.credential.register_url || "",
        rotate: res.data.credential.rotate,
      });
      setFormOpen(true);
    } catch (e: any) {
      notify("err", "读取密钥失败：" + (e?.message || e));
    }
  };

  const submit = async () => {
    if (!form.name.trim()) {
      notify("err", "请填写密钥名称");
      return;
    }
    setSaving(true);
    try {
      if (form.id) {
        await credentialsApi.update(form.id, {
          name: form.name.trim(),
          value: form.value,
          purpose: form.purpose.trim(),
          register_url: form.register_url.trim(),
          rotate: form.rotate,
        });
        notify("ok", "密钥已更新");
      } else {
        await credentialsApi.create({
          name: form.name.trim(),
          value: form.value,
          purpose: form.purpose.trim(),
          register_url: form.register_url.trim(),
          rotate: form.rotate,
        });
        notify("ok", "密钥已创建");
      }
      setFormOpen(false);
      refresh();
    } catch (e: any) {
      notify("err", "保存失败：" + (e?.message || e));
    } finally {
      setSaving(false);
    }
  };

  const toggleRotate = async (item: Credential) => {
    try {
      await credentialsApi.update(item.id, { rotate: !item.rotate });
      setItems((prev) =>
        prev.map((i) => (i.id === item.id ? { ...i, rotate: !item.rotate } : i))
      );
      notify("ok", item.rotate ? `已关闭 ${item.name} 轮询` : `已开启 ${item.name} 轮询`);
    } catch (e: any) {
      notify("err", "切换轮询失败：" + (e?.message || e));
    }
  };

  const toggleReveal = async (item: Credential) => {
    if (revealed[item.id]) {
      setRevealed((prev) => {
        const next = { ...prev };
        delete next[item.id];
        return next;
      });
      return;
    }
    setRevealLoading(item.id);
    try {
      const res = await credentialsApi.get(item.id, true);
      setRevealed((prev) => ({ ...prev, [item.id]: res.data.credential.value || "" }));
    } catch (e: any) {
      notify("err", "读取密钥失败：" + (e?.message || e));
    } finally {
      setRevealLoading("");
    }
  };

  const askDelete = async (item: Credential) => {
    setDeleteTarget(item);
    setUsage(null);
    try {
      const res = await credentialsApi.usage(item.id);
      setUsage(res.data.references || []);
    } catch {
      setUsage([]);
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await credentialsApi.remove(deleteTarget.id);
      notify("ok", `已删除 ${deleteTarget.name}`);
      setDeleteTarget(null);
      refresh();
    } catch (e: any) {
      notify("err", "删除失败：" + (e?.message || e));
    } finally {
      setDeleting(false);
    }
  };

  const copyRef = async (item: Credential) => {
    try {
      await navigator.clipboard.writeText(`secret://${item.name}`);
      setCopied(item.id);
      setTimeout(() => setCopied(""), 1500);
    } catch {
      notify("err", "复制失败");
    }
  };

  const fmt = (v?: string | null) => (v ? v.slice(0, 10) : "—");

  return (
    <div className="space-y-4">
      {toast && (
        <div
          className={cn(
            "flex items-center gap-2 rounded-xl border p-3 text-sm",
            toast.type === "ok"
              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
              : "border-red-500/30 bg-red-500/10 text-red-400"
          )}
        >
          {toast.type === "ok" ? <ShieldCheck className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}
          {toast.msg}
        </div>
      )}

      <div className="rounded-2xl border border-border/50 bg-card/70 p-5">
        <div className="flex items-start gap-3">
          <KeyRound className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
          <div className="space-y-1 text-sm">
            <div className="font-semibold">密钥统一保存在本机数据库</div>
            <p className="text-muted-foreground">
              配置文件中只保存密钥名称引用（形如 <code className="rounded bg-muted px-1">secret://OPENAI_API_KEY</code>），
              真实值存放在 <code className="rounded bg-muted px-1">data/control-plane.db</code>。
              该数据库属于用户私有资产，不随软件分发，git 更新也不会覆盖。
            </p>
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            className={cn(inputCls, "w-full pl-8")}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="搜索名称或用途说明"
          />
        </div>
        <button
          onClick={refresh}
          className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-border/60 px-3 text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
          刷新
        </button>
        <button
          onClick={openCreate}
          className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-primary px-3 text-xs font-medium text-primary-foreground"
        >
          <Plus className="h-3.5 w-3.5" />
          新建密钥
        </button>
      </div>

      <div className="overflow-hidden rounded-2xl border border-border/50">
        {loading && items.length === 0 ? (
          <div className="flex items-center justify-center py-16 text-sm text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            加载中…
          </div>
        ) : filtered.length === 0 ? (
          <div className="py-16 text-center text-sm text-muted-foreground">
            {items.length === 0 ? "尚未配置任何密钥" : "没有匹配的密钥"}
          </div>
        ) : (
          <table className="w-full table-fixed text-sm">
            <thead className="bg-muted/40 text-xs uppercase tracking-wider text-muted-foreground">
              <tr>
                <th className="w-[18%] px-4 py-2.5 text-left font-medium">名称</th>
                <th className="w-[16%] px-4 py-2.5 text-left font-medium">用途说明</th>
                <th className="w-[20%] px-4 py-2.5 text-left font-medium">密钥值</th>
                <th className="w-[6%] px-4 py-2.5 text-left font-medium">注册</th>
                <th className="w-[8%] px-4 py-2.5 text-left font-medium">轮询</th>
                <th className="w-[9%] px-4 py-2.5 text-left font-medium">更新时间</th>
                <th className="w-28 px-4 py-2.5 text-right font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((item) => (
                <tr key={item.id} className="border-t border-border/40 transition-colors hover:bg-accent/30">
                  <td className="max-w-[16rem] px-4 py-3">
                    <div className="flex min-w-0 items-center gap-1.5">
                      <span className="truncate font-medium" title={item.name}>
                        {item.name}
                      </span>
                      <button
                        onClick={() => copyRef(item)}
                        title="复制引用名"
                        className="shrink-0 text-muted-foreground transition-colors hover:text-foreground"
                      >
                        {copied === item.id ? (
                          <Check className="h-3.5 w-3.5 text-emerald-500" />
                        ) : (
                          <Copy className="h-3.5 w-3.5" />
                        )}
                      </button>
                    </div>
                  </td>
                  <td className="max-w-[14rem] px-4 py-3">
                    <span className="line-clamp-2 text-muted-foreground">{item.purpose || "—"}</span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex min-w-0 items-center gap-2">
                      <code
                        className="max-w-[11rem] truncate rounded bg-muted px-1.5 py-0.5 text-xs"
                        title={revealed[item.id] ?? item.masked}
                      >
                        {revealed[item.id] ?? item.masked}
                      </code>
                      {item.keys_count > 1 && (
                        <span className="whitespace-nowrap rounded-full bg-info/10 px-1.5 py-0.5 text-[11px] text-info">
                          #{(item.current_index % item.keys_count) + 1}/{item.keys_count}
                        </span>
                      )}
                      <button
                        onClick={() => toggleReveal(item)}
                        className="text-muted-foreground transition-colors hover:text-foreground"
                        title={revealed[item.id] ? "隐藏" : "显示"}
                      >
                        {revealLoading === item.id ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : revealed[item.id] ? (
                          <EyeOff className="h-3.5 w-3.5" />
                        ) : (
                          <Eye className="h-3.5 w-3.5" />
                        )}
                      </button>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    {item.register_url ? (
                      <button
                        onClick={() => window.open(item.register_url, "_blank")}
                        title={`打开注册页面：${item.register_url}`}
                        className="inline-flex h-6 shrink-0 items-center gap-1 whitespace-nowrap rounded-full bg-primary/10 px-2 text-[11px] font-medium text-primary transition-colors hover:bg-primary/20"
                      >
                        <ExternalLink className="h-3 w-3" />
                        注册
                      </button>
                    ) : (
                      <span className="text-[11px] text-muted-foreground/50">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => toggleRotate(item)}
                      title={item.rotate ? "轮询已开启，点击关闭" : item.keys_count > 1 ? "点击开启多 key 轮询" : "粘贴多个 key 后可开启轮询"}
                      className={cn(
                        "inline-flex h-6 shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-2 text-[11px] font-medium transition-colors",
                        item.rotate
                          ? "bg-emerald-500/15 text-emerald-500"
                          : "bg-muted text-muted-foreground hover:text-foreground"
                      )}
                    >
                      <RotateCw className={cn("h-3 w-3", item.rotate && "animate-[spin_3s_linear_infinite]")} />
                      {item.rotate ? "轮询中" : "关闭"}
                    </button>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-xs text-muted-foreground">
                    {fmt(item.updated_at)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-1">
                      <button
                        onClick={() => openEdit(item)}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-border/60 text-muted-foreground transition-colors hover:text-foreground"
                        title="编辑"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      <button
                        onClick={() => askDelete(item)}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-border/60 text-muted-foreground transition-colors hover:text-destructive"
                        title="删除"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* 新建 / 编辑 */}
      <Dialog open={formOpen} onOpenChange={setFormOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{form.id ? "编辑密钥" : "新建密钥"}</DialogTitle>
            <DialogDescription>
              名称用于在各能力接口中引用，建议使用大写英文与下划线。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">名称 *</label>
              <input
                className={cn(inputCls, "w-full")}
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value.toUpperCase() })}
                placeholder="OPENAI_API_KEY"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">用途说明</label>
              <input
                className={cn(inputCls, "w-full")}
                value={form.purpose}
                onChange={(e) => setForm({ ...form, purpose: e.target.value })}
                placeholder="例如：302.AI 聚合平台，用于 LLM 与 TTS"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">注册地址</label>
              <div className="flex items-center gap-2">
                <input
                  className={cn(inputCls, "flex-1")}
                  value={form.register_url}
                  onChange={(e) => setForm({ ...form, register_url: e.target.value })}
                  placeholder="https://platform.openai.com/api-keys"
                />
                {form.register_url && (
                  <button
                    type="button"
                    onClick={() => window.open(form.register_url, "_blank")}
                    title="打开注册页面"
                    className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-lg border border-border/60 px-3 text-xs text-muted-foreground transition-colors hover:text-primary"
                  >
                    <ExternalLink className="h-3.5 w-3.5" />
                    打开
                  </button>
                )}
              </div>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                密钥值（每行一个，可粘贴多个实现轮询）
              </label>
              <textarea
                className="min-h-[80px] w-full rounded-lg border border-border/60 bg-background/60 p-3 text-sm outline-none transition-colors focus:border-primary/60"
                value={form.value}
                onChange={(e) => setForm({ ...form, value: e.target.value })}
                placeholder={"粘贴 API Key / Token\n支持多行，每行一个 key"}
                spellCheck={false}
              />
              <label className="mt-2 flex cursor-pointer items-center gap-2 text-xs text-muted-foreground">
                <input
                  type="checkbox"
                  checked={form.rotate}
                  onChange={(e) => setForm({ ...form, rotate: e.target.checked })}
                  className="h-3.5 w-3.5 accent-[hsl(var(--primary))]"
                />
                开启轮询：存在多个 key 时每次调用自动切换下一个（单 key 时无影响）
              </label>
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <button
              onClick={() => setFormOpen(false)}
              className="h-9 rounded-lg border border-border/60 px-4 text-sm text-muted-foreground hover:text-foreground"
            >
              取消
            </button>
            <button
              onClick={submit}
              disabled={saving}
              className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-60"
            >
              {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              保存
            </button>
          </div>
        </DialogContent>
      </Dialog>

      {/* 删除确认 */}
      <Dialog open={!!deleteTarget} onOpenChange={(v) => !v && setDeleteTarget(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-amber-500" />
              删除密钥
            </DialogTitle>
            <DialogDescription>
              确认删除 <span className="font-medium text-foreground">{deleteTarget?.name}</span> ？
            </DialogDescription>
          </DialogHeader>
          <div className="rounded-xl border border-border/50 bg-muted/30 p-3 text-xs">
            {usage === null ? (
              <span className="text-muted-foreground">检查引用情况…</span>
            ) : usage.length === 0 ? (
              <span className="text-muted-foreground">当前没有配置项引用该密钥。</span>
            ) : (
              <div className="space-y-1">
                <div className="font-medium text-amber-500">
                  有 {usage.length} 处配置引用了该密钥，删除后相关接口将调用失败：
                </div>
                <ul className="max-h-32 space-y-0.5 overflow-y-auto text-muted-foreground">
                  {usage.map((r) => (
                    <li key={r} className="truncate">
                      · {r}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
          <div className="flex justify-end gap-2">
            <button
              onClick={() => setDeleteTarget(null)}
              className="h-9 rounded-lg border border-border/60 px-4 text-sm text-muted-foreground hover:text-foreground"
            >
              取消
            </button>
            <button
              onClick={confirmDelete}
              disabled={deleting}
              className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-destructive px-4 text-sm font-medium text-destructive-foreground disabled:opacity-60"
            >
              {deleting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              确认删除
            </button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

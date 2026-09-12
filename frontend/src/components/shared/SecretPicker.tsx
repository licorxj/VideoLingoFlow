import { useEffect, useMemo, useState } from "react";
import { credentialsApi, Credential } from "@/api/credentials";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { KeyRound, Search, Plus, Check, Loader2, Link2, AlertTriangle, X } from "lucide-react";
import { cn } from "@/lib/utils";

export const SECRET_PREFIX = "secret://";

export function toSecretRef(name: string): string {
  return `${SECRET_PREFIX}${name}`;
}

export function secretNameOf(value?: string | null): string {
  if (!value) return "";
  return value.startsWith(SECRET_PREFIX) ? value.slice(SECRET_PREFIX.length) : "";
}

export function isSecretRef(value?: string | null): boolean {
  return !!value && value.startsWith(SECRET_PREFIX);
}

const SECRET_ROW_KEYS = new Set([
  "api_key",
  "sdk_api_key",
  "wallet_api_key",
  "router_api_key",
  "hf_token",
  "token",
  "password",
]);

/** 动态表单里按字段名判断该行是否应改用密钥匹配控件。 */
export function isSecretRowKey(key: string): boolean {
  return SECRET_ROW_KEYS.has(key);
}

const inputCls =
  "h-9 rounded-lg border border-border/60 bg-background/60 px-3 text-sm outline-none transition-colors placeholder:text-muted-foreground/60 focus:border-primary/60";

/* -------------------------------------------------------------------------- */
/* 选择弹窗：列出已有密钥，并支持快捷新建                                        */
/* -------------------------------------------------------------------------- */
interface ModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onPick: (ref: string) => void;
  title?: string;
}

export function SecretPickerModal({ open, onOpenChange, onPick, title = "匹配密钥" }: ModalProps) {
  const [items, setItems] = useState<Credential[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [selected, setSelected] = useState("");
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: "", value: "", purpose: "", register_url: "", rotate: true });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const refresh = async () => {
    setLoading(true);
    try {
      const res = await credentialsApi.list();
      setItems(res.data.credentials || []);
    } catch (e: any) {
      setError(e?.message || "加载密钥列表失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!open) return;
    setKeyword("");
    setSelected("");
    setCreating(false);
    setForm({ name: "", value: "", purpose: "", register_url: "", rotate: true });
    setError("");
    refresh();
  }, [open]);

  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    if (!kw) return items;
    return items.filter(
      (i) => i.name.toLowerCase().includes(kw) || (i.purpose || "").toLowerCase().includes(kw)
    );
  }, [items, keyword]);

  const handleCreate = async () => {
    if (!form.name.trim()) {
      setError("请填写密钥名称");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const res = await credentialsApi.create({
        name: form.name.trim(),
        value: form.value,
        purpose: form.purpose.trim(),
        register_url: form.register_url.trim(),
        rotate: form.rotate,
      });
      const created = res.data.credential;
      setItems((prev) => [...prev, created].sort((a, b) => a.name.localeCompare(b.name)));
      setSelected(created.name);
      setCreating(false);
      setForm({ name: "", value: "", purpose: "", register_url: "", rotate: true });
    } catch (e: any) {
      setError(e?.message || "创建失败");
    } finally {
      setSaving(false);
    }
  };

  const confirm = () => {
    if (!selected) return;
    onPick(toSecretRef(selected));
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl border-primary/40 shadow-2xl shadow-black/40 ring-1 ring-primary/20">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <KeyRound className="h-4 w-4" />
            {title}
          </DialogTitle>
          <DialogDescription>
            选择已配置的密钥，配置处将只保存密钥名称引用，真实值留在本机数据库中。
          </DialogDescription>
        </DialogHeader>

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
            onClick={() => setCreating((v) => !v)}
            className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-primary/40 bg-primary/10 px-3 text-sm font-medium text-foreground transition-colors hover:bg-primary/20"
          >
            <Plus className="h-3.5 w-3.5" />
            新建密钥
          </button>
        </div>

        {creating && (
          <div className="grid grid-cols-2 gap-3 rounded-xl border border-primary/50 bg-primary/[0.07] p-3.5 shadow-lg shadow-black/25 ring-1 ring-primary/20">
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
                placeholder="用于 xxx 接口调用"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">注册地址</label>
              <input
                className={cn(inputCls, "w-full")}
                value={form.register_url}
                onChange={(e) => setForm({ ...form, register_url: e.target.value })}
                placeholder="https://..."
              />
            </div>
            <div className="col-span-2">
              <label className="mb-1 block text-xs font-medium text-muted-foreground">密钥值（每行一个，可粘贴多个）</label>
              <textarea
                className="min-h-[72px] w-full rounded-lg border border-border/60 bg-background/60 p-2.5 text-sm outline-none transition-colors focus:border-primary/60"
                value={form.value}
                onChange={(e) => setForm({ ...form, value: e.target.value })}
                placeholder={"sk-key-1\nsk-key-2"}
                spellCheck={false}
              />
            </div>
            <label className="col-span-2 flex cursor-pointer items-center gap-2 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={form.rotate}
                onChange={(e) => setForm({ ...form, rotate: e.target.checked })}
                className="h-3.5 w-3.5 accent-[hsl(var(--primary))]"
              />
              开启轮询：存在多个 key 时每次调用自动切换下一个（单 key 时无影响）
            </label>
            <div className="col-span-2 flex justify-end gap-2">
              <button
                onClick={() => setCreating(false)}
                className="h-8 rounded-lg border border-border/60 px-3 text-xs text-muted-foreground hover:text-foreground"
              >
                取消
              </button>
              <button
                onClick={handleCreate}
                disabled={saving}
                className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-primary px-3 text-xs font-medium text-primary-foreground disabled:opacity-60"
              >
                {saving && <Loader2 className="h-3 w-3 animate-spin" />}
                保存并选用
              </button>
            </div>
          </div>
        )}

        {error && (
          <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
            <AlertTriangle className="h-3.5 w-3.5" />
            {error}
          </div>
        )}

        <div className="max-h-72 overflow-y-auto rounded-xl border border-border/50">
          {loading ? (
            <div className="flex items-center justify-center py-10 text-sm text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              加载中…
            </div>
          ) : filtered.length === 0 ? (
            <div className="py-10 text-center text-sm text-muted-foreground">暂无匹配的密钥</div>
          ) : (
            filtered.map((item) => {
              const active = item.name === selected;
              return (
                <button
                  key={item.id}
                  onClick={() => setSelected(item.name)}
                  className={cn(
                    "flex w-full items-center gap-3 border-b border-border/40 px-3 py-2.5 text-left transition-colors last:border-b-0",
                    active ? "bg-primary/10" : "hover:bg-accent/60"
                  )}
                >
                  <span
                    className={cn(
                      "flex h-4 w-4 shrink-0 items-center justify-center rounded-full border",
                      active ? "border-primary bg-primary text-primary-foreground" : "border-border"
                    )}
                  >
                    {active && <Check className="h-2.5 w-2.5" />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{item.name}</div>
                    {item.purpose && (
                      <div className="truncate text-[11px] text-muted-foreground">{item.purpose}</div>
                    )}
                  </div>
                  <code className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
                    {item.masked}
                  </code>
                </button>
              );
            })
          )}
        </div>

        <div className="flex justify-end gap-2">
          <button
            onClick={() => onOpenChange(false)}
            className="h-9 rounded-lg border border-border/60 px-4 text-sm text-muted-foreground hover:text-foreground"
          >
            取消
          </button>
          <button
            onClick={confirm}
            disabled={!selected}
            className="h-9 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            使用所选密钥
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/* -------------------------------------------------------------------------- */
/* 表单字段：替换原先的明文输入框                                               */
/* -------------------------------------------------------------------------- */
interface FieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string;
  className?: string;
}

export function SecretField({ label, value, onChange, hint, className }: FieldProps) {
  const [open, setOpen] = useState(false);
  const boundName = secretNameOf(value);
  const isRef = isSecretRef(value);
  const hasPlainText = !!value && !isRef;

  return (
    <div className={className}>
      <label className="mb-1.5 block text-xs font-medium text-muted-foreground">{label}</label>
      <div className="flex items-center gap-2">
        <div
          className={cn(
            "flex h-9 min-w-0 flex-1 items-center gap-2 rounded-lg border px-3 text-sm",
            boundName
              ? "border-primary/40 bg-primary/5"
              : "border-border/60 bg-background/60"
          )}
        >
          {boundName ? (
            <>
              <Link2 className="h-3.5 w-3.5 shrink-0 text-primary" />
              <span className="truncate font-medium">{boundName}</span>
            </>
          ) : hasPlainText ? (
            <>
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-500" />
              <span className="truncate text-xs text-muted-foreground">
                历史密钥仍明文存于配置文件，点「匹配key」绑定后保存即可迁移
              </span>
            </>
          ) : (
            <span className="text-xs text-muted-foreground">未绑定密钥</span>
          )}
        </div>
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-lg border border-border/60 px-3 text-xs font-medium transition-colors hover:border-primary/50 hover:text-foreground"
        >
          <KeyRound className="h-3.5 w-3.5" />
          匹配key
        </button>
        {value && (
          <button
            type="button"
            onClick={() => onChange("")}
            title="解除绑定"
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border/60 text-muted-foreground transition-colors hover:text-destructive"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      {hint && <p className="mt-1 text-[11px] text-muted-foreground">{hint}</p>}
      <SecretPickerModal open={open} onOpenChange={setOpen} onPick={onChange} title={`匹配密钥 · ${label}`} />
    </div>
  );
}

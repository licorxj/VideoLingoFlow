import { useState, useEffect } from "react";
import { aigcApi } from "@/api/aigcCapabilities";
import { cn } from "@/lib/utils";
import {
  Boxes,
  Cloudy,
  Wand2,
  Plug,
  CheckCircle2,
  XCircle,
  Loader2,
  AlertTriangle,
} from "lucide-react";

type ProviderState = Record<string, any>;

export default function AigcCapabilitiesSettings() {
  const [config, setConfig] = useState<{
    comfyui: ProviderState;
    runninghub: ProviderState;
    jimeng: ProviderState;
  } | null>(null);
  const [status, setStatus] = useState<any>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [toast, setToast] = useState<{ type: "ok" | "err"; msg: string } | null>(null);

  const load = async () => {
    try {
      const [cfgRes, stRes] = await Promise.all([
        aigcApi.getConfig(),
        aigcApi.status().catch(() => ({ data: { status: {} } })),
      ]);
      setConfig(cfgRes.data.config);
      setStatus(stRes.data.status || {});
    } catch (e: any) {
      setToast({ type: "err", msg: "加载配置失败：" + (e?.message || e) });
    }
  };

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(null), 4000);
      return () => clearTimeout(t);
    }
  }, [toast]);

  const updateProvider = async (provider: string, patch: ProviderState) => {
    setSaving(provider);
    try {
      const res = await aigcApi.updateConfig(provider, patch);
      setConfig((prev) => ({ ...(prev as any), [provider]: res.data.config[provider] }));
      setToast({ type: "ok", msg: `${provider} 配置已保存` });
    } catch (e: any) {
      setToast({ type: "err", msg: "保存失败：" + (e?.message || e) });
    } finally {
      setSaving(null);
    }
  };

  const testProvider = async (provider: string) => {
    setTesting(provider);
    try {
      if (provider === "comfyui") await aigcApi.testComfyui();
      else if (provider === "runninghub") await aigcApi.testRunninghub();
      else if (provider === "jimeng") await aigcApi.jimengVersion();
      setToast({ type: "ok", msg: `${provider} 测试通过` });
      load();
    } catch (e: any) {
      setToast({ type: "err", msg: `${provider} 测试失败：` + (e?.message || e) });
    } finally {
      setTesting(null);
    }
  };

  if (!config) {
    return (
      <div className="flex items-center justify-center py-20 text-muted-foreground">
        <Loader2 className="w-5 h-5 animate-spin mr-2" /> 加载中…
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {toast && (
        <div
          className={cn(
            "rounded-xl border p-3 text-sm flex items-center gap-2",
            toast.type === "ok"
              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
              : "border-red-500/30 bg-red-500/10 text-red-400"
          )}
        >
          {toast.type === "ok" ? <CheckCircle2 className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
          {toast.msg}
        </div>
      )}

      <ComfyuiCard
        value={config.comfyui}
        status={status?.comfyui}
        saving={saving === "comfyui"}
        testing={testing === "comfyui"}
        onChange={(patch) => updateProvider("comfyui", patch)}
        onTest={() => testProvider("comfyui")}
      />
      <RunninghubCard
        value={config.runninghub}
        status={status?.runninghub}
        saving={saving === "runninghub"}
        testing={testing === "runninghub"}
        onChange={(patch) => updateProvider("runninghub", patch)}
        onTest={() => testProvider("runninghub")}
      />
      <JimengCard
        value={config.jimeng}
        status={status?.jimeng}
        saving={saving === "jimeng"}
        testing={testing === "jimeng"}
        onChange={(patch) => updateProvider("jimeng", patch)}
        onTest={() => testProvider("jimeng")}
      />
    </div>
  );
}

interface CardProps {
  value: ProviderState;
  status?: any;
  saving: boolean;
  testing: boolean;
  onChange: (patch: ProviderState) => void;
  onTest: () => void;
}

function StatusBadge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium",
        ok ? "bg-emerald-500/15 text-emerald-400" : "bg-amber-500/15 text-amber-400"
      )}
    >
      {ok ? <CheckCircle2 className="w-3 h-3" /> : <AlertTriangle className="w-3 h-3" />}
      {label}
    </span>
  );
}

function SectionCard({
  icon: Icon,
  title,
  desc,
  value,
  status,
  saving,
  testing,
  children,
  onTest,
}: CardProps & {
  icon: any;
  title: string;
  desc: string;
  status?: any;
  children: React.ReactNode;
  onTest: () => void;
}) {
  return (
    <div className="rounded-2xl border border-border/50 bg-card/40 p-5 space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
            <Icon className="w-5 h-5 text-primary" />
          </div>
          <div>
            <h3 className="font-semibold text-base">{title}</h3>
            <p className="text-xs text-muted-foreground mt-0.5 max-w-xl">{desc}</p>
            <div className="mt-2">{status}</div>
          </div>
        </div>
        <button
          onClick={onTest}
          disabled={testing}
          className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border/60 text-sm hover:bg-muted/50 disabled:opacity-50"
        >
          {testing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plug className="w-4 h-4" />}
          连接测试
        </button>
      </div>
      <div className="space-y-3">{children}</div>
      {saving && (
        <div className="text-xs text-muted-foreground flex items-center gap-1">
          <Loader2 className="w-3 h-3 animate-spin" /> 保存中…
        </div>
      )}
    </div>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block space-y-1">
      <span className="text-sm font-medium">{label}</span>
      {children}
      {hint && <span className="block text-xs text-muted-foreground">{hint}</span>}
    </label>
  );
}

const inputCls =
  "w-full rounded-lg border border-border/60 bg-background/60 px-3 py-2 text-sm outline-none focus:border-primary/60";

function ComfyuiCard({ value, status, saving, testing, onChange, onTest }: CardProps) {
  const instances = Array.isArray(value.instances) ? value.instances.join(", ") : "";
  const ok = status?.reachable;
  return (
    <SectionCard
      icon={Boxes}
      title="ComfyUI（本地/局域网）"
      desc="调用本地或局域网内的 ComfyUI 实例运行工作流，支持文生图/图生图/视频生成。"
      value={value}
      status={status && <StatusBadge ok={!!ok} label={ok ? `已连接 ${status.instance}` : "未连接"} />}
      saving={saving}
      testing={testing}
      onChange={onChange}
      onTest={onTest}
    >
      <Field label="实例地址（逗号分隔，支持负载均衡）" hint="例如 127.0.0.1:8188, 192.168.1.20:8188">
        <input
          className={inputCls}
          defaultValue={instances}
          onBlur={(e) =>
            onChange({ instances: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })
          }
        />
      </Field>
      <Field label="轮询总超时（秒）">
        <input
          type="number"
          className={inputCls}
          defaultValue={value.timeout}
          onBlur={(e) => onChange({ timeout: Number(e.target.value) })}
        />
      </Field>
    </SectionCard>
  );
}

function RunninghubCard({ value, status, saving, testing, onChange, onTest }: CardProps) {
  const ok = status?.configured;
  return (
    <SectionCard
      icon={Cloudy}
      title="RunningHub（云端 OpenAPI）"
      desc="通过 RunningHub OpenAPI 运行工作流或 AI 应用，生成图片/视频。需填写 API Key。"
      value={value}
      status={status && <StatusBadge ok={!!ok} label={ok ? "已配置 Key" : "未配置 Key"} />}
      saving={saving}
      testing={testing}
      onChange={onChange}
      onTest={onTest}
    >
      <Field label="Base URL">
        <input
          className={inputCls}
          defaultValue={value.base_url}
          onBlur={(e) => onChange({ base_url: e.target.value.trim() })}
        />
      </Field>
      <Field label="API Key（标准模型接口）" hint="用于 /task/openapi/ai-app/run 等标准模型接口">
        <input
          type="password"
          className={inputCls}
          defaultValue={value.api_key}
          onBlur={(e) => onChange({ api_key: e.target.value.trim() })}
        />
      </Field>
      <Field label="钱包 API Key（账户余额）" hint="用于工作流提交 /task/openapi/create 的鉴权">
        <input
          type="password"
          className={inputCls}
          defaultValue={value.wallet_api_key}
          onBlur={(e) => onChange({ wallet_api_key: e.target.value.trim() })}
        />
      </Field>
      <Field label="轮询总超时（秒）">
        <input
          type="number"
          className={inputCls}
          defaultValue={value.timeout}
          onBlur={(e) => onChange({ timeout: Number(e.target.value) })}
        />
      </Field>
    </SectionCard>
  );
}

function JimengCard({ value, status, saving, testing, onChange, onTest }: CardProps) {
  const ok = status?.cli_found;
  return (
    <SectionCard
      icon={Wand2}
      title="即梦 CLI（本地子进程）"
      desc="调用本机即梦(dreamina) CLI 生成图片/视频。需先安装并登录：curl -fsSL https://jimeng.jianying.com/cli | bash && dreamina login"
      value={value}
      status={status && <StatusBadge ok={!!ok} label={ok ? `CLI 已找到：${status.exe}` : "未找到 CLI"} />}
      saving={saving}
      testing={testing}
      onChange={onChange}
      onTest={onTest}
    >
      <Field label="可执行文件路径" hint="留空则自动探测 dreamina / dreamina.exe">
        <input
          className={inputCls}
          defaultValue={value.bin}
          onBlur={(e) => onChange({ bin: e.target.value.trim() })}
        />
      </Field>
      <Field label="通过 WSL 调用" hint="非 WSL 的 Windows 上可开启，经由 wsl.exe 调用 Linux 版 CLI">
        <input
          type="checkbox"
          defaultChecked={!!value.use_wsl}
          onChange={(e) => onChange({ use_wsl: e.target.checked })}
        />
      </Field>
      <Field label="单次调用超时（秒）">
        <input
          type="number"
          className={inputCls}
          defaultValue={value.timeout}
          onBlur={(e) => onChange({ timeout: Number(e.target.value) })}
        />
      </Field>
    </SectionCard>
  );
}

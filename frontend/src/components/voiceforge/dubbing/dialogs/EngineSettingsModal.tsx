import { useEffect, useState } from "react";
import { Settings2, Loader2, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ttsInterfacesApi, TTSInterface, TTSInterfaceConfig } from "@/api/ttsInterfaces";

interface EngineSettingsModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  currentEngine?: string;
  onSaved?: () => void;
}

interface ParamDraft {
  key: string;
  value: string;
  description?: string;
}

export function EngineSettingsModal({
  open,
  onOpenChange,
  currentEngine,
  onSaved,
}: EngineSettingsModalProps) {
  const [interfaces, setInterfaces] = useState<TTSInterface[]>([]);
  const [activeId, setActiveId] = useState("");
  const [params, setParams] = useState<ParamDraft[]>([]);
  const [timeout, setTimeoutVal] = useState("");
  const [maxConcurrent, setMaxConcurrent] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const active = interfaces.find((i) => i.id === activeId);

  const populate = (iface: TTSInterface) => {
    const cfg: TTSInterfaceConfig = iface.config || {};
    setParams(
      (cfg.custom_params ?? []).map((p) => ({
        key: p.key,
        value: p.default ?? "",
        description: p.description,
      })),
    );
    setTimeoutVal(cfg.timeout != null ? String(cfg.timeout) : "");
    setMaxConcurrent(cfg.max_concurrent != null ? String(cfg.max_concurrent) : "");
  };

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    ttsInterfacesApi
      .list()
      .then((res) => {
        if (cancelled) return;
        const list: TTSInterface[] = res.data?.interfaces ?? [];
        setInterfaces(list);
        const preferred =
          list.find((i) => i.id === currentEngine) ??
          list.find((i) => i.enabled) ??
          list[0];
        if (preferred) {
          setActiveId(preferred.id);
          populate(preferred);
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(
          (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
            "加载 TTS 接口失败",
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const switchTab = (id: string) => {
    setActiveId(id);
    const iface = interfaces.find((i) => i.id === id);
    if (iface) populate(iface);
  };

  const setParamValue = (index: number, value: string) => {
    setParams((prev) => prev.map((p, i) => (i === index ? { ...p, value } : p)));
  };

  const handleSave = async () => {
    if (!active) return;
    setSaving(true);
    setError("");
    const config: TTSInterfaceConfig = {
      ...(active.config || {}),
      custom_params: params.map((p) => ({
        key: p.key,
        default: p.value,
        description: p.description ?? "",
      })),
    };
    if (timeout.trim() !== "") config.timeout = Number(timeout);
    else delete config.timeout;
    if (maxConcurrent.trim() !== "") config.max_concurrent = Number(maxConcurrent);
    else delete config.max_concurrent;

    try {
      await ttsInterfacesApi.update(active.id, { config });
      onSaved?.();
      onOpenChange(false);
    } catch (err: unknown) {
      setError(
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
          "保存引擎参数失败",
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>引擎参数设置</DialogTitle>
          <DialogDescription>
            调整各 TTS 接口的高级参数，保存后写入 tts_interfaces.json 并在合成时生效。
          </DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="flex items-center justify-center py-10 text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            加载中…
          </div>
        ) : interfaces.length === 0 ? (
          <div className="py-10 text-center text-sm text-muted-foreground">
            没有可用的 TTS 接口
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                TTS 接口
              </label>
              <Select value={activeId} onValueChange={switchTab}>
                <SelectTrigger className="h-8 text-sm">
                  <SelectValue placeholder="选择接口" />
                </SelectTrigger>
                <SelectContent>
                  {interfaces.map((i) => (
                    <SelectItem key={i.id} value={i.id}>
                      {i.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {active && (
              <>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="mb-1 block text-xs font-medium text-muted-foreground">
                      请求超时（秒）
                    </label>
                    <Input
                      type="number"
                      min={1}
                      value={timeout}
                      onChange={(e) => setTimeoutVal(e.target.value)}
                      className="h-8 text-sm"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-muted-foreground">
                      最大并发数
                    </label>
                    <Input
                      type="number"
                      min={1}
                      value={maxConcurrent}
                      onChange={(e) => setMaxConcurrent(e.target.value)}
                      className="h-8 text-sm"
                    />
                  </div>
                </div>

                {params.length > 0 && (
                  <div>
                    <label className="mb-2 flex items-center gap-1 text-xs font-medium text-muted-foreground">
                      <Settings2 className="h-3 w-3" />
                      引擎高级参数
                    </label>
                    <div className="space-y-3">
                      {params.map((p, idx) => (
                        <div key={p.key}>
                          <label className="mb-1 block text-xs text-muted-foreground">
                            {p.key}
                            {p.description ? `（${p.description}）` : ""}
                          </label>
                          <Input
                            value={p.value}
                            onChange={(e) => setParamValue(idx, e.target.value)}
                            className="h-8 text-sm"
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {error && <div className="text-xs text-destructive">{error}</div>}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={handleSave} disabled={!active || saving || loading}>
            {saving ? (
              <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
            ) : (
              <Save className="mr-1 h-3.5 w-3.5" />
            )}
            保存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

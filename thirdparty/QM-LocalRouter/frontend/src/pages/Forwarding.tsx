import React, { useState, useEffect } from "react";
import { useI18n } from "../i18n";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getSettings, updateSettings, getProviders, getModels, getLanIp } from "../services/api";
import { toast } from "../stores/toast";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Label } from "../components/ui/label";
import { Switch } from "../components/ui/switch";
import { Badge } from "../components/ui/badge";
import { Separator } from "../components/ui/separator";
import { Select, SelectTrigger, SelectContent, SelectItem, SelectValue } from "../components/ui/select";
import { Globe, Copy, Check, Box, Save, Loader2, Route } from "lucide-react";

export default function ForwardingPage() {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  const [lanIp, setLanIp] = useState("");
  const [appSettings, setAppSettings] = useState({
    output_protocol: "openai",
    default_model: "",
    default_provider_id: 0,
    lan_access: false,
  });
  const [defaultProviderId, setDefaultProviderId] = useState<number>(0);

  useEffect(() => {
    getLanIp().then((r) => setLanIp(r.data.ip)).catch(() => {});
  }, []);

  const { data: appSettingsData, refetch: refetchSettings } = useQuery({
    queryKey: ["appSettings"],
    queryFn: () => getSettings().then((r) => r.data),
  });

  const { data: providersList = [] } = useQuery({
    queryKey: ["providers"],
    queryFn: () => getProviders().then((r) => r.data),
  });

  const { data: modelsList = [] } = useQuery({
    queryKey: ["models", defaultProviderId],
    queryFn: () => getModels(defaultProviderId).then((r) => r.data),
    enabled: !!defaultProviderId,
  });

  useEffect(() => {
    if (appSettingsData) {
      setAppSettings(appSettingsData);
      setDefaultProviderId(appSettingsData.default_provider_id || 0);
    }
  }, [appSettingsData]);

  const saveSettingsMut = useMutation({
    mutationFn: () => updateSettings(appSettings),
    onSuccess: () => {
      refetchSettings();
      toast({ title: t("settings.saved"), variant: "success" });
    },
    onError: () => toast({ title: t("settings.configSaveFailed"), variant: "destructive" }),
  });

  const copyCode = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    toast({ title: t("common.copied"), variant: "success" });
    setTimeout(() => setCopied(false), 2000);
  };

  // 端点地址端口取后端真实监听端口（appSettings.backend_port），不写死上游默认值
  const backendPort = appSettings.backend_port || 12002;
  const proxyUrl = appSettings.lan_access && lanIp ? `http://${lanIp}:${backendPort}/v1` : `http://127.0.0.1:${backendPort}/v1`;
  const betaUrl = appSettings.lan_access && lanIp ? `http://${lanIp}:${backendPort}/v1beta` : `http://127.0.0.1:${backendPort}/v1beta`;

  // 客户端格式 → 请求端点。格式由端点决定，后端自动转换；与上游同格式时直通。
  const ENDPOINT_CARDS = [
    {
      id: "openai", label: "OpenAI", method: "POST", path: "/v1/chat/completions",
      desc: t("settings.epOpenaiDesc"),
      curl: `curl ${proxyUrl}/chat/completions \\\n  -H "Content-Type: application/json" \\\n  -d '{"model":"your-strategy","messages":[{"role":"user","content":"Hello"}]}'`,
    },
    {
      id: "responses", label: "Responses", method: "POST", path: "/v1/responses",
      desc: t("settings.epResponsesDesc"),
      curl: `curl ${proxyUrl}/responses \\\n  -H "Content-Type: application/json" \\\n  -d '{"model":"your-strategy","input":"Hello","stream":true}'`,
    },
    {
      id: "claude", label: "Claude", method: "POST", path: "/v1/messages",
      desc: t("settings.epClaudeDesc"),
      curl: `curl ${proxyUrl}/messages \\\n  -H "Content-Type: application/json" \\\n  -d '{"model":"your-strategy","max_tokens":1024,"messages":[{"role":"user","content":"Hello"}]}'`,
    },
    {
      id: "gemini", label: "Gemini", method: "POST", path: "/v1beta/models/{model}:generateContent",
      desc: t("settings.epGeminiDesc"),
      curl: `curl "${betaUrl}/models/your-strategy:generateContent" \\\n  -H "Content-Type: application/json" \\\n  -d '{"contents":[{"role":"user","parts":[{"text":"Hello"}]}]}'`,
    },
  ];

  return (
    <div className="space-y-6 max-w-3xl">

      {/* Route Management Model */}
      <Card className="card-hover">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <Box className="h-4 w-4 text-amber-400" />
            <CardTitle className="text-base">{t("settings.routeModel")}</CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between">
            <div>
              <Label className="text-sm font-medium">{t("settings.defaultModel")}</Label>
              <p className="text-xs text-muted-foreground mt-0.5">{t("settings.defaultModelDesc")}</p>
            </div>
            <div className="flex items-center gap-2">
              <Select value={defaultProviderId ? String(defaultProviderId) : ""} onValueChange={(v) => {
                const pid = Number(v);
                setDefaultProviderId(pid);
                setAppSettings((s) => ({ ...s, default_provider_id: pid, default_model: "" }));
              }}>
                <SelectTrigger className="w-48 h-9 text-sm">
                  <SelectValue placeholder={t("settings.selectProvider")} />
                </SelectTrigger>
                <SelectContent>
                  {(providersList as any[]).filter((p: any) => p.is_active).map((p: any) => (
                    <SelectItem key={p.id} value={String(p.id)}>{p.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={appSettings.default_model || ""} onValueChange={(v) => setAppSettings((s) => ({ ...s, default_model: v }))} disabled={!defaultProviderId}>
                <SelectTrigger className="w-48 h-9 text-sm">
                  <SelectValue placeholder={t("settings.selectModel")} />
                </SelectTrigger>
                <SelectContent>
                  {(modelsList as any[]).filter((m: any) => m.is_active).map((m: any) => (
                    <SelectItem key={m.id} value={m.model_id}>{m.model_id}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="mt-3 pt-3 border-t">
            <Button onClick={() => saveSettingsMut.mutate()} disabled={saveSettingsMut.isPending} className="gap-1.5">
              <Save className="h-3.5 w-3.5" />
              {t("common.save")}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Client-format endpoints */}
      <Card className="card-hover">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <Globe className="h-4 w-4 text-purple-400" />
            <CardTitle className="text-base">{t("settings.clientEndpoints")}</CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground">{t("settings.clientEndpointsDesc")}</p>
          <div className="mt-3 space-y-2">
            {ENDPOINT_CARDS.map((ep) => {
              const active = appSettings.output_protocol === ep.id;
              return (
                <div key={ep.id} className="rounded-lg border border-border p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <Badge variant={active ? "default" : "secondary"} className={active ? "bg-cyan-600 hover:bg-cyan-700" : ""}>{ep.label}</Badge>
                      <code className="text-xs font-mono text-muted-foreground">{ep.method} {ep.path}</code>
                    </div>
                    <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" onClick={() => copyCode(ep.curl)} title={t("settings.copyCurl")}>
                      <Copy className="h-3 w-3" />
                    </Button>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1.5">{ep.desc}</p>
                  <pre className="text-[11px] leading-relaxed bg-muted p-2.5 rounded-md font-mono overflow-x-auto text-foreground mt-2">{ep.curl}</pre>
                </div>
              );
            })}
          </div>
          <p className="text-xs text-muted-foreground mt-3">{t("settings.clientEndpointsHint")}</p>
        </CardContent>
      </Card>

      {/* Network Access */}
      <Card className="card-hover">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <Globe className="h-4 w-4 text-blue-400" />
            <CardTitle className="text-base">{t("settings.networkAccess")}</CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between">
            <div>
              <Label className="text-sm font-medium">{t("settings.lanAccess")}</Label>
              <p className="text-xs text-muted-foreground mt-0.5">{t("settings.lanAccessDesc")}</p>
            </div>
            <Switch checked={appSettings.lan_access} onCheckedChange={(v) => setAppSettings({ ...appSettings, lan_access: v })} />
          </div>
          {appSettings.lan_access && lanIp && (
            <div className="mt-4 pt-4 border-t">
              <Label className="text-sm font-medium">{t("settings.lanAddress")}</Label>
              <p className="text-xs text-muted-foreground mt-0.5 mb-2">{t("settings.lanAddressDesc")}</p>
              <div className="flex items-center gap-2">
                <code className="flex-1 font-mono text-sm bg-muted p-3 rounded-lg text-foreground">{proxyUrl}</code>
                <Button variant="outline" size="icon" className="shrink-0" onClick={() => copyCode(proxyUrl)}>
                  {copied ? <Check className="h-4 w-4 text-green-400" /> : <Copy className="h-4 w-4" />}
                </Button>
              </div>
            </div>
          )}
          <div className="flex justify-end mt-4">
            <Button size="sm" onClick={() => saveSettingsMut.mutate()} disabled={saveSettingsMut.isPending}>
              {saveSettingsMut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" /> : <Save className="h-3.5 w-3.5 mr-1" />}
              {t("common.save")}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Proxy Configuration */}
      <Card className="card-hover">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <Route className="h-4 w-4 text-green-400" />
            <CardTitle className="text-base">{t("settings.proxyConfig")}</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-5">
          <div>
            <Label className="text-sm font-medium">{t("settings.proxyAddress")}</Label>
            <p className="text-xs text-muted-foreground mt-0.5 mb-2">{t("settings.proxyAddressDesc")}</p>
            <div className="flex items-center gap-2">
              <code className="flex-1 font-mono text-sm bg-muted p-3 rounded-lg text-foreground">{proxyUrl}</code>
              <Button variant="outline" size="icon" className="shrink-0" onClick={() => copyCode(proxyUrl)}>
                {copied ? <Check className="h-4 w-4 text-green-400" /> : <Copy className="h-4 w-4" />}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground mt-2">{t("settings.proxyUsageDesc")}</p>
            {appSettings.lan_access && lanIp && (
              <p className="text-xs text-muted-foreground mt-2">
                <span className="text-green-400 font-medium">LAN:</span> {t("settings.lanAddressDesc")}: <code className="bg-muted px-1 rounded">{proxyUrl}</code>
              </p>
            )}
          </div>
          <Separator />
          <div>
            <Label className="text-sm font-medium">{t("settings.callExample")}</Label>
            <p className="text-xs text-muted-foreground mt-0.5 mb-2">{t("settings.callExampleDesc")}</p>
            <div className="relative">
              <pre className="text-xs bg-muted p-4 rounded-lg overflow-x-auto text-foreground font-mono leading-relaxed">{`curl ${proxyUrl}/chat/completions \\
  -H "Content-Type: application/json" \\
  -d '{"model": "your-strategy", "messages": [{"role": "user", "content": "Hello"}]}'`}</pre>
              <Button variant="ghost" size="icon" className="absolute top-2 right-2 h-7 w-7" onClick={() => copyCode(`curl ${proxyUrl}/chat/completions`)}>
                <Copy className="h-3 w-3" />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
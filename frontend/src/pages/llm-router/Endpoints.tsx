// @ts-nocheck
import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getSettings, updateSettings, getLanIp,
  getClientKeys, createClientKey, updateClientKey, deleteClientKey, getEndpointsInfo, getAuthStatus, saveAuthCredentials,
} from './api';
import { useI18n } from './i18n';
import { toast } from './toast';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { Separator } from '@/components/ui/separator';
import { Select, SelectTrigger, SelectContent, SelectItem, SelectValue } from '@/components/ui/select';
import { Copy, Loader2, KeyRound, Link2, Network, ShieldCheck, Save, Trash2 } from "lucide-react";

export default function Endpoints() {
  const { t, locale } = useI18n();
  const qc = useQueryClient();
  const [lanIp, setLanIp] = useState("");

  useEffect(() => {
    getLanIp().then(r => setLanIp(r.data.ip)).catch(() => {});
  }, []);

  const { data: appSettingsData, refetch: refetchSettings } = useQuery({
    queryKey: ["appSettings"],
    queryFn: () => getSettings().then((r) => r.data),
  });
  const [appSettings, setAppSettings] = useState<any>({});
  useEffect(() => { if (appSettingsData) setAppSettings(appSettingsData); }, [appSettingsData]);

  const proxyUrl = appSettings.lan_access && lanIp ? `http://${lanIp}:12002/v1` : "http://127.0.0.1:12002/v1";
  const localProxyUrl = "http://127.0.0.1:12002/v1";

  // --- Virtual keys ---
  const [newKeyName, setNewKeyName] = useState("");
  const { data: clientKeys = [], refetch: refetchClientKeys } = useQuery({ queryKey: ["clientKeys"], queryFn: () => getClientKeys().then((r) => r.data) });
  const createKeyMut = useMutation({
    mutationFn: (name: string) => createClientKey({ name }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["clientKeys"] }); setNewKeyName(""); toast({ title: t("settings.keyCreated"), variant: "success" }); },
    onError: () => toast({ title: t("settings.configSaveFailed"), variant: "destructive" }),
  });
  const toggleKeyMut = useMutation({
    mutationFn: ({ id, is_active }: any) => updateClientKey(id, { is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["clientKeys"] }),
  });
  const deleteKeyMut = useMutation({
    mutationFn: (id: number) => deleteClientKey(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["clientKeys"] }); toast({ title: t("settings.deleted"), variant: "success" }); },
  });

  // --- Endpoint registry ---
  const [enabledGroups, setEnabledGroups] = useState<Record<string, boolean>>({});
  const { data: endpointsInfo } = useQuery({ queryKey: ["endpointsInfo"], queryFn: () => getEndpointsInfo().then((r) => r.data) });
  useEffect(() => {
    if (endpointsInfo?.enabled_groups) setEnabledGroups(endpointsInfo.enabled_groups);
  }, [endpointsInfo]);

  const saveEndpointMut = useMutation({
    mutationFn: () => updateSettings({ ...appSettings, enabled_groups: enabledGroups }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["appSettings"] }); qc.invalidateQueries({ queryKey: ["endpointsInfo"] }); toast({ title: t("settings.saved"), variant: "success" }); },
    onError: () => toast({ title: t("settings.configSaveFailed"), variant: "destructive" }),
  });

  // --- Browser login (OAuth) ---
  const [oauthUsername, setOauthUsername] = useState("admin");
  const [oauthPassword, setOauthPassword] = useState("");
  const { data: authStatus, refetch: refetchAuthStatus } = useQuery({ queryKey: ["authStatus"], queryFn: () => getAuthStatus().then((r) => r.data) });
  const saveCredsMut = useMutation({
    mutationFn: () => saveAuthCredentials({ username: oauthUsername || "admin", password: oauthPassword }),
    onSuccess: () => { refetchAuthStatus(); setOauthPassword(""); toast({ title: t("settings.oauthCredsSaved"), variant: "success" }); },
    onError: (e: any) => toast({ title: t("settings.configSaveFailed"), description: e?.response?.data?.detail, variant: "destructive" }),
  });

  const copyKey = (text: string) => {
    navigator.clipboard.writeText(text);
    toast({ title: t("common.copied"), variant: "success" });
  };

  const groupIds: string[] = endpointsInfo ? Array.from(new Set((endpointsInfo.endpoints || []).map((e: any) => e.group))) : [];
  const endpointDesc = (e: any) => (locale.startsWith("zh") ? e.desc?.zh : e.desc?.en) || e.path;

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{t("endpoints.title")}</h1>
        <p className="text-sm text-muted-foreground mt-1">{t("endpoints.subtitle")}</p>
      </div>

      {/* Access URLs */}
      <Card className="card-hover">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2"><Link2 className="h-4 w-4 text-cyan-400" /><CardTitle className="text-base">{t("settings.accessUrls")}</CardTitle></div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <Label className="text-xs text-muted-foreground">{t("settings.localUrl")}</Label>
            <div className="flex items-center gap-2 mt-1.5">
              <code className="flex-1 font-mono text-sm bg-muted p-3 rounded-lg text-foreground">{localProxyUrl}</code>
              <Button variant="outline" size="icon" className="shrink-0" onClick={() => copyKey(localProxyUrl)}><Copy className="h-4 w-4" /></Button>
            </div>
          </div>
          {appSettings.lan_access && lanIp && (
            <div>
              <Label className="text-xs text-muted-foreground">{t("settings.lanAddress")}</Label>
              <div className="flex items-center gap-2 mt-1.5">
                <code className="flex-1 font-mono text-sm bg-muted p-3 rounded-lg text-foreground">{proxyUrl}</code>
                <Button variant="outline" size="icon" className="shrink-0" onClick={() => copyKey(proxyUrl)}><Copy className="h-4 w-4" /></Button>
              </div>
            </div>
          )}
          <p className="text-xs text-muted-foreground">{t("settings.accessUrlsDesc")}</p>
        </CardContent>
      </Card>

      {/* Access authentication */}
      <Card className="card-hover">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2"><KeyRound className="h-4 w-4 text-amber-400" /><CardTitle className="text-base">{t("settings.authMode")}</CardTitle></div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="pr-4">
              <Label className="text-sm font-medium">{t("settings.authModeLabel")}</Label>
              <p className="text-xs text-muted-foreground mt-0.5">
                {appSettings.auth_mode === "oauth"
                  ? t("settings.authOAuthDesc")
                  : appSettings.auth_mode === "virtual_key"
                    ? t("settings.authVirtualKeyDesc")
                    : t("settings.authOpenDesc")}
              </p>
            </div>
            <Select value={appSettings.auth_mode || "open"} onValueChange={(v) => setAppSettings({ ...appSettings, auth_mode: v })}>
              <SelectTrigger className="w-36 h-9 text-sm shrink-0"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="open">{t("settings.authOpen")}</SelectItem>
                <SelectItem value="virtual_key">{t("settings.authVirtualKey")}</SelectItem>
                <SelectItem value="oauth">{t("settings.authOAuth")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Separator />
          <div>
            <div className="flex items-center justify-between mb-2 gap-2">
              <Label className="text-sm font-medium shrink-0">{t("settings.virtualKeys")}</Label>
              <div className="flex gap-2">
                <Input value={newKeyName} onChange={(e) => setNewKeyName(e.target.value)} placeholder={t("settings.newKeyName")} className="h-8 w-36 text-xs" />
                <Button size="sm" className="h-8 gap-1" onClick={() => createKeyMut.mutate(newKeyName)} disabled={createKeyMut.isPending}>
                  {createKeyMut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <KeyRound className="h-3.5 w-3.5" />}
                  {t("settings.generateKey")}
                </Button>
              </div>
            </div>
            {(clientKeys as any[]).length === 0 ? (
              <div className="text-center text-muted-foreground py-6 border border-dashed rounded-lg text-sm">{t("settings.noKeys")}</div>
            ) : (
              <div className="space-y-2 max-h-64 overflow-y-auto">
                {(clientKeys as any[]).map((k: any) => (
                  <div key={k.id} className="flex items-center gap-3 rounded-lg border p-3">
                    <Switch checked={k.is_active} onCheckedChange={(v) => toggleKeyMut.mutate({ id: k.id, is_active: v })} />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{k.name || t("settings.unnamedKey")}</p>
                      <button className="font-mono text-xs text-muted-foreground truncate block max-w-full hover:underline" onClick={() => copyKey(k.key_value)}>{k.key_value}</button>
                    </div>
                    <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" onClick={() => copyKey(k.key_value)}><Copy className="h-3.5 w-3.5" /></Button>
                    <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive shrink-0" onClick={() => { if (confirm(t("settings.confirmDeleteKey"))) deleteKeyMut.mutate(k.id); }}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="flex justify-end">
            <Button size="sm" onClick={() => saveEndpointMut.mutate()} disabled={saveEndpointMut.isPending}>
              {saveEndpointMut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" /> : <Save className="h-3.5 w-3.5 mr-1" />}
              {t("common.save")}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Browser login (OAuth) */}
      <Card className="card-hover">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-emerald-400" /><CardTitle className="text-base">{t("settings.oauthCard")}</CardTitle>
            {authStatus && (
              <Badge variant={authStatus.configured ? "success" : "secondary"} className="text-[10px]">
                {authStatus.configured ? t("settings.oauthConfigured") : t("settings.oauthNotConfigured")}
              </Badge>
            )}
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-xs text-muted-foreground">{t("settings.oauthCardDesc")}</p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <Label className="text-xs text-muted-foreground">{t("settings.oauthUsername")}</Label>
              <Input value={oauthUsername} onChange={(e) => setOauthUsername(e.target.value)} className="mt-1.5 h-9 text-sm" />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">{authStatus?.configured ? t("settings.oauthNewPassword") : t("settings.oauthPassword")}</Label>
              <Input type="password" value={oauthPassword} onChange={(e) => setOauthPassword(e.target.value)} placeholder={authStatus?.configured ? "••••••" : ""} className="mt-1.5 h-9 text-sm" />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">{t("settings.oauthTokenTtl")}</Label>
              <Input type="number" min="1" value={appSettings.oauth_token_hours ?? 24} onChange={(e) => setAppSettings({ ...appSettings, oauth_token_hours: Number(e.target.value) })} className="mt-1.5 h-9 text-sm" />
            </div>
          </div>
          <div className="flex items-center justify-between flex-wrap gap-2">
            <Button size="sm" className="gap-1.5" onClick={() => saveCredsMut.mutate()} disabled={saveCredsMut.isPending || oauthPassword.length < 4}>
              {saveCredsMut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <KeyRound className="h-3.5 w-3.5" />}
              {authStatus?.configured ? t("settings.oauthUpdateCreds") : t("settings.oauthSetCreds")}
            </Button>
            <p className="text-[11px] text-muted-foreground">{t("settings.oauthCredsHint")}</p>
          </div>
          <Separator />
          <div>
            <Label className="text-xs text-muted-foreground">{t("settings.oauthFlowTitle")}</Label>
            <pre className="text-xs bg-muted p-4 rounded-lg overflow-x-auto text-foreground font-mono leading-relaxed mt-2">{t("settings.oauthFlowSteps")}</pre>
          </div>
        </CardContent>
      </Card>

      {/* Endpoint groups + registry */}
      <Card className="card-hover">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2"><Network className="h-4 w-4 text-purple-400" /><CardTitle className="text-base">{t("settings.endpointList")}</CardTitle></div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <Label className="text-sm font-medium">{t("settings.endpointGroups")}</Label>
            <p className="text-xs text-muted-foreground mt-0.5 mb-2">{t("settings.endpointGroupsDesc")}</p>
            <div className="flex flex-wrap gap-x-6 gap-y-2">
              {groupIds.map((g) => (
                <div key={g} className="flex items-center gap-2">
                  <Switch checked={enabledGroups[g] !== false} onCheckedChange={(v) => setEnabledGroups({ ...enabledGroups, [g]: v })} />
                  <Label className="text-sm">{t("settings.group_" + g)}</Label>
                </div>
              ))}
            </div>
          </div>
          <Separator />
          <div>
            <Label className="text-sm font-medium">{t("settings.endpointList")}</Label>
            <p className="text-xs text-muted-foreground mt-0.5 mb-2">{t("settings.endpointListDesc")}</p>
            <div className="space-y-1.5">
              {(endpointsInfo?.endpoints || []).map((e: any, i: number) => (
                <div key={i} className={`flex items-center gap-3 rounded-lg border p-2.5 ${enabledGroups[e.group] === false ? "opacity-40" : ""}`}>
                  <Badge variant={e.method === "GET" ? "secondary" : "default"} className="font-mono text-[10px] w-14 justify-center shrink-0">{e.method}</Badge>
                  <code className="flex-1 font-mono text-xs truncate">{e.path}</code>
                  <span className="text-xs text-muted-foreground truncate max-w-[240px] hidden md:block">{endpointDesc(e)}</span>
                </div>
              ))}
            </div>
            <p className="text-xs text-muted-foreground mt-3">{t("settings.aliasHint")}</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

import React, { useState, useEffect } from "react";
import { useI18n, LOCALES } from "../i18n";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getSettings, updateSettings, getProviders, getModels, getBackupConfig, updateBackupConfig, createBackup,
  listBackups, restoreLocalBackup, deleteBackup, downloadBackupUrl, getLanIp,
} from "../services/api";
import { toast } from "../stores/toast";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Switch } from "../components/ui/switch";
import { Badge } from "../components/ui/badge";
import { Separator } from "../components/ui/separator";
import { Select, SelectTrigger, SelectContent, SelectItem, SelectValue } from "../components/ui/select";
import { Palette, Globe, Copy, Check, Database, Download, Upload, Trash2, Loader2, HardDrive, Clock, FolderOpen, RefreshCw, ShieldCheck, Sun, Moon, Box, Save } from "lucide-react";
export default function SettingsPage() {
  const { t, locale, setLocale } = useI18n();
  const [dark, setDark] = useState(document.documentElement.classList.contains("dark"));
  const [copied, setCopied] = useState(false);
  const [backing, setBacking] = useState(false);
  const [restoring, setRestoring] = useState<string | null>(null);
  const [deletingBackup, setDeletingBackup] = useState<string | null>(null);
  const [appSettings, setAppSettings] = useState({ output_protocol: "openai", default_model: "", default_provider_id: 0, lan_access: false });
  const [lanIp, setLanIp] = useState("");

  useEffect(() => {
    getLanIp().then(r => setLanIp(r.data.ip)).catch(() => {});
  }, []);

  const toggleTheme = () => {
    const next = !dark;
    setDark(next);
    if (next) { document.documentElement.classList.add("dark"); }
    else { document.documentElement.classList.remove("dark"); }
  };

  const copyCode = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    toast({ title: t("common.copied"), variant: "success" });
    setTimeout(() => setCopied(false), 2000);
  };

  const { data: appSettingsData, refetch: refetchSettings } = useQuery({
    queryKey: ["appSettings"],
    queryFn: () => getSettings().then((r) => r.data),
  });

  const [defaultProviderId, setDefaultProviderId] = useState<number>(0);
  const { data: providersList = [] } = useQuery({ queryKey: ["providers"], queryFn: () => getProviders().then((r) => r.data) });
  const { data: modelsList = [] } = useQuery({ queryKey: ["models", defaultProviderId], queryFn: () => getModels(defaultProviderId).then((r) => r.data), enabled: !!defaultProviderId });

  useEffect(() => {
    if (appSettingsData) {
      setAppSettings(appSettingsData);
      setDefaultProviderId(appSettingsData.default_provider_id || 0);
    }
  }, [appSettingsData]);

  const saveSettingsMut = useMutation({
    mutationFn: () => updateSettings(appSettings),
    onSuccess: () => { refetchSettings(); toast({ title: t("settings.saved"), variant: "success" }); },
    onError: () => toast({ title: t("settings.configSaveFailed"), variant: "destructive" }),
  });

  const { data: backupConfig, refetch: refetchConfig } = useQuery({
    queryKey: ["backupConfig"],
    queryFn: () => getBackupConfig().then((r) => r.data),
  });

  const { data: backups = [], refetch: refetchBackups } = useQuery({
    queryKey: ["backups"],
    queryFn: () => listBackups().then((r) => r.data),
  });

  const [configForm, setConfigForm] = useState({
    backup_dir: "", auto_backup_enabled: false, auto_backup_interval_hours: 24, max_backups: 30,
  });

  useEffect(() => {
    if (backupConfig) {
      setConfigForm({
        backup_dir: backupConfig.backup_dir || "",
        auto_backup_enabled: backupConfig.auto_backup_enabled || false,
        auto_backup_interval_hours: backupConfig.auto_backup_interval_hours || 24,
        max_backups: backupConfig.max_backups || 30,
      });
    }
  }, [backupConfig]);

  const saveConfigMut = useMutation({
    mutationFn: () => updateBackupConfig(configForm),
    onSuccess: () => { refetchConfig(); toast({ title: t("settings.configSaved"), variant: "success" }); },
    onError: () => toast({ title: t("settings.configSaveFailed"), variant: "destructive" }),
  });

  const createBackupMut = useMutation({
    mutationFn: () => { setBacking(true); return createBackup(); },
    onSuccess: (res) => {
      setBacking(false); refetchBackups();
      toast({ title: t("settings.backupCreated"), description: res.data.filename + " (" + res.data.size_mb + "MB)", variant: "success" });
    },
    onError: () => { setBacking(false); toast({ title: t("settings.backupFailed"), variant: "destructive" }); },
  });

  const restoreMut = useMutation({
    mutationFn: (filename: string) => { setRestoring(filename); return restoreLocalBackup(filename); },
    onSuccess: () => { setRestoring(null); toast({ title: t("settings.restored"), description: t("settings.restoreHint"), variant: "success" }); },
    onError: () => { setRestoring(null); toast({ title: t("settings.restoreFailed"), variant: "destructive" }); },
  });

  const deleteBackupMut = useMutation({
    mutationFn: (filename: string) => { setDeletingBackup(filename); return deleteBackup(filename); },
    onSuccess: () => { setDeletingBackup(null); refetchBackups(); toast({ title: t("settings.deleted"), variant: "success" }); },
    onError: () => { setDeletingBackup(null); toast({ title: t("settings.deleteFailed"), variant: "destructive" }); },
  });

  const handleFileRestore = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.name.endsWith(".db")) { toast({ title: t("settings.selectDbFile"), variant: "destructive" }); return; }
    const formData = new FormData();
    formData.append("file", file);
    try {
      const resp = await fetch("/api/backup/restore", { method: "POST", body: formData });
      const data = await resp.json();
      if (data.success) { toast({ title: t("settings.restored"), description: t("settings.restoreHint"), variant: "success" }); }
      else { toast({ title: t("settings.restoreFailed"), variant: "destructive" }); }
    } catch { toast({ title: t("settings.restoreFailed"), variant: "destructive" }); }
    e.target.value = "";
  };

  const formatDate = (iso: string) => { try { return new Date(iso).toLocaleString(); } catch { return iso; } };

  const proxyUrl = appSettings.lan_access && lanIp ? `http://${lanIp}:12002/v1` : "http://127.0.0.1:12002/v1";

  return (
    <div className="space-y-6 max-w-3xl">

      {/* Appearance */}
      <Card className="card-hover">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2"><Palette className="h-4 w-4 text-cyan-400" /><CardTitle className="text-base">{t("settings.appearance")}</CardTitle></div>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between">
            <div>
              <Label className="text-sm font-medium">{t("settings.themeMode")}</Label>
              <p className="text-xs text-muted-foreground mt-0.5">{t("settings.themeDesc")}</p>
            </div>
            <button onClick={toggleTheme} className="relative inline-flex h-8 w-14 items-center rounded-full transition-colors" style={{ background: dark ? "#0ea5e9" : "#e2e8f0" }}>
              <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-white transition-transform" style={{ transform: dark ? "translateX(30px)" : "translateX(2px)" }}>
                {dark ? <Moon className="h-3.5 w-3.5 text-sky-600" /> : <Sun className="h-3.5 w-3.5 text-amber-500" />}
              </span>
            </button>
          </div>
          <div className="flex items-center justify-between mt-4 pt-4 border-t">
            <div>
              <Label className="text-sm font-medium">{t("settings.language")}</Label>
              <p className="text-xs text-muted-foreground mt-0.5">{t("settings.languageDesc")}</p>
            </div>
            <div className="flex gap-2">
              {LOCALES.map((l) => (
                <Button key={l.value} variant={locale === l.value ? "default" : "outline"} size="sm" className={locale === l.value ? "bg-cyan-600 hover:bg-cyan-700" : ""} onClick={() => setLocale(l.value)}>
                  {l.label}
                </Button>
              ))}
            </div>
          </div>

        </CardContent>
      </Card>
      {/* Route Management Model */}
      <Card className="card-hover">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2"><Box className="h-4 w-4 text-amber-400" /><CardTitle className="text-base">{t("settings.routeModel")}</CardTitle></div>
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

      {/* Output Protocol */}
      <Card className="card-hover">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2"><Globe className="h-4 w-4 text-purple-400" /><CardTitle className="text-base">{t("settings.outputProtocol")}</CardTitle></div>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between">
            <div>
              <Label className="text-sm font-medium">{t("settings.responseFormat")}</Label>
              <p className="text-xs text-muted-foreground mt-0.5">{t("settings.responseFormatDesc")}</p>
            </div>
            <div className="flex gap-2">
              {["openai", "claude", "gemini"].map((p) => (
                <Button key={p} variant={appSettings.output_protocol === p ? "default" : "outline"} size="sm" className={appSettings.output_protocol === p ? "bg-cyan-600 hover:bg-cyan-700" : ""} onClick={() => { setAppSettings({ ...appSettings, output_protocol: p }); }}>
                  {p === "openai" ? "OpenAI" : p === "claude" ? "Claude" : "Gemini"}
                </Button>
              ))}
            </div>
          </div>
          <p className="text-xs text-muted-foreground mt-3">
            {appSettings.output_protocol === "openai" && t("settings.openaiFormatDesc")}
            {appSettings.output_protocol === "claude" && t("settings.claudeFormatDesc")}
            {appSettings.output_protocol === "gemini" && t("settings.geminiFormatDesc")}
          </p>
          <div className="flex justify-end mt-4">
            <Button size="sm" onClick={() => saveSettingsMut.mutate()} disabled={saveSettingsMut.isPending}>
              {saveSettingsMut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" /> : <ShieldCheck className="h-3.5 w-3.5 mr-1" />}
              {t("common.save")}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Network Access */}
      <Card className="card-hover">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2"><Globe className="h-4 w-4 text-blue-400" /><CardTitle className="text-base">{t("settings.networkAccess")}</CardTitle></div>
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
          <div className="flex items-center gap-2"><Globe className="h-4 w-4 text-green-400" /><CardTitle className="text-base">{t("settings.proxyConfig")}</CardTitle></div>
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

      {/* Backup and Restore */}
      <Card className="card-hover">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2"><Database className="h-4 w-4 text-blue-400" /><CardTitle className="text-base">{t("settings.backupRestore")}</CardTitle></div>
        </CardHeader>
        <CardContent className="space-y-5">

          {/* Backup Config */}
          <div>
            <Label className="text-sm font-medium">{t("settings.backupConfig")}</Label>
            <div className="mt-3 space-y-4">
              <div>
                <Label className="text-xs text-muted-foreground">{t("settings.backupFolder")}</Label>
                <div className="flex gap-2 mt-1.5">
                  <Input value={configForm.backup_dir} onChange={(e) => setConfigForm({ ...configForm, backup_dir: e.target.value })} placeholder="backup folder path" className="font-mono text-xs" />
                  <Button variant="outline" size="icon" className="shrink-0"><FolderOpen className="h-4 w-4" /></Button>
                </div>
              </div>
              <div className="grid grid-cols-3 gap-4">
                <div className="flex items-center gap-3 col-span-1">
                  <Switch checked={configForm.auto_backup_enabled} onCheckedChange={(v) => setConfigForm({ ...configForm, auto_backup_enabled: v })} />
                  <Label className="text-sm">{t("settings.autoBackup")}</Label>
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground">{t("settings.intervalHours")}</Label>
                  <Input type="number" min="1" value={configForm.auto_backup_interval_hours} onChange={(e) => setConfigForm({ ...configForm, auto_backup_interval_hours: Number(e.target.value) })} className="mt-1.5" />
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground">{t("settings.maxBackups")}</Label>
                  <Input type="number" min="1" value={configForm.max_backups} onChange={(e) => setConfigForm({ ...configForm, max_backups: Number(e.target.value) })} className="mt-1.5" />
                </div>
              </div>
              <div className="flex justify-end">
                <Button size="sm" onClick={() => saveConfigMut.mutate()} disabled={saveConfigMut.isPending}>
                  {saveConfigMut.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" /> : <ShieldCheck className="h-3.5 w-3.5 mr-1" />}
                  {t("settings.saveConfig")}
                </Button>
              </div>
            </div>
          </div>

          <Separator />

          {/* Backup List */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Label className="text-sm font-medium">{t("settings.backupList")}</Label>
                <Badge variant="secondary" className="text-xs">{backups.length}</Badge>
              </div>
              <div className="flex gap-2">
                <Button variant="ghost" size="sm" className="h-7 gap-1" onClick={() => refetchBackups()}>
                  <RefreshCw className="h-3 w-3" />{t("common.refresh")}
                </Button>
                <Button variant="outline" size="sm" className="h-7 gap-1" onClick={() => createBackupMut.mutate()} disabled={backing}>
                  {backing ? <Loader2 className="h-3 w-3 animate-spin" /> : <HardDrive className="h-3 w-3" />}
                  {t("settings.createBackup")}
                </Button>
              </div>
            </div>
            {backups.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8 text-muted-foreground border border-dashed rounded-lg">
                <Database className="h-8 w-8 mb-2 opacity-20" />
                <p className="text-sm">{t("settings.noBackups")}</p>
                <p className="text-xs opacity-60 mt-1">{t("settings.noBackupsHint")}</p>
              </div>
            ) : (
              <div className="space-y-2 max-h-72 overflow-y-auto">
                {backups.map((b: any) => (
                  <div key={b.filename} className="flex items-center gap-3 rounded-lg border border-border p-3 hover:bg-accent/30 transition-colors group">
                    <Database className="h-4 w-4 text-muted-foreground shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium font-mono truncate">{b.filename}</div>
                      <div className="flex items-center gap-3 text-xs text-muted-foreground mt-0.5">
                        <span className="flex items-center gap-1"><Clock className="h-3 w-3" />{formatDate(b.created_at)}</span>
                        <span>{b.size_mb} MB</span>
                      </div>
                    </div>
                    <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                      <Button variant="ghost" size="sm" className="h-7 gap-1 text-xs" onClick={() => restoreMut.mutate(b.filename)} disabled={restoring === b.filename}>
                        {restoring === b.filename ? <Loader2 className="h-3 w-3 animate-spin" /> : <Upload className="h-3 w-3" />}
                        {t("settings.restore")}
                      </Button>
                      <Button variant="ghost" size="sm" className="h-7 gap-1 text-xs" asChild>
                        <a href={downloadBackupUrl(b.filename)} download><Download className="h-3 w-3" />{t("settings.download")}</a>
                      </Button>
                      <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" onClick={() => deleteBackupMut.mutate(b.filename)} disabled={deletingBackup === b.filename}>
                        {deletingBackup === b.filename ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <Separator />

          {/* Upload Restore */}
          <div>
            <Label className="text-sm font-medium">{t("settings.uploadRestore")}</Label>
            <p className="text-xs text-muted-foreground mt-0.5 mb-2">{t("settings.uploadRestoreDesc")}</p>
            <input type="file" accept=".db" onChange={handleFileRestore} className="hidden" id="restore-upload" />
            <Button variant="outline" size="sm" className="gap-1.5" onClick={() => document.getElementById("restore-upload")?.click()}>
              <Upload className="h-3.5 w-3.5" />{t("settings.selectDbFile")}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}


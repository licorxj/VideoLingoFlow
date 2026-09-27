// @ts-nocheck
import React, { useState, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getProviders, getKeys, createKey, createKeysBatch, updateKey, deleteKey, testKey, getOauthProfiles, startOauthLogin, getOauthStatus } from './api';
import { toast } from './toast';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectTrigger, SelectContent, SelectItem, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Plus, Trash2, Zap, KeyRound, Loader2, Globe, Copy } from "lucide-react";

export default function ApiKeys() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [selectedProvider, setSelectedProvider] = useState<number | null>(null);
  const [form, setForm] = useState({ provider_id: 0, key_value: "", alias: "", weight: 1 });
  const [testingId, setTestingId] = useState<number | null>(null);

  const { data: providers = [] } = useQuery({
    queryKey: ["providers"],
    queryFn: () => getProviders().then((r) => r.data),
  });

  const { data: oauthProfiles = {} } = useQuery({ queryKey: ["oauthProfiles"], queryFn: () => getOauthProfiles().then((r) => r.data) });

  const { data: keys = [] } = useQuery({
    queryKey: ["keys", selectedProvider],
    queryFn: () => selectedProvider ? getKeys(selectedProvider).then((r) => r.data) : [],
    enabled: !!selectedProvider,
  });

  const createMut = useMutation({
    mutationFn: (d: any) => createKey(d),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["keys"] }); setOpen(false); toast({ title: "Key 添加成功", variant: "success" }); },
    onError: (e: any) => toast({ title: "添加失败", description: e?.response?.data?.detail, variant: "destructive" }),
  });

  const createBatchMut = useMutation({
    mutationFn: (d: any) => createKeysBatch(d.provider_id, d),
    onSuccess: (res: any) => {
      qc.invalidateQueries({ queryKey: ["keys"] }); setOpen(false);
      const created = res.data?.created?.length ?? 0;
      const dup = res.data?.duplicates ?? 0;
      toast({ title: `已添加 ${created} 个 Key`, description: dup > 0 ? `跳过重复 ${dup} 个` : undefined, variant: "success" });
    },
    onError: (e: any) => toast({ title: "批量添加失败", description: e?.response?.data?.detail, variant: "destructive" }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteKey(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["keys"] }); toast({ title: "已删除", variant: "success" }); },
  });

  const testMut = useMutation({
    mutationFn: (id: number) => { setTestingId(id); return testKey(id); },
    onSuccess: (res) => {
      setTestingId(null);
      toast({ title: res.data.success ? "测试成功" : "测试失败", description: res.data.message + (res.data.latency_ms ? ` (${res.data.latency_ms}ms)` : ""), variant: res.data.success ? "success" : "destructive" });
      qc.invalidateQueries({ queryKey: ["keys"] });
    },
    onError: () => { setTestingId(null); toast({ title: "测试失败", variant: "destructive" }); },
  });

  const openCreate = () => { setForm({ provider_id: selectedProvider || 0, key_value: "", alias: "", weight: 1 }); setOpen(true); };

  // Multi-line input: one key per line, trimmed, empty lines and duplicates removed
  const parsedKeys = Array.from(new Set(form.key_value.split(/\r?\n/).map((s) => s.trim()).filter(Boolean)));
  const multi = parsedKeys.length > 1;

  // --- OAuth browser login flow ---
  const currentProvider = providers.find((p: any) => p.id === selectedProvider);
  // Resolve the OAuth profile: explicit auth_type first, then name/base_url keyword match
  const matchedProfile = (() => {
    const p = currentProvider as any;
    if (!p) return null;
    if (p.auth_type && p.auth_type !== "api_key") return p.auth_type;
    const base = (p.base_url || "").toLowerCase();
    const name = (p.name || "").toLowerCase();
    for (const [id, prof] of Object.entries(oauthProfiles as any)) {
      if (id.startsWith("_")) continue;
      const kws: string[] = (prof as any).match_keywords || [];
      if (kws.some((k) => base.includes(k.toLowerCase()) || name.includes(k.toLowerCase()))) return id;
    }
    return null;
  })();
  const isOauthProvider = !!matchedProfile;
  const [oauthWaiting, setOauthWaiting] = useState(false);
  const [deviceUserCode, setDeviceUserCode] = useState("");
  const pollTimer = useRef<any>(null);

  const handleOauthLogin = async () => {
    if (!form.provider_id) return;
    setOauthWaiting(true);
    setDeviceUserCode("");
    try {
      const res = await startOauthLogin({ provider_id: form.provider_id, profile_id: matchedProfile });
      const flowType = res.data.flow || "authorization_code";
      const openUrl = res.data.verification_uri || res.data.authorize_url;
      if (openUrl) window.open(openUrl, "_blank");
      if (flowType !== "authorization_code") setDeviceUserCode(res.data.user_code || "");
      const sessionId = res.data.session_id;
      const startedAt = Date.now();
      const poll = async () => {
        try {
          const st = await getOauthStatus(sessionId);
          if (st.data.status === "success") {
            setOauthWaiting(false);
            qc.invalidateQueries({ queryKey: ["keys"] });
            setOpen(false);
            toast({ title: "OAuth 登录成功，令牌已保存", variant: "success" });
            return;
          }
          if (st.data.status === "failed") {
            setOauthWaiting(false);
            toast({ title: "OAuth 登录失败", description: st.data.error, variant: "destructive" });
            return;
          }
          if (st.data.status === "expired" || Date.now() - startedAt > 300000) {
            setOauthWaiting(false);
            toast({ title: "授权超时，请重试", variant: "destructive" });
            return;
          }
          if (st.data.user_code) setDeviceUserCode(st.data.user_code);
          pollTimer.current = setTimeout(poll, 2000);
        } catch {
          setOauthWaiting(false);
        }
      };
      pollTimer.current = setTimeout(poll, 2000);
    } catch (e: any) {
      setOauthWaiting(false);
      toast({ title: "OAuth 登录失败", description: e?.response?.data?.detail, variant: "destructive" });
    }
  };

  const save = () => {
    if (!parsedKeys.length || !form.provider_id) return;
    if (multi) {
      createBatchMut.mutate({ provider_id: form.provider_id, keys: parsedKeys, alias_prefix: form.alias.trim() || "Key", weight: form.weight });
    } else {
      createMut.mutate({ provider_id: form.provider_id, key_value: parsedKeys[0], alias: form.alias, weight: form.weight });
    }
  };

  const statusMap: Record<string, { label: string; variant: any }> = {
    active: { label: "活跃", variant: "success" },
    inactive: { label: "禁用", variant: "secondary" },
    expired: { label: "过期", variant: "destructive" },
    rate_limited: { label: "限流", variant: "warning" },
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">API Key 管理</h1>
          <p className="text-sm text-muted-foreground mt-1">管理各平台的 API 密钥</p>
        </div>
        <Button onClick={openCreate} disabled={!selectedProvider} className="gap-2"><Plus className="h-4 w-4" />添加 Key</Button>
      </div>

      {/* Provider tabs */}
      <div className="flex gap-2 flex-wrap">
        {providers.map((p: any) => (
          <Button key={p.id} variant={selectedProvider === p.id ? "default" : "outline"} size="sm" className="gap-2" onClick={() => setSelectedProvider(p.id)}>
            {p.name}
          </Button>
        ))}
        {providers.length === 0 && <p className="text-sm text-muted-foreground">请先添加上游平台</p>}
      </div>

      {selectedProvider ? (
        keys.length === 0 ? (
          <Card className="border-dashed">
            <CardContent className="flex flex-col items-center justify-center py-12">
              <KeyRound className="h-10 w-10 text-muted-foreground/30 mb-3" />
              <p className="text-muted-foreground">该平台还没有 Key</p>
              <Button onClick={openCreate} variant="outline" size="sm" className="mt-3 gap-2"><Plus className="h-4 w-4" />添加</Button>
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>别名</TableHead>
                    <TableHead>Key</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead>权重</TableHead>
                    <TableHead>错误信息</TableHead>
                    <TableHead className="text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {keys.map((k: any) => (
                    <TableRow key={k.id} className="group">
                      <TableCell className="font-medium">
                        {k.alias || "-"}
                        {k.oauth_profile && <Badge variant="outline" className="ml-1.5 text-[10px]">OAuth</Badge>}
                        {!!k.oauth_expires_at && (
                          <p className="text-[10px] font-normal text-muted-foreground">令牌到期: {new Date(k.oauth_expires_at * 1000).toLocaleString()}</p>
                        )}
                      </TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">{k.key_masked}</TableCell>
                      <TableCell>
                        <Badge variant={statusMap[k.status]?.variant || "secondary"}>{statusMap[k.status]?.label || k.status}</Badge>
                      </TableCell>
                      <TableCell>{k.weight}</TableCell>
                      <TableCell className="text-xs text-destructive max-w-xs truncate">{k.last_error || "-"}</TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <Button variant="ghost" size="sm" className="h-8 gap-1" onClick={() => testMut.mutate(k.id)} disabled={testingId === k.id}>
                            {testingId === k.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />}
                            测试
                          </Button>
                          <Button variant="ghost" size="icon" className="h-8 w-8 text-destructive" onClick={() => { if (confirm("确定删除？")) deleteMut.mutate(k.id); }}>
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        )
      ) : (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-12">
            <p className="text-sm text-muted-foreground">请选择一个平台来查看 Key</p>
          </CardContent>
        </Card>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>添加 API Key</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>平台</Label>
              <Select value={String(form.provider_id)} onValueChange={(v) => setForm({ ...form, provider_id: Number(v) })}>
                <SelectTrigger><SelectValue placeholder="选择平台" /></SelectTrigger>
                <SelectContent>{providers.map((p: any) => <SelectItem key={p.id} value={String(p.id)}>{p.name}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            {isOauthProvider ? (
              <>
                <div>
                  <Label>API Key</Label>
                  <div className="rounded-lg border border-dashed p-4 text-center space-y-2">
                    <p className="text-sm text-muted-foreground">此平台通过浏览器 OAuth 登录获取令牌，无需手动填写 Key</p>
                    <Button onClick={handleOauthLogin} disabled={oauthWaiting} className="gap-2">
                      {oauthWaiting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Globe className="h-4 w-4" />}
                      {oauthWaiting ? "已打开浏览器，等待授权..." : "使用浏览器登录获取令牌"}
                    </Button>
                    {oauthWaiting && deviceUserCode && (
                      <div className="text-xs text-muted-foreground flex items-center justify-center gap-1.5 flex-wrap">
                        在打开的页面输入设备码：
                        <code className="font-mono text-sm font-bold text-foreground select-all tracking-wider">{deviceUserCode}</code>
                        <button
                          className="inline-flex items-center gap-0.5 text-[11px] text-cyan-600 hover:underline"
                          onClick={() => { navigator.clipboard.writeText(deviceUserCode.trim().toUpperCase()); toast({ title: "设备码已复制，请直接粘贴", variant: "success" }); }}
                        >
                          <Copy className="h-3 w-3" />复制
                        </button>
                        <span className="text-[11px] opacity-70">（建议直接复制粘贴；手动输入请切换英文输入法，避免全角字符）</span>
                      </div>
                    )}
                    {oauthWaiting && <p className="text-xs text-muted-foreground">完成登录后本窗口会自动关闭并保存令牌</p>}
                  </div>
                </div>
                <div><Label>权重 (用于加权均衡)</Label><Input type="number" min="1" value={form.weight} onChange={(e) => setForm({ ...form, weight: Number(e.target.value) })} /></div>
              </>
            ) : (
              <>
                <div>
                  <Label>API Key{multi ? `（已识别 ${parsedKeys.length} 个）` : ""}</Label>
                  <Textarea
                    value={form.key_value}
                    onChange={(e) => setForm({ ...form, key_value: e.target.value })}
                    placeholder="sk-...  （每行一个 Key，可批量粘贴）"
                    className="font-mono text-xs min-h-[120px]"
                  />
                  {multi && <p className="text-xs text-muted-foreground mt-1">将按别名前缀自动编号命名</p>}
                </div>
                <div>
                  <Label>{multi ? "别名前缀" : "别名"}</Label>
                  <Input value={form.alias} onChange={(e) => setForm({ ...form, alias: e.target.value })} placeholder={multi ? "Key（自动命名为 Key-1、Key-2…）" : "可选，方便识别这个 Key"} />
                </div>
                <div><Label>权重 (用于加权均衡)</Label><Input type="number" min="1" value={form.weight} onChange={(e) => setForm({ ...form, weight: Number(e.target.value) })} /></div>
              </>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>取消</Button>
            {!isOauthProvider && (
              <Button onClick={save} disabled={!parsedKeys.length || !form.provider_id || createMut.isPending || createBatchMut.isPending}>
                保存{multi ? `（${parsedKeys.length} 个）` : ""}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

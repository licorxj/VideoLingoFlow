import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getProviders, getKeys, createKey, updateKey, deleteKey, testKey } from "../services/api";
import { toast } from "../stores/toast";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Badge } from "../components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../components/ui/dialog";
import { Select, SelectTrigger, SelectContent, SelectItem, SelectValue } from "../components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Plus, Trash2, Zap, KeyRound, Loader2 } from "lucide-react";

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
  const save = () => createMut.mutate(form);

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
                      <TableCell className="font-medium">{k.alias || "-"}</TableCell>
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
            <div><Label>API Key</Label><Input type="password" value={form.key_value} onChange={(e) => setForm({ ...form, key_value: e.target.value })} placeholder="sk-..." /></div>
            <div><Label>别名</Label><Input value={form.alias} onChange={(e) => setForm({ ...form, alias: e.target.value })} placeholder="可选，方便识别这个 Key" /></div>
            <div><Label>权重 (用于加权均衡)</Label><Input type="number" min="1" value={form.weight} onChange={(e) => setForm({ ...form, weight: Number(e.target.value) })} /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>取消</Button>
            <Button onClick={save} disabled={!form.key_value || !form.provider_id}>保存</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

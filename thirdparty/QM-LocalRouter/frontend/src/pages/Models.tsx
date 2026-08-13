import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getProviders, getModels, createModel, updateModel, deleteModel, syncModels } from "../services/api";
import { toast } from "../stores/toast";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "../components/ui/dialog";
import { Select, SelectTrigger, SelectContent, SelectItem, SelectValue } from "../components/ui/select";
import { Switch } from "../components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table";
import { Plus, Trash2, RefreshCw, Cpu, Loader2 } from "lucide-react";

export default function Models() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [selectedProvider, setSelectedProvider] = useState<number | null>(null);
  const [form, setForm] = useState({ provider_id: 0, model_id: "", display_name: "", is_active: true });

  const { data: providers = [] } = useQuery({
    queryKey: ["providers"],
    queryFn: () => getProviders().then((r) => r.data),
  });

  const { data: models = [] } = useQuery({
    queryKey: ["models", selectedProvider],
    queryFn: () => selectedProvider ? getModels(selectedProvider).then((r) => r.data) : [],
    enabled: !!selectedProvider,
  });

  const createMut = useMutation({
    mutationFn: (d: any) => createModel(d),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["models"] }); setOpen(false); toast({ title: "妯″瀷娣诲姞鎴愬姛", variant: "success" }); },
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteModel(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["models"] }); toast({ title: "宸插垹闄?, variant: "success" }); },
  });

  const toggleMut = useMutation({
    mutationFn: ({ id, is_active }: any) => updateModel(id, { is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["models"] }),
  });

  const syncMut = useMutation({
    mutationFn: (providerId: number) => syncModels(providerId),
    onSuccess: (res) => { qc.invalidateQueries({ queryKey: ["models"] }); toast({ title: "鍚屾鎴愬姛", description: `鑾峰彇鍒?${res.data.length} 涓ā鍨媊, variant: "success" }); },
    onError: () => toast({ title: "鍚屾澶辫触", variant: "destructive" }),
  });

  const openCreate = () => { setForm({ provider_id: selectedProvider || 0, model_id: "", display_name: "", is_active: true }); setOpen(true); };
  const save = () => createMut.mutate(form);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">妯″瀷绠＄悊</h1>
          <p className="text-sm text-muted-foreground mt-1">绠＄悊鍚勫钩鍙扮殑鍙敤妯″瀷</p>
        </div>
        <div className="flex gap-2">
          {selectedProvider && (
            <Button variant="outline" onClick={() => syncMut.mutate(selectedProvider)} disabled={syncMut.isPending} className="gap-2">
              {syncMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              同步平台模型
            </Button>
          )}
          <Button onClick={openCreate} disabled={!selectedProvider} className="gap-2"><Plus className="h-4 w-4" />娣诲姞妯″瀷</Button>
        </div>
      </div>

      <div className="flex gap-2 flex-wrap">
        {providers.map((p: any) => (
          <Button key={p.id} variant={selectedProvider === p.id ? "default" : "outline"} size="sm" onClick={() => setSelectedProvider(p.id)}>
            {p.name}
          </Button>
        ))}
        {providers.length === 0 && <p className="text-sm text-muted-foreground">璇峰厛娣诲姞涓婃父骞冲彴</p>}
      </div>

      {selectedProvider ? (
        models.length === 0 ? (
          <Card className="border-dashed">
            <CardContent className="flex flex-col items-center justify-center py-12">
              <Cpu className="h-10 w-10 text-muted-foreground/30 mb-3" />
              <p className="text-muted-foreground">璇ュ钩鍙拌繕娌℃湁妯″瀷</p>
              <p className="text-xs text-muted-foreground/70 mt-1">点击“同步平台模型”或手动添加</p>
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>妯″瀷 ID</TableHead>
                    <TableHead>鏄剧ず鍚?/TableHead>
                    <TableHead>鐘舵€?/TableHead>
                    <TableHead className="text-right">鎿嶄綔</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {models.map((m: any) => (
                    <TableRow key={m.id} className="group">
                      <TableCell className="font-mono text-sm">{m.model_id}</TableCell>
                      <TableCell>{m.display_name || "-"}</TableCell>
                      <TableCell><Switch checked={m.is_active} onCheckedChange={(v) => toggleMut.mutate({ id: m.id, is_active: v })} /></TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end opacity-0 group-hover:opacity-100 transition-opacity">
                          <Button variant="ghost" size="icon" className="h-8 w-8 text-destructive" onClick={() => { if (confirm("纭畾鍒犻櫎锛?)) deleteMut.mutate(m.id); }}>
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
            <p className="text-sm text-muted-foreground">璇烽€夋嫨涓€涓钩鍙版潵鏌ョ湅妯″瀷</p>
          </CardContent>
        </Card>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>娣诲姞妯″瀷</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>骞冲彴</Label>
              <Select value={String(form.provider_id)} onValueChange={(v) => setForm({ ...form, provider_id: Number(v) })}>
                <SelectTrigger><SelectValue placeholder="閫夋嫨骞冲彴" /></SelectTrigger>
                <SelectContent>{providers.map((p: any) => <SelectItem key={p.id} value={String(p.id)}>{p.name}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div><Label>妯″瀷 ID</Label><Input value={form.model_id} onChange={(e) => setForm({ ...form, model_id: e.target.value })} placeholder="gpt-4o / claude-3-5-sonnet" /></div>
            <div><Label>鏄剧ず鍚?/Label><Input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} placeholder="鍙€? /></div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>鍙栨秷</Button>
            <Button onClick={save} disabled={!form.model_id || !form.provider_id}>淇濆瓨</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}



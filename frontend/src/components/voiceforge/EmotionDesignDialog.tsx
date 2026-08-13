import { useEffect, useMemo, useState } from "react";
import { Check, Loader2, Play, RefreshCw, Save, Sparkles, Trash2 } from "lucide-react";
import { VoiceForgeCapability, VoiceForgeEmotionTag, VoiceForgeEmotionTask, VoiceForgeVoice, voiceForgeApi } from "@/api/voiceforge";
import { getWebSocketUrl } from "@/api/ws";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

type DesignItem = {
  emotion: string;
  text: string;
  instruct: string;
  interfaceId: string;
  taskId?: string;
  status?: string;
  progress?: number;
  error?: string;
  storageKey?: string;
};

const activeStatuses = ["queued", "running"];

function getErrorMessage(error: any, fallback: string) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object") {
        const field = Array.isArray(item.loc) ? item.loc.filter((value: unknown) => value !== "body").join(".") : "";
        return field ? `${field}：${item.msg || "参数无效"}` : item.msg || "请求参数无效";
      }
      return "请求参数无效";
    }).filter(Boolean);
    return messages.join("；") || fallback;
  }
  if (typeof error?.response?.data === "string") return error.response.data;
  return typeof error?.message === "string" ? error.message : fallback;
}

export function EmotionDesignDialog({ voice, open, onOpenChange, onSaved }: { voice: VoiceForgeVoice | null; open: boolean; onOpenChange: (open: boolean) => void; onSaved: () => void }) {
  const [tags, setTags] = useState<VoiceForgeEmotionTag[]>([]);
  const [capabilities, setCapabilities] = useState<VoiceForgeCapability[]>([]);
  const [interfaceId, setInterfaceId] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [background, setBackground] = useState("");
  const [items, setItems] = useState<DesignItem[]>([]);
  const [busy, setBusy] = useState<"fill" | "generate" | "save" | null>(null);
  const [error, setError] = useState("");

  const cloneCapabilities = useMemo(() => capabilities.filter((item) => item.modes?.controllable_clone?.enabled), [capabilities]);
  const hasActiveTasks = items.some((item) => item.taskId && activeStatuses.includes(item.status || ""));

  useEffect(() => {
    if (!open || !voice) return;
    setSelected([]);
    setItems([]);
    setBackground("");
    setError("");
    void Promise.all([voiceForgeApi.emotionTags(), voiceForgeApi.capabilities(), voiceForgeApi.voiceEmotionTasks(voice.id)])
      .then(([tagResult, capabilityResult, taskResult]) => {
        const nextCapabilities = (capabilityResult.data.capabilities ?? capabilityResult.data.interfaces ?? []) as VoiceForgeCapability[];
        const supported = nextCapabilities.filter((item) => item.modes?.controllable_clone?.enabled);
        const initialInterface = supported.some((item) => item.id === voice.interface_id) ? (voice.interface_id || "") : supported[0]?.id || "";
        setTags(tagResult.data.tags);
        setCapabilities(nextCapabilities);
        setInterfaceId(initialInterface);
        const restored: DesignItem[] = (taskResult.data.tasks as VoiceForgeEmotionTask[]).map((task) => ({
          emotion: task.output?.emotion || "",
          text: task.output?.text || "",
          instruct: task.output?.instruct || "",
          interfaceId: task.output?.interface_id || initialInterface,
          taskId: task.id,
          status: task.status,
          progress: task.progress,
          error: task.error_message,
          storageKey: task.output?.storage_key,
        })).filter((item) => item.emotion);
        setItems(restored);
        setSelected(restored.map((item) => item.emotion));
      })
      .catch((err: any) => setError(getErrorMessage(err, "情绪设计数据加载失败")));
  }, [open, voice?.id]);

  useEffect(() => {
    if (!voice || !hasActiveTasks) return;
    const socket = new WebSocket(getWebSocketUrl(`/ws/voiceforge/voices/${encodeURIComponent(voice.id)}/progress`));
    socket.onmessage = (event) => {
      try {
        const tasks = JSON.parse(event.data).tasks as VoiceForgeEmotionTask[];
        setItems((current) => current.map((item) => {
          const task = tasks.find((candidate) => candidate.id === item.taskId);
          return task ? { ...item, status: task.status, progress: task.progress, error: task.error_message, storageKey: task.output?.storage_key || item.storageKey } : item;
        }));
      } catch {
        setError("情绪任务状态解析失败");
      }
    };
    return () => socket.close();
  }, [voice?.id, hasActiveTasks]);

  const toggle = (name: string) => {
    setSelected((current) => {
      const next = current.includes(name) ? current.filter((item) => item !== name) : [...current, name];
      setItems((existing) => next.includes(name) ? existing.some((item) => item.emotion === name) ? existing : [...existing, { emotion: name, text: "", instruct: "", interfaceId }] : existing.filter((item) => item.emotion !== name));
      return next;
    });
  };

  const selectAll = () => {
    const next = selected.length === tags.length ? [] : tags.map((tag) => tag.name);
    setSelected(next);
    setItems((current) => next.map((emotion) => current.find((item) => item.emotion === emotion) || { emotion, text: "", instruct: "", interfaceId }));
  };

  const updateItem = (emotion: string, field: "text" | "instruct", value: string) => setItems((current) => current.map((item) => item.emotion === emotion ? { ...item, [field]: value } : item));

  const fill = async () => {
    if (!voice || !selected.length || !interfaceId) return;
    setBusy("fill");
    setError("");
    try {
      const result = await voiceForgeApi.fillVoiceEmotions(voice.id, { emotions: selected, character_background: background, interface_id: interfaceId });
      const suggestions = result.data.tasks;
      setItems((current) => current.map((item) => {
        const suggestion = suggestions.find((candidate) => candidate.emotion === item.emotion);
        return suggestion ? { ...item, text: suggestion.text, instruct: suggestion.instruct, interfaceId } : item;
      }));
    } catch (err: any) {
      setError(getErrorMessage(err, "AI 情绪设计失败"));
    } finally {
      setBusy(null);
    }
  };

  const generate = async (targetItems = items.filter((item) => selected.includes(item.emotion))) => {
    if (!voice || !targetItems.length || !interfaceId) return;
    if (targetItems.some((item) => !item.text.trim() || !item.instruct.trim())) {
      setError("请先为每个情绪填写朗读文本和生成指令");
      return;
    }
    setBusy("generate");
    setError("");
    try {
      const result = await voiceForgeApi.generateVoiceEmotions(voice.id, targetItems.map(({ emotion, text, instruct }) => ({ emotion, text, instruct, interface_id: interfaceId })));
      setItems((current) => current.map((item) => {
        const task = result.data.tasks.find((candidate) => candidate.emotion === item.emotion);
        return task ? { ...item, taskId: task.task_id, status: "queued", progress: 0, error: "", storageKey: undefined, interfaceId } : item;
      }));
    } catch (err: any) {
      setError(getErrorMessage(err, "情绪片段生成失败"));
    } finally {
      setBusy(null);
    }
  };

  const remove = (emotion: string) => {
    setSelected((current) => current.filter((item) => item !== emotion));
    setItems((current) => current.filter((item) => item.emotion !== emotion));
  };

  const save = async () => {
    if (!voice) return;
    const taskIds = items.filter((item) => item.status === "succeeded" && item.taskId).map((item) => item.taskId as string);
    if (!taskIds.length) return;
    setBusy("save");
    setError("");
    try {
      await voiceForgeApi.saveVoiceEmotions(voice.id, taskIds);
      onSaved();
      onOpenChange(false);
    } catch (err: any) {
      setError(getErrorMessage(err, "保存情绪片段失败"));
    } finally {
      setBusy(null);
    }
  };

  return <Dialog open={open} onOpenChange={onOpenChange}><DialogContent className="max-h-[90vh] max-w-4xl overflow-y-auto"><DialogHeader><DialogTitle>情绪片段设计</DialogTitle><DialogDescription>选择支持可控克隆的 TTS 引擎，为每个情绪准备试听文本和自然语言生成指令。</DialogDescription></DialogHeader><div className="space-y-5">
    <section className="grid gap-4 border-b border-border/60 pb-5 md:grid-cols-[minmax(0,1fr)_220px]"><div><h3 className="text-sm font-semibold">情绪生成引擎</h3><p className="mt-1 text-xs text-muted-foreground">仅显示已启用且支持可控克隆的接口。</p></div><select value={interfaceId} onChange={(event) => { setInterfaceId(event.target.value); setItems((current) => current.map((item) => ({ ...item, interfaceId: event.target.value }))); }} className="voice-input"><option value="">请选择 TTS 引擎</option>{cloneCapabilities.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></section>
    <section className="space-y-3"><div className="flex items-center justify-between"><h3 className="text-sm font-semibold">选择情绪</h3><Button type="button" variant="ghost" size="sm" onClick={selectAll}>{selected.length === tags.length && tags.length ? "取消全选" : "全选"}</Button></div><div className="flex flex-wrap gap-2">{tags.map((tag) => <button type="button" key={tag.id} onClick={() => toggle(tag.name)} className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm transition ${selected.includes(tag.name) ? "border-primary bg-primary text-primary-foreground" : "border-border bg-background hover:bg-accent"}`}><i className="h-2 w-2 rounded-full" style={{ backgroundColor: selected.includes(tag.name) ? "currentColor" : tag.color || "#94a3b8" }} />{tag.name}</button>)}</div></section>
    <section className="space-y-2 border-t border-border/60 pt-4"><label className="text-sm font-medium">角色补充设定 <span className="font-normal text-muted-foreground">可选</span></label><textarea value={background} onChange={(event) => setBackground(event.target.value)} className="voice-input min-h-20 resize-none" placeholder="例如：悬疑故事中的冷静女侦探，克制但有压迫感" /><Button type="button" variant="outline" onClick={fill} disabled={!selected.length || !interfaceId || busy !== null}>{busy === "fill" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Sparkles className="mr-2 h-4 w-4" />}AI 填充文本与指令</Button></section>
    {items.length > 0 && <section className="space-y-3 border-t border-border/60 pt-4"><div className="flex items-center justify-between"><h3 className="text-sm font-semibold">情绪生成参数 <span className="font-normal text-muted-foreground">{items.length} 项</span></h3><Button type="button" onClick={() => void generate()} disabled={busy !== null || !interfaceId}>{busy === "generate" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Sparkles className="mr-2 h-4 w-4" />}生成试听</Button></div><div className="grid gap-3 md:grid-cols-2">{items.map((item) => <article key={item.emotion} className="space-y-3 rounded-lg border border-border/70 bg-muted/20 p-4"><div className="flex items-center justify-between"><Badge variant="outline">{item.emotion}</Badge><div className="flex items-center gap-1"><Button type="button" variant="ghost" size="icon" title="试听" aria-label={`试听 ${item.emotion}`} disabled={!item.storageKey} onClick={() => { if (item.storageKey) { const audio = new Audio(voiceForgeApi.voicePreviewUrl(item.storageKey)); void audio.play(); } }}><Play className="h-4 w-4" /></Button><Button type="button" variant="ghost" size="icon" title="重新生成" aria-label={`重新生成 ${item.emotion}`} disabled={busy !== null || !item.text.trim() || !item.instruct.trim()} onClick={() => void generate([item])}><RefreshCw className="h-4 w-4" /></Button><Button type="button" variant="ghost" size="icon" title="删除" aria-label={`删除 ${item.emotion}`} onClick={() => remove(item.emotion)}><Trash2 className="h-4 w-4 text-destructive" /></Button></div></div><textarea value={item.text} onChange={(event) => updateItem(item.emotion, "text", event.target.value)} className="voice-input min-h-16 resize-none" placeholder="输入该情绪的朗读文本" /><textarea value={item.instruct} onChange={(event) => updateItem(item.emotion, "instruct", event.target.value)} className="voice-input min-h-20 resize-none" placeholder="描述情绪、语气、节奏、音调和力度" />{item.status && <div className="flex items-center gap-2 text-xs text-muted-foreground">{item.status === "succeeded" ? <Check className="h-4 w-4 text-emerald-600" /> : item.status === "running" ? <Loader2 className="h-4 w-4 animate-spin" /> : null}<span>{item.status === "queued" ? "排队中" : item.status === "running" ? `生成中 ${Math.round((item.progress || 0) * 100)}%` : item.status === "succeeded" ? "已生成，可试听或保存" : item.status}</span></div>}{item.error && <p className="text-xs text-destructive">{item.error}</p>}{item.storageKey && <audio className="w-full" controls src={voiceForgeApi.voicePreviewUrl(item.storageKey)} />}</article>)}</div></section>}
    {error && <p className="text-sm text-destructive">{error}</p>}
  </div><DialogFooter><Button type="button" variant="outline" onClick={() => onOpenChange(false)}>取消</Button><Button type="button" onClick={() => void save()} disabled={busy !== null || !items.some((item) => item.status === "succeeded" && item.taskId)}>{busy === "save" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}保存成功片段</Button></DialogFooter></DialogContent></Dialog>;
}

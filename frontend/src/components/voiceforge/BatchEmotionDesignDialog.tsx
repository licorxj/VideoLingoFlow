import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, Loader2, Play, RefreshCw, Save, Sparkles, Trash2, UserRound, Volume2 } from "lucide-react";
import { VoiceForgeCapability, VoiceForgeEmotionTag, VoiceForgeVoice, voiceForgeApi } from "@/api/voiceforge";
import { getWebSocketUrl } from "@/api/ws";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

type BatchItem = { emotion: string; text: string; instruct: string; taskId?: string; status?: string; progress?: number; error?: string; storageKey?: string };
type VoiceState = { items: BatchItem[]; status: "idle" | "generating" | "done" | "error"; error?: string };

const activeStatuses = new Set(["queued", "running"]);

function messageOf(error: any, fallback: string) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((item) => typeof item === "string" ? item : item?.msg || "请求参数无效").join("；") || fallback;
  return error?.message || fallback;
}

async function eachLimit<T>(items: T[], limit: number, task: (item: T) => Promise<void>) {
  let cursor = 0;
  const worker = async () => { while (cursor < items.length) { const item = items[cursor++]; await task(item); } };
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
}

export function BatchEmotionDesignDialog({ voices, open, onOpenChange, onSaved }: { voices: VoiceForgeVoice[]; open: boolean; onOpenChange: (open: boolean) => void; onSaved: () => void }) {
  const [tags, setTags] = useState<VoiceForgeEmotionTag[]>([]);
  const [capabilities, setCapabilities] = useState<VoiceForgeCapability[]>([]);
  const [interfaceId, setInterfaceId] = useState("");
  const [selectedEmotions, setSelectedEmotions] = useState<string[]>([]);
  const [customEmotion, setCustomEmotion] = useState("");
  const [background, setBackground] = useState("");
  const [states, setStates] = useState<Record<string, VoiceState>>({});
  const [expanded, setExpanded] = useState<string[]>([]);
  const [busy, setBusy] = useState<"fill" | "generate" | "save" | null>(null);
  const [error, setError] = useState("");
  const statesRef = useRef(states);
  useEffect(() => { statesRef.current = states; }, [states]);
  const cloneCapabilities = useMemo(() => capabilities.filter((item) => item.modes?.controllable_clone?.enabled), [capabilities]);
  const total = Object.values(states).reduce((sum, state) => sum + state.items.length, 0);
  const done = Object.values(states).reduce((sum, state) => sum + state.items.filter((item) => item.status === "succeeded").length, 0);
  const taskSignature = useMemo(() => Object.entries(states).map(([id, state]) => `${id}:${state.items.map((item) => item.taskId || "").join(",")}`).join("|"), [states]);

  useEffect(() => {
    if (!open) return;
    const next: Record<string, VoiceState> = {};
    voices.forEach((voice) => { next[voice.id] = { items: [], status: "idle" }; });
    setStates(next);
    setSelectedEmotions([]);
    setBackground("");
    setCustomEmotion("");
    setError("");
    setExpanded(voices.length <= 5 ? voices.map((voice) => voice.id) : []);
    void Promise.all([voiceForgeApi.emotionTags(), voiceForgeApi.capabilities()]).then(([tagResult, capabilityResult]) => {
      const nextCapabilities = (capabilityResult.data.capabilities ?? capabilityResult.data.interfaces ?? []) as VoiceForgeCapability[];
      const supported = nextCapabilities.filter((item) => item.modes?.controllable_clone?.enabled);
      setTags(tagResult.data.tags);
      setCapabilities(nextCapabilities);
      setInterfaceId((current) => supported.some((item) => item.id === current) ? current : supported[0]?.id || "");
    }).catch((err) => setError(messageOf(err, "批量情绪设计数据加载失败")));
  }, [open, voices]);

  const toggleEmotion = (emotion: string) => {
    setSelectedEmotions((current) => current.includes(emotion) ? current.filter((item) => item !== emotion) : [...current, emotion]);
  };
  const applyEmotions = () => {
    setStates((current) => {
      const next = { ...current };
      Object.entries(next).forEach(([id, state]) => {
        const existing = new Set(state.items.map((item) => item.emotion));
        next[id] = { ...state, items: [...state.items, ...selectedEmotions.filter((emotion) => !existing.has(emotion)).map((emotion) => ({ emotion, text: "", instruct: "" }))] };
      });
      return next;
    });
  };
  const addCustomEmotion = () => {
    const emotion = customEmotion.trim();
    if (emotion && !selectedEmotions.includes(emotion)) setSelectedEmotions((current) => [...current, emotion]);
    setCustomEmotion("");
  };
  const updateItem = (voiceId: string, emotion: string, field: "text" | "instruct", value: string) => setStates((current) => ({ ...current, [voiceId]: { ...current[voiceId], items: current[voiceId].items.map((item) => item.emotion === emotion ? { ...item, [field]: value } : item) } }));
  const removeItem = (voiceId: string, emotion: string) => setStates((current) => ({ ...current, [voiceId]: { ...current[voiceId], items: current[voiceId].items.filter((item) => item.emotion !== emotion) } }));

  const fill = async () => {
    if (!interfaceId || !selectedEmotions.length) return;
    setBusy("fill"); setError("");
    await eachLimit(voices, 5, async (voice) => {
      const state = states[voice.id];
      if (!state?.items.length) return;
      try {
        const result = await voiceForgeApi.fillVoiceEmotions(voice.id, { emotions: state.items.map((item) => item.emotion), character_background: background, interface_id: interfaceId });
        const suggestions = result.data.tasks || [];
        setStates((current) => ({ ...current, [voice.id]: { ...current[voice.id], items: current[voice.id].items.map((item) => { const suggestion = suggestions.find((candidate) => candidate.emotion === item.emotion); return suggestion ? { ...item, text: suggestion.text, instruct: suggestion.instruct } : item; }) } }));
      } catch (err: any) {
        setStates((current) => ({ ...current, [voice.id]: { ...current[voice.id], status: "error", error: messageOf(err, "AI 填充失败") } }));
      }
    });
    setBusy(null);
  };

  const generateVoice = async (voice: VoiceForgeVoice, target?: BatchItem) => {
    const source = states[voice.id]?.items || [];
    const items = target ? [target] : source.filter((item) => item.text.trim() && item.instruct.trim() && item.status !== "succeeded");
    if (!items.length) return;
    setStates((current) => ({ ...current, [voice.id]: { ...current[voice.id], status: "generating", error: undefined, items: current[voice.id].items.map((item) => items.some((candidate) => candidate.emotion === item.emotion) ? { ...item, status: "queued", progress: 0, error: undefined } : item) } }));
    try {
      const result = await voiceForgeApi.generateVoiceEmotions(voice.id, items.map(({ emotion, text, instruct }) => ({ emotion, text, instruct, interface_id: interfaceId })));
      setStates((current) => ({ ...current, [voice.id]: { ...current[voice.id], items: current[voice.id].items.map((item) => { const task = result.data.tasks.find((candidate) => candidate.emotion === item.emotion); return task ? { ...item, taskId: task.task_id, status: "queued", progress: 0 } : item; }) } }));
    } catch (err: any) {
      setStates((current) => ({ ...current, [voice.id]: { ...current[voice.id], status: "error", error: messageOf(err, "情绪片段生成失败") } }));
    }
  };
  const generateAll = async () => { setBusy("generate"); await eachLimit(voices, 5, (voice) => generateVoice(voice)); setBusy(null); };
  const save = async () => {
    setBusy("save"); setError(""); let saved = 0; let saveError = "";
    await eachLimit(voices, 5, async (voice) => { const ids = (statesRef.current[voice.id]?.items || []).filter((item) => item.status === "succeeded" && item.taskId).map((item) => item.taskId as string); if (!ids.length) return; try { await voiceForgeApi.saveVoiceEmotions(voice.id, ids); saved += ids.length; } catch (err: any) { saveError = messageOf(err, `${voice.display_name} 保存失败`); } });
    setBusy(null); if (saved) { onSaved(); onOpenChange(false); } else setError(saveError || "没有可保存的成功片段");
  };

  useEffect(() => {
    if (!open) return;
    const sockets = voices.map((voice) => {
      if (!statesRef.current[voice.id]?.items.some((item) => item.taskId && activeStatuses.has(item.status || ""))) return null;
      const socket = new WebSocket(getWebSocketUrl(`/ws/voiceforge/voices/${encodeURIComponent(voice.id)}/progress`));
      socket.onmessage = (event) => { try { const tasks = JSON.parse(event.data).tasks; setStates((current) => ({ ...current, [voice.id]: { ...current[voice.id], status: tasks.some((task: any) => task.status === "failed") ? "error" : current[voice.id].status, items: current[voice.id].items.map((item) => { const task = tasks.find((candidate: any) => candidate.id === item.taskId); return task ? { ...item, status: task.status, progress: task.progress, error: task.error_message, storageKey: task.output?.storage_key || item.storageKey } : item; }) } })); } catch { setError("情绪任务状态解析失败"); } };
      return socket;
    }).filter(Boolean) as WebSocket[];
    return () => sockets.forEach((socket) => socket.close());
  }, [open, voices, taskSignature]);

  return <Dialog open={open} onOpenChange={onOpenChange}><DialogContent className="max-h-[92vh] max-w-5xl overflow-y-auto"><DialogHeader><DialogTitle className="flex items-center gap-2"><Sparkles className="h-5 w-5 text-primary" />批量生成情绪片段（{voices.length} 个音色）</DialogTitle><DialogDescription>统一设置情绪和角色背景，为多个音色批量生成可控克隆情绪试听片段。</DialogDescription></DialogHeader><div className="space-y-5">
    <section className="grid gap-3 border-b border-border/60 pb-4 md:grid-cols-[1fr_260px]"><div><h3 className="text-sm font-semibold">情绪生成引擎</h3><p className="mt-1 text-xs text-muted-foreground">仅显示已启用且支持可控克隆的接口。</p></div><select value={interfaceId} onChange={(event) => setInterfaceId(event.target.value)} className="voice-input"><option value="">请选择 TTS 引擎</option>{cloneCapabilities.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></section>
    <section className="space-y-3"><div className="flex flex-wrap items-center gap-2"><h3 className="mr-auto text-sm font-semibold">预设情绪</h3><Button type="button" variant="ghost" size="sm" onClick={() => setSelectedEmotions(tags.map((tag) => tag.name))}>全选</Button><Button type="button" variant="ghost" size="sm" onClick={() => setSelectedEmotions(tags.filter((tag) => !selectedEmotions.includes(tag.name)).map((tag) => tag.name))}>反选</Button><Button type="button" variant="outline" size="sm" onClick={applyEmotions} disabled={!selectedEmotions.length}>应用到全部音色</Button></div><div className="flex flex-wrap gap-2">{tags.map((tag) => <button type="button" key={tag.id} onClick={() => toggleEmotion(tag.name)} className={`rounded-full border px-3 py-1.5 text-sm ${selectedEmotions.includes(tag.name) ? "border-primary bg-primary text-primary-foreground" : "border-border bg-background hover:bg-accent"}`}>{tag.name}</button>)}<div className="flex gap-1"><input value={customEmotion} onChange={(event) => setCustomEmotion(event.target.value)} onKeyDown={(event) => event.key === "Enter" && addCustomEmotion()} placeholder="自定义情绪" className="voice-input h-8 w-28" /><Button type="button" size="sm" onClick={addCustomEmotion}>添加</Button></div></div></section>
    <section className="space-y-2 border-t border-border/60 pt-4"><label className="text-sm font-medium">人设和背景设定 <span className="font-normal text-muted-foreground">（全局，可选）</span></label><textarea value={background} onChange={(event) => setBackground(event.target.value)} className="voice-input min-h-20 resize-none" placeholder="描述角色性格、身份、背景故事等，LLM 将为每个音色生成贴合的文本与指令" /><div className="flex flex-wrap gap-2"><Button type="button" variant="outline" onClick={() => void fill()} disabled={!selectedEmotions.length || !interfaceId || busy !== null}><Sparkles className="mr-1.5 h-4 w-4" />{busy === "fill" ? "正在填充..." : "LLM 填充全部"}</Button><Button type="button" onClick={() => void generateAll()} disabled={busy !== null || !interfaceId}><Volume2 className="mr-1.5 h-4 w-4" />{busy === "generate" ? "正在提交..." : "生成全部情绪片段"}</Button></div></section>
    {total > 0 && <div className="flex items-center gap-3 text-xs text-muted-foreground"><div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted"><div className="h-full bg-primary transition-all" style={{ width: `${Math.round(done / total * 100)}%` }} /></div><span>{done}/{total}</span></div>}
    <div className="space-y-2">{voices.map((voice) => { const state = states[voice.id] || { items: [], status: "idle" as const }; const isOpen = expanded.includes(voice.id); const completed = state.items.filter((item) => item.status === "succeeded").length; return <section key={voice.id} className="border border-border/70 bg-muted/10"><button type="button" onClick={() => setExpanded((current) => isOpen ? current.filter((id) => id !== voice.id) : [...current, voice.id])} className="flex w-full items-center gap-2 px-4 py-3 text-left"><UserRound className="h-4 w-4 text-primary" /><span className="font-medium">{voice.display_name || voice.name}</span><span className="text-xs text-muted-foreground">{completed}/{state.items.length}</span><ChevronDown className={`ml-auto h-4 w-4 transition-transform ${isOpen ? "rotate-180" : ""}`} /></button>{isOpen && <div className="space-y-3 border-t border-border/60 p-4">{state.error && <p className="text-xs text-destructive">{state.error}</p>}{!state.items.length && <p className="text-sm text-muted-foreground">请先选择情绪并点击“应用到全部音色”。</p>}{state.items.map((item) => <article key={item.emotion} className="space-y-2 rounded-lg border border-border/70 bg-background p-3"><div className="flex items-center gap-2"><Badge variant="outline">{item.emotion}</Badge><span className="text-xs text-muted-foreground">{item.status === "running" ? `生成中 ${Math.round((item.progress || 0) * 100)}%` : item.status || "待生成"}</span><div className="ml-auto flex gap-1"><Button type="button" variant="ghost" size="icon" title="试听" aria-label={`试听 ${item.emotion}`} disabled={!item.storageKey} onClick={() => { if (item.storageKey) void new Audio(voiceForgeApi.voicePreviewUrl(item.storageKey)).play(); }}><Play className="h-4 w-4" /></Button><Button type="button" variant="ghost" size="icon" title="重新生成" aria-label={`重新生成 ${item.emotion}`} disabled={busy !== null || !item.text.trim() || !item.instruct.trim()} onClick={() => void generateVoice(voice, item)}><RefreshCw className="h-4 w-4" /></Button><Button type="button" variant="ghost" size="icon" title="删除" aria-label={`删除 ${item.emotion}`} onClick={() => removeItem(voice.id, item.emotion)}><Trash2 className="h-4 w-4 text-destructive" /></Button></div></div><textarea value={item.text} onChange={(event) => updateItem(voice.id, item.emotion, "text", event.target.value)} className="voice-input min-h-14 resize-none" placeholder="朗读文本" /><textarea value={item.instruct} onChange={(event) => updateItem(voice.id, item.emotion, "instruct", event.target.value)} className="voice-input min-h-16 resize-none" placeholder="情绪、语气、节奏、音调和力度指令" />{item.error && <p className="text-xs text-destructive">{item.error}</p>}</article>)}<Button type="button" variant="outline" onClick={() => void generateVoice(voice)} disabled={busy !== null || !state.items.some((item) => item.text.trim() && item.instruct.trim())}><Volume2 className="mr-1.5 h-4 w-4" />生成该音色</Button></div>}</section>; })}</div>
    {error && <p className="text-sm text-destructive">{error}</p>}
  </div><DialogFooter><Button type="button" variant="outline" onClick={() => onOpenChange(false)}>取消</Button><Button type="button" onClick={() => void save()} disabled={busy !== null || done === 0}>{busy === "save" ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Save className="mr-1.5 h-4 w-4" />}保存全部成功片段</Button></DialogFooter></DialogContent></Dialog>;
}

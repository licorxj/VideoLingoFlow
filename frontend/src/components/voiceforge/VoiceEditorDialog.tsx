import { ChangeEvent, useEffect, useState } from "react";
import { Loader2, Play, Plus, Save, Sparkles, Upload, X } from "lucide-react";
import { VoiceForgeCapability, VoiceForgeVoice, voiceForgeApi } from "@/api/voiceforge";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const modeLabels: Record<string, string> = { preset_voice: "预置音色", clone: "声音克隆", controllable_clone: "可控克隆", voice_design: "声音设计" };
const previewTexts = [
  "您好，感谢您的来电，请问有什么可以帮您？", "您的订单已经发货，预计明天送达，请注意查收。",
  "欢迎来到直播间，喜欢的朋友记得点击关注。", "今天的天气晴朗，适合和家人一起外出游玩。",
  "尊敬的客户，您的服务申请已经审核通过。", "请您系好安全带，我们即将进入高速公路。",
  "本次列车即将到站，请提前整理好随身物品。", "新品限时优惠中，现在下单即可享受专属福利。",
  "感谢您的耐心等待，工作人员正在为您处理。", "早上好，新的一天从一杯热咖啡开始吧。",
  "请根据页面提示完成操作，如有疑问请联系客服。", "会议将在十分钟后开始，请各位参会人员做好准备。",
  "本店所有商品均为正品，支持七天无理由退换。", "温馨提示，请勿将个人验证码透露给任何人。",
  "旅途愉快，祝您在本次行程中收获美好回忆。", "系统正在升级维护，预计今晚十点恢复正常服务。",
  "今天的新闻播报到这里，感谢您的收听与关注。", "您好，您的预约已成功，请按时到店办理业务。",
  "请保持通道畅通，紧急情况请及时拨打服务热线。", "愿每一次认真付出，都能迎来值得期待的结果。",
  "点击下方按钮即可领取新人专享优惠券。", "本课程将帮助您快速掌握实用的办公技巧。",
  "感谢一路相伴，我们期待下一次与您再次见面。", "请仔细阅读服务条款，确认无误后再提交申请。",
  "现在出发，去发现生活中更多细微的美好。",
  "雨落在旧窗台上，故事从这一刻悄然开始。", "他握紧手中的信，终于走向那扇紧闭的门。",
  "月光洒满长街，远处传来若有若无的歌声。", "她回过头微微一笑，像春风吹散了阴霾。",
  "命运的齿轮缓缓转动，没有人能够置身事外。", "这一夜风声很紧，所有秘密都藏进了黑暗里。",
  "镜头拉近，那个沉默的背影显得格外孤独。", "看似平静的小镇，正酝酿着一场惊天反转。",
  "接下来发生的事情，让在场所有人目瞪口呆。", "他原以为赢定了，却没想到结局突然逆转。",
  "别着急，深呼吸一下，我们慢慢把话说清楚。", "太好了，我就知道你一定可以做到这件事！",
  "你怎么现在才来，我已经在这里等了很久了。", "这件事真的让我又惊又喜，简直不敢相信。",
  "没关系，失败一次并不代表你永远做不好。", "请听我说完，这个决定关系到我们所有人。",
  "哇，这里的景色也太美了，快帮我拍张照！", "别怕，有我在这里，我们一定能找到办法的。",
  "原来如此，难怪事情会朝着完全不同的方向发展。", "谢谢你愿意理解我，这句话对我真的很重要。",
  "门外忽然传来脚步声，她的心跳骤然加快。", "在漫长的岁月里，他始终守着最初的承诺。",
  "画面一转，答案就藏在那张泛黄的旧照片里。", "如果喜欢这期内容，别忘了点赞和分享给朋友。",
  "这不仅是一段旅程，更是一次重新认识自己的机会。",
];
const genders = ["男", "女"];
const ages = ["儿童", "少年", "青年", "中年", "老年"];
const pitches = ["极低", "低", "中", "高", "极高"];
const dialects = ["普通话", "东北话", "北京话", "天津话", "河北话", "山东话", "河南话", "陕西话", "山西话", "甘肃话", "宁夏话", "青海话", "新疆话", "四川话", "重庆话", "贵州话", "云南话", "湖南话", "湖北话", "江西话", "安徽话", "江苏话", "上海话", "吴语", "浙江话", "福建话", "闽南话", "粤语", "客家话", "广西话", "桂林话", "潮汕话", "海南话", "台湾腔", "港式普通话"];

export function VoiceEditorDialog({ open, voice, initialMode = "preset_voice", capabilities, onOpenChange, onSaved }: { open: boolean; voice?: VoiceForgeVoice | null; initialMode?: string; capabilities: VoiceForgeCapability[]; onOpenChange: (open: boolean) => void; onSaved: () => void }) {
  const [name, setName] = useState("");
  const [interfaceId, setInterfaceId] = useState("");
  const [mode, setMode] = useState("preset_voice");
  const [voiceId, setVoiceId] = useState("");
  const [language, setLanguage] = useState("zh-CN");
  const [tags, setTags] = useState<string[]>([]);
  const [customTag, setCustomTag] = useState("");
  const [description, setDescription] = useState("");
  const [text, setText] = useState(previewTexts[0]);
  const [speed, setSpeed] = useState(1);
  const [referenceKey, setReferenceKey] = useState("");
  const [instruction, setInstruction] = useState("");
  const [previewKey, setPreviewKey] = useState("");
  const [previewCandidates, setPreviewCandidates] = useState<Array<{ index: number; storage_key?: string; duration?: number; error?: string }>>([]);
  const [selectedPreviewKey, setSelectedPreviewKey] = useState("");
  const [previewCount, setPreviewCount] = useState(1);
  const [gender, setGender] = useState("");
  const [age, setAge] = useState("");
  const [pitchLabel, setPitchLabel] = useState("");
  const [dialect, setDialect] = useState("普通话");
  const [busy, setBusy] = useState<"upload" | "preview" | "save" | null>(null);
  const [error, setError] = useState("");
  const [aiIntentOpen, setAiIntentOpen] = useState(false);
  const [aiIntent, setAiIntent] = useState("");
  const [aiBusy, setAiBusy] = useState(false);

  const capability = capabilities.find((item) => item.id === interfaceId);
  const enabledModes = Object.entries(capability?.modes || {}).filter(([, config]) => config.enabled).map(([value]) => value);
  const cloneMode = mode === "clone" || mode === "controllable_clone";
  const attributeTags = [gender, age, pitchLabel, dialect].filter(Boolean);

  useEffect(() => {
    if (!open) return;
    setName(voice?.display_name || "");
    setInterfaceId(voice?.interface_id || capabilities[0]?.id || "");
    setMode(voice?.mode || initialMode);
    setVoiceId(voice?.voice_id || "");
    setLanguage(voice?.language || "zh-CN");
    setTags(voice?.tags || []);
    setDescription(voice?.description || "");
    setText(voice?.preview_text || previewTexts[0]);
    setReferenceKey(voice?.reference_storage_key || "");
    setPreviewKey(voice?.preview_storage_key || "");
    setPreviewCandidates([]);
    setSelectedPreviewKey(voice?.preview_storage_key || "");
    setPreviewCount(1);
    setInstruction(String(voice?.params?.voice_design || voice?.params?.controllable_clone || voice?.design_text || ""));
    setGender(voice?.gender || "");
    setAge(voice?.voice_age || "");
    setPitchLabel(voice?.voice_pitch || "");
    setDialect(voice?.dialect || "普通话");
    setCustomTag("");
    setError("");
  }, [open, voice, capabilities, initialMode]);

  useEffect(() => {
    if (enabledModes.length && !enabledModes.includes(mode)) setMode(enabledModes[0]);
  }, [interfaceId, enabledModes.join(",")]);

  useEffect(() => {
    if (!cloneMode && mode !== "voice_design") return;
    setInstruction(attributeTags.join("，"));
  }, [gender, age, pitchLabel, dialect, mode]);

  const setAttribute = (setter: (value: string) => void, value: string) => setter(value);
  const addTag = () => {
    const value = customTag.trim();
    if (value && !tags.includes(value) && !attributeTags.includes(value)) setTags((current) => [...current, value]);
    setCustomTag("");
  };
  const allTags = [...attributeTags, ...tags.filter((tag) => !attributeTags.includes(tag))];

  const openAiFill = () => {
    const missing = [["性别", gender], ["年龄", age], ["音高", pitchLabel], ["方言", dialect]].filter(([, value]) => !value).map(([label]) => label);
    if (missing.length) {
      setError(`请先点选全部声音属性：${missing.join("、")}`);
      return;
    }
    setError("");
    setAiIntentOpen(true);
  };

  const fillWithAi = async () => {
    if (!aiIntent.trim()) return;
    setAiBusy(true);
    setError("");
    try {
      const result = await voiceForgeApi.aiFillVoiceParams({ intent: aiIntent.trim(), language, gender, age, pitch_label: pitchLabel, dialect });
      const suggestion = result.data.suggestion;
      setName(suggestion.name);
      setDescription(suggestion.description);
      setInstruction(suggestion.design_text);
      setText(suggestion.preview_text);
      setAiIntentOpen(false);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "AI 参数填充失败");
    } finally {
      setAiBusy(false);
    }
  };

  const uploadReference = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy("upload");
    setError("");
    try {
      const result = await voiceForgeApi.uploadVoiceReference(file);
      setReferenceKey(result.data.storage_key);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "参考音频上传失败");
    } finally {
      setBusy(null);
    }
  };

  const preview = async () => {
    if (!interfaceId || !text.trim()) return;
    if (cloneMode && !referenceKey) {
      setError("克隆模式需要上传参考音频");
      return;
    }
    setBusy("preview");
    setError("");
    try {
      if (previewCandidates.length) await voiceForgeApi.cleanupVoicePreviews(previewCandidates.flatMap((item) => item.storage_key ? [item.storage_key] : []));
      const result = await voiceForgeApi.previewVoiceBatch({
        interface_id: interfaceId, mode, voice_id: voiceId || undefined, text, speed,
        count: previewCount,
        reference_storage_key: referenceKey || undefined,
        voice_design: mode === "voice_design" ? instruction || undefined : undefined,
        controllable_clone: mode === "controllable_clone" ? instruction || undefined : undefined,
      });
      const candidates = result.data.candidates;
      const first = candidates.find((item: { storage_key?: string }) => item.storage_key)?.storage_key || "";
      setPreviewCandidates(candidates);
      setSelectedPreviewKey(first);
      setPreviewKey(first);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "音色试听生成失败");
    } finally {
      setBusy(null);
    }
  };

  const save = async () => {
    if (!name.trim() || !interfaceId) {
      setError("请填写音色名称并选择 TTS 接口");
      return;
    }
    if (cloneMode && !referenceKey) {
      setError("克隆模式需要上传参考音频");
      return;
    }
    setBusy("save");
    setError("");
    const data = {
      name: name.trim(), display_name: name.trim(), interface_id: interfaceId, voice_id: voiceId || undefined,
      mode, language, tags: allTags, description, gender, age, pitch_label: pitchLabel, dialect,
      is_cloned: cloneMode, design_text: mode === "voice_design" ? instruction : undefined,
      reference_storage_key: referenceKey || undefined, preview_storage_key: selectedPreviewKey || previewKey || undefined, preview_text: text.trim(),
      params: mode === "voice_design" ? { voice_design: instruction } : mode === "controllable_clone" ? { controllable_clone: instruction } : {},
    };
    try {
      if (voice) await voiceForgeApi.updateVoice(voice.id, data);
      else await voiceForgeApi.createVoice(data);
      const discarded = previewCandidates.flatMap((item) => item.storage_key && item.storage_key !== selectedPreviewKey ? [item.storage_key] : []);
      if (discarded.length) await voiceForgeApi.cleanupVoicePreviews(discarded);
      onSaved();
      onOpenChange(false);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "保存音色失败");
    } finally {
      setBusy(null);
    }
  };

  const close = (nextOpen: boolean) => {
    if (!nextOpen && previewCandidates.length) void voiceForgeApi.cleanupVoicePreviews(previewCandidates.flatMap((item) => item.storage_key ? [item.storage_key] : []));
    onOpenChange(nextOpen);
  };

  return <Dialog open={open} onOpenChange={close}>
    <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
      <DialogHeader>
        <DialogTitle>{voice ? "编辑音色档案" : modeLabels[mode] || "新建音色档案"}</DialogTitle>
        <DialogDescription>配置声音属性、生成指令与试听文本后，保存为可复用音色。</DialogDescription>
      </DialogHeader>
      <div className="space-y-6">
        {mode !== "preset_voice" && <div className="flex justify-end"><Button type="button" variant="outline" size="sm" onClick={openAiFill}><Sparkles className="mr-1.5 h-4 w-4" />AI 填充参数</Button></div>}
        <section className="space-y-4">
          <h3 className="text-sm font-semibold">基础档案</h3>
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="音色名称"><input value={name} onChange={(event) => setName(event.target.value)} className="voice-input" placeholder="例如：温柔女旁白" /></Field>
            <Field label="TTS 接口"><select value={interfaceId} onChange={(event) => setInterfaceId(event.target.value)} className="voice-input">{capabilities.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field>
            <Field label="合成模式"><select value={mode} onChange={(event) => setMode(event.target.value)} className="voice-input">{enabledModes.map((item) => <option key={item} value={item}>{modeLabels[item] || item}</option>)}</select></Field>
            <Field label="语言"><input value={language} onChange={(event) => setLanguage(event.target.value)} className="voice-input" /></Field>
            {mode === "preset_voice" && <Field label="接口原生音色"><select value={voiceId} onChange={(event) => setVoiceId(event.target.value)} className="voice-input"><option value="">使用接口默认音色</option>{(capability?.voice_options || []).map((item) => <option key={item} value={item}>{item}</option>)}</select></Field>}
            <div className="md:col-span-2"><Field label="说明"><textarea value={description} onChange={(event) => setDescription(event.target.value)} className="voice-input min-h-16 resize-none" placeholder="记录声音适用场景和风格" /></Field></div>
          </div>
        </section>
        {(cloneMode || mode === "voice_design") && <>
          <section className="voice-section space-y-4">
            <h3 className="text-sm font-semibold">声音属性</h3>
            <AttributeGroup label="性别" values={genders} value={gender} onChange={(value) => setAttribute(setGender, value)} />
            <AttributeGroup label="年龄" values={ages} value={age} onChange={(value) => setAttribute(setAge, value)} />
            <AttributeGroup label="音高" values={pitches} value={pitchLabel} onChange={(value) => setAttribute(setPitchLabel, value)} />
            <AttributeGroup label="方言" values={dialects} value={dialect} onChange={(value) => setAttribute(setDialect, value)} collapsible />
            <div className="grid gap-2"><span className="text-sm font-medium">自定义标签</span><div className="flex gap-2"><input value={customTag} onChange={(event) => setCustomTag(event.target.value)} onKeyDown={(event) => event.key === "Enter" && (event.preventDefault(), addTag())} className="voice-input" placeholder="输入后回车添加" /><Button type="button" size="icon" onClick={addTag} aria-label="添加标签"><Plus className="h-4 w-4" /></Button></div><div className="flex flex-wrap gap-1.5">{allTags.map((tag) => <Badge key={tag} variant="secondary" className="gap-1">{tag}{!attributeTags.includes(tag) && <button type="button" onClick={() => setTags((current) => current.filter((item) => item !== tag))} aria-label={`移除 ${tag}`}><X className="h-3 w-3" /></button>}</Badge>)}</div></div>
          </section>
          {cloneMode && <section className="voice-section"><Field label="参考音频"><div className="flex items-center gap-3"><label className="inline-flex h-9 cursor-pointer items-center gap-2 rounded-md border border-border px-3 text-sm hover:bg-accent"><Upload className="h-4 w-4" />{busy === "upload" ? <Loader2 className="h-4 w-4 animate-spin" /> : "选择文件"}<input type="file" accept="audio/*" onChange={uploadReference} className="hidden" /></label>{referenceKey ? <Badge variant="outline">已上传</Badge> : <span className="text-xs text-muted-foreground">支持 WAV、MP3、FLAC 格式</span>}</div></Field></section>}
          <section className="voice-section"><Field label="TTS 生成指令"><textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} className="voice-input min-h-20 resize-none" placeholder="选择声音属性后会自动填入，可继续自由编辑" /></Field></section>
        </>}
        <section className="voice-section space-y-4"><h3 className="text-sm font-semibold">试听验证</h3><Field label="试听文本"><div className="flex gap-2"><select onChange={(event) => event.target.value && setText(event.target.value)} className="h-10 w-12 shrink-0 rounded-md border border-border bg-background px-1 text-sm" aria-label="选择预设试听文本"><option value="">预设</option>{previewTexts.map((item, index) => <option key={item} value={item}>{index + 1}. {item}</option>)}</select><input value={text} onChange={(event) => setText(event.target.value)} className="voice-input" placeholder="输入或选择试听文本" /></div></Field><Field label="语速"><div className="flex items-center gap-3"><input type="range" min="0.5" max="2" step="0.1" value={speed} onChange={(event) => setSpeed(Number(event.target.value))} className="flex-1" /><span className="w-12 text-right text-sm tabular-nums">{speed}x</span></div></Field><div className="flex items-center gap-3"><Button variant="outline" onClick={preview} disabled={busy === "preview" || !interfaceId || !text.trim()}>{busy === "preview" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}试听效果</Button><label className="flex items-center gap-2 text-sm text-muted-foreground">批量<select value={previewCount} onChange={(event) => setPreviewCount(Number(event.target.value))} className="h-9 rounded-md border border-border bg-background px-2 text-foreground">{Array.from({ length: 10 }, (_, index) => <option key={index + 1} value={index + 1}>{index + 1}</option>)}</select></label></div>{previewCandidates.length > 0 && <div className="space-y-2 rounded-lg border border-border bg-muted/20 p-3"><p className="text-sm font-medium">生成结果 <span className="font-normal text-muted-foreground">选择一条保存</span></p>{previewCandidates.map((candidate) => candidate.storage_key ? <label key={candidate.index} className={`flex items-center gap-3 rounded-md border p-2 transition ${selectedPreviewKey === candidate.storage_key ? "border-primary bg-primary/5" : "border-border bg-background"}`}><input type="radio" name="voice-preview" checked={selectedPreviewKey === candidate.storage_key} onChange={() => { setSelectedPreviewKey(candidate.storage_key!); setPreviewKey(candidate.storage_key!); }} /><span className="w-6 text-sm text-muted-foreground">#{candidate.index}</span><audio controls src={voiceForgeApi.voicePreviewUrl(candidate.storage_key)} className="min-w-0 flex-1" /></label> : <div key={candidate.index} className="rounded-md border border-destructive/30 px-3 py-2 text-sm text-destructive">#{candidate.index} 生成失败：{candidate.error || "未知错误"}</div>)}</div>}</section>
        {error && <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">{error}</p>}
      </div>
      <DialogFooter><Button variant="outline" onClick={() => close(false)}>取消</Button><Button onClick={save} disabled={busy === "save" || (previewCandidates.length > 0 && !selectedPreviewKey)}>{busy === "save" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}保存音色</Button></DialogFooter>
    </DialogContent>
    <Dialog open={aiIntentOpen} onOpenChange={setAiIntentOpen}>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle>AI 填充音色参数</DialogTitle><DialogDescription>描述角色的性格、职业、音色气质或使用场景。已选择的声音属性将作为固定条件。</DialogDescription></DialogHeader>
        <textarea value={aiIntent} onChange={(event) => setAiIntent(event.target.value)} className="voice-input min-h-32 resize-none" placeholder="例如：一位冷静专业的女性法制节目主持人，表达清晰、有亲和力..." />
        <DialogFooter><Button variant="outline" onClick={() => setAiIntentOpen(false)}>取消</Button><Button onClick={fillWithAi} disabled={aiBusy || !aiIntent.trim()}>{aiBusy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Sparkles className="mr-2 h-4 w-4" />}生成并填充</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </Dialog>;
}

function AttributeGroup({ label, values, value, onChange, collapsible = false }: { label: string; values: string[]; value: string; onChange: (value: string) => void; collapsible?: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const visibleValues = collapsible && !expanded ? values.slice(0, 12) : values;
  return <div className="grid gap-2"><div className="flex items-center justify-between"><span className="text-sm font-medium">{label}</span>{collapsible && <Button type="button" variant="ghost" size="sm" className="h-7 px-2 text-xs text-muted-foreground" onClick={() => setExpanded((current) => !current)}>{expanded ? "收起" : "展开全部"}</Button>}</div><div className={`flex flex-wrap gap-2 ${collapsible && !expanded ? "max-h-[68px] overflow-hidden" : ""}`}>{visibleValues.map((item) => <Button key={item} type="button" variant={value === item ? "default" : "outline"} size="sm" className="rounded-full" onClick={() => onChange(item)}>{item}</Button>)}</div></div>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="grid gap-1.5 text-sm"><span className="font-medium">{label}</span>{children}</label>;
}

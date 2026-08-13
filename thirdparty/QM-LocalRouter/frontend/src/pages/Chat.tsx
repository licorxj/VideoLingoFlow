import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getStrategies, getProviders, getModels, getConversations, createConversation, updateConversation, deleteConversation, generateImage, generateSpeech, createVideo, getVideoTask } from '../services/api';
import { useI18n } from '../i18n';
import { toast } from '../stores/toast';
import { Button } from '../components/ui/button';
import { Select, SelectTrigger, SelectContent, SelectItem, SelectValue } from '../components/ui/select';
import { Textarea } from '../components/ui/textarea';
import { Send, Trash2, Paperclip, Image as ImageIcon, FileText, Loader2, Bot, User, Copy, Check, Plus, MessageSquare, Search, Zap, Boxes, Volume2, Film, Download } from 'lucide-react';
import { Switch } from '../components/ui/switch';

type ModelType = 'text' | 'image' | 'tts' | 'video' | 'embedding' | 'audio';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  files?: { name: string; type: string; preview?: string }[];
  richType?: 'image' | 'audio' | 'video_task';
  imageUrls?: string[];
  audioUrl?: string;
  videoTask?: { id: string; status: string; videoUrl?: string; providerId?: number };
}

interface ConversationItem {
  id: number;
  title: string;
  strategy_name: string;
  chat_mode: string;
  stream_mode: boolean;
  model_used: string;
  provider_used: string;
  messages: string;
  updated_at: string;
}

const MODEL_TYPE_ICONS: Record<ModelType, typeof Bot> = {
  text: Zap, image: ImageIcon, tts: Volume2, video: Film, audio: Volume2, embedding: Boxes,
};

const MODEL_TYPE_COLORS: Record<ModelType, string> = {
  text: 'bg-blue-500/10 text-blue-600 dark:text-blue-400',
  image: 'bg-purple-500/10 text-purple-600 dark:text-purple-400',
  tts: 'bg-green-500/10 text-green-600 dark:text-green-400',
  video: 'bg-orange-500/10 text-orange-600 dark:text-orange-400',
  audio: 'bg-green-500/10 text-green-600 dark:text-green-400',
  embedding: 'bg-gray-500/10 text-gray-600 dark:text-gray-400',
};
export default function Chat() {
  const { t } = useI18n();
  const [convList, setConvList] = useState<ConversationItem[]>([]);
  const [activeConvId, setActiveConvId] = useState<number | null>(null);
  const [convSearch, setConvSearch] = useState('');
  const [chatMode, setChatMode] = useState<'strategy' | 'model'>('strategy');
  const [selectedStrategy, setSelectedStrategy] = useState('');
  const [selectedProviderId, setSelectedProviderId] = useState<number>(0);
  const [selectedModelId, setSelectedModelId] = useState('');
  const [selectedModelType, setSelectedModelType] = useState<ModelType>('text');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamMode, setStreamMode] = useState(true);
  const [attachedFiles, setAttachedFiles] = useState<{ name: string; type: string; file: File; preview?: string }[]>([]);
  const [videoPollingId, setVideoPollingId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);

  const { data: strategies = [] } = useQuery({ queryKey: ['strategies'], queryFn: () => getStrategies().then((r) => r.data) });
  const activeStrategies = (strategies as any[]).filter((s: any) => s.is_active);
  const { data: providers = [] } = useQuery({ queryKey: ['providers'], queryFn: () => getProviders().then((r) => r.data), enabled: chatMode === 'model' });
  const { data: modelList = [] } = useQuery({ queryKey: ['models', selectedProviderId], queryFn: () => getModels(selectedProviderId).then((r) => r.data), enabled: chatMode === 'model' && !!selectedProviderId });

  const loadConversations = useCallback(async () => { try { const res = await getConversations(); setConvList(res.data || []); } catch (_e) {} }, []);
  useEffect(() => { loadConversations(); }, [loadConversations]);
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);
  useEffect(() => { if (textareaRef.current) { textareaRef.current.style.height = 'auto'; textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 200) + 'px'; } }, [input]);

  useEffect(() => {
    if (chatMode === 'model' && selectedModelId && Array.isArray(modelList)) {
      const m = (modelList as any[]).find((x: any) => x.model_id === selectedModelId);
      if (m) { setSelectedModelType((m.model_type || 'text') as ModelType); return; }
    }
    if (chatMode === 'strategy') setSelectedModelType('text');
  }, [chatMode, selectedModelId, modelList]);

  useEffect(() => {
    if (!videoPollingId) return;
    const iv = setInterval(async () => {
      try {
        // using static import
        let providerId: number | undefined;
        setMessages(prev => { for (let i = prev.length - 1; i >= 0; i--) { if (prev[i].videoTask?.id === videoPollingId) { providerId = prev[i].videoTask?.providerId; break; } } return prev; });
        if (!providerId) { setVideoPollingId(null); return; }
        const res = await getVideoTask(videoPollingId, providerId);
        const data = res.data;
        setMessages(prev => {
          const u = [...prev];
          for (let j = u.length - 1; j >= 0; j--) {
            if (u[j].videoTask?.id === videoPollingId) {
              u[j] = { ...u[j], videoTask: { ...u[j].videoTask!, status: data.status, videoUrl: data.video_url || u[j].videoTask!.videoUrl }, content: data.status === 'completed' && data.video_url ? 'Video ready: ' + data.video_url : 'Status: ' + data.status };
              if (data.status === 'completed' || data.status === 'failed') setVideoPollingId(null);
              break;
            }
          }
          return u;
        });
      } catch {}
    }, 5000);
    return () => clearInterval(iv);
  }, [videoPollingId]);
  const loadConversation = (conv: ConversationItem) => {
    setActiveConvId(conv.id);
    try { setMessages(JSON.parse(conv.messages || '[]')); } catch { setMessages([]); }
    const mode = conv.chat_mode || 'strategy';
    setChatMode(mode as 'strategy' | 'model');
    if (conv.stream_mode !== undefined) setStreamMode(conv.stream_mode);
    if (mode === 'model') {
      const pid = Number(conv.provider_used) || 0;
      setSelectedProviderId(pid);
      setSelectedModelId(conv.model_used || '');
      setSelectedModelType('text');
    } else {
      setSelectedStrategy(conv.strategy_name || '');
      setSelectedModelType('text');
    }
  };

  const handleNewChat = async () => {
    try {
      const res = await createConversation({ title: t('chat.newChat'), strategy_name: chatMode === 'strategy' ? selectedStrategy : '', chat_mode: chatMode, stream_mode: streamMode, model_used: chatMode === 'model' ? selectedModelId : selectedStrategy, provider_used: chatMode === 'model' ? String(selectedProviderId) : '' });
      const newConv = { ...res.data, messages: '[]' };
      setConvList(prev => [newConv, ...prev]); setActiveConvId(newConv.id); setMessages([]); setInput(''); setAttachedFiles([]);
    } catch { toast({ title: t('common.error'), variant: 'destructive' }); }
  };

  const handleDeleteConv = async (id: number, e: React.MouseEvent) => { e.stopPropagation(); try { await deleteConversation(id); setConvList(prev => prev.filter(c => c.id !== id)); if (activeConvId === id) { setActiveConvId(null); setMessages([]); } } catch {} };
  const removeFile = (idx: number) => setAttachedFiles(prev => prev.filter((_, i) => i !== idx));
  const handleFileAttach = (e: React.ChangeEvent<HTMLInputElement>) => { Array.from(e.target.files || []).forEach(file => { const reader = new FileReader(); reader.onload = () => { setAttachedFiles(prev => [...prev, { name: file.name, type: file.type, file, preview: file.type.startsWith('image/') ? reader.result as string : undefined }]); }; reader.readAsDataURL(file); }); e.target.value = ''; };
  const copyMessage = (text: string, idx: number) => { navigator.clipboard.writeText(text).then(() => { setCopiedIdx(idx); setTimeout(() => setCopiedIdx(null), 2000); }); };
  const isReady = chatMode === 'strategy' ? !!selectedStrategy : (!!selectedProviderId && !!selectedModelId);
  const getDirectProviderId = (): number | undefined => chatMode === 'model' ? selectedProviderId : undefined;
  const doSendImage = async (prompt: string, convId: number, prevMessages: ChatMessage[]) => {
    const userMsg: ChatMessage = { role: 'user', content: prompt };
    const allMessages = [...prevMessages, userMsg]; setMessages([...allMessages, { role: 'assistant', content: '', richType: 'image' }]); setIsStreaming(true);
    try {
      // using static import
      const body: any = { model: selectedModelId, prompt, size: '1024x1024', n: 1 };
      const pid = getDirectProviderId(); if (pid) body._direct_provider_id = pid;
      const res = await generateImage(body); const data = res.data;
      const urls: string[] = []; if (data.data) { for (const item of data.data) { if (item.url) urls.push(item.url); else if (item.b64_json) urls.push('data:image/png;base64,' + item.b64_json); } }
      const assistantMsg: ChatMessage = { role: 'assistant', content: urls.length > 0 ? 'Generated ' + urls.length + ' image(s)' : 'No images returned', richType: 'image', imageUrls: urls };
      const finalMessages = [...allMessages, assistantMsg]; setMessages(finalMessages);
      await updateConversation(convId, { messages: JSON.stringify(finalMessages), title: allMessages[0]?.content?.slice(0, 50) || t('chat.newChat'), chat_mode: chatMode, stream_mode: streamMode, model_used: chatMode === 'strategy' ? selectedStrategy : selectedModelId, provider_used: chatMode === 'model' ? String(selectedProviderId) : '' });
      loadConversations();
    } catch (err: any) { const errMsg = err.message || 'Image generation failed'; toast({ title: t('common.error'), description: errMsg, variant: 'destructive' }); setMessages(prev => [...prev, { role: 'assistant', content: 'Error: ' + errMsg }]); } finally { setIsStreaming(false); }
  };

  const doSendTts = async (text: string, convId: number, prevMessages: ChatMessage[]) => {
    const userMsg: ChatMessage = { role: 'user', content: text };
    const allMessages = [...prevMessages, userMsg]; setMessages([...allMessages, { role: 'assistant', content: '', richType: 'audio' }]); setIsStreaming(true);
    try {
      // using static import
      const body: any = { model: selectedModelId, input: text, voice: 'alloy' };
      const pid = getDirectProviderId(); if (pid) body._direct_provider_id = pid;
      const blob = await generateSpeech(body); const audioUrl = URL.createObjectURL(blob);
      const assistantMsg: ChatMessage = { role: 'assistant', content: 'Audio generated (' + (blob.size / 1024).toFixed(1) + ' KB)', richType: 'audio', audioUrl };
      const finalMessages = [...allMessages, assistantMsg]; setMessages(finalMessages);
      await updateConversation(convId, { messages: JSON.stringify(finalMessages), title: allMessages[0]?.content?.slice(0, 50) || t('chat.newChat'), chat_mode: chatMode, stream_mode: streamMode, model_used: chatMode === 'strategy' ? selectedStrategy : selectedModelId, provider_used: chatMode === 'model' ? String(selectedProviderId) : '' });
      loadConversations();
    } catch (err: any) { const errMsg = err.message || 'TTS failed'; toast({ title: t('common.error'), description: errMsg, variant: 'destructive' }); setMessages(prev => [...prev, { role: 'assistant', content: 'Error: ' + errMsg }]); } finally { setIsStreaming(false); }
  };

  const doSendVideo = async (prompt: string, convId: number, prevMessages: ChatMessage[]) => {
    const userMsg: ChatMessage = { role: 'user', content: prompt };
    const allMessages = [...prevMessages, userMsg]; setMessages([...allMessages, { role: 'assistant', content: t('chat.videoCreating'), richType: 'video_task', videoTask: { id: '', status: 'queued' } }]); setIsStreaming(true);
    try {
      // using static import
      const body: any = { model: selectedModelId, prompt };
      const pid = getDirectProviderId(); if (pid) body._direct_provider_id = pid;
      const res = await createVideo(body); const data = res.data;
      const taskId = data.id || ''; const status = data.status || 'queued';
      const assistantMsg: ChatMessage = { role: 'assistant', content: status === 'completed' && data.video_url ? 'Video ready: ' + data.video_url : t('chat.videoTaskCreated') + ' ID: ' + taskId, richType: 'video_task', videoTask: { id: taskId, status, videoUrl: data.video_url, providerId: pid || selectedProviderId } };
      const finalMessages = [...allMessages, assistantMsg]; setMessages(finalMessages);
      if (status !== 'completed' && status !== 'failed' && taskId) setVideoPollingId(taskId);
      await updateConversation(convId, { messages: JSON.stringify(finalMessages), title: allMessages[0]?.content?.slice(0, 50) || t('chat.newChat'), chat_mode: chatMode, stream_mode: streamMode, model_used: chatMode === 'strategy' ? selectedStrategy : selectedModelId, provider_used: chatMode === 'model' ? String(selectedProviderId) : '' });
      loadConversations();
    } catch (err: any) { const errMsg = err.message || 'Video generation failed'; toast({ title: t('common.error'), description: errMsg, variant: 'destructive' }); setMessages(prev => [...prev, { role: 'assistant', content: 'Error: ' + errMsg }]); } finally { setIsStreaming(false); }
  };
  const doSendText = async (convId: number, prevMessages: ChatMessage[]) => {
    const fileInfos = attachedFiles.map(f => ({ name: f.name, type: f.type, preview: f.preview }));
    const userMsg: ChatMessage = { role: 'user', content: input.trim(), files: fileInfos.length > 0 ? fileInfos : undefined };
    const allMessages = [...prevMessages, userMsg]; setMessages(allMessages); setInput(''); setAttachedFiles([]); setIsStreaming(true);
    const apiMessages = allMessages.map(m => {
      const parts: any[] = [];
      if (m.files && m.files.length > 0) { m.files.forEach(f => { if (f.type.startsWith('image/') && f.preview) parts.push({ type: 'image_url', image_url: { url: f.preview } }); else parts.push({ type: 'text', text: '[File: ' + f.name + ']' }); }); }
      if (m.content) parts.push({ type: 'text', text: m.content });
      return { role: m.role, content: parts.length === 1 && parts[0].type === 'text' ? m.content : parts };
    });
    try {
      let response: Response;
      if (chatMode === 'strategy') { response = await fetch('/v1/chat/completions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model: selectedStrategy, messages: apiMessages, stream: streamMode }) }); }
      else { response = await fetch('/v1/chat/completions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model: selectedModelId, messages: apiMessages, stream: streamMode, _direct_provider_id: selectedProviderId }) }); }
      if (!response.ok) { const err = await response.json().catch(() => ({ error: { message: response.statusText } })); throw new Error(err.error?.detail || err.error?.message || 'Request failed'); }
      let assistantContent = '';
      if (streamMode) {
        const reader = response.body?.getReader(); const decoder = new TextDecoder(); let buffer = ''; setMessages([...allMessages, { role: 'assistant', content: '' }]);
        if (reader) { while (true) { const { done, value } = await reader.read(); if (done) break; buffer += decoder.decode(value, { stream: true }); const lines = buffer.split('\n'); buffer = lines.pop() || ''; for (const line of lines) { const trimmed = line.trim(); if (!trimmed || !trimmed.startsWith('data: ')) continue; const d = trimmed.slice(6); if (d === '[DONE]') continue; try { const obj = JSON.parse(d); const delta = obj.choices?.[0]?.delta?.content; if (delta) { assistantContent += delta; setMessages(prev => { const updated = [...prev]; updated[updated.length - 1] = { role: 'assistant', content: assistantContent }; return updated; }); } } catch {} } } }
      } else { const data = await response.json(); assistantContent = data.choices?.[0]?.message?.content || ''; setMessages([...allMessages, { role: 'assistant', content: assistantContent }]); }
      const finalMessages = [...allMessages, { role: 'assistant' as const, content: assistantContent }];
      await updateConversation(convId, { messages: JSON.stringify(finalMessages), title: allMessages[0]?.content?.slice(0, 50) || t('chat.newChat'), chat_mode: chatMode, stream_mode: streamMode, model_used: chatMode === 'strategy' ? selectedStrategy : selectedModelId, provider_used: chatMode === 'model' ? String(selectedProviderId) : '' });
      loadConversations();
    } catch (err: any) { toast({ title: t('common.error'), description: err.message, variant: 'destructive' }); setMessages(prev => [...prev, { role: 'assistant', content: 'Error: ' + err.message }]); } finally { setIsStreaming(false); }
  };

  const doSend = async (convId: number, prevMessages: ChatMessage[]) => {
    const text = input.trim(); if (!text && attachedFiles.length === 0) return;
    if (chatMode === 'model') {
      if (selectedModelType === 'image') { setInput(''); setAttachedFiles([]); return doSendImage(text || 'Generate an image', convId, prevMessages); }
      if (selectedModelType === 'tts') { setInput(''); setAttachedFiles([]); return doSendTts(text || 'Hello', convId, prevMessages); }
      if (selectedModelType === 'video') { setInput(''); setAttachedFiles([]); return doSendVideo(text || 'Generate a video', convId, prevMessages); }
    }
    return doSendText(convId, prevMessages);
  };

  const sendMessage = async () => {
    if ((!input.trim() && attachedFiles.length === 0) || !isReady || isStreaming) return;
    if (!activeConvId) {
      try {
        const title = input.trim().slice(0, 50) || t('chat.newChat');
        const res = await createConversation({ title, strategy_name: chatMode === 'strategy' ? selectedStrategy : '', chat_mode: chatMode, stream_mode: streamMode, model_used: chatMode === 'model' ? selectedModelId : selectedStrategy, provider_used: chatMode === 'model' ? String(selectedProviderId) : '' });
        const newConv = { ...res.data, messages: '[]' }; setConvList(prev => [newConv, ...prev]); setActiveConvId(newConv.id); await doSend(newConv.id, []);
      } catch { toast({ title: t('common.error'), variant: 'destructive' }); } return;
    }
    await doSend(activeConvId, messages);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } };
  const filteredConvList = convSearch ? convList.filter(c => c.title.toLowerCase().includes(convSearch.toLowerCase())) : convList;
  const placeholderText = selectedModelType === 'image' ? t('chat.placeholderImage') : selectedModelType === 'tts' ? t('chat.placeholderTts') : selectedModelType === 'video' ? t('chat.placeholderVideo') : t('chat.placeholder');
  const TypeIcon = MODEL_TYPE_ICONS[selectedModelType] || Zap;
  return (
    <div className='flex h-[calc(100vh-4rem)] -m-8'>
      <div className='w-64 border-r bg-muted/30 flex flex-col'>
        <div className='p-3 border-b'>
          <Button size='sm' className='w-full gap-2' onClick={handleNewChat}><Plus className='h-4 w-4' />{t('chat.newChat')}</Button>
          <div className='relative mt-2'><Search className='absolute left-2 top-2.5 h-3.5 w-3.5 text-muted-foreground' /><input value={convSearch} onChange={e => setConvSearch(e.target.value)} placeholder={t('chat.searchConv')} className='w-full pl-7 pr-2 py-1.5 text-xs rounded-md border bg-background' /></div>
        </div>
        <div className='flex-1 overflow-y-auto'>
          {filteredConvList.length === 0 && <div className='p-4 text-xs text-muted-foreground text-center'>{t('chat.noHistory')}</div>}
          {filteredConvList.map(conv => (
            <div key={conv.id} onClick={() => loadConversation(conv)} className={'group flex items-center gap-2 px-3 py-2.5 cursor-pointer hover:bg-accent/50 transition-colors ' + (activeConvId === conv.id ? 'bg-accent/70' : '')}>
              <MessageSquare className='h-3.5 w-3.5 flex-shrink-0 text-muted-foreground' />
              <div className='flex-1 min-w-0'>
                <div className='text-xs font-medium truncate'>{conv.title}</div>
                {conv.model_used && <div className='text-[10px] text-muted-foreground truncate mt-0.5'>{conv.chat_mode === 'strategy' ? '\u{1F3AF} ' : '\u{1F527} '}{conv.model_used}{conv.stream_mode ? ' \u{1F4E1}' : ' \u{1F4DD}'}</div>}
              </div>
              <button onClick={(e) => handleDeleteConv(conv.id, e)} className='opacity-0 group-hover:opacity-100 transition-opacity p-1 hover:text-destructive'><Trash2 className='h-3 w-3' /></button>
            </div>
          ))}
        </div>
      </div>

      <div className='flex-1 flex flex-col'>
        <div className='border-b px-6 py-3 flex items-center gap-3 bg-background/80 backdrop-blur-sm'>
          <div className='flex items-center gap-2 flex-1'>
            <div className='flex items-center gap-1 rounded-lg border p-0.5'>
              <button onClick={() => { setChatMode('strategy'); setSelectedModelType('text'); }} className={'px-3 py-1 text-xs rounded-md transition-colors ' + (chatMode === 'strategy' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted')}>{t('chat.modeStrategy')}</button>
              <button onClick={() => setChatMode('model')} className={'px-3 py-1 text-xs rounded-md transition-colors ' + (chatMode === 'model' ? 'bg-primary text-primary-foreground' : 'hover:bg-muted')}>{t('chat.modeModel')}</button>
            </div>
            {chatMode === 'strategy' ? (
              <Select value={selectedStrategy} onValueChange={setSelectedStrategy}><SelectTrigger className='w-[200px] h-8 text-xs'><SelectValue placeholder={t('chat.selectStrategy')} /></SelectTrigger><SelectContent>{activeStrategies.map((s: any) => <SelectItem key={s.name} value={s.name}>{s.name}</SelectItem>)}</SelectContent></Select>
            ) : (
              <>
                <Select value={String(selectedProviderId)} onValueChange={v => { setSelectedProviderId(Number(v)); setSelectedModelId(''); setSelectedModelType('text'); }}><SelectTrigger className='w-[160px] h-8 text-xs'><SelectValue placeholder={t('chat.selectProvider')} /></SelectTrigger><SelectContent>{(providers as any[]).filter((p: any) => p.is_active).map((p: any) => <SelectItem key={p.id} value={String(p.id)}>{p.name}</SelectItem>)}</SelectContent></Select>
                <Select value={selectedModelId} onValueChange={setSelectedModelId}><SelectTrigger className='w-[220px] h-8 text-xs'><SelectValue placeholder={t('chat.directModel')} /></SelectTrigger><SelectContent>{(modelList as any[]).filter((m: any) => m.is_active).map((m: any) => <SelectItem key={m.model_id} value={m.model_id}><span className='flex items-center gap-1.5'>{(() => { const mt = (m.model_type || 'text') as ModelType; const Ic = MODEL_TYPE_ICONS[mt] || Zap; return <Ic className='h-3 w-3' />; })()}<span>{m.display_name || m.model_id}</span></span></SelectItem>)}</SelectContent></Select>
              </>
            )}
          </div>
          {chatMode === 'model' && selectedModelId && (
            <div className={'flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ' + MODEL_TYPE_COLORS[selectedModelType]}><TypeIcon className='h-3 w-3' /><span>{t('chat.type.' + selectedModelType)}</span></div>
          )}
          {chatMode === 'strategy' && selectedModelType === 'text' && (
            <div className='flex items-center gap-2'><Switch checked={streamMode} onCheckedChange={setStreamMode} /><span className='text-xs text-muted-foreground whitespace-nowrap'>{streamMode ? t('chat.stream') : t('chat.nonStream')}</span></div>
          )}
        </div>

        <div className='flex-1 overflow-y-auto px-6 py-4 space-y-4'>
          {messages.length === 0 && (
            <div className='flex flex-col items-center justify-center h-full text-muted-foreground'><Boxes className='h-12 w-12 mb-3 opacity-30' /><div className='text-sm font-medium'>{t('chat.welcome')}</div><div className='text-xs mt-1'>{t('chat.welcomeHint')}</div></div>
          )}
          {messages.map((msg, idx) => (
            <div key={idx} className={'flex gap-3 ' + (msg.role === 'user' ? 'justify-end' : 'justify-start')}>
              {msg.role === 'assistant' && <div className='flex-shrink-0 h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center'><Bot className='h-4 w-4 text-primary' /></div>}
              <div className={'max-w-[70%] rounded-2xl px-4 py-3 text-sm ' + (msg.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted')}>
                {msg.files && msg.files.length > 0 && <div className='flex flex-wrap gap-2 mb-2'>{msg.files.map((f, fi) => <div key={fi}>{f.preview ? <img src={f.preview} alt={f.name} className='h-20 rounded-lg border object-cover' /> : <div className='flex items-center gap-1.5 text-xs bg-background/10 rounded-lg px-2 py-1'><FileText className='h-3 w-3' />{f.name}</div>}</div>)}</div>}
                {msg.richType === 'image' && msg.imageUrls && msg.imageUrls.length > 0 && <div className='flex flex-wrap gap-2 mb-2'>{msg.imageUrls.map((url, ui) => <a key={ui} href={url} target='_blank' rel='noopener noreferrer' className='block'><img src={url} alt={'Generated ' + (ui + 1)} className='max-w-xs max-h-80 rounded-lg border object-contain hover:opacity-90 transition-opacity' /></a>)}</div>}
                {msg.richType === 'audio' && msg.audioUrl && <div className='mb-2'><audio controls src={msg.audioUrl} className='w-full max-w-sm h-10' /><a href={msg.audioUrl} download='speech.mp3' className='flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground mt-1'><Download className='h-3 w-3' />{t('chat.downloadAudio')}</a></div>}
                {msg.richType === 'video_task' && msg.videoTask && <div className='mb-2'>{msg.videoTask.status === 'completed' && msg.videoTask.videoUrl ? <div><video controls src={msg.videoTask.videoUrl} className='max-w-sm max-h-64 rounded-lg border' /><a href={msg.videoTask.videoUrl} target='_blank' rel='noopener noreferrer' className='flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground mt-1'><Download className='h-3 w-3' />{t('chat.downloadVideo')}</a></div> : <div className='flex items-center gap-2 text-xs text-muted-foreground'>{msg.videoTask.status !== 'failed' && <Loader2 className='h-4 w-4 animate-spin text-orange-500' />}<span className='font-medium'>{t('chat.videoStatus')}: </span><span className={msg.videoTask.status === 'failed' ? 'text-destructive' : 'text-orange-600 dark:text-orange-400'}>{msg.videoTask.status}</span>{msg.videoTask.id && <span className='text-[10px] opacity-60'> ({msg.videoTask.id})</span>}</div>}</div>}
                {msg.content ? <div className='whitespace-pre-wrap break-words'>{msg.content}</div> : msg.role === 'assistant' && isStreaming && idx === messages.length - 1 && <div className='flex items-center gap-1.5 text-muted-foreground'><Loader2 className='h-3.5 w-3.5 animate-spin' /><span className='text-xs'>{t('chat.thinking')}</span></div>}
                {msg.role === 'assistant' && msg.content && <button onClick={() => copyMessage(msg.content, idx)} className='mt-2 flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors'>{copiedIdx === idx ? <Check className='h-3 w-3' /> : <Copy className='h-3 w-3' />}{copiedIdx === idx ? t('common.copied') : t('common.copy')}</button>}
              </div>
              {msg.role === 'user' && <div className='flex-shrink-0 h-8 w-8 rounded-full bg-muted flex items-center justify-center'><User className='h-4 w-4' /></div>}
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        <div className='border-t px-6 py-3 bg-background/80 backdrop-blur-sm'>
          {attachedFiles.length > 0 && <div className='flex flex-wrap gap-2 mb-2'>{attachedFiles.map((f, i) => <div key={i} className='flex items-center gap-1.5 text-xs bg-muted rounded-lg px-2 py-1'>{f.preview ? <img src={f.preview} alt='' className='h-6 w-6 rounded object-cover' /> : <FileText className='h-3 w-3' />}<span className='max-w-[120px] truncate'>{f.name}</span><button onClick={() => removeFile(i)} className='text-muted-foreground hover:text-destructive ml-1'>x</button></div>)}</div>}
          <div className='flex items-end gap-2'>
            {selectedModelType === 'text' && <div className='flex gap-1'><Button variant='ghost' size='sm' className='h-9 w-9 p-0' onClick={() => fileInputRef.current?.click()}><Paperclip className='h-4 w-4' /></Button><Button variant='ghost' size='sm' className='h-9 w-9 p-0' onClick={() => { const inp = document.createElement('input'); inp.type = 'file'; inp.accept = 'image/*'; inp.multiple = true; inp.onchange = (e: any) => { Array.from(e.target.files || []).forEach(file => { const reader = new FileReader(); reader.onload = () => setAttachedFiles(prev => [...prev, { name: file.name, type: file.type, file, preview: reader.result as string }]); reader.readAsDataURL(file); }); }; inp.click(); }}><ImageIcon className='h-4 w-4' /></Button></div>}
            <input ref={fileInputRef} type='file' multiple className='hidden' onChange={handleFileAttach} />
            <Textarea ref={textareaRef} value={input} onChange={e => setInput(e.target.value)} onKeyDown={handleKeyDown} placeholder={isReady ? placeholderText : t('chat.selectModelFirst')} className='flex-1 min-h-[40px] max-h-[200px] resize-none text-sm' disabled={isStreaming} />
            <Button size='sm' className='h-10 w-10 p-0' onClick={sendMessage} disabled={isStreaming || !isReady || (!input.trim() && attachedFiles.length === 0)}>{isStreaming ? <Loader2 className='h-4 w-4 animate-spin' /> : <Send className='h-4 w-4' />}</Button>
          </div>
        </div>
      </div>
    </div>
  );
}
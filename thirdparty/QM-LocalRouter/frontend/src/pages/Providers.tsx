import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getProviders, createProvider, updateProvider, deleteProvider,
  searchIcons, saveIcon, getHotProviders,
  getKeys, createKey, deleteKey, testKey, testAllKeys, deleteInvalidKeys,
  getModels, createModel, updateModel, deleteModel, fetchModels, syncModels, testAllModels, deleteInvalidModels, clearModels,
} from '../services/api';
import { useI18n } from '../i18n';
import { toast } from '../stores/toast';
import { Button } from '../components/ui/button';
import { Card, CardContent } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Badge } from '../components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '../components/ui/dialog';
import { Select, SelectTrigger, SelectContent, SelectItem, SelectValue } from '../components/ui/select';
import { Switch } from '../components/ui/switch';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { Separator } from '../components/ui/separator';
import {
  Plus, Pencil, Trash2, Trash, Server, Wand2, KeyRound, Zap, Loader2, RefreshCw, Play, Layers, Cpu,
  Video, Mic, Box, ChevronRight, ImageIcon, Search, X, Flame, Copy, Globe,
} from 'lucide-react';

const protocolColors: Record<string, string> = {
  openai: 'bg-green-500/10 text-green-400 border-green-500/20',
  claude: 'bg-orange-500/10 text-orange-400 border-orange-500/20',
  gemini: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
  custom: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
};

const knownPaths: Record<string, string> = {
  'api.openai.com': '/v1',
  'api.deepseek.com': '/v1',
  'api.anthropic.com': '/v1',
  'generativelanguage.googleapis.com': '/v1beta',
  'api.groq.com': '/openai/v1',
  'api.moonshot.cn': '/v1',
  'api.siliconflow.cn': '/v1',
  'openrouter.ai': '/api/v1',
  'api.x.ai': '/v1',
};

const endpointSuffixes = ['/chat/completions', '/completions', '/messages', '/embeddings', '/models'];

const contextPresets = [
  { label: '4K', value: 4096 },
  { label: '8K', value: 8192 },
  { label: '16K', value: 16384 },
  { label: '32K', value: 32768 },
  { label: '64K', value: 65536 },
  { label: '128K', value: 131072 },
  { label: '200K', value: 200000 },
  { label: '1M', value: 1000000 },
];
function iconUrl(icon: string | undefined): string {
  if (!icon) return "";
  if (icon.startsWith("http")) return icon;
  if (icon.startsWith("icons/")) return "/api/icons/file/" + icon.replace("icons/", "");
  return icon;
}


function extractHost(url: string) {
  try { return new URL(url.startsWith('http') ? url : 'https://' + url).hostname; } catch (_e) { return ''; }
}

function normalizeBaseUrl(input: string) {
  if (!input) return { base: input, stripped: null as string | null };
  const trimmed = input.trim().replace(/\/$/, '');
  if (!trimmed) return { base: trimmed, stripped: null };
  try {
    const parsed = new URL(trimmed.startsWith('http') ? trimmed : 'https://' + trimmed);
    const pathname = parsed.pathname.replace(/\/$/, '');
    if (!pathname || pathname === '/') return { base: trimmed, stripped: null };
    for (const suffix of endpointSuffixes) {
      if (pathname.toLowerCase().endsWith(suffix)) {
        const bp = pathname.slice(0, pathname.toLowerCase().lastIndexOf(suffix));
        return { base: parsed.origin + (bp || ''), stripped: suffix };
      }
    }
  } catch (_e) {}
  return { base: trimmed, stripped: null };
}

function autoCompleteUrl(input: string) {
  if (!input) return input;
  const { base } = normalizeBaseUrl(input);
  const trimmed = base.replace(/\/$/, '');
  if (!trimmed) return trimmed;
  try { new URL(trimmed.startsWith('http') ? trimmed : 'https://' + trimmed); } catch (_e) { return trimmed; }
  const host = extractHost(trimmed);
  const kp = knownPaths[host];
  if (kp) return trimmed.replace(/\/$/, '') + kp;
  return trimmed;
}
export default function Providers() {
  const { t } = useI18n();
  const qc = useQueryClient();

  const protocols = [
    { value: 'openai', label: 'OpenAI', desc: 'OpenAI / DeepSeek / ' + t('providers.compatibleApi') },
    { value: 'claude', label: 'Claude', desc: 'Anthropic Claude API' },
    { value: 'gemini', label: 'Gemini', desc: 'Google Gemini API' },
    { value: 'custom', label: 'Custom', desc: t('providers.customProtocol') },
  ];

  const modelTypeOpts = [
    { value: 'text', label: t('providers.textModel'), icon: Layers, color: 'bg-sky-500/10 text-sky-400 border-sky-500/20' },
    { value: 'image', label: t('providers.imageModel'), icon: ImageIcon, color: 'bg-pink-500/10 text-pink-400 border-pink-500/20' },
    { value: 'video', label: t('providers.videoModel'), icon: Video, color: 'bg-amber-500/10 text-amber-400 border-amber-500/20' },
    { value: 'tts', label: t('providers.ttsModel'), icon: Mic, color: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' },
    { value: 'embedding', label: t('providers.embeddingModel'), icon: Box, color: 'bg-violet-500/10 text-violet-400 border-violet-500/20' },
  ];

  const [selectedProvider, setSelectedProvider] = useState<any>(null);
  const [providerDialogOpen, setProviderDialogOpen] = useState(false);
  const [editingProvider, setEditingProvider] = useState<any>(null);
  const [providerForm, setProviderForm] = useState({ name: '', protocol: 'openai', base_url: '', description: '', icon: '', homepage: '', is_active: true });
  const [autoComplete, setAutoComplete] = useState(true);
  const [urlPreview, setUrlPreview] = useState('');

  const [keyDialogOpen, setKeyDialogOpen] = useState(false);
  const [keyForm, setKeyForm] = useState({ key_value: '', alias: '', weight: 1 });
  const [testingKeyId, setTestingKeyId] = useState<number | null>(null);
  const [testingAll, setTestingAll] = useState(false);
  const [deletingInvalid, setDeletingInvalid] = useState(false);
const [testingAllModels, setTestingAllModels] = useState(false);
const [deletingInvalidModels, setDeletingInvalidModels] = useState(false);
const [clearingModels, setClearingModels] = useState(false);

  const [modelDialogOpen, setModelDialogOpen] = useState(false);
  const [editingModel, setEditingModel] = useState<any>(null);
  const [modelForm, setModelForm] = useState({
    model_id: '', display_name: '', model_type: 'text', is_multimodal: false,
    context_window: '', temperature: '', price_input: '', price_output: '', is_active: true,
  });
  const [syncDialogOpen, setSyncDialogOpen] = useState(false);
  const [fetchedModels, setFetchedModels] = useState<any[]>([]);
  const [selectedSyncIds, setSelectedSyncIds] = useState<Set<string>>(new Set());
  const [syncFetching, setSyncFetching] = useState(false);
  const [addSingleModelLoading, setAddSingleModelLoading] = useState<Map<string, boolean>>(new Map());
  const [syncModelSearch, setSyncModelSearch] = useState('');

  const [iconSearchOpen, setIconSearchOpen] = useState(false);
  const [iconKeyword, setIconKeyword] = useState('');
  const [iconResults, setIconResults] = useState<any[]>([]);
  const [iconSearching, setIconSearching] = useState(false);
  const [iconSaving, setIconSaving] = useState(false);
  const [iconEngine, setIconEngine] = useState('baidu');
  const [providerSearch, setProviderSearch] = useState('');
  const [modelSearch, setModelSearch] = useState('');

  const [hotDialogOpen, setHotDialogOpen] = useState(false);
  const [hotProviders, setHotProviders] = useState<any[]>([]);
  const [hotLoading, setHotLoading] = useState(false);
  const [hotSearch, setHotSearch] = useState('');

  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [confirmDeleteKeyId, setConfirmDeleteKeyId] = useState<number | null>(null);
  // --- Queries ---
  const { data: providers = [] } = useQuery({
    queryKey: ['providers'],
    queryFn: () => getProviders().then(r => r.data),
  });
  const { data: keys = [] } = useQuery({
    queryKey: ['keys', selectedProvider?.id],
    queryFn: () => selectedProvider ? getKeys(selectedProvider.id).then(r => r.data) : Promise.resolve([]),
    enabled: !!selectedProvider,
  });
  const { data: models = [] } = useQuery({
    queryKey: ['models', selectedProvider?.id],
    queryFn: () => selectedProvider ? getModels(selectedProvider.id).then(r => r.data) : Promise.resolve([]),
    enabled: !!selectedProvider,
  });

  // --- Mutations ---
  const createProvMut = useMutation({
    mutationFn: (data: any) => createProvider(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['providers'] });
      toast({ title: t('providers.providerCreated'), variant: 'success' });
      setProviderDialogOpen(false);
    },
    onError: () => toast({ title: t('providers.createFailed'), variant: 'destructive' }),
  });

  const updateProvMut = useMutation({
    mutationFn: ({ id, data }: any) => updateProvider(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['providers'] });
      toast({ title: t('providers.providerUpdated'), variant: 'success' });
      setProviderDialogOpen(false);
    },
    onError: () => toast({ title: t('providers.createFailed'), variant: 'destructive' }),
  });

  const deleteProvMut = useMutation({
    mutationFn: (id: number) => deleteProvider(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['providers'] });
      toast({ title: t('providers.providerDeleted'), variant: 'success' });
      if (selectedProvider?.id === confirmDeleteId) setSelectedProvider(null);
      setConfirmDeleteId(null);
    },
    onError: () => toast({ title: t('providers.deleteFailed'), variant: 'destructive' }),
  });

  const createKeyMut = useMutation({
    mutationFn: (data: any) => createKey(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['keys', selectedProvider?.id] });
      toast({ title: t('providers.keyAdded'), variant: 'success' });
      setKeyDialogOpen(false);
      setKeyForm({ key_value: '', alias: '', weight: 1 });
    },
    onError: () => toast({ title: t('providers.addFailed'), variant: 'destructive' }),
  });

  const deleteKeyMut = useMutation({
    mutationFn: (id: number) => deleteKey(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['keys', selectedProvider?.id] });
      toast({ title: t('providers.keyDeleted'), variant: 'success' });
      setConfirmDeleteKeyId(null);
    },
    onError: () => toast({ title: t('providers.deleteFailed'), variant: 'destructive' }),
  });

  const testKeyMut = useMutation({
    mutationFn: (id: number) => {
      setTestingKeyId(id);
      return testKey(id);
    },
    onSuccess: (res: any) => {
      qc.invalidateQueries({ queryKey: ['keys', selectedProvider?.id] });
      toast({
        title: res.data.success ? t('providers.testSuccess') : t('providers.testFailed'),
        variant: res.data.success ? 'success' : 'destructive',
        description: res.data.message,
      });
      setTestingKeyId(null);
    },
    onError: () => {
      toast({ title: t('providers.testFailed'), variant: 'destructive' });
      setTestingKeyId(null);
    },
  });
  const testAllMut = useMutation({
    mutationFn: () => {
      if (!selectedProvider) return Promise.reject();
      setTestingAll(true);
      return testAllKeys(selectedProvider.id);
    },
    onSuccess: (res: any) => {
      qc.invalidateQueries({ queryKey: ['keys', selectedProvider?.id] });
      toast({ title: t('providers.batchTestDone') + ': ' + res.data.success + '/' + res.data.total, variant: 'success' });
      setTestingAll(false);
    },
    onError: () => {
      toast({ title: t('providers.batchTestFailed'), variant: 'destructive' });
      setTestingAll(false);
    },
  });

  const deleteInvalidMut = useMutation({
    mutationFn: () => {
      if (!selectedProvider) return Promise.reject();
      setDeletingInvalid(true);
      return deleteInvalidKeys(selectedProvider.id);
    },
    onSuccess: (res: any) => {
      qc.invalidateQueries({ queryKey: ['keys', selectedProvider?.id] });
      toast({ title: t('providers.invalidDeleted') + ': ' + res.data.deleted, variant: 'success' });
      setDeletingInvalid(false);
    },
    onError: () => {
      toast({ title: t('providers.deleteFailed'), variant: 'destructive' });
      setDeletingInvalid(false);
    },
  });

    const testAllModelsMut = useMutation({
    mutationFn: () => {
      if (!selectedProvider) return Promise.reject();
      setTestingAllModels(true);
      return testAllModels(selectedProvider.id);
    },
    onSuccess: (res: any) => {
      qc.invalidateQueries({ queryKey: ['models', selectedProvider?.id] });
      toast({ title: t('providers.modelBatchTestDone') + ': ' + (res.data?.success ?? '') + '/' + (res.data?.total ?? ''), variant: 'success' });
      setTestingAllModels(false);
    },
    onError: () => {
      toast({ title: t('providers.modelBatchTestFailed'), variant: 'destructive' });
      setTestingAllModels(false);
    },
  });

  const deleteInvalidModelsMut = useMutation({
    mutationFn: () => {
      if (!selectedProvider) throw new Error('No provider selected');
      return deleteInvalidModels(selectedProvider.id);
    },
    onMutate: () => setDeletingInvalidModels(true),
    onSettled: () => setDeletingInvalidModels(false),
    onSuccess: (res: any) => {
      qc.invalidateQueries({ queryKey: ['models', selectedProvider?.id] });
      toast({ title: t('providers.modelInvalidDeleted') + ': ' + (res.data?.deleted ?? ''), variant: 'success' });
    },
    onError: () => {
      toast({ title: t('providers.deleteFailed'), variant: 'destructive' });
    },
  });

  const clearModelsMut = useMutation({
    mutationFn: () => {
      if (!selectedProvider) throw new Error('No provider selected');
      return clearModels(selectedProvider.id);
    },
    onMutate: () => setClearingModels(true),
    onSettled: () => setClearingModels(false),
    onSuccess: (res: any) => {
      qc.invalidateQueries({ queryKey: ['models', selectedProvider?.id] });
      toast({ title: t('providers.modelsCleared') + ': ' + (res.data?.deleted ?? ''), variant: 'success' });
    },
    onError: () => {
      toast({ title: t('providers.deleteFailed'), variant: 'destructive' });
    },
  });

const createModelMut = useMutation({
    mutationFn: (data: any) => createModel(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['models', selectedProvider?.id] });
      toast({ title: t('providers.modelAdded'), variant: 'success' });
      setModelDialogOpen(false);
    },
    onError: () => toast({ title: t('providers.createFailed'), variant: 'destructive' }),
  });

  const updateModelMut = useMutation({
    mutationFn: ({ id, data }: any) => updateModel(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['models', selectedProvider?.id] });
      toast({ title: t('providers.modelUpdated'), variant: 'success' });
      setModelDialogOpen(false);
    },
    onError: () => toast({ title: t('providers.createFailed'), variant: 'destructive' }),
  });

  const deleteModelMut = useMutation({
    mutationFn: (id: number) => deleteModel(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['models', selectedProvider?.id] });
      toast({ title: t('providers.modelDeleted'), variant: 'success' });
    },
    onError: () => toast({ title: t('providers.deleteFailed'), variant: 'destructive' }),
  });

  const [testingModelId, setTestingModelId] = useState<number | null>(null);
  const testModelMut = useMutation({
    mutationFn: async (m: any) => {
      setTestingModelId(m.id);
      try {
        const res = await fetch('/v1/chat/completions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            model: m.model_id,
            messages: [{ role: 'user', content: 'hi' }],
            stream: false,
            max_tokens: 5,
            _direct_provider_id: m.provider_id,
          }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.error?.detail || res.statusText);
        }
        return res.json();
      } finally {
        setTestingModelId(null);
      }
    },
    onSuccess: () => toast({ title: t('common.success'), variant: 'success' }),
    onError: (err: any) => toast({ title: t('common.error'), description: err.message?.slice(0, 100), variant: 'destructive' }),
  });

  // --- Sync Models Handlers ---
  function handleSyncSelectAll() {
    const addable = fetchedModels.filter((m: any) => !m.already_added);
    if (selectedSyncIds.size === addable.length) {
      setSelectedSyncIds(new Set());
    } else {
      setSelectedSyncIds(new Set(addable.map((m: any) => m.model_id)));
    }
  }

  function handleSyncInvert() {
    const newSelected = new Set<string>();
    for (const m of fetchedModels) {
      if (m.already_added) continue;
      if (!selectedSyncIds.has(m.model_id)) newSelected.add(m.model_id);
    }
    setSelectedSyncIds(newSelected);
  }

  function handleSyncToggle(modelId: string) {
    const next = new Set(selectedSyncIds);
    if (next.has(modelId)) {
      next.delete(modelId);
    } else {
      next.add(modelId);
    }
    setSelectedSyncIds(next);
  }

  async function handleAddSingleModel(m: any) {
    setAddSingleModelLoading(prev => new Map(prev).set(m.model_id, true));
    try {
      await createModel({
        provider_id: selectedProvider.id,
        model_id: m.model_id,
        display_name: m.display_name || '',
        is_multimodal: m.is_multimodal || false,
        model_type: m.model_type || 'text',
        context_window: m.context_window || null,
        temperature: m.temperature ?? null,
        price_input: m.price_input ?? null,
        price_output: m.price_output ?? null,
      });
      qc.invalidateQueries({ queryKey: ['models', selectedProvider?.id] });
      toast({ title: t('providers.modelAdded'), variant: 'success' });
      // Mark as already_added in local state
      setFetchedModels(prev => prev.map(x => x.model_id === m.model_id ? { ...x, already_added: true } : x));
      setSelectedSyncIds(prev => { const n = new Set(prev); n.delete(m.model_id); return n; });
    } catch {
      toast({ title: t('providers.addFailed'), variant: 'destructive' });
    } finally {
      setAddSingleModelLoading(prev => { const n = new Map(prev); n.delete(m.model_id); return n; });
    }
  }

  async function handleBatchAddModels() {
    const toAdd = fetchedModels.filter((m: any) => selectedSyncIds.has(m.model_id) && !m.already_added);
    let successCount = 0;
    let failCount = 0;
    for (const m of toAdd) {
      setAddSingleModelLoading(prev => new Map(prev).set(m.model_id, true));
      try {
        await createModel({
          provider_id: selectedProvider.id,
          model_id: m.model_id,
          display_name: m.display_name || '',
          is_multimodal: m.is_multimodal || false,
          model_type: m.model_type || 'text',
          context_window: m.context_window || null,
          temperature: m.temperature ?? null,
          price_input: m.price_input ?? null,
          price_output: m.price_output ?? null,
        });
        successCount++;
        setFetchedModels(prev => prev.map(x => x.model_id === m.model_id ? { ...x, already_added: true } : x));
      } catch {
        failCount++;
      } finally {
        setAddSingleModelLoading(prev => { const n = new Map(prev); n.delete(m.model_id); return n; });
      }
    }
    qc.invalidateQueries({ queryKey: ['models', selectedProvider?.id] });
    setSelectedSyncIds(new Set());
    toast({
      title: t('providers.batchAddResult', { success: successCount, fail: failCount }) || `添加成功 ${successCount} 个，失败 ${failCount} 个`,
      variant: failCount > 0 ? 'destructive' : 'success',
    });
  }

  // --- Handlers ---
  function openCreateProvider() {
    setEditingProvider(null);
    setProviderForm({ name: '', protocol: 'openai', base_url: '', description: '', icon: '', homepage: '', is_active: true });
    setAutoComplete(true);
    setUrlPreview('');
    setProviderDialogOpen(true);
  }

  function openEditProvider(p: any) {
    setEditingProvider(p);
    setProviderForm({ name: p.name, protocol: p.protocol, base_url: p.base_url, description: p.description || '', icon: p.icon || '', homepage: p.homepage || '', is_active: p.is_active });
    setAutoComplete(false);
    setUrlPreview(p.base_url);
    setProviderDialogOpen(true);
  }

  function handleProviderUrlChange(val: string) {
    setProviderForm(f => ({ ...f, base_url: val }));
    if (autoComplete) {
      setUrlPreview(autoCompleteUrl(val));
    } else {
      setUrlPreview(val);
    }
  }

  function saveProvider() {
    const data = { ...providerForm };
    if (autoComplete && urlPreview) data.base_url = urlPreview;
    const { stripped } = normalizeBaseUrl(data.base_url);
    if (stripped) {
      const { base } = normalizeBaseUrl(data.base_url);
      data.base_url = base;
    }
    if (editingProvider) {
      updateProvMut.mutate({ id: editingProvider.id, data });
    } else {
      createProvMut.mutate(data);
    }
  }

  function openCreateKey() {
    setKeyForm({ key_value: '', alias: '', weight: 1 });
    setKeyDialogOpen(true);
  }

  function saveKey() {
    if (!selectedProvider) return;
    createKeyMut.mutate({ ...keyForm, provider_id: selectedProvider.id });
  }

  function openCreateModel() {
    setEditingModel(null);
    setModelForm({ model_id: '', display_name: '', model_type: 'text', is_multimodal: false, context_window: '', temperature: '', price_input: '', price_output: '', is_active: true });
    setModelDialogOpen(true);
  }

  function openEditModel(m: any) {
    setEditingModel(m);
    setModelForm({
      model_id: m.model_id, display_name: m.display_name || '', model_type: m.model_type || 'text',
      is_multimodal: m.is_multimodal || false, context_window: m.context_window ?? '',
      temperature: m.temperature ?? '', price_input: m.price_input ?? '',
      price_output: m.price_output ?? '', is_active: m.is_active,
    });
    setModelDialogOpen(true);
  }

  function saveModel() {
    if (!selectedProvider) return;
    const data: any = {
      ...modelForm,
      provider_id: selectedProvider.id,
      context_window: modelForm.context_window ? Number(modelForm.context_window) : null,
      temperature: modelForm.temperature ? Number(modelForm.temperature) : null,
      price_input: modelForm.price_input ? Number(modelForm.price_input) : null,
      price_output: modelForm.price_output ? Number(modelForm.price_output) : null,
    };
    if (editingModel) {
      updateModelMut.mutate({ id: editingModel.id, data });
    } else {
      createModelMut.mutate(data);
    }
  }

  async function handleIconSearch() {
    if (!iconKeyword.trim()) return;
    setIconSearching(true);
    try {
      const res = await searchIcons(iconKeyword.trim(), 0, iconEngine);
      setIconResults(res.data?.results || res.data || []);
    } catch (_e) { toast({ title: t('providers.searchFailed'), variant: 'destructive' }); }
    setIconSearching(false);
  }
  async function handleIconSelect(url: string) {
    setIconSaving(true);
    try {
      const providerId = selectedProvider?.id || 0;
      const saveRes = await saveIcon(url, providerId);
      if (selectedProvider) {
        qc.invalidateQueries({ queryKey: ['providers'] });
        setSelectedProvider((prev: any) => prev ? { ...prev, icon: saveRes.data.path } : prev);
      }
      setProviderForm((f: any) => ({ ...f, icon: saveRes.data.path }));
      toast({ title: t('providers.iconSet'), variant: 'success' });
      setIconSearchOpen(false);
      setIconResults([]);
    } catch (_e) { toast({ title: t('providers.iconSaveFailed'), variant: 'destructive' }); }
    setIconSaving(false);
  }

  async function openHotProviders() {
    setHotDialogOpen(true);
    setHotLoading(true);
    try {
      const res = await getHotProviders();
      setHotProviders(res.data || []);
    } catch (_e) { toast({ title: t('providers.loadFailed'), variant: 'destructive' }); }
    setHotLoading(false);
  }

  function selectHotProvider(p: any) {
    setEditingProvider(null);
    setProviderForm({ name: p.name, protocol: p.protocol || 'openai', base_url: p.base_url || '', description: p.description || '', icon: p.icon || '', homepage: p.homepage || '', is_active: true });
    setAutoComplete(true);
    setUrlPreview(autoCompleteUrl(p.base_url || ''));
    setHotDialogOpen(false);
    setProviderDialogOpen(true);
  }

  const filteredHot = hotProviders.filter((p: any) => {
    if (!hotSearch) return true;
    const q = hotSearch.toLowerCase();
    return (p.name || '').toLowerCase().includes(q) || (p.protocol || '').toLowerCase().includes(q) || (p.description || '').toLowerCase().includes(q);
  });

  function getKeyStatusBadge(status: string) {
    if (status === 'active') return <Badge className='bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-xs'>{t('providers.keyStatusActive')}</Badge>;
    if (status === 'inactive' || status === 'expired' || status === 'rate_limited') return <Badge className='bg-red-500/10 text-red-400 border border-red-500/20 text-xs'>{t('providers.keyStatusInactive')}</Badge>;
    return <Badge className='bg-yellow-500/10 text-yellow-400 border border-yellow-500/20 text-xs'>{t('providers.keyStatusUntested')}</Badge>;
  }

  function getModelTypeBadge(type: string) {
    const mt = modelTypeOpts.find(m => m.value === type);
    if (!mt) return <Badge className='text-xs'>{type}</Badge>;
    const Icon = mt.icon;
    return <Badge className={mt.color + ' text-xs border flex items-center gap-1'}><Icon className='w-3 h-3' />{mt.label}</Badge>;
  }

  function getModelTestStatusBadge(status: string) {
    if (status === 'active') return <Badge className='bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-xs'>{t('common.active')}</Badge>;
    if (status === 'inactive') return <Badge className='bg-red-500/10 text-red-400 border border-red-500/20 text-xs'>{t('common.inactive')}</Badge>;
    return <Badge className='bg-gray-500/10 text-gray-400 border border-gray-500/20 text-xs'>{t('providers.keyStatusUntested')}</Badge>;
  }

  const activeProviders = providers.filter((p: any) => p.is_active);

  const filteredProviders = providers.filter((p: any) => !providerSearch || p.name.toLowerCase().includes(providerSearch.toLowerCase()));

  return (
    <>
    <div className='flex h-[calc(100vh-4rem)] gap-4 p-4'>
      <div className='w-72 flex-shrink-0 flex flex-col gap-2'>
        <div className='flex items-center justify-between mb-2'>
          <h2 className='text-lg font-semibold'>{t('providers.title')}</h2>
          <div className='flex gap-1'>
            <Button variant='outline' size='sm' onClick={openHotProviders}><Flame className='w-4 h-4 mr-1' />{t('providers.hotPlatforms')}</Button>
            <Button size='sm' onClick={openCreateProvider}><Plus className='w-4 h-4' /></Button>
          </div>
        </div>
        <div className='relative'>
          <Search className='absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground' />
          <Input value={providerSearch} onChange={e => setProviderSearch(e.target.value)} placeholder={t('common.search') + '...'} className='pl-8 h-8 text-xs' />
        </div>
        <div className='flex-1 overflow-y-auto space-y-1'>
          {filteredProviders.length === 0 && (
            <div className='text-center text-muted-foreground py-8'>{providerSearch ? t('providers.noProviders') : t('providers.noProviders')}</div>
          )}
          {filteredProviders.map((p: any) => (
            <div key={p.id} className={`p-3 rounded-lg border cursor-pointer transition-all hover:border-primary/50 ${selectedProvider?.id === p.id ? 'border-primary bg-primary/5' : 'border-border'}`} onClick={() => setSelectedProvider(p)}>
              <div className='flex items-center gap-2'>
                {p.icon ? <img src={iconUrl(p.icon)} alt='' className='w-6 h-6 rounded' /> : <Server className='w-5 h-5 text-muted-foreground' />}
                <span className='flex-1 font-medium text-sm truncate'>{p.name}</span>
              <Badge className={`${protocolColors[p.protocol] || ''} text-[10px] border`}>{p.protocol.toUpperCase()}</Badge>
              </div>
              <div className='flex items-center justify-between mt-1'>
                <span className='text-xs text-muted-foreground truncate max-w-[140px]'>{p.base_url}</span>
                <div className='flex gap-1'>
                  <Button variant='ghost' size='sm' className='h-6 w-6 p-0' onClick={(e) => { e.stopPropagation(); openEditProvider(p); }}><Pencil className='w-3 h-3' /></Button>
                  <Button variant='ghost' size='sm' className='h-6 w-6 p-0 text-destructive' onClick={(e) => { e.stopPropagation(); setConfirmDeleteId(p.id); }}><Trash2 className='w-3 h-3' /></Button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className='flex-1 overflow-y-auto'>
        {!selectedProvider ? (
          <div className='flex flex-col items-center justify-center h-full text-muted-foreground'>
            <Server className='w-16 h-16 mb-4 opacity-30' />
            <p className='text-lg'>{t('providers.selectProviderHint')}</p>
            <p className='text-sm mt-1'>{t('providers.orClickPlus')}</p>
          </div>
        ) : (
          <div className='space-y-4'>
            <div className='flex items-center justify-between'>
              <div className='flex items-center gap-3'>
                {selectedProvider.icon ? <img src={iconUrl(selectedProvider.icon)} alt='' className='w-10 h-10 rounded-lg' /> : <Server className='w-8 h-8 text-muted-foreground' />}
                <div><h3 className='text-lg font-semibold'>{selectedProvider.name}</h3><p className='text-sm text-muted-foreground'>{selectedProvider.base_url}</p></div>
              </div>
              <Button
                variant='outline'
                size='sm'
                disabled={!selectedProvider.homepage}
                onClick={() => selectedProvider.homepage && window.open(selectedProvider.homepage, '_blank', 'noopener,noreferrer')}
              >
                <Globe className='w-3 h-3 mr-1' />{t('providers.visitHomepage')}
              </Button>
            </div>
            <Card><CardContent className='p-4'>

              <Separator className='my-3' />
              <div className='flex items-center justify-between mb-2 bg-muted/50 rounded-lg px-3 py-2'>
                <h4 className='font-medium flex items-center gap-2'><KeyRound className='w-4 h-4' />{t('providers.apiKeys')}</h4>
                <div className='flex gap-1'>
                  <Button variant='outline' size='sm' onClick={() => testAllMut.mutate()} disabled={testingAll}>{testingAll ? <Loader2 className='w-3 h-3 animate-spin mr-1' /> : <Zap className='w-3 h-3 mr-1' />}{t('providers.testAll')}</Button>
                  <Button variant='outline' size='sm' onClick={() => deleteInvalidMut.mutate()} disabled={deletingInvalid}>{deletingInvalid ? <Loader2 className='w-3 h-3 animate-spin mr-1' /> : <Trash className='w-3 h-3 mr-1' />}{t('providers.deleteInvalid')}</Button>
                  <Button size='sm' onClick={openCreateKey}><Plus className='w-3 h-3 mr-1' />{t('providers.addKey')}</Button>
                </div>
              </div>
              {keys.length === 0 ? <p className='text-sm text-muted-foreground py-2'>{t('providers.noKeys')}</p> : (
                <Table><TableHeader><TableRow>
                  <TableHead>{t('providers.keyValue')}</TableHead>
                  <TableHead>{t('providers.alias')}</TableHead>
                  <TableHead>{t('providers.weight')}</TableHead>
                  <TableHead>{t('providers.status')}</TableHead>
                  <TableHead>{t('providers.errorInfo')}</TableHead>
                  <TableHead>{t('providers.actions')}</TableHead>
                </TableRow></TableHeader><TableBody>
                  {keys.map((k: any) => (
                    <TableRow key={k.id}>
                      <TableCell className='font-mono text-xs'>
                        <span className='flex items-center gap-1'>
                          {k.key_masked}
                          <Button variant='ghost' size='sm' className='h-5 w-5 p-0 opacity-50 hover:opacity-100' onClick={() => { navigator.clipboard.writeText(k.key_value); toast({ title: t('common.copied'), variant: 'success' as any }); }}>
                            <Copy className='h-3 w-3' />
                          </Button>
                        </span>
                      </TableCell>
                      <TableCell>{k.alias || '-'}</TableCell>
                      <TableCell>{k.weight}</TableCell>
                      <TableCell>{getKeyStatusBadge(k.status)}</TableCell>
                      <TableCell className='text-xs text-muted-foreground max-w-[200px] truncate'>{k.last_error || '-'}</TableCell>
                      <TableCell>
                        <div className='flex gap-1'>
                          <Button variant='ghost' size='sm' className='h-7' onClick={() => testKeyMut.mutate(k.id)} disabled={testingKeyId === k.id}>{testingKeyId === k.id ? <Loader2 className='w-3 h-3 animate-spin' /> : <Zap className='w-3 h-3' />}</Button>
                          <Button variant='ghost' size='sm' className='h-7 text-destructive' onClick={() => setConfirmDeleteKeyId(k.id)}><Trash2 className='w-3 h-3' /></Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody></Table>
              )}

              <Separator className='my-3' />
              <div className='flex items-center justify-between mb-2 bg-muted/50 rounded-lg px-3 py-2'>
                <h4 className='font-medium flex items-center gap-2'><Cpu className='w-4 h-4' />{t('providers.modelsTitle')}</h4>
                <div className='flex items-center gap-2'>
                  <div className='relative'>
                    <Search className='absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground' />
                    <Input value={modelSearch} onChange={e => setModelSearch(e.target.value)} placeholder={t('common.search') + '...'} className='pl-7 h-7 text-xs w-40' />
                  </div>
                  <Button variant='outline' size='sm' onClick={() => testAllModelsMut.mutate()} disabled={testingAllModels}>{testingAllModels ? <Loader2 className='w-3 h-3 animate-spin mr-1' /> : <Zap className='w-3 h-3 mr-1' />}{t('providers.testAllModels')}</Button>
                  <Button variant='outline' size='sm' onClick={() => deleteInvalidModelsMut.mutate()} disabled={deletingInvalidModels}>{deletingInvalidModels ? <Loader2 className='w-3 h-3 animate-spin mr-1' /> : <Trash className='w-3 h-3 mr-1' />}{t('providers.deleteInvalidModels')}</Button>
                  <Button variant='outline' size='sm' onClick={() => { if (window.confirm(t('providers.confirmClearModels'))) clearModelsMut.mutate(); }} disabled={clearingModels}>{clearingModels ? <Loader2 className='w-3 h-3 animate-spin mr-1' /> : <Trash2 className='w-3 h-3 mr-1' />}{t('providers.clearModels')}</Button>
                  <Button variant='outline' size='sm' onClick={async () => {
                  setSyncFetching(true);
                  try {
                    const res = await fetchModels(selectedProvider.id);
                    setFetchedModels(res.data || []);
                    setSelectedSyncIds(new Set());
                    setSyncDialogOpen(true);
                  } catch {
                    toast({ title: t('providers.syncFailed'), variant: 'destructive' });
                  } finally {
                    setSyncFetching(false);
                  }
                }} disabled={syncFetching}>{syncFetching ? <Loader2 className='w-3 h-3 animate-spin mr-1' /> : <RefreshCw className='w-3 h-3 mr-1' />}{t('providers.syncModels')}</Button>
                  <Button size='sm' onClick={openCreateModel}><Plus className='w-3 h-3 mr-1' />{t('providers.addModel')}</Button>
                </div>
              </div>
              {models.length === 0 ? (
                <div className='text-center py-4 text-muted-foreground'><p>{t('providers.noModels')}</p><p className='text-xs mt-1'>{t('providers.noModelsHint')}</p></div>
              ) : models.filter((m: any) => !modelSearch || m.model_id.toLowerCase().includes(modelSearch.toLowerCase()) || (m.display_name || '').toLowerCase().includes(modelSearch.toLowerCase())).length === 0 ? (
                <div className='text-center py-4 text-muted-foreground'><p>{modelSearch ? t('common.search') + ': ' + modelSearch : t('providers.noModels')}</p></div>
              ) : (
                <Table><TableHeader><TableRow>
                  <TableHead>{t('providers.modelId')}</TableHead>
                  <TableHead>{t('providers.displayName')}</TableHead>
                  <TableHead>{t('providers.type')}</TableHead>
                  <TableHead>{t('providers.isMultimodal')}</TableHead>
                  <TableHead>{t('providers.context')}</TableHead>
                  <TableHead>{t('providers.price')}</TableHead>
                  <TableHead>{t('providers.status')}</TableHead>
                  <TableHead>{t('providers.actions')}</TableHead>
                </TableRow></TableHeader><TableBody>
                  {models.filter((m: any) => !modelSearch || m.model_id.toLowerCase().includes(modelSearch.toLowerCase()) || (m.display_name || '').toLowerCase().includes(modelSearch.toLowerCase())).map((m: any) => (
                    <TableRow key={m.id}>
                      <TableCell className='font-mono text-xs'>
                        <span className='flex items-center gap-1'>
                          {m.model_id}
                          <Button variant='ghost' size='sm' className='h-5 w-5 p-0 opacity-50 hover:opacity-100' onClick={() => { navigator.clipboard.writeText(m.model_id); toast({ title: t('common.copied'), variant: 'success' as any }); }}>
                            <Copy className='h-3 w-3' />
                          </Button>
                        </span>
                      </TableCell>
                      <TableCell>{m.display_name || '-'}</TableCell>
                      <TableCell>{getModelTypeBadge(m.model_type)}</TableCell>
                      <TableCell>{m.is_multimodal ? t('providers.isYes') : '-'}</TableCell>
                      <TableCell className='text-xs'>{m.context_window ? (m.context_window >= 1000000 ? (m.context_window / 1000000) + 'M' : m.context_window >= 1000 ? (m.context_window / 1000) + 'K' : m.context_window) : '-'}</TableCell>
                      <TableCell className='text-xs'>{m.price_input != null ? '$' + m.price_input : '-'}</TableCell>
                      <TableCell>{getModelTestStatusBadge(m.status || 'untested')}</TableCell>
                      <TableCell>
                        <div className='flex gap-1 items-center'>
                          <Switch checked={m.is_active} onCheckedChange={(v) => updateModelMut.mutate({ id: m.id, data: { is_active: v } })} />
                          <Button variant='ghost' size='sm' className='h-7' title={t('common.test')} onClick={() => testModelMut.mutate(m)} disabled={testingModelId === m.id}>{testingModelId === m.id ? <Loader2 className='w-3 h-3 animate-spin' /> : <Play className='w-3 h-3' />}</Button>
                          <Button variant='ghost' size='sm' className='h-7' onClick={() => openEditModel(m)}><Pencil className='w-3 h-3' /></Button>
                          <Button variant='ghost' size='sm' className='h-7 text-destructive hover:text-destructive' title={t('common.delete')} onClick={() => deleteModelMut.mutate(m.id)}><Trash2 className='w-3 h-3' /></Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody></Table>
              )}
            </CardContent></Card>
          </div>
        )}
      </div>
    </div>

    {/* Provider Dialog */}
    <Dialog open={providerDialogOpen} onOpenChange={setProviderDialogOpen}>
      <DialogContent className='max-w-lg'>
        <DialogHeader><DialogTitle>{editingProvider ? t('providers.editProviderTitle') : t('providers.addProviderTitle')}</DialogTitle></DialogHeader>
        <div className='space-y-4'>
          <div className='flex items-center gap-3'>
            <div className='w-12 h-12 rounded-lg border flex items-center justify-center bg-muted'>
              {providerForm.icon ? <img src={iconUrl(providerForm.icon)} alt='' className='w-10 h-10 rounded' /> : <Server className='w-6 h-6 text-muted-foreground' />}
            </div>
            <div className='flex-1'>
              <Label>{t('providers.platformIcon')}</Label>
              <div className='flex gap-1 mt-1'>
                <Button variant='outline' size='sm' onClick={() => { setIconSearchOpen(true); setIconKeyword((selectedProvider?.name || providerForm.name || '') + ' icon'); setIconResults([]); }}><Search className='w-3 h-3 mr-1' />{t('providers.searchIcon')}</Button>
                {providerForm.icon && <Button variant='outline' size='sm' onClick={() => setProviderForm(f => ({ ...f, icon: '' }))}><X className='w-3 h-3 mr-1' />{t('providers.clearIcon')}</Button>}
              </div>
            </div>
          </div>

          <div><Label>{t('providers.platformName')}</Label><Input value={providerForm.name} onChange={e => setProviderForm(f => ({ ...f, name: e.target.value }))} className='mt-1' /></div>

          <div><Label>{t('providers.protocolType')}</Label>
            <Select value={providerForm.protocol} onValueChange={v => setProviderForm(f => ({ ...f, protocol: v }))}>
              <SelectTrigger className='mt-1'><SelectValue /></SelectTrigger>
              <SelectContent>{protocols.map(p => <SelectItem key={p.value} value={p.value}>{p.label} - {p.desc}</SelectItem>)}</SelectContent>
            </Select>
          </div>

          <div><Label>{t('providers.baseUrl')}</Label><Input value={autoComplete ? urlPreview : providerForm.base_url} onChange={e => handleProviderUrlChange(e.target.value)} className='mt-1' placeholder='https://api.openai.com/v1' /></div>

          <div className='flex items-center gap-3'>
            <Switch checked={autoComplete} onCheckedChange={v => { setAutoComplete(v); if (v) setUrlPreview(autoCompleteUrl(providerForm.base_url)); else setUrlPreview(providerForm.base_url); }} />
            <div><p className='text-sm font-medium'>{t('providers.urlAutoComplete')}</p><p className='text-xs text-muted-foreground'>{t('providers.urlAutoCompleteDesc')}</p></div>
          </div>

          <div><Label>{t('providers.description')}</Label><Input value={providerForm.description} onChange={e => setProviderForm(f => ({ ...f, description: e.target.value }))} className='mt-1' /></div>

          <div><Label>{t('providers.homepage')}</Label><Input value={providerForm.homepage} onChange={e => setProviderForm(f => ({ ...f, homepage: e.target.value }))} className='mt-1' placeholder='https://openai.com' /></div>
          <p className='text-xs text-muted-foreground -mt-2'>{t('providers.homepageDesc')}</p>

          <div className='flex items-center gap-3'>
            <Switch checked={providerForm.is_active} onCheckedChange={v => setProviderForm(f => ({ ...f, is_active: v }))} />
            <Label>{t('providers.enabled')}</Label>
          </div>
        </div>
        <DialogFooter>
          <Button variant='outline' onClick={() => setProviderDialogOpen(false)}>{t('providers.cancel')}</Button>
          <Button onClick={saveProvider} disabled={createProvMut.isPending || updateProvMut.isPending}>{(createProvMut.isPending || updateProvMut.isPending) ? <Loader2 className='w-4 h-4 animate-spin mr-1' /> : null}{editingProvider ? t('providers.saveBtn') : t('providers.createBtn')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    {/* Key Dialog */}
    <Dialog open={keyDialogOpen} onOpenChange={setKeyDialogOpen}>
      <DialogContent className='max-w-md'>
        <DialogHeader><DialogTitle>{t('providers.addApiKeyTitle')}</DialogTitle></DialogHeader>
        <div className='space-y-4'>
          <div><Label>{t('providers.keyValue')}</Label><Input value={keyForm.key_value} onChange={e => setKeyForm(f => ({ ...f, key_value: e.target.value }))} className='mt-1' placeholder='sk-...' /></div>
          <div><Label>{t('providers.alias')}</Label><Input value={keyForm.alias} onChange={e => setKeyForm(f => ({ ...f, alias: e.target.value }))} className='mt-1' placeholder='My Key' /></div>
          <div><Label>{t('providers.weight')} ({t('providers.weightHint')})</Label><Input type='number' value={keyForm.weight} onChange={e => setKeyForm(f => ({ ...f, weight: Number(e.target.value) }))} className='mt-1' min={1} /></div>
        </div>
        <DialogFooter>
          <Button variant='outline' onClick={() => setKeyDialogOpen(false)}>{t('providers.cancel')}</Button>
          <Button onClick={saveKey} disabled={createKeyMut.isPending}>{createKeyMut.isPending ? <Loader2 className='w-4 h-4 animate-spin mr-1' /> : null}{t('providers.saveBtn')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    {/* Model Dialog */}
    <Dialog open={modelDialogOpen} onOpenChange={setModelDialogOpen}>
      <DialogContent className='max-w-lg'>
        <DialogHeader><DialogTitle>{editingModel ? t('providers.editModelTitle') : t('providers.addModelTitle')}</DialogTitle></DialogHeader>
        <div className='space-y-4'>
          <div><Label>{t('providers.modelId')}</Label><Input value={modelForm.model_id} onChange={e => setModelForm(f => ({ ...f, model_id: e.target.value }))} className='mt-1' placeholder='gpt-4o' /></div>
          <div><Label>{t('providers.displayName')}</Label><Input value={modelForm.display_name} onChange={e => setModelForm(f => ({ ...f, display_name: e.target.value }))} className='mt-1' /></div>

          <div><Label>{t('providers.modelType')}</Label>
            <div className='flex flex-wrap gap-2 mt-2'>
              {modelTypeOpts.map(mt => {
                const Icon = mt.icon;
                return (
                  <button key={mt.value} type='button' onClick={() => setModelForm(f => ({ ...f, model_type: mt.value }))} className={mt.color + ' flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-sm transition-all ' + (modelForm.model_type === mt.value ? 'border-current' : 'border-border hover:border-primary/50')}>
                    <Icon className='w-3.5 h-3.5' />{mt.label}
                  </button>
                );
              })}
            </div>
          </div>

          <div className='flex items-center gap-3'>
            <Switch checked={modelForm.is_multimodal} onCheckedChange={v => setModelForm(f => ({ ...f, is_multimodal: v }))} />
            <div><p className='text-sm font-medium'>{t('providers.multimodal')}</p><p className='text-xs text-muted-foreground'>{t('providers.multimodalDesc')}</p></div>
          </div>

          <div><Label>{t('providers.contextWindow')}</Label>
            <div className='flex flex-wrap gap-1.5 mt-2'>
              {contextPresets.map(cp => (
                <button key={cp.value} type='button' onClick={() => setModelForm(f => ({ ...f, context_window: cp.value }))} className={'px-2.5 py-1 rounded-md border text-xs transition-all ' + (Number(modelForm.context_window) === cp.value ? 'bg-primary text-primary-foreground border-primary' : 'border-border hover:border-primary/50')}>{cp.label}</button>
              ))}
              <Input type='number' value={modelForm.context_window} onChange={e => setModelForm(f => ({ ...f, context_window: e.target.value }))} className='w-24 h-8 text-xs' placeholder='Custom' />
            </div>
          </div>

          <div><Label>{t('providers.defaultTemp')}</Label><Input type='number' value={modelForm.temperature} onChange={e => setModelForm(f => ({ ...f, temperature: e.target.value }))} className='mt-1' min={0} max={2} step={0.1} placeholder='0.7' /></div>

          <div className='grid grid-cols-2 gap-3'>
            <div><Label>{t('providers.inputPrice')} {t('providers.perMTokens')}</Label><Input type='number' value={modelForm.price_input} onChange={e => setModelForm(f => ({ ...f, price_input: e.target.value }))} className='mt-1' min={0} step={0.01} placeholder='0.00' /></div>
            <div><Label>{t('providers.outputPrice')} {t('providers.perMTokens')}</Label><Input type='number' value={modelForm.price_output} onChange={e => setModelForm(f => ({ ...f, price_output: e.target.value }))} className='mt-1' min={0} step={0.01} placeholder='0.00' /></div>
          </div>
        </div>
        <DialogFooter>
          <Button variant='outline' onClick={() => setModelDialogOpen(false)}>{t('providers.cancel')}</Button>
          <Button onClick={saveModel} disabled={createModelMut.isPending || updateModelMut.isPending}>{(createModelMut.isPending || updateModelMut.isPending) ? <Loader2 className='w-4 h-4 animate-spin mr-1' /> : null}{editingModel ? t('providers.saveBtn') : t('providers.createBtn')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    {/* Icon Search Dialog */}
    <Dialog open={iconSearchOpen} onOpenChange={v => { setIconSearchOpen(v); if (!v) { setIconResults([]); setIconKeyword(''); } }}>
      <DialogContent className='max-w-lg'>
        <DialogHeader><DialogTitle>{t('providers.searchIconTitle')}</DialogTitle></DialogHeader>
        <div className='space-y-4'>
          <div className='flex gap-2'>
            <Input value={iconKeyword} onChange={e => setIconKeyword(e.target.value)} placeholder={t('providers.iconKeywordHint')} onKeyDown={e => e.key === 'Enter' && handleIconSearch()} />
            <Button onClick={handleIconSearch} disabled={iconSearching}>{iconSearching ? <Loader2 className='w-4 h-4 animate-spin' /> : <Search className='w-4 h-4' />}</Button>
          </div>
          <div className='flex gap-1'>
            {['baidu', 'bing', 'sogou'].map(eng => (
              <button key={eng} type='button' onClick={() => setIconEngine(eng)}
                className={'px-3 py-1 text-xs rounded-md border transition-all ' + (iconEngine === eng ? 'bg-primary text-primary-foreground border-primary' : 'bg-muted text-muted-foreground border-border hover:bg-muted/80')}>
                {eng === 'baidu' ? 'Baidu' : eng === 'bing' ? 'Bing' : 'Sogou'}
              </button>
            ))}
          </div>
          {iconResults.length > 0 && (
            <div className='grid grid-cols-3 gap-2'>
              {iconResults.map((item: any, i) => (
                <button key={i} type='button' onClick={() => handleIconSelect(item.thumb || item.url || item)} className='aspect-square rounded-lg border overflow-hidden hover:border-primary transition-all relative group'>
                  <img src={item.thumb || item.url || item} alt='' className='w-full h-full object-contain p-1' />
                  <div className='absolute inset-0 bg-primary/10 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center'><span className='text-xs bg-primary text-primary-foreground px-2 py-0.5 rounded'>{t('providers.selectBtn')}</span></div>
                </button>
              ))}
            </div>
          )}
          {iconSearching && <div className='text-center py-4 text-muted-foreground'><Loader2 className='w-6 h-6 animate-spin mx-auto mb-2' />{t('providers.searching')}</div>}
          {!iconSearching && iconResults.length === 0 && iconKeyword && <p className='text-center text-muted-foreground py-4'>{t('providers.noResults')}</p>}
        </div>
      </DialogContent>
    </Dialog>

    {/* Hot Providers Dialog */}
    <Dialog open={hotDialogOpen} onOpenChange={setHotDialogOpen}>
      <DialogContent className='max-w-2xl max-h-[80vh] flex flex-col'>
        <DialogHeader><DialogTitle>{t('providers.hotProvidersQuickAdd')}</DialogTitle></DialogHeader>
        <div className='flex-1 overflow-hidden flex flex-col'>
          <Input value={hotSearch} onChange={e => setHotSearch(e.target.value)} placeholder={t('providers.hotSearchHint')} className='mb-3' />
          {hotLoading ? (
            <div className='text-center py-8 text-muted-foreground'><Loader2 className='w-6 h-6 animate-spin mx-auto mb-2' />{t('providers.loading')}</div>
          ) : (
            <div className='flex-1 overflow-y-auto space-y-1'>
              {filteredHot.length === 0 && <p className='text-center text-muted-foreground py-4'>{t('providers.noMatchProviders')}</p>}
              {filteredHot.map((p: any, i: number) => (
                <button key={i} type='button' onClick={() => selectHotProvider(p)} className='w-full text-left p-3 rounded-lg border hover:border-primary/50 transition-all flex items-center gap-3'>
                  <div className='w-8 h-8 rounded bg-muted flex items-center justify-center'>
                    {p.icon ? <img src={iconUrl(p.icon)} alt='' className='w-6 h-6 rounded' /> : <Server className='w-4 h-4 text-muted-foreground' />}
                  </div>
                  <div className='flex-1 min-w-0'><p className='font-medium text-sm truncate'>{p.name}</p><p className='text-xs text-muted-foreground truncate'>{p.base_url}</p></div>
                  <Badge className={`${protocolColors[p.protocol] || ''} text-[10px] border`}>{p.protocol?.toUpperCase()}</Badge>
                  <ChevronRight className='w-4 h-4 text-muted-foreground' />
                </button>
              ))}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>

    {/* Confirm Delete Provider */}
    <Dialog open={confirmDeleteId !== null} onOpenChange={v => { if (!v) setConfirmDeleteId(null); }}>
      <DialogContent className='max-w-sm'>
        <DialogHeader><DialogTitle>{t('providers.delete')}</DialogTitle></DialogHeader>
        <p className='text-sm text-muted-foreground'>{t('providers.confirmDeleteProvider')}</p>
        <DialogFooter>
          <Button variant='outline' onClick={() => setConfirmDeleteId(null)}>{t('providers.cancel')}</Button>
          <Button variant='destructive' onClick={() => confirmDeleteId && deleteProvMut.mutate(confirmDeleteId)}>{t('providers.delete')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    {/* Confirm Delete Key */}
    <Dialog open={confirmDeleteKeyId !== null} onOpenChange={v => { if (!v) setConfirmDeleteKeyId(null); }}>
      <DialogContent className='max-w-sm'>
        <DialogHeader><DialogTitle>{t('providers.delete')}</DialogTitle></DialogHeader>
        <p className='text-sm text-muted-foreground'>{t('providers.confirmDeleteKey')}</p>
        <DialogFooter>
          <Button variant='outline' onClick={() => setConfirmDeleteKeyId(null)}>{t('providers.cancel')}</Button>
          <Button variant='destructive' onClick={() => confirmDeleteKeyId && deleteKeyMut.mutate(confirmDeleteKeyId)}>{t('providers.delete')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    {/* Sync Models Dialog */}
    <Dialog open={syncDialogOpen} onOpenChange={v => { if (!v) { setSyncDialogOpen(false); setFetchedModels([]); setSelectedSyncIds(new Set()); setSyncModelSearch(''); } }}>
      <DialogContent className='max-w-[90vw] max-h-[85vh] flex flex-col'>
        <DialogHeader>
          <DialogTitle>{t('providers.syncModelsTitle') || '同步平台模型 - ' + selectedProvider?.name}</DialogTitle>
        </DialogHeader>
        <div className='flex-1 flex flex-col min-h-0'>
          <div className='relative mb-3'>
            <Search className='absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground' />
            <Input value={syncModelSearch} onChange={e => setSyncModelSearch(e.target.value)} placeholder={t('common.search') + '...'} className='pl-8 h-9 text-sm' />
          </div>
          {(() => {
            const filteredModels = fetchedModels.filter((m: any) =>
              !syncModelSearch || m.model_id.toLowerCase().includes(syncModelSearch.toLowerCase()) ||
              (m.display_name || '').toLowerCase().includes(syncModelSearch.toLowerCase()) ||
              (m.model_type || '').toLowerCase().includes(syncModelSearch.toLowerCase())
            );
            const addableCount = filteredModels.filter((m: any) => !m.already_added).length;
            const selectedInFilter = filteredModels.filter((m: any) => selectedSyncIds.has(m.model_id));
            return (<>
            <div className='flex items-center justify-between mb-3 gap-2 flex-wrap'>
            <div className='flex items-center gap-2'>
              <label className='flex items-center gap-1.5 text-sm cursor-pointer select-none'>
                <input type='checkbox' checked={filteredModels.length > 0 && selectedInFilter.length === addableCount && addableCount > 0}
                  onChange={() => {
                    const addable = filteredModels.filter((m: any) => !m.already_added);
                    if (selectedInFilter.length === addable.length && addable.length > 0) {
                      setSelectedSyncIds(new Set([...selectedSyncIds].filter(id => !addable.some((m: any) => m.model_id === id))));
                    } else {
                      setSelectedSyncIds(new Set([...selectedSyncIds, ...addable.map((m: any) => m.model_id)]));
                    }
                  }} className='w-4 h-4 rounded border-border accent-primary' />
                {t('strategies.selectAll')}
              </label>
              <Button variant='ghost' size='sm' onClick={() => {
                const newSelected = new Set(selectedSyncIds);
                for (const m of filteredModels) {
                  if (m.already_added) continue;
                  if (newSelected.has(m.model_id)) newSelected.delete(m.model_id);
                  else newSelected.add(m.model_id);
                }
                setSelectedSyncIds(newSelected);
              }}>{t('providers.invertSelection') || '反选'}</Button>
            </div>
            <div className='flex items-center gap-2'>
              <span className='text-sm text-muted-foreground'>{t('providers.syncFetchedCount', { count: filteredModels.length }) || '获取到 ' + filteredModels.length + ' 个模型'}</span>
              {selectedSyncIds.size > 0 && <span className='text-sm text-primary'>{t('providers.selectedCount', { count: selectedSyncIds.size }) || '已选 ' + selectedSyncIds.size + ' 个'}</span>}
              <Button size='sm' disabled={selectedSyncIds.size === 0} onClick={handleBatchAddModels}>
                <Plus className='w-3 h-3 mr-1' />{t('providers.batchAdd') || '批量添加'} ({selectedSyncIds.size})
              </Button>
            </div>
          </div>
          <div className='flex-1 overflow-y-auto border rounded-lg'>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className='w-10'></TableHead>
                  <TableHead>{t('providers.modelId')}</TableHead>
                  <TableHead>{t('providers.displayName')}</TableHead>
                  <TableHead>{t('providers.type')}</TableHead>
                  <TableHead>{t('providers.isMultimodal')}</TableHead>
                  <TableHead>{t('providers.context')}</TableHead>
                  <TableHead>{t('providers.price')}</TableHead>
                  <TableHead className='w-20'>{t('providers.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredModels.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={8} className='text-center text-muted-foreground py-8'>{syncFetching ? <Loader2 className='w-4 h-4 animate-spin mx-auto' /> : t('common.noData')}</TableCell>
                  </TableRow>
                ) : (
                  filteredModels.map((m: any) => {
                    const isSelected = selectedSyncIds.has(m.model_id);
                    const isAlreadyAdded = m.already_added;
                    return (
                      <TableRow key={m.model_id} className={isAlreadyAdded ? 'opacity-50' : ''}>
                        <TableCell>
                          <input type='checkbox' checked={isSelected} disabled={isAlreadyAdded} onChange={() => handleSyncToggle(m.model_id)} className='w-4 h-4 rounded border-border accent-primary' />
                        </TableCell>
                        <TableCell className='font-mono text-xs'>
                          <span className='flex items-center gap-1'>
                            {m.model_id}
                            {isAlreadyAdded && <Badge className='bg-muted text-muted-foreground text-[10px]'>{t('providers.alreadyAdded') || '已添加'}</Badge>}
                          </span>
                        </TableCell>
                        <TableCell>{m.display_name || '-'}</TableCell>
                        <TableCell>{getModelTypeBadge(m.model_type)}</TableCell>
                        <TableCell>{m.is_multimodal ? t('providers.isYes') : '-'}</TableCell>
                        <TableCell className='text-xs'>{m.context_window ? (m.context_window >= 1000000 ? (m.context_window / 1000000) + 'M' : m.context_window >= 1000 ? (m.context_window / 1000) + 'K' : m.context_window) : '-'}</TableCell>
                        <TableCell className='text-xs'>{m.price_input != null ? '$' + m.price_input : '-'}</TableCell>
                        <TableCell>
                          <Button
                            variant='outline'
                            size='sm'
                            className='h-7 text-xs'
                            disabled={isAlreadyAdded || addSingleModelLoading.get(m.model_id)}
                            onClick={() => handleAddSingleModel(m)}
                          >
                            {addSingleModelLoading.get(m.model_id) ? <Loader2 className='w-3 h-3 animate-spin' /> : <Plus className='w-3 h-3' />}
                            {t('common.add')}
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })
                )}
              </TableBody>
            </Table>
          </div>
          </>);
          })()}
        </div>
      </DialogContent>
    </Dialog>

    </>
  );
}

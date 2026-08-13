import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getStrategies, createStrategy, updateStrategy, deleteStrategy,
  getProviders, getModels, testStrategy,
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
import { Textarea } from '../components/ui/textarea';
import { Plus, Trash2, Pencil, Zap, GitBranch, X, Loader2, ArrowRight, Check, Search, ListChecks } from 'lucide-react';

interface Rule { provider_id: number; model_id: number; priority: number; weight: number; is_active: boolean; }

export default function Strategies() {
  const { t } = useI18n();
  const qc = useQueryClient();

  const keyStrategyOptions = [
    { value: 'round_robin', label: t('strategies.optionRoundRobin'), desc: t('strategies.optionDescOrder') },
    { value: 'random', label: t('strategies.optionRandom'), desc: t('strategies.optionDescRandom') },
    { value: 'failover', label: t('strategies.optionFailover'), desc: t('strategies.optionDescFailover') },
  ];

  const keySwitchOptions = [
    { value: 'none', label: t('strategies.optionNoSwitch'), desc: t('strategies.optionNoSwitchDesc') },
    { value: 'rpm_threshold', label: t('strategies.optionRPM'), desc: t('strategies.optionRPMDesc') },
    { value: 'count_threshold', label: t('strategies.optionCount'), desc: t('strategies.optionCountDesc') },
  ];

  const lbOptions = [
    { value: 'round_robin', label: t('strategies.optionRoundRobin'), desc: t('strategies.optionDescOrder') },
    { value: 'weighted', label: t('strategies.optionWeighted'), desc: t('strategies.optionDescWeight') },
    { value: 'random', label: t('strategies.optionRandom'), desc: t('strategies.optionDescRandom') },
    { value: 'failover', label: t('strategies.optionFailover'), desc: t('strategies.optionDescFailover') },
    { value: 'priority', label: t('strategies.optionPriority'), desc: t('strategies.optionDescHighest') },
    { value: 'token_threshold', label: t('strategies.optionTokenThreshold'), desc: t('strategies.optionTokenThresholdDesc') },
  ];

  const tokenPeriodOptions = [
    { value: 'per_minute', label: t('strategies.tokenPeriodMinute') },
    { value: 'per_5min', label: t('strategies.tokenPeriod5Min') },
    { value: 'per_day', label: t('strategies.tokenPeriodDay') },
    { value: 'per_month', label: t('strategies.tokenPeriodMonth') },
  ];

  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<any>(null);
  const [form, setForm] = useState({ name: '', description: '', lb_strategy: 'round_robin', key_strategy: 'round_robin', key_switch_mode: 'none', key_rpm_threshold: 0, key_count_threshold: 0, rule_token_threshold: 0, rule_token_period: 'per_day', is_active: true, timeout: 120, retry_count: 2, rules: [] as Rule[] });
  const [newRule, setNewRule] = useState({ provider_id: 0, model_id: 0, priority: 0, weight: 1, is_active: true });
  const [testingId, setTestingId] = useState<number | null>(null);
  const [testResults, setTestResults] = useState<Record<number, any>>({});

  // Create by model dialog state
  const [byModelOpen, setByModelOpen] = useState(false);
  const [byModelProviders, setByModelProviders] = useState<any[]>([]);
  const [byModelSelProvider, setByModelSelProvider] = useState<number>(0);
  const [byModelModels, setByModelModels] = useState<any[]>([]);
  const [byModelChecked, setByModelChecked] = useState<Set<number>>(new Set());
  const [byModelSearch, setByModelSearch] = useState('');
  const [byModelLoading, setByModelLoading] = useState(false);

  const { data: strategies = [] } = useQuery({ queryKey: ['strategies'], queryFn: () => getStrategies().then((r) => r.data) });
  const { data: providers = [] } = useQuery({ queryKey: ['providers'], queryFn: () => getProviders().then((r) => r.data) });
  const { data: models = [] } = useQuery({ queryKey: ['models', newRule.provider_id], queryFn: () => newRule.provider_id ? getModels(newRule.provider_id).then((r) => r.data) : [], enabled: !!newRule.provider_id });

  const createMut = useMutation({
    mutationFn: (d: any) => createStrategy(d),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['strategies'] }); setOpen(false); toast({ title: t('strategies.created'), variant: 'success' }); },
    onError: (e: any) => toast({ title: t('strategies.createFailed'), description: e?.response?.data?.detail, variant: 'destructive' }),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, ...d }: any) => updateStrategy(id, d),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['strategies'] }); setOpen(false); toast({ title: t('strategies.updated'), variant: 'success' }); },
    onError: (e: any) => toast({ title: t('strategies.updateFailed'), description: e?.response?.data?.detail, variant: 'destructive' }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteStrategy(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['strategies'] }); toast({ title: t('strategies.deleted'), variant: 'success' }); },
  });

  const testMut = useMutation({
    mutationFn: (id: number) => { setTestingId(id); return testStrategy(id); },
    onSuccess: (res, id) => { setTestingId(null); setTestResults((prev) => ({ ...prev, [id]: res.data })); toast({ title: res.data.success ? t('strategies.testSuccess') : t('strategies.testFailed'), description: res.data.message, variant: res.data.success ? 'success' : 'destructive' }); },
    onError: () => { setTestingId(null); toast({ title: t('strategies.testFailed'), variant: 'destructive' }); },
  });

  const toggleActive = useMutation({
    mutationFn: ({ id, is_active }: { id: number; is_active: boolean }) => updateStrategy(id, { is_active }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['strategies'] }); },
    onError: () => { toast({ title: t('common.error'), variant: 'destructive' }); },
  });

  const openByModel = async () => {
    setByModelChecked(new Set());
    setByModelSearch('');
    setByModelSelProvider(0);
    setByModelModels([]);
    setByModelOpen(true);
    setByModelLoading(true);
    try {
      const res = await getProviders();
      setByModelProviders(res.data || []);
    } catch (_e) { toast({ title: t('common.error'), variant: 'destructive' }); }
    setByModelLoading(false);
  };

  const loadByModelModels = async (providerId: number) => {
    setByModelSelProvider(providerId);
    setByModelLoading(true);
    try {
      const res = await getModels(providerId);
      setByModelModels(res.data || []);
    } catch (_e) { toast({ title: t('common.error'), variant: 'destructive' }); }
    setByModelLoading(false);
  };

  const toggleByModelCheck = (modelId: number) => {
    setByModelChecked(prev => {
      const next = new Set(prev);
      if (next.has(modelId)) next.delete(modelId); else next.add(modelId);
      return next;
    });
  };

  const toggleByModelAll = () => {
    const filteredIds = new Set(byModelFiltered.map((m: any) => m.id));
    const allFilteredSelected = byModelFiltered.length > 0 && byModelFiltered.every((m: any) => byModelChecked.has(m.id));
    if (allFilteredSelected) {
      setByModelChecked(prev => { const next = new Set(prev); filteredIds.forEach(id => next.delete(id)); return next; });
    } else {
      setByModelChecked(prev => { const next = new Set(prev); filteredIds.forEach(id => next.add(id)); return next; });
    }
  };

  const byModelFiltered = byModelModels.filter((m: any) => !byModelSearch || m.model_id.toLowerCase().includes(byModelSearch.toLowerCase()) || (m.display_name || '').toLowerCase().includes(byModelSearch.toLowerCase()));

  const openCreate = () => {
    setEditing(null);
    setForm({ name: '', description: '', lb_strategy: 'round_robin', key_strategy: 'round_robin', key_switch_mode: 'none', key_rpm_threshold: 0, key_count_threshold: 0, rule_token_threshold: 0, rule_token_period: 'per_day', is_active: true, timeout: 120, retry_count: 2, rules: [] });
    setOpen(true);
  };

  const openEdit = (s: any) => {
    setEditing(s);
    setForm({
      name: s.name, description: s.description || '', lb_strategy: s.lb_strategy, key_strategy: s.key_strategy || 'round_robin', key_switch_mode: s.key_switch_mode || 'none', key_rpm_threshold: s.key_rpm_threshold || 0, key_count_threshold: s.key_count_threshold || 0, rule_token_threshold: s.rule_token_threshold || 0, rule_token_period: s.rule_token_period || 'per_day',
      is_active: s.is_active, timeout: s.timeout, retry_count: s.retry_count,
      rules: (s.rules || []).map((r: any) => ({ provider_id: r.provider_id, model_id: r.model_id, model_name: r.model_name || '', priority: r.priority, weight: r.weight, is_active: r.is_active })),
    });
    setOpen(true);
  };

  const addRule = () => {
    if (newRule.provider_id && newRule.model_id) {
      const modelName = (models as any[]).find((m: any) => m.id === newRule.model_id)?.model_id || '';
      setForm({ ...form, rules: [...form.rules, { ...newRule, model_name: modelName }] });
      setNewRule({ provider_id: 0, model_id: 0, priority: 0, weight: 1, is_active: true });
    }
  };

  const removeRule = (idx: number) => setForm({ ...form, rules: form.rules.filter((_, i) => i !== idx) });

  const save = () => {
    const payload = {
      name: form.name, description: form.description, lb_strategy: form.lb_strategy,
      key_strategy: form.key_strategy, key_switch_mode: form.key_switch_mode,
      key_rpm_threshold: form.key_rpm_threshold, key_count_threshold: form.key_count_threshold,
      rule_token_threshold: form.rule_token_threshold, rule_token_period: form.rule_token_period,
      is_active: form.is_active, timeout: form.timeout, retry_count: form.retry_count,
      rules: form.rules,
    };
    if (editing) { updateMut.mutate({ id: editing.id, ...payload }); }
    else { createMut.mutate(payload); }
  };

  const getProviderName = (id: number) => providers.find((p: any) => p.id === id)?.name || `${id}`;

  return (
    <div className='space-y-6'>
      <div className='flex items-center justify-between'>
        <div>
          <h1 className='text-2xl font-bold tracking-tight'>{t('strategies.title')}</h1>
          <p className='text-sm text-muted-foreground mt-1'>{t('strategies.routingRules')}</p>
        </div>
        <div className='flex gap-2'>
          <Button variant='outline' onClick={openByModel} className='gap-2'><ListChecks className='h-4 w-4' />{t('strategies.createByModel')}</Button>
          <Button onClick={openCreate} className='gap-2'><Plus className='h-4 w-4' />{t('strategies.createStrategy')}</Button>
        </div>
      </div>

      {strategies.length === 0 ? (
        <Card className='border-dashed'>
          <CardContent className='flex flex-col items-center justify-center py-16'>
            <GitBranch className='h-12 w-12 text-muted-foreground/30 mb-4' />
            <p className='text-lg font-medium text-muted-foreground'>{t('strategies.noRules')}</p>
            <Button onClick={openCreate} variant='outline' className='gap-2 mt-4'><Plus className='h-4 w-4' />{t('strategies.createStrategy')}</Button>
          </CardContent>
        </Card>
      ) : (
        <div className='grid gap-4'>
          {strategies.map((s: any) => (
            <Card key={s.id} className='card-hover'>
              <CardContent className='p-5'>
                <div className='flex items-start justify-between mb-4'>
                  <div className='flex items-center gap-3'>
                    <div className='flex h-10 w-10 items-center justify-center rounded-xl bg-purple-500/10'>
                      <GitBranch className='h-5 w-5 text-purple-400' />
                    </div>
                    <div>
                      <h3 className='font-semibold'>{s.name}</h3>
                      {s.description && <p className='text-xs text-muted-foreground mt-0.5'>{s.description}</p>}
                    </div>
                  </div>
                  <div className='flex items-center gap-2'>
                    <Badge variant='outline'>{lbOptions.find(l => l.value === s.lb_strategy)?.label || s.lb_strategy}</Badge>
                    {s.lb_strategy === 'token_threshold' && s.rule_token_threshold > 0 && (
                      <Badge variant='outline' className='bg-green-500/10 text-green-400 border-green-500/20'>
                        {t('strategies.tokenThreshold')}: {s.rule_token_threshold.toLocaleString()} / {tokenPeriodOptions.find(p => p.value === (s.rule_token_period || 'per_day'))?.label || s.rule_token_period}
                      </Badge>
                    )}
                    <Badge variant='outline' className='bg-blue-500/10 text-blue-400 border-blue-500/20'>Key: {keyStrategyOptions.find(k => k.value === (s.key_strategy || 'round_robin'))?.label || s.key_strategy}</Badge>
                    {s.key_switch_mode && s.key_switch_mode !== 'none' && (
                      <Badge variant='outline' className='bg-amber-500/10 text-amber-400 border-amber-500/20'>
                        {s.key_switch_mode === 'rpm_threshold' ? 'RPM>' + s.key_rpm_threshold : s.key_count_threshold + t('strategies.countUnit')}
                      </Badge>
                    )}
                    {s.is_active ? <Badge variant='success'>{t('common.enabled')}</Badge> : <Badge variant='secondary'>{t('common.disabled')}</Badge>}
                  </div>
                </div>

                <div className='flex items-center gap-4 text-xs text-muted-foreground mb-3'>
                  <span>{t('strategies.routingRules')}: {s.rules?.length || 0}</span>
                  <span>{t('strategies.timeout')}: {s.timeout}s</span>
                  <span>{t('strategies.retryCount')}: {s.retry_count}</span>
                </div>

                {s.rules && s.rules.length > 0 && (
                  <div className='flex flex-wrap gap-2 mb-4'>
                    {s.rules.map((r: any, i: number) => (
                      <div key={i} className='flex items-center gap-1.5 text-xs bg-muted/60 rounded-md px-2.5 py-1.5'>
                        <span className='font-medium'>{getProviderName(r.provider_id)}</span>
                        <ArrowRight className='h-3 w-3 text-muted-foreground' />
                        <span className='text-muted-foreground'>{r.model_name || ('Model #' + r.model_id)}</span>
                        <Badge variant='outline' className='ml-1 text-[10px] px-1 py-0'>P{r.priority}</Badge>
                      </div>
                    ))}
                  </div>
                )}

                <div className='flex gap-2 pt-2 border-t border-border'>
                  <Button variant='ghost' size='sm' className='gap-1.5' onClick={() => openEdit(s)}><Pencil className='h-3.5 w-3.5' />{t('common.edit')}</Button>
                  <Button variant='ghost' size='sm' className='gap-1.5' onClick={() => testMut.mutate(s.id)} disabled={testingId === s.id}>
                    {testingId === s.id ? <Loader2 className='h-3.5 w-3.5 animate-spin' /> : <Zap className='h-3.5 w-3.5' />}{t('common.test')}
                  </Button>
                  <div className='flex items-center gap-1.5 ml-1'>
                    <Switch checked={s.is_active} onCheckedChange={(v) => toggleActive.mutate({ id: s.id, is_active: v })} />
                    <span className='text-xs text-muted-foreground'>{s.is_active ? t('common.enabled') : t('common.disabled')}</span>
                  </div>
                  <Button variant='ghost' size='sm' className='gap-1.5 text-destructive hover:text-destructive' onClick={() => deleteMut.mutate(s.id)}>
                    <Trash2 className='h-3.5 w-3.5' />{t('common.delete')}
                  </Button>
                  {testResults[s.id] && (
                    <span className={'text-xs ml-auto self-center ' + (testResults[s.id].success ? 'text-green-400' : 'text-red-400')}>
                      {testResults[s.id].message}
                    </span>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className='max-w-2xl max-h-[85vh] overflow-y-auto'>
          <DialogHeader>
            <DialogTitle>{editing ? t('strategies.editStrategy') : t('strategies.createStrategy')}</DialogTitle>
          </DialogHeader>
          <div className='space-y-5 py-2'>
            <div className='grid grid-cols-2 gap-4'>
              <div><Label>{t('strategies.strategyName')} *</Label><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder='e.g. my-gpt4' /></div>
              <div><Label>{t('providers.description')}</Label><Textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} rows={2} placeholder={t('providers.description')} /></div>
            </div>

            <div className='grid grid-cols-2 gap-4'>
              <div>
                <Label>{t('strategies.loadBalancing')}</Label>
                <Select value={form.lb_strategy} onValueChange={(v) => setForm({ ...form, lb_strategy: v })}>
                  <SelectTrigger className='mt-1.5'><SelectValue /></SelectTrigger>
                  <SelectContent>{lbOptions.map((o) => <SelectItem key={o.value} value={o.value}>{o.label} - {o.desc}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div>
                <Label>{t('strategies.timeout')}</Label>
                <Input type='number' value={form.timeout} onChange={(e) => setForm({ ...form, timeout: Number(e.target.value) })} className='mt-1.5' />
              </div>
            </div>

            {form.lb_strategy === 'token_threshold' && (
              <div className='border rounded-lg p-4 bg-muted/30 space-y-3'>
                <div>
                  <Label className='text-sm font-semibold'>{t('strategies.tokenThreshold')}</Label>
                  <p className='text-xs text-muted-foreground mb-2'>{t('strategies.tokenThresholdDesc')}</p>
                </div>
                <div className='grid grid-cols-2 gap-4'>
                  <div>
                    <Label>{t('strategies.tokenThreshold')}</Label>
                    <Input type='number' min='1' value={form.rule_token_threshold || ''} onChange={(e) => setForm({ ...form, rule_token_threshold: Number(e.target.value) })} placeholder='100000' className='mt-1.5' />
                    <p className='text-[10px] text-muted-foreground mt-1'>{t('strategies.tokenThresholdHint')}</p>
                  </div>
                  <div>
                    <Label>{t('strategies.tokenPeriod')}</Label>
                    <Select value={form.rule_token_period} onValueChange={(v) => setForm({ ...form, rule_token_period: v })}>
                      <SelectTrigger className='mt-1.5'><SelectValue /></SelectTrigger>
                      <SelectContent>{tokenPeriodOptions.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}</SelectContent>
                    </Select>
                  </div>
                </div>
              </div>
            )}

            <div className='grid grid-cols-2 gap-4'>
              <div>
                <Label>{t('strategies.retryCount')}</Label>
                <Input type='number' value={form.retry_count} onChange={(e) => setForm({ ...form, retry_count: Number(e.target.value) })} className='mt-1.5' />
              </div>
              <div className='flex items-end gap-2 pb-0.5'>
                <Switch checked={form.is_active} onCheckedChange={(v) => setForm({ ...form, is_active: v })} />
                <Label>{t('strategies.enable')}</Label>
              </div>
            </div>

            <div className='border-t pt-5'>
              <Label className='text-sm font-semibold'>{t('strategies.keyStrategy')}</Label>
              <p className='text-xs text-muted-foreground mb-3'>{t('strategies.keyStrategyDesc')}</p>
              <div className='grid grid-cols-2 gap-4'>
                <div>
                  <Label>{t('strategies.keySelection')}</Label>
                  <Select value={form.key_strategy} onValueChange={(v) => setForm({ ...form, key_strategy: v })}>
                    <SelectTrigger className='mt-1.5'><SelectValue /></SelectTrigger>
                    <SelectContent>{keyStrategyOptions.map((o) => <SelectItem key={o.value} value={o.value}>{o.label} - {o.desc}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div>
                  <Label>{t('strategies.keySwitch')}</Label>
                  <p className='text-[10px] text-muted-foreground mt-0.5 mb-1'>{t('strategies.keySwitchDesc')}</p>
                  <Select value={form.key_switch_mode} onValueChange={(v) => setForm({ ...form, key_switch_mode: v, key_rpm_threshold: 0, key_count_threshold: 0 })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>{keySwitchOptions.map((o) => <SelectItem key={o.value} value={o.value}>{o.label} - {o.desc}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
              </div>
              {form.key_switch_mode === 'rpm_threshold' && (
                <div className='mt-3'>
                  <Label>{t('strategies.rpmValue')}</Label>
                  <Input type='number' min='1' value={form.key_rpm_threshold || ''} onChange={(e) => setForm({ ...form, key_rpm_threshold: Number(e.target.value) })} placeholder='60' />
                  <p className='text-[10px] text-muted-foreground mt-1'>{t('strategies.rpmHint')}</p>
                </div>
              )}
              {form.key_switch_mode === 'count_threshold' && (
                <div className='mt-3'>
                  <Label>{t('strategies.countValue')}</Label>
                  <Input type='number' min='1' value={form.key_count_threshold || ''} onChange={(e) => setForm({ ...form, key_count_threshold: Number(e.target.value) })} placeholder='1000' />
                  <p className='text-[10px] text-muted-foreground mt-1'>{t('strategies.countHint')}</p>
                </div>
              )}
            </div>

            <div className='border-t pt-5'>
              <Label className='text-sm font-semibold'>{t('strategies.routingRules')}</Label>
              <div className='mt-3 space-y-2'>
                {form.rules.map((r, idx) => (
                  <div key={idx} className='flex items-center gap-2 text-sm bg-muted/50 rounded-lg p-3'>
                    <span className='flex-1 font-medium'>{getProviderName(r.provider_id)}</span>
                    <ArrowRight className='h-3 w-3 text-muted-foreground' />
                    <span className='text-muted-foreground'>{r.model_name || ('Model #' + r.model_id)}</span>
                    <Badge variant='outline' className='text-xs'>P{r.priority}</Badge>
                    <div className='flex items-center gap-1'>
                      <span className='text-[10px] text-muted-foreground'>W</span>
                      <Input type='number' className='h-6 w-14 text-xs px-1' value={r.weight} onChange={(e) => {
                        const newRules = [...form.rules];
                        newRules[idx] = { ...newRules[idx], weight: Number(e.target.value) || 1 };
                        setForm({ ...form, rules: newRules });
                      }} />
                    </div>
                    <Button variant='ghost' size='icon' className='h-6 w-6 ml-1' onClick={() => removeRule(idx)}><X className='h-3 w-3' /></Button>
                  </div>
                ))}
                {form.rules.length === 0 && <p className='text-xs text-muted-foreground py-2'>{t('strategies.noRules')}</p>}
              </div>
              <div className='mt-3 grid grid-cols-4 gap-2'>
                <Select value={String(newRule.provider_id)} onValueChange={(v) => setNewRule({ ...newRule, provider_id: Number(v), model_id: 0 })}>
                  <SelectTrigger><SelectValue placeholder={t('strategies.selectPlatform')} /></SelectTrigger>
                  <SelectContent>{providers.map((p: any) => <SelectItem key={p.id} value={String(p.id)}>{p.name}</SelectItem>)}</SelectContent>
                </Select>
                <Select value={String(newRule.model_id)} onValueChange={(v) => setNewRule({ ...newRule, model_id: Number(v) })}>
                  <SelectTrigger><SelectValue placeholder={t('strategies.selectModel')} /></SelectTrigger>
                  <SelectContent>{(models as any[]).map((m: any) => <SelectItem key={m.id} value={String(m.id)}>{m.model_id}</SelectItem>)}</SelectContent>
                </Select>
                <Input type='number' placeholder={t('strategies.priorityPlaceholder')} value={newRule.priority} onChange={(e) => setNewRule({ ...newRule, priority: Number(e.target.value) })} />
                <Button variant='outline' onClick={addRule} disabled={!newRule.provider_id || !newRule.model_id}><Plus className='h-4 w-4 mr-1' />{t('strategies.addRule')}</Button>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant='outline' onClick={() => setOpen(false)}>{t('common.cancel')}</Button>
            <Button onClick={save} disabled={!form.name}>{editing ? t('common.update') : t('common.create')}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

    {/* Create Strategy by Model Dialog */}
    <Dialog open={byModelOpen} onOpenChange={setByModelOpen}>
      <DialogContent className='max-w-4xl max-h-[85vh] flex flex-col'>
        <DialogHeader><DialogTitle>{t('strategies.createByModel')}</DialogTitle></DialogHeader>
        <div className='flex-1 flex gap-3 overflow-hidden min-h-0'>
          <div className='w-48 flex-shrink-0 border rounded-lg overflow-y-auto'>
            <div className='p-2 text-xs font-semibold text-muted-foreground border-b'>{t('providers.title')}</div>
            {byModelLoading && byModelSelProvider === 0 && <div className='p-4 text-center text-muted-foreground'><Loader2 className='h-4 w-4 animate-spin mx-auto' /></div>}
            {byModelProviders.map((p: any) => (
              <button key={p.id} type='button' onClick={() => loadByModelModels(p.id)}
                className={'w-full text-left px-3 py-2 text-sm transition-colors ' + (byModelSelProvider === p.id ? 'bg-primary/10 text-primary font-medium' : 'hover:bg-muted')}>
                {p.name}
              </button>
            ))}
          </div>
          <div className='flex-1 flex flex-col border rounded-lg overflow-hidden min-w-0'>
            <div className='p-2 border-b flex items-center gap-2'>
              <div className='relative flex-1'>
                <Search className='absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground' />
                <Input value={byModelSearch} onChange={e => setByModelSearch(e.target.value)} placeholder={t('common.search') + '...'} className='pl-7 h-7 text-xs' />
              </div>
              <Button variant='outline' size='sm' className='h-7 text-xs' onClick={toggleByModelAll}>
                {byModelChecked.size === byModelModels.length && byModelModels.length > 0 ? t('strategies.deselectAll') : t('strategies.selectAll')}
              </Button>
              <span className='text-xs text-muted-foreground whitespace-nowrap'>{byModelChecked.size}/{byModelModels.length}</span>
            </div>
            <div className='flex-1 overflow-y-auto'>
              {byModelSelProvider === 0 ? (
                <div className='flex items-center justify-center h-full text-muted-foreground text-sm'>{t('strategies.selectPlatformFirst')}</div>
              ) : byModelLoading ? (
                <div className='flex items-center justify-center h-full'><Loader2 className='h-5 w-5 animate-spin text-muted-foreground' /></div>
              ) : byModelFiltered.length === 0 ? (
                <div className='flex items-center justify-center h-full text-muted-foreground text-sm'>{t('providers.noModels')}</div>
              ) : (
                byModelFiltered.map((m: any) => (
                  <label key={m.id} onClick={() => toggleByModelCheck(m.id)} className={'flex items-center gap-2 px-3 py-2 text-sm cursor-pointer transition-colors hover:bg-muted/50 ' + (byModelChecked.has(m.id) ? 'bg-primary/5' : '')}>
                    <div className={'w-4 h-4 rounded border flex items-center justify-center flex-shrink-0 transition-colors ' + (byModelChecked.has(m.id) ? 'bg-primary border-primary text-primary-foreground' : 'border-muted-foreground/30')}>
                      {byModelChecked.has(m.id) && <Check className='h-3 w-3' />}
                    </div>
                    <span className='font-mono text-xs truncate'>{m.model_id}</span>
                    {m.display_name && m.display_name !== m.model_id && <span className='text-xs text-muted-foreground truncate'>{'·'} {m.display_name}</span>}
                  </label>
                ))
              )}
            </div>
          </div>
          <div className='w-56 flex-shrink-0 border rounded-lg flex flex-col overflow-hidden'>
            <div className='p-2 border-b text-xs font-semibold text-muted-foreground'>{t('strategies.selectedModels')} ({byModelChecked.size})</div>
            <div className='flex-1 overflow-y-auto'>
              {byModelChecked.size === 0 ? (
                <div className='flex items-center justify-center h-full text-muted-foreground text-xs p-2 text-center'>{t('strategies.hintSelectModels')}</div>
              ) : (
                Array.from(byModelChecked).map(modelId => {
                  const m = byModelModels.find((x: any) => x.id === modelId);
                  if (!m) return null;
                  return (
                    <div key={m.id} className='flex items-center gap-1.5 px-2.5 py-1.5 text-xs border-b last:border-b-0'>
                      <span className='font-mono truncate flex-1' title={m.model_id}>{m.model_id}</span>
                      <button type='button' onClick={() => toggleByModelCheck(m.id)} className='text-muted-foreground hover:text-destructive'><X className='h-3 w-3' /></button>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant='outline' onClick={() => setByModelOpen(false)}>{t('common.cancel')}</Button>
          <Button disabled={byModelChecked.size === 0} onClick={() => {
            const rules: Rule[] = [];
            let idx = 0;
            byModelModels.filter((m: any) => byModelChecked.has(m.id)).forEach((m: any) => {
              rules.push({ provider_id: m.provider_id, model_id: m.id, model_name: m.model_id, priority: idx, weight: 1, is_active: true });
              idx++;
            });
            setForm({ name: '', description: '', lb_strategy: 'round_robin', key_strategy: 'round_robin', key_switch_mode: 'none', key_rpm_threshold: 0, key_count_threshold: 0, rule_token_threshold: 0, rule_token_period: 'per_day', is_active: true, timeout: 120, retry_count: 2, rules });
            setEditing(null);
            setByModelOpen(false);
            setOpen(true);
          }} className='gap-2'><ListChecks className='h-4 w-4' />{t('strategies.createStrategy')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    </div>
  );
}

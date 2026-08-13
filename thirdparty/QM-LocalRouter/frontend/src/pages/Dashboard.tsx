import React, { useState } from 'react';
import { toast } from "../stores/toast";
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getDashboardStats, getStrategies, getProviders, clearTodayStats } from '../services/api';
import { useI18n } from '../i18n';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import {
  Activity, CheckCircle, XCircle, Clock, GitBranch, Server, KeyRound,
  ArrowUpRight, Zap, TrendingUp, Coins, Trash2,
} from 'lucide-react';

export default function Dashboard() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [clearing, setClearing] = useState(false);
  const { data, isLoading } = useQuery({
    queryKey: ['dashboard'],
    queryFn: () => getDashboardStats().then((r) => r.data),
    refetchInterval: 5000,
  });

  const clearMutation = useMutation({
    mutationFn: () => clearTodayStats(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      toast({ title: t('dashboard.clearToday') + ' OK', variant: 'success' });
    },
    onError: () => {
      toast({ title: t('common.error'), variant: 'destructive' });
    },
  });


  const { data: strategies = [] } = useQuery({
    queryKey: ['strategies'],
    queryFn: () => getStrategies().then((r) => r.data),
  });

  const { data: providers = [] } = useQuery({
    queryKey: ['providers'],
    queryFn: () => getProviders().then((r) => r.data),
  });

  const stats = data || {
    total_requests: 0, success_count: 0, error_count: 0,
    success_rate: 0, avg_latency_ms: 0,
    total_prompt_tokens: 0, total_completion_tokens: 0, total_tokens: 0,
    active_strategies: 0, active_providers: 0, active_keys: 0,
  };

  const statCards = [
    { title: t('dashboard.todayRequests'), value: stats.total_requests, icon: Activity, color: 'from-cyan-400 to-cyan-600', bgColor: 'bg-cyan-500/10' },
    { title: t('dashboard.successRequests'), value: stats.success_count, icon: CheckCircle, color: 'from-green-500 to-emerald-600', bgColor: 'bg-green-500/10' },
    { title: t('dashboard.failedRequests'), value: stats.error_count, icon: XCircle, color: 'from-red-500 to-rose-600', bgColor: 'bg-red-500/10' },
    { title: t('dashboard.successRate'), value: stats.success_rate + '%', icon: TrendingUp, color: 'from-emerald-500 to-teal-600', bgColor: 'bg-emerald-500/10' },
    { title: t('dashboard.avgLatency'), value: Math.round(stats.avg_latency_ms) + t('dashboard.ms'), icon: Clock, color: 'from-yellow-500 to-amber-600', bgColor: 'bg-yellow-500/10' },
    { title: t('dashboard.promptTokens'), value: stats.total_prompt_tokens.toLocaleString(), icon: Coins, color: 'from-teal-400 to-cyan-500', bgColor: 'bg-teal-500/10' },
    { title: t('dashboard.completionTokens'), value: stats.total_completion_tokens.toLocaleString(), icon: Coins, color: 'from-sky-400 to-blue-500', bgColor: 'bg-sky-500/10' },
    { title: t('dashboard.totalTokens'), value: stats.total_tokens.toLocaleString(), icon: Coins, color: 'from-indigo-400 to-purple-500', bgColor: 'bg-indigo-500/10' },
    { title: t('dashboard.activeStrategies'), value: stats.active_strategies, icon: GitBranch, color: 'from-purple-500 to-violet-600', bgColor: 'bg-purple-500/10' },
    { title: t('dashboard.activeProviders'), value: stats.active_providers, icon: Server, color: 'from-cyan-500 to-sky-600', bgColor: 'bg-cyan-500/10' },
    { title: t('dashboard.activeKeys'), value: stats.active_keys, icon: KeyRound, color: 'from-orange-500 to-amber-600', bgColor: 'bg-orange-500/10' },
  ];

  const quickSteps = [
    { step: '1', text: t('dashboard.step1Title'), desc: t('dashboard.step1Desc') },
    { step: '2', text: t('dashboard.step2Title'), desc: t('dashboard.step2Desc') },
    { step: '3', text: t('dashboard.step3Title'), desc: t('dashboard.step3Desc') },
    { step: '4', text: t('dashboard.step4Title'), desc: t('dashboard.step4Desc') },
  ];

  return (
    <div className='space-y-8'>
      {/* Header */}
      <div className='flex items-center justify-between'>
        <div>
          <h1 className='text-2xl font-extrabold tracking-tight animate-in'>{t('dashboard.title')}</h1>
          <p className='text-sm text-muted-foreground mt-1'>{t('dashboard.subtitle')}</p>
        </div>
        <div className='flex items-center gap-2'>
          <button
            className='inline-flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-1.5 text-xs font-medium text-red-500 hover:bg-red-500/20 transition-all duration-200 disabled:opacity-50'
            onClick={() => { if (window.confirm(t('dashboard.clearTodayDesc'))) clearMutation.mutate(); }}
            disabled={clearing}
          >
            <Trash2 className='h-3.5 w-3.5' />
            {t('dashboard.clearToday')}
          </button>
          <div className='h-2 w-2 rounded-full bg-green-500 pulse-dot' />
          <span className='text-sm text-muted-foreground'>{t('sidebar.serviceRunning')}</span>
        </div>
      </div>

      {/* Stat Cards */}
      <div className='grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4'>
        {statCards.map((c, i) => (
          <Card key={c.title} className='card-hover overflow-hidden relative animate-in' style={{ animationDelay: (i * 0.06) + 's' }}>
            <CardContent className='p-5'>
              <div className='flex items-start justify-between'>
                <div>
                  <p className='text-xs font-medium text-muted-foreground uppercase tracking-wider'>{c.title}</p>
                  <p className='text-2xl font-bold mt-2'>{isLoading ? '—' : c.value}</p>
                </div>
                <div className={'flex h-10 w-10 items-center justify-center rounded-xl ' + c.bgColor + ' shadow-sm'}>
                  <c.icon className={'h-5 w-5 bg-gradient-to-br ' + c.color} style={{ WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }} />
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Quick Actions + Active Strategies */}
      <div className='grid grid-cols-1 lg:grid-cols-2 gap-6'>
        {/* Quick Start Guide */}
        <Card className='card-hover animate-in stagger-2'>
          <CardHeader className='pb-3'>
            <div className='flex items-center gap-2'>
              <Zap className='h-4 w-4 text-cyan-400' />
              <CardTitle className='text-base'>{t('dashboard.quickStart')}</CardTitle>
            </div>
          </CardHeader>
          <CardContent className='space-y-4'>
            <div className='space-y-3'>
              {quickSteps.map((item) => (
                <div key={item.step} className='flex items-start gap-3'>
                  <div className='flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-cyan-400/10 text-xs font-bold text-cyan-400 border border-cyan-400/20'>
                    {item.step}
                  </div>
                  <div>
                    <p className='text-sm font-medium'>{item.text}</p>
                    <p className='text-xs text-muted-foreground'>{item.desc}</p>
                  </div>
                </div>
              ))}
            </div>
            <div className='pt-2 border-t border-border'>
              <p className='text-xs text-muted-foreground mb-2'>{t('dashboard.requestEndpoint')}</p>
              <code className='text-xs bg-muted px-3 py-1.5 rounded-md font-mono text-foreground block'>
                POST http://127.0.0.1:12002/v1/chat/completions
              </code>
            </div>
          </CardContent>
        </Card>

        {/* Active Strategies */}
        <Card className='card-hover animate-in stagger-3'>
          <CardHeader className='pb-3'>
            <div className='flex items-center justify-between'>
              <div className='flex items-center gap-2'>
                <GitBranch className='h-4 w-4 text-purple-400' />
                <CardTitle className='text-base'>{t('dashboard.activeStrategiesTitle')}</CardTitle>
              </div>
              <Badge variant='secondary'>{strategies.length}</Badge>
            </div>
          </CardHeader>
          <CardContent>
            {strategies.length === 0 ? (
              <p className='text-sm text-muted-foreground text-center py-6'>{t('dashboard.noStrategies')}</p>
            ) : (
              <div className='space-y-2'>
                {strategies.slice(0, 5).map((s: any) => (
                  <div key={s.id} className='flex items-center justify-between p-3 rounded-xl bg-muted/30 hover:bg-muted/50 transition-all duration-200 hover:shadow-sm'>
                    <div className='flex items-center gap-3'>
                      <div className='h-2 w-2 rounded-full bg-green-500' />
                      <div>
                        <p className='text-sm font-medium'>{s.name}</p>
                        <p className='text-xs text-muted-foreground'>{s.rules?.length || 0} {t('dashboard.rulesCount')} · {s.lb_strategy}</p>
                      </div>
                    </div>
                    <ArrowUpRight className='h-4 w-4 text-muted-foreground' />
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

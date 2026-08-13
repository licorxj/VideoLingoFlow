import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getLogs, getStrategies, getProviders } from '../services/api';
import { useI18n } from '../i18n';
import { Card, CardContent } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '../components/ui/dialog';
import { Select, SelectTrigger, SelectContent, SelectItem, SelectValue } from '../components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { ChevronLeft, ChevronRight, ScrollText, Copy, Check } from 'lucide-react';

export default function Logs() {
  const { t } = useI18n();
  const [page, setPage] = useState(1);
  const [strategyFilter, setStrategyFilter] = useState<string>('');
  const [providerFilter, setProviderFilter] = useState<string>('');
  const [selectedError, setSelectedError] = useState<any>(null);
  const [copied, setCopied] = useState(false);

  const { data: strategies = [] } = useQuery({ queryKey: ['strategies'], queryFn: () => getStrategies().then((r) => r.data) });
  const { data: providers = [] } = useQuery({ queryKey: ['providers'], queryFn: () => getProviders().then((r) => r.data) });

  const params: any = { page, page_size: 20 };
  if (strategyFilter) params.strategy_id = strategyFilter;
  if (providerFilter) params.provider_id = providerFilter;

  const { data, isLoading } = useQuery({ queryKey: ['logs', params], queryFn: () => getLogs(params).then((r) => r.data) });
  const logs = data?.items || [];
  const total = data?.total || 0;
  const totalPages = Math.ceil(total / 20);

  const getStrategyName = (id: number) => strategies.find((s: any) => s.id === id)?.name || '#' + id;
  const getProviderName = (id: number) => providers.find((p: any) => p.id === id)?.name || '#' + id;
  const formatTime = (dt: string) => dt ? new Date(dt + 'Z').toLocaleString() : '-';

  const copyError = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className='space-y-6'>
      <div>
        <h1 className='text-2xl font-bold tracking-tight'>{t('logs.title')}</h1>
        <p className='text-sm text-muted-foreground mt-1'>{t('logs.subtitle')}</p>
      </div>

      <div className='flex gap-3'>
        <Select value={strategyFilter} onValueChange={(v) => { setStrategyFilter(v === 'all' ? '' : v); setPage(1); }}>
          <SelectTrigger className='w-48'><SelectValue placeholder={t('logs.allStrategies')} /></SelectTrigger>
          <SelectContent>
            <SelectItem value='all'>{t('logs.allStrategies')}</SelectItem>
            {strategies.map((s: any) => <SelectItem key={s.id} value={String(s.id)}>{s.name}</SelectItem>)}
          </SelectContent>
        </Select>
        <Select value={providerFilter} onValueChange={(v) => { setProviderFilter(v === 'all' ? '' : v); setPage(1); }}>
          <SelectTrigger className='w-48'><SelectValue placeholder={t('logs.allProviders')} /></SelectTrigger>
          <SelectContent>
            <SelectItem value='all'>{t('logs.allProviders')}</SelectItem>
            {providers.map((p: any) => <SelectItem key={p.id} value={String(p.id)}>{p.name}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      {logs.length === 0 && !isLoading ? (
        <Card className='border-dashed'>
          <CardContent className='flex flex-col items-center justify-center py-12'>
            <ScrollText className='h-10 w-10 text-muted-foreground/30 mb-3' />
            <p className='text-muted-foreground'>{t('logs.noLogs')}</p>
            <p className='text-xs text-muted-foreground/70 mt-1'>{t('logs.noLogsHint')}</p>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className='p-0'>
            <Table>
              <TableHeader>
                <TableRow className='hover:bg-transparent'>
                  <TableHead className='w-12'>ID</TableHead>
                  <TableHead>{t('logs.time')}</TableHead>
                  <TableHead>{t('logs.strategy')}</TableHead>
                  <TableHead>{t('logs.platform')}</TableHead>
                  <TableHead>{t('logs.model')}</TableHead>
                  <TableHead>{t('logs.statusCode')}</TableHead>
                  <TableHead>{t('logs.latency')}</TableHead>
                  <TableHead>{t('logs.stream')}</TableHead>
                  <TableHead>{t('logs.error')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {logs.map((l: any) => (
                  <TableRow key={l.id}>
                    <TableCell className='text-muted-foreground text-xs'>{l.id}</TableCell>
                    <TableCell className='text-xs'>{formatTime(l.created_at)}</TableCell>
                    <TableCell className='text-sm'>{l.strategy_id ? getStrategyName(l.strategy_id) : '-'}</TableCell>
                    <TableCell className='text-sm'>{l.provider_id ? getProviderName(l.provider_id) : '-'}</TableCell>
                    <TableCell className='font-mono text-xs text-muted-foreground'>{l.model_used || '-'}</TableCell>
                    <TableCell>
                      {l.status_code && l.status_code >= 200 && l.status_code < 300 ? (
                        <Badge variant='success'>{l.status_code}</Badge>
                      ) : l.status_code ? (
                        <Badge variant='destructive'>{l.status_code}</Badge>
                      ) : '-'}
                    </TableCell>
                    <TableCell className='text-sm'>{l.latency_ms ? l.latency_ms + 'ms' : '-'}</TableCell>
                    <TableCell>{l.is_stream ? <Badge variant='outline'>SSE</Badge> : '-'}</TableCell>
                    <TableCell>
                      {l.error_message ? (
                        <button
                          className='text-xs text-destructive max-w-[200px] truncate block hover:underline cursor-pointer text-left'
                          onClick={() => { setSelectedError(l); setCopied(false); }}
                        >
                          {l.error_message}
                        </button>
                      ) : '-'}
                    </TableCell>
                  </TableRow>
                ))}
                {isLoading && (
                  <TableRow><TableCell colSpan={9} className='text-center text-muted-foreground py-8'>{t('logs.loading')}</TableCell></TableRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {totalPages > 1 && (
        <div className='flex items-center justify-between'>
          <span className='text-sm text-muted-foreground'>{t('logs.totalRecords')}: {total}</span>
          <div className='flex items-center gap-2'>
            <Button variant='outline' size='sm' onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}><ChevronLeft className='h-4 w-4' /></Button>
            <span className='text-sm px-2'>{page} / {totalPages}</span>
            <Button variant='outline' size='sm' onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page === totalPages}><ChevronRight className='h-4 w-4' /></Button>
          </div>
        </div>
      )}

      <Dialog open={selectedError !== null} onOpenChange={(v) => { if (!v) setSelectedError(null); }}>
        <DialogContent className='max-w-2xl'>
          <DialogHeader>
            <DialogTitle>{t('logs.error')} - #{selectedError?.id}</DialogTitle>
          </DialogHeader>
          <div className='space-y-3'>
            <div className='flex gap-4 text-sm text-muted-foreground'>
              <span>{t('logs.time')}: {formatTime(selectedError?.created_at)}</span>
              <span>{t('logs.statusCode')}: <Badge variant={selectedError?.status_code >= 200 && selectedError?.status_code < 300 ? 'success' : 'destructive'}>{selectedError?.status_code}</Badge></span>
              <span>{t('logs.latency')}: {selectedError?.latency_ms}ms</span>
              <span>{t('logs.platform')}: {selectedError?.provider_id ? getProviderName(selectedError.provider_id) : '-'}</span>
            </div>
            <div className='flex gap-4 text-sm text-muted-foreground'>
              <span>{t('logs.model')}: {selectedError?.model_used || '-'}</span>
              <span>{t('logs.stream')}: {selectedError?.is_stream ? 'SSE' : '-'}</span>
              {selectedError?.strategy_id && <span>{t('logs.strategy')}: {getStrategyName(selectedError.strategy_id)}</span>}
            </div>
            <div className='relative'>
              <pre className='text-sm bg-muted p-4 rounded-lg overflow-x-auto max-h-[400px] overflow-y-auto whitespace-pre-wrap break-all font-mono'>
                {selectedError?.error_message || '-'}
              </pre>
            </div>
          </div>
          <DialogFooter>
            <Button variant='outline' size='sm' onClick={() => copyError(selectedError?.error_message || '')} className='gap-1.5'>
              {copied ? <Check className='h-3.5 w-3.5' /> : <Copy className='h-3.5 w-3.5' />}
              {copied ? t('common.copied') : t('common.copy')}
            </Button>
            <Button variant='outline' size='sm' onClick={() => setSelectedError(null)}>{t('common.close')}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

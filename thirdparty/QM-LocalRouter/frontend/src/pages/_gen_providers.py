import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getProviders, createProvider, updateProvider, deleteProvider,
  searchIcons, saveIcon, getHotProviders,
  getKeys, createKey, deleteKey, testKey, testAllKeys, deleteInvalidKeys,
  getModels, createModel, updateModel, deleteModel, syncModels,
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
  Plus, Pencil, Trash2, Server, Wand2, KeyRound, Zap, Loader2, RefreshCw,
  Cpu, CheckCircle2, XCircle, CircleDot, ShieldCheck, Trash, Layers, Image,
  Video, Mic, Box, ChevronRight, ImageIcon, Search, X, Flame,
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

function extractHost(url: string) {
  try { return new URL(url.startsWith('http') ? url : 'https://' + url).hostname; } catch { return ''; }
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
  } catch {}
  return { base: trimmed, stripped: null };
}

function autoCompleteUrl(input: string) {
  if (!input) return input;
  const { base } = normalizeBaseUrl(input);
  const trimmed = base.replace(/\/$/, '');
  if (!trimmed) return trimmed;
  try { new URL(trimmed.startsWith('http') ? trimmed : 'https://' + trimmed); } catch { return trimmed; }
  const host = extractHost(trimmed);
  const kp = knownPaths[host];
  if (kp) return trimmed.replace(/\/$/, '') + kp;
  return trimmed;
}

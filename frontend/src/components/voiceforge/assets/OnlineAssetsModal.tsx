import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Save, Download, Search, Music2, X, ChevronDown, Tag, XCircle, Copy, Check, Library } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { voiceForgeApi, type OnlineAssetItem, type OnlineSoundItem } from "@/api/voiceforge";
import { ASSET_TYPE_LABELS } from "./meta";

type Category = { id: string; label: string; asset_type: string };

const SOURCE_TABS = [{ id: "elevenlabs", label: "ElevenLabs" }, { id: "chinaz", label: "chinaZ" }];
const PAGE_SIZE = 16;

type SaveDraft = {
  name: string;
  asset_type: string;
  category: string;
  tags: string;
  description: string;
  download: boolean;
};

function fuzzyScore(text: string, query: string): number {
  if (!query) return 1;
  const t = text.toLowerCase();
  const q = query.toLowerCase().trim();
  if (!q) return 1;
  if (t === q) return 1000;
  const idx = t.indexOf(q);
  if (idx >= 0) return 800 - idx;
  let ti = 0;
  let qi = 0;
  let score = 0;
  let lastHit = -2;
  while (ti < t.length && qi < q.length) {
    if (t[ti] === q[qi]) {
      const gap = ti - lastHit - 1;
      score += 10 + Math.max(0, 5 - gap);
      lastHit = ti;
      qi += 1;
    }
    ti += 1;
  }
  if (qi < q.length) return 0;
  return score;
}

function flattenSounds(items: OnlineAssetItem[]): OnlineSoundItem[] {
  const out: OnlineSoundItem[] = [];
  for (const item of items) {
    for (const sound of item.sounds || []) {
      out.push(sound);
    }
  }
  return out;
}

function SoundCard({
  sound,
  selected,
  onToggle,
  categories,
  onSaved,
  onPick,
}: {
  sound: OnlineSoundItem;
  selected: boolean;
  onToggle: () => void;
  categories: Category[];
  onSaved: (download: boolean) => void;
  onPick?: (v: { url: string; id: string }) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [saving, setSaving] = useState(false);
  const preset = useMemo<SaveDraft>(
    () => ({
      name: sound.name || "未命名素材",
      asset_type: "sfx",
      category: "",
      tags: (sound.labels || []).filter(Boolean).join(", "),
      description: sound.short_description || "",
      download: false,
    }),
    [sound],
  );
  const [draft, setDraft] = useState<SaveDraft>(preset);
  const [downloading, setDownloading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [copiedId, setCopiedId] = useState(false);

  useEffect(() => { setDraft(preset); }, [preset]);

  const proxyUrl = voiceForgeApi.onlineProxyUrl(sound.audio_url);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(sound.audio_url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // 剪贴板 API 被拒时降级到 textarea + execCommand
      const ta = document.createElement("textarea");
      ta.value = sound.audio_url;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      } finally {
        document.body.removeChild(ta);
      }
    }
  };

  const handleCopyId = async () => {
    try {
      await navigator.clipboard.writeText(sound.id);
      setCopiedId(true);
      window.setTimeout(() => setCopiedId(false), 1500);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = sound.id;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        setCopiedId(true);
        window.setTimeout(() => setCopiedId(false), 1500);
      } finally {
        document.body.removeChild(ta);
      }
    }
  };

  const submit = async (download: boolean) => {
    setSaving(true);
    try {
      await voiceForgeApi.onlineImport({
        name: draft.name.trim() || sound.name || "未命名素材",
        asset_type: draft.asset_type,
        source_url: sound.audio_url,
        source_site: "elevenlabs",
        source_id: sound.id,
        category: draft.category,
        tags: draft.tags.split(",").map((t) => t.trim()).filter(Boolean),
        description: draft.description,
        download,
      });
      onSaved(download);
      setExpanded(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="relative flex flex-col rounded-lg border bg-card p-2.5 text-card-foreground shadow-sm">
      <label
        className="absolute left-1.5 top-1.5 z-10 flex h-5 w-5 cursor-pointer items-center justify-center"
        onClick={(e) => e.stopPropagation()}
      >
        <input type="checkbox" className="size-4 accent-primary" checked={selected} onChange={onToggle} />
      </label>
      <div className="flex items-start justify-between gap-2 pl-6">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium" title={sound.name}>{sound.name}</p>
          <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground" title={sound.short_description}>
            {sound.short_description || "—"}
          </p>
        </div>
        <Music2 className="size-4 shrink-0 text-muted-foreground" />
      </div>

      {sound.labels?.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {sound.labels.slice(0, 4).map((label) => (
            <Badge key={label} variant="secondary" className="text-[10px]">{label}</Badge>
          ))}
        </div>
      )}

      <audio className="mt-2 h-8 w-full" controls preload="metadata" src={proxyUrl} />

      {!expanded ? (
        onPick ? (
          <div className="mt-2 grid grid-cols-3 gap-1.5">
            <Button size="sm" variant="outline" onClick={handleCopy} title="复制素材链接">
              {copied ? (
                <>
                  <Check className="mr-1 size-3.5" />
                  已复制
                </>
              ) : (
                <>
                  <Copy className="mr-1 size-3.5" />
                  复制链接
                </>
              )}
            </Button>
            <Button size="sm" variant="outline" onClick={handleCopyId} title="复制素材ID">
              {copiedId ? (
                <>
                  <Check className="mr-1 size-3.5" />
                  已复制
                </>
              ) : (
                <>
                  <Copy className="mr-1 size-3.5" />
                  复制ID
                </>
              )}
            </Button>
            <Button size="sm" variant="default" onClick={() => onPick({ url: sound.audio_url, id: sound.id })} title="插入到节点">
              <Library className="mr-1 size-3.5" />
              插入
            </Button>
          </div>
        ) : (
          <div className="mt-2 space-y-1.5">
            <div className="grid grid-cols-2 gap-1.5">
              <Button size="sm" variant="outline" onClick={() => setExpanded(true)}>
                <Save className="mr-1 size-3.5" />保存URL
              </Button>
              <Button size="sm" variant="outline" onClick={() => setExpanded(true)}>
                <Download className="mr-1 size-3.5" />下载入库
              </Button>
            </div>
            <Button
              size="sm"
              variant="outline"
              className="w-full"
              onClick={handleCopy}
              title="复制素材原始链接"
            >
              {copied ? (
                <>
                  <Check className="mr-1 size-3.5" />
                  已复制
                </>
              ) : (
                <>
                  <Copy className="mr-1 size-3.5" />
                  复制链接
                </>
              )}
            </Button>
          </div>
        )
      ) : (
        !onPick && (
        <div className="mt-2 space-y-2 rounded-md border bg-muted/40 p-2">
          <div className="space-y-1">
            <Label className="text-xs">名称</Label>
            <Input
              className="h-7 text-xs"
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <Label className="text-xs">类型</Label>
              <Select value={draft.asset_type} onValueChange={(v) => setDraft({ ...draft, asset_type: v })}>
                <SelectTrigger className="h-7 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {Object.entries(ASSET_TYPE_LABELS).map(([value, label]) => (
                    <SelectItem key={value} value={value}>{label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">分类</Label>
              <Select value={draft.category} onValueChange={(v) => setDraft({ ...draft, category: v })}>
                <SelectTrigger className="h-7 text-xs">
                  <SelectValue placeholder="未分类" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none">未分类</SelectItem>
                  {categories.map((c) => (
                    <SelectItem key={c.id} value={c.id}>{c.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">标签（逗号分隔）</Label>
            <Input
              className="h-7 text-xs"
              value={draft.tags}
              onChange={(e) => setDraft({ ...draft, tags: e.target.value })}
            />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">描述</Label>
            <Textarea
              className="text-xs"
              rows={2}
              value={draft.description}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })}
            />
          </div>
          <div className="flex items-center gap-1.5">
            <Button
              size="sm"
              className="flex-1"
              disabled={saving}
              onClick={() => submit(false)}
            >
              {saving && !downloading ? <Loader2 className="mr-1 size-3.5 animate-spin" /> : <Save className="mr-1 size-3.5" />}
              保存URL
            </Button>
            <Button
              size="sm"
              className="flex-1"
              disabled={saving}
              onClick={() => { setDownloading(true); submit(true).finally(() => setDownloading(false)); }}
            >
              {downloading ? <Loader2 className="mr-1 size-3.5 animate-spin" /> : <Download className="mr-1 size-3.5" />}
              下载并入库
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setExpanded(false)}>
              <X className="size-3.5" />
            </Button>
          </div>
        </div>
        )
      )}
    </div>
  );
}

function ChinazTagPicker({
  open, onOpenChange, tags, value, onPick,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tags: { name: string; url: string }[];
  value: string;
  onPick: (url: string) => void;
}) {
  const [filter, setFilter] = useState("");
  useEffect(() => { if (!open) setFilter(""); }, [open]);

  const scored = useMemo(() => {
    const q = filter.trim();
    if (!q) return tags.map((t) => ({ tag: t, score: 1 }));
    return tags
      .map((t) => ({ tag: t, score: fuzzyScore(t.name, q) }))
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score);
  }, [tags, filter]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[min(960px,96vw)] max-w-none gap-0 p-0">
        <DialogHeader className="border-b px-4 py-3">
          <DialogTitle className="flex items-center gap-2">
            <Tag className="size-4" />选择分类标签
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3 p-4">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              autoFocus
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="输入关键字模糊匹配标签…（支持中英文）"
              className="pl-8 pr-8"
            />
            {filter && (
              <button
                type="button"
                onClick={() => setFilter("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                title="清空"
              >
                <XCircle className="size-4" />
              </button>
            )}
          </div>
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>共 {tags.length} 个标签{filter && ` · 匹配 ${scored.length} 个`}</span>
            <Button
              size="sm"
              variant="ghost"
              disabled={!value}
              onClick={() => { onPick(""); onOpenChange(false); }}
            >
              清除选择
            </Button>
          </div>
          <div className="max-h-[420px] overflow-y-auto rounded-md border bg-muted/20 p-2">
            {tags.length === 0 ? (
              <div className="py-12 text-center text-sm text-muted-foreground">分类加载中…</div>
            ) : scored.length === 0 ? (
              <div className="py-12 text-center text-sm text-muted-foreground">没有匹配的标签</div>
            ) : (
              <div className="grid grid-cols-5 gap-1.5 sm:grid-cols-6 md:grid-cols-8 lg:grid-cols-10">
                {scored.map(({ tag }) => {
                  const active = tag.url === value;
                  return (
                    <button
                      key={tag.url}
                      type="button"
                      onClick={() => { onPick(tag.url); onOpenChange(false); }}
                      className={[
                        "truncate rounded-md border px-2 py-1.5 text-center text-xs transition",
                        "hover:border-primary/60 hover:bg-primary/5",
                        active
                          ? "border-primary bg-primary/15 font-medium text-primary"
                          : "border-border bg-card text-card-foreground",
                      ].join(" ")}
                      title={tag.name}
                    >
                      {tag.name}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export default function OnlineAssetsModal({
  open, onOpenChange, onImported, onPick,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onImported?: () => void;
  onPick?: (v: { url: string; id: string }) => void;
}) {
  const [activeTab, setActiveTab] = useState(SOURCE_TABS[0].id);
  const [keyword, setKeyword] = useState("");
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<OnlineAssetItem[]>([]);
  const [searched, setSearched] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [categories, setCategories] = useState<Category[]>([]);
  const [chinazTags, setChinazTags] = useState<{ name: string; url: string }[]>([]);
  const [chinazCategory, setChinazCategory] = useState("");
  const [tagPickerOpen, setTagPickerOpen] = useState(false);
  const [tagFilter, setTagFilter] = useState("");
  const [savedToast, setSavedToast] = useState<"" | "url" | "download">("");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [batchType, setBatchType] = useState("sfx");
  const [batchCategory, setBatchCategory] = useState("");
  const [batchBusy, setBatchBusy] = useState(false);
  const [batchDownloading, setBatchDownloading] = useState(false);

  const loadCategories = useCallback(async () => {
    try {
      const cats = await voiceForgeApi.assetCategories();
      setCategories(cats.data.categories.map((c: any) => ({ id: c.id, label: c.label, asset_type: c.asset_type })));
    } catch {
      setCategories([]);
    }
  }, []);

  useEffect(() => {
    if (open) loadCategories();
  }, [open, loadCategories]);

  const loadChinazTags = useCallback(async () => {
    try {
      const res = await voiceForgeApi.onlineCategories();
      setChinazTags(res.data.tags || []);
    } catch {
      setChinazTags([]);
    }
  }, []);

  useEffect(() => {
    if (open && activeTab === "chinaz" && chinazTags.length === 0) {
      void loadChinazTags();
    }
  }, [open, activeTab, chinazTags.length, loadChinazTags]);

  const doSearch = useCallback(async (overrides?: { keyword?: string; categoryUrl?: string }) => {
    const kw = (overrides?.keyword ?? keyword).trim();
    const cat = overrides?.categoryUrl ?? chinazCategory;
    if (!kw && !(activeTab === "chinaz" && cat)) return;
    setLoading(true);
    setSearched(true);
    setSearchError("");
    setPage(0);
    setSelected(new Set());
    try {
      if (activeTab === "chinaz") {
        const res = await voiceForgeApi.onlineSearch({
          source: "chinaz",
          keyword: kw,
          categoryUrl: cat,
        });
        setItems(res.data.items || []);
      } else {
        const res = await voiceForgeApi.onlineSearch({ source: "elevenlabs", keyword: kw });
        setItems(res.data.items || []);
      }
    } catch (err: any) {
      setSearchError(err?.response?.data?.detail || "在线素材搜索失败，请稍后重试");
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [keyword, activeTab, chinazCategory]);

  const sounds = useMemo(() => flattenSounds(items), [items]);
  const pageCount = Math.max(1, Math.ceil(sounds.length / PAGE_SIZE));
  const pagedSounds = useMemo(
    () => sounds.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE),
    [sounds, page],
  );
  const pageKeys = useMemo(() => pagedSounds.map((s) => s.audio_url), [pagedSounds]);
  const allPageSelected = pageKeys.length > 0 && pageKeys.every((k) => selected.has(k));
  const soundMap = useMemo(() => new Map(sounds.map((s) => [s.audio_url, s])), [sounds]);

  const toggleKey = useCallback((key: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  }, []);

  const togglePage = useCallback((checked: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      for (const k of pageKeys) {
        if (checked) next.add(k); else next.delete(k);
      }
      return next;
    });
  }, [pageKeys]);

  const handleSaved = useCallback((download: boolean) => {
    setSavedToast(download ? "download" : "url");
    window.setTimeout(() => setSavedToast(""), 1800);
    onImported?.();
  }, [onImported]);

  const batchImport = useCallback(async (download: boolean) => {
    const keys = Array.from(selected);
    if (keys.length === 0) return;
    setBatchBusy(true);
    try {
      for (const key of keys) {
        const s = soundMap.get(key);
        if (!s) continue;
        await voiceForgeApi.onlineImport({
          name: s.name || "未命名素材",
          asset_type: batchType,
          source_url: s.audio_url,
          source_site: "elevenlabs",
          source_id: s.id,
          category: batchCategory,
          tags: s.labels || [],
          description: s.short_description || "",
          download,
        });
      }
      setSavedToast(download ? "download" : "url");
      setSelected(new Set());
      onImported?.();
    } catch (err: any) {
      setSearchError(err?.response?.data?.detail || "批量入库失败，请稍后重试");
    } finally {
      setBatchBusy(false);
    }
  }, [selected, soundMap, batchType, batchCategory, onImported]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[88vh] w-[min(1280px,96vw)] max-w-none flex-col gap-3 overflow-hidden p-0">
        <DialogHeader className="border-b px-4 py-3">
          <DialogTitle>在线素材</DialogTitle>
        </DialogHeader>

        <Tabs value={activeTab} onValueChange={setActiveTab} className="flex min-h-0 flex-1 flex-col px-4">
          <TabsList className="w-fit">
            {SOURCE_TABS.map((tab) => (
              <TabsTrigger key={tab.id} value={tab.id}>{tab.label}</TabsTrigger>
            ))}
          </TabsList>

          {SOURCE_TABS.map((tab) => (
            <TabsContent key={tab.id} value={tab.id} className="mt-3 flex min-h-0 flex-1 flex-col gap-3 data-[state=inactive]:hidden">
              {activeTab === "chinaz" && (
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    className="h-9 flex-1 justify-between"
                    onClick={() => setTagPickerOpen(true)}
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <Tag className="size-4 shrink-0 text-muted-foreground" />
                      <span className="truncate">
                        {chinazCategory
                          ? chinazTags.find((c) => c.url === chinazCategory)?.name || "已选分类"
                          : chinazTags.length
                            ? "点击选择分类标签…"
                            : "加载分类中…"}
                      </span>
                    </span>
                    <ChevronDown className="size-4 shrink-0 opacity-60" />
                  </Button>
                  {chinazCategory && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="size-9 shrink-0"
                      onClick={() => setChinazCategory("")}
                      title="清空分类"
                    >
                      <XCircle className="size-4" />
                    </Button>
                  )}
                </div>
              )}

              <div className="flex gap-2">
                <Input
                  placeholder={activeTab === "chinaz" ? "输入关键词搜索素材…" : "输入关键词搜索素材…"}
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") doSearch(); }}
                />
                <Button onClick={() => doSearch()} disabled={loading || (!keyword.trim() && !(activeTab === "chinaz" && chinazCategory))}>
                  {loading ? <Loader2 className="mr-1 size-4 animate-spin" /> : <Search className="mr-1 size-4" />}
                  搜索
                </Button>
              </div>

              {sounds.length > 0 && (
                <div className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/30 px-2 py-1.5">
                  <label className="flex items-center gap-1.5 text-xs">
                    <input type="checkbox" className="size-4 accent-primary" checked={allPageSelected} onChange={(e) => togglePage(e.target.checked)} />
                    全选本页
                  </label>
                  <span className="text-xs text-muted-foreground">已选 {selected.size} 项</span>
                  <div className="ml-auto flex items-center gap-2">
                    <Select value={batchType} onValueChange={setBatchType}>
                      <SelectTrigger className="h-7 w-24 text-xs"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {Object.entries(ASSET_TYPE_LABELS).map(([value, label]) => (
                          <SelectItem key={value} value={value}>{label}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Select value={batchCategory} onValueChange={setBatchCategory}>
                      <SelectTrigger className="h-7 w-32 text-xs">
                        <SelectValue placeholder="批量分类：未分类" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__none">未分类</SelectItem>
                        {categories.map((c) => (
                          <SelectItem key={c.id} value={c.id}>{c.label}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Button size="sm" variant="outline" disabled={selected.size === 0 || batchBusy} onClick={() => batchImport(false)}>
                      {batchBusy && !batchDownloading ? <Loader2 className="mr-1 size-3.5 animate-spin" /> : <Save className="mr-1 size-3.5" />}
                      批量保存URL
                    </Button>
                    <Button size="sm" disabled={selected.size === 0 || batchBusy} onClick={() => { setBatchDownloading(true); batchImport(true).finally(() => setBatchDownloading(false)); }}>
                      {batchDownloading ? <Loader2 className="mr-1 size-3.5 animate-spin" /> : <Download className="mr-1 size-3.5" />}
                      批量下载入库
                    </Button>
                  </div>
                </div>
              )}

              <div className="min-h-0 flex-1 overflow-y-auto pr-1">
                {loading && (
                  <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
                    <Loader2 className="size-4 animate-spin" /> 正在搜索在线素材…
                  </div>
                )}
                {!loading && searched && sounds.length === 0 && (
                  <div className="py-16 text-center text-sm text-muted-foreground">未找到相关素材</div>
                )}
                {!loading && !searched && (
                  <div className="py-16 text-center text-sm text-muted-foreground">
                    输入关键词，从 {tab.label} 检索在线音效素材
                  </div>
                )}
                {!loading && searchError && (
                  <div className="mx-auto max-w-xl rounded-md border border-destructive/40 bg-destructive/10 px-3 py-3 text-center text-xs text-destructive">
                    {searchError}
                  </div>
                )}
                {!loading && sounds.length > 0 && (
                  <>
                    <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-4">
                      {pagedSounds.map((sound) => (
                        <SoundCard
                          key={sound.audio_url}
                          sound={sound}
                          selected={selected.has(sound.audio_url)}
                          onToggle={() => toggleKey(sound.audio_url)}
                          categories={categories}
                          onSaved={handleSaved}
                          onPick={onPick}
                        />
                      ))}
                    </div>
                    <div className="mt-3 flex items-center justify-between border-t pt-2">
                      <span className="text-xs text-muted-foreground">
                        共 {sounds.length} 条 · 第 {page + 1}/{pageCount} 页
                      </span>
                      <div className="flex items-center gap-1.5">
                        <Button size="sm" variant="outline" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>
                          上一页
                        </Button>
                        <Button size="sm" variant="outline" disabled={page >= pageCount - 1} onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}>
                          下一页
                        </Button>
                      </div>
                    </div>
                  </>
                )}
              </div>
            </TabsContent>
          ))}
        </Tabs>

        {savedToast === "url" && (
          <div className="pointer-events-none absolute bottom-12 left-1/2 -translate-x-1/2 rounded-md bg-emerald-600 px-3 py-1.5 text-xs text-white shadow">
            URL 已保存到素材库
          </div>
        )}
        {savedToast === "download" && (
          <div className="pointer-events-none absolute bottom-12 left-1/2 -translate-x-1/2 rounded-md bg-sky-600 px-3 py-1.5 text-xs text-white shadow">
            已下载并入库
          </div>
        )}

        <ChinazTagPicker
          open={tagPickerOpen}
          onOpenChange={setTagPickerOpen}
          tags={chinazTags}
          value={chinazCategory}
          onPick={(url) => {
            setChinazCategory(url);
            if (url) void doSearch({ categoryUrl: url });
          }}
        />
      </DialogContent>
    </Dialog>
  );
}

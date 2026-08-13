import { useEffect, useState } from "react";
import { ArrowDownToLine, FolderOpen, FolderPlus, ListMusic, Loader2, Play, Plus, Trash2, X } from "lucide-react";
import { VoiceForgeAssetCategory, VoiceForgeAssetTag, voiceForgeApi } from "@/api/voiceforge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ASSET_TYPE_LABELS, AUDIO_FILETYPES } from "./meta";

type PendingItem = { path: string; size?: number; name: string; category: string; tags: string[] };

function errorText(error: any, fallback: string) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;
  return error?.message || fallback;
}

function baseName(path: string) {
  return path.split(/[\\/]/).pop() || path;
}

function formatBytes(value?: number) {
  if (!value) return "";
  return value >= 1024 * 1024 ? `${(value / 1024 / 1024).toFixed(1)} MB` : `${Math.round(value / 1024)} KB`;
}

export function AssetAddDialog({
  open,
  defaultType,
  onClose,
  onAdded,
}: {
  open: boolean;
  defaultType: string;
  onClose: () => void;
  onAdded: () => void;
}) {
  const [assetType, setAssetType] = useState(defaultType);
  const [category, setCategory] = useState("");
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [allCategories, setAllCategories] = useState<VoiceForgeAssetCategory[]>([]);
  const [tags, setTags] = useState<VoiceForgeAssetTag[]>([]);
  const [paths, setPaths] = useState<PendingItem[]>([]);
  const [manualPath, setManualPath] = useState("");
  const [previewPath, setPreviewPath] = useState("");
  const [recursive, setRecursive] = useState(true);
  const [quickCat, setQuickCat] = useState("");
  const [quickTag, setQuickTag] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState("");
  const [imported, setImported] = useState(0);
  const [total, setTotal] = useState(0);

  const loadRefs = async (type: string) => {
    const [categoryResult, tagResult] = await Promise.all([
      voiceForgeApi.assetCategories(),
      voiceForgeApi.assetTags("", type),
    ]);
    setAllCategories(categoryResult.data.categories);
    setTags(tagResult.data.tags);
  };

  useEffect(() => {
    if (open) {
      setAssetType(defaultType);
      setCategory("");
      setSelectedTags([]);
      setName("");
      setPaths([]);
      setManualPath("");
      setPreviewPath("");
      setError("");
      setInfo("");
      setImported(0);
      setTotal(0);
      void loadRefs(defaultType);
    }
  }, [open, defaultType]);

  const typeCategories = allCategories.filter((item) => item.asset_type === assetType);

  const changeType = (value: string) => {
    setAssetType(value);
    if (category && !typeCategories.some((item) => item.name === category)) {
      setCategory("");
    }
    void loadRefs(value);
  };

  const appendPaths = (items: Array<{ path: string; size?: number }>) => {
    setPaths((current) => {
      const existing = new Set(current.map((item) => item.path));
      const added = items
        .filter((item) => !existing.has(item.path))
        .map((item) => ({ path: item.path, size: item.size, name: "", category, tags: [...selectedTags] }));
      return [...current, ...added];
    });
  };

  const updateItem = (path: string, patch: Partial<Pick<PendingItem, "name" | "category" | "tags">>) => {
    setPaths((current) => current.map((item) => (item.path === path ? { ...item, ...patch } : item)));
  };

  const pickFiles = async () => {
    const result = await voiceForgeApi.fileDialog({ type: "file", title: "选择音频素材（可多选）", filetypes: AUDIO_FILETYPES, multiple: true });
    if (!result.data.cancelled) {
      appendPaths((result.data.paths || []).map((path) => ({ path })));
    }
  };

  const pickFolder = async () => {
    setBusy("folder");
    setError("");
    try {
      const result = await voiceForgeApi.fileDialog({ type: "folder", title: "选择音频文件夹", multiple: false });
      const folder = result.data.paths?.[0] || result.data.path || "";
      if (result.data.cancelled || !folder) return;
      const scan = await voiceForgeApi.scanAudio(folder, recursive);
      const found = (scan.data.files || []).map((file) => ({ path: file.path, size: file.size }));
      if (!found.length) {
        setError(recursive ? "该文件夹（含子文件夹）下未找到音频文件" : "该文件夹下未找到音频文件");
        return;
      }
      appendPaths(found);
    } catch (err) {
      setError(errorText(err, "扫描文件夹失败"));
    } finally {
      setBusy("");
    }
  };

  const addManual = () => {
    const value = manualPath.trim();
    if (!value) return;
    appendPaths([{ path: value }]);
    setManualPath("");
  };

  const removePath = (path: string) => {
    setPaths((current) => current.filter((item) => item.path !== path));
    if (previewPath === path) setPreviewPath("");
  };

  const addQuickCategory = async () => {
    const label = quickCat.trim();
    if (!label) return;
    setBusy("quick-cat");
    setError("");
    try {
      const created = await voiceForgeApi.createAssetCategory({
        name: label.toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]/g, "") || `cat_${Date.now()}`,
        label,
        asset_type: assetType,
        sort_order: typeCategories.length,
      });
      setCategory(created.data.category.name);
      setQuickCat("");
      setAllCategories((await voiceForgeApi.assetCategories()).data.categories);
    } catch (err) {
      setError(errorText(err, "新增分类失败"));
    } finally {
      setBusy("");
    }
  };

  const addQuickTag = async () => {
    const value = quickTag.trim();
    if (!value) return;
    setBusy("quick-tag");
    setError("");
    try {
      const created = await voiceForgeApi.createAssetTag(value);
      const tag = created.data.tag;
      // 新标签尚未被任何素材使用，按类型聚合查询不会包含它，这里直接并入可选项
      setTags((current) => (current.some((item) => item.name === tag.name) ? current : [...current, tag]));
      if (!selectedTags.includes(value)) setSelectedTags((current) => [...current, value]);
      setQuickTag("");
    } catch (err) {
      setError(errorText(err, "新增标签失败"));
    } finally {
      setBusy("");
    }
  };

  const syncDefaults = () => {
    setPaths((current) => current.map((item) => ({ ...item, name, category, tags: [...selectedTags] })));
  };

  const toggleTag = (tagName: string) => {
    setSelectedTags((current) => current.includes(tagName) ? current.filter((item) => item !== tagName) : [...current, tagName]);
  };

  const importAll = async () => {
    if (!paths.length) return;
    setBusy("import");
    setError("");
    setInfo("");
    setImported(0);
    setTotal(paths.length);
    let failed = 0;
    let duplicates = 0;
    for (const item of paths) {
      try {
        const result = await voiceForgeApi.createAssetFromPath({
          name: item.name.trim() || name.trim() || undefined,
          asset_type: assetType,
          category: item.category || undefined,
          tags: item.tags,
          path: item.path,
        });
        if (result.data.created === false) duplicates += 1;
        setImported((current) => current + 1);
      } catch (err) {
        failed += 1;
        setError(errorText(err, "导入失败"));
      }
    }
    setBusy("");
    onAdded();
    if (failed > 0) {
      setError(`有 ${failed} 个文件导入失败，其余已成功。`);
      setPaths([]);
    } else if (duplicates > 0) {
      setInfo(`已导入 ${total - duplicates} 个新素材，${duplicates} 个为重复素材（同类型下相同路径），已仅更新其分类/标签等信息，未新建记录。`);
      setPaths([]);
    } else {
      onClose();
    }
  };

  return (
    <Dialog open={open} onOpenChange={(value) => !value && onClose()}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>添加素材</DialogTitle>
          <DialogDescription>仅记录本地文件路径，不复制文件到项目；素材类型为必选项，分类与标签作为批次默认值，可逐条调整。</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <div className="grid gap-2 md:grid-cols-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">素材类型 <span className="text-destructive">*</span></label>
              <select value={assetType} onChange={(event) => changeType(event.target.value)} className="voice-input">
                {Object.entries(ASSET_TYPE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">分类（批次默认）</label>
              <div className="flex gap-1.5">
                <select value={category} onChange={(event) => setCategory(event.target.value)} className="voice-input">
                  <option value="">未分类</option>
                  {typeCategories.map((item) => (
                    <option key={item.id} value={item.name}>{item.label}</option>
                  ))}
                </select>
                <input
                  value={quickCat}
                  onChange={(event) => setQuickCat(event.target.value)}
                  onKeyDown={(event) => event.key === "Enter" && void addQuickCategory()}
                  placeholder="新分类"
                  className="voice-input w-24 text-xs"
                />
                <Button variant="outline" size="icon" onClick={() => void addQuickCategory()} disabled={busy === "quick-cat" || !quickCat.trim()} title="快捷新增分类">
                  {busy === "quick-cat" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                </Button>
              </div>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">素材名称（批次默认，留空用文件名）</label>
              <input value={name} onChange={(event) => setName(event.target.value)} className="voice-input" placeholder="可留空" />
            </div>
          </div>
          <div>
            <div className="mb-1 text-xs font-medium text-muted-foreground">标签（批次默认）</div>
            <div className="flex flex-wrap items-center gap-1.5">
              {tags.map((tag) => (
                <button
                  key={tag.id}
                  type="button"
                  onClick={() => toggleTag(tag.name)}
                  className={`rounded-full border px-2.5 py-1 text-xs ${selectedTags.includes(tag.name) ? "border-primary/60 bg-primary/10 text-primary" : "border-border/60 text-muted-foreground hover:bg-accent"}`}
                >
                  {tag.name}
                </button>
              ))}
              {!tags.length && <span className="text-xs text-muted-foreground">该类型暂无标签。</span>}
              <input
                value={quickTag}
                onChange={(event) => setQuickTag(event.target.value)}
                onKeyDown={(event) => event.key === "Enter" && void addQuickTag()}
                placeholder="新标签"
                className="voice-input h-7 w-24 text-xs"
              />
              <Button variant="outline" size="icon" onClick={() => void addQuickTag()} disabled={busy === "quick-tag" || !quickTag.trim()} title="快捷新增标签">
                {busy === "quick-tag" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              </Button>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={syncDefaults} disabled={!paths.length} title="将上方名称、分类、标签应用到下方所有条目">
              <ArrowDownToLine className="mr-1.5 h-4 w-4" />同步到下方列表
            </Button>
            <span className="text-[11px] text-muted-foreground">将上方“名称、分类、标签”应用到下方全部 {paths.length || ""} 个条目，之后仍可逐条修改</span>
          </div>
          <div>
            <div className="mb-1 text-xs font-medium text-muted-foreground">本地文件（仅记录路径）</div>
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="outline" onClick={() => void pickFiles()} disabled={busy === "import" || busy === "folder"}>
                <FolderPlus className="mr-1.5 h-4 w-4" />选择文件
              </Button>
              <Button variant="outline" onClick={() => void pickFolder()} disabled={busy === "import" || busy === "folder"}>
                {busy === "folder" ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <FolderOpen className="mr-1.5 h-4 w-4" />}选择文件夹
              </Button>
              <label className="flex cursor-pointer items-center gap-1.5 rounded-md border border-border/60 px-2.5 py-1.5 text-xs text-muted-foreground">
                <input type="checkbox" checked={recursive} onChange={(event) => setRecursive(event.target.checked)} className="h-3.5 w-3.5" />
                遍历子文件夹
              </label>
              <input value={manualPath} onChange={(event) => setManualPath(event.target.value)} onKeyDown={(event) => event.key === "Enter" && addManual()} placeholder="或直接粘贴文件路径" className="voice-input min-w-40 flex-1" />
              <Button variant="outline" size="icon" onClick={addManual} title="添加路径"><Plus className="h-4 w-4" /></Button>
            </div>
            {paths.length ? (
              <div className="mt-2 rounded-lg border border-border/50 p-2">
                <div className="mb-1.5 flex items-center justify-between text-[11px] text-muted-foreground">
                  <span className="flex items-center gap-1"><ListMusic className="h-3.5 w-3.5" />已选 {paths.length} 个文件，可逐条设置名称、分类与标签</span>
                  <button type="button" onClick={() => { setPaths([]); setPreviewPath(""); }} className="hover:text-destructive">清空</button>
                </div>
                <div className="max-h-56 space-y-1 overflow-y-auto pr-1">
                  <div className="grid grid-cols-[auto_minmax(140px,1fr)_150px_110px_150px_auto] items-center gap-2 text-[11px] text-muted-foreground">
                    <span />
                    <span>文件</span>
                    <span>素材名称</span>
                    <span>分类</span>
                    <span>标签</span>
                    <span />
                  </div>
                  {paths.map((item) => (
                    <div key={item.path} className="grid grid-cols-[auto_minmax(140px,1fr)_150px_110px_150px_auto] items-center gap-2 rounded border border-border/40 px-2 py-1.5 text-xs">
                      <button
                        type="button"
                        onClick={() => setPreviewPath(previewPath === item.path ? "" : item.path)}
                        title={previewPath === item.path ? "停止预览" : "试听预览"}
                        className="shrink-0 rounded-full bg-primary/10 p-1 text-primary hover:bg-primary/20"
                      >
                        {previewPath === item.path ? <X className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                      </button>
                      <div className="min-w-0">
                        <div className="truncate" title={item.path}>{baseName(item.path)}</div>
                        <div className="text-[10px] text-muted-foreground">{item.size ? formatBytes(item.size) : ""}</div>
                      </div>
                      <input
                        value={item.name}
                        onChange={(event) => updateItem(item.path, { name: event.target.value })}
                        placeholder="留空用全局/文件名"
                        className="voice-input h-8 w-full text-xs"
                      />
                      <select value={item.category} onChange={(event) => updateItem(item.path, { category: event.target.value })} className="voice-input h-8 w-full text-xs">
                        <option value="">未分类</option>
                        {typeCategories.map((cat) => (
                          <option key={cat.id} value={cat.name}>{cat.label}</option>
                        ))}
                      </select>
                      <select
                        multiple
                        size={2}
                        value={item.tags}
                        onChange={(event) => updateItem(item.path, { tags: Array.from(event.target.selectedOptions, (option) => option.value) })}
                        className="voice-input h-10 w-full text-xs"
                      >
                        {tags.map((tag) => (
                          <option key={tag.id} value={tag.name}>{tag.name}</option>
                        ))}
                      </select>
                      <button type="button" onClick={() => removePath(item.path)} className="shrink-0 text-muted-foreground hover:text-destructive" title="移除">
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
                {previewPath && (
                  <audio controls autoPlay preload="none" src={voiceForgeApi.fileStreamUrl(previewPath)} className="mt-1.5 h-8 w-full" />
                )}
              </div>
            ) : null}
          </div>
          {error && <p className="rounded-lg border border-destructive/30 bg-destructive/5 p-2 text-xs text-destructive">{error}</p>}
          {info && <p className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-2 text-xs text-emerald-600">{info}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy === "import"}>取消</Button>
          <Button onClick={() => void importAll()} disabled={!paths.length || busy === "import" || busy === "folder"}>
            {busy === "import" ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Plus className="mr-1.5 h-4 w-4" />}
            {busy === "import" ? `导入中 ${imported}/${total}` : `批量导入 ${paths.length || ""} 个`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

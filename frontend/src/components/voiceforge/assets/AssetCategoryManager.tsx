import { useEffect, useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { VoiceForgeAssetCategory, voiceForgeApi } from "@/api/voiceforge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ASSET_TYPE_COLORS, ASSET_TYPE_LABELS, ASSET_TYPE_ORDER } from "./meta";

export function AssetCategoryManager({
  open,
  activeType,
  onClose,
  onChanged,
}: {
  open: boolean;
  activeType: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [currentType, setCurrentType] = useState(activeType);
  const [categories, setCategories] = useState<VoiceForgeAssetCategory[]>([]);
  const [name, setName] = useState("");
  const [label, setLabel] = useState("");
  const [editing, setEditing] = useState<VoiceForgeAssetCategory | null>(null);
  const [busy, setBusy] = useState("");

  const load = async (type = currentType) => {
    const result = await voiceForgeApi.assetCategories(type);
    setCategories(result.data.categories);
  };

  useEffect(() => {
    if (open) {
      setCurrentType(activeType);
      setName("");
      setLabel("");
      setEditing(null);
      void load(activeType);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, activeType]);

  const switchType = (type: string) => {
    setCurrentType(type);
    setEditing(null);
    setName("");
    setLabel("");
    void load(type);
  };

  const create = async () => {
    if (!name.trim() || !label.trim()) return;
    setBusy("create");
    try {
      await voiceForgeApi.createAssetCategory({
        name: name.trim().toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]/g, "") || `cat_${Date.now()}`,
        label: label.trim(),
        asset_type: currentType,
        sort_order: categories.length,
      });
      setName("");
      setLabel("");
      await load();
      onChanged();
    } finally {
      setBusy("");
    }
  };

  const update = async () => {
    if (!editing || !label.trim()) return;
    setBusy("update");
    try {
      await voiceForgeApi.updateAssetCategory(editing.id, {
        name: name.trim().toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]/g, "") || editing.name,
        label: label.trim(),
      });
      setEditing(null);
      await load();
      onChanged();
    } finally {
      setBusy("");
    }
  };

  const remove = async (category: VoiceForgeAssetCategory) => {
    if (!confirm(`删除分类“${category.label}”？`)) return;
    await voiceForgeApi.deleteAssetCategory(category.id);
    await load();
    onChanged();
  };

  const startEdit = (category: VoiceForgeAssetCategory) => {
    setEditing(category);
    setName(category.name);
    setLabel(category.label);
  };

  return (
    <Dialog open={open} onOpenChange={(value) => !value && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>分类管理</DialogTitle>
          <DialogDescription>分别维护背景音乐、音效和环境音的分类，素材数量实时统计。</DialogDescription>
        </DialogHeader>
        <div className="flex gap-1">
          {ASSET_TYPE_ORDER.map((type) => {
            const isActive = type === currentType;
            const typeColor = ASSET_TYPE_COLORS[type];
            return (
              <button
                key={type}
                type="button"
                onClick={() => switchType(type)}
                className={`flex-1 rounded-lg border px-3 py-1.5 text-sm ${isActive ? "font-semibold" : "border-border/60 text-muted-foreground hover:bg-accent"}`}
                style={isActive ? { borderColor: typeColor, color: typeColor, background: `${typeColor}14` } : undefined}
              >
                {ASSET_TYPE_LABELS[type]}
              </button>
            );
          })}
        </div>
        <div className="max-h-64 space-y-1.5 overflow-y-auto">
          {categories.map((item) => (
            <div key={item.id} className="flex items-center gap-2 rounded-lg border border-border/50 px-3 py-2 text-sm">
              <span className="min-w-0 flex-1 truncate">{item.label}</span>
              <span className="text-xs text-muted-foreground">{item.count} 个</span>
              <Button size="icon" variant="ghost" onClick={() => startEdit(item)} title="编辑"><Pencil className="h-3.5 w-3.5" /></Button>
              <Button size="icon" variant="ghost" onClick={() => void remove(item)} title="删除"><Trash2 className="h-3.5 w-3.5 text-destructive" /></Button>
            </div>
          ))}
          {!categories.length && <p className="py-8 text-center text-sm text-muted-foreground">该类型暂无分类，请在下方添加。</p>}
        </div>
        <div className="flex gap-2">
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder="分类标识（英文，如 epic）" className="voice-input flex-1" />
          <input value={label} onChange={(event) => setLabel(event.target.value)} placeholder="显示名（如 史诗）" className="voice-input flex-1" />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>关闭</Button>
          {editing ? (
            <Button onClick={() => void update()} disabled={busy === "update"}>保存修改</Button>
          ) : (
            <Button onClick={() => void create()} disabled={busy === "create"}><Plus className="mr-1.5 h-4 w-4" />添加分类</Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

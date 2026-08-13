import { FormEvent, useEffect, useState } from "react";
import { Loader2, Pencil, Plus, Trash2 } from "lucide-react";
import { VoiceForgeEmotionTag, voiceForgeApi } from "@/api/voiceforge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

export function EmotionTagDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [tags, setTags] = useState<VoiceForgeEmotionTag[]>([]);
  const [name, setName] = useState("");
  const [color, setColor] = useState("#14b8a6");
  const [busy, setBusy] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState("");

  const load = async () => setTags((await voiceForgeApi.emotionTags()).data.tags);
  useEffect(() => { if (open) { load(); setEditingId(null); setEditingName(""); } }, [open]);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    try {
      await voiceForgeApi.createEmotionTag({ name: name.trim(), color });
      setName("");
      await load();
    } finally {
      setBusy(false);
    }
  };

  const startEdit = (tag: VoiceForgeEmotionTag) => {
    setEditingId(tag.id);
    setEditingName(tag.name);
  };

  const saveEdit = async (tag: VoiceForgeEmotionTag) => {
    if (!editingName.trim() || editingName.trim() === tag.name) {
      setEditingId(null);
      return;
    }
    setBusy(true);
    try {
      await voiceForgeApi.updateEmotionTag(tag.id, { name: editingName.trim() });
      await load();
    } finally {
      setBusy(false);
      setEditingId(null);
    }
  };

  const deleteTag = async (tag: VoiceForgeEmotionTag) => {
    if (!confirm(`删除情绪标签"${tag.name}"？`)) return;
    await voiceForgeApi.deleteEmotionTag(tag.id);
    await load();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>情绪标签管理</DialogTitle>
          <DialogDescription>管理可在音色和句子中复用的情绪标签。</DialogDescription>
        </DialogHeader>

        <form onSubmit={create} className="flex gap-2">
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="voice-input flex-1"
            placeholder="新标签名称"
          />
          <input
            value={color}
            onChange={(event) => setColor(event.target.value)}
            className="h-9 w-9 border border-border bg-background p-1"
            type="color"
          />
          <Button size="sm" disabled={busy}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
          </Button>
        </form>

        <div className="max-h-72 space-y-1 overflow-y-auto pr-1">
          {tags.map((tag) => (
            <div key={tag.id} className="flex items-center gap-2 rounded-lg border border-border px-3 py-2">
              <i className="h-3 w-3 shrink-0 rounded-full" style={{ backgroundColor: tag.color || "#94a3b8" }} />
              {editingId === tag.id ? (
                <input
                  autoFocus
                  value={editingName}
                  onChange={(event) => setEditingName(event.target.value)}
                  onKeyDown={(event) => { if (event.key === "Enter") saveEdit(tag); if (event.key === "Escape") setEditingId(null); }}
                  onBlur={() => saveEdit(tag)}
                  className="h-7 flex-1 border border-border bg-background px-2 text-sm"
                />
              ) : (
                <span className="flex-1 text-sm">{tag.name}</span>
              )}
              <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-foreground" onClick={() => startEdit(tag)} aria-label="编辑">
                <Pencil className="h-3.5 w-3.5" />
              </Button>
              <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-destructive" onClick={() => deleteTag(tag)} aria-label="删除">
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
          ))}
          {!tags.length && <p className="py-4 text-center text-sm text-muted-foreground">暂无情绪标签</p>}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>关闭</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

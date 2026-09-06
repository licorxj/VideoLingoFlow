import { useState } from "react";
import { AudioLines, X } from "lucide-react";
import { materialsApi } from "@/api/materials";
import { VoiceForgeVoice } from "@/api/voiceforge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { VoicePickerDialog } from "./VoicePickerDialog";

const EMPTY = {
  name: "",
  tags: "",
  gender: "",
  age: "",
  occupation: "",
  aliases: "",
  personality: "",
  voice_design: "",
  voice_ref: "",
  images_dir: "",
};

/** 新建公共角色弹窗。 */
export function CharacterAddDialog({ open, onClose, onAdded }: { open: boolean; onClose: () => void; onAdded: () => void }) {
  const [form, setForm] = useState({ ...EMPTY });
  const [voiceName, setVoiceName] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const set = (patch: Partial<typeof EMPTY>) => setForm((current) => ({ ...current, ...patch }));

  const handleVoiceSelected = (ref: string, voice: VoiceForgeVoice) => {
    set({ voice_ref: ref });
    setVoiceName(voice.display_name || voice.name);
  };

  const submit = async () => {
    if (!form.name.trim()) {
      setError("角色名称不能为空");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await materialsApi.createCharacter({
        name: form.name.trim(),
        tags: form.tags.split(",").map((item) => item.trim()).filter(Boolean),
        gender: form.gender,
        age: form.age,
        occupation: form.occupation,
        aliases: form.aliases.split(",").map((item) => item.trim()).filter(Boolean),
        personality: form.personality,
        voice_design: form.voice_design,
        voice_ref: form.voice_ref.trim(),
        images_dir: form.images_dir.trim(),
      });
      setForm({ ...EMPTY });
      onAdded();
      onClose();
    } catch (err: any) {
      setError(err?.message || "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(value) => !value && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>添加角色</DialogTitle>
          <DialogDescription>角色进入公共角色库,可被各创作项目引用;音色引用填 vf:voices:&lt;id&gt; 格式。</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <label className="text-xs font-medium text-muted-foreground">姓名 *</label>
          <input value={form.name} onChange={(event) => set({ name: event.target.value })} className="voice-input" placeholder="如 林远" />
          <div className="grid grid-cols-3 gap-2">
            <div>
              <label className="text-xs font-medium text-muted-foreground">性别</label>
              <input value={form.gender} onChange={(event) => set({ gender: event.target.value })} className="voice-input mt-1" />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground">年龄</label>
              <input value={form.age} onChange={(event) => set({ age: event.target.value })} className="voice-input mt-1" placeholder="如 28" />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground">职业</label>
              <input value={form.occupation} onChange={(event) => set({ occupation: event.target.value })} className="voice-input mt-1" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-xs font-medium text-muted-foreground">标签(逗号分隔)</label>
              <input value={form.tags} onChange={(event) => set({ tags: event.target.value })} className="voice-input mt-1" placeholder="如 主角, 冷静" />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground">别名(逗号分隔)</label>
              <input value={form.aliases} onChange={(event) => set({ aliases: event.target.value })} className="voice-input mt-1" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-xs font-medium text-muted-foreground">性格</label>
              <textarea value={form.personality} onChange={(event) => set({ personality: event.target.value })} className="voice-input mt-1 min-h-24 resize-none" />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground">音色设计描述</label>
              <textarea value={form.voice_design} onChange={(event) => set({ voice_design: event.target.value })} className="voice-input mt-1 min-h-24 resize-none" placeholder="如 低沉磁性,语速偏慢" />
            </div>
          </div>
          <label className="text-xs font-medium text-muted-foreground">音色素材引用</label>
          <div className="flex items-center gap-2">
            <Button type="button" variant="outline" onClick={() => setPickerOpen(true)}>
              <AudioLines className="mr-1.5 h-4 w-4" />
              选择音色
            </Button>
            {form.voice_ref ? (
              <span className="flex min-w-0 flex-1 items-center gap-1.5 rounded-md border border-border/60 bg-muted/30 px-2.5 py-1.5 text-xs">
                <span className="truncate text-muted-foreground">
                  {voiceName && <span className="font-semibold text-foreground">{voiceName} · </span>}
                  <span className="font-mono">{form.voice_ref}</span>
                </span>
                <button
                  type="button"
                  title="清除音色"
                  onClick={() => {
                    set({ voice_ref: "" });
                    setVoiceName("");
                  }}
                  className="ml-auto shrink-0 rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </span>
            ) : (
              <span className="text-xs text-muted-foreground">未选择,点击按钮试听并选择音色</span>
            )}
          </div>
          <label className="text-xs font-medium text-muted-foreground">多视角图文件夹(data/ 相对路径)</label>
          <input value={form.images_dir} onChange={(event) => set({ images_dir: event.target.value })} className="voice-input" placeholder="如 data/characters/linyuan/views" />
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>取消</Button>
          <Button onClick={() => void submit()} disabled={saving}>{saving ? "保存中…" : "保存"}</Button>
        </DialogFooter>
      </DialogContent>
      <VoicePickerDialog open={pickerOpen} onClose={() => setPickerOpen(false)} onSelected={handleVoiceSelected} />
    </Dialog>
  );
}

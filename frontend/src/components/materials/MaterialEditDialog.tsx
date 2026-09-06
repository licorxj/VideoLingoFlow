import { useState } from "react";
import { MaterialCharacter, MaterialImage, MaterialVideo, materialsApi } from "@/api/materials";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

export type EditTarget =
  | { kind: "image"; data: MaterialImage }
  | { kind: "video"; data: MaterialVideo }
  | { kind: "character"; data: MaterialCharacter };

function splitTags(value: string): string[] {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

/**
 * 通用素材元数据编辑弹窗(不影响文件本身)。
 * 页面侧用 key=<id> 渲染,保证每次打开都以初始值重建表单。
 */
export function MaterialEditDialog({ target, onClose, onSaved }: { target: EditTarget; onClose: () => void; onSaved: () => void }) {
  const { kind, data } = target;
  const isCharacter = kind === "character";
  const [groupTags, setGroupTags] = useState(isCharacter ? (data as MaterialCharacter).tags.join(", ") : (data as MaterialImage).group_tags.join(", "));
  const [subTags, setSubTags] = useState(isCharacter ? (data as MaterialCharacter).aliases.join(", ") : (data as MaterialImage).custom_tags.join(", "));
  const [longText, setLongText] = useState(isCharacter ? (data as MaterialCharacter).personality : (data as MaterialImage).description);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    setSaving(true);
    setError("");
    try {
      if (kind === "character") {
        await materialsApi.updateCharacter(data.id, { tags: splitTags(groupTags), aliases: splitTags(subTags), personality: longText });
      } else if (kind === "image") {
        await materialsApi.updateImage(data.id, { group_tags: splitTags(groupTags), custom_tags: splitTags(subTags), description: longText });
      } else {
        await materialsApi.updateVideo(data.id, { group_tags: splitTags(groupTags), custom_tags: splitTags(subTags), description: longText });
      }
      onSaved();
      onClose();
    } catch (err: any) {
      setError(err?.message || "保存失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open onOpenChange={(value) => !value && onClose()}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>编辑素材</DialogTitle>
          <DialogDescription>修改元数据不会影响源文件。</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <div className={isCharacter ? "grid grid-cols-2 gap-2" : ""}>
            <div>
              <label className="text-xs font-medium text-muted-foreground">{isCharacter ? "标签(逗号分隔)" : "分组标签(逗号分隔)"}</label>
              <input value={groupTags} onChange={(event) => setGroupTags(event.target.value)} className={isCharacter ? "voice-input mt-1" : "voice-input"} />
            </div>
            {isCharacter && (
              <div>
                <label className="text-xs font-medium text-muted-foreground">别名(逗号分隔)</label>
                <input value={subTags} onChange={(event) => setSubTags(event.target.value)} className="voice-input mt-1" />
              </div>
            )}
          </div>
          {!isCharacter && (
            <>
              <label className="text-xs font-medium text-muted-foreground">自定义标签(逗号分隔)</label>
              <input value={subTags} onChange={(event) => setSubTags(event.target.value)} className="voice-input" />
            </>
          )}
          <label className="text-xs font-medium text-muted-foreground">{isCharacter ? "性格" : "描述"}</label>
          <textarea value={longText} onChange={(event) => setLongText(event.target.value)} className="voice-input min-h-16 resize-none" />
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={saving}>取消</Button>
          <Button onClick={() => void submit()} disabled={saving}>{saving ? "保存中…" : "保存"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

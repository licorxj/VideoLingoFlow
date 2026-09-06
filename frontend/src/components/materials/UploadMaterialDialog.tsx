import { useRef, useState } from "react";
import { Upload } from "lucide-react";
import { materialsApi } from "@/api/materials";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

export type UploadKind = "image" | "video";

/** 图片/视频上传弹窗:文件复制进 data/materials/ 并登记元数据,支持一次多选。 */
export function UploadMaterialDialog({
  kind,
  open,
  onClose,
  onAdded,
}: {
  kind: UploadKind;
  open: boolean;
  onClose: () => void;
  onAdded: () => void;
}) {
  const isImage = kind === "image";
  const [groupTags, setGroupTags] = useState("");
  const [customTags, setCustomTags] = useState("");
  const [description, setDescription] = useState("");
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement | null>(null);

  const reset = () => {
    setGroupTags("");
    setCustomTags("");
    setDescription("");
    setError("");
    if (fileRef.current) fileRef.current.value = "";
  };

  const submit = async () => {
    const files = Array.from(fileRef.current?.files || []);
    if (!files.length) {
      setError("请选择文件");
      return;
    }
    setUploading(true);
    setError("");
    try {
      const meta = { group_tags: groupTags, custom_tags: customTags, description };
      const upload = isImage ? materialsApi.uploadImage : materialsApi.uploadVideo;
      for (const file of files) {
        await upload(file, meta);
      }
      reset();
      onAdded();
      onClose();
    } catch (err: any) {
      setError(err?.message || "上传失败");
    } finally {
      setUploading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(value) => !value && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>添加{isImage ? "图片" : "视频"}素材</DialogTitle>
          <DialogDescription>文件会复制到项目 data/materials/ 目录统一管理,并自动识别{isImage ? "尺寸与比例" : "尺寸与时长"}。</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <label className="text-xs font-medium text-muted-foreground">选择文件{!isImage ? "" : "(可多选)"}</label>
          <input
            ref={fileRef}
            type="file"
            multiple={isImage}
            accept={isImage ? "image/png,image/jpeg,image/webp,image/gif,image/bmp" : "video/mp4,video/mov,video/mkv,video/avi,video/webm,video/x-m4v"}
            className="voice-input py-1.5"
          />
          <label className="text-xs font-medium text-muted-foreground">分组标签(逗号分隔)</label>
          <input value={groupTags} onChange={(event) => setGroupTags(event.target.value)} className="voice-input" placeholder="如 场景, 空间站" />
          <label className="text-xs font-medium text-muted-foreground">自定义标签(逗号分隔)</label>
          <input value={customTags} onChange={(event) => setCustomTags(event.target.value)} className="voice-input" placeholder="如 测试, 精选" />
          <label className="text-xs font-medium text-muted-foreground">描述</label>
          <textarea value={description} onChange={(event) => setDescription(event.target.value)} className="voice-input min-h-16 resize-none" placeholder="素材内容描述,便于后续按描述模糊搜索" />
          {error && <p className="text-sm text-destructive">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={uploading}>取消</Button>
          <Button onClick={() => void submit()} disabled={uploading}>
            <Upload className="mr-1.5 h-4 w-4" />
            {uploading ? "上传中…" : "上传"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

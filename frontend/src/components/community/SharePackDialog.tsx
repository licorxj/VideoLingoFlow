import { useCallback, useEffect, useRef, useState } from "react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Camera, Upload, Loader2, CheckCircle2, ExternalLink, ImageOff } from "lucide-react";
import type { PublishResult } from "@/api/community";

export interface SharePackFields {
  shareName: string;
  description: string;
  author: string;
  category: string;
  tags: string[];
}

interface SharePackDialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  initialName: string;
  initialDescription: string;
  initialCategory?: string;
  /** 自动填充的作者名（社区已注册身份），可手动修改。 */
  initialAuthor?: string;
  categories: { value: string; label: string }[];
  /** 生成快照图（节点卡片 / 工作流画布）。 */
  previewProvider: () => Promise<File | null>;
  /** 提交打包并发布，成功后返回结果（含社区 URL）。 */
  onSubmit: (fields: SharePackFields, preview: File | null) => Promise<PublishResult>;
}

export default function SharePackDialog({
  open, onClose, title, initialName, initialDescription, initialCategory, initialAuthor, categories, previewProvider, onSubmit,
}: SharePackDialogProps) {
  const [shareName, setShareName] = useState("");
  const [description, setDescription] = useState("");
  const [author, setAuthor] = useState("");
  const [category, setCategory] = useState(categories[0]?.value || "");
  const [tagsText, setTagsText] = useState("");

  const [preview, setPreview] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string>("");
  const [snapshoting, setSnapshoting] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<PublishResult | null>(null);

  const fileRef = useRef<HTMLInputElement>(null);
  const previewUrlRef = useRef<string>("");

  const releasePreviewUrl = useCallback(() => {
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current);
      previewUrlRef.current = "";
    }
  }, []);

  const applyPreviewFile = useCallback((file: File | null) => {
    releasePreviewUrl();
    setPreview(file);
    if (file) {
      const url = URL.createObjectURL(file);
      previewUrlRef.current = url;
      setPreviewUrl(url);
    } else {
      setPreviewUrl("");
    }
  }, [releasePreviewUrl]);

  const takeSnapshot = useCallback(async () => {
    setSnapshoting(true);
    setError("");
    try {
      const file = await previewProvider();
      if (file) applyPreviewFile(file);
      else setError("截图失败，请上传自定义图片");
    } catch {
      setError("截图失败，请上传自定义图片");
    } finally {
      setSnapshoting(false);
    }
  }, [previewProvider, applyPreviewFile]);

  useEffect(() => {
    if (open) {
      setShareName(initialName);
      setDescription(initialDescription);
      setAuthor(initialAuthor || "");
      setCategory(initialCategory && categories.some((c) => c.value === initialCategory) ? initialCategory : (categories[0]?.value || ""));
      setTagsText("");
      setResult(null);
      setError("");
      takeSnapshot();
    }
    return () => releasePreviewUrl();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const handleUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] || null;
    if (file) applyPreviewFile(file);
    e.target.value = "";
  };

  const handleSubmit = async () => {
    if (!shareName.trim()) {
      setError("请填写分享名称");
      return;
    }
    if (!preview) {
      setError("请先生成或上传一张预览图");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const tags = tagsText
        .split(/[,，]/)
        .map((t) => t.trim())
        .filter(Boolean);
      const res = await onSubmit(
        { shareName: shareName.trim(), description: description.trim(), author: author.trim(), category, tags },
        preview
      );
      setResult(res);
    } catch (e: any) {
      setError(e?.message || "打包发布失败");
    } finally {
      setSubmitting(false);
    }
  };

  const handleClose = () => {
    if (submitting) return;
    setResult(null);
    onClose();
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) handleClose(); }}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>填写分享信息并生成预览图，打包后发布到共享社区。</DialogDescription>
        </DialogHeader>

        {result ? (
          <div className="space-y-4 py-2">
            <div className="flex flex-col items-center gap-3 rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-6 text-center">
              <CheckCircle2 className="w-10 h-10 text-emerald-500" />
              <div className="text-sm font-semibold">发布成功！</div>
              <div className="text-xs text-muted-foreground break-all max-w-full">{result.url}</div>
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={handleClose}>完成</Button>
              <Button
                onClick={() => window.open(window.location.origin + "/community", "_blank")}
              >
                <ExternalLink className="w-3.5 h-3.5 mr-1.5" /> 去社区查看
              </Button>
            </div>
          </div>
        ) : (
          <div className="grid gap-4 py-1">
            {/* 预览图 */}
            <div>
              <div className="text-xs font-medium text-muted-foreground mb-1.5">预览图（快照附图）</div>
              <div className="relative aspect-video rounded-xl overflow-hidden border border-border bg-muted/40 flex items-center justify-center">
                {previewUrl ? (
                  <img src={previewUrl} alt="预览" className="w-full h-full object-cover" />
                ) : (
                  <div className="flex flex-col items-center gap-2 text-muted-foreground/60">
                    <ImageOff className="w-6 h-6" />
                    <span className="text-xs">暂无预览图</span>
                  </div>
                )}
                {snapshoting && (
                  <div className="absolute inset-0 bg-black/40 flex items-center justify-center">
                    <Loader2 className="w-6 h-6 text-white animate-spin" />
                  </div>
                )}
              </div>
              <div className="flex gap-2 mt-2">
                <Button type="button" variant="outline" size="sm" onClick={takeSnapshot} disabled={snapshoting}>
                  <Camera className="w-3.5 h-3.5 mr-1.5" /> 重新截图
                </Button>
                <Button type="button" variant="outline" size="sm" onClick={() => fileRef.current?.click()}>
                  <Upload className="w-3.5 h-3.5 mr-1.5" /> 上传图片
                </Button>
                {preview && (
                  <Button type="button" variant="ghost" size="sm" onClick={() => applyPreviewFile(null)}>
                    移除
                  </Button>
                )}
                <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={handleUpload} />
              </div>
            </div>

            {/* 表单 */}
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2">
                <label className="text-xs font-medium text-muted-foreground">分享名称 *</label>
                <Input value={shareName} onChange={(e) => setShareName(e.target.value)} placeholder="资源名称" className="mt-1" />
              </div>
              <div className="col-span-2">
                <label className="text-xs font-medium text-muted-foreground">描述说明</label>
                <Textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="介绍这个节点/工作流的用途…"
                  className="mt-1 min-h-[64px]"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground">作者</label>
                <Input value={author} onChange={(e) => setAuthor(e.target.value)} placeholder="你的昵称" className="mt-1" />
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground">分类</label>
                <Select value={category} onValueChange={setCategory}>
                  <SelectTrigger className="mt-1">
                    <SelectValue placeholder="选择分类" />
                  </SelectTrigger>
                  <SelectContent>
                    {categories.map((c) => (
                      <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="col-span-2">
                <label className="text-xs font-medium text-muted-foreground">标签（逗号分隔）</label>
                <Input value={tagsText} onChange={(e) => setTagsText(e.target.value)} placeholder="如：tts, 音频" className="mt-1" />
              </div>
            </div>

            {error && <div className="text-xs text-red-500">{error}</div>}

            <div className="flex justify-end gap-2 pt-1">
              <Button variant="outline" onClick={handleClose} disabled={submitting}>取消</Button>
              <Button onClick={handleSubmit} disabled={submitting || snapshoting}>
                {submitting && <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />}
                打包并发布
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownAZ,
  ArrowUpAZ,
  Check,
  Copy,
  Eye,
  File as FileIcon,
  FolderOpen,
  FolderPlus,
  FolderX,
  Image as ImageIcon,
  Loader2,
  Music2,
  Pencil,
  RefreshCw,
  Trash2,
  Upload,
  Video,
} from "lucide-react";
import {
  MATERIAL_FILE_KINDS,
  MATERIAL_FILE_SORTS,
  MaterialFileItem,
  MaterialFileListResult,
  MaterialFileQuery,
  formatFileSize,
  materialPreviewUrl,
  materialsApi,
} from "@/api/materials";
import client from "@/api/client";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EmptyState } from "@/components/shared/EmptyState";
import { LoadingState } from "@/components/shared/LoadingState";

const PAGE_SIZE = 24;

const KIND_ICONS: Record<string, typeof ImageIcon> = {
  image: ImageIcon,
  video: Video,
  audio: Music2,
  text: FileIcon,
  archive: FileIcon,
  other: FileIcon,
};

const KIND_COLORS: Record<string, string> = {
  image: "#74b9ff",
  video: "#55efc4",
  audio: "#a29bfe",
  text: "#ffeaa7",
  archive: "#fab1a0",
  other: "#b2bec3",
};

type Filters = { root: string; dir: string; search: string; kind: string; sort: string; order: string };

const EMPTY_FILTERS: Filters = { root: "all", dir: "", search: "", kind: "all", sort: "mtime", order: "desc" };

function errorText(error: any, fallback: string) {
  const detail = error?.response?.data?.detail ?? error?.message;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;
  return fallback;
}

function formatTime(value: string) {
  return value ? value.slice(0, 16).replace("T", " ") : "-";
}

function iconFor(kind: string) {
  const Icon = KIND_ICONS[kind] || FileIcon;
  return <Icon className="h-4 w-4 shrink-0" style={{ color: KIND_COLORS[kind] || KIND_COLORS.other }} />;
}

async function copyText(value: string) {
  try {
    await navigator.clipboard.writeText(value);
  } catch {
    const textarea = document.createElement("textarea");
    textarea.value = value;
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand("copy");
    document.body.removeChild(textarea);
  }
}

/** 预览弹窗:图片/视频/音频直接流式播放,文本读取内容,其它类型只展示路径信息。 */
function FilePreviewDialog({ item, onClose }: { item: MaterialFileItem; onClose: () => void }) {
  const [text, setText] = useState("");
  const [textError, setTextError] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!item.text_preview) return;
    let cancelled = false;
    client
      .get<{ content: string }>("/api/files/read", { params: { path: item.abs_path } })
      .then(({ data }) => !cancelled && setText(data.content))
      .catch((err) => !cancelled && setTextError(errorText(err, "文本读取失败")));
    return () => {
      cancelled = true;
    };
  }, [item]);

  const url = materialPreviewUrl(item.path, item.abs_path);

  return (
    <Dialog open onOpenChange={(value) => !value && onClose()}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {iconFor(item.kind)}
            <span className="truncate">{item.name}</span>
          </DialogTitle>
          <DialogDescription className="truncate">
            {item.root_label} · {item.dir || "根目录"} · {formatFileSize(item.size)} · {formatTime(item.mtime)}
            {item.registered ? " · 已登记为素材" : ""}
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[68vh] overflow-auto rounded-lg border border-border/60 bg-muted/30 p-2">
          {item.kind === "image" && <img src={url} alt={item.name} className="mx-auto max-h-[62vh] object-contain" />}
          {item.kind === "video" && <video src={url} controls autoPlay className="mx-auto max-h-[62vh] w-full bg-black/80" />}
          {item.kind === "audio" && <audio src={url} controls autoPlay className="mt-6 w-full" />}
          {item.text_preview && (
            <pre className="max-h-[62vh] overflow-auto whitespace-pre-wrap break-all p-3 text-xs leading-relaxed">{textError || text || "加载中…"}</pre>
          )}
          {!item.text_preview && item.kind !== "image" && item.kind !== "video" && item.kind !== "audio" && (
            <p className="p-6 text-center text-sm text-muted-foreground">该类型不支持在线预览，可复制路径后在本地打开。</p>
          )}
        </div>

        <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
          <span className="truncate font-mono">{item.path || item.abs_path}</span>
          <Button
            size="sm"
            variant="outline"
            className="ml-auto shrink-0"
            onClick={() => {
              void copyText(item.abs_path);
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1500);
            }}
          >
            {copied ? <Check className="mr-1 h-3.5 w-3.5 text-emerald-500" /> : <Copy className="mr-1 h-3.5 w-3.5" />}
            {copied ? "已复制" : "复制路径"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** 素材库「文件」标签页:浏览落盘目录内的真实文件并支持增删改查。 */
export function MaterialFilesPanel({ onChanged }: { onChanged: () => void }) {
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<MaterialFileListResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [previewTarget, setPreviewTarget] = useState<MaterialFileItem | null>(null);
  const [renameTarget, setRenameTarget] = useState<MaterialFileItem | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [mkdirOpen, setMkdirOpen] = useState(false);
  const [mkdirValue, setMkdirValue] = useState("");
  const debounceRef = useRef<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const load = useCallback(async (nextPage: number, nextFilters: Filters) => {
    setLoading(true);
    setError("");
    try {
      const params: MaterialFileQuery = {
        root: nextFilters.root,
        dir: nextFilters.dir || undefined,
        search: nextFilters.search || undefined,
        kind: nextFilters.kind === "all" ? undefined : nextFilters.kind,
        sort: nextFilters.sort,
        order: nextFilters.order,
        page: nextPage,
        page_size: PAGE_SIZE,
      };
      const { data: payload } = await materialsApi.files(params);
      setData(payload);
      setPage(payload.page);
    } catch (err) {
      setError(errorText(err, "文件列表加载失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => void load(1, filters), 300);
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current);
    };
  }, [filters, load]);

  const refresh = useCallback(
    (message = "") => {
      setNotice(message);
      void load(page, filters);
      onChanged();
    },
    [filters, load, onChanged, page],
  );

  const roots = data?.roots || [];
  const rootLabel = useMemo(() => {
    const map: Record<string, string> = {};
    for (const root of roots) map[root.key] = `${root.label}(${root.rel})`;
    return map;
  }, [roots]);

  const specificRoot = filters.root !== "all";
  const uploadRoot = specificRoot ? filters.root : "materials";
  const uploadDir = specificRoot ? filters.dir : "";

  const upload = async (files: FileList) => {
    const list = Array.from(files);
    if (!list.length) return;
    setBusy(true);
    setError("");
    setNotice("");
    let done = 0;
    const failed: string[] = [];
    for (const file of list) {
      try {
        await materialsApi.uploadFile(file, { root: uploadRoot, dir: uploadDir });
        done += 1;
      } catch (err) {
        failed.push(`${file.name}: ${errorText(err, "上传失败")}`);
      }
    }
    setBusy(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
    refresh(failed.length ? `已上传 ${done} 个文件,${failed.length} 个失败(${failed[0]})` : `已上传 ${done} 个文件`);
  };

  const rename = async () => {
    if (!renameTarget) return;
    const nextName = renameValue.trim();
    if (!nextName || nextName === renameTarget.name) {
      setRenameTarget(null);
      return;
    }
    setBusy(true);
    try {
      const { data: result } = await materialsApi.renameFile({ root: renameTarget.root, path: renameTarget.rel_path, new_name: nextName });
      setRenameTarget(null);
      refresh(result.updated_records?.length ? "已重命名，并同步更新素材登记路径" : "已重命名");
    } catch (err) {
      setError(errorText(err, "重命名失败"));
    } finally {
      setBusy(false);
    }
  };

  const createDir = async () => {
    const name = mkdirValue.trim();
    if (!name) return;
    setBusy(true);
    try {
      await materialsApi.createDir({ root: uploadRoot, dir: uploadDir, name });
      setMkdirOpen(false);
      setMkdirValue("");
      refresh(`已新建文件夹 ${name}`);
    } catch (err) {
      setError(errorText(err, "新建文件夹失败"));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (item: MaterialFileItem) => {
    const extra =
      item.registered_as === "image" || item.registered_as === "video"
        ? `\n该文件已登记为${item.registered_as === "video" ? "视频" : "图片"}素材,删除会同步移除对应登记记录。`
        : item.registered_as === "character"
          ? "\n该文件属于公共角色图集,删除后角色记录仍保留(图集会缺图),请谨慎操作。"
          : "";
    if (!confirm(`删除文件“${item.name}”?${extra}\n删除后不可恢复。`)) return;
    setBusy(true);
    try {
      const { data: result } = await materialsApi.deleteFile({ root: item.root, path: item.rel_path });
      refresh(result.removed_records?.length ? `已删除，并移除 ${result.removed_records.length} 条素材登记` : "已删除");
    } catch (err) {
      setError(errorText(err, "删除失败"));
    } finally {
      setBusy(false);
    }
  };

  const removeDir = async () => {
    if (!specificRoot || !filters.dir) return;
    if (!confirm(`删除目录“${filters.dir}”及其中的全部文件?\n删除后不可恢复。`)) return;
    setBusy(true);
    try {
      await materialsApi.deleteFile({ root: filters.root, path: filters.dir });
      setFilters({ ...filters, dir: "" });
      setNotice("已删除目录");
      onChanged();
    } catch (err) {
      setError(errorText(err, "删除目录失败"));
    } finally {
      setBusy(false);
    }
  };

  const totalPages = useMemo(() => Math.max(1, Math.ceil((data?.total || 0) / PAGE_SIZE)), [data?.total]);
  const hasFilter = filters.search || filters.kind !== "all" || filters.dir || specificRoot;
  const targetLabel = `${rootLabel[uploadRoot] || uploadRoot}${uploadDir ? ` / ${uploadDir}` : " / 根目录"}`;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button disabled={busy} title={`上传到 ${targetLabel}`} onClick={() => fileInputRef.current?.click()}>
          <Upload className="mr-1.5 h-4 w-4" />
          上传文件
        </Button>
        <input ref={fileInputRef} type="file" multiple className="hidden" onChange={(event) => event.target.files && void upload(event.target.files)} />
        <Button
          variant="outline"
          disabled={busy || filters.root === "characters"}
          title={filters.root === "characters" ? "角色图集目录由角色库维护，不支持手动新建" : `在 ${targetLabel} 内新建文件夹`}
          onClick={() => setMkdirOpen(true)}
        >
          <FolderPlus className="mr-1.5 h-4 w-4" />
          新建文件夹
        </Button>
        <div className="relative min-w-52 flex-1">
          <input
            value={filters.search}
            onChange={(event) => setFilters({ ...filters, search: event.target.value })}
            placeholder="搜索文件名或路径"
            className="voice-input"
          />
        </div>
        <select
          value={filters.root}
          onChange={(event) => setFilters({ ...filters, root: event.target.value, dir: "" })}
          className="voice-input h-10 w-44"
          title="存储位置"
        >
          <option value="all">全部存储位置</option>
          {roots.map((root) => (
            <option key={root.key} value={root.key} disabled={!root.exists}>
              {root.label}（{root.rel}）
            </option>
          ))}
        </select>
        {specificRoot && (
          <select
            value={filters.dir}
            onChange={(event) => setFilters({ ...filters, dir: event.target.value })}
            className="voice-input h-10 w-40"
            title="子目录"
          >
            <option value="">根目录</option>
            {(data?.dirs || []).map((dir) => (
              <option key={dir} value={dir}>{dir}</option>
            ))}
          </select>
        )}
        {specificRoot && filters.dir && (
          <Button size="sm" variant="outline" disabled={busy} onClick={() => void removeDir()} title="删除当前目录及其内容">
            <FolderX className="mr-1 h-3.5 w-3.5" />
            删除目录
          </Button>
        )}
        <select value={filters.kind} onChange={(event) => setFilters({ ...filters, kind: event.target.value })} className="voice-input h-10 w-32" title="文件类型">
          {MATERIAL_FILE_KINDS.map((kind) => (
            <option key={kind.value} value={kind.value}>{kind.label}</option>
          ))}
        </select>
        <select value={filters.sort} onChange={(event) => setFilters({ ...filters, sort: event.target.value })} className="voice-input h-10 w-32" title="排序字段">
          {MATERIAL_FILE_SORTS.map((sort) => (
            <option key={sort.value} value={sort.value}>{sort.label}</option>
          ))}
        </select>
        <Button
          variant="outline"
          size="icon"
          title={filters.order === "asc" ? "升序" : "降序"}
          onClick={() => setFilters({ ...filters, order: filters.order === "asc" ? "desc" : "asc" })}
        >
          {filters.order === "asc" ? <ArrowUpAZ className="h-4 w-4" /> : <ArrowDownAZ className="h-4 w-4" />}
        </Button>
        <Button variant="outline" disabled={loading} onClick={() => refresh()}>
          <RefreshCw className={`mr-1.5 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          刷新
        </Button>
      </div>

      {error && <p className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}
      {notice && !error && <p className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-2.5 text-sm text-emerald-600">{notice}</p>}

      <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
        <span>共 {data?.total ?? 0} 个文件</span>
        <span>·</span>
        <span>合计 {formatFileSize(data?.total_size || 0)}</span>
        {busy && (
          <span className="flex items-center gap-1 text-primary">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />处理中…
          </span>
        )}
      </div>

      <div className={`rounded-xl border border-border/60 bg-card/40 ${loading ? "opacity-60 transition-opacity" : ""}`}>
        {data?.items.length ? (
          <div className="divide-y divide-border/50">
            {data.items.map((item) => (
              <div key={`${item.root}/${item.rel_path}`} className="flex items-center gap-3 px-3 py-2 hover:bg-accent/40">
                {iconFor(item.kind)}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium" title={item.name}>{item.name}</span>
                    {item.registered && (
                      <span className="shrink-0 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary" title="已被素材库登记">
                        已登记
                      </span>
                    )}
                  </div>
                  <div className="truncate text-[11px] text-muted-foreground" title={item.path}>
                    {item.root_label} · {item.dir || "根目录"} · {item.kind_label}
                  </div>
                </div>
                <span className="hidden w-20 shrink-0 text-right text-xs text-muted-foreground sm:block">{formatFileSize(item.size)}</span>
                <span className="hidden w-32 shrink-0 text-xs text-muted-foreground md:block">{formatTime(item.mtime)}</span>
                <div className="flex shrink-0 items-center gap-1">
                  <button
                    type="button"
                    onClick={() => setPreviewTarget(item)}
                    className="flex items-center gap-1 rounded px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
                  >
                    <Eye className="h-3 w-3" />预览
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setRenameTarget(item);
                      setRenameValue(item.name);
                    }}
                    className="flex items-center gap-1 rounded px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
                  >
                    <Pencil className="h-3 w-3" />重命名
                  </button>
                  <button
                    type="button"
                    onClick={() => void remove(item)}
                    className="flex items-center gap-1 rounded px-2 py-1 text-xs text-destructive/80 hover:bg-destructive/10 hover:text-destructive"
                  >
                    <Trash2 className="h-3 w-3" />删除
                  </button>
                </div>
              </div>
            ))}
          </div>
        ) : loading ? (
          <LoadingState label="正在读取素材目录…" />
        ) : (
          <EmptyState
            icon={FolderOpen}
            title={hasFilter ? "当前条件下没有文件" : "素材目录为空"}
            detail="素材库落盘目录包含 data/materials(上传素材)、data/libraries(入库素材)与 data/characters(角色图集)。"
            action={hasFilter ? <Button variant="outline" onClick={() => setFilters(EMPTY_FILTERS)}>重置筛选</Button> : undefined}
          />
        )}
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => void load(page - 1, filters)}>上一页</Button>
          <span className="text-sm text-muted-foreground">{page} / {totalPages}</span>
          <Button size="sm" variant="outline" disabled={page >= totalPages} onClick={() => void load(page + 1, filters)}>下一页</Button>
        </div>
      )}

      {previewTarget && <FilePreviewDialog item={previewTarget} onClose={() => setPreviewTarget(null)} />}

      {renameTarget && (
        <Dialog open onOpenChange={(value) => !value && setRenameTarget(null)}>
          <DialogContent className="max-w-md">
            <DialogHeader>
              <DialogTitle>重命名</DialogTitle>
              <DialogDescription className="truncate">当前文件:{renameTarget.rel_path}</DialogDescription>
            </DialogHeader>
            <input
              autoFocus
              value={renameValue}
              onChange={(event) => setRenameValue(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && void rename()}
              className="voice-input"
              placeholder="新文件名（含扩展名）"
            />
            {(renameTarget.registered_as === "image" || renameTarget.registered_as === "video") && (
              <p className="text-xs text-muted-foreground">该文件已登记为素材，重命名会同步更新素材记录路径。</p>
            )}
            <DialogFooter>
              <Button variant="outline" onClick={() => setRenameTarget(null)} disabled={busy}>取消</Button>
              <Button onClick={() => void rename()} disabled={busy}>保存</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}

      {mkdirOpen && (
        <Dialog open onOpenChange={(value) => !value && setMkdirOpen(false)}>
          <DialogContent className="max-w-md">
            <DialogHeader>
              <DialogTitle>新建文件夹</DialogTitle>
              <DialogDescription>
                位置:{rootLabel[uploadRoot] || uploadRoot}{uploadDir ? ` / ${uploadDir}` : " / 根目录"}
              </DialogDescription>
            </DialogHeader>
            <input
              autoFocus
              value={mkdirValue}
              onChange={(event) => setMkdirValue(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && void createDir()}
              className="voice-input"
              placeholder="文件夹名称"
            />
            <DialogFooter>
              <Button variant="outline" onClick={() => setMkdirOpen(false)} disabled={busy}>取消</Button>
              <Button onClick={() => void createDir()} disabled={busy || !mkdirValue.trim()}>创建</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}

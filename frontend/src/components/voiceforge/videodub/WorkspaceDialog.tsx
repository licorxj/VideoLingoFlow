import { useCallback, useEffect, useState } from "react";
import { Film, FolderOpen, Loader2, Trash2 } from "lucide-react";
import { videodubApi, VideoDubWorkspaceSummary } from "@/api/videodub";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { loadWorkspace } from "./persistence";

function formatDate(value: string | null) {
  if (!value) return "—";
  const date = new Date(value.includes("T") ? value : value.replace(" ", "T"));
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(date);
}

/** 打开工程：列出后端已保存的配音工程，支持载入与删除。 */
export function WorkspaceDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [list, setList] = useState<VideoDubWorkspaceSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  const refresh = useCallback(() => {
    setLoading(true);
    setError("");
    videodubApi
      .list()
      .then((result) => setList(result.data.workspaces || []))
      .catch(() => setError("工程列表加载失败，请确认主后端已启动"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (open) refresh();
  }, [open, refresh]);

  const openWorkspace = async (id: string) => {
    setBusyId(id);
    setError("");
    const result = await loadWorkspace(id);
    setBusyId(null);
    if (result.ok) onOpenChange(false);
    else setError(result.error || "打开失败");
  };

  const removeWorkspace = async (workspace: VideoDubWorkspaceSummary) => {
    if (!window.confirm(`删除工程「${workspace.name}」？视频与音频文件将一并删除。`)) return;
    setBusyId(workspace.id);
    try {
      await videodubApi.remove(workspace.id);
      refresh();
    } finally {
      setBusyId(null);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>打开工程</DialogTitle>
          <DialogDescription>载入已保存的视频配音工程（字幕、轨道与配音片段）。</DialogDescription>
        </DialogHeader>

        <div className="max-h-[50vh] min-h-24 overflow-y-auto">
          {loading ? (
            <p className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              正在加载…
            </p>
          ) : error && !list.length ? (
            <p className="py-8 text-center text-sm text-destructive">{error}</p>
          ) : !list.length ? (
            <p className="py-8 text-center text-sm text-muted-foreground">还没有已保存的工程，先点击「保存工程」。</p>
          ) : (
            <ul className="space-y-1.5">
              {list.map((workspace) => (
                <li
                  key={workspace.id}
                  className="flex items-center gap-3 rounded-lg border border-border/60 bg-background px-3 py-2"
                >
                  <Film className="h-4 w-4 flex-none text-primary/70" />
                  <button
                    type="button"
                    onClick={() => void openWorkspace(workspace.id)}
                    disabled={busyId === workspace.id}
                    className="min-w-0 flex-1 text-left"
                    title="载入该工程"
                  >
                    <span className="block truncate text-sm font-medium">{workspace.name}</span>
                    <span className="mt-0.5 block truncate text-[11px] text-muted-foreground">
                      {workspace.video_name || "无视频"} · {workspace.subtitle_count} 条字幕 · {formatDate(workspace.updated_at)}
                    </span>
                  </button>
                  {busyId === workspace.id ? (
                    <Loader2 className="h-4 w-4 flex-none animate-spin text-muted-foreground" />
                  ) : (
                    <>
                      <Button size="sm" variant="outline" className="h-7 flex-none px-2 text-xs" onClick={() => void openWorkspace(workspace.id)}>
                        <FolderOpen className="mr-1 h-3 w-3" />
                        打开
                      </Button>
                      <button
                        type="button"
                        title="删除该工程"
                        onClick={() => void removeWorkspace(workspace)}
                        className="flex-none rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        {error && list.length ? <p className="mt-2 text-xs text-destructive">{error}</p> : null}
      </DialogContent>
    </Dialog>
  );
}

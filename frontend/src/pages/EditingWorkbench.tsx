import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Clapperboard, Download, ExternalLink, FilePlus2, FolderInput, Home, Loader2, Maximize2, RefreshCw, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import TaskImportDialog from "@/components/editor/TaskImportDialog";
import { type EditorSnapshot, editorApi } from "@/api/editor";
import { toast } from "@/pages/llm-router/toast";
import { PageBackground } from "@/components/shared/PageBackground";

const CUTIA_EDITOR_URL = "/cutia/zh/editor";
const TASK_PROJECT_BRIDGE_VERSION = 1;
type ProjectSaveState = "idle" | "saving" | "saved" | "failed" | "conflict" | "local-only";

export default function EditingWorkbench() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const taskId = searchParams.get("task");
  const blankProjectId = searchParams.get("blank");
  const workspaceId = taskId || blankProjectId;
  const [importOpen, setImportOpen] = useState(false);
  const [snapshot, setSnapshot] = useState<EditorSnapshot | null>(null);
  const [editorReady, setEditorReady] = useState(false);
  const [editorReadyVersion, setEditorReadyVersion] = useState(0);
  const [importStatus, setImportStatus] = useState("");
  const [projectSaveState, setProjectSaveState] = useState<ProjectSaveState>("idle");
  const [projectSaveMessage, setProjectSaveMessage] = useState("");
  const [conflictRevision, setConflictRevision] = useState<number | null>(null);
  const [updatingCutia, setUpdatingCutia] = useState(false);
  const frameRef = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    const handleMessage = (event: MessageEvent<unknown>) => {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") return;
      const message = event.data as { type?: string; version?: number; taskId?: string; message?: string; revision?: number; asset?: { name?: string } };
      if (message.type === "videolingo:editor-ready") {
        setEditorReady(true);
        setEditorReadyVersion((version) => version + 1);
      }
      if (message.type === "videolingo:export-uploading" && message.taskId === taskId) setImportStatus("导出完成，正在归档到任务输出目录…");
      if (message.type === "videolingo:export-uploaded") {
        if (message.taskId !== taskId) return;
        const fileName = message.asset?.name || "导出视频";
        setImportStatus(`已归档导出文件：${fileName}`);
        toast({ title: "导出已归档", description: `${fileName} 已保存到当前任务输出目录。`, variant: "success" });
      }
      if (message.type === "videolingo:export-upload-failed") {
        if (message.taskId !== taskId) return;
        setImportStatus("导出文件归档失败，本地下载仍可用。");
        toast({ title: "导出未归档", description: message.message || "归档请求失败，本地下载仍可用。", variant: "destructive", duration: 8000 });
      }
      if (message.version !== TASK_PROJECT_BRIDGE_VERSION) return;
      if (message.type === "videolingo:load-task-project-complete") setImportStatus("任务项目已加载到 Cutia。");
      if (message.type === "videolingo:load-task-project-failed") setImportStatus(message.message || "任务项目加载失败。");
      if (message.type === "videolingo:project-save-started") { setProjectSaveState("saving"); setProjectSaveMessage("正在保存到任务项目…"); }
      if (message.type === "videolingo:project-save-complete") { setProjectSaveState("saved"); setProjectSaveMessage(`已保存至修订版 ${message.revision ?? ""}`); setConflictRevision(null); }
      if (message.type === "videolingo:project-save-failed") { setProjectSaveState("failed"); setProjectSaveMessage(message.message || "保存任务项目失败。"); }
      if (message.type === "videolingo:project-save-conflict") { setProjectSaveState("conflict"); setConflictRevision(message.revision ?? null); setProjectSaveMessage("服务端项目已被其他修改更新。"); }
      if (message.type === "videolingo:project-save-local-only") { setProjectSaveState("local-only"); setProjectSaveMessage("当前修改仅保存在本地 Cutia 项目中。"); }
    };
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, []);

  useEffect(() => {
    if (!taskId) return;
    // #region debug-point B:parent-project-fetch
    fetch("http://127.0.0.1:7777/event", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sessionId: "cutia-project-load", runId: "pre-fix-2", hypothesisId: "B", location: "EditingWorkbench.tsx:project-effect", msg: "[DEBUG] Parent requesting project", data: { taskId, apiBase: window.location.origin }, ts: Date.now() }) }).catch(() => {});
    // #endregion
    editorApi.getProject(taskId).then((response) => {
      // #region debug-point B:parent-project-success
      fetch("http://127.0.0.1:7777/event", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sessionId: "cutia-project-load", runId: "pre-fix-2", hypothesisId: "B", location: "EditingWorkbench.tsx:project-effect", msg: "[DEBUG] Parent project received", data: { taskId, revision: response.data.revision, assetCount: response.data.assets.length }, ts: Date.now() }) }).catch(() => {});
      // #endregion
      setSnapshot(response.data);
    }).catch((error) => {
      // #region debug-point B:parent-project-failed
      fetch("http://127.0.0.1:7777/event", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sessionId: "cutia-project-load", runId: "pre-fix-2", hypothesisId: "B", location: "EditingWorkbench.tsx:project-effect", msg: "[DEBUG] Parent project request failed", data: { taskId, message: error instanceof Error ? error.message : String(error) }, ts: Date.now() }) }).catch(() => {});
      // #endregion
      setSnapshot(null);
    });
  }, [taskId]);

  const loadTaskProject = () => {
    if (!taskId || !snapshot || !frameRef.current?.contentWindow) return;
    setImportStatus("正在加载任务项目到 Cutia…");
    // #region debug-point A:parent-load-message
    fetch("http://127.0.0.1:7777/event", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sessionId: "cutia-project-load", runId: "pre-fix", hypothesisId: "A", location: "EditingWorkbench.tsx:loadTaskProject", msg: "[DEBUG] Parent sent task project", data: { taskId, revision: snapshot.revision, assetCount: snapshot.assets.length }, ts: Date.now() }) }).catch(() => {});
    // #endregion
    frameRef.current.contentWindow.postMessage({
      type: "videolingo:load-task-project",
      version: TASK_PROJECT_BRIDGE_VERSION,
      taskId,
      project: snapshot.project,
      assets: snapshot.assets,
      revision: snapshot.revision,
    }, window.location.origin);
  };

  useEffect(() => {
    if (editorReady && editorReadyVersion && snapshot) loadTaskProject();
  }, [editorReady, editorReadyVersion, snapshot]);

  const onImported = async (id: string) => {
    setSearchParams({ task: id });
    setImportStatus("");
    setProjectSaveState("idle");
    setProjectSaveMessage("");
    setConflictRevision(null);
    const response = await editorApi.getProject(id);
    setSnapshot(response.data);
  };

  const source = `${CUTIA_EDITOR_URL}/${encodeURIComponent(workspaceId || "videolingo-workspace")}`;

  const createBlankProject = () => {
    setEditorReady(false);
    setEditorReadyVersion(0);
    setSnapshot(null);
    setImportStatus("");
    setProjectSaveState("idle");
    setProjectSaveMessage("");
    setConflictRevision(null);
    setSearchParams({ blank: `blank-${crypto.randomUUID()}` });
  };

  const updateCutia = async () => {
    if (!window.confirm("更新前会检查本地改动、远端地址与分支，并创建备份分支。确认开始更新 Cutia？")) return;
    setUpdatingCutia(true);
    try {
      const response = await editorApi.updateCutia();
      const result = response.data;
      toast({ title: result.updated ? "Cutia 已更新" : "Cutia 已是最新版本", description: result.updated ? `${result.previous_revision} → ${result.current_revision}，备份分支：${result.backup_branch}` : result.message, variant: "success", duration: 8000 });
    } catch (error: any) {
      toast({ title: "Cutia 未更新", description: error?.response?.data?.message || "更新请求失败。", variant: "destructive", duration: 8000 });
    } finally {
      setUpdatingCutia(false);
    }
  };

  const reloadAfterConflict = async () => {
    if (!taskId) return;
    try {
      const response = await editorApi.getProject(taskId);
      setSnapshot(response.data);
      setProjectSaveState("idle");
      setProjectSaveMessage("正在重新加载服务端项目…");
      setConflictRevision(null);
    } catch {
      setProjectSaveState("failed");
      setProjectSaveMessage("无法重新加载服务端项目。");
    }
  };

  const requestSaveProject = () => {
    if (!taskId) {
      toast({ title: "空白项目", description: "空白项目仅保存在本地 Cutia 中，无需同步到任务项目。", variant: "default", duration: 3000 });
      return;
    }
    if (!editorReady || !frameRef.current?.contentWindow) return;
    setProjectSaveState("saving");
    setProjectSaveMessage("正在同步剪辑信息到任务项目…");
    frameRef.current.contentWindow.postMessage({ type: "videolingo:request-save", version: TASK_PROJECT_BRIDGE_VERSION, taskId }, window.location.origin);
  };

  const preserveLocalProject = () => {
    if (!taskId || !frameRef.current?.contentWindow) return;
    frameRef.current.contentWindow.postMessage({ type: "videolingo:preserve-local-project", version: TASK_PROJECT_BRIDGE_VERSION, taskId, revision: conflictRevision }, window.location.origin);
  };

  if (!workspaceId) {
    return <PageBackground tone="editing" className="h-full min-h-[560px] flex items-center justify-center"><div className="max-w-xl px-6 text-center"><div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-lg bg-primary/10 text-primary"><Clapperboard className="h-7 w-7" /></div><h1 className="text-2xl font-bold">剪辑工作台</h1><p className="mt-2 text-sm leading-6 text-muted-foreground">使用原始 Cutia 编辑器制作新视频，或导入历史任务的成片、配音、字幕和封面继续精剪。</p><div className="mt-7 grid gap-3 sm:grid-cols-2"><Button className="h-11" onClick={() => setImportOpen(true)}><FolderInput className="mr-2 h-4 w-4" />导入历史项目</Button><Button className="h-11" variant="outline" onClick={createBlankProject}><FilePlus2 className="mr-2 h-4 w-4" />新建空白项目</Button></div></div><TaskImportDialog open={importOpen} onOpenChange={setImportOpen} onImported={onImported} /></PageBackground>;
  }

  return <PageBackground tone="editing" className="flex h-full min-h-0 flex-col overflow-hidden p-3 sm:p-4">
    <div className="flex h-auto min-h-11 shrink-0 flex-wrap items-center gap-2 border-b px-3 py-1"><div className="flex min-w-0 items-center gap-2"><Clapperboard className="h-4 w-4 text-primary" /><span className="truncate text-sm font-medium">剪辑工作台 · {taskId ? `任务 ${taskId}` : "空白项目"}</span></div><span className="hidden text-xs text-muted-foreground md:block">{projectSaveMessage || importStatus || (editorReady ? "原始 Cutia 编辑器已就绪" : "正在加载原始 Cutia 编辑器…")}</span>{taskId && projectSaveState === "saving" && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}{taskId && projectSaveState === "saved" && <Save className="h-3.5 w-3.5 text-success" />}{projectSaveState === "conflict" && <div className="flex items-center gap-1"><Button variant="outline" size="sm" onClick={reloadAfterConflict}><RefreshCw className="mr-1.5 h-3.5 w-3.5" />重新加载</Button><Button variant="outline" size="sm" onClick={preserveLocalProject}>保留本地修改</Button></div>}<div className="ml-auto flex items-center gap-1"><Button variant="ghost" size="sm" disabled={!taskId || !editorReady} onClick={requestSaveProject}><Save className="mr-1.5 h-4 w-4" />保存</Button><Button variant="ghost" size="sm" onClick={() => navigate("/editing")}><Home className="mr-1.5 h-4 w-4" />返回首页</Button><Button variant="ghost" size="sm" onClick={() => setImportOpen(true)}><FolderInput className="mr-1.5 h-4 w-4" />导入任务</Button><Button variant="ghost" size="sm" disabled={updatingCutia} onClick={updateCutia}>{updatingCutia ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Download className="mr-1.5 h-4 w-4" />}更新 Cutia</Button><Button variant="ghost" size="sm" onClick={() => window.open("https://github.com/msgbyte/cutia", "_blank", "noopener,noreferrer")}><ExternalLink className="mr-1.5 h-4 w-4" />访问 Cutia 开源项目</Button><Button variant="ghost" size="icon" title="重新加载项目" disabled={!editorReady || !snapshot} onClick={loadTaskProject}><RefreshCw className="h-4 w-4" /></Button><Button variant="ghost" size="icon" title="在独立窗口打开 Cutia" onClick={() => window.open(source, "_blank", "noopener,noreferrer")}><Maximize2 className="h-4 w-4" /></Button></div></div>
    <div className="relative min-h-0 flex-1 overflow-hidden rounded-lg border shadow-sm">{!editorReady && <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center bg-background/70"><div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />加载 Cutia 编辑器</div></div>}<iframe ref={frameRef} key={source} src={source} title="Cutia video editor" className="h-full w-full border-0" allow="clipboard-read; clipboard-write; fullscreen" onLoad={() => setEditorReady(true)} /></div>
    <TaskImportDialog open={importOpen} onOpenChange={setImportOpen} onImported={onImported} />
  </PageBackground>;
}

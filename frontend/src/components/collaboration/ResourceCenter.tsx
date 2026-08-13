import { useCallback, useEffect, useRef, useState } from "react";
import { Download, FolderOpen, FolderPlus, HardDrive, RefreshCw, Trash2, Upload, ChevronRight } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useAlert } from "@/components/ui/AlertProvider";
import { useProjectStore } from "@/stores/projectStore";
import { listControlProjects } from "@/api/controlPlane";
import {
  assetDownloadUrl, deleteAsset, formatBytes, listAssets, listProjectTasks, listTaskFiles, taskFileDownloadUrl, uploadAsset,
  type ControlAsset, type WorkspaceFileEntry,
} from "@/api/collaboration";

const ASSET_KINDS = [
  { value: "all", label: "全部类型" },
  { value: "project", label: "项目素材" },
  { value: "task", label: "任务产物" },
  { value: "export", label: "导出文件" },
  { value: "checkpoint", label: "检查点" },
];

export default function ResourceCenter() {
  const { alert, confirm } = useAlert();
  const { projects, currentProjectId, setProjects, setCurrentProjectId } = useProjectStore();
  const [kindFilter, setKindFilter] = useState("all");
  const [assets, setAssets] = useState<ControlAsset[]>([]);
  const [uploadKind, setUploadKind] = useState("project");
  const [uploading, setUploading] = useState(false);
  const [fileInputKey, setFileInputKey] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // 工作区文件
  const [tasks, setTasks] = useState<{ id: string; status: string; name: string }[]>([]);
  const [taskId, setTaskId] = useState("");
  const [filePath, setFilePath] = useState("");
  const [entries, setEntries] = useState<WorkspaceFileEntry[]>([]);

  useEffect(() => {
    if (projects.length === 0) {
      listControlProjects().then(setProjects).catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadAssets = useCallback(async (projectId: string) => {
    try {
      setAssets(await listAssets(projectId, kindFilter === "all" ? undefined : kindFilter));
    } catch {
      setAssets([]);
    }
  }, [kindFilter]);

  const loadWorkspace = useCallback(async (projectId: string, task: string, path: string) => {
    if (!task) {
      setEntries([]);
      return;
    }
    try {
      const data = await listTaskFiles(projectId, task, path);
      setEntries(data.entries);
    } catch {
      setEntries([]);
    }
  }, []);

  useEffect(() => {
    if (!currentProjectId) return;
    loadAssets(currentProjectId);
    listProjectTasks(currentProjectId).then(setTasks).catch(() => setTasks([]));
  }, [currentProjectId, loadAssets]);

  const refreshAll = () => {
    if (currentProjectId) {
      loadAssets(currentProjectId);
      loadWorkspace(currentProjectId, taskId, filePath);
    }
  };

  const handleUpload = async (file: File | undefined) => {
    if (!file || !currentProjectId) return;
    setUploading(true);
    try {
      await uploadAsset(currentProjectId, uploadKind, file.name, file);
      alert(`已上传 ${file.name}`, "success");
      await loadAssets(currentProjectId);
    } catch (error: any) {
      alert(error?.message || "上传失败", "error");
    } finally {
      setUploading(false);
      setFileInputKey((k) => k + 1);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleDelete = async (asset: ControlAsset) => {
    if (!(await confirm(`确认删除资产「${asset.metadata?.original_name || asset.object_key}」？`))) return;
    try {
      await deleteAsset(asset.id);
      alert("已删除", "success");
      await loadAssets(currentProjectId!);
    } catch (error: any) {
      alert(error?.message || "删除失败", "error");
    }
  };

  const enterDir = (entry: WorkspaceFileEntry) => {
    if (!entry.is_dir) return;
    const next = filePath ? `${filePath}/${entry.name}` : entry.name;
    setFilePath(next);
    if (currentProjectId) loadWorkspace(currentProjectId, taskId, next);
  };

  const goUp = () => {
    const next = filePath.includes("/") ? filePath.slice(0, filePath.lastIndexOf("/")) : "";
    setFilePath(next);
    if (currentProjectId) loadWorkspace(currentProjectId, taskId, next);
  };

  return (
    <div className="space-y-4">
      {/* 项目选择 */}
      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 py-3">
          <span className="text-sm font-medium text-muted-foreground">当前项目：</span>
          <Select value={currentProjectId || ""} onValueChange={(value) => setCurrentProjectId(value || null)}>
            <SelectTrigger className="w-64">
              <SelectValue placeholder="未选择项目" />
            </SelectTrigger>
            <SelectContent>
              {projects.map((project) => <SelectItem key={project.id} value={project.id}>{project.name}</SelectItem>)}
            </SelectContent>
          </Select>
          <Button variant="outline" size="sm" onClick={refreshAll}><RefreshCw className="h-3.5 w-3.5" />刷新</Button>
          <p className="text-xs text-muted-foreground">资源均存储在主机，成员按项目权限访问</p>
        </CardContent>
      </Card>

      {!currentProjectId ? (
        <Card>
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            <HardDrive className="mx-auto mb-2 h-8 w-8 text-muted-foreground/40" />
            请先选择项目，或让管理员将你加入项目
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {/* 资产库 */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-base"><FolderOpen className="h-4 w-4 text-primary" />项目资产库</CardTitle>
              <CardDescription>上传 / 下载 / 删除项目共享资产（素材、产物、导出文件）</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <Select value={uploadKind} onValueChange={setUploadKind}>
                  <SelectTrigger className="w-32 h-8 text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="project">项目素材</SelectItem>
                    <SelectItem value="task">任务产物</SelectItem>
                    <SelectItem value="export">导出文件</SelectItem>
                  </SelectContent>
                </Select>
                <Select value={kindFilter} onValueChange={(v) => { setKindFilter(v); }} >
                  <SelectTrigger className="w-28 h-8 text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {ASSET_KINDS.map((kind) => <SelectItem key={kind.value} value={kind.value}>{kind.label}</SelectItem>)}
                  </SelectContent>
                </Select>
                <input
                  key={fileInputKey}
                  ref={fileInputRef}
                  type="file"
                  className="hidden"
                  onChange={(e) => handleUpload(e.target.files?.[0])}
                />
                <Button size="sm" disabled={uploading} onClick={() => fileInputRef.current?.click()}>
                  <Upload className="h-3.5 w-3.5" />{uploading ? "上传中..." : "上传资产"}
                </Button>
              </div>
              <div className="max-h-80 space-y-1.5 overflow-y-auto">
                {assets.length === 0 && <p className="py-6 text-center text-xs text-muted-foreground">暂无资产</p>}
                {assets.map((asset) => (
                  <div key={asset.id} className="flex items-center gap-2 rounded-lg border border-border px-2.5 py-1.5">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-medium">{asset.metadata?.original_name || asset.object_key.split("/").pop()}</p>
                      <p className="font-mono text-[10px] text-muted-foreground">
                        {asset.kind} · {formatBytes(asset.size_bytes)}
                        {asset.expires_at && ` · ${new Date(asset.expires_at).toLocaleDateString()} 过期`}
                      </p>
                    </div>
                    <a href={assetDownloadUrl(asset.id)} className="text-muted-foreground hover:text-primary" title="下载">
                      <Download className="h-4 w-4" />
                    </a>
                    <button onClick={() => handleDelete(asset)} className="text-muted-foreground hover:text-destructive" title="删除">
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* 工作区文件 */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-base"><FolderPlus className="h-4 w-4 text-primary" />任务工作区文件</CardTitle>
              <CardDescription>浏览并下载主机上任务的产物文件（只读）</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <Select value={taskId} onValueChange={(value) => { setTaskId(value); setFilePath(""); loadWorkspace(currentProjectId, value, ""); }}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="选择任务" />
                </SelectTrigger>
                <SelectContent>
                  {tasks.map((task) => <SelectItem key={task.id} value={task.id}>{task.name} · {task.status}</SelectItem>)}
                </SelectContent>
              </Select>
              {taskId && (
                <div className="flex items-center gap-1 text-xs text-muted-foreground">
                  <button onClick={goUp} className="rounded border border-border px-1.5 py-0.5 hover:bg-muted">返回上级</button>
                  <span className="truncate font-mono">{filePath || "（根目录）"}</span>
                </div>
              )}
              <div className="max-h-80 space-y-1 overflow-y-auto">
                {!taskId && <p className="py-6 text-center text-xs text-muted-foreground">请先选择任务</p>}
                {taskId && entries.length === 0 && filePath === "" && <p className="py-6 text-center text-xs text-muted-foreground">该任务工作区为空</p>}
                {entries.map((entry) => (
                  <div key={entry.path} className="flex items-center gap-2 rounded-lg border border-border px-2.5 py-1.5">
                    <button
                      onClick={() => enterDir(entry)}
                      disabled={!entry.is_dir}
                      className="min-w-0 flex-1 truncate text-left text-xs font-medium disabled:cursor-default"
                    >
                      {entry.is_dir ? <FolderOpen className="mr-1 inline h-3.5 w-3.5 text-sky-500" /> : <ChevronRight className="mr-1 inline h-3.5 w-3.5 text-muted-foreground" />}
                      {entry.name}
                    </button>
                    {!entry.is_dir && (
                      <>
                        <span className="font-mono text-[10px] text-muted-foreground">{formatBytes(entry.size_bytes)}</span>
                        <a href={taskFileDownloadUrl(currentProjectId, taskId, entry.path)} className="text-muted-foreground hover:text-primary" title="下载">
                          <Download className="h-4 w-4" />
                        </a>
                      </>
                    )}
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}

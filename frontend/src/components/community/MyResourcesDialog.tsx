import { useCallback, useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Box, Workflow as WorkflowIcon, Package, Loader2, Share2, FolderArchive } from "lucide-react";
import { listNodeTypes, type NodeTypeConfig } from "@/api/nodeTypes";
import client from "@/api/client";
import { CATEGORIES } from "@/lib/workflowTypes";
import {
  packNode, packWorkflow, publishPackage, listPackages,
  type CommunityPackage, type PublishResult, type CommunityUser,
} from "@/api/community";
import { captureNodeCard, captureWorkflowCard } from "@/lib/snapshot";
import SharePackDialog, { type SharePackFields } from "./SharePackDialog";
import { useAlert } from "@/components/ui/AlertProvider";

const WORKFLOW_SHARE_CATEGORIES = [
  { value: "通用工作流", label: "通用工作流" },
  { value: "视频处理", label: "视频处理" },
  { value: "字幕处理", label: "字幕处理" },
  { value: "AI 处理", label: "AI 处理" },
  { value: "多平台发布", label: "多平台发布" },
  { value: "工具工作流", label: "工具工作流" },
];

type TabKey = "all" | "node" | "workflow";

interface WorkflowSummary {
  id: string;
  name: string;
  description: string;
  updatedAt: string;
}

function formatDate(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.getFullYear() + "/" + (d.getMonth() + 1) + "/" + d.getDate();
}

export default function MyResourcesDialog({ open, onClose, user }: { open: boolean; onClose: () => void; user: CommunityUser | null }) {
  const { alert } = useAlert();
  const [tab, setTab] = useState<TabKey>("all");
  const [nodes, setNodes] = useState<NodeTypeConfig[]>([]);
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([]);
  const [packages, setPackages] = useState<CommunityPackage[]>([]);
  const [loading, setLoading] = useState(false);

  const [packNodeTarget, setPackNodeTarget] = useState<NodeTypeConfig | null>(null);
  const [packWfTarget, setPackWfTarget] = useState<WorkflowSummary | null>(null);
  const [publishingId, setPublishingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [nodeList, wfRes, pkgList] = await Promise.all([
        listNodeTypes(),
        client.get("/api/workflows"),
        listPackages(),
      ]);
      setNodes(nodeList);
      setWorkflows(wfRes.data.workflows || []);
      setPackages(pkgList);
    } catch (e: any) {
      alert(e?.message || "加载本地资源失败", "error");
    } finally {
      setLoading(false);
    }
  }, [alert]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  /* ---------- 打包并发布：节点 ---------- */
  const handleNodeSubmit = async (fields: SharePackFields, preview: File | null): Promise<PublishResult> => {
    if (!packNodeTarget) throw new Error("未选择节点");
    const form = new FormData();
    form.append("nodeId", packNodeTarget.id);
    form.append("shareName", fields.shareName);
    form.append("description", fields.description);
    form.append("author", fields.author);
    form.append("category", fields.category);
    form.append("tags", JSON.stringify(fields.tags));
    if (preview) form.append("preview", preview);
    const packed = await packNode(form);
    return publishPackage(packed.folder);
  };

  /* ---------- 打包并发布：工作流 ---------- */
  const handleWorkflowSubmit = async (fields: SharePackFields, preview: File | null): Promise<PublishResult> => {
    if (!packWfTarget) throw new Error("未选择工作流");
    const res = await client.get(`/api/workflows/${packWfTarget.id}`);
    const wf = res.data.workflow || {};
    const form = new FormData();
    form.append("workflow", JSON.stringify({ ...wf, name: fields.shareName, description: fields.description }));
    form.append("shareName", fields.shareName);
    form.append("description", fields.description);
    form.append("author", fields.author);
    form.append("category", fields.category);
    form.append("tags", JSON.stringify(fields.tags));
    if (preview) form.append("preview", preview);
    const packed = await packWorkflow(form);
    return publishPackage(packed.folder);
  };

  /* ---------- 已打包资源：直接发布 ---------- */
  const handlePublishPacked = async (pkg: CommunityPackage) => {
    setPublishingId(pkg.folder);
    try {
      const res = await publishPackage(pkg.folder);
      alert(`已发布到社区（${pkg.name}）`, "success");
      void res;
    } catch (e: any) {
      alert(e?.message || "发布失败", "error");
    } finally {
      setPublishingId(null);
    }
  };

  /* ---------- 工作流全貌预览：取真实工作流数据渲染全貌高清图 ---------- */
  const workflowPreviewProvider = useCallback(async (): Promise<File | null> => {
    if (!packWfTarget) return null;
    try {
      const res = await client.get(`/api/workflows/${packWfTarget.id}`);
      const wf = res.data.workflow || {};
      return captureWorkflowCard(wf as any);
    } catch {
      return captureWorkflowCard({ name: packWfTarget.name, nodes: [], edges: [] } as any);
    }
  }, [packWfTarget]);

  const showNodes = tab === "all" || tab === "node";
  const showWorkflows = tab === "all" || tab === "workflow";
  const nodeCategories = Object.entries(CATEGORIES).map(([value, meta]) => ({ value, label: meta.label }));
  const hasShareable = (showNodes && nodes.length > 0) || (showWorkflows && workflows.length > 0);

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Package className="w-4 h-4 text-primary" /> 分享我的资源
          </DialogTitle>
          <DialogDescription>筛选并打包本地的节点与工作流，发布到共享社区。</DialogDescription>
        </DialogHeader>

        {/* 资源类型筛选 */}
        <div className="flex rounded-lg bg-muted p-1 w-fit">
          {([["all", "全部"], ["node", "节点"], ["workflow", "工作流"]] as [TabKey, string][]).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={cn(
                "px-3 py-1.5 text-xs font-medium rounded-md transition-colors",
                tab === key ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
              )}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="overflow-y-auto max-h-[55vh] space-y-5 pr-1">
          {loading ? (
            <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin text-primary" /></div>
          ) : (
            <>
              {/* 可分享的资源 */}
              <div>
                <h4 className="text-xs font-bold text-muted-foreground mb-2 flex items-center gap-1.5">
                  <Share2 className="w-3 h-3" /> 可分享的资源
                </h4>
                {showNodes && nodes.length > 0 && (
                  <div className="space-y-1.5">
                    {nodes.map((node) => (
                      <div key={node.id} className="flex items-center gap-2.5 rounded-lg border border-border/60 bg-card/50 px-3 py-2">
                        <div className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0" style={{ backgroundColor: (node.color || "#6b7280") + "20" }}>
                          <Box className="w-3.5 h-3.5" style={{ color: node.color || "#6b7280" }} />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-medium truncate">{node.name}</div>
                          <div className="text-[11px] text-muted-foreground truncate">
                            {CATEGORIES[node.category as keyof typeof CATEGORIES]?.label || node.category}
                            {node.isBuiltIn ? "" : " · 自定义"}
                          </div>
                        </div>
                        <Button size="sm" variant="outline" onClick={() => setPackNodeTarget(node)}>
                          <Share2 className="w-3 h-3 mr-1" /> 打包分享
                        </Button>
                      </div>
                    ))}
                  </div>
                )}
                {showWorkflows && workflows.length > 0 && (
                  <div className="space-y-1.5 mt-1.5">
                    {workflows.map((wf) => (
                      <div key={wf.id} className="flex items-center gap-2.5 rounded-lg border border-border/60 bg-card/50 px-3 py-2">
                        <div className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0" style={{ backgroundColor: "#6366f1" + "20" }}>
                          <WorkflowIcon className="w-3.5 h-3.5 text-indigo-400" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-medium truncate">{wf.name}</div>
                          <div className="text-[11px] text-muted-foreground truncate">{wf.description || "工作流"}</div>
                        </div>
                        <Button size="sm" variant="outline" onClick={() => setPackWfTarget(wf)}>
                          <Share2 className="w-3 h-3 mr-1" /> 打包分享
                        </Button>
                      </div>
                    ))}
                  </div>
                )}
                {!hasShareable && (
                  <div className="text-xs text-muted-foreground/60 py-6 text-center">当前类型下没有可分享的资源</div>
                )}
              </div>

              {/* 已打包的资源 */}
              <div>
                <h4 className="text-xs font-bold text-muted-foreground mb-2 flex items-center gap-1.5">
                  <FolderArchive className="w-3 h-3" /> 已打包（{packages.length}）
                </h4>
                {packages.length === 0 ? (
                  <div className="text-xs text-muted-foreground/60 py-4 text-center">暂无已打包的本地包</div>
                ) : (
                  <div className="space-y-1.5">
                    {packages.map((pkg) => (
                      <div key={pkg.folder} className="flex items-center gap-2.5 rounded-lg border border-border/60 bg-card/50 px-3 py-2">
                        <div className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0" style={{ backgroundColor: (pkg.type === "node" ? "#8b5cf6" : "#6366f1") + "20" }}>
                          {pkg.type === "node"
                            ? <Box className="w-3.5 h-3.5 text-violet-400" />
                            : <WorkflowIcon className="w-3.5 h-3.5 text-indigo-400" />}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-medium truncate">{pkg.name || pkg.resourceId}</div>
                          <div className="text-[11px] text-muted-foreground">
                            {pkg.type === "node" ? "节点" : "工作流"} · {pkg.files.length} 个文件 · {formatDate(pkg.createdAt)}
                          </div>
                        </div>
                        <Button
                          size="sm"
                          onClick={() => handlePublishPacked(pkg)}
                          disabled={publishingId === pkg.folder}
                        >
                          {publishingId === pkg.folder && <Loader2 className="w-3 h-3 mr-1 animate-spin" />}
                          发布到社区
                        </Button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        {/* 节点打包分享 */}
        <SharePackDialog
          open={!!packNodeTarget}
          onClose={() => setPackNodeTarget(null)}
          title={"分享打包节点：" + (packNodeTarget?.name || "")}
          initialName={packNodeTarget?.name || ""}
          initialDescription={packNodeTarget?.description || ""}
          initialCategory={packNodeTarget?.category}
          initialAuthor={user?.name || ""}
          categories={nodeCategories}
          previewProvider={() => captureNodeCard(packNodeTarget ?? undefined)}
          onSubmit={handleNodeSubmit}
        />

        {/* 工作流打包分享 */}
        <SharePackDialog
          open={!!packWfTarget}
          onClose={() => setPackWfTarget(null)}
          title={"分享打包工作流：" + (packWfTarget?.name || "")}
          initialName={packWfTarget?.name || ""}
          initialDescription={packWfTarget?.description || ""}
          initialAuthor={user?.name || ""}
          categories={WORKFLOW_SHARE_CATEGORIES}
          previewProvider={workflowPreviewProvider}
          onSubmit={handleWorkflowSubmit}
        />
      </DialogContent>
    </Dialog>
  );
}

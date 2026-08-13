import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Loader2, Download, AlertCircle } from "lucide-react";
import {
  downloadResource, blobToFile, analyzeWorkflowPackage, importWorkflowPackage,
  type CommunityResource, type WorkflowAnalysis, type NodeImportAction,
} from "@/api/community";

const STATUS_META: Record<string, { label: string; cls: string }> = {
  new: { label: "新装", cls: "text-blue-600 dark:text-blue-400 bg-blue-500/10 border-blue-500/20" },
  upgrade: { label: "升级", cls: "text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 border-emerald-500/20" },
  downgrade: { label: "降级", cls: "text-amber-600 dark:text-amber-400 bg-amber-500/10 border-amber-500/20" },
  same: { label: "同版本", cls: "text-orange-600 dark:text-orange-400 bg-orange-500/10 border-orange-500/20" },
  different: { label: "版本差异", cls: "text-orange-600 dark:text-orange-400 bg-orange-500/10 border-orange-500/20" },
};

export default function WorkflowImportPanel({ resource, baseUrl, onSuccess, onCancel }: {
  resource: CommunityResource;
  baseUrl: string;
  onSuccess: (msg: string) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(resource.name);
  const [analyzing, setAnalyzing] = useState(true);
  const [analysis, setAnalysis] = useState<WorkflowAnalysis | null>(null);
  const [decisions, setDecisions] = useState<Record<string, { action: NodeImportAction; renameTo: string }>>({});
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState("");
  const [file, setFile] = useState<File | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const blob = await downloadResource(baseUrl, resource.id);
        const f = blobToFile(blob, `workflow_${resource.name}.zip`);
        const a = await analyzeWorkflowPackage(f);
        if (cancelled) return;
        setFile(f);
        setAnalysis(a);
        const dec: Record<string, { action: NodeImportAction; renameTo: string }> = {};
        for (const n of a.nodes) {
          dec[n.nodeId] = { action: "install", renameTo: "" };
        }
        setDecisions(dec);
      } catch (e: any) {
        if (!cancelled) setError(e?.message || "分析工作流包失败");
      } finally {
        if (!cancelled) setAnalyzing(false);
      }
    })();
    return () => { cancelled = true; };
  }, [baseUrl, resource.id, resource.name]);

  const setDecision = (nodeId: string, patch: Partial<{ action: NodeImportAction; renameTo: string }>) => {
    setDecisions((d) => ({ ...d, [nodeId]: { ...(d[nodeId] || { action: "install", renameTo: "" }), ...patch } }));
  };

  const installCount = analysis
    ? Object.values(decisions).filter((d) => d.action !== "skip").length
    : 0;

  const submit = async () => {
    if (!file) return;
    setImporting(true);
    setError("");
    try {
      const res = await importWorkflowPackage(file, name.trim() || resource.name, decisions);
      const failMsg = res.failed.length > 0 ? `，${res.failed.length} 个节点导入失败` : "";
      onSuccess(`工作流已导入（${res.workflow.name}），已安装 ${res.installed.length} 个自定义节点${failMsg}`);
    } catch (e: any) {
      setError(e?.message || "导入失败");
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="rounded-lg border border-border bg-muted/30 p-3 space-y-2">
      <div className="text-xs text-muted-foreground">以新名称导入为全局工作流：</div>
      <Input value={name} onChange={(e) => setName(e.target.value)} className="h-8 text-xs" />

      {analyzing && (
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground py-1">
          <Loader2 className="w-3 h-3 animate-spin" /> 正在分析工作流中的自定义节点…
        </div>
      )}

      {analysis && (
        analysis.nodes.length > 0 ? (
          <>
            <div className="text-[11px] font-semibold text-muted-foreground">
              将一并导入的自定义节点（{analysis.nodes.length} 个）
            </div>
            <div className="max-h-44 overflow-y-auto space-y-1.5 pr-1">
              {analysis.nodes.map((n) => {
                const meta = STATUS_META[n.status] || STATUS_META.new;
                const decision = decisions[n.nodeId] || { action: "install", renameTo: "" };
                return (
                  <div key={n.nodeId} className="flex items-center gap-2 text-[11px] flex-wrap">
                    <span className="min-w-0 flex-1 truncate" title={`${n.nodeId}${n.exists ? `（本地 v${n.localVersion}）` : ""}`}>
                      {n.name || n.nodeId}
                    </span>
                    <span className="text-muted-foreground flex-shrink-0">v{n.version}</span>
                    <span className={cn("px-1.5 py-0.5 rounded border flex-shrink-0", meta.cls)}>{meta.label}</span>
                    <Select
                      value={decision.action}
                      onValueChange={(v) => setDecision(n.nodeId, { action: v as NodeImportAction })}
                    >
                      <SelectTrigger className="w-[116px] h-7 text-[11px]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="install">{n.exists ? "覆盖 + 备份" : "安装"}</SelectItem>
                        {n.exists && <SelectItem value="rename">改名导入</SelectItem>}
                        <SelectItem value="skip">跳过</SelectItem>
                      </SelectContent>
                    </Select>
                    {decision.action === "rename" && (
                      <Input
                        value={decision.renameTo}
                        onChange={(e) => setDecision(n.nodeId, { renameTo: e.target.value })}
                        placeholder={`${n.nodeId}_import`}
                        className="h-7 w-40 text-[11px] font-mono"
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </>
        ) : (
          <div className="text-[11px] text-muted-foreground">该工作流未附带自定义节点，将直接保存为全局工作流。</div>
        )
      )}

      {error && (
        <div className="text-[11px] text-red-500 flex items-center gap-1"><AlertCircle className="w-3 h-3" />{error}</div>
      )}

      <div className="flex gap-2">
        <Button size="sm" variant="outline" onClick={onCancel} disabled={importing}>取消</Button>
        <Button size="sm" onClick={submit} disabled={importing || analyzing || !file}>
          {importing ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Download className="w-3 h-3 mr-1" />}
          保存并导入{analysis && analysis.nodes.length > 0 ? `（${installCount} 个节点）` : ""}
        </Button>
      </div>
    </div>
  );
}

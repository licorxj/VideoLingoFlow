import { useState, useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { historyApi } from "@/api/history";
import { tasksApi } from "@/api/tasks";
import TaskCard from "@/components/task/TaskCard";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/shared/PageHeader";
import { PageBackground } from "@/components/shared/PageBackground";
import { EmptyState } from "@/components/shared/EmptyState";
import { LoadingState } from "@/components/shared/LoadingState";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  History as HistoryIcon,
  RefreshCw,
  Inbox,
  Search,
  Trash2,
  CheckSquare,
  ListChecks,
} from "lucide-react";

export default function History() {
  const [tasks, setTasks] = useState<any[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [keyword, setKeyword] = useState("");
  const [sortDir, setSortDir] = useState<"desc" | "asc">("desc");
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const load = async () => {
    setLoading(true);
    try {
      const res = await historyApi.list();
      setTasks(res.data.tasks || []);
    } catch (err) {
      console.error("Failed to load history tasks:", err);
      setTasks([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  // Fuzzy filter by name / task id / workflow name, then sort by created_at
  const visibleTasks = useMemo(() => {
    let list = [...tasks];
    const kw = keyword.trim().toLowerCase();
    if (kw) {
      list = list.filter((t) => {
        const name = ((t.task_name || t.id) || "").toLowerCase();
        const id = (t.id || "").toLowerCase();
        const wf = (t.workflow_name || "").toLowerCase();
        return name.includes(kw) || id.includes(kw) || wf.includes(kw);
      });
    }
    list.sort((a, b) => {
      const ta = a.created_at || "";
      const tb = b.created_at || "";
      return sortDir === "asc" ? ta.localeCompare(tb) : tb.localeCompare(ta);
    });
    return list;
  }, [tasks, keyword, sortDir]);

  const allVisibleSelected =
    visibleTasks.length > 0 &&
    visibleTasks.every((t) => selected.has(t.id));

  const handleSelect = (id: string, checked: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const handleSelectAll = () => {
    if (visibleTasks.length === 0) return;
    setSelected((prev) => {
      const next = new Set(prev);
      if (allVisibleSelected) {
        visibleTasks.forEach((t) => next.delete(t.id));
      } else {
        visibleTasks.forEach((t) => next.add(t.id));
      }
      return next;
    });
  };

  const handleInvert = () => {
    setSelected((prev) => {
      const next = new Set(prev);
      visibleTasks.forEach((t) => {
        if (next.has(t.id)) next.delete(t.id);
        else next.add(t.id);
      });
      return next;
    });
  };

  const handleDelete = async (id: string) => {
    if (!confirm("确定要删除此任务吗？")) return;
    try {
      await tasksApi.delete(id);
      setTasks((prev) => prev.filter((task) => task.id !== id));
      setSelected((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    } catch (err: any) {
      const msg =
        err?.response?.data?.detail ||
        err?.message ||
        "删除历史项目失败";
      window.alert(msg);
    }
  };

  const handleBatchDelete = async () => {
    if (selected.size === 0) return;
    if (!confirm(`确定要删除选中的 ${selected.size} 个项目吗？`)) return;
    const ids = [...selected];
    const failed: string[] = [];
    for (const id of ids) {
      try {
        await tasksApi.delete(id);
      } catch (err) {
        console.error("Failed to delete task:", id, err);
        failed.push(id);
      }
    }
    setTasks((prev) => prev.filter((task) => !ids.includes(task.id)));
    setSelected(new Set());
    if (failed.length > 0) {
      window.alert(`部分项目删除失败：${failed.join(", ")}`);
    }
  };

  return (
    <PageBackground tone="history" className="max-w-7xl mx-auto space-y-5 p-1">
      <PageHeader
        icon={HistoryIcon}
        title="历史项目"
        detail="查看已完成的任务记录，可回溯执行"
        actions={
          <>
            <Button variant="outline" size="sm" onClick={handleSelectAll} disabled={visibleTasks.length === 0}>
              <CheckSquare className="mr-1.5 h-4 w-4" />
              {allVisibleSelected ? "取消全选" : "全选"}
            </Button>
            <Button variant="outline" size="sm" onClick={handleInvert} disabled={visibleTasks.length === 0}>
              <ListChecks className="mr-1.5 h-4 w-4" />
              反选
            </Button>
            <Button variant="destructive" size="sm" onClick={handleBatchDelete} disabled={selected.size === 0}>
              <Trash2 className="mr-1.5 h-4 w-4" />
              批量删除
              {selected.size > 0 && (
                <span className="ml-1 rounded-md bg-destructive-foreground/20 px-1.5 py-0.5 text-[11px] font-semibold">
                  {selected.size}
                </span>
              )}
            </Button>
            <Button variant="outline" size="sm" onClick={load}>
              <RefreshCw className="mr-1.5 h-4 w-4" />
              刷新
            </Button>
          </>
        }
      />

      <div className="flex items-center gap-3 rounded-xl border border-border/60 bg-card p-3">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground/50" />
          <Input
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="搜索项目名称、任务ID、工作流名称..."
            className="pl-9"
          />
        </div>
        <Select
          value={sortDir}
          onValueChange={(v) => setSortDir(v as "desc" | "asc")}
        >
          <SelectTrigger className="w-44 flex-shrink-0">
            <SelectValue placeholder="排序方式" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="desc">最新创建</SelectItem>
            <SelectItem value="asc">最早创建</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {loading ? (
        <LoadingState label="正在加载历史记录…" />
      ) : visibleTasks.length > 0 ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4 gap-4">
          {visibleTasks.map((t) => (
            <TaskCard
              key={t.id}
              task={t}
              selected={selected.has(t.id)}
              onSelect={handleSelect}
              onSelectCard={(id) => navigate("/?task=" + id)}
              onDelete={handleDelete}
            />
          ))}
        </div>
      ) : (
        <EmptyState
          icon={Inbox}
          title={keyword.trim() ? "未找到匹配的项目" : "暂无历史记录"}
          detail={
            keyword.trim()
              ? "请尝试更换关键词，或清除搜索条件"
              : "完成的任务将自动出现在这里"
          }
        />
      )}
    </PageBackground>
  );
}

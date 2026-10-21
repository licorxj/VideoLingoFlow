import { useEffect, useState } from "react";
import { Plus, Minus } from "lucide-react";
import client from "@/api/client";

interface WfItem {
  group: string;
  workflow: string;
}

interface WfInfo {
  id: string;
  name: string;
}

interface GroupInfo {
  id: string;
  name: string;
}

interface Props {
  config: Record<string, any>;
  onConfigChange: (key: string, value: any) => void;
}

/**
 * 指定调用工作流：双列选择（分组 → 工作流）+ 加减号增删。
 * 工作流列表来自 GET /api/workflows（含 groups / membership），分组为动态用户分组。
 */
export function SpecifiedWorkflowEditor({ config, onConfigChange }: Props) {
  const list: WfItem[] = Array.isArray(config.workflows) ? (config.workflows as WfItem[]) : [];

  const [wfInfos, setWfInfos] = useState<WfInfo[]>([]);
  const [groups, setGroups] = useState<GroupInfo[]>([]);
  const [membership, setMembership] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    client
      .get("/api/workflows")
      .then((res) => {
        if (!alive) return;
        const d = res.data || {};
        setWfInfos(d.workflows || []);
        setGroups(d.groups || []);
        setMembership(d.membership || {});
      })
      .catch(() => {
        /* 忽略：列表失败时仅显示空选项 */
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  // 分组选项：固定「未分组」+ 用户动态分组（按接口返回顺序）
  const groupOptions: GroupInfo[] = [{ id: "", name: "未分组" }, ...groups];
  const workflowsOf = (gid: string) =>
    wfInfos.filter((w) => (gid ? membership[w.id] === gid : !membership[w.id]));

  const update = (next: WfItem[]) => onConfigChange("workflows", next);
  const setItem = (i: number, patch: Partial<WfItem>) =>
    update(list.map((p, idx) => (idx === i ? { ...p, ...patch } : p)));
  const remove = (i: number) => update(list.filter((_, idx) => idx !== i));
  const add = () => update([...list, { group: "", workflow: "" }]);

  return (
    <div className="px-3 pb-3 pt-1 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-semibold text-muted-foreground">指定调用的工作流（分组 → 工作流）</span>
        <button
          type="button"
          onClick={add}
          onPointerDown={(e) => e.stopPropagation()}
          className="inline-flex items-center gap-1 rounded-md border border-primary/30 bg-primary/10 px-2 py-0.5 text-[10px] text-primary hover:bg-primary/20 transition-colors"
        >
          <Plus className="w-3 h-3" /> 添加
        </button>
      </div>

      {loading && <div className="text-[11px] text-muted-foreground/70 py-1">加载工作流列表…</div>}
      {!loading && list.length === 0 && (
        <div className="text-[11px] text-muted-foreground/70 text-center py-2">尚未选择工作流，点击右上角「添加」增加。</div>
      )}

      {list.map((p, i) => {
        const wfs = workflowsOf(p.group);
        return (
          <div key={i} className="rounded-md border border-border/60 bg-background/60 p-2 space-y-1.5">
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] text-muted-foreground/70 shrink-0 w-5">#{i + 1}</span>
              <div className="flex-1 grid grid-cols-2 gap-1.5">
                <select
                  value={p.group}
                  onPointerDown={(e) => e.stopPropagation()}
                  onChange={(e) => setItem(i, { group: e.target.value, workflow: "" })}
                  className="w-full rounded-md border border-border bg-background px-1.5 py-1 text-[11px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  <option value="">选择分组</option>
                  {groupOptions.map((g) => (
                    <option key={g.id} value={g.id}>
                      {g.name}
                    </option>
                  ))}
                </select>
                <select
                  value={p.workflow}
                  disabled={!p.group}
                  onPointerDown={(e) => e.stopPropagation()}
                  onChange={(e) => setItem(i, { workflow: e.target.value })}
                  className="w-full rounded-md border border-border bg-background px-1.5 py-1 text-[11px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
                >
                  <option value="">选择工作流</option>
                  {wfs.map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.name}
                    </option>
                  ))}
                </select>
              </div>
              <button
                type="button"
                onClick={() => remove(i)}
                onPointerDown={(e) => e.stopPropagation()}
                title="移除该工作流"
                className="shrink-0 inline-flex items-center justify-center rounded-md border border-border/60 bg-background px-1.5 py-1 text-muted-foreground hover:text-destructive hover:border-destructive/40 transition-colors"
              >
                <Minus className="w-3 h-3" />
              </button>
            </div>
          </div>
        );
      })}

      <p className="text-[10px] text-muted-foreground/60 leading-relaxed">
        后端按所选工作流顺序，组装「通用调用方法 / 工作流入口 / 输入与输出 / 节点组成与可选配置」为提示词，从「提示词」端口输出（不落盘）。
      </p>
    </div>
  );
}

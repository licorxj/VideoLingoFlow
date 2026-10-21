import { Plus, Minus } from "lucide-react";
import { CATEGORIES, getNodesByCategory } from "@/lib/workflowTypes";

interface PackageItem {
  group: string;
  node: string;
}

interface Props {
  config: Record<string, any>;
  onConfigChange: (key: string, value: any) => void;
}

/**
 * 指定调用节点包：双列选择（分组 → 节点）+ 加减号增删。
 * 仅维护 config.packages 数组，提示词由后端步骤组装。
 */
export function SpecifiedNodePackageEditor({ config, onConfigChange }: Props) {
  const packages: PackageItem[] = Array.isArray(config.packages) ? (config.packages as PackageItem[]) : [];

  // 只展示真实存在节点的分组，并按 CATEGORIES 顺序
  const categories = Object.keys(CATEGORIES).filter((cat) => getNodesByCategory(cat).length > 0);

  const update = (next: PackageItem[]) => onConfigChange("packages", next);
  const setItem = (i: number, patch: Partial<PackageItem>) =>
    update(packages.map((p, idx) => (idx === i ? { ...p, ...patch } : p)));
  const remove = (i: number) => update(packages.filter((_, idx) => idx !== i));
  const add = () => update([...packages, { group: "", node: "" }]);

  return (
    <div className="px-3 pb-3 pt-1 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-semibold text-muted-foreground">指定调用的节点（分组 → 节点）</span>
        <button
          type="button"
          onClick={add}
          onPointerDown={(e) => e.stopPropagation()}
          className="inline-flex items-center gap-1 rounded-md border border-primary/30 bg-primary/10 px-2 py-0.5 text-[10px] text-primary hover:bg-primary/20 transition-colors"
        >
          <Plus className="w-3 h-3" /> 添加
        </button>
      </div>

      {packages.length === 0 && (
        <div className="text-[11px] text-muted-foreground/70 text-center py-2">尚未选择节点，点击右上角「添加」增加。</div>
      )}

      {packages.map((p, i) => {
        const nodes = p.group ? getNodesByCategory(p.group) : [];
        return (
          <div key={i} className="rounded-md border border-border/60 bg-background/60 p-2 space-y-1.5">
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] text-muted-foreground/70 shrink-0 w-5">#{i + 1}</span>
              <div className="flex-1 grid grid-cols-2 gap-1.5">
                <select
                  value={p.group}
                  onPointerDown={(e) => e.stopPropagation()}
                  onChange={(e) => setItem(i, { group: e.target.value, node: "" })}
                  className="w-full rounded-md border border-border bg-background px-1.5 py-1 text-[11px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  <option value="">选择分组</option>
                  {categories.map((c) => (
                    <option key={c} value={c}>
                      {CATEGORIES[c as keyof typeof CATEGORIES]?.label || c}
                    </option>
                  ))}
                </select>
                <select
                  value={p.node}
                  disabled={!p.group}
                  onPointerDown={(e) => e.stopPropagation()}
                  onChange={(e) => setItem(i, { node: e.target.value })}
                  className="w-full rounded-md border border-border bg-background px-1.5 py-1 text-[11px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
                >
                  <option value="">选择节点</option>
                  {nodes.map((n) => (
                    <option key={n.id} value={n.id}>
                      {n.name}
                    </option>
                  ))}
                </select>
              </div>
              <button
                type="button"
                onClick={() => remove(i)}
                onPointerDown={(e) => e.stopPropagation()}
                title="移除该节点"
                className="shrink-0 inline-flex items-center justify-center rounded-md border border-border/60 bg-background px-1.5 py-1 text-muted-foreground hover:text-destructive hover:border-destructive/40 transition-colors"
              >
                <Minus className="w-3 h-3" />
              </button>
            </div>
          </div>
        );
      })}

      <p className="text-[10px] text-muted-foreground/60 leading-relaxed">
        后端按所选节点顺序，组装「通用调用方法 / 入口脚本路径 / 输入与输出 / 可选设置参数」为提示词，从「提示词」端口输出（不落盘）。
      </p>
    </div>
  );
}

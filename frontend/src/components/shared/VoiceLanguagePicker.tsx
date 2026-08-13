import { useState, useEffect } from "react";
import { cn } from "@/lib/utils";
import { Check, Search, X, Languages } from "lucide-react";

interface Props {
  title: string;
  items: string[];
  selected: string[];
  onConfirm: (selected: string[]) => void;
  onCancel: () => void;
  fetchUrl?: string;
  fetchKeyPath?: string;
}

export default function VoiceLanguagePicker({ title, items, selected, onConfirm, onCancel, fetchUrl, fetchKeyPath }: Props) {
  const [allItems, setAllItems] = useState<string[]>(items);
  const [selectedSet, setSelectedSet] = useState<Set<string>>(new Set(selected));
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setAllItems(items);
    setSelectedSet(new Set(selected));
  }, [items, selected]);

  const fetchItems = async () => {
    if (!fetchUrl) return;
    setLoading(true);
    setError("");
    try {
      const resp = await fetch(fetchUrl);
      const data = await resp.json();
      let result: string[] = [];
      if (fetchKeyPath) {
        const nested = fetchKeyPath.split(".").reduce((obj: any, k: string) => obj?.[k], data);
        if (Array.isArray(nested)) {
          result = nested.map((v: any) => typeof v === "string" ? v : JSON.stringify(v));
        }
      } else if (Array.isArray(data)) {
        result = data.map((v: any) => typeof v === "string" ? v : JSON.stringify(v));
      }
      if (result.length > 0) {
        setAllItems(result);
      } else {
        setError("未找到项目，请检查 URL 和 Key 路径");
      }
    } catch (e: any) {
      setError(`获取失败: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  const toggleItem = (item: string) => {
    setSelectedSet((prev) => {
      const next = new Set(prev);
      if (next.has(item)) {
        next.delete(item);
      } else {
        next.add(item);
      }
      return next;
    });
  };

  const toggleAll = () => {
    const filtered = filteredItems();
    const allSelected = filtered.every((item) => selectedSet.has(item));
    if (allSelected) {
      setSelectedSet((prev) => {
        const next = new Set(prev);
        filtered.forEach((item) => next.delete(item));
        return next;
      });
    } else {
      setSelectedSet((prev) => {
        const next = new Set(prev);
        filtered.forEach((item) => next.add(item));
        return next;
      });
    }
  };

  const clearAll = () => {
    setSelectedSet(new Set());
  };

  const filteredItems = () => {
    if (!filter.trim()) return allItems;
    const lower = filter.toLowerCase();
    return allItems.filter((item) => item.toLowerCase().includes(lower));
  };

  const filtered = filteredItems();
  const allFilteredSelected = filtered.length > 0 && filtered.every((item) => selectedSet.has(item));

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 backdrop-blur-sm animate-fade-in">
      <div className="bg-background border border-border/60 rounded-2xl shadow-2xl w-[min(600px,90vw)] max-h-[80vh] flex flex-col animate-scale-in">
        {/* Header */}
        <div className="px-5 py-4 border-b border-border/40 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Languages className="w-4 h-4 text-primary" />
            <h3 className="text-sm font-bold">{title}</h3>
          </div>
          <button onClick={onCancel} className="p-1.5 rounded-lg hover:bg-secondary transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Toolbar */}
        <div className="px-5 py-3 border-b border-border/30 space-y-2">
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
              <input
                className="w-full pl-8 pr-3 py-2 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none"
                placeholder="搜索..."
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              />
            </div>
            {fetchUrl && (
              <button
                onClick={fetchItems}
                disabled={loading}
                className="px-3 py-2 text-xs font-medium border border-border/60 rounded-xl hover:bg-accent/60 transition-colors disabled:opacity-40 whitespace-nowrap"
              >
                {loading ? "获取中..." : "从 URL 获取"}
              </button>
            )}
          </div>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <button
                onClick={toggleAll}
                className="px-3 py-1.5 text-xs font-medium border border-border/60 rounded-lg hover:bg-accent/60 transition-colors"
              >
                {allFilteredSelected ? "取消筛选项" : "全选筛选项"}
              </button>
              <button
                onClick={clearAll}
                className="px-3 py-1.5 text-xs font-medium border border-border/60 rounded-lg hover:bg-accent/60 transition-colors text-muted-foreground"
              >
                清空全部
              </button>
            </div>
            <span className="text-xs text-muted-foreground">
              已选 {selectedSet.size} / {allItems.length}
            </span>
          </div>
        </div>

        {error && <div className="px-5 py-2 text-xs text-red-500 bg-red-500/5">{error}</div>}

        {/* Items list */}
        <div className="flex-1 overflow-y-auto px-5 py-2 min-h-[200px] max-h-[400px]">
          {filtered.length === 0 ? (
            <div className="text-center py-8 text-xs text-muted-foreground">未找到项目</div>
          ) : (
            <div className="grid grid-cols-2 gap-1.5">
              {filtered.map((item) => {
                const isSelected = selectedSet.has(item);
                return (
                  <button
                    key={item}
                    onClick={() => toggleItem(item)}
                    className={cn(
                      "flex items-center gap-2 px-3 py-2 rounded-lg border text-left text-sm transition-all duration-150",
                      isSelected
                        ? "border-primary/40 bg-primary/5 text-foreground"
                        : "border-border/30 hover:border-border/50 text-muted-foreground hover:text-foreground"
                    )}
                  >
                    <div className={cn(
                      "w-4 h-4 rounded border flex-shrink-0 flex items-center justify-center transition-all duration-150",
                      isSelected
                        ? "bg-primary border-primary text-primary-foreground"
                        : "border-border/60"
                    )}>
                      {isSelected && <Check className="w-3 h-3" strokeWidth={3} />}
                    </div>
                    <span className="font-medium text-xs">{item}</span>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-border/40 flex gap-3 justify-end">
          <button onClick={onCancel} className="px-4 py-2 text-sm font-medium border border-border/60 rounded-xl hover:bg-secondary/70 transition-all duration-200 active:scale-[0.97]">取消</button>
          <button
            onClick={() => onConfirm(Array.from(selectedSet))}
            className="px-4 py-2 text-sm font-semibold bg-primary text-primary-foreground rounded-xl transition-all duration-200 hover:shadow-lg hover:shadow-primary/25 active:scale-[0.97]"
          >
            确认（{selectedSet.size}）
          </button>
        </div>
      </div>
    </div>
  );
}

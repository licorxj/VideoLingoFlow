import { useState, useEffect, useRef } from "react";
import { CATEGORIES, type NodeTypeDef, getAllNodeTypes, PORT_COLORS } from "@/lib/workflowTypes";
import { cn } from "@/lib/utils";
import {
  Film, Music, Subtitles, Mic, Mic2, Scissors, Brain, Languages, AlignLeft,
  FileText, Volume2, Merge, Clapperboard, Image, Stamp, Download,
  Upload, Wrench, Play, Eye, Sparkles, Share2, ChevronRight, Search,
  SlidersHorizontal,
} from "lucide-react";

const ICON_MAP: Record<string, any> = {
  Film, Music, Subtitles, Mic, Mic2, Scissors, Brain, Languages, AlignLeft,
  FileText, Volume2, Merge, Clapperboard, Image, Stamp, Download,
  Upload, Wrench, Play, Eye, Sparkles, Share2, SlidersHorizontal,
};

interface ContextMenuProps {
  visible: boolean;
  position: { x: number; y: number };
  onClose: () => void;
  onSelectNode: (nodeType: NodeTypeDef, screenPos?: { x: number; y: number }) => void;
}

export default function ContextMenu({ visible, position, onClose, onSelectNode }: ContextMenuProps) {
  type CategoryKey = keyof typeof CATEGORIES;
  const [hoveredCategory, setHoveredCategory] = useState<CategoryKey | null>(null);
  const [search, setSearch] = useState("");
  const menuRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Reset state when menu opens/closes
  useEffect(() => {
    if (visible) {
      setHoveredCategory(null);
      setSearch("");
      setTimeout(() => searchRef.current?.focus(), 50);
    }
  }, [visible]);

  // Close on outside click or Escape
  useEffect(() => {
    if (!visible) return;
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", handleClick, true);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClick, true);
      document.removeEventListener("keydown", handleKey);
    };
  }, [visible, onClose]);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => { if (closeTimer.current) clearTimeout(closeTimer.current); };
  }, []);

  if (!visible) return null;

  const allNodes = getAllNodeTypes();
  const categories = Object.entries(CATEGORIES) as [CategoryKey, (typeof CATEGORIES)[CategoryKey]][];

  // Filter nodes by search
  const filteredNodes = search
    ? allNodes.filter((n) => n.name.toLowerCase().includes(search.toLowerCase()) || n.id.toLowerCase().includes(search.toLowerCase()))
    : null;

  const handleNodeClick = (nodeType: NodeTypeDef, e: React.MouseEvent) => {
    onSelectNode(nodeType, { x: e.clientX, y: e.clientY });
    onClose();
  };

  // 支持从菜单直接拖拽节点到画布（与左侧节点面板共用 application/reactflow 数据格式）
  const handleNodeDragStart = (e: React.DragEvent, nodeType: NodeTypeDef) => {
    e.dataTransfer.setData("application/reactflow", JSON.stringify(nodeType));
    e.dataTransfer.effectAllowed = "move";
  };

  const handleCategoryEnter = (cat: CategoryKey) => {
    if (closeTimer.current) { clearTimeout(closeTimer.current); closeTimer.current = null; }
    setHoveredCategory(cat);
  };

  const handleCategoryLeave = () => {
    closeTimer.current = setTimeout(() => setHoveredCategory(null), 200);
  };

  const handleSubmenuEnter = () => {
    if (closeTimer.current) { clearTimeout(closeTimer.current); closeTimer.current = null; }
  };

  const handleSubmenuLeave = () => {
    closeTimer.current = setTimeout(() => setHoveredCategory(null), 200);
  };

  // Calculate position ensuring menu stays in viewport
  const catMenuWidth = 220;
  const subMenuWidth = 240;
  const totalWidth = catMenuWidth + subMenuWidth;
  // 菜单高度在原 420px 基础上提升 20%
  const menuMaxHeight = 504;

  // Position: try to keep the full two-panel menu in viewport
  let px = position.x;
  let py = position.y;
  if (px + totalWidth > window.innerWidth - 10) {
    px = Math.max(10, position.x - totalWidth);
  }
  if (py + menuMaxHeight > window.innerHeight - 10) {
    py = Math.max(10, window.innerHeight - menuMaxHeight - 10);
  }

  const hoveredCatConfig = hoveredCategory ? CATEGORIES[hoveredCategory] : null;
  const visibleNodes = search ? (filteredNodes ?? []) : allNodes;
  const subNodes = hoveredCategory
    ? visibleNodes.filter((n) => n.category === hoveredCategory)
    : [];

  return (
    <div
      ref={menuRef}
      className="fixed z-[9999] bg-card border border-border rounded-xl shadow-2xl shadow-black/20 overflow-hidden flex"
      style={{ left: px, top: py, maxHeight: menuMaxHeight }}
      onContextMenu={(e) => e.preventDefault()}
    >
      {/* Left: Category list */}
      <div className="flex-shrink-0 py-1" style={{ width: catMenuWidth }}>
        {/* Search bar */}
        <div className="px-2 py-1.5 border-b border-border/30">
          <div className="flex items-center gap-2 px-2 py-1.5 rounded-lg bg-background/60 border border-border/40">
            <Search className="w-3.5 h-3.5 text-muted-foreground/60 flex-shrink-0" />
            <input
              ref={searchRef}
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索节点..."
              className="flex-1 bg-transparent text-xs outline-none placeholder:text-muted-foreground/40"
            />
          </div>
        </div>

        {search ? (
          // Search results inline
          <div className="overflow-y-auto py-1" style={{ maxHeight: menuMaxHeight - 44 }}>
            {filteredNodes && filteredNodes.length > 0 ? (
              filteredNodes.map((nodeType) => (
                <NodeItem key={nodeType.id} nodeType={nodeType} onClick={(e) => handleNodeClick(nodeType, e)}
                  onDragStartNode={handleNodeDragStart} onDragEndNode={onClose} />
              ))
            ) : (
              <div className="px-4 py-6 text-center text-xs text-muted-foreground/50">无匹配节点</div>
            )}
          </div>
        ) : (
          // Category list
          <div className="overflow-y-auto py-1" style={{ maxHeight: menuMaxHeight - 44 }}>
            {categories.map(([cat, cfg]) => {
              const catNodes = allNodes.filter((n) => n.category === cat);
              if (catNodes.length === 0) return null;
              const IconComp = ICON_MAP[cfg.icon] || Wrench;
              const isActive = hoveredCategory === cat;
              return (
                <div
                  key={cat}
                  onMouseEnter={() => handleCategoryEnter(cat)}
                  onMouseLeave={handleCategoryLeave}
                  className={cn(
                    "flex items-center gap-2.5 px-3 py-2.5 text-xs cursor-pointer transition-colors",
                    isActive ? "bg-secondary/70" : "hover:bg-secondary/50"
                  )}
                >
                  <div
                    className="w-6 h-6 rounded-md flex items-center justify-center flex-shrink-0"
                    style={{ backgroundColor: cfg.color + "20" }}
                  >
                    <IconComp className="w-3 h-3" style={{ color: cfg.color }} />
                  </div>
                  <span className="font-medium flex-1 text-left" style={{ color: cfg.color }}>{cfg.label}</span>
                  <span className="text-[10px] text-muted-foreground/40 mr-1">{catNodes.length}</span>
                  <ChevronRight className={cn(
                    "w-3 h-3 transition-colors",
                    isActive ? "text-muted-foreground" : "text-muted-foreground/30"
                  )} />
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Right: Sub-menu for hovered category */}
      {!search && hoveredCategory && hoveredCatConfig && (
        <div
          className="border-l border-border/30 py-1 overflow-y-auto flex-shrink-0"
          style={{ width: subMenuWidth, maxHeight: menuMaxHeight }}
          onMouseEnter={handleSubmenuEnter}
          onMouseLeave={handleSubmenuLeave}
        >
          {/* Category header */}
          <div className="px-3 py-2 border-b border-border/20">
            <span className="text-[10px] font-semibold" style={{ color: hoveredCatConfig.color }}>{hoveredCatConfig.label}</span>
          </div>
          <div className="py-1">
            {subNodes.length > 0 ? (
              subNodes.map((nodeType) => (
                <NodeItem key={nodeType.id} nodeType={nodeType} onClick={(e) => handleNodeClick(nodeType, e)}
                  onDragStartNode={handleNodeDragStart} onDragEndNode={onClose} />
              ))
            ) : (
              <div className="px-4 py-6 text-center text-xs text-muted-foreground/50">该分类下无节点</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function NodeItem({ nodeType, onClick, onDragStartNode, onDragEndNode }: {
  nodeType: NodeTypeDef;
  onClick: (e: React.MouseEvent) => void;
  onDragStartNode: (e: React.DragEvent, nodeType: NodeTypeDef) => void;
  onDragEndNode: () => void;
}) {
  const IconComp = ICON_MAP[nodeType.icon] || Wrench;
  return (
    <button
      draggable
      onClick={onClick}
      onDragStart={(e) => onDragStartNode(e, nodeType)}
      onDragEnd={onDragEndNode}
      title="点击选择后粘附鼠标放置，或直接拖入画布"
      className="w-full flex items-center gap-2.5 px-3 py-2 hover:bg-primary/5 transition-colors group cursor-grab active:cursor-grabbing"
    >
      <div
        className="w-5 h-5 rounded flex items-center justify-center flex-shrink-0"
        style={{ backgroundColor: nodeType.color + "25" }}
      >
        <IconComp className="w-2.5 h-2.5" style={{ color: nodeType.color }} />
      </div>
      <div className="flex-1 min-w-0 text-left">
        <div className="text-xs font-medium truncate group-hover:text-primary transition-colors">{nodeType.name}</div>
      </div>
      <div className="flex gap-0.5 flex-shrink-0">
        {nodeType.inputs.slice(0, 4).map((p) => (
          <span key={p.id} className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: p.color || PORT_COLORS[p.type] }} />
        ))}
        {nodeType.outputs.slice(0, 4).map((p) => (
          <span key={p.id} className="w-1 h-1 rounded-full border" style={{ borderColor: p.color || PORT_COLORS[p.type] }} />
        ))}
      </div>
    </button>
  );
}

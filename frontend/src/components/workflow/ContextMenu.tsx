import { useState, useEffect, useRef } from "react";
import { CATEGORIES, type NodeTypeDef, getAllNodeTypes, PORT_COLORS } from "@/lib/workflowTypes";
import { cn } from "@/lib/utils";
import {
  Film, Music, Subtitles, Mic, Mic2, Scissors, Brain, Languages, AlignLeft,
  FileText, Volume2, Merge, Clapperboard, Image, Stamp, Download,
  Upload, Wrench, Play, Eye, Sparkles, Share2, ChevronRight, Search,
  SlidersHorizontal, Workflow as WorkflowIcon, Loader2,
} from "lucide-react";

const ICON_MAP: Record<string, any> = {
  Film, Music, Subtitles, Mic, Mic2, Scissors, Brain, Languages, AlignLeft,
  FileText, Volume2, Merge, Clapperboard, Image, Stamp, Download,
  Upload, Wrench, Play, Eye, Sparkles, Share2, SlidersHorizontal,
};

/** 菜单里需要的最少工作流信息（不需要整份工作流数据） */
export interface WorkflowBrief {
  id: string;
  name: string;
  description?: string;
  /** 列表接口给出的节点数：用于区分「工作流本来就是空的」与「节点拉取失败」 */
  nodeCount?: number;
}

interface ContextMenuProps {
  visible: boolean;
  position: { x: number; y: number };
  onClose: () => void;
  onSelectNode: (nodeType: NodeTypeDef, screenPos?: { x: number; y: number }) => void;
  /** 可插入节点的工作流列表（第一项「来自其他工作流」的二级菜单数据） */
  workflows?: WorkflowBrief[];
  /** 当前工作流：从列表里排除，避免「从自己导自己」 */
  currentWorkflowId?: string;
  /** 拉取某个工作流的节点（三级菜单）；实现方负责带鉴权与错误兜底 */
  onLoadWorkflowNodes?: (workflowId: string) => Promise<any[]>;
  /** 点击三级菜单里的节点：把该节点（含配置参数）插入画布，screenPos 为右键位置 */
  onInsertNode?: (node: any, screenPos: { x: number; y: number }) => void;
}

export default function ContextMenu({
  visible, position, onClose, onSelectNode,
  workflows = [], currentWorkflowId, onLoadWorkflowNodes, onInsertNode,
}: ContextMenuProps) {
  type CategoryKey = keyof typeof CATEGORIES;
  const [hoveredCategory, setHoveredCategory] = useState<CategoryKey | null>(null);
  const [search, setSearch] = useState("");
  // 「来自其他工作流」二级面板
  const [workflowsEntryOpen, setWorkflowsEntryOpen] = useState(false);
  // 三级面板：当前悬停的工作流
  const [hoveredWfId, setHoveredWfId] = useState<string | null>(null);
  const [loadingWfId, setLoadingWfId] = useState<string | null>(null);
  // 拉取失败的工作流 id：失败不写缓存，移开再悬停即可重试
  const [errorWfId, setErrorWfId] = useState<string | null>(null);
  // 已加载节点缓存（按工作流 id）：避免反复请求，也避免用 state 存大对象反复拷贝
  const nodesCacheRef = useRef<Record<string, any[]>>({});
  const loadingRef = useRef<Set<string>>(new Set());
  const [, forceTick] = useState(0);
  const menuRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Reset state when menu opens/closes
  useEffect(() => {
    if (visible) {
      setHoveredCategory(null);
      setSearch("");
      setWorkflowsEntryOpen(false);
      setHoveredWfId(null);
      setLoadingWfId(null);
      // 每次打开菜单清空节点缓存：目标工作流可能刚被改过，保证插进来的是最新配置
      nodesCacheRef.current = {};
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

  const cancelClose = () => {
    if (closeTimer.current) { clearTimeout(closeTimer.current); closeTimer.current = null; }
  };
  const armClose = (fn: () => void) => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(fn, 200);
  };

  const handleCategoryEnter = (cat: CategoryKey) => {
    cancelClose();
    // 两个二级面板互斥：悬停分类时收起工作流面板
    setWorkflowsEntryOpen(false);
    setHoveredWfId(null);
    setHoveredCategory(cat);
  };

  const handleCategoryLeave = () => {
    armClose(() => setHoveredCategory(null));
  };

  const handleWorkflowsEntryEnter = () => {
    cancelClose();
    setHoveredCategory(null);
    setWorkflowsEntryOpen(true);
  };

  const handleWorkflowsEntryLeave = () => {
    armClose(() => {
      setWorkflowsEntryOpen(false);
      setHoveredWfId(null);
    });
  };

  const handleSubmenuEnter = () => cancelClose();

  const handleSubmenuLeave = () => armClose(() => setHoveredCategory(null));

  /** 悬停工作流 → 拉取它的节点（带缓存与并发去重） */
  const handleWorkflowEnter = (wfId: string) => {
    cancelClose();
    setHoveredWfId(wfId);
    if (nodesCacheRef.current[wfId] || loadingRef.current.has(wfId) || !onLoadWorkflowNodes) return;
    loadingRef.current.add(wfId);
    setLoadingWfId(wfId);
    setErrorWfId((cur) => (cur === wfId ? null : cur));
    onLoadWorkflowNodes(wfId)
      .then((list) => {
        nodesCacheRef.current[wfId] = list;
        setErrorWfId((cur) => (cur === wfId ? null : cur));
        forceTick((t) => t + 1);
      })
      .catch((err) => {
        // 不写缓存：移开再悬停可以重新请求，避免一次失败后本次会话永久显示空
        console.error("Failed to load workflow nodes:", err);
        setErrorWfId(wfId);
        forceTick((t) => t + 1);
      })
      .finally(() => {
        loadingRef.current.delete(wfId);
        setLoadingWfId((cur) => (cur === wfId ? null : cur));
      });
  };

  // Calculate position ensuring menu stays in viewport
  const catMenuWidth = 220;
  const subMenuWidth = 240;
  const thirdMenuWidth = 260;
  // 菜单高度在原 420px 基础上提升 30%
  const menuMaxHeight = 546;

  const showWorkflowPanel = !search && workflowsEntryOpen;
  const showWorkflowNodesPanel = showWorkflowPanel && !!hoveredWfId;
  // 固定按「左栏 + 二级 + 三级」的最宽形态预留宽度：菜单一旦定位就不再随 hover 移动。
  // 若按当前展开的面板动态计算，hover 时菜单会平移，鼠标相对菜单的位置随之改变，
  // 触发 mouseleave → 收起 → 又移回，形成抖动。
  const totalWidth = catMenuWidth + subMenuWidth + thirdMenuWidth;

  // Position: try to keep the full multi-panel menu in viewport
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

  const insertableWorkflows = workflows.filter((w) => w.id !== currentWorkflowId);
  const hoveredWorkflow = insertableWorkflows.find((w) => w.id === hoveredWfId) || null;
  const hoveredWorkflowNodes = hoveredWfId ? (nodesCacheRef.current[hoveredWfId] || null) : null;
  const nodeTypeById = new Map(allNodes.map((t) => [t.id, t]));

  const handleInsertNodeClick = (node: any) => {
    onInsertNode?.(node, position);
    onClose();
  };

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
            {/* 第一项：从其它工作流搬运节点（二级选工作流、三级选节点） */}
            <div
              onMouseEnter={handleWorkflowsEntryEnter}
              onMouseLeave={handleWorkflowsEntryLeave}
              className={cn(
                "flex items-center gap-2.5 px-3 py-2.5 text-xs cursor-pointer transition-colors",
                workflowsEntryOpen ? "bg-secondary/70" : "hover:bg-secondary/50"
              )}
            >
              <div className="w-6 h-6 rounded-md flex items-center justify-center flex-shrink-0 bg-primary/15">
                <WorkflowIcon className="w-3 h-3 text-primary" />
              </div>
              <span className="font-medium flex-1 text-left">来自其他工作流</span>
              <span className="text-[10px] text-muted-foreground/40 mr-1">{insertableWorkflows.length}</span>
              <ChevronRight className={cn(
                "w-3 h-3 transition-colors",
                workflowsEntryOpen ? "text-muted-foreground" : "text-muted-foreground/30"
              )} />
            </div>
            <div className="mx-2 my-1 h-px bg-border/40" />

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

      {/* 二级：工作流列表 */}
      {showWorkflowPanel && (
        <div
          className="border-l border-border/30 py-1 overflow-y-auto flex-shrink-0"
          style={{ width: subMenuWidth, maxHeight: menuMaxHeight }}
          onMouseEnter={handleSubmenuEnter}
          onMouseLeave={handleWorkflowsEntryLeave}
        >
          <div className="px-3 py-2 border-b border-border/20">
            <span className="text-[10px] font-semibold text-primary">来自其他工作流</span>
          </div>
          <div className="py-1">
            {insertableWorkflows.length > 0 ? (
              insertableWorkflows.map((wf) => {
                const isActive = hoveredWfId === wf.id;
                return (
                  <div
                    key={wf.id}
                    onMouseEnter={() => handleWorkflowEnter(wf.id)}
                    className={cn(
                      "flex items-center gap-2 px-3 py-2 text-xs cursor-pointer transition-colors",
                      isActive ? "bg-secondary/70" : "hover:bg-secondary/50"
                    )}
                  >
                    <FileText className="w-3 h-3 flex-shrink-0 text-muted-foreground/60" />
                    <span className="flex-1 min-w-0 truncate" title={wf.description || wf.name}>{wf.name}</span>
                    <ChevronRight className={cn(
                      "w-3 h-3 flex-shrink-0 transition-colors",
                      isActive ? "text-muted-foreground" : "text-muted-foreground/30"
                    )} />
                  </div>
                );
              })
            ) : (
              <div className="px-4 py-6 text-center text-xs text-muted-foreground/50">暂无其他工作流</div>
            )}
          </div>
        </div>
      )}

      {/* 三级：该工作流里的节点 */}
      {showWorkflowNodesPanel && (
        <div
          className="border-l border-border/30 py-1 overflow-y-auto flex-shrink-0"
          style={{ width: thirdMenuWidth, maxHeight: menuMaxHeight }}
          onMouseEnter={handleSubmenuEnter}
          onMouseLeave={handleWorkflowsEntryLeave}
        >
          <div className="px-3 py-2 border-b border-border/20 flex items-center justify-between gap-2">
            <span className="text-[10px] font-semibold truncate">{hoveredWorkflow?.name || "节点"}</span>
            {hoveredWorkflowNodes && (
              <span className="text-[10px] text-muted-foreground/40 flex-shrink-0">{hoveredWorkflowNodes.length}</span>
            )}
          </div>
          <div className="py-1">
            {errorWfId === hoveredWfId ? (
              // 失败不缓存，点一下立刻重试（常见原因是登录态刚过期）
              <button
                onClick={() => hoveredWfId && handleWorkflowEnter(hoveredWfId)}
                className="w-full px-4 py-6 text-center text-xs text-amber-500 hover:text-amber-400 transition-colors"
              >
                节点加载失败，点击重试
              </button>
            ) : loadingWfId === hoveredWfId && !hoveredWorkflowNodes ? (
              <div className="px-4 py-6 flex items-center justify-center gap-2 text-xs text-muted-foreground/60">
                <Loader2 className="w-3 h-3 animate-spin" />加载中...
              </div>
            ) : hoveredWorkflowNodes && hoveredWorkflowNodes.length > 0 ? (
              hoveredWorkflowNodes.map((node: any, idx: number) => {
                const def = node?.data?.nodeType ? nodeTypeById.get(node.data.nodeType) : undefined;
                const IconComp = (def?.icon && ICON_MAP[def.icon]) || Wrench;
                const color = def?.color || "#6366f1";
                const label = node?.data?.label || def?.name || node?.data?.nodeType || node?.id;
                // 原工作流里的备注（data.note）：跟随节点一起带过来，跟在名称后用括号展示
                const note = typeof node?.data?.note === "string" ? node.data.note.trim() : "";
                return (
                  <button
                    key={node?.id || idx}
                    onClick={() => handleInsertNodeClick(node)}
                    title={note ? `${label}（${note}）` : "插入到当前画布（含节点配置参数）"}
                    className="w-full flex items-center gap-2.5 px-3 py-2 hover:bg-primary/5 transition-colors group"
                  >
                    <div
                      className="w-5 h-5 rounded flex items-center justify-center flex-shrink-0"
                      style={{ backgroundColor: color + "25" }}
                    >
                      <IconComp className="w-2.5 h-2.5" style={{ color }} />
                    </div>
                    <div className="flex-1 min-w-0 text-left">
                      <div className="text-xs font-medium truncate group-hover:text-primary transition-colors">
                        {label}
                        {note && (
                          <span className="ml-1 font-normal text-muted-foreground/70">（{note}）</span>
                        )}
                      </div>
                      {def?.name && node?.data?.label && node.data.label !== def.name && (
                        <div className="text-[10px] text-muted-foreground/50 truncate">{def.name}</div>
                      )}
                    </div>
                  </button>
                );
              })
            ) : (
              <div className="px-4 py-6 text-center text-xs text-muted-foreground/50">
                {/* 列表里有节点数却拿回空数组 → 实际是拉取异常，不是真空工作流 */}
                {hoveredWorkflow?.nodeCount ? "节点加载失败，移开重新悬停可重试" : "该工作流暂无节点"}
              </div>
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

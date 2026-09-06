import { useState, useEffect, useRef } from "react";
import {
  CATEGORIES,
  type NodeTypeDef,
  PORT_COLORS,
  getAllNodeTypes,
  registerRuntimeNodeTypes,
} from "@/lib/workflowTypes";
import { listNodeTypes, type NodeTypeConfig } from "@/api/nodeTypes";
import NodeManager from "./NodeManager";
import {
  Film, Music, Subtitles, Mic, Mic2, Scissors, Brain, Languages, AlignLeft,
  FileText, Volume2, Merge, Clapperboard, Image, Stamp, Download,
  Upload, Wrench, ChevronDown, ChevronRight, ChevronLeft, GripVertical, Settings2,
  Play, Eye, PanelRightClose, RefreshCw, Sparkles, Share2, ChevronsDownUp, ChevronsUpDown,
  Captions, SlidersHorizontal, Grid3x3, Ratio, Video, UserRound, AudioLines, UserRoundPlus,
} from "lucide-react";
import { cn } from "@/lib/utils";

const ICON_MAP: Record<string, any> = {
  Film, Music, Subtitles, Mic, Mic2, Scissors, Brain, Languages, AlignLeft,
  FileText, Volume2, Merge, Clapperboard, Image, Stamp, Download,
  Upload, Wrench, Play, Eye, Sparkles, Share2, Captions, SlidersHorizontal,
  Grid3x3, Ratio, Video, UserRound, AudioLines, UserRoundPlus,
};

interface Props {
  onAddNode: (nodeType: NodeTypeDef) => void;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
}

export default function NodePalette({ onAddNode, collapsed, onToggleCollapse }: Props) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({
    io: true,
    preview: false,
    audio: false,
    video: false,
    ai_gen: false,
    translation: false,
    flow_control: false,
    network_request: false,
    aigc: false,
    asset: false,
    agent: false,
    utility: true,
    file: false,
    hyperframes: true,
  });
  const [managerOpen, setManagerOpen] = useState(false);
  const [nodeRegistry, setNodeRegistry] = useState<NodeTypeDef[]>(getAllNodeTypes());
  const [hoveredNode, setHoveredNode] = useState<{ node: NodeTypeDef; rect: DOMRect } | null>(null);
  const hoverTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadNodeRegistry = async () => {
    try {
      const nodes = await listNodeTypes();
      const mapped: NodeTypeDef[] = nodes.map((n) => ({
        id: n.id,
        name: n.name,
        category: (n.category as any) || "utility",
        description: n.description || "",
        icon: n.icon || "Wrench",
        color: n.color || "#6b7280",
        inputs: (n.inputs || []).map((p: any) => ({ id: p.id, label: p.label, type: p.type, required: p.required })),
        outputs: (n.outputs || []).map((p: any) => ({ id: p.id, label: p.label, type: p.type, required: p.required })),
        defaultConfig: n.defaultConfig || {},
        configFields: n.configFields || [],
        isBuiltIn: n.isBuiltIn ?? false,
        kind: n.kind,
        groupDefinition: n.groupDefinition as NodeTypeDef["groupDefinition"],
      }));
      registerRuntimeNodeTypes(mapped);
      setNodeRegistry(getAllNodeTypes());
    } catch (e) {
      console.error("Failed to load node registry", e);
      setNodeRegistry(getAllNodeTypes());
    }
  };

  useEffect(() => {
    loadNodeRegistry();
  }, []);

  const toggleCategory = (cat: string) => {
    setExpanded((prev) => ({ ...prev, [cat]: !prev[cat] }));
  };

  const allExpanded = Object.values(expanded).every(Boolean);

  const toggleAll = () => {
    const newVal = !allExpanded;
    setExpanded((prev) => {
      const next: Record<string, boolean> = {};
      for (const key of Object.keys(prev)) next[key] = newVal;
      return next;
    });
  };

  const handleDragStart = (e: React.DragEvent, nodeType: NodeTypeDef) => {
    e.dataTransfer.setData("application/reactflow", JSON.stringify(nodeType));
    e.dataTransfer.effectAllowed = "move";
  };

  const categories = Object.entries(CATEGORIES) as [string, { label: string; color: string; icon: string }][];

  if (collapsed) {
    return (
      <>
        <div className="w-9 border-l border-border bg-card flex flex-col items-center pt-2 flex-shrink-0 shadow-[-4px_0_12px_rgba(0,0,0,0.08)]">
          <button
            onClick={onToggleCollapse}
            className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
            title="展开节点面板"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
        </div>
        <NodeManager open={managerOpen} onClose={() => { setManagerOpen(false); loadNodeRegistry(); }} />
      </>
    );
  }

  return (
    <>
      <div className="w-60 border-l border-border bg-card flex flex-col h-full overflow-hidden flex-shrink-0 shadow-[-4px_0_12px_rgba(0,0,0,0.08)]">
        {/* Header with manager button */}
        <div className="px-3 py-2.5 border-b border-border flex-shrink-0">
          <div className="flex items-center justify-between">
            <span className="text-sm font-bold text-muted-foreground">节点面板</span>
            <div className="flex items-center gap-1">
              <button
                onClick={toggleAll}
                className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary/60 transition-colors"
                title={allExpanded ? "全部折叠" : "全部展开"}
              >
                {allExpanded ? <ChevronsDownUp className="w-3.5 h-3.5" /> : <ChevronsUpDown className="w-3.5 h-3.5" />}
              </button>
              <button
                onClick={loadNodeRegistry}
                className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary/60 transition-colors"
                title="刷新节点列表"
              >
                <RefreshCw className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={() => setManagerOpen(true)}
                className="flex items-center gap-1 px-2 py-1 text-xs rounded-md bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
                title="管理器"
              >
                <Settings2 className="w-3 h-3" />
                管理器
              </button>
              <button
                onClick={onToggleCollapse}
                className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary/60 transition-colors"
                title="折叠节点面板"
              >
                <ChevronRight className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
          <div className="text-[9px] text-muted-foreground/50 mt-0.5">拖拽到画布区</div>
        </div>
        <div className="flex-1 overflow-y-auto px-2 py-2 space-y-1">
          {categories.map(([cat, cfg]) => {
            const catNodes = nodeRegistry.filter((n) => n.category === cat);
            if (catNodes.length === 0) return null;
            return (
              <div key={cat}>
                <button
                  onClick={() => toggleCategory(cat)}
                  className="w-full flex items-center gap-1.5 text-xs font-semibold text-muted-foreground hover:text-foreground py-1.5 px-1 rounded-md hover:bg-secondary/50 transition-colors"
                >
                  {expanded[cat] ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                  <span style={{ color: cfg.color }}>{cfg.label}</span>
                </button>
                {expanded[cat] && (
                  <div className="space-y-1 pb-1">
                    {catNodes.map((nodeType) => {
                      const IconComp = ICON_MAP[nodeType.icon] || Wrench;
                      const isCustom = nodeType.isBuiltIn === false;
                      return (
                        <div
                          key={nodeType.id}
                          draggable
                          onDragStart={(e) => handleDragStart(e, nodeType)}
                          onMouseEnter={(e) => {
                            if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current);
                            // 立即取矩形（500ms 后再取 currentTarget 可能已卸载为 null）
                            const rect = e.currentTarget.getBoundingClientRect();
                            hoverTimerRef.current = setTimeout(() => {
                              setHoveredNode({ node: nodeType, rect });
                            }, 500);
                          }}
                          onMouseLeave={() => {
                            if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current);
                            setHoveredNode(null);
                          }}
                          className={cn(
                            "flex items-center gap-2 px-2.5 py-2 rounded-lg border border-border",
                            "bg-background hover:bg-primary/5 hover:border-primary/30 hover:shadow-sm",
                            "cursor-grab active:cursor-grabbing transition-all duration-150",
                          )}
                        >
                          <GripVertical className="w-3 h-3 text-muted-foreground/30 flex-shrink-0" />
                          <div
                            className="w-6 h-6 rounded-md flex items-center justify-center flex-shrink-0"
                            style={{ backgroundColor: nodeType.color + "30" }}
                          >
                            <IconComp className="w-3 h-3" style={{ color: nodeType.color }} />
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="text-xs font-semibold truncate leading-tight flex items-center gap-1">
                              {nodeType.name}
                              {isCustom && (
                                <span className="text-[8px] px-1 py-0 rounded bg-primary/10 text-primary">自定义</span>
                              )}
                            </div>
                            <div className="flex gap-0.5 mt-0.5">
                              {nodeType.inputs.map((p) => (
                                <span key={p.id} className="w-2 h-2 rounded-full" style={{ backgroundColor: p.color || PORT_COLORS[p.type] }} />
                              ))}
                              {nodeType.outputs.map((p) => (
                                <span key={p.id} className="w-1.5 h-1.5 rounded-full border" style={{ borderColor: p.color || PORT_COLORS[p.type], backgroundColor: "transparent" }} />
                              ))}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
      <NodeManager open={managerOpen} onClose={() => { setManagerOpen(false); loadNodeRegistry(); }} />

      {/* Fixed-position hover tooltip for node palette */}
      {hoveredNode && (
        <div
          className="fixed z-[9999] w-56 p-3 rounded-xl border border-border bg-card shadow-2xl"
          style={{
            right: window.innerWidth - hoveredNode.rect.left + 8,
            top: hoveredNode.rect.top,
          }}
          onMouseEnter={() => {
            if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current);
          }}
          onMouseLeave={() => {
            if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current);
            setHoveredNode(null);
          }}
        >
          <div className="flex items-center gap-2 mb-2">
            <div
              className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
              style={{ backgroundColor: hoveredNode.node.color + "30" }}
            >
              {(() => {
                const IconComp = ICON_MAP[hoveredNode.node.icon] || Wrench;
                return <IconComp className="w-4 h-4" style={{ color: hoveredNode.node.color }} />;
              })()}
            </div>
            <div className="min-w-0">
              <div className="text-sm font-bold truncate">{hoveredNode.node.name}</div>
              <div className="text-[10px] text-muted-foreground">
                {CATEGORIES[hoveredNode.node.category]?.label || hoveredNode.node.category}
              </div>
            </div>
          </div>
          {hoveredNode.node.description && (
            <p className="text-xs text-muted-foreground mb-2 leading-relaxed">{hoveredNode.node.description}</p>
          )}
          <div className="space-y-1.5 text-[10px]">
            {hoveredNode.node.inputs.length > 0 && (
              <div className="flex items-center gap-1 flex-wrap">
                <span className="text-muted-foreground font-medium">输入:</span>
                {hoveredNode.node.inputs.map((p) => (
                  <span key={p.id} className="inline-flex items-center gap-0.5 px-1 py-0 rounded-full border border-border/60 bg-background">
                    <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: p.color || PORT_COLORS[p.type] }} />
                    {p.label}
                  </span>
                ))}
              </div>
            )}
            {hoveredNode.node.outputs.length > 0 && (
              <div className="flex items-center gap-1 flex-wrap">
                <span className="text-muted-foreground font-medium">输出:</span>
                {hoveredNode.node.outputs.map((p) => (
                  <span key={p.id} className="inline-flex items-center gap-0.5 px-1 py-0 rounded-full border border-border/60 bg-background">
                    <span className="w-1.5 h-1.5 rounded-full border" style={{ borderColor: p.color || PORT_COLORS[p.type] }} />
                    {p.label}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}

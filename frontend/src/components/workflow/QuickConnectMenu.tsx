import { useState, useEffect, useRef } from "react";
import {
  CATEGORIES, PORT_COLORS, PORT_LABELS, isPreviewNode,
  type PortType, type DownstreamCandidate,
} from "@/lib/workflowTypes";
import { cn } from "@/lib/utils";
import {
  Film, Music, Subtitles, Mic, Mic2, Scissors, Brain, Languages, AlignLeft,
  FileText, Volume2, Merge, Clapperboard, Image, Stamp, Download,
  Upload, Wrench, Play, Eye, Sparkles, Share2, Captions, SlidersHorizontal,
  Layers, Eraser, Type, Search, X,
} from "lucide-react";

const ICON_MAP: Record<string, any> = {
  Film, Music, Subtitles, Mic, Mic2, Scissors, Brain, Languages, AlignLeft,
  FileText, Volume2, Merge, Clapperboard, Image, Stamp, Download,
  Upload, Wrench, Play, Eye, Sparkles, Share2, Captions, SlidersHorizontal,
  Layers, Eraser, Type, Boxes: Layers,
};

export interface QuickConnectRequest {
  screen: { x: number; y: number };
  /** 源节点 id / 名称 / 输出句柄 id */
  sourceNodeId: string;
  sourceNodeName: string;
  sourceHandle: string;
  sourcePortLabel: string;
  sourcePortType: PortType;
  candidates: DownstreamCandidate[];
}

interface Props {
  visible: boolean;
  request: QuickConnectRequest | null;
  onSelect: (candidate: DownstreamCandidate) => void;
  onClose: () => void;
}

const PANEL_WIDTH = 288;
const PANEL_MAX_HEIGHT = 440;

/**
 * 从输出端点拖线到空白处松开时弹出的"可接入下游节点"面板。
 * 点击条目即完成"放入节点 + 自动连线"，预览类节点排在最前。
 */
export default function QuickConnectMenu({ visible, request, onSelect, onClose }: Props) {
  const [search, setSearch] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const panelRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!visible) return;
    setSearch("");
    setActiveIndex(0);
    const timer = window.setTimeout(() => searchRef.current?.focus(), 30);
    return () => window.clearTimeout(timer);
  }, [visible, request]);

  // 点击面板外 / Esc 关闭
  useEffect(() => {
    if (!visible) return;
    const handleDown = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) onClose();
    };
    const handleKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("mousedown", handleDown, true);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleDown, true);
      document.removeEventListener("keydown", handleKey);
    };
  }, [visible, onClose]);

  // 保证键盘高亮项在可视范围内
  useEffect(() => {
    if (!visible) return;
    const el = listRef.current?.querySelector<HTMLElement>(`[data-idx="${activeIndex}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [activeIndex, visible, request]);

  if (!visible || !request) return null;

  const keyword = search.trim().toLowerCase();
  const filtered = keyword
    ? request.candidates.filter(
      (c) =>
        c.nodeType.name.toLowerCase().includes(keyword) ||
        c.nodeType.id.toLowerCase().includes(keyword) ||
        (c.nodeType.description || "").toLowerCase().includes(keyword)
    )
    : request.candidates;
  const previewCount = filtered.filter((c) => isPreviewNode(c.nodeType)).length;

  const commit = (candidate: DownstreamCandidate) => {
    onSelect(candidate);
    onClose();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const target = filtered[activeIndex];
      if (target) commit(target);
    }
  };

  const srcColor = PORT_COLORS[request.sourcePortType] || "#6b7280";
  const srcTypeLabel = PORT_LABELS[request.sourcePortType] || request.sourcePortType;

  let px = request.screen.x;
  let py = request.screen.y;
  if (px + PANEL_WIDTH > window.innerWidth - 8) px = Math.max(8, window.innerWidth - PANEL_WIDTH - 8);
  if (py + PANEL_MAX_HEIGHT > window.innerHeight - 8) py = Math.max(8, window.innerHeight - PANEL_MAX_HEIGHT - 8);

  return (
    <div
      ref={panelRef}
      className="fixed z-[9999] flex flex-col bg-card border border-border rounded-xl shadow-2xl shadow-black/25 overflow-hidden"
      style={{ left: px, top: py, width: PANEL_WIDTH, maxHeight: PANEL_MAX_HEIGHT }}
      onContextMenu={(e) => e.preventDefault()}
    >
      {/* 头部：来源端口 */}
      <div className="flex-shrink-0 px-3 py-2 border-b border-border bg-secondary/40">
        <div className="flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: srcColor }} />
          <span className="text-[11px] font-semibold text-muted-foreground truncate">
            从「{request.sourceNodeName} · {request.sourcePortLabel}」连出
          </span>
          <button
            onClick={onClose}
            className="ml-auto w-5 h-5 rounded flex items-center justify-center text-muted-foreground/60 hover:text-foreground hover:bg-foreground/10 flex-shrink-0"
            title="关闭"
          >
            <X className="w-3 h-3" />
          </button>
        </div>
        <div className="mt-0.5 text-[10px] text-muted-foreground/70">
          {srcTypeLabel} 输出 · 选择下方节点即可自动连线
        </div>
      </div>

      {/* 搜索 */}
      <div className="flex-shrink-0 px-2.5 py-2 border-b border-border/50">
        <div className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg bg-background/60 border border-border/50">
          <Search className="w-3.5 h-3.5 text-muted-foreground/60 flex-shrink-0" />
          <input
            ref={searchRef}
            value={search}
            onChange={(e) => { setSearch(e.target.value); setActiveIndex(0); }}
            onKeyDown={handleKeyDown}
            placeholder="搜索可接入的节点..."
            className="flex-1 bg-transparent text-xs outline-none placeholder:text-muted-foreground/40"
          />
        </div>
      </div>

      {/* 候选列表 */}
      <div ref={listRef} className="flex-1 overflow-y-auto py-1">
        {filtered.length === 0 ? (
          <div className="px-4 py-8 text-center text-xs text-muted-foreground/60">
            {request.candidates.length === 0 ? "没有节点可接收该输出" : "无匹配节点"}
          </div>
        ) : (
          filtered.map((candidate, index) => {
            const def = candidate.nodeType;
            const IconComp = ICON_MAP[def.icon] || Wrench;
            const showPreviewTitle = index === 0 && previewCount > 0;
            const showOthersTitle = index === previewCount && previewCount > 0 && previewCount < filtered.length;
            return (
              <div key={def.id}>
                {showPreviewTitle && <GroupTitle text="预览节点" />}
                {showOthersTitle && <GroupTitle text="其他节点" />}
                <button
                  data-idx={index}
                  onClick={() => commit(candidate)}
                  onMouseEnter={() => setActiveIndex(index)}
                  title={def.description || def.name}
                  className={cn(
                    "w-full flex items-center gap-2 px-2.5 py-1.5 text-left transition-colors",
                    activeIndex === index ? "bg-primary/10" : "hover:bg-secondary/60"
                  )}
                >
                  <div
                    className="w-6 h-6 rounded-md flex items-center justify-center flex-shrink-0"
                    style={{ backgroundColor: def.color + "25" }}
                  >
                    <IconComp className="w-3 h-3" style={{ color: def.color }} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1">
                      <span className="text-xs font-semibold truncate">{def.name}</span>
                      {def.isBuiltIn === false && (
                        <span className="text-[8px] px-1 py-px rounded bg-primary/10 text-primary flex-shrink-0">自定义</span>
                      )}
                    </div>
                    <div className="flex items-center gap-1 text-[10px] text-muted-foreground/70 min-w-0">
                      <span className="truncate">{CATEGORIES[def.category]?.label || def.category}</span>
                      <span className="text-muted-foreground/30">·</span>
                      <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ backgroundColor: candidate.port.color || PORT_COLORS[candidate.port.type] }} />
                      <span className="truncate">接入 {candidate.port.label}</span>
                    </div>
                  </div>
                </button>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

function GroupTitle({ text }: { text: string }) {
  return (
    <div className="px-2.5 pt-1.5 pb-0.5 text-[10px] font-semibold text-muted-foreground/50">{text}</div>
  );
}

// -*- coding: utf-8 -*-
/**
 * 创作·画布 —— 基于 Toonflow 创作流程的自建前端（P2：全链数据渲染 + 删除/重生）。
 *
 * 布局：左侧主区 React Flow 无限画布（章节/剧本/资产/分镜/视频 节点，按阶段泳道自动布局），
 * 右侧 Agent 会话侧边栏（P3 接会话流），顶部流水线阶段操作条。
 * 制作流程与 Agent/Skill/提示词资产基于 Toonflow (Apache-2.0) 迁移。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  useEdgesState,
  useNodesState,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  BookOpen,
  Bot,
  Clapperboard,
  FileText,
  Film,
  Image as ImageIcon,
  Loader2,
  MoreHorizontal,
  Pencil,
  Plus,
  RefreshCw,
  RotateCw,
  Send,
  Settings,
  SlidersHorizontal,

  Sparkles,
  Trash2,
  UserRound,
  Users,
  Wand2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import client from "@/api/client";
import { settingsApi } from "@/api/settings";
import toonflowApi, { ProjectCreatePayload, TfProject } from "@/api/toonflow";

// ---------------- 快照类型 ----------------
interface Snapshot {
  project: { id: number; name: string; artStyle: string; videoRatio: string };
  chapters: { id: number; chapter: string; event: string; eventState: number; chars: number }[];
  scripts: { id: number; title: string; extractState: number; chars: number }[];
  assets: { id: number; name: string; type: string; describe: string; prompt: string; imageUrl: string; imageId: number | null }[];
  storyboards: {
    id: number; orderNo: number; videoDesc: string; prompt: string; videoPrompt: string;
    duration: number; imageUrl: string; state: string; videoUrl: string;
  }[];
  videos: { id: number; storyboardId: number | null; prompt: string; candidates: { id: number; url: string; state: string; selected: boolean }[] }[];
  bindings: { id: number; assetId: number; assetName: string; audioId: string }[];
  /** 后台任务活动计数（type → 生成中数量），执行状态条数据源 */
  activities: Record<string, number>;
}

type CanvasData = {
  kind: "chapter" | "script" | "asset" | "storyboard" | "video";
  title: string;
  desc: string;
  imageUrl?: string;
  videoUrl?: string;
  state?: string;
  badge?: string;
  projectId: number;
  /** 各类型实体 id（卡片操作需要） */
  chapterId?: number;
  scriptId?: number;
  assetId?: number;
  storyboardId?: number;
  videoId?: number;
  trackId?: number;
  /** 已生成内容标记，用于决定「生成」还是「重生」 */
  hasImage?: boolean;
  hasVideo?: boolean;
  /** 视频候选（视频卡片操作菜单用） */
  candidates?: { id: number; url: string; state: string; selected: boolean }[];
};

const KIND_META: Record<CanvasData["kind"], { label: string; color: string; icon: typeof Film }> = {
  chapter: { label: "章节", color: "#64748b", icon: Pencil },
  script: { label: "剧本", color: "#0ea5e9", icon: Pencil },
  asset: { label: "资产", color: "#8b5cf6", icon: UserRound },
  storyboard: { label: "分镜", color: "#f59e0b", icon: Clapperboard },
  video: { label: "视频", color: "#ef4444", icon: Film },
};

/** 通用画布节点卡片：类型徽标 + 媒体预览 + 删除/重生 */
function CanvasNodeCard({ data }: NodeProps) {
  const d = data as CanvasData;
  const meta = KIND_META[d.kind] || KIND_META.asset;
  const Icon = meta.icon;
  const generating = d.state === "生成中";

  return (
    <div className="w-52 rounded-xl border border-border/60 bg-background shadow-sm overflow-hidden">
      <div className="flex items-center gap-1.5 px-2 py-1.5" style={{ background: `${meta.color}18` }}>
        <Icon className="w-3 h-3" style={{ color: meta.color }} />
        <span className="text-xs font-semibold" style={{ color: meta.color }}>{meta.label}</span>
        {d.badge && <span className="text-[11px] px-1 rounded bg-muted text-muted-foreground">{d.badge}</span>}
        <div className="ml-auto flex items-center gap-1">
          {generating && <Loader2 className="w-3 h-3 animate-spin text-primary" />}
          {d.state && !generating && <span className="text-[11px] text-muted-foreground">{d.state}</span>}
          <button
            type="button"
            title={d.kind === "asset" ? "重生资产图" : d.kind === "storyboard" ? "重生分镜图" : undefined}
            className="text-muted-foreground hover:text-primary disabled:opacity-30"
            disabled={generating}
            onClick={(e) => {
              e.stopPropagation();
              (window as any).__tfCanvasAction?.("regenerate", d);
            }}
          >
            <RotateCw className="w-3 h-3" />
          </button>
          <button
            type="button"
            title="删除"
            className="text-muted-foreground hover:text-destructive"
            onClick={(e) => {
              e.stopPropagation();
              (window as any).__tfCanvasAction?.("delete", d);
            }}
          >
            <Trash2 className="w-3 h-3" />
          </button>
          <button
            type="button"
            title="更多操作"
            className="text-muted-foreground hover:text-primary"
            onClick={(e) => {
              e.stopPropagation();
              (window as any).__tfCanvasAction?.("menu", d, e);
            }}
          >
            <MoreHorizontal className="w-3 h-3" />
          </button>
        </div>
      </div>
      {d.imageUrl ? (
        <img src={d.imageUrl} alt="" loading="lazy" className="w-full h-24 object-cover" />
      ) : d.videoUrl ? (
        <video src={d.videoUrl} controls preload="metadata" className="w-full h-24 bg-black" />
      ) : null}
      <div className="px-2 py-1.5">
        <div className="text-xs font-semibold truncate">{d.title}</div>
        {d.desc && <div className="text-[11px] text-muted-foreground line-clamp-2 leading-snug mt-0.5">{d.desc}</div>}
      </div>
      <Handle type="source" position={Position.Right} isConnectable={false} className="!opacity-0" />
      <Handle type="target" position={Position.Left} isConnectable={false} className="!opacity-0" />
    </div>
  );
}

const nodeTypes = { tfCard: CanvasNodeCard };

// ---------------- 会话持久化（切页/刷新后原地续上） ----------------
const LS_ACTIVE = "tf-canvas:active-project";
const LS_VIEWPORT = "tf-canvas:viewport";
const LS_CHAT = (id: number) => `tf-canvas:chat:${id}`;
const LS_SNAP = (id: number) => `tf-canvas:snapshot:${id}`;

function readJSON<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function writeJSON(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* 容量超限时静默降级 */
  }
}

// ---------------- 项目设置可选项 ----------------
const VIDEO_RATIOS = [
  { value: "16:9", label: "16:9 横屏" },
  { value: "9:16", label: "9:16 竖屏（短视频首选）" },
  { value: "1:1", label: "1:1 方形" },
  { value: "4:3", label: "4:3" },
  { value: "21:9", label: "21:9 宽银幕" },
];
const VIDEO_RESOLUTIONS = [
  { value: "480P", label: "480P · 省时长/低成本" },
  { value: "720P", label: "720P · 推荐" },
  { value: "1080P", label: "1080P · 高清/成本高" },
];
const IMAGE_QUALITIES = [
  { value: "1K", label: "1K · 推荐" },
  { value: "2K", label: "2K" },
  { value: "4K", label: "4K" },
];
/** 导演风格预设 → 写入项目 directorManual（可自由改写） */
const DIRECTOR_PRESETS = [
  { label: "不设定", text: "" },
  { label: "快节奏反转爽剧", text: "节奏：快。每 15 秒内给出一个信息增量或反转；前三镜必须建立冲突，结尾留钩子。镜头偏短、剪辑密集，允许跳切强化推进感。" },
  { label: "悬疑推进", text: "节奏：中偏慢，重氛围。优先展示线索与环境细节，人物反应后置；多用客观视角与局部特写制造悬念，避免提前揭示动机。" },
  { label: "情感细腻", text: "节奏：中。以人物情绪弧线为主，多近景/特写捕捉微表情，保留留白与停顿的呼吸感；音效服务情绪不抢戏。" },
  { label: "史诗叙事", text: "节奏：宏大稳重。多用远景/大全景建立空间与规模，群像调度清晰；重要时刻给足停顿与仪式感，镜头运动克制。" },
  { label: "幽默轻喜", text: "节奏：轻快。强调反差与节奏点，台词密度略高；可接受夸张表演与俏皮构图，收尾给笑点或反转。" },
];

/** 快照 → 泳道布局节点（按阶段横向排布） */
function snapshotToNodes(snap: Snapshot, projectId: number) {
  const nodes: any[] = [];
  let col = 0;
  const LANE_W = 280;

  const place = (kind: CanvasData["kind"], items: any[], yBase = 40, yStep = 230) => {
    items.forEach((item, i) => {
      nodes.push({
        id: item.nid,
        type: "tfCard",
        position: { x: col * LANE_W, y: yBase + i * yStep },
        data: item.data,
        draggable: true,
      });
    });
    col += 1;
  };

  // 泳道：章节 → 剧本 → 资产 → 分镜 → 视频
  place("chapter", snap.chapters.slice(0, 9).map((c) => ({
    nid: `ch-${c.id}`,
    data: { kind: "chapter", title: c.chapter || "章节", desc: c.event || "（未提取事件）",
            badge: c.eventState === 1 ? "已提取" : c.eventState === 2 ? "提取中" : c.eventState === -1 ? "失败" : "未提取",
            projectId, chapterId: c.id } as CanvasData,
  })));
  place("script", snap.scripts.slice(0, 6).map((s) => ({
    nid: `sc-${s.id}`,
    data: { kind: "script", title: s.title, desc: `共 ${s.chars} 字`,
            badge: s.extractState === 1 ? "已提取" : s.extractState === -1 ? "失败" : s.extractState === 2 ? "提取中" : "待提取",
            projectId, scriptId: s.id } as CanvasData,
  })));
  // 资产按类型拆分泳道：角色 / 场景 / 道具 / 其他（各占一列）
  const ASSET_TYPE_LABEL: Record<string, string> = {
    role: "角色", scene: "场景", tool: "道具", clip: "分镜片段", audio: "音频",
  };
  const assetTypeOrder = ["role", "scene", "tool"];
  const assetGroups = new Map<string, typeof snap.assets>();
  for (const a of snap.assets) {
    const t = assetTypeOrder.includes(a.type) ? a.type : (a.type || "other");
    if (!assetGroups.has(t)) assetGroups.set(t, []);
    assetGroups.get(t)!.push(a);
  }
  const assetLaneTypes = [
    ...assetTypeOrder.filter((t) => assetGroups.has(t)),
    ...[...assetGroups.keys()].filter((t) => !assetTypeOrder.includes(t)),
  ];
  for (const t of assetLaneTypes) {
    place("asset", (assetGroups.get(t) || []).map((a) => ({
      nid: `as-${a.id}`,
      data: { kind: "asset", title: a.name, desc: a.describe,
              imageUrl: a.imageUrl, badge: ASSET_TYPE_LABEL[a.type] || a.type, projectId,
              imageId: a.imageId, assetId: a.id } as CanvasData,
    })));
  }
  place("storyboard", snap.storyboards.map((b) => ({
    nid: `sb-${b.id}`,
    data: { kind: "storyboard", title: `#${b.orderNo} · ${b.duration}s`, desc: b.videoDesc.slice(0, 60),
            imageUrl: b.imageUrl, state: b.state || (b.imageUrl ? "已完成" : ""), projectId,
            storyboardId: b.id, hasImage: !!b.imageUrl, hasVideo: !!b.videoUrl } as CanvasData,
  })));
  const videoItems = snap.videos.filter((v) => v.candidates.length);
  place("video", videoItems.map((v) => {
    const sel = v.candidates.find((c) => c.selected) || v.candidates[0];
    return {
      nid: `vd-${v.id}`,
      data: { kind: "video", title: `轨道 ${v.storyboardId ?? "-"}`, desc: v.prompt.slice(0, 60),
              videoUrl: sel?.url, state: sel?.state, projectId,
              videoId: sel?.id, trackId: v.id, storyboardId: v.storyboardId ?? undefined,
              candidates: v.candidates } as CanvasData,
    };
  }));
  return nodes;
}

// ---------------- 主组件 ----------------
export default function CreationCanvas() {
  const [projects, setProjects] = useState<TfProject[]>([]);
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState("");
  const [activeId, setActiveId] = useState<number | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<any>([]);
  const [edges, , onEdgesChange] = useEdgesState<any>([]);
  const [messages, setMessages] = useState<ChatMessage[]>(() => {
    const savedId = Number(localStorage.getItem(LS_ACTIVE) || 0);
    const saved = savedId ? readJSON<ChatMessage[]>(LS_CHAT(savedId)) : null;
    return saved?.length ? saved : [
      { role: "assistant", kind: "md", text: "我是创作 Agent（决策层）。直接下达创作指令，我会拆解任务、派发执行层子 Agent 并汇报进度。" },
    ];
  });

  // 切换项目时载入该项目的会话记录
  useEffect(() => {
    if (!activeId) return;
    const saved = readJSON<ChatMessage[]>(LS_CHAT(activeId));
    setMessages(saved?.length ? saved : [
      { role: "assistant", kind: "md", text: "我是创作 Agent（决策层）。直接下达创作指令，我会拆解任务、派发执行层子 Agent 并汇报进度。" },
    ]);
  }, [activeId]);

  // 会话记录持久化（每项目保留最近 80 条）
  useEffect(() => {
    if (!activeId) return;
    writeJSON(LS_CHAT(activeId), messages.slice(-80));
  }, [messages, activeId]);
  const [draft, setDraft] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const pollRef = useRef<number | null>(null);

  const loadProjects = useCallback(() => {
    toonflowApi.listProjects().then(({ data }) => {
      const list: TfProject[] = data.projects || [];
      setProjects(list);
      const saved = Number(localStorage.getItem(LS_ACTIVE) || 0);
      const restored = saved && list.some((p) => p.id === saved) ? saved : list[0]?.id ?? null;
      setActiveId((prev) => prev ?? restored);
    }).catch(() => undefined);
  }, []);

  const loadSnapshot = useCallback((id: number) => {
    // 先用缓存快照瞬时恢复画面，再向服务端刷新
    const cached = readJSON<Snapshot>(LS_SNAP(id));
    if (cached) {
      setSnap(cached);
      setNodes(snapshotToNodes(cached, id));
    }
    setLoading(true);
    toonflowApi.getCanvas(id)
      .then(({ data }) => {
        setSnap(data);
        setNodes(snapshotToNodes(data as Snapshot, id));
        writeJSON(LS_SNAP(id), data);
      })
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, [setNodes]);

  // 记住当前项目，切走/刷新后回到同一个项目
  useEffect(() => {
    if (activeId) localStorage.setItem(LS_ACTIVE, String(activeId));
  }, [activeId]);

  // 记住画布视口（缩放/平移）
  const [initialViewport] = useState(() => readJSON<{ x: number; y: number; zoom: number }>(LS_VIEWPORT));

  useEffect(() => { loadProjects(); }, [loadProjects]);

  useEffect(() => {
    if (activeId) loadSnapshot(activeId);
    else { setSnap(null); setNodes([]); }
  }, [activeId, loadSnapshot, setNodes]);

  // 有进行中状态时轮询
  const hasPending = useMemo(() => {
    if (!snap) return false;
    return snap.chapters.some((c) => c.eventState === 2)
      || snap.scripts.some((s) => s.extractState === 2)
      || snap.storyboards.some((b) => b.state === "生成中")
      || snap.videos.some((v) => v.candidates.some((c) => c.state === "生成中"))
      || Object.values(snap.activities || {}).some((n) => n > 0);
  }, [snap]);

  useEffect(() => {
    if (!hasPending || !activeId) return;
    pollRef.current = window.setInterval(() => loadSnapshot(activeId), 5000);
    return () => { if (pollRef.current) window.clearInterval(pollRef.current); };
  }, [hasPending, activeId, loadSnapshot]);

  const runStage = (action: string, body: any = {}) => {
    if (!activeId) return;
    setBusy(action);
    // 上游三步走专用路由；其余走通用流水线映射
    let req: Promise<unknown>;
    if (action === "script") req = toonflowApi.makeScriptDraft(activeId);
    else if (action === "extract") req = latestScript
      ? toonflowApi.extractScriptAssets(latestScript.id)
      : Promise.reject(new Error("缺少剧本"));
    else if (action === "assetImages") req = toonflowApi.generateAssetImages(activeId, body.ids || []);
    else req = toonflowApi.runStage(activeId, action, body);
    req
      .then(() => {
        // 立即刷一次拿"已入队"状态；稍后再刷一次等 worker 写上台账（线程池可能排队）
        loadSnapshot(activeId);
        window.setTimeout(() => { if (activeId) loadSnapshot(activeId); setBusy(""); }, 1500);
      })
      .catch(() => setBusy(""));
  };
  const [novelOpen, setNovelOpen] = useState(false);

  // ---------------- 卡片操作：快捷按钮 + 「更多」菜单 + 编辑弹窗 ----------------
  const [menu, setMenu] = useState<{ x: number; y: number; data: CanvasData } | null>(null);
  const [editor, setEditor] = useState<CanvasData | null>(null);

  const refresh = useCallback(() => {
    if (activeId) loadSnapshot(activeId);
  }, [activeId, loadSnapshot]);

  const doDelete = useCallback((d: CanvasData) => {
    if (d.assetId) toonflowApi.deleteAsset(d.assetId).then(refresh);
    else if (d.chapterId) toonflowApi.deleteNovel(d.chapterId).then(refresh);
    else if (d.scriptId) toonflowApi.deleteScript(d.scriptId).then(refresh);
    else if (d.storyboardId) toonflowApi.deleteStoryboard(d.storyboardId).then(refresh);
    else if (d.videoId) toonflowApi.deleteVideo(d.videoId).then(refresh);
  }, [refresh]);

  const doRegenerate = useCallback((d: CanvasData) => {
    if (d.assetId) toonflowApi.regenerateAssetImage(d.assetId).then(refresh);
    else if (d.storyboardId && !d.videoUrl) toonflowApi.regenerateStoryboardImage(d.storyboardId).then(refresh);
    else if (d.chapterId) toonflowApi.extractNovelEvent(d.chapterId).then(refresh);
    else if (d.scriptId) toonflowApi.extractScriptAssets(d.scriptId).then(refresh);
  }, [refresh]);

  /** 卡片「更多」菜单项（按类型给足手动控制权） */
  const buildMenu = useCallback((d: CanvasData): { label: string; danger?: boolean; run: () => void }[] => {
    const items: { label: string; danger?: boolean; run: () => void }[] = [];
    if (d.kind === "chapter" && d.chapterId) {
      const id = d.chapterId;
      items.push({ label: "重新提取事件", run: () => toonflowApi.extractNovelEvent(id).then(refresh) });
      items.push({ label: "编辑章节文本", run: () => setEditor(d) });
      items.push({ label: "删除章节", danger: true, run: () => toonflowApi.deleteNovel(id).then(refresh) });
    } else if (d.kind === "script" && d.scriptId) {
      const id = d.scriptId;
      items.push({ label: "编辑剧本", run: () => setEditor(d) });
      items.push({ label: "重新提取资产", run: () => toonflowApi.extractScriptAssets(id).then(refresh) });
      items.push({ label: "删除剧本", danger: true, run: () => toonflowApi.deleteScript(id).then(refresh) });
    } else if (d.kind === "asset" && d.assetId) {
      const id = d.assetId;
      items.push({ label: "编辑资产信息", run: () => setEditor(d) });
      items.push({ label: d.hasImage ? "重生资产图" : "生成资产图", run: () => toonflowApi.regenerateAssetImage(id).then(refresh) });
      items.push({ label: "删除资产", danger: true, run: () => toonflowApi.deleteAsset(id).then(refresh) });
    } else if (d.kind === "storyboard" && d.storyboardId && activeId) {
      const id = d.storyboardId;
      items.push({ label: "编辑分镜内容", run: () => setEditor(d) });
      items.push({ label: d.hasImage ? "重生分镜图" : "生成分镜图", run: () => toonflowApi.generateStoryboardImage(activeId, [id]).then(refresh) });
      items.push({ label: "生成该镜视频", run: () => toonflowApi.generateVideoForStoryboard(activeId, id).then(refresh) });
      items.push({ label: "删除分镜", danger: true, run: () => toonflowApi.deleteStoryboard(id).then(refresh) });
    } else if (d.kind === "video" && activeId) {
      if (d.storyboardId) {
        const sid = d.storyboardId;
        items.push({ label: "重新生成该镜视频", run: () => toonflowApi.generateVideoForStoryboard(activeId, sid).then(refresh) });
      }
      if (d.videoId && d.trackId) {
        const vid = d.videoId, tid = d.trackId;
        items.push({ label: "设为采用", run: () => toonflowApi.selectTrackVideo(tid, vid).then(refresh) });
        items.push({ label: "删除该候选", danger: true, run: () => toonflowApi.deleteVideo(vid).then(refresh) });
      }
    }
    return items;
  }, [activeId, refresh]);

  // 节点操作（删除/重生/菜单）——经全局桥接从节点卡片调用
  useEffect(() => {
    (window as any).__tfCanvasAction = (action: string, d: CanvasData, e?: MouseEvent) => {
      if (!activeId) return;
      if (action === "delete") doDelete(d);
      else if (action === "regenerate") doRegenerate(d);
      else if (action === "menu") setMenu({ x: e?.clientX ?? 200, y: e?.clientY ?? 200, data: d });
    };
    return () => { delete (window as any).__tfCanvasAction; };
  }, [activeId, doDelete, doRegenerate]);

  // 菜单/编辑弹窗点击外部关闭
  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, [menu]);

  const [projectDlg, setProjectDlg] = useState<{ open: boolean; initial: TfProject | null }>({ open: false, initial: null });

  const saveProject = (payload: ProjectPayload) => {
    if (projectDlg.initial) {
      toonflowApi.updateProject(projectDlg.initial.id, payload).then(() => {
        loadProjects();
        if (activeId) loadSnapshot(activeId);
        setProjectDlg({ open: false, initial: null });
      }).catch(() => undefined);
    } else {
      toonflowApi.createProject(payload).then(({ data }) => {
        loadProjects();
        if (data.project) setActiveId(data.project.id);
        setProjectDlg({ open: false, initial: null });
      }).catch(() => undefined);
    }
  };

  const importNovels = (chapters: { reel: string; chapter: string; chapterData: string }[]) => {
    if (!activeId) return;
    setBusy("novels");
    toonflowApi.addNovels(activeId, chapters)
      .then(() => {
        setNovelOpen(false);
        setMessages((prev) => [...prev,
          { role: "assistant" as const, kind: "md", text: `已导入 **${chapters.length} 章**，事件提取已在后台开始，完成后「生成剧本」按钮会自动亮起。` }]);
        window.setTimeout(() => loadSnapshot(activeId), 1200);
      })
      .catch(() => undefined)
      .finally(() => setBusy(""));
  };

  // ---------------- Agent 会话（WS 单向推送，Agent 服务端执行） ----------------
  const wsRef = useRef<WebSocket | null>(null);
  const [agentBusy, setAgentBusy] = useState(false);

  const appendLine = useCallback((m: Omit<ChatMessage, "role">) => {
    setMessages((prev) => [...prev, { role: "assistant" as const, ...m }]);
  }, []);

  const ensureWs = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState <= WebSocket.OPEN) return wsRef.current;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/tf-agent`);
    ws.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data);
        if (data.type === "message") appendLine({ kind: "md", text: data.content || "" });
        else if (data.type === "thinking") appendLine({ kind: "note", text: `💭 ${String(data.text || "").slice(-300)}` });
        else if (data.type === "tool") {
          const args = typeof data.args === "object" ? JSON.stringify(data.args) : String(data.args || "");
          appendLine({ kind: "tool", text: `${data.name} ${args.slice(0, 160)}` });
        } else if (data.type === "tool_result") {
          appendLine({ kind: "tool_result", text: String(data.preview || "") });
        } else if (data.type === "warn") appendLine({ kind: "note", text: `⚠️ ${data.message}` });
        else if (data.type === "error") appendLine({ kind: "note", text: `⛔ ${data.message}` });
        else if (data.type === "done") setAgentBusy(false);
      } catch { /* ignore */ }
    };
    ws.onclose = () => { wsRef.current = null; setAgentBusy(false); };
    wsRef.current = ws;
    return ws;
  }, [appendLine]);

  const sendChat = () => {
    const text = draft.trim();
    if (!text || !activeId) return;
    const ws = ensureWs();
    const doSend = () => {
      setMessages((prev) => [...prev, { role: "user", text }]);
      setAgentBusy(true);
      ws.send(JSON.stringify({ type: "chat", projectId: activeId, agent: "production", text }));
    };
    if (ws.readyState === WebSocket.OPEN) doSend();
    else {
      ws.onopen = () => doSend();
    }
    setDraft("");
  };

  const activeProject = projects.find((p) => p.id === activeId);

  // ---------------- 阶段门控：前置条件不满足则禁用并提示缺什么 ----------------
  const latestScript = useMemo(() => {
    if (!snap?.scripts.length) return null;
    return snap.scripts.reduce((acc, s) => (!acc || s.id > acc.id ? s : acc), snap.scripts[0]);
  }, [snap]);
  const chapters = snap?.chapters || [];
  const assets = snap?.assets || [];
  const boards = snap?.storyboards || [];
  const hasEvents = chapters.some((c) => c.eventState === 1);
  const extractingEvents = chapters.some((c) => c.eventState === 2);
  const boardsWithPrompt = boards.filter((b) => (b.prompt || "").trim()).length;
  const boardsWithImage = boards.filter((b) => b.imageUrl).length;
  const boardsWithVideoPrompt = boards.filter((b) => (b.videoPrompt || "").trim()).length;
  const assetsWithoutImage = assets.filter((a) => !a.imageId).map((a) => a.id);
  const gates = {
    novel: activeId != null,
    script: hasEvents,
    extract: !!latestScript,
    assetImages: assetsWithoutImage.length > 0,
    table: !!latestScript,
    prompts: boards.length > 0,
    boardImages: boardsWithPrompt > 0,
    videoPrompts: boardsWithImage > 0,
    videos: boardsWithVideoPrompt > 0,
    dubbing: assets.length > 0,
  };
  const gateHint = (ok: boolean, need: string) => (ok ? undefined : `前置条件：${need}`);

  // ---------------- 执行状态：阶段在跑 → 按钮转圈+禁用，防止重复点击 ----------------
  const act = snap?.activities || {};
  const stageActive = {
    extract: snap?.scripts.some((s) => s.extractState === 2) || false,
    assetImages: (act["image"] || 0) > 0,
    boardImages: snap?.storyboards.some((b) => b.state === "生成中") || false,
    videos: snap?.videos.some((v) => v.candidates.some((c) => c.state === "生成中")) || false,
  };
  const activityLabel: Record<string, string> = {
    text: "文本生成", image: "图片生成", video: "视频生成", tts: "语音合成", music: "音乐生成",
  };
  const activeSummary = Object.entries(act).filter(([, n]) => n > 0)
    .map(([k, n]) => `${activityLabel[k] || k} ×${n}`).join(" · ");


  return (
    <div className="h-full flex flex-col gap-2 p-2">
      {/* 紧凑页头：全屏模式下保留项目/阶段操作所需的最小信息条 */}
      <div className="flex items-center gap-2 flex-shrink-0">
        <Sparkles className="w-4 h-4 text-primary" />
        <span className="text-sm font-semibold">创作画布</span>
        <span className="text-xs text-muted-foreground hidden lg:inline">
          小说 → 剧本 → 资产 → 分镜 → 视频全链创作 · 基于 Toonflow (Apache-2.0) 迁移
        </span>
      </div>
    <div className="flex-1 min-h-0 rounded-xl border border-border/50 bg-background overflow-hidden flex flex-col">
      {/* 工具条 */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border/50 bg-muted/30 flex-shrink-0 flex-wrap">
        <span className="text-xs font-semibold">创作画布</span>
        <select
          value={activeId ?? ""}
          onChange={(e) => setActiveId(e.target.value ? Number(e.target.value) : null)}
          className="text-xs px-2 py-1 rounded-md border border-border/50 bg-background outline-none max-w-[200px]"
        >
          <option value="">选择创作项目…</option>
          {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <Button size="sm" variant="outline" onClick={() => setProjectDlg({ open: true, initial: null })}>
          <Plus className="h-3.5 w-3.5" />新建
        </Button>
        {activeProject && (
          <Button size="sm" variant="ghost" onClick={() => setProjectDlg({ open: true, initial: activeProject })}
            title="修改项目参数（比例/分辨率/画风/导演风格）">
            <SlidersHorizontal className="h-3.5 w-3.5" />项目设置
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={() => activeId && loadSnapshot(activeId)} title="刷新">
          <RefreshCw className={"h-3.5 w-3.5" + (loading ? " animate-spin" : "")} />
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setSettingsOpen(true)} title="画布能力设置">
          <Settings className="h-3.5 w-3.5" />
        </Button>
        {/* 流水线阶段操作：上游(小说→剧本→资产) + 下游(分镜→视频→配音) */}
        {activeId && (
          <div className="ml-auto flex items-center gap-1 flex-wrap">
            <StageButton icon={<BookOpen className="w-3 h-3" />} label="导入小说" busy={busy === "novels"}
              onClick={() => setNovelOpen(true)} title="粘贴小说文本，按章节标题切分导入并自动提取事件" />
            <StageButton icon={<FileText className="w-3 h-3" />} label="生成剧本" busy={busy === "script"}
              disabled={!gates.script || extractingEvents}
              onClick={() => runStage("script")} title={gateHint(gates.script, "先导入小说并完成事件提取（点击章节卡片可查看进度）") || "根据已提取的事件生成剧本草稿"} />
            <StageButton icon={<Users className="w-3 h-3" />} label="提取资产" busy={busy === "extract"}
              active={stageActive.extract} disabled={!gates.extract}
              onClick={() => runStage("extract")} title={gateHint(gates.extract, "先生成剧本") || `从剧本《${latestScript?.title || ""}》提取角色/场景/道具资产`} />
            <StageButton icon={<ImageIcon className="w-3 h-3" />} label={`资产出图${assetsWithoutImage.length ? `(${assetsWithoutImage.length})` : ""}`} busy={busy === "assetImages"}
              active={stageActive.assetImages} disabled={!gates.assetImages}
              onClick={() => runStage("assetImages", { ids: assetsWithoutImage })} title={gateHint(gates.assetImages, "先提取资产（且全部资产已有图）") || "为没有图的资产生成设定图"} />
            <span className="w-px h-4 bg-border/60 mx-0.5" />
            <StageButton icon={<ImageIcon className="w-3 h-3" />} label="分镜表" busy={busy === "table"}
              disabled={!gates.table}
              onClick={() => runStage("table")} title={gateHint(gates.table, "先生成剧本") || "按剧本+资产生成分镜表（覆盖重建）"} />
            <StageButton icon={<Wand2 className="w-3 h-3" />} label="分镜提示词" busy={busy === "prompts"}
              disabled={!gates.prompts}
              onClick={() => runStage("prompts")} title={gateHint(gates.prompts, "先生成分镜表") || "为每个分镜润色生图提示词"} />
            <StageButton icon={<ImageIcon className="w-3 h-3" />} label="生成分镜图" busy={busy === "boardImages"}
              active={stageActive.boardImages} disabled={!gates.boardImages}
              onClick={() => runStage("boardImages")} title={gateHint(gates.boardImages, "先生成分镜提示词") || "批量生成缺失的分镜图"} />
            <StageButton icon={<Sparkles className="w-3 h-3" />} label="视频提示词" busy={busy === "videoPrompts"}
              disabled={!gates.videoPrompts}
              onClick={() => runStage("videoPrompts")} title={gateHint(gates.videoPrompts, "先生成分镜图") || "按模型模板生成分镜视频提示词"} />
            <StageButton icon={<Film className="w-3 h-3" />} label="生成视频" busy={busy === "videos"}
              active={stageActive.videos} disabled={!gates.videos}
              onClick={() => runStage("videos")} title={gateHint(gates.videos, "先生成视频提示词") || "为有视频提示词的分镜生成视频"} />
            <StageButton icon={<Bot className="w-3 h-3" />} label="绑定音色" busy={busy === "dubbing"}
              disabled={!gates.dubbing}
              onClick={() => runStage("dubbing")} title={gateHint(gates.dubbing, "先提取资产") || "从配音谷音色库为角色匹配音色"} />
          </div>
        )}
      </div>

      {/* 执行状态条：后台任务实时反馈，防止重复点击 */}
      {activeSummary && (
        <div className="flex items-center gap-2 px-3 py-1.5 border-b border-border/50 bg-primary/5 flex-shrink-0">
          <Loader2 className="w-3 h-3 animate-spin text-primary" />
          <span className="text-xs text-primary font-medium">后台执行中：{activeSummary}</span>
          <span className="text-[11px] text-muted-foreground">完成后画面自动刷新，无需重复点击</span>
        </div>
      )}

      {/* 主区 */}
      <div className="flex flex-1 min-h-0 relative">
        <div className="flex-1 relative">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            nodeTypes={nodeTypes}
            fitView={!initialViewport}
            defaultViewport={initialViewport || undefined}
            onMoveEnd={(_, vp) => writeJSON(LS_VIEWPORT, vp)}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={22} size={1.4} />
            <Controls showInteractive={false} />
            <MiniMap pannable zoomable className="!bg-muted/50" />
          </ReactFlow>
          {!activeProject && (
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-10">
              <div className="text-center text-sm text-muted-foreground">
                <Sparkles className="w-8 h-8 mx-auto mb-2 text-muted-foreground/40" />
                选择或新建项目后开始创作
              </div>
            </div>
          )}
        </div>
        {/* Agent 侧边栏 */}
        <div className="w-80 flex-shrink-0 border-l border-border/60 bg-background/80 flex flex-col">
          <div className="flex items-center gap-1.5 px-3 py-2.5 border-b border-border/50">
            <Bot className="w-3.5 h-3.5 text-primary" />
            <span className="text-xs font-semibold">创作 Agent</span>
            {activeProject && <span className="ml-auto text-xs text-muted-foreground truncate max-w-[110px]">{activeProject.name}</span>}
          </div>
          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            {messages.map((m, i) => {
              if (m.kind === "tool") {
                return (
                  <div key={i} className="text-[11px] font-mono text-muted-foreground/90 truncate max-w-[92%]" title={m.text}>
                    ⚙️ {m.text}
                  </div>
                );
              }
              if (m.kind === "tool_result") {
                return (
                  <div key={i} className="text-[11px] pl-3 border-l-2 border-border/50 max-w-[92%]">
                    <ToolResultView preview={m.text} />
                  </div>
                );
              }
              if (m.kind === "note") {
                return (
                  <div key={i} className="text-[11px] text-muted-foreground/80 max-w-[92%]">{m.text}</div>
                );
              }
              return (
                <div key={i} className={`text-xs rounded-lg px-2.5 py-2 max-w-[92%] ${m.role === "user" ? "ml-auto bg-primary/10 text-foreground" : "bg-muted/60 text-foreground"}`}>
                  {m.role === "user" ? m.text : <MdContent text={m.text} />}
                </div>
              );
            })}
          </div>
          <div className="p-2.5 border-t border-border/50 flex items-center gap-1.5">
            <Input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") sendChat(); }}
              placeholder={activeProject ? "向 Agent 下达创作指令…" : "请先选择项目"}
              disabled={!activeProject || agentBusy}
              className="h-9 text-sm"
            />
            <Button size="icon" variant="ghost" className="h-8 w-8" onClick={sendChat}
              disabled={!activeProject || agentBusy}>
              {agentBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
            </Button>
          </div>
        </div>
      </div>
      <NovelImportDialog open={novelOpen} onClose={() => setNovelOpen(false)}
        onImport={importNovels} busy={busy === "novels"} />
      <ProjectDialog open={projectDlg.open} initial={projectDlg.initial}
        onClose={() => setProjectDlg({ open: false, initial: null })} onSave={saveProject} />
      {menu && (
        <div className="fixed z-50 min-w-[150px] rounded-lg border border-border bg-background shadow-lg py-1"
          style={{ left: Math.min(menu.x, window.innerWidth - 170), top: Math.min(menu.y, window.innerHeight - 180) }}
          onClick={(e) => e.stopPropagation()}>
          <div className="px-3 py-1 text-[11px] text-muted-foreground border-b border-border/40">
            {menu.data.title.slice(0, 16)}
          </div>
          {buildMenu(menu.data).map((it) => (
            <button key={it.label} type="button"
              onClick={() => { setMenu(null); it.run(); }}
              className={`w-full text-left px-3 py-1.5 text-xs hover:bg-muted ${it.danger ? "text-destructive" : ""}`}>
              {it.label}
            </button>
          ))}
        </div>
      )}
      <CardEditDialog data={editor} snap={snap} onClose={() => setEditor(null)}
        onSaved={() => { setEditor(null); refresh(); }} />
      <CanvasSettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
    </div>
  );
}

/** 行内 Markdown：**加粗** 与 `代码` */
function renderInline(text: string, keyBase: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0, i = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("**")) parts.push(<strong key={`${keyBase}b${i}`}>{tok.slice(2, -2)}</strong>);
    else parts.push(<code key={`${keyBase}c${i}`} className="px-1 rounded bg-muted font-mono text-[11px]">{tok.slice(1, -1)}</code>);
    last = m.index + tok.length;
    i++;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

/** 轻量 Markdown 块级渲染：标题 / 表格 / 有序无序列表 / 代码块 / 分隔线 / 段落 */
function MdContent({ text }: { text: string }) {
  const lines = (text || "").replace(/\r\n/g, "\n").split("\n");
  const blocks: React.ReactNode[] = [];
  let i = 0, key = 0;
  const isTableLine = (s: string) => /^\s*\|.*\|\s*$/.test(s);
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      blocks.push(<div key={key} className={`font-semibold ${h[1].length <= 2 ? "text-xs" : ""}`}>{renderInline(h[2], `h${key}`)}</div>);
      i++; key++; continue;
    }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
      blocks.push(<hr key={key++} className="border-border/40 my-1" />);
      i++; continue;
    }
    if (line.trim().startsWith("```")) {
      const code: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) { code.push(lines[i]); i++; }
      i++;
      blocks.push(<pre key={key++} className="text-[11px] bg-muted/70 rounded p-1.5 overflow-x-auto whitespace-pre-wrap font-mono">{code.join("\n")}</pre>);
      continue;
    }
    if (isTableLine(line) && i + 1 < lines.length && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1])) {
      const header = line.trim().replace(/^\||\|$/g, "").split("|").map((s) => s.trim());
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && isTableLine(lines[i])) {
        rows.push(lines[i].trim().replace(/^\||\|$/g, "").split("|").map((s) => s.trim()));
        i++;
      }
      blocks.push(
        <table key={key++} className="w-full text-[11px] border-collapse my-1">
          <thead><tr>{header.map((c, ci) => (
            <th key={ci} className="border border-border/40 px-1.5 py-0.5 text-left bg-muted/40">{renderInline(c, `th${key}-${ci}`)}</th>
          ))}</tr></thead>
          <tbody>{rows.map((r, ri) => (
            <tr key={ri}>{r.map((c, ci) => (
              <td key={ci} className="border border-border/40 px-1.5 py-0.5 align-top">{renderInline(c, `td${key}-${ri}-${ci}`)}</td>
            ))}</tr>
          ))}</tbody>
        </table>);
      continue;
    }
    const ul = line.match(/^\s*[-*]\s+(.*)$/);
    if (ul) {
      const items: string[] = [];
      while (i < lines.length) {
        const m2 = lines[i].match(/^\s*[-*]\s+(.*)$/);
        if (!m2) break;
        items.push(m2[1]); i++;
      }
      blocks.push(<ul key={key++} className="list-disc pl-4 space-y-0.5">{items.map((it, ii) => <li key={ii}>{renderInline(it, `ul${key}-${ii}`)}</li>)}</ul>);
      continue;
    }
    const ol = line.match(/^\s*\d+[.、]\s+(.*)$/);
    if (ol) {
      const items: string[] = [];
      while (i < lines.length) {
        const m2 = lines[i].match(/^\s*\d+[.、]\s+(.*)$/);
        if (!m2) break;
        items.push(m2[1]); i++;
      }
      blocks.push(<ol key={key++} className="list-decimal pl-4 space-y-0.5">{items.map((it, ii) => <li key={ii}>{renderInline(it, `ol${key}-${ii}`)}</li>)}</ol>);
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim()
      && !/^#{1,6}\s/.test(lines[i]) && !isTableLine(lines[i])
      && !/^\s*[-*]\s/.test(lines[i]) && !/^\s*\d+[.、]\s/.test(lines[i])
      && !lines[i].trim().startsWith("```")) {
      para.push(lines[i].trim()); i++;
    }
    if (para.length) {
      blocks.push(<p key={key++} className="leading-snug whitespace-pre-wrap">{renderInline(para.join("\n"), `p${key}`)}</p>);
    }
  }
  return <div className="space-y-1">{blocks}</div>;
}

/** 工具返回结果结构化展示：记忆检索折叠摘要 / 错误红字 / 通用 JSON 折叠 */
function ToolResultView({ preview }: { preview: string }) {
  let data: any = null;
  try { data = JSON.parse(preview); } catch { /* 非 JSON */ }
  if (data && typeof data === "object" && !Array.isArray(data)) {
    if (data.error) return <span className="text-destructive">✗ {String(data.error)}</span>;
    if (Array.isArray(data.memories)) {
      const items: string[] = data.memories.map((m: any) => (typeof m === "string" ? m : String(m?.content ?? "")));
      return (
        <details className="w-full">
          <summary className="cursor-pointer text-muted-foreground">检索到 {items.length} 条相关记忆</summary>
          <div className="mt-1 space-y-1">
            {items.slice(0, 3).map((c, i) => (
              <div key={i} className="bg-muted/50 rounded p-1.5 max-h-28 overflow-y-auto">
                <MdContent text={c.slice(0, 800)} />
              </div>
            ))}
          </div>
        </details>
      );
    }
    const keys = Object.keys(data);
    return (
      <details className="w-full">
        <summary className="cursor-pointer text-muted-foreground">
          {keys.length ? `返回：${keys.slice(0, 4).join(" / ")}${keys.length > 4 ? " …" : ""}` : "返回空对象"}
        </summary>
        <pre className="text-[11px] bg-muted/50 rounded p-1.5 mt-1 max-h-32 overflow-auto whitespace-pre-wrap font-mono">
          {JSON.stringify(data, null, 2).slice(0, 3000)}
        </pre>
      </details>
    );
  }
  if (Array.isArray(data)) {
    return <details className="w-full"><summary className="cursor-pointer text-muted-foreground">返回 {data.length} 项</summary>
      <pre className="text-[11px] bg-muted/50 rounded p-1.5 mt-1 max-h-32 overflow-auto whitespace-pre-wrap font-mono">{JSON.stringify(data, null, 2).slice(0, 3000)}</pre>
    </details>;
  }
  return <span className="text-muted-foreground">{preview.slice(0, 240) || "（空）"}</span>;
}

function StageButton({ icon, label, onClick, busy, title, disabled, active }: {
  icon: React.ReactNode; label: string; onClick: () => void; busy?: boolean; title?: string;
  disabled?: boolean; active?: boolean;
}) {
  const running = busy || active;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={running || disabled}
      title={title}
      className={`inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium border transition-colors ${
        running ? "border-primary/40 bg-primary/10 text-primary"
          : disabled ? "border-border/40 bg-background text-muted-foreground/50 cursor-not-allowed"
            : "border-border/50 bg-background hover:bg-muted"
      }`}
    >
      {running ? <Loader2 className="w-3 h-3 animate-spin" /> : icon}
      {label}
    </button>
  );
}

/** 导入小说弹窗：粘贴全文，按章节标题自动切分后批量入库并触发事件提取。 */
const CHAPTER_HEADING_RE = /^\s*(第[0-9零一二三四五六七八九十百千万两]+[章回节卷][^\n]*)$/;

function splitChapters(text: string): { reel: string; chapter: string; chapterData: string }[] {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const out: { reel: string; chapter: string; chapterData: string }[] = [];
  let cur: { reel: string; chapter: string; chapterData: string } | null = null;
  for (const line of lines) {
    const m = line.match(CHAPTER_HEADING_RE);
    if (m) {
      if (cur) out.push(cur);
      cur = { reel: "", chapter: m[1].trim(), chapterData: "" };
    } else if (cur) {
      cur.chapterData += (cur.chapterData ? "\n" : "") + line;
    }
  }
  if (cur) out.push(cur);
  // 没识别到任何章节标题：整篇作为一章
  if (!out.length && text.trim()) {
    out.push({ reel: "", chapter: "全文", chapterData: text.trim() });
  }
  return out.filter((c) => c.chapterData.trim());
}

/** 画布能力设置弹窗：读写 config.yaml（经 /api/settings），覆盖 LLM 地址与生图/视频/TTS 能力默认接口模型。 */
interface IfaceItem { id: string; name: string }

function CanvasSettingsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const empty = {
    llmUrl: "", llmKey: "", llmKeySet: false, llmModel: "",
    imgT2IIface: "", imgT2IModel: "", imgI2IIface: "", imgI2IModel: "",
    vidT2VIface: "", vidT2VModel: "", vidI2VIface: "", vidI2VModel: "",
    vidV2VIface: "", vidV2VModel: "",
    ttsIface: "", ttsModel: "",
  };
  const [form, setForm] = useState(empty);
  const [base, setBase] = useState(empty);
  const [imageIfaces, setImageIfaces] = useState<IfaceItem[]>([]);
  const [videoIfaces, setVideoIfaces] = useState<IfaceItem[]>([]);
  const [ttsIfaces, setTtsIfaces] = useState<IfaceItem[]>([]);
  // 模型候选按「能力|模式|接口」缓存（每个模式行各自联动自己的接口）
  const [modelOpts, setModelOpts] = useState<Record<string, string[]>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  const patch = (p: Partial<typeof empty>) => setForm((f) => ({ ...f, ...p }));
  const optKey = (kind: string, mode: string, iface: string) => `${kind}|${mode}|${iface}`;

  const fetchIfaceList = async (url: string): Promise<IfaceItem[]> => {
    const { data } = await client.get(url);
    const list: any[] = Array.isArray(data) ? data : data.interfaces || [];
    return list.map((i) => ({ id: String(i.id || ""), name: String(i.name || i.id || "") }))
      .filter((i) => i.id);
  };
  const fetchModels = async (kind: "imagegen" | "videogen" | "tts", ifaceId: string, mode: string): Promise<string[]> => {
    if (!ifaceId) return [];
    try {
      const base2 = kind === "imagegen" ? "/api/imagegen-interfaces"
        : kind === "videogen" ? "/api/videogen-interfaces" : "/api/tts-interfaces";
      const { data } = await client.get(`${base2}/${ifaceId}/models-for-node`, { params: { mode } });
      const list: any[] = Array.isArray(data) ? data : data.models || [];
      return list.map((m) => (typeof m === "string" ? m : String(m?.name || ""))).filter(Boolean);
    } catch { return []; }
  };

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setErr("");
    Promise.all([
      settingsApi.getAll(),
      fetchIfaceList("/api/imagegen-interfaces/enabled").catch(() => []),
      fetchIfaceList("/api/videogen-interfaces/enabled").catch(() => []),
      fetchIfaceList("/api/tts-interfaces/enabled").catch(() => []),
    ]).then(async ([cfgRes, imgIf, vidIf, ttsIf]) => {
      const cfg: any = (cfgRes.data as any)?.config || {};
      const next = {
        llmUrl: String(cfg?.llm?.base_url ?? cfg?.llm?.router_url ?? ""),
        llmKey: "",
        llmKeySet: Boolean(cfg?.llm?.api_key),
        llmModel: String(cfg?.llm?.step_models?.toonflow ?? ""),
        imgT2IIface: String(cfg?.imagegen?.t2i_interface ?? cfg?.imagegen?.method ?? ""),
        imgT2IModel: String(cfg?.imagegen?.default_t2i_model ?? ""),
        imgI2IIface: String(cfg?.imagegen?.i2i_interface ?? cfg?.imagegen?.method ?? ""),
        imgI2IModel: String(cfg?.imagegen?.default_i2i_model ?? ""),
        vidT2VIface: String(cfg?.videogen?.t2v_interface ?? cfg?.videogen?.method ?? ""),
        vidT2VModel: String(cfg?.videogen?.default_t2v_model ?? ""),
        vidI2VIface: String(cfg?.videogen?.i2v_interface ?? cfg?.videogen?.method ?? ""),
        vidI2VModel: String(cfg?.videogen?.default_i2v_model ?? ""),
        vidV2VIface: String(cfg?.videogen?.v2v_interface ?? ""),
        vidV2VModel: String(cfg?.videogen?.default_v2v_model ?? ""),
        ttsIface: String(cfg?.tts?.method ?? ""),
        ttsModel: String(cfg?.tts?.default_model ?? ""),
      };
      setForm(next);
      setBase(next);
      setImageIfaces(imgIf);
      setVideoIfaces(vidIf);
      setTtsIfaces(ttsIf);
      // 为已配置接口的每个模式行拉取模型候选
      const jobs: Array<[string, "imagegen" | "videogen" | "tts", string, string]> = [
        [optKey("imagegen", "txt2img", next.imgT2IIface), "imagegen", next.imgT2IIface, "txt2img"],
        [optKey("imagegen", "img2img", next.imgI2IIface), "imagegen", next.imgI2IIface, "img2img"],
        [optKey("videogen", "t2v", next.vidT2VIface), "videogen", next.vidT2VIface, "t2v"],
        [optKey("videogen", "i2v", next.vidI2VIface), "videogen", next.vidI2VIface, "i2v"],
        [optKey("videogen", "v2v", next.vidV2VIface), "videogen", next.vidV2VIface, "v2v"],
        [optKey("tts", "", next.ttsIface), "tts", next.ttsIface, ""],
      ].filter(([k, , iface]) => iface && k) as Array<[string, "imagegen" | "videogen" | "tts", string, string]>;
      const entries = await Promise.all(jobs.map(async ([k, kind, iface, mode]) =>
        [k, await fetchModels(kind, iface, mode)] as [string, string[]]));
      setModelOpts(Object.fromEntries(entries));
    }).catch(() => setErr("设置读取失败，请检查后端服务")).finally(() => setLoading(false));
  }, [open]);

  const save = async () => {
    setSaving(true);
    setErr("");
    try {
      const updates: Array<[string, unknown]> = [];
      const url = form.llmUrl.trim();
      if (url && url !== base.llmUrl) updates.push(["llm.base_url", url], ["llm.router_url", url]);
      const key = form.llmKey.trim();
      if (key) updates.push(["llm.api_key", key]);
      const fieldOf: Record<string, keyof typeof base> = {
        "llm.step_models.toonflow": "llmModel",
        "imagegen.t2i_interface": "imgT2IIface", "imagegen.default_t2i_model": "imgT2IModel",
        "imagegen.i2i_interface": "imgI2IIface", "imagegen.default_i2i_model": "imgI2IModel",
        "videogen.t2v_interface": "vidT2VIface", "videogen.default_t2v_model": "vidT2VModel",
        "videogen.i2v_interface": "vidI2VIface", "videogen.default_i2v_model": "vidI2VModel",
        "videogen.v2v_interface": "vidV2VIface", "videogen.default_v2v_model": "vidV2VModel",
        "tts.method": "ttsIface", "tts.default_model": "ttsModel",
      };
      for (const [k, v] of Object.entries(fieldOf)) {
        if (form[v] !== base[v]) updates.push([k, form[v]]);
      }
      await Promise.all(updates.map(([k, v]) => settingsApi.update(k, v)));
      onClose();
    } catch {
      setErr("保存失败，请重试");
    } finally {
      setSaving(false);
    }
  };

  if (!open) return null;

  const Section = ({ title, children }: { title: string; children: React.ReactNode }) => (
    <div className="mb-4">
      <div className="text-xs font-semibold text-muted-foreground mb-1.5">{title}</div>
      <div className="space-y-2">{children}</div>
    </div>
  );
  /** 并排字段：标签在上，控件在下；配合 grid 实现「接口 | 模型」两列布局 */
  const Field = ({ label, children }: { label: string; children: React.ReactNode }) => (
    <div className="flex flex-col gap-1 min-w-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      {children}
    </div>
  );
  const Sel = ({ value, onChange, options, placeholder }: {
    value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; placeholder: string;
  }) => (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full text-sm px-2 py-1.5 rounded-md border border-border/50 bg-background outline-none truncate"
    >
      <option value="">{placeholder}</option>
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
  const withCurrent = (list: string[], cur: string) =>
    cur && !list.includes(cur) ? [cur, ...list] : list;
  /** 一行 = 一个模式的两列设置：[接口 | 模型]，模型候选随本行接口联动 */
  type TextFieldKey = { [K in keyof typeof empty]: (typeof empty)[K] extends string ? K : never }[keyof typeof empty];
  const ModeRow = ({ label, kind, mode, ifaceKey, modelKey, ifaces }: {
    label: string; kind: "imagegen" | "videogen" | "tts"; mode: string;
    ifaceKey: TextFieldKey; modelKey: TextFieldKey; ifaces: IfaceItem[];
  }) => {
    const ifaceVal = form[ifaceKey];
    const opts = modelOpts[optKey(kind, mode, ifaceVal)] || [];
    return (
      <div className="grid grid-cols-2 gap-3">
        <Field label={`${label} · 接口`}>
          <Sel value={ifaceVal} placeholder="留空用首个已启用接口"
            options={ifaces.map((i) => ({ value: i.id, label: i.name }))}
            onChange={async (v) => {
              patch({ [ifaceKey]: v } as Partial<typeof empty>);
              const models = await fetchModels(kind, v, mode);
              setModelOpts((m) => ({ ...m, [optKey(kind, mode, v)]: models }));
            }} />
        </Field>
        <Field label={`${label} · 模型`}>
          <Sel value={form[modelKey]} placeholder="跟随接口默认"
            options={withCurrent(opts, form[modelKey]).map((m) => ({ value: m, label: m }))}
            onChange={(v) => patch({ [modelKey]: v } as Partial<typeof empty>)} />
        </Field>
      </div>
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={saving ? undefined : onClose}>
      <div className="w-[676px] max-w-[92vw] max-h-[82vh] flex flex-col rounded-xl border border-border bg-background shadow-lg"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 px-4 py-3 border-b border-border/50">
          <Settings className="w-4 h-4 text-primary" />
          <span className="text-sm font-semibold">画布能力设置</span>
          <span className="text-xs text-muted-foreground">写入 config.yaml，对所有画布项目生效</span>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3">
          {loading ? (
            <div className="flex items-center justify-center py-10 text-muted-foreground">
              <Loader2 className="w-4 h-4 animate-spin mr-2" />加载中…
            </div>
          ) : (
            <>
              <Section title="LLM">
                <div className="grid grid-cols-2 gap-3">
                  <Field label="接口地址">
                    <Input value={form.llmUrl} onChange={(e) => patch({ llmUrl: e.target.value })}
                      placeholder="http://localhost:8800/v1" className="h-9 w-full text-sm" />
                  </Field>
                  <Field label="模型">
                    <Input value={form.llmModel} onChange={(e) => patch({ llmModel: e.target.value })}
                      placeholder="留空跟随全局默认模型" className="h-9 w-full text-sm" />
                  </Field>
                </div>
                <Field label="API Key">
                  <Input type="password" value={form.llmKey} onChange={(e) => patch({ llmKey: e.target.value })}
                    placeholder={form.llmKeySet ? "已配置（留空保持不变）" : "未配置"} className="h-9 w-full text-sm" />
                </Field>
              </Section>
              <Section title="生图（资产图 / 分镜图）">
                <ModeRow label="文生图" kind="imagegen" mode="txt2img"
                  ifaceKey="imgT2IIface" modelKey="imgT2IModel" ifaces={imageIfaces} />
                <ModeRow label="图生图" kind="imagegen" mode="img2img"
                  ifaceKey="imgI2IIface" modelKey="imgI2IModel" ifaces={imageIfaces} />
              </Section>
              <Section title="视频（分镜视频）">
                <ModeRow label="文生视频" kind="videogen" mode="t2v"
                  ifaceKey="vidT2VIface" modelKey="vidT2VModel" ifaces={videoIfaces} />
                <ModeRow label="图生视频" kind="videogen" mode="i2v"
                  ifaceKey="vidI2VIface" modelKey="vidI2VModel" ifaces={videoIfaces} />
                <ModeRow label="视频续写" kind="videogen" mode="v2v"
                  ifaceKey="vidV2VIface" modelKey="vidV2VModel" ifaces={videoIfaces} />
              </Section>
              <Section title="TTS（配音候选音色来自配音谷音色库）">
                <ModeRow label="TTS" kind="tts" mode=""
                  ifaceKey="ttsIface" modelKey="ttsModel" ifaces={ttsIfaces} />
              </Section>
              {err && <div className="text-xs text-destructive">{err}</div>}
            </>
          )}
        </div>
        <div className="flex items-center gap-2 px-4 py-3 border-t border-border/50">
          <span className="text-xs text-muted-foreground">接口在「设置 → 能力接口」中维护；此处仅选择画布默认项</span>
          <div className="ml-auto flex items-center gap-1.5">
            <Button size="sm" variant="ghost" disabled={saving} onClick={onClose}>取消</Button>
            <Button size="sm" disabled={loading || saving} onClick={save}>
              {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
              保存
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function NovelImportDialog({ open, onClose, onImport, busy }: {
  open: boolean; onClose: () => void;
  onImport: (chapters: { reel: string; chapter: string; chapterData: string }[]) => void;
  busy: boolean;
}) {
  const [text, setText] = useState("");
  if (!open) return null;
  const chapters = splitChapters(text);
  const totalChars = chapters.reduce((n, c) => n + c.chapterData.length, 0);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="w-[560px] max-w-[92vw] max-h-[80vh] flex flex-col rounded-xl border border-border bg-background shadow-lg"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 px-4 py-3 border-b border-border/50">
          <BookOpen className="w-4 h-4 text-primary" />
          <span className="text-sm font-semibold">导入小说</span>
          <span className="text-xs text-muted-foreground">按「第X章/回/节」标题自动切分章节，导入后自动提取事件</span>
        </div>
        <div className="flex-1 min-h-0 p-3">
          <textarea
            autoFocus
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={"在此粘贴小说全文，例如：\n\n第一章 初入江湖\n\n正文……\n\n第二章 故人重逢\n\n正文……"}
            className="w-full h-full min-h-[260px] text-xs rounded-md border border-border/50 bg-background p-2 outline-none resize-none focus:border-primary/50"
          />
        </div>
        <div className="flex items-center gap-2 px-4 py-3 border-t border-border/50">
          <span className="text-xs text-muted-foreground">
            {text.trim()
              ? `识别到 ${chapters.length} 章 · 共 ${totalChars} 字`
              : "支持简繁数字章节标题；未识别到标题时整篇作为一章"}
          </span>
          <div className="ml-auto flex items-center gap-1.5">
            <Button size="sm" variant="ghost" onClick={onClose}>取消</Button>
            <Button size="sm" disabled={!chapters.length || busy} onClick={() => onImport(chapters)}>
              {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}
              导入{chapters.length ? ` ${chapters.length} 章` : ""}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

type ProjectPayload = ProjectCreatePayload;

/** 卡片内容编辑弹窗：章节/剧本（长文本，按需从接口取全文）、资产、分镜 */
function CardEditDialog({ data, snap, onClose, onSaved }: {
  data: CanvasData | null; snap: Snapshot | null;
  onClose: () => void; onSaved: () => void;
}) {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [prompt, setPrompt] = useState("");
  const [duration, setDuration] = useState(4);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!data) return;
    setErr("");
    setTitle(""); setBody(""); setPrompt(""); setDuration(4);
    if (data.kind === "chapter" && data.chapterId) {
      setLoading(true);
      toonflowApi.getNovel(data.chapterId)
        .then(({ data: n }) => { setTitle(n.chapter || ""); setBody(n.chapterData || ""); })
        .catch(() => setErr("章节内容读取失败"))
        .finally(() => setLoading(false));
    } else if (data.kind === "script" && data.scriptId) {
      setLoading(true);
      toonflowApi.getScript(data.scriptId)
        .then(({ data: s }) => { setTitle(s.title || ""); setBody(s.scriptData || ""); })
        .catch(() => setErr("剧本内容读取失败"))
        .finally(() => setLoading(false));
    } else if (data.kind === "asset" && data.assetId) {
      const a = snap?.assets.find((x) => x.id === data.assetId);
      setTitle(a?.name || data.title);
      setBody(a?.describe || "");
      setPrompt(a?.prompt || "");
    } else if (data.kind === "storyboard" && data.storyboardId) {
      const b = snap?.storyboards.find((x) => x.id === data.storyboardId);
      setTitle(b?.videoDesc || data.desc);
      setPrompt(b?.prompt || "");
      setDuration(b?.duration || 4);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  if (!data) return null;

  const save = async () => {
    setSaving(true);
    setErr("");
    try {
      if (data.kind === "chapter" && data.chapterId) {
        await toonflowApi.updateNovel(data.chapterId, { chapter: title, chapterData: body });
      } else if (data.kind === "script" && data.scriptId) {
        await toonflowApi.updateScript(data.scriptId, { title, scriptData: body });
      } else if (data.kind === "asset" && data.assetId) {
        await toonflowApi.updateAssetFields(data.assetId, { name: title, describe: body, prompt });
      } else if (data.kind === "storyboard" && data.storyboardId) {
        await toonflowApi.updateStoryboardFields(data.storyboardId, {
          videoDesc: title, prompt, duration: Number(duration) || 4,
        });
      }
      onSaved();
    } catch {
      setErr("保存失败，请重试");
    } finally {
      setSaving(false);
    }
  };

  const isLongText = data.kind === "chapter" || data.kind === "script";
  const Field = ({ label, children }: { label: string; children: React.ReactNode }) => (
    <div className="flex flex-col gap-1 min-w-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      {children}
    </div>
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="w-[676px] max-w-[92vw] max-h-[88vh] flex flex-col rounded-xl border border-border bg-background shadow-lg"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 px-4 py-3 border-b border-border/50">
          <Pencil className="w-4 h-4 text-primary" />
          <span className="text-sm font-semibold">
            编辑{data.kind === "chapter" ? "章节" : data.kind === "script" ? "剧本" : data.kind === "asset" ? "资产" : "分镜"}
          </span>
          {isLongText && <span className="text-xs text-muted-foreground">修改正文后事件/资产状态会重置，需重新提取</span>}
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3 space-y-3">
          {loading ? (
            <div className="flex items-center justify-center py-10 text-muted-foreground">
              <Loader2 className="w-4 h-4 animate-spin mr-2" />读取中…
            </div>
          ) : (
            <>
              <Field label={data.kind === "chapter" ? "章节名" : data.kind === "asset" ? "资产名称" : data.kind === "storyboard" ? "画面描述" : "标题"}>
                <Input value={title} onChange={(e) => setTitle(e.target.value)} className="h-9 w-full text-sm" />
              </Field>
              <Field label={data.kind === "asset" ? "资产描述" : data.kind === "storyboard" ? "（分镜描述见上方）" : "正文"}>
                <textarea value={body} onChange={(e) => setBody(e.target.value)}
                  rows={isLongText ? 14 : 5} disabled={data.kind === "storyboard"}
                  className="w-full text-sm rounded-md border border-border/50 bg-background p-2 outline-none resize-y disabled:opacity-50" />
              </Field>
              {(data.kind === "asset" || data.kind === "storyboard") && (
                <Field label={data.kind === "asset" ? "生图提示词" : "分镜图提示词"}>
                  <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={4}
                    className="w-full text-sm rounded-md border border-border/50 bg-background p-2 outline-none resize-y" />
                </Field>
              )}
              {data.kind === "storyboard" && (
                <Field label="时长（秒）">
                  <Input type="number" min={1} value={duration}
                    onChange={(e) => setDuration(Number(e.target.value))} className="h-9 w-32 text-sm" />
                </Field>
              )}
              {err && <div className="text-xs text-destructive">{err}</div>}
            </>
          )}
        </div>
        <div className="flex items-center gap-2 px-4 py-3 border-t border-border/50">
          <span className="text-xs text-muted-foreground">手动修改会直接写入数据，可随时重跑对应阶段</span>
          <div className="ml-auto flex items-center gap-1.5">
            <Button size="sm" variant="ghost" disabled={saving} onClick={onClose}>取消</Button>
            <Button size="sm" disabled={loading || saving} onClick={save}>
              {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : null}保存
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

/** 新建 / 编辑项目：名称 + 画面比例 + 视频分辨率 + 图片质量 + 画风 + 导演风格（手册） */
function ProjectDialog({ open, initial, onClose, onSave }: {
  open: boolean; initial: TfProject | null;
  onClose: () => void; onSave: (payload: ProjectPayload) => void;
}) {
  const [form, setForm] = useState<ProjectPayload>({
    name: "", introduce: "", artStyle: "", directorManual: "",
    videoRatio: "16:9", imageQuality: "1K", videoResolution: "720P",
  });
  const [styles, setStyles] = useState<{ value: string; label: string; desc: string }[]>([]);

  useEffect(() => {
    if (!open) return;
    setForm(initial ? {
      name: initial.name || "", introduce: initial.introduce || "",
      artStyle: initial.artStyle || "", directorManual: initial.directorManual || "",
      videoRatio: initial.videoRatio || "16:9", imageQuality: initial.imageQuality || "1K",
      videoResolution: initial.videoResolution || "720P",
    } : {
      name: "", introduce: "", artStyle: "", directorManual: "",
      videoRatio: "16:9", imageQuality: "1K", videoResolution: "720P",
    });
    toonflowApi.listArtStyles().then(({ data }) => setStyles(data.styles || [])).catch(() => setStyles([]));
  }, [open, initial]);

  if (!open) return null;

  const patch = (p: Partial<ProjectPayload>) => setForm((f) => ({ ...f, ...p }));
  // 导演风格：当前手册文本命中预设则回显预设名，否则为自定义
  const presetIndex = DIRECTOR_PRESETS.findIndex((p) => p.text && p.text === (form.directorManual || ""));

  const Sel = ({ value, onChange, options, placeholder }: {
    value: string; onChange: (v: string) => void; options: { value: string; label: string }[];
    placeholder?: string;
  }) => (
    <select value={value} onChange={(e) => onChange(e.target.value)}
      className="w-full text-sm px-2 py-1.5 rounded-md border border-border/50 bg-background outline-none">
      {placeholder && <option value="">{placeholder}</option>}
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
  const Field = ({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) => (
    <div className="flex flex-col gap-1 min-w-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      {children}
      {hint && <span className="text-[11px] text-muted-foreground/70">{hint}</span>}
    </div>
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="w-[676px] max-w-[92vw] max-h-[88vh] flex flex-col rounded-xl border border-border bg-background shadow-lg"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 px-4 py-3 border-b border-border/50">
          <Sparkles className="w-4 h-4 text-primary" />
          <span className="text-sm font-semibold">{initial ? "项目设置" : "新建创作项目"}</span>
          <span className="text-xs text-muted-foreground">比例 / 分辨率 / 画风 / 导演风格决定后续所有生成</span>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3 space-y-3">
          <Field label="项目名称">
            <Input autoFocus value={form.name} onChange={(e) => patch({ name: e.target.value })}
              placeholder="例如：剑毒梅香" className="h-9 w-full text-sm" />
          </Field>
          <Field label="项目简介（可选）">
            <textarea value={form.introduce || ""} onChange={(e) => patch({ introduce: e.target.value })}
              placeholder="一句话说明题材与受众，会参与后续生成的上下文" rows={2}
              className="w-full text-sm rounded-md border border-border/50 bg-background p-2 outline-none resize-none" />
          </Field>
          <div className="grid grid-cols-3 gap-3">
            <Field label="画面比例">
              <Sel value={form.videoRatio || "16:9"} options={VIDEO_RATIOS}
                onChange={(v) => patch({ videoRatio: v })} />
            </Field>
            <Field label="视频分辨率">
              <Sel value={form.videoResolution || "720P"} options={VIDEO_RESOLUTIONS}
                onChange={(v) => patch({ videoResolution: v })} />
            </Field>
            <Field label="图片质量">
              <Sel value={form.imageQuality || "1K"} options={IMAGE_QUALITIES}
                onChange={(v) => patch({ imageQuality: v })} />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="画风" hint="注入资产图与分镜图的风格前缀">
              <Sel value={form.artStyle || ""} placeholder="不设定（跟随模型默认）"
                options={styles.map((s) => ({ value: s.value, label: s.label }))}
                onChange={(v) => patch({ artStyle: v })} />
            </Field>
            <Field label="导演风格" hint="选择预设后可在下方手册里改写">
              <Sel value={presetIndex > 0 ? String(presetIndex) : "0"} options={DIRECTOR_PRESETS.map((p, i) => ({ value: String(i), label: p.label }))}
                onChange={(v) => patch({ directorManual: DIRECTOR_PRESETS[Number(v) || 0]?.text || "" })} />
            </Field>
          </div>
          <Field label="导演手册（可选）" hint="视觉与叙事要求，会随资产/分镜生成为模型提供约束">
            <textarea value={form.directorManual || ""} onChange={(e) => patch({ directorManual: e.target.value })}
              placeholder="节奏、镜头语言、色调与表演要求等；选了预设风格会自动填入，可自由改写" rows={4}
              className="w-full text-sm rounded-md border border-border/50 bg-background p-2 outline-none resize-none" />
          </Field>
        </div>
        <div className="flex items-center gap-2 px-4 py-3 border-t border-border/50">
          <span className="text-xs text-muted-foreground">建完仍可随时在「项目设置」里修改</span>
          <div className="ml-auto flex items-center gap-1.5">
            <Button size="sm" variant="ghost" onClick={onClose}>取消</Button>
            <Button size="sm" disabled={!form.name.trim()}
              onClick={() => onSave({ ...form, name: form.name.trim() })}>
              {initial ? "保存" : "创建项目"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

type ChatMessage = {
  role: "user" | "assistant";
  text: string;
  /** md=Markdown 正文；tool=工具调用行；tool_result=工具返回（结构化展示）；note=提示行 */
  kind?: "md" | "tool" | "tool_result" | "note";
};

// -*- coding: utf-8 -*-
/**
 * 创作·生产矩阵面板（P0 只读驾驶舱）
 *
 * 行 = 章节，列 = 生产阶段，格子 = 完成度 / 缺口 / 失败数。
 * 状态全部由后端从「分镜表 + 资产表 + 生成台账」推导（GET /api/creation/{id}/matrix），
 * 前端不维护第二套状态；点击格子后按分镜展开产物明细（复用 /api/creation/{id}/tree）。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ChevronRight, Grid3x3, Loader2, Play, RefreshCw, RotateCw, X } from "lucide-react";
import client from "@/api/client";
import { useKeepAliveActive } from "@/components/layout/keepAliveActive";

/** 驾驶舱任务（POST /api/creation/run-stage 返回、GET /api/creation/tasks 回查） */
interface CockpitTask {
  task_id: string;
  step_id: string;
  chapter_id: string;
  shot_id: string;
  status: string;
  node_status: string;
  error_class: string;
  created_at: string;
  updated_at: string;
}

const ACTIVE_TASK_STATUS = ["created", "queued", "running", "paused", "stopping"];

/** 后端矩阵接口返回结构 */
export interface MatrixStage {
  key: string;
  label: string;
  level: "shot" | "chapter";
  step_id: string;
}

export interface MatrixCell {
  status: "empty" | "partial" | "done";
  done: number;
  total: number;
  missing: number[];
  failed: number;
  updated_at: string;
}

export interface MatrixRow {
  id: string;
  order_no: number;
  title: string;
  shot_count: number;
  cells: Record<string, MatrixCell>;
}

export interface MatrixData {
  id: string;
  name: string;
  stages: MatrixStage[];
  rows: MatrixRow[];
  /** 阶段汇总 + chapters/shots 两个计数键 */
  summary: Record<string, any>;
}

/** 资产审查元信息（与 tree 里的 URL 列表一一对应） */
interface AssetMeta {
  asset_id: string;
  url: string;
  review_status: string;
  review_note: string;
  is_primary: boolean;
}

/** 树接口（抽屉明细）的最小可用结构 */
interface TreeShot {
  id: string;
  order_no: number;
  label: string;
  scene_descriptions: string[];
  image_prompt?: string;
  frames: string[];
  videos: string[];
  audios: string[];
  renders: string[];
  frames_meta?: AssetMeta[];
  videos_meta?: AssetMeta[];
  audios_meta?: AssetMeta[];
  renders_meta?: AssetMeta[];
}

interface TreeChapter {
  id: string;
  title: string;
  shots: TreeShot[];
}

const CELL_STYLE: Record<string, string> = {
  done: "bg-emerald-500/15 text-emerald-600 border-emerald-500/30 hover:bg-emerald-500/25",
  partial: "bg-amber-500/15 text-amber-600 border-amber-500/30 hover:bg-amber-500/25",
  empty: "bg-muted/60 text-muted-foreground/70 border-border/40 hover:bg-muted",
};

const DOT_STYLE: Record<string, string> = {
  done: "bg-emerald-500",
  partial: "bg-amber-500",
  empty: "bg-muted-foreground/30",
};

const STAGE_MEDIA: Record<string, "image" | "video" | "audio" | "text"> = {
  frame: "image",
  video: "video",
  dub: "audio",
  render: "video",
  prompt: "text",
  shot: "text",
};

function formatTime(value: string): string {
  if (!value) return "";
  return String(value).replace("T", " ").slice(0, 16);
}

const REVIEW_STYLE: Record<string, { label: string; cls: string }> = {
  approved: { label: "已通过", cls: "bg-emerald-500/15 text-emerald-600 border-emerald-500/30" },
  rejected: { label: "已打回", cls: "bg-red-500/15 text-red-600 border-red-500/30" },
  "": { label: "未审", cls: "bg-muted text-muted-foreground/70 border-border/40" },
};

/** 单条产物 + 审查操作（通过 / 打回+备注 / 设为主选） */
function AssetItem({ meta, kind, onReviewed }: {
  meta: AssetMeta;
  kind: "image" | "video" | "audio";
  onReviewed: (assetId: string, status: string, note: string, primary?: boolean) => void;
}) {
  const [note, setNote] = useState(meta.review_note || "");
  const [editing, setEditing] = useState(false);
  const style = REVIEW_STYLE[meta.review_status || ""] || REVIEW_STYLE[""];

  return (
    <div className={`rounded-md border p-1.5 space-y-1 ${meta.is_primary ? "border-primary ring-1 ring-primary/40" : "border-border/40"}`}>
      {kind === "image" ? (
        <a href={meta.url} target="_blank" rel="noreferrer">
          <img src={meta.url} alt="" loading="lazy"
            className="h-16 w-auto max-w-[120px] object-cover rounded hover:opacity-90" />
        </a>
      ) : kind === "video" ? (
        <video src={meta.url} controls preload="metadata" className="w-40 rounded bg-black" />
      ) : (
        <audio src={meta.url} controls preload="metadata" className="w-40 h-8" />
      )}
      <div className="flex items-center gap-1 flex-wrap">
        <span className={`text-[9px] px-1 py-0.5 rounded border ${style.cls}`}>{style.label}</span>
        {meta.is_primary && (
          <span className="text-[9px] px-1 py-0.5 rounded bg-primary/15 text-primary">主选</span>
        )}
        <button type="button"
          onClick={() => onReviewed(meta.asset_id, "approved", note)}
          className="ml-auto px-1 py-0.5 text-[9px] rounded border border-emerald-500/40 text-emerald-600 hover:bg-emerald-500/10">
          通过
        </button>
        <button type="button"
          onClick={() => setEditing((v) => !v)}
          className="px-1 py-0.5 text-[9px] rounded border border-red-500/40 text-red-600 hover:bg-red-500/10">
          打回
        </button>
        <button type="button" title="N 选 1：设为该分镜本阶段的主选产物"
          onClick={() => onReviewed(meta.asset_id, meta.review_status || "", note, true)}
          className="px-1 py-0.5 text-[9px] rounded border border-border/50 hover:bg-muted">
          主选
        </button>
      </div>
      {editing && (
        <div className="flex items-center gap-1">
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="打回原因（可选）"
            className="flex-1 text-[10px] px-1.5 py-0.5 rounded border border-border/50 bg-background outline-none"
          />
          <button type="button"
            onClick={() => { onReviewed(meta.asset_id, "rejected", note); setEditing(false); }}
            className="px-1.5 py-0.5 text-[9px] rounded bg-red-500 text-white hover:opacity-90">
            提交
          </button>
        </div>
      )}
      {meta.review_note && !editing && (
        <div className="text-[9px] text-muted-foreground truncate" title={meta.review_note}>
          备注：{meta.review_note}
        </div>
      )}
    </div>
  );
}

/** 产物列表：有审查元信息时逐条可审，否则退回纯预览 */
function ShotMedia({ urls, meta, kind, onReviewed }: {
  urls: string[];
  meta?: AssetMeta[];
  kind: "image" | "video" | "audio";
  onReviewed: (assetId: string, status: string, note: string, primary?: boolean) => void;
}) {
  if (!urls?.length) {
    return <span className="text-[10px] text-muted-foreground/60">缺失</span>;
  }
  if (meta && meta.length === urls.length) {
    return (
      <div className="flex gap-1.5 flex-wrap">
        {meta.map((m) => (
          <AssetItem key={m.asset_id || m.url} meta={m} kind={kind} onReviewed={onReviewed} />
        ))}
      </div>
    );
  }
  if (kind === "image") {
    return (
      <div className="flex gap-1.5 flex-wrap">
        {urls.map((u, i) => (
          <a key={i} href={u} target="_blank" rel="noreferrer">
            <img src={u} alt="" loading="lazy"
              className="h-16 w-auto max-w-[120px] object-cover rounded-md border border-border/40 hover:opacity-90" />
          </a>
        ))}
      </div>
    );
  }
  if (kind === "video") {
    return (
      <div className="flex gap-1.5 flex-wrap">
        {urls.map((u, i) => (
          <video key={i} src={u} controls preload="metadata"
            className="w-44 rounded-md border border-border/40 bg-black" />
        ))}
      </div>
    );
  }
  return (
    <div className="flex gap-1.5 flex-wrap">
      {urls.map((u, i) => (
        <audio key={i} src={u} controls preload="metadata" className="w-44 h-8" />
      ))}
    </div>
  );
}

/** 格子：状态色 + n/N + 失败角标 + 运行态 + 悬浮执行按钮 */
function MatrixCellView({ cell, running, onRun, onClick }: {
  cell: MatrixCell;
  running: boolean;
  onRun: (force: boolean) => void;
  onClick: () => void;
}) {
  const hasTotal = (cell.total || 0) > 0;
  return (
    <div className="relative group/cell">
      <button
        type="button"
        onClick={onClick}
        className={`relative w-full px-2 py-1.5 rounded-md border text-[11px] font-medium transition-colors ${CELL_STYLE[cell.status] || CELL_STYLE.empty}`}
      >
        <span className="inline-flex items-center gap-1">
          {running ? (
            <Loader2 className="w-3 h-3 animate-spin text-primary" />
          ) : (
            <span className={`w-1.5 h-1.5 rounded-full ${DOT_STYLE[cell.status] || DOT_STYLE.empty}`} />
          )}
          {running ? "进行中" : cell.status === "empty" && !hasTotal ? "未开始" : `${cell.done}${hasTotal ? `/${cell.total}` : " 镜"}`}
        </span>
        {cell.failed > 0 && (
          <span className="absolute -top-1.5 -right-1.5 min-w-[14px] h-[14px] px-[3px] rounded-full bg-red-500 text-white text-[9px] leading-[14px] font-bold">
            {cell.failed}
          </span>
        )}
      </button>
      {!running && (
        <button
          type="button"
          title="生成 / 补齐该阶段"
          onClick={(e) => { e.stopPropagation(); onRun(false); }}
          className="absolute -top-2 -right-2 hidden group-hover/cell:flex w-5 h-5 items-center justify-center rounded-full bg-primary text-primary-foreground shadow hover:opacity-90"
        >
          <Play className="w-2.5 h-2.5" />
        </button>
      )}
    </div>
  );
}

/** 点击格子后的分镜级产物墙 */
function StageDrawer({ chapter, stageKey, stageLabel, running, onRun, onReviewed, onClose }: {
  chapter: TreeChapter;
  stageKey: string;
  stageLabel: string;
  running: boolean;
  onRun: (force: boolean) => void;
  onReviewed: (assetId: string, status: string, note: string, primary?: boolean) => void;
  onClose: () => void;
}) {
  const stageMetas: AssetMeta[] = chapter.shots.flatMap((s) =>
    stageKey === "frame" ? (s.frames_meta || [])
      : stageKey === "video" ? (s.videos_meta || [])
        : stageKey === "dub" ? (s.audios_meta || [])
          : stageKey === "render" ? (s.renders_meta || [])
            : []);
  const approved = stageMetas.filter((m) => m.review_status === "approved").length;
  const rejected = stageMetas.filter((m) => m.review_status === "rejected").length;
  const pending = Math.max(0, stageMetas.length - approved - rejected);

  const stageKind = STAGE_MEDIA[stageKey] || "image";
  const kind: "image" | "video" | "audio" =
    stageKind === "video" ? "video" : stageKind === "audio" ? "audio" : "image";
  const missingFirst = chapter.shots.filter((s) => {
    if (kind === "image") return !s.frames?.length;
    if (kind === "video") return !s.videos?.length && !s.renders?.length;
    if (kind === "audio") return !s.audios?.length;
    if (stageKey === "prompt") return !String(s.image_prompt || "").trim();
    return false;
  });

  return (
    <div className="absolute inset-y-0 right-0 w-[560px] max-w-[92vw] bg-background border-l border-border/60 shadow-2xl flex flex-col z-20">
      <div className="flex items-center gap-2 px-3 py-2.5 border-b border-border/50 bg-muted/30 flex-shrink-0">
        <Grid3x3 className="w-3.5 h-3.5 text-primary" />
        <span className="text-xs font-semibold truncate">{chapter.title}</span>
        <ChevronRight className="w-3 h-3 text-muted-foreground" />
        <span className="text-xs text-muted-foreground">{stageLabel}</span>
        <span className="ml-auto text-[10px] text-muted-foreground">
          共 {chapter.shots.length} 镜{missingFirst.length ? ` · 缺 ${missingFirst.length} 镜` : ""}
        </span>
        {running ? (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] bg-primary/10 text-primary">
            <Loader2 className="w-3 h-3 animate-spin" />进行中
          </span>
        ) : (
          <>
            <button type="button"
              onClick={() => onRun(false)}
              className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium border border-primary/40 bg-primary/10 text-primary hover:bg-primary/20">
              <Play className="w-3 h-3" />生成
            </button>
            <button type="button"
              onClick={() => onRun(true)}
              title="忽略已完成产物，强制重跑本阶段"
              className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium border border-border/50 hover:bg-muted">
              <RotateCw className="w-3 h-3" />强制重跑
            </button>
          </>
        )}
        <button type="button" onClick={onClose} className="p-1 rounded-md hover:bg-muted text-muted-foreground">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
      {missingFirst.length > 0 && (
        <div className="px-3 py-1.5 text-[10px] text-amber-600 bg-amber-500/5 border-b border-border/40 flex-shrink-0">
          缺口镜号：{missingFirst.map((s) => `#${s.order_no}`).join("、")}
        </div>
      )}
      {!!stageMetas.length && (
        <div className="px-3 py-1.5 text-[10px] text-muted-foreground border-b border-border/40 flex items-center gap-2 flex-shrink-0">
          <span className="text-emerald-600">通过 {approved}</span>
          <span className="text-red-600">打回 {rejected}</span>
          <span>未审 {pending}</span>
          {rejected > 0 && <span className="ml-auto text-amber-600">有打回项，可用「强制重跑」重做本阶段</span>}
        </div>
      )}
      <div className="flex-1 overflow-y-auto p-3 space-y-2.5">
        {chapter.shots.map((s) => (
          <div key={s.id} className="rounded-xl border border-border/50 bg-background/90 p-2.5">
            <div className="flex items-center gap-1.5 mb-1.5">
              <span className="text-[11px] font-bold text-primary">#{s.order_no}</span>
              <span className="text-[10px] text-muted-foreground truncate flex-1">
                {(s.scene_descriptions?.[0] || s.label || "").slice(0, 40)}
              </span>
            </div>
            {stageKey === "prompt" ? (
              <div className="text-[10px] whitespace-pre-wrap text-muted-foreground bg-muted/40 rounded-md p-2 max-h-40 overflow-y-auto">
                {String(s.image_prompt || "").trim() || "（尚未生成提示词）"}
              </div>
            ) : stageKey === "shot" ? (
              <div className="text-[10px] text-muted-foreground space-y-0.5">
                {(s.scene_descriptions || []).map((d, i) => (
                  <div key={i}>· {d}</div>
                ))}
                {!s.scene_descriptions?.length && <div>（无画面描述）</div>}
              </div>
            ) : (
              <ShotMedia
                urls={kind === "image" ? s.frames : kind === "audio" ? s.audios : [...(s.videos || []), ...(s.renders || [])]}
                meta={kind === "image" ? s.frames_meta
                  : kind === "audio" ? s.audios_meta
                    : [...(s.videos_meta || []), ...(s.renders_meta || [])]}
                kind={kind}
                onReviewed={onReviewed}
              />
            )}
          </div>
        ))}
        {!chapter.shots.length && (
          <div className="text-[11px] text-muted-foreground text-center py-8">该章节还没有分镜</div>
        )}
      </div>
    </div>
  );
}

export function CreationMatrixPanel({ creationId }: { creationId: string }) {
  const [data, setData] = useState<MatrixData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [transposed, setTransposed] = useState(false);
  /** 打开的格子：{chapterId, stageKey, stageLabel} */
  const [open, setOpen] = useState<{ chapterId: string; stageKey: string; stageLabel: string } | null>(null);
  const [treeChapters, setTreeChapters] = useState<TreeChapter[] | null>(null);
  const [treeLoading, setTreeLoading] = useState(false);
  /** 驾驶舱任务（用于格子显示「进行中」与失败标记） */
  const [tasks, setTasks] = useState<CockpitTask[]>([]);
  /** 正在发起的任务 key：`${chapter_id}:${step_id}` */
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const [runError, setRunError] = useState("");
  const treeRef = useRef<TreeChapter[] | null>(null);
  treeRef.current = treeChapters;

  const load = useCallback(() => {
    if (!creationId) {
      setError("尚未产生创作项目（请先运行节点或从项目列表选择）");
      setData(null);
      return;
    }
    setLoading(true);
    setError("");
    client.get(`/api/creation/${creationId}/matrix`)
      .then((res) => setData(res.data))
      .catch((e) => {
        setError(e?.response?.data?.detail || e?.message || "矩阵加载失败");
        setData(null);
      })
      .finally(() => setLoading(false));
  }, [creationId]);

  useEffect(() => { load(); }, [load]);

  // ---------------- 驾驶舱任务：回查 + 执行 ----------------
  const loadTasks = useCallback(() => {
    if (!creationId) return Promise.resolve();
    return client.get("/api/creation/tasks", { params: { creation_id: creationId, limit: 50 } })
      .then((res) => setTasks(res.data?.tasks || []))
      .catch(() => setTasks([]));
  }, [creationId]);

  useEffect(() => { loadTasks(); }, [loadTasks]);

  const activeTasks = useMemo(
    () => tasks.filter((t) => ACTIVE_TASK_STATUS.includes(t.status)),
    [tasks]
  );

  // 有任务在跑时轮询；全部结束后刷新矩阵与分镜明细
  const finishedRef = useRef(0);
  const keepAliveActive = useKeepAliveActive();
  useEffect(() => {
    // 被 KeepAlive 隐藏时整体挂起：既不 4s 轮询也不触发收尾刷新
    if (!keepAliveActive) return;
    if (!activeTasks.length) {
      if (finishedRef.current > 0) {
        finishedRef.current = 0;
        load();
        setTreeChapters(null); // 让抽屉下次打开时重新拉取最新产物
        loadTasks();
      }
      return;
    }
    finishedRef.current = activeTasks.length;
    const timer = window.setInterval(() => { loadTasks(); }, 4000);
    return () => window.clearInterval(timer);
  }, [activeTasks.length, load, loadTasks, keepAliveActive]);

  /** 发起一次「章节 × 阶段」生产 */
  const runStage = (chapterId: string, stepId: string, force: boolean) => {
    if (!creationId || !stepId) return;
    const key = `${chapterId}:${stepId}`;
    setPending((prev) => ({ ...prev, [key]: true }));
    setRunError("");
    client.post("/api/creation/run-stage", {
      creation_id: creationId,
      step_id: stepId,
      chapter_id: chapterId,
      force,
    })
      .then(() => { loadTasks(); })
      .catch((e) => {
        setRunError(e?.response?.data?.detail || e?.message || "任务投递失败");
      })
      .finally(() => {
        setPending((prev) => {
          const next = { ...prev };
          delete next[key];
          return next;
        });
      });
  };

  /** 该格子是否正在执行（任务活跃或刚投递） */
  const isRunning = (chapterId: string, stepId: string) => {
    if (pending[`${chapterId}:${stepId}`]) return true;
    return tasks.some((t) => t.chapter_id === chapterId && t.step_id === stepId
      && ACTIVE_TASK_STATUS.includes(t.status));
  };

  /** 审查一条资产：落库后本地同步元信息（避免整棵树重拉） */
  const reviewAsset = (assetId: string, status: string, note: string, primary?: boolean) => {
    if (!assetId) return;
    client.put(`/api/creation/assets/${assetId}/review`, {
      status,
      note: note || "",
      primary: primary === undefined ? null : primary,
    })
      .then((res) => {
        const updated = res.data || {};
        setTreeChapters((prev) => (prev || []).map((ch) => ({
          ...ch,
          shots: ch.shots.map((s) => {
            const patch = (list?: AssetMeta[]) => (list || []).map((m) =>
              m.asset_id === assetId
                ? { ...m, review_status: updated.review_status ?? status,
                    review_note: updated.review_note ?? note,
                    is_primary: primary === true ? true : (primary === false ? false : (updated.is_primary ?? m.is_primary)) }
                : (primary === true ? { ...m, is_primary: false } : m));
            return {
              ...s,
              frames_meta: patch(s.frames_meta),
              videos_meta: patch(s.videos_meta),
              audios_meta: patch(s.audios_meta),
              renders_meta: patch(s.renders_meta),
            };
          }),
        })));
      })
      .catch((e) => setRunError(e?.response?.data?.detail || e?.message || "审查保存失败"));
  };

  // 展开格子时才拉取分镜级明细（含可播放地址）
  const openCell = (chapterId: string, stageKey: string, stageLabel: string) => {
    setOpen({ chapterId, stageKey, stageLabel });
    const fetchTree = () => {
      setTreeLoading(true);
      client.get(`/api/creation/${creationId}/tree`)
        .then((res) => setTreeChapters(res.data?.chapters || []))
        .catch(() => setTreeChapters([]))
        .finally(() => setTreeLoading(false));
    };
    if (treeRef.current) return;
    fetchTree();
  };

  const stages = data?.stages || [];
  const rows = data?.rows || [];

  const openChapter = useMemo(
    () => (treeChapters || []).find((c) => c.id === open?.chapterId) || null,
    [treeChapters, open]
  );

  if (loading && !data) {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground">
        <Loader2 className="w-5 h-5 animate-spin mr-2" /> 加载中…
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="h-full flex items-center justify-center text-sm text-amber-600 gap-2">
        <AlertTriangle className="w-4 h-4" /> {error}
        <button type="button" onClick={load}
          className="ml-2 px-2 py-1 rounded-md border border-border/50 text-xs hover:bg-muted">重试</button>
      </div>
    );
  }

  if (!data || !rows.length) {
    return (
      <div className="h-full flex items-center justify-center text-sm text-muted-foreground">
        该项目还没有章节，先运行「章节规划」节点
      </div>
    );
  }

  return (
    <div className="relative h-full flex flex-col">
      {/* 工具条：图例 + 视角切换 + 刷新 */}
      <div className="flex items-center gap-2 mb-2 flex-shrink-0 flex-wrap">
        <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
          {[["done", "已完成"], ["partial", "部分"], ["empty", "未开始"]].map(([key, label]) => (
            <span key={key} className="inline-flex items-center gap-1">
              <span className={`w-2 h-2 rounded-full ${DOT_STYLE[key]}`} />{label}
            </span>
          ))}
          <span className="inline-flex items-center gap-1">
            <span className="w-3.5 h-3.5 rounded-full bg-red-500 text-white text-[9px] leading-[14px] text-center font-bold">!</span>
            失败次数
          </span>
        </div>
        {activeTasks.length > 0 && (
          <span className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] bg-primary/10 text-primary">
            <Loader2 className="w-3 h-3 animate-spin" />进行中 {activeTasks.length}
          </span>
        )}
        <button type="button"
          onClick={() => setTransposed((v) => !v)}
          className="ml-auto px-2.5 py-1 rounded-md text-[11px] font-medium border border-border/50 hover:bg-muted transition-colors">
          {transposed ? "按章看" : "按阶段看"}
        </button>
        <button type="button" onClick={load} title="刷新"
          className="p-1.5 rounded-md hover:bg-muted text-muted-foreground">
          <RefreshCw className={"w-3.5 h-3.5" + (loading ? " animate-spin" : "")} />
        </button>
      </div>

      {runError && (
        <div className="mb-2 flex items-center gap-2 px-2.5 py-1.5 rounded-md border border-amber-500/40 bg-amber-500/10 text-[11px] text-amber-600 flex-shrink-0">
          <AlertTriangle className="w-3.5 h-3.5" />{runError}
          <button type="button" onClick={() => setRunError("")} className="ml-auto hover:opacity-70">
            <X className="w-3 h-3" />
          </button>
        </div>
      )}

      {/* 项目汇总 */}
      <div className="flex items-center gap-3 text-[10px] text-muted-foreground mb-2 flex-shrink-0">
        <span>{data.summary?.chapters ?? rows.length} 章</span>
        <span>{data.summary?.shots ?? 0} 镜</span>
        {stages.map((s) => {
          const sum = data.summary?.[s.key];
          if (!sum) return null;
          return (
            <span key={s.key} className="inline-flex items-center gap-1">
              <span className={`w-1.5 h-1.5 rounded-full ${DOT_STYLE[sum.status] || DOT_STYLE.empty}`} />
              {s.label} {sum.done}/{sum.total}
            </span>
          );
        })}
      </div>

      {/* 矩阵 */}
      <div className="flex-1 overflow-auto rounded-xl border border-border/50 bg-background">
        <table className="border-collapse text-xs w-full">
          <thead className="sticky top-0 z-10 bg-muted/60 backdrop-blur">
            <tr>
              <th className="sticky left-0 z-20 bg-muted/90 px-3 py-2 text-left font-semibold whitespace-nowrap border-b border-r border-border/50 min-w-[140px]">
                {transposed ? "生产阶段" : "章节"}
              </th>
              {(transposed ? rows : stages).map((col: any) => (
                <th key={col.id || col.key}
                  className="px-2 py-2 text-center font-medium text-muted-foreground whitespace-nowrap border-b border-border/50 min-w-[96px]">
                  {transposed ? col.title : col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(transposed ? stages : rows).map((row: any) => (
              <tr key={row.id || row.key} className="border-b border-border/40 last:border-b-0">
                <th className="sticky left-0 z-10 bg-muted/90 px-3 py-2 text-left font-medium whitespace-nowrap border-r border-border/50">
                  {transposed ? row.label : row.title}
                  {!transposed && <span className="ml-1 text-[10px] text-muted-foreground/70">{row.shot_count}镜</span>}
                </th>
                {(transposed ? rows : stages).map((col: any) => {
                  const chapterId = transposed ? col.id : row.id;
                  const stage = transposed ? row : col;
                  const cell: MatrixCell | undefined = row?.cells?.[stage.key] ?? col?.cells?.[stage.key];
                  const resolved = cell || (transposed ? col.cells?.[stage.key] : row.cells?.[stage.key]);
                  if (!resolved) {
                    return <td key={col.id || col.key} className="px-2 py-2 text-center text-muted-foreground/50">—</td>;
                  }
                  const running = isRunning(chapterId, stage.step_id);
                  return (
                    <td key={col.id || col.key} className="px-1.5 py-1.5 align-middle">
                      <div title={`${resolved.done}/${resolved.total}${resolved.updated_at ? ` · ${formatTime(resolved.updated_at)}` : ""}`}>
                        <MatrixCellView
                          cell={resolved}
                          running={running}
                          onRun={(force) => runStage(chapterId, stage.step_id, force)}
                          onClick={() => openCell(chapterId, stage.key, stage.label)}
                        />
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 分镜级产物墙 */}
      {open && (
        <>
          <div className="absolute inset-0 bg-black/20 z-10" onClick={() => setOpen(null)} />
          {openChapter ? (
            <StageDrawer
              chapter={openChapter}
              stageKey={open.stageKey}
              stageLabel={open.stageLabel}
              running={isRunning(open.chapterId, stages.find((s) => s.key === open.stageKey)?.step_id || "")}
              onRun={(force) => runStage(
                open.chapterId,
                stages.find((s) => s.key === open.stageKey)?.step_id || "",
                force)}
              onReviewed={reviewAsset}
              onClose={() => setOpen(null)}
            />
          ) : (
            <div className="absolute inset-y-0 right-0 w-[560px] max-w-[92vw] bg-background border-l border-border/60 shadow-2xl flex items-center justify-center z-20 text-muted-foreground text-xs">
              {treeLoading ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : "暂无分镜明细"}
              {treeLoading ? "加载中…" : null}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default CreationMatrixPanel;

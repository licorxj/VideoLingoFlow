import { createPortal } from "react-dom";
import { useEffect, useMemo, useState } from "react";
import client from "@/api/client";
import CreationMatrixPanel from "@/components/creation/CreationMatrixPanel";
import {
  X, RefreshCw, Network, BookOpen, Users, Clapperboard, Scissors,
  Image as ImageIcon, Film, Mic2, AudioLines, Loader2, AlertTriangle,
  LayoutGrid, ArrowLeft, Pencil, Save, Eye, Package,
} from "lucide-react";

/** 文本固定框：限定高度内部滚动，避免长文撑爆版面 */
const FIXED_TEXT = "max-h-24 overflow-y-auto whitespace-pre-wrap break-words text-[11px] leading-relaxed bg-muted/30 border border-border/40 rounded-md px-2 py-1.5 text-foreground/90 relative group";

type Dialogue = { character?: string; content?: string };
type Shot = {
  id: string; order_no?: number; label?: string;
  scene_descriptions?: string[]; characters?: (string | { name?: string })[];
  dialogues?: Dialogue[]; bgm_design?: string; sfx_design?: string;
  frames?: string[]; videos?: string[]; audios?: string[]; renders?: string[];
};
type Chapter = {
  id: string; order_no?: number; title?: string; summary?: string;
  original_text?: string; shots?: Shot[];
};
type CharacterItem = {
  id: string; name?: string; gender?: string; age?: string;
  personality?: string; occupation?: string; voice_design?: string;
  voice_url?: string; images?: string[];
};
type PropItem = { id: string; name?: string; type?: string; description?: string; url?: string };
type Tree = {
  id: string; name?: string; description?: string; status?: string;
  genre_tags?: string[]; art_style_tags?: string[]; audience_tags?: string[];
  script_text?: string; characters?: CharacterItem[];
  scenes?: { id?: string; url: string; description?: string; name?: string; location?: string; time?: string }[];
  props?: PropItem[];
  chapters?: Chapter[];
};
type ProjectSummary = {
  id: string; name?: string; description?: string; status?: string;
  updated_at?: string;
  counts?: { characters?: number; chapters?: number; shots?: number };
  asset_counts?: Record<string, number>;
  assets_total?: number;
  progress?: { stage?: string; percent?: number };
  cover?: string;
};

type TextScope =
  | { type: "creation"; id: string; field: "description" | "script_text" }
  | { type: "character"; id: string; field: "personality" }
  | { type: "scene"; id: string; field: "description" }
  | { type: "prop"; id: string; field: "description" }
  | { type: "chapter"; id: string; field: "summary" | "original_text" }
  | { type: "shot"; chapterId: string; id: string; field: "scene_descriptions" | "dialogues" | "bgm_design" | "sfx_design" };

const ASSET_LABELS: Record<string, string> = {
  character: "角色", scene_image: "图", shot_video: "视频",
  voiceover: "配音", sfx: "音效", bgm: "BGM",
  shot_render: "成片", chapter_render: "章节成片",
};

function splitScript(text: string): { head: string; body: string }[] {
  return (text || "")
    .split(/(?=【)/)
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => {
      const m = s.match(/^【(.+?)】\s*/);
      return m ? { head: m[1], body: s.slice(m[0].length).trim() } : { head: "", body: s };
    });
}

function formatDialogues(dialogues?: Dialogue[]): string {
  return (dialogues || [])
    .map((d) => `${d.character || "?"}：${d.content || ""}`)
    .join("\n");
}

function parseDialogues(text: string): Dialogue[] {
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((line) => {
      const idx = line.search(/[：:]/);
      if (idx > 0) {
        return { character: line.slice(0, idx).trim(), content: line.slice(idx + 1).trim() };
      }
      return { character: "?", content: line };
    });
}

function buildSavePayload(scope: TextScope, value: string): { url: string; payload: unknown } {
  switch (scope.type) {
    case "creation":
      return { url: `/api/creation/${scope.id}`, payload: { [scope.field]: value } };
    case "character":
      return { url: `/api/creation/characters/${scope.id}`, payload: { [scope.field]: value } };
    case "scene":
      // 浏览树把 scene.prompt 作为描述展示，编辑时回写 prompt
      return { url: `/api/creation/scenes/${scope.id}`, payload: { prompt: value } };
    case "prop":
      return { url: `/api/creation/props/${scope.id}`, payload: { description: value } };
    case "chapter":
      return { url: `/api/creation/chapters/${scope.id}`, payload: { [scope.field]: value } };
    case "shot": {
      if (scope.field === "scene_descriptions") {
        return { url: `/api/creation/shots/${scope.id}`, payload: { scene_descriptions: value.split("\n").map((s) => s.trim()).filter(Boolean) } };
      }
      if (scope.field === "dialogues") {
        return { url: `/api/creation/shots/${scope.id}`, payload: { dialogues: parseDialogues(value) } };
      }
      return { url: `/api/creation/shots/${scope.id}`, payload: { [scope.field]: value } };
    }
  }
}

/** 文本放大/编辑弹窗 */
function TextZoomDialog({ open, title, value, multiline, onClose, onSave }: {
  open: boolean; title: string; value: string; multiline?: boolean;
  onClose: () => void; onSave: (v: string) => Promise<void>;
}) {
  const [text, setText] = useState(value);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => { setText(value); setErr(""); }, [value, open]);
  if (!open) return null;

  const save = async () => {
    setSaving(true);
    setErr("");
    try {
      await onSave(text);
      onClose();
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const INP = "w-full rounded-lg border border-border/60 bg-muted/40 px-3 py-2 text-sm focus:outline-none focus:border-primary/60 focus:ring-1 focus:ring-primary/30";
  return (
    <div className="fixed inset-0 z-[10030] bg-black/70 flex items-center justify-center p-6"
      onClick={(e) => { e.stopPropagation(); onClose(); }}>
      <div className="w-[80vw] max-w-3xl h-[80vh] flex flex-col rounded-xl border border-border/60 bg-background shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 px-4 py-3 border-b border-border/50 bg-muted/30 flex-shrink-0">
          <Eye className="w-4 h-4 text-primary" />
          <span className="text-sm font-semibold truncate">{title}</span>
          <button type="button" onClick={onClose}
            className="ml-auto p-1.5 rounded-md hover:bg-muted text-muted-foreground" title="关闭">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="flex-1 overflow-auto p-4">
          {multiline ? (
            <textarea className={INP + " h-full min-h-[320px] resize-none font-mono text-[13px] leading-relaxed"}
              value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
          ) : (
            <textarea className={INP + " h-full min-h-[320px] resize-none leading-relaxed"}
              value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
          )}
        </div>
        {err && <div className="px-4 text-xs text-amber-600">{err}</div>}
        <div className="flex items-center justify-end gap-2 px-4 py-3 border-t border-border/50 bg-muted/30 flex-shrink-0">
          <button type="button" onClick={onClose}
            className="px-3 py-1.5 rounded-md text-xs border border-border/50 hover:bg-muted">取消</button>
          <button type="button" onClick={save} disabled={saving}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-60">
            {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            保存
          </button>
        </div>
      </div>
    </div>
  );
}

function EditableTextBlock({ text, title, scope, onSaved }: {
  text: string; title: string; scope?: TextScope; onSaved?: () => void;
}) {
  const [zoomOpen, setZoomOpen] = useState(false);
  if (!text && !scope) return null;

  const displayText = text || "";

  const handleSave = async (value: string) => {
    if (!scope) return;
    const { url, payload } = buildSavePayload(scope, value);
    await client.put(url, payload);
    onSaved?.();
  };

  return (
    <>
      <div className={FIXED_TEXT}>
        {displayText}
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); setZoomOpen(true); }}
          className="absolute top-1 right-1 p-1 rounded-md opacity-60 hover:opacity-100 hover:bg-primary/10 text-muted-foreground hover:text-primary transition-colors"
          title="放大查看 / 编辑"
        >
          <Eye className="w-3 h-3" />
        </button>
      </div>
      {zoomOpen && (
        <TextZoomDialog
          open={zoomOpen}
          title={title}
          value={displayText}
          multiline
          onClose={() => setZoomOpen(false)}
          onSave={scope ? handleSave : async () => { /* 只读 */ }}
        />
      )}
    </>
  );
}

function MediaStrip({ urls, kind, onZoom }: {
  urls: string[]; kind: "image" | "video" | "audio";
  onZoom: (u: string) => void;
}) {
  if (!urls?.length) return null;
  if (kind === "image") {
    return (
      <div className="flex gap-1.5 flex-wrap">
        {urls.map((u, i) => (
          <img
            key={i}
            src={u}
            alt=""
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => { e.stopPropagation(); onZoom(u); }}
            className="h-20 w-auto max-w-[160px] object-cover rounded-lg border border-border/40 cursor-zoom-in hover:opacity-90 hover:shadow-sm transition-all"
            loading="lazy"
          />
        ))}
      </div>
    );
  }
  if (kind === "video") {
    return (
      <div className="flex gap-1.5 flex-wrap">
        {urls.map((u, i) => (
          <video key={i} src={u} controls preload="metadata"
            onPointerDown={(e) => e.stopPropagation()}
            className="w-48 rounded-lg border border-border/40 bg-black" />
        ))}
      </div>
    );
  }
  return (
    <div className="flex gap-1.5 flex-wrap">
      {urls.map((u, i) => (
        <audio key={i} src={u} controls preload="metadata"
          onPointerDown={(e) => e.stopPropagation()}
          className="w-48 h-8" />
      ))}
    </div>
  );
}

/** 章节「人工审改」弹层：编辑标题/摘要/格式化剧本文本并保存 */
function ChapterEditor({ chapter, onCancel, onSaved }: {
  chapter: Chapter;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [title, setTitle] = useState(chapter.title || "");
  const [summary, setSummary] = useState(chapter.summary || "");
  const [text, setText] = useState(chapter.original_text || "");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  const dirty = (): Record<string, string> => {
    const out: Record<string, string> = {};
    if (title !== (chapter.title || "")) out.title = title;
    if (summary !== (chapter.summary || "")) out.summary = summary;
    if (text !== (chapter.original_text || "")) out.original_text = text;
    return out;
  };

  const save = () => {
    const patch = dirty();
    if (!Object.keys(patch).length) { onCancel(); return; }
    setSaving(true);
    setErr("");
    client.put(`/api/creation/chapters/${chapter.id}`, patch)
      .then(() => { onSaved(); onCancel(); })
      .catch((e) => { setErr(e?.response?.data?.detail || e?.message || "保存失败"); })
      .finally(() => setSaving(false));
  };

  const INP = "w-full rounded-md border border-border/50 bg-muted/40 px-2 py-1.5 text-xs focus:outline-none focus:border-primary/60";
  return (
    <div className="fixed inset-0 z-[10020] bg-black/60 flex items-center justify-center p-6"
      onClick={(e) => { e.stopPropagation(); onCancel(); }}>
      <div className="w-[72vw] max-w-3xl h-[82vh] flex flex-col rounded-xl border border-border/60 bg-background shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border/50 bg-muted/30 flex-shrink-0">
          <BookOpen className="w-4 h-4 text-amber-500" />
          <span className="text-sm font-semibold truncate">
            人工审改 · {chapter.title || `第${chapter.order_no}章`}
          </span>
          <span className="text-[10px] text-muted-foreground">保存后下游提取/拆解以修改后的剧本为准</span>
          <button type="button" onClick={onCancel}
            className="ml-auto p-1.5 rounded-md hover:bg-muted text-muted-foreground" title="取消">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="flex-1 overflow-auto p-4 space-y-3">
          <div>
            <div className="text-[11px] font-semibold text-foreground/80 mb-1">标题</div>
            <input className={INP} value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div>
            <div className="text-[11px] font-semibold text-foreground/80 mb-1">摘要</div>
            <textarea className={INP + " h-20 resize-y"} value={summary} onChange={(e) => setSummary(e.target.value)} />
          </div>
          <div>
            <div className="text-[11px] font-semibold text-foreground/80 mb-1">剧本正文（格式化剧本）</div>
            <textarea className={INP + " h-52 resize-y font-mono text-[12px] leading-relaxed"}
              value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
          </div>
          {err && <div className="text-xs text-amber-600">{err}</div>}
        </div>
        <div className="flex items-center justify-end gap-2 px-4 py-2.5 border-t border-border/50 bg-muted/30 flex-shrink-0">
          <button type="button" onClick={onCancel}
            className="px-3 py-1.5 rounded-md text-xs border border-border/50 hover:bg-muted">取消</button>
          <button type="button" onClick={save} disabled={saving}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-60">
            {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            保存
          </button>
        </div>
      </div>
    </div>
  );
}

function SectionTitle({ icon, text, extra }: { icon?: React.ReactNode; text: string; extra?: string }) {
  return (
    <div className="flex items-center gap-1.5 mb-1.5">
      {icon}
      <span className="text-[11px] font-semibold text-foreground/90">{text}</span>
      {extra && <span className="text-[10px] text-muted-foreground">{extra}</span>}
    </div>
  );
}

const BRANCH = "ml-3 pl-3 border-l-2 border-border/40 space-y-3";
const LEAF_TICK = "relative before:absolute before:-left-3 before:top-4 before:w-3 before:h-px before:bg-border/60";
const CARD = "rounded-xl border border-border/50 bg-background/90 p-3 shadow-sm";
const COLUMN = "flex-shrink-0 w-72 bg-muted/20 rounded-2xl border border-border/40 p-3 space-y-3";
const HEADER_CARD = "rounded-xl border border-border/50 bg-gradient-to-r p-3 shadow-sm";

const ASSET_KIND_ORDER = ["character", "scene_image", "shot_video", "voiceover", "sfx", "bgm", "shot_render", "chapter_render"];

/** 项目多宫格首页：所有创作项目的简介 / 进度 / 资产数量 */
function ProjectGrid({ projects, loading, error, onOpen, onReload }: {
  projects: ProjectSummary[];
  loading: boolean;
  error: string;
  onOpen: (id: string) => void;
  onReload: () => void;
}) {
  if (loading && !projects.length) {
    return (
      <div className="h-full flex items-center justify-center text-muted-foreground">
        <Loader2 className="w-5 h-5 animate-spin mr-2" /> 加载中…
      </div>
    );
  }
  if (error && !projects.length) {
    return (
      <div className="h-full flex items-center justify-center text-sm text-amber-600 gap-2">
        <AlertTriangle className="w-4 h-4" /> {error}
        <button type="button" onClick={onReload}
          className="ml-2 px-2 py-1 rounded-md border border-border/50 text-xs hover:bg-muted">重试</button>
      </div>
    );
  }
  if (!projects.length) {
    return (
      <div className="h-full flex items-center justify-center text-sm text-muted-foreground">
        数据库中还没有创作项目，先运行「项目立项·剧本创作」节点
      </div>
    );
  }
  return (
    <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(250px, 1fr))" }}>
      {projects.map((p) => {
        const pct = Math.max(0, Math.min(100, p.progress?.percent ?? 0));
        return (
          <button
            key={p.id}
            type="button"
            onClick={(e) => { e.stopPropagation(); onOpen(p.id); }}
            className={`${CARD} text-left w-full hover:border-primary/50 hover:shadow-md transition-all flex flex-col overflow-hidden`}
          >
            {/* 封面 */}
            <div className="h-24 bg-muted/50 border-b border-border/40 flex items-center justify-center overflow-hidden">
              {p.cover ? (
                <img src={p.cover} alt="" className="w-full h-full object-cover" loading="lazy"
                  onPointerDown={(e) => e.stopPropagation()} />
              ) : (
                <Film className="w-6 h-6 text-muted-foreground/50" />
              )}
            </div>
            <div className="p-2.5 flex flex-col gap-1.5 flex-1">
              <div className="flex items-center gap-1.5">
                <span className="text-xs font-bold truncate flex-1">{p.name}</span>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary flex-shrink-0">
                  {p.status || "draft"}
                </span>
              </div>
              {/* 进度 */}
              <div>
                <div className="flex items-center justify-between text-[10px] text-muted-foreground mb-0.5">
                  <span>{p.progress?.stage || "立项完成"}</span>
                  <span>{pct}%</span>
                </div>
                <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                  <div className="h-full rounded-full bg-primary/70 transition-all" style={{ width: `${pct}%` }} />
                </div>
              </div>
              {/* 简介 */}
              {p.description ? <div className={FIXED_TEXT}>{p.description}</div> : null}
              {/* 结构计数 */}
              <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                <span className="inline-flex items-center gap-0.5"><Users className="w-3 h-3" />{p.counts?.characters ?? 0} 人</span>
                <span className="inline-flex items-center gap-0.5"><BookOpen className="w-3 h-3" />{p.counts?.chapters ?? 0} 章</span>
                <span className="inline-flex items-center gap-0.5"><Clapperboard className="w-3 h-3" />{p.counts?.shots ?? 0} 镜</span>
                <span className="ml-auto inline-flex items-center gap-0.5 text-primary">
                  <Film className="w-3 h-3" />{p.assets_total ?? 0} 资产
                </span>
              </div>
              {/* 资产分类数量 */}
              <div className="flex gap-1 flex-wrap pt-0.5">
                {ASSET_KIND_ORDER.filter((k) => (p.asset_counts?.[k] ?? 0) > 0).map((k) => (
                  <span key={k} className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                    {ASSET_LABELS[k]} ×{p.asset_counts?.[k]}
                  </span>
                ))}
              </div>
              {p.updated_at && (
                <div className="text-[10px] text-muted-foreground/70 mt-auto">
                  更新于 {String(p.updated_at).replace("T", " ").slice(0, 16)}
                </div>
              )}
            </div>
          </button>
        );
      })}
    </div>
  );
}

export default function CreationBrowserDialog({ open, onClose, creationId }: {
  open: boolean;
  onClose: () => void;
  creationId: string;
}) {
  const [tree, setTree] = useState<Tree | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [zoom, setZoom] = useState("");
  /** 正在「人工审改」的章节（非空时显示编辑弹层） */
  const [editing, setEditing] = useState<Chapter | null>(null);
  /** 视图：map=思维导图（单项目） / grid=项目列表首页（多宫格） / matrix=生产矩阵 */
  const [view, setView] = useState<"map" | "grid" | "matrix">("map");
  /** 从项目列表点入的项目（覆盖节点绑定的 creationId） */
  const [browseId, setBrowseId] = useState("");
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(false);
  const [projectsError, setProjectsError] = useState("");

  const effId = browseId || creationId || "";

  useEffect(() => {
    (window as any).__creationBrowserZoom = (u: string) => setZoom(u);
    return () => { delete (window as any).__creationBrowserZoom; };
  }, []);

  const load = (id?: string) => {
    const target = id || effId;
    if (!target) { setError("尚未产生创作项目（请先运行节点或从项目列表选择）"); setTree(null); return; }
    setLoading(true);
    setError("");
    client.get(`/api/creation/${target}/tree`)
      .then((res) => { setTree(res.data); })
      .catch((e) => { setError(e?.response?.data?.detail || e?.message || "加载失败"); setTree(null); })
      .finally(() => setLoading(false));
  };

  const loadProjects = () => {
    setProjectsLoading(true);
    setProjectsError("");
    client.get("/api/creation/list")
      .then((res) => { setProjects(res.data || []); })
      .catch((e) => { setProjectsError(e?.response?.data?.detail || e?.message || "加载失败"); })
      .finally(() => setProjectsLoading(false));
  };

  useEffect(() => {
    if (!open) return;
    if (view === "map") load();
    else if (view === "grid") loadProjects();
    // matrix 视图由 CreationMatrixPanel 自行取数（含独立刷新）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, view, effId]);

  const scriptParts = useMemo(() => splitScript(tree?.script_text || ""), [tree?.script_text]);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
      onPointerDown={(e) => e.stopPropagation()}>
      <div
        className="w-[96vw] h-[90vh] rounded-2xl border border-border/60 bg-background shadow-2xl flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 顶栏 */}
        <div className="flex items-center gap-2 px-4 py-3 border-b border-border/50 bg-muted/30 flex-shrink-0">
          {view === "grid" ? (
            <button type="button"
              onClick={(e) => { e.stopPropagation(); setView("map"); }}
              className="p-1.5 rounded-md hover:bg-muted text-muted-foreground" title="返回导图">
              <ArrowLeft className="w-4 h-4" />
            </button>
          ) : (
            <Network className="w-4 h-4 text-primary" />
          )}
          <span className="text-sm font-semibold">
            {view === "grid" ? "项目列表" : view === "matrix" ? "生产矩阵" : "项目浏览"}
          </span>
          <span className="text-xs text-muted-foreground truncate">
            {view === "grid"
              ? `共 ${projects.length} 个创作项目`
              : (tree?.name || effId)}
          </span>
          <div className="ml-auto flex items-center gap-1.5">
            {/* 生产矩阵：章节 × 阶段的完成度总览 */}
            {view !== "grid" && (
              <button type="button"
                onClick={(e) => { e.stopPropagation(); setView(view === "matrix" ? "map" : "matrix"); }}
                className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-[11px] font-medium border border-border/50 bg-background hover:bg-muted transition-colors"
                title={view === "matrix" ? "返回思维导图" : "查看章节生产矩阵"}>
                <LayoutGrid className="w-3.5 h-3.5" />
                {view === "matrix" ? "返回导图" : "生产矩阵"}
              </button>
            )}
            {/* 项目列表 / 返回导图 切换 */}
            <button type="button"
              onClick={(e) => { e.stopPropagation(); setView(view === "map" ? "grid" : "map"); }}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-[11px] font-medium border border-primary/40 bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
              title={view === "map" ? "查看所有创作项目" : "返回当前项目导图"}>
              {view === "map" ? <LayoutGrid className="w-3.5 h-3.5" /> : <Network className="w-3.5 h-3.5" />}
              {view === "map" ? "项目列表" : "返回导图"}
            </button>
            <button type="button"
              onClick={(e) => { e.stopPropagation(); view === "map" ? load() : loadProjects(); }}
              className="p-1.5 rounded-md hover:bg-muted text-muted-foreground" title="刷新">
              <RefreshCw className={"w-3.5 h-3.5" + ((view === "map" ? loading : projectsLoading) ? " animate-spin" : "")} />
            </button>
            <button type="button" onClick={onClose}
              className="p-1.5 rounded-md hover:bg-muted text-muted-foreground" title="关闭">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* 正文 */}
        <div className="flex-1 overflow-auto p-4 bg-muted/10">
          {view === "grid" ? (
            <ProjectGrid
              projects={projects}
              loading={projectsLoading}
              error={projectsError}
              onOpen={(id) => { setBrowseId(id); setView("map"); }}
              onReload={loadProjects}
            />
          ) : view === "matrix" ? (
            <CreationMatrixPanel creationId={effId} />
          ) : (
            <>
              {loading && !tree && (
                <div className="h-full flex items-center justify-center text-muted-foreground">
                  <Loader2 className="w-5 h-5 animate-spin mr-2" /> 加载中…
                </div>
              )}
              {error && !tree && (
                <div className="h-full flex items-center justify-center text-sm text-amber-600 gap-2">
                  <AlertTriangle className="w-4 h-4" /> {error}
                  <button type="button" onClick={() => { setBrowseId(""); setView("grid"); }}
                    className="ml-2 px-2 py-1 rounded-md border border-border/50 text-xs hover:bg-muted">
                    从项目列表选择
                  </button>
                </div>
              )}
              {tree && (
                <div className="flex items-start gap-4 min-w-max">
                  {/* 第一列：项目根信息 + 故事骨架 */}
                  <div className="sticky left-0 top-0 self-start flex-shrink-0 w-72 max-h-full overflow-y-auto pr-1 space-y-3">
                    {/* 根节点 */}
                    <div className={`${CARD} border-l-4 border-l-primary`}>
                      <div className="text-sm font-bold truncate">{tree.name}</div>
                      <div className="text-[10px] text-muted-foreground mt-0.5">
                        状态：{tree.status || "draft"}
                      </div>
                      <div className="flex gap-1 flex-wrap mt-2">
                        {(tree.genre_tags || []).map((t) => (
                          <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary">{t}</span>
                        ))}
                        {(tree.art_style_tags || []).map((t) => (
                          <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">{t}</span>
                        ))}
                      </div>
                      {tree.description && (
                        <EditableTextBlock
                          text={tree.description}
                          title="项目简介"
                          scope={{ type: "creation", id: tree.id, field: "description" }}
                          onSaved={load}
                        />
                      )}
                    </div>

                    {/* 故事骨架 */}
                    <div className={`${HEADER_CARD} from-sky-500/10 to-transparent border-l-4 border-l-sky-500`}>
                      <SectionTitle icon={<BookOpen className="w-3.5 h-3.5 text-sky-500" />} text="故事骨架" />
                    </div>
                    <div className={BRANCH}>
                      {scriptParts.length ? scriptParts.map((p, i) => (
                        <div key={i} className={`${CARD} ${LEAF_TICK}`}>
                          <SectionTitle text={p.head || "剧本"} />
                          <EditableTextBlock
                            text={p.body}
                            title={p.head || "剧本"}
                            scope={{ type: "creation", id: tree.id, field: "script_text" }}
                            onSaved={load}
                          />
                        </div>
                      )) : (
                        <div className={`${CARD} ${LEAF_TICK}`}>
                          <EditableTextBlock
                            text={tree.script_text || "（暂无）"}
                            title="剧本全文"
                            scope={{ type: "creation", id: tree.id, field: "script_text" }}
                            onSaved={load}
                          />
                        </div>
                      )}
                    </div>
                  </div>

                  {/* 第二列：人物资产 */}
                  <div className={COLUMN}>
                    <div className={`${HEADER_CARD} from-pink-500/10 to-transparent border-l-4 border-l-pink-500`}>
                      <SectionTitle icon={<Users className="w-3.5 h-3.5 text-pink-500" />} text="人物资产"
                        extra={`${tree.characters?.length || 0} 人`} />
                    </div>
                    <div className={BRANCH}>
                      {(tree.characters || []).map((c) => (
                        <div key={c.id} className={`${CARD} ${LEAF_TICK}`}>
                          <div className="flex items-baseline gap-2">
                            <span className="text-xs font-semibold">{c.name}</span>
                            <span className="text-[10px] text-muted-foreground">
                              {[c.gender, c.age, c.occupation].filter(Boolean).join(" · ")}
                            </span>
                          </div>
                          <EditableTextBlock
                            text={c.personality || ""}
                            title={`人物设定 · ${c.name}`}
                            scope={{ type: "character", id: c.id, field: "personality" }}
                            onSaved={load}
                          />
                          <MediaStrip urls={c.images || []} kind="image" onZoom={setZoom} />
                          {c.voice_url && (
                            <div className="mt-1.5 flex items-center gap-1.5">
                              <Mic2 className="w-3 h-3 text-muted-foreground flex-shrink-0" />
                              <MediaStrip urls={[c.voice_url]} kind="audio" onZoom={setZoom} />
                            </div>
                          )}
                        </div>
                      ))}
                      {!tree.characters?.length && (
                        <div className={`${CARD} ${LEAF_TICK} text-[11px] text-muted-foreground`}>暂无人物</div>
                      )}
                    </div>
                  </div>

                  {/* 第三列：道具资产 */}
                  <div className={COLUMN}>
                    <div className={`${HEADER_CARD} from-amber-500/10 to-transparent border-l-4 border-l-amber-500`}>
                      <SectionTitle icon={<Package className="w-3.5 h-3.5 text-amber-500" />} text="道具资产"
                        extra={`${tree.props?.length || 0} 件`} />
                    </div>
                    <div className={BRANCH}>
                      {(tree.props || []).map((p) => (
                        <div key={p.id} className={`${CARD} ${LEAF_TICK}`}>
                          <div className="flex items-baseline gap-2">
                            <span className="text-xs font-semibold">{p.name}</span>
                            {p.type && <span className="text-[10px] text-muted-foreground">{p.type}</span>}
                          </div>
                          {p.url && <MediaStrip urls={[p.url]} kind="image" onZoom={setZoom} />}
                          <EditableTextBlock
                            text={p.description || ""}
                            title={`道具描述 · ${p.name}`}
                            scope={{ type: "prop", id: p.id, field: "description" }}
                            onSaved={load}
                          />
                        </div>
                      ))}
                      {!tree.props?.length && (
                        <div className={`${CARD} ${LEAF_TICK} text-[11px] text-muted-foreground`}>暂无道具</div>
                      )}
                    </div>
                  </div>

                  {/* 第四列：场景资产 */}
                  <div className={COLUMN}>
                    <div className={`${HEADER_CARD} from-emerald-500/10 to-transparent border-l-4 border-l-emerald-500`}>
                      <SectionTitle icon={<ImageIcon className="w-3.5 h-3.5 text-emerald-500" />} text="场景资产"
                        extra={`${tree.scenes?.length || 0} 张`} />
                    </div>
                    <div className={BRANCH}>
                      {(tree.scenes || []).map((s, i) => (
                        <div key={i} className={`${CARD} ${LEAF_TICK}`}>
                          <MediaStrip urls={[s.url]} kind="image" onZoom={setZoom} />
                          {(s.name || s.location || s.time) && (
                            <div className="text-[10px] text-muted-foreground mt-1">
                              {[s.name, s.location, s.time].filter(Boolean).join(" · ")}
                            </div>
                          )}
                          {s.description && s.id && (
                            <EditableTextBlock
                              text={s.description}
                              title={`场景描述 · ${s.name || `场景${i + 1}`}`}
                              scope={{ type: "scene", id: s.id, field: "description" }}
                              onSaved={load}
                            />
                          )}
                        </div>
                      ))}
                      {!tree.scenes?.length && (
                        <div className={`${CARD} ${LEAF_TICK} text-[11px] text-muted-foreground`}>暂无场景</div>
                      )}
                    </div>
                  </div>

                  {/* 第五列：章节 · 分镜 */}
                  <div className={COLUMN}>
                    <div className={`${HEADER_CARD} from-violet-500/10 to-transparent border-l-4 border-l-violet-500`}>
                      <SectionTitle icon={<Clapperboard className="w-3.5 h-3.5 text-violet-500" />} text="章节 · 分镜"
                        extra={`${tree.chapters?.length || 0} 章`} />
                    </div>
                    <div className={BRANCH}>
                      {(tree.chapters || []).map((ch) => (
                        <div key={ch.id} className={LEAF_TICK}>
                          <div className={`${CARD}`}>
                            <div className="flex items-center gap-1">
                              <div className="text-xs font-semibold flex-1 truncate" title={ch.title}>{ch.title}</div>
                              <button type="button"
                                onClick={(e) => { e.stopPropagation(); setEditing(ch); }}
                                className="p-1 rounded-md hover:bg-muted text-muted-foreground" title="人工审改（编辑剧本/摘要）">
                                <Pencil className="w-3 h-3" />
                              </button>
                            </div>
                            {ch.summary && (
                              <EditableTextBlock
                                text={ch.summary}
                                title={`章节摘要 · ${ch.title}`}
                                scope={{ type: "chapter", id: ch.id, field: "summary" }}
                                onSaved={load}
                              />
                            )}
                            {ch.original_text && (
                              <div className="mt-1">
                                <SectionTitle text="格式化剧本" />
                                <EditableTextBlock
                                  text={ch.original_text}
                                  title={`格式化剧本 · ${ch.title}`}
                                  scope={{ type: "chapter", id: ch.id, field: "original_text" }}
                                  onSaved={load}
                                />
                              </div>
                            )}
                          </div>
                          <div className={BRANCH + " mt-2"}>
                            {(ch.shots || []).map((s) => (
                              <div key={s.id} className={`${CARD} ${LEAF_TICK}`}>
                                <div className="flex items-center gap-1.5">
                                  <Scissors className="w-3 h-3 text-muted-foreground" />
                                  <span className="text-[11px] font-medium">{s.label}</span>
                                </div>
                                {(s.scene_descriptions || []).length > 0 && (
                                  <EditableTextBlock
                                    text={(s.scene_descriptions || []).join("\n")}
                                    title={`分镜场景 · ${s.label}`}
                                    scope={{ type: "shot", chapterId: ch.id, id: s.id, field: "scene_descriptions" }}
                                    onSaved={load}
                                  />
                                )}
                                {!!s.dialogues?.length && (
                                  <EditableTextBlock
                                    text={formatDialogues(s.dialogues)}
                                    title={`分镜对话 · ${s.label}`}
                                    scope={{ type: "shot", chapterId: ch.id, id: s.id, field: "dialogues" }}
                                    onSaved={load}
                                  />
                                )}
                                {s.bgm_design && (
                                  <div className="mt-1">
                                    <SectionTitle text="BGM 设计" />
                                    <EditableTextBlock
                                      text={s.bgm_design}
                                      title={`BGM 设计 · ${s.label}`}
                                      scope={{ type: "shot", chapterId: ch.id, id: s.id, field: "bgm_design" }}
                                      onSaved={load}
                                    />
                                  </div>
                                )}
                                {s.sfx_design && (
                                  <div className="mt-1">
                                    <SectionTitle text="SFX 设计" />
                                    <EditableTextBlock
                                      text={s.sfx_design}
                                      title={`SFX 设计 · ${s.label}`}
                                      scope={{ type: "shot", chapterId: ch.id, id: s.id, field: "sfx_design" }}
                                      onSaved={load}
                                    />
                                  </div>
                                )}
                                <div className="flex flex-wrap gap-x-3 gap-y-1.5 mt-2">
                                  {s.frames?.length ? (
                                    <div>
                                      <SectionTitle icon={<ImageIcon className="w-3 h-3" />} text="帧" extra={`${s.frames.length}`} />
                                      <MediaStrip urls={s.frames} kind="image" onZoom={setZoom} />
                                    </div>
                                  ) : null}
                                  {s.videos?.length ? (
                                    <div>
                                      <SectionTitle icon={<Film className="w-3 h-3" />} text="视频" />
                                      <MediaStrip urls={s.videos} kind="video" onZoom={setZoom} />
                                    </div>
                                  ) : null}
                                  {s.audios?.length ? (
                                    <div>
                                      <SectionTitle icon={<AudioLines className="w-3 h-3" />} text="配音" />
                                      <MediaStrip urls={s.audios} kind="audio" onZoom={setZoom} />
                                    </div>
                                  ) : null}
                                  {s.renders?.length ? (
                                    <div>
                                      <SectionTitle icon={<Film className="w-3 h-3 text-primary" />} text="成片" />
                                      <MediaStrip urls={s.renders} kind="video" onZoom={setZoom} />
                                    </div>
                                  ) : null}
                                </div>
                              </div>
                            ))}
                            {!ch.shots?.length && (
                              <div className={`${CARD} ${LEAF_TICK} text-[11px] text-muted-foreground`}>本章暂无分镜</div>
                            )}
                          </div>
                        </div>
                      ))}
                      {!tree.chapters?.length && (
                        <div className={`${CARD} ${LEAF_TICK} text-[11px] text-muted-foreground`}>暂无章节</div>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* 章节人工审改 */}
      {editing && (
        <ChapterEditor
          chapter={editing}
          onCancel={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }}
        />
      )}

      {/* 图片放大预览 */}
      {zoom && (
        <div className="fixed inset-0 z-[10000] bg-black/80 flex items-center justify-center"
          onClick={(e) => { e.stopPropagation(); setZoom(""); }}>
          <img src={zoom} alt="" className="max-h-[85vh] max-w-[90vw] object-contain rounded-lg" />
        </div>
      )}
    </div>,
    document.body
  );
}

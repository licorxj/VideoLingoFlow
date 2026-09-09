import { createPortal } from "react-dom";
import { useEffect, useState } from "react";
import client from "@/api/client";
import {
  X, RefreshCw, Network, BookOpen, Users, Clapperboard, Scissors,
  Image as ImageIcon, Film, Mic2, AudioLines, Loader2, AlertTriangle,
  LayoutGrid, ArrowLeft,
} from "lucide-react";

/** 文本固定框：限定高度内部滚动，避免长文撑爆版面 */
const FIXED_TEXT = "max-h-24 overflow-y-auto whitespace-pre-wrap break-words text-[11px] leading-relaxed bg-muted/40 border border-border/40 rounded-md px-2 py-1.5 text-foreground/90";

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
type Tree = {
  id: string; name?: string; description?: string; status?: string;
  genre_tags?: string[]; art_style_tags?: string[]; audience_tags?: string[];
  script_text?: string; characters?: CharacterItem[];
  scenes?: { url: string; description?: string }[];
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

function TextBlock({ text }: { text: string }) {
  if (!text) return null;
  return <div className={FIXED_TEXT}>{text}</div>;
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
            className="h-20 w-auto max-w-[160px] object-cover rounded-md border border-border/40 cursor-zoom-in hover:opacity-90"
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
            className="w-48 rounded-md border border-border/40 bg-black" />
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

function SectionTitle({ icon, text, extra }: { icon?: React.ReactNode; text: string; extra?: string }) {
  return (
    <div className="flex items-center gap-1.5 mb-1.5">
      {icon}
      <span className="text-[11px] font-semibold text-foreground/90">{text}</span>
      {extra && <span className="text-[10px] text-muted-foreground">{extra}</span>}
    </div>
  );
}

/** 思维导图子项的连接线（列容器竖线 + 项前横线） */
const BRANCH = "ml-3 pl-3 border-l border-border/50 space-y-2.5";
const LEAF_TICK = "relative before:absolute before:-left-3 before:top-4 before:w-3 before:h-px before:bg-border/50";
const CARD = "rounded-lg border border-border/50 bg-background/80 p-2.5 shadow-sm";

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
              {p.description ? <TextBlock text={p.description} /> : null}
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
  /** 视图：map=思维导图（单项目） / grid=项目列表首页（多宫格） */
  const [view, setView] = useState<"map" | "grid">("map");
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
    else loadProjects();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, view, effId]);

  if (!open) return null;

  const scriptParts = splitScript(tree?.script_text || "");

  return createPortal(
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
      onPointerDown={(e) => e.stopPropagation()}>
      <div
        className="w-[92vw] h-[88vh] rounded-xl border border-border/60 bg-background shadow-2xl flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 顶栏 */}
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border/50 bg-muted/30 flex-shrink-0">
          {view === "grid" ? (
            <button type="button"
              onClick={(e) => { e.stopPropagation(); setView("map"); }}
              className="p-1.5 rounded-md hover:bg-muted text-muted-foreground" title="返回导图">
              <ArrowLeft className="w-4 h-4" />
            </button>
          ) : (
            <Network className="w-4 h-4 text-primary" />
          )}
          <span className="text-sm font-semibold">{view === "grid" ? "项目列表" : "项目浏览"}</span>
          <span className="text-xs text-muted-foreground truncate">
            {view === "grid"
              ? `共 ${projects.length} 个创作项目`
              : (tree?.name || effId)}
          </span>
          <div className="ml-auto flex items-center gap-1.5">
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
        <div className="flex-1 overflow-auto p-5">
          {view === "grid" ? (
            <ProjectGrid
              projects={projects}
              loading={projectsLoading}
              error={projectsError}
              onOpen={(id) => { setBrowseId(id); setView("map"); }}
              onReload={loadProjects}
            />
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
                  {/* 根节点 */}
                  <div className={`${CARD} w-52 flex-shrink-0 sticky left-0 top-0`}>
                    <div className="text-sm font-bold truncate">{tree.name}</div>
                    <div className="text-[10px] text-muted-foreground mt-0.5">
                      状态：{tree.status || "draft"}
                    </div>
                    <div className="flex gap-1 flex-wrap mt-1.5">
                      {(tree.genre_tags || []).map((t) => (
                        <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary">{t}</span>
                      ))}
                      {(tree.art_style_tags || []).map((t) => (
                        <span key={t} className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">{t}</span>
                      ))}
                    </div>
                    {tree.description && <div className={FIXED_TEXT + " mt-2"}>{tree.description}</div>}
                  </div>

                  {/* 分支一：故事骨架 */}
                  <div className="flex-shrink-0">
                    <div className={`${CARD} w-56`}>
                      <SectionTitle icon={<BookOpen className="w-3.5 h-3.5 text-sky-500" />} text="故事骨架" />
                    </div>
                    <div className={BRANCH}>
                      {scriptParts.length ? scriptParts.map((p, i) => (
                        <div key={i} className={`${CARD} w-64 ${LEAF_TICK}`}>
                          <SectionTitle text={p.head || "剧本"} />
                          <TextBlock text={p.body} />
                        </div>
                      )) : (
                        <div className={`${CARD} w-64 ${LEAF_TICK}`}>
                          <TextBlock text={tree.script_text || "（暂无）"} />
                        </div>
                      )}
                    </div>
                  </div>

                  {/* 分支二：人物资产 */}
                  <div className="flex-shrink-0">
                    <div className={`${CARD} w-56`}>
                      <SectionTitle icon={<Users className="w-3.5 h-3.5 text-pink-500" />} text="人物资产"
                        extra={`${tree.characters?.length || 0} 人`} />
                    </div>
                    <div className={BRANCH}>
                      {(tree.characters || []).map((c) => (
                        <div key={c.id} className={`${CARD} w-72 ${LEAF_TICK}`}>
                          <div className="flex items-baseline gap-2">
                            <span className="text-xs font-semibold">{c.name}</span>
                            <span className="text-[10px] text-muted-foreground">
                              {[c.gender, c.age, c.occupation].filter(Boolean).join(" · ")}
                            </span>
                          </div>
                          <TextBlock text={c.personality || ""} />
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
                        <div className={`${CARD} w-72 ${LEAF_TICK} text-[11px] text-muted-foreground`}>暂无人物</div>
                      )}
                    </div>
                  </div>

                  {/* 分支三：场景 + 章节/分镜 */}
                  <div className="flex-shrink-0">
                    <div className={`${CARD} w-56`}>
                      <SectionTitle icon={<ImageIcon className="w-3.5 h-3.5 text-emerald-500" />} text="场景资产"
                        extra={`${tree.scenes?.length || 0} 张`} />
                    </div>
                    <div className={BRANCH}>
                      {(tree.scenes || []).map((s, i) => (
                        <div key={i} className={`${CARD} w-72 ${LEAF_TICK}`}>
                          <MediaStrip urls={[s.url]} kind="image" onZoom={setZoom} />
                          {s.description && <TextBlock text={s.description} />}
                        </div>
                      ))}
                    </div>

                    <div className={`${CARD} w-56 mt-3`}>
                      <SectionTitle icon={<Clapperboard className="w-3.5 h-3.5 text-amber-500" />} text="章节 · 分镜"
                        extra={`${tree.chapters?.length || 0} 章`} />
                    </div>
                    <div className={BRANCH}>
                      {(tree.chapters || []).map((ch) => (
                        <div key={ch.id} className={LEAF_TICK}>
                          <div className={`${CARD} w-64`}>
                            <div className="text-xs font-semibold">{ch.title}</div>
                            <TextBlock text={ch.summary || ch.original_text || ""} />
                          </div>
                          <div className={BRANCH + " mt-2"}>
                            {(ch.shots || []).map((s) => (
                              <div key={s.id} className={`${CARD} w-80 ${LEAF_TICK}`}>
                                <div className="flex items-center gap-1.5">
                                  <Scissors className="w-3 h-3 text-muted-foreground" />
                                  <span className="text-[11px] font-medium">{s.label}</span>
                                </div>
                                {(s.scene_descriptions || []).map((d, i) => (
                                  <TextBlock key={i} text={d} />
                                ))}
                                {!!s.dialogues?.length && (
                                  <TextBlock text={s.dialogues
                                    .map((d) => `${d.character || "?"}：${d.content || ""}`)
                                    .join("\n")} />
                                )}
                                <div className="flex flex-wrap gap-x-3 gap-y-1.5 mt-1.5">
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
                              <div className={`${CARD} w-80 ${LEAF_TICK} text-[11px] text-muted-foreground`}>本章暂无分镜</div>
                            )}
                          </div>
                        </div>
                      ))}
                      {!tree.chapters?.length && (
                        <div className={`${CARD} w-72 ${LEAF_TICK} text-[11px] text-muted-foreground`}>暂无章节</div>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>

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

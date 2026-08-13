import { useState, useEffect, useRef, useCallback } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { promptApi, type PromptTemplate } from "@/api/llm";
import { Save, AlertTriangle, CheckCircle2, Tag } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAlert } from "@/components/ui/AlertProvider";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export default function PromptEditor({ open, onOpenChange }: Props) {
  const { alert: showAlert, confirm: showConfirm } = useAlert();
  const [templates, setTemplates] = useState<PromptTemplate[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [systemPrompt, setSystemPrompt] = useState("");
  const [userPrompt, setUserPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ type: "ok" | "error"; text: string } | null>(null);

  const systemRef = useRef<HTMLTextAreaElement>(null);
  const userRef = useRef<HTMLTextAreaElement>(null);

  // Load templates when dialog opens
  useEffect(() => {
    if (!open) return;
    setLoading(true);
    promptApi.listTemplates().then((res) => {
      setTemplates(res.data.templates || []);
      if (res.data.templates?.length && !selectedId) {
        setSelectedId(res.data.templates[0].id);
      }
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [open]);

  // Load selected template content
  useEffect(() => {
    if (!selectedId) return;
    const tpl = templates.find((t) => t.id === selectedId);
    if (tpl) {
      setSystemPrompt(tpl.system_prompt || "");
      setUserPrompt(tpl.user_prompt || "");
      setSaveMsg(null);
    }
  }, [selectedId, templates]);

  const selectedTemplate = templates.find((t) => t.id === selectedId);

  // Insert placeholder tag at cursor position
  const insertPlaceholder = useCallback(
    (tag: string, target: "system" | "user") => {
      const ref = target === "system" ? systemRef : userRef;
      const setter = target === "system" ? setSystemPrompt : setUserPrompt;
      const textarea = ref.current;
      if (!textarea) return;

      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      const current = target === "system" ? systemPrompt : userPrompt;
      const before = current.substring(0, start);
      const after = current.substring(end);
      const insertTag = `{{ ${tag} }}`;
      setter(before + insertTag + after);

      requestAnimationFrame(() => {
        textarea.focus();
        const pos = start + insertTag.length;
        textarea.setSelectionRange(pos, pos);
      });
    },
    [systemPrompt, userPrompt]
  );

  // Save with validation popup
  const handleSave = async () => {
    if (!selectedId || saving) return;
    setSaving(true);
    setSaveMsg(null);

    try {
      // 1. Validate placeholders
      const valRes = await promptApi.validatePlaceholders(selectedId, {
        system_prompt: systemPrompt,
        user_prompt: userPrompt,
      });
      const { invalid, unused, valid } = valRes.data;

      // 2. If not valid, show confirm popup
      if (!valid) {
        const parts: string[] = [];
        if (invalid.length > 0) {
          parts.push(
            `无效占位符（未在模板中定义）：\n${invalid.map((i) => `  ${i.tag} → 出现在 ${i.location}`).join("\n")}`
          );
        }
        if (unused.length > 0) {
          parts.push(
            `未使用的占位符（已定义但未在 prompt 中使用）：\n${unused.map((t) => `  ${t}`).join("\n")}`
          );
        }
        const message = parts.join("\n\n") + "\n\n是否仍要保存？";
        const confirmed = await showConfirm(message, {
          type: "warning",
          title: "占位符校验提醒",
          confirmLabel: "仍然保存",
          cancelLabel: "取消编辑",
        });
        if (!confirmed) {
          setSaving(false);
          return;
        }
      }

      // 3. Save to backend
      await promptApi.updateTemplate(selectedId, {
        system_prompt: systemPrompt,
        user_prompt: userPrompt,
      });

      // 4. Update local state
      setTemplates((prev) =>
        prev.map((t) =>
          t.id === selectedId
            ? { ...t, system_prompt: systemPrompt, user_prompt: userPrompt }
            : t
        )
      );

      setSaveMsg({ type: "ok", text: "保存成功" });
      setTimeout(() => setSaveMsg(null), 3000);
    } catch {
      setSaveMsg({ type: "error", text: "保存失败" });
    } finally {
      setSaving(false);
    }
  };

  // Placeholder tag chips
  const PlaceholderChips = ({
    placeholders,
    target,
  }: {
    placeholders: PromptTemplate["placeholders"];
    target: "system" | "user";
  }) => (
    <div className="flex flex-wrap gap-1.5 mb-2">
      {placeholders.map((p) => (
        <button
          key={p.tag}
          type="button"
          onClick={() => insertPlaceholder(p.tag, target)}
          title={`${p.label} [${p.type || "string"}]：${p.description}`}
          className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-mono rounded-md
                     bg-primary/10 text-primary border border-primary/20
                     hover:bg-primary/20 hover:border-primary/40 transition-colors cursor-pointer group"
        >
          <Tag className="w-3 h-3" />
          <span>{p.tag}</span>
          {p.type && (
            <span className="text-[10px] opacity-50 group-hover:opacity-100 ml-1">
              ({p.type})
            </span>
          )}
        </button>
      ))}
    </div>
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl w-[90vw] h-[85vh] max-h-[85vh] flex flex-col p-0 gap-0">
        <DialogHeader className="px-6 pt-5 pb-3 border-b border-border/50">
          <DialogTitle className="text-base font-semibold flex items-center gap-2">
            <Tag className="w-4 h-4 text-primary" />
            Prompt 工程 - 自定义 Prompt 模板编辑
          </DialogTitle>
        </DialogHeader>

        <div className="flex flex-1 min-h-0">
          {/* Left: template list */}
          <div className="w-64 flex-shrink-0 border-r border-border/50 overflow-y-auto bg-muted/20">
            <div className="p-3">
              <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                Prompt 模板列表
              </h4>
              {loading ? (
                <p className="text-xs text-muted-foreground py-4 text-center">加载中...</p>
              ) : (
                <div className="space-y-1">
                  {templates.map((tpl) => (
                    <button
                      key={tpl.id}
                      onClick={() => setSelectedId(tpl.id)}
                      className={cn(
                        "w-full text-left px-3 py-2.5 rounded-lg transition-all duration-150",
                        selectedId === tpl.id
                          ? "bg-primary/10 border border-primary/30 text-foreground"
                          : "hover:bg-muted/50 border border-transparent text-muted-foreground hover:text-foreground"
                      )}
                    >
                      <div className="text-sm font-medium truncate">{tpl.name}</div>
                      <div className="text-[11px] text-muted-foreground font-mono truncate mt-0.5">
                        {tpl.id}
                      </div>
                      <div className="text-[11px] text-muted-foreground truncate mt-0.5">
                        {tpl.description}
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Right: editor */}
          <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
            {selectedTemplate ? (
              <>
                {/* Header */}
                <div className="px-6 py-3 border-b border-border/30 bg-muted/10">
                  <h3 className="text-sm font-semibold">{selectedTemplate.name}</h3>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {selectedTemplate.description}
                  </p>
                </div>

                {/* Editors */}
                <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
                  {/* System Prompt */}
                  <div>
                    <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider block mb-1.5">
                      System Prompt
                    </label>
                    <PlaceholderChips
                      placeholders={selectedTemplate.placeholders}
                      target="system"
                    />
                    <textarea
                      ref={systemRef}
                      className="w-full min-h-[100px] max-h-[200px] rounded-lg border border-border/60 bg-background/50 px-3.5 py-2.5 text-sm font-mono
                                 focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all outline-none resize-y"
                      value={systemPrompt}
                      onChange={(e) => setSystemPrompt(e.target.value)}
                      placeholder="输入 system prompt（可选）..."
                    />
                  </div>

                  {/* User Prompt */}
                  <div>
                    <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider block mb-1.5">
                      User Prompt
                    </label>
                    <PlaceholderChips
                      placeholders={selectedTemplate.placeholders}
                      target="user"
                    />
                    <textarea
                      ref={userRef}
                      className="w-full min-h-[200px] max-h-[400px] rounded-lg border border-border/60 bg-background/50 px-3.5 py-2.5 text-sm font-mono
                                 focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all outline-none resize-y"
                      value={userPrompt}
                      onChange={(e) => setUserPrompt(e.target.value)}
                      placeholder="输入 user prompt..."
                    />
                  </div>
                </div>

                {/* Jinja2 Help (Collapsible) */}
                <div className="px-6 py-2 border-t border-border/30 bg-muted/5">
                  <details className="group">
                    <summary className="text-[11px] text-muted-foreground cursor-pointer hover:text-primary transition-colors flex items-center gap-1 list-none">
                      <span className="group-open:rotate-90 transition-transform">▶</span>
                      Jinja2 动态组装语法说明 (支持逻辑判断与循环)
                    </summary>
                    <div className="mt-2 grid grid-cols-2 gap-4 p-3 bg-background/50 rounded-lg border border-border/40 text-[11px] font-mono leading-relaxed">
                      <div>
                        <p className="text-primary font-semibold mb-1">变量与判断：</p>
                        <code className="block bg-muted/50 p-1 mb-1">{"{{ var_name }}"}</code>
                        <code className="block bg-muted/50 p-1 mb-1">{"{% if enable_tone %}"} ... {"{% endif %}"}</code>
                        <code className="block bg-muted/50 p-1">{"{% if is_chinese and enable_normalize %}"}</code>
                      </div>
                      <div>
                        <p className="text-primary font-semibold mb-1">循环示例：</p>
                        <code className="block bg-muted/50 p-1">
                          {"{% for seg in raw_segments %}"}<br />
                          - [{"{{ seg.index }}"}] {"{{ seg.text }}"}<br />
                          {"{% endfor %}"}
                        </code>
                      </div>
                    </div>
                  </details>
                </div>

                {/* Footer */}
                <div className="px-6 py-3 border-t border-border/50 flex items-center gap-3">
                  <button
                    onClick={handleSave}
                    disabled={saving}
                    className={cn(
                      "flex items-center gap-2 px-5 py-2 text-sm font-medium rounded-lg transition-all duration-200",
                      saving
                        ? "bg-muted text-muted-foreground cursor-wait"
                        : "bg-primary text-primary-foreground hover:bg-primary/90 shadow-sm"
                    )}
                  >
                    <Save className="w-4 h-4" />
                    {saving ? "保存中..." : "保存"}
                  </button>

                  {saveMsg && (
                    <div
                      className={cn(
                        "flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg",
                        saveMsg.type === "ok" && "bg-green-500/10 text-green-600 border border-green-500/20",
                        saveMsg.type === "error" && "bg-red-500/10 text-red-600 border border-red-500/20"
                      )}
                    >
                      {saveMsg.type === "ok" && <CheckCircle2 className="w-3.5 h-3.5" />}
                      {saveMsg.type === "error" && <AlertTriangle className="w-3.5 h-3.5" />}
                      {saveMsg.text}
                    </div>
                  )}

                  <div className="flex-1" />
                  <span className="text-[11px] text-muted-foreground">
                    点击占位符标签可插入到编辑框光标位置
                  </span>
                </div>
              </>
            ) : (
              <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
                {loading ? "加载中..." : "请从左侧选择一个 Prompt 模板"}
              </div>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

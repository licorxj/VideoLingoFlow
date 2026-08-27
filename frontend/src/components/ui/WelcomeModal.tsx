import { useState, useEffect } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { Rocket, BookOpen, X, Sparkles } from "lucide-react";

const STORAGE_KEY = "vl_welcome_dismissed";

export default function WelcomeModal() {
  const [open, setOpen] = useState(false);
  const [dontShow, setDontShow] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    const dismissed = localStorage.getItem(STORAGE_KEY);
    if (!dismissed) {
      setOpen(true);
    }
  }, []);

  const handleClose = () => {
    if (dontShow) {
      localStorage.setItem(STORAGE_KEY, "true");
    }
    setOpen(false);
  };

  const handleGuide = () => {
    localStorage.setItem(STORAGE_KEY, "true");
    setOpen(false);
    navigate("/guide");
  };

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 backdrop-blur-sm animate-fade-in">
      <div className="relative w-[min(520px,90vw)] bg-background border border-border/60 rounded-2xl shadow-2xl animate-scale-in overflow-hidden">
        {/* Header gradient */}
        <div className="relative h-32 bg-gradient-to-br from-primary/20 via-primary/10 to-background flex items-center justify-center">
          <div className="text-center space-y-2">
            <div className="flex items-center justify-center gap-2">
              <Sparkles className="w-6 h-6 text-primary" />
              <h2 className="text-2xl font-bold text-foreground">欢迎使用 VideoLingoFlow</h2>
            </div>
            <p className="text-sm text-muted-foreground">AI 驱动的视频处理工作流平台</p>
          </div>
          <button
            onClick={handleClose}
            className="absolute top-3 right-3 p-1.5 rounded-lg hover:bg-white/10 text-muted-foreground hover:text-foreground transition-all"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 space-y-5">
          <div className="space-y-3">
            <p className="text-sm text-foreground/80 leading-relaxed">
              VideoLingoFlow 是一个自由扩展的 AI 工作流框架，支持视频翻译、配音、字幕生成等多种任务。
              通过智能节点和 Skill/MCP 扩展，你可以实现几乎任何视频处理需求。
            </p>
            <div className="grid grid-cols-2 gap-3">
              <div className="p-3 rounded-xl bg-primary/5 border border-primary/10">
                <p className="text-xs font-medium text-primary mb-1">工作流编排</p>
                <p className="text-[11px] text-muted-foreground">拖拽式节点编排，灵活组合处理流程</p>
              </div>
              <div className="p-3 rounded-xl bg-primary/5 border border-primary/10">
                <p className="text-xs font-medium text-primary mb-1">批量处理</p>
                <p className="text-[11px] text-muted-foreground">一次验证，批量执行，规模化产出</p>
              </div>
              <div className="p-3 rounded-xl bg-primary/5 border border-primary/10">
                <p className="text-xs font-medium text-primary mb-1">多模型支持</p>
                <p className="text-[11px] text-muted-foreground">统一配置 ASR/TTS/LLM 等 AI 能力</p>
              </div>
              <div className="p-3 rounded-xl bg-primary/5 border border-primary/10">
                <p className="text-xs font-medium text-primary mb-1">社区共享</p>
                <p className="text-[11px] text-muted-foreground">导入导出节点与工作流，共享创意</p>
              </div>
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center justify-between pt-2">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={dontShow}
                onChange={(e) => setDontShow(e.target.checked)}
                className="w-4 h-4 rounded border-border/60 text-primary focus:ring-primary/20"
              />
              <span className="text-xs text-muted-foreground">下次不再显示</span>
            </label>
            <div className="flex items-center gap-2">
              <button
                onClick={handleClose}
                className="px-4 py-2 text-xs font-medium border border-border/60 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent/60 transition-all"
              >
                跳过
              </button>
              <button
                onClick={handleGuide}
                className="flex items-center gap-1.5 px-4 py-2 text-xs font-semibold bg-primary text-primary-foreground rounded-lg transition-all hover:shadow-lg hover:shadow-primary/25"
              >
                <BookOpen className="w-3.5 h-3.5" />
                使用向导
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}

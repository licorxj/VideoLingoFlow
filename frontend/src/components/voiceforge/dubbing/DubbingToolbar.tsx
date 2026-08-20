import {
  CheckSquare,
  Trash2,
  Bot,
  Eraser,
  Scissors,
  Users,
  Zap,
  Volume2,
  PlayCircle,
  Download,
  FolderArchive,
  Settings,
  RefreshCw,
} from "lucide-react";
import { Button } from "@/components/ui/button";

interface DubbingToolbarProps {
  selectedCount: number;
  totalCount: number;
  engine: string;
  engines: string[];
  voiceControlMode: "clone" | "instruct";
  defaultGap: number;
  onSelectAll: () => void;
  onDelete: () => void;
  onAIDialogue: () => void;
  onTextClean: () => void;
  onSentenceSplit: () => void;
  onBatchRole: () => void;
  onBatchGenerate: () => void;
  onCompleteGenerate: () => void;
  onPreviewSection: () => void;
  onExportChapter: () => void;
  onBrowseExports: () => void;
  onEngineChange: (engine: string) => void;
  onVoiceControlModeChange: (mode: "clone" | "instruct") => void;
  onGapChange: (gap: number) => void;
  onEngineSettings: () => void;
  busy: string;
}

export function DubbingToolbar({
  selectedCount,
  totalCount,
  engine,
  engines,
  voiceControlMode,
  defaultGap,
  onSelectAll,
  onDelete,
  onAIDialogue,
  onTextClean,
  onSentenceSplit,
  onBatchRole,
  onBatchGenerate,
  onCompleteGenerate,
  onPreviewSection,
  onExportChapter,
  onBrowseExports,
  onEngineChange,
  onVoiceControlModeChange,
  onGapChange,
  onEngineSettings,
  busy,
}: DubbingToolbarProps) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border/60 bg-card p-3">
      {/* 第一行 */}
      <div className="flex flex-wrap items-center gap-2">
        {/* 全选复选框 */}
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={selectedCount > 0 && selectedCount === totalCount}
            onChange={onSelectAll}
            className="h-4 w-4 rounded border-input"
          />
          <span className="text-muted-foreground">
            ({selectedCount}/{totalCount})
          </span>
        </label>

        {/* 删除选中按钮 */}
        {selectedCount > 0 && (
          <Button
            variant="destructive"
            size="sm"
            onClick={onDelete}
            className="gap-1.5"
          >
            <Trash2 className="h-4 w-4" />
            删除选中
          </Button>
        )}

        {/* 间隔符 */}
        <div className="flex-1" />

        {/* AI提取对话按钮 */}
        <Button
          variant="ai-soft"
          size="sm"
          onClick={onAIDialogue}
          className="gap-1.5"
        >
          <Bot className="h-4 w-4" />
          AI提取对话
        </Button>

        {/* 文本清洗按钮 */}
        <Button variant="outline" size="sm" onClick={onTextClean} className="gap-1.5">
          <Eraser className="h-4 w-4" />
          文本清洗
        </Button>

        {/* 句子拆分按钮 */}
        <Button variant="outline" size="sm" onClick={onSentenceSplit} className="gap-1.5">
          <Scissors className="h-4 w-4" />
          句子拆分
        </Button>

        {/* 声音控制模式选择 */}
        <select
          className="h-8 rounded-md border border-input bg-background px-2 text-sm"
          value={voiceControlMode}
          onChange={(e) =>
            onVoiceControlModeChange(e.target.value as "clone" | "instruct")
          }
        >
          <option value="clone">克隆模式</option>
          <option value="instruct">指令模式</option>
        </select>

        {/* 引擎选择 */}
        <select
          className="h-8 rounded-md border border-input bg-background px-2 text-sm"
          value={engine}
          onChange={(e) => onEngineChange(e.target.value)}
        >
          {engines.map((eng) => (
            <option key={eng} value={eng}>
              {eng}
            </option>
          ))}
        </select>

        {/* 引擎设置按钮 */}
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8"
          onClick={onEngineSettings}
          title="引擎设置"
        >
          <Settings className="h-4 w-4" />
        </Button>
      </div>

      {/* 第二行 */}
      <div className="flex flex-wrap items-center gap-2">
        {/* 批量修改角色按钮 */}
        <Button variant="outline" size="sm" onClick={onBatchRole} className="gap-1.5">
          <Users className="h-4 w-4" />
          批量修改角色
        </Button>

        {/* 批量生成按钮 */}
        <Button
          variant="default"
          size="sm"
          onClick={onBatchGenerate}
          disabled={busy === "batch"}
          className="gap-1.5"
        >
          <Zap className="h-4 w-4" />
          批量生成
        </Button>

        {/* 补全生成按钮 */}
        <Button
          variant="info-soft"
          size="sm"
          onClick={onCompleteGenerate}
          className="gap-1.5"
        >
          <RefreshCw className="h-4 w-4" />
          补全生成
        </Button>

        {/* 句间间隔滑块 */}
        <div className="flex items-center gap-2">
          <Volume2 className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm text-muted-foreground">句间间隔</span>
          <input
            type="range"
            min="0"
            max="3"
            step="0.1"
            value={defaultGap}
            onChange={(e) => onGapChange(parseFloat(e.target.value))}
            className="h-2 w-24 cursor-pointer accent-primary"
          />
          <span className="w-10 text-sm text-muted-foreground">
            {defaultGap.toFixed(1)}s
          </span>
        </div>

        {/* 预览小节按钮 */}
        <Button
          variant="success-soft"
          size="sm"
          onClick={onPreviewSection}
          className="gap-1.5"
        >
          <PlayCircle className="h-4 w-4" />
          预览小节
        </Button>

        {/* 导出章节按钮 */}
        <Button
          variant="warning-soft"
          size="sm"
          onClick={onExportChapter}
          className="gap-1.5"
        >
          <Download className="h-4 w-4" />
          导出章节
        </Button>

        {/* 浏览产物按钮 */}
        <Button
          variant="ai-soft"
          size="sm"
          onClick={onBrowseExports}
          className="gap-1.5"
        >
          <FolderArchive className="h-4 w-4" />
          浏览产物
        </Button>
      </div>
    </div>
  );
}
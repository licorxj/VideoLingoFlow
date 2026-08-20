import { useState } from "react";
import {
  BookOpen,
  Plus,
  Pencil,
  Trash2,
  FileText,
  FileEdit,
  Bot,
  SplitSquareVertical,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { VoiceForgeSentence } from "@/api/voiceforge";
import { Chapter } from "./DubbingContext";

interface ChapterPanelProps {
  projectName: string;
  chapters: Chapter[];
  selectedChapterId: string | null;
  onSelectChapter: (id: string | null) => void;
  onImportText: () => void;
  onEditOriginal: () => void;
  onRuleSplitChapters: () => void;
  onAISplitChapters: () => void;
  onCreateChapter: (title: string, parentId?: string | null) => void;
  onDeleteChapter: (id: string) => void;
  onUpdateChapterText: (id: string, text: string) => Promise<void>;
  sentences: VoiceForgeSentence[];
}

export function ChapterPanel({
  projectName,
  chapters,
  selectedChapterId,
  onSelectChapter,
  onImportText,
  onEditOriginal,
  onRuleSplitChapters,
  onAISplitChapters,
  onCreateChapter,
  onDeleteChapter,
  onUpdateChapterText,
  sentences,
}: ChapterPanelProps) {
  const [addChapterOpen, setAddChapterOpen] = useState(false);
  const [addParentId, setAddParentId] = useState<string | null>(null);
  const [editChapterOpen, setEditChapterOpen] = useState(false);
  const [editingChapter, setEditingChapter] = useState<Chapter | null>(null);
  const [editingText, setEditingText] = useState("");

  const handleAddChapter = (parentId: string | null = null) => {
    setAddParentId(parentId);
    setAddChapterOpen(true);
  };

  const handleEditChapter = (chapter: Chapter) => {
    setEditingChapter(chapter);
    setEditingText(chapter.title);
    setEditChapterOpen(true);
  };

  const handleSaveChapterTitle = async () => {
    if (editingChapter && editingText.trim()) {
      await onUpdateChapterText(editingChapter.id, editingText.trim());
      setEditChapterOpen(false);
      setEditingChapter(null);
      setEditingText("");
    }
  };

  const handleConfirmDelete = (chapter: Chapter) => {
    if (confirm(`确认删除章节"${chapter.title}"？`)) {
      onDeleteChapter(chapter.id);
    }
  };

  const renderChapterNode = (chapter: Chapter, level: number = 0) => {
    const sentenceCount = chapter.sentence_count ?? 0;
    const truncatedTitle =
      chapter.title.length > 12
        ? chapter.title.substring(0, 12) + "..."
        : chapter.title;

    return (
      <div key={chapter.id} style={{ paddingLeft: `${level * 16}px` }}>
        <div
          className={`group flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-accent/60 ${
            selectedChapterId === chapter.id
              ? "bg-accent text-accent-foreground"
              : ""
          }`}
          onClick={() => onSelectChapter(chapter.id)}
        >
          <BookOpen className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1 truncate">{truncatedTitle}</span>
          {sentenceCount > 0 && (
            <span className="rounded-full bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
              {sentenceCount}
            </span>
          )}
          <div className="flex shrink-0 gap-1 opacity-0 transition-opacity group-hover:opacity-100">
            <Button
              size="icon"
              variant="ghost"
              className="h-6 w-6"
              onClick={(e) => {
                e.stopPropagation();
                handleEditChapter(chapter);
              }}
              title="编辑文本"
            >
              <Pencil className="h-3.5 w-3.5" />
            </Button>
            <Button
              size="icon"
              variant="ghost"
              className="h-6 w-6"
              onClick={(e) => {
                e.stopPropagation();
                handleAddChapter(chapter.id);
              }}
              title="添加子章节"
            >
              <Plus className="h-3.5 w-3.5" />
            </Button>
            <Button
              size="icon"
              variant="ghost"
              className="h-6 w-6 text-destructive"
              onClick={(e) => {
                e.stopPropagation();
                handleConfirmDelete(chapter);
              }}
              title="删除"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
        {chapter.children?.map((child: Chapter) =>
          renderChapterNode(child, level + 1)
        )}
      </div>
    );
  };

  return (
    <div className="flex h-full flex-col">
      {/* 项目名称标题 */}
      <div className="border-b border-border/60 px-3 py-4 text-center">
        <h2 className="text-lg font-bold">{projectName}</h2>
      </div>

      {/* 操作按钮行 */}
      <div className="space-y-2 border-b border-border/60 px-3 py-3">
        <div className="flex gap-2">
          <Button
            variant="default"
            className="flex-1"
            onClick={onImportText}
          >
            <FileText className="mr-1.5 h-4 w-4" />
            导入文本
          </Button>
          <Button
            variant="ai-soft"
            className="flex-1"
            onClick={onEditOriginal}
          >
            <FileEdit className="mr-1.5 h-4 w-4" />
            编辑原文
          </Button>
        </div>
        <div className="flex gap-2">
          <Button
            variant="success-soft"
            className="flex-1"
            onClick={onRuleSplitChapters}
          >
            <SplitSquareVertical className="mr-1.5 h-4 w-4" />
            规则拆分章
          </Button>
          <Button
            variant="ai-soft"
            className="flex-1"
            onClick={onAISplitChapters}
          >
            <Bot className="mr-1.5 h-4 w-4" />
            AI分章节
          </Button>
        </div>
      </div>

      {/* 章节树 */}
      <div className="flex-1 overflow-y-auto px-3 py-2">
        {/* 全部句子按钮 */}
        <Button
          variant={!selectedChapterId ? "secondary" : "ghost"}
          className="mb-2 w-full justify-between"
          onClick={() => onSelectChapter(null)}
        >
          <span>全部句子</span>
          <span className="text-xs text-muted-foreground">
            {sentences.length}
          </span>
        </Button>

        {/* 章节列表 */}
        <div className="space-y-1">
          {chapters.map((chapter) => renderChapterNode(chapter))}
        </div>

        {/* 添加章节按钮 */}
        <Button
          variant="ghost"
          className="mt-3 w-full justify-center text-muted-foreground"
          onClick={() => handleAddChapter()}
        >
          <Plus className="mr-1.5 h-4 w-4" />
          添加章节
        </Button>
      </div>

      {/* 添加章节对话框 */}
      <Dialog open={addChapterOpen} onOpenChange={setAddChapterOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {addParentId ? "添加子章节" : "添加章节"}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <Input
              placeholder="章节标题"
              value={editingText}
              onChange={(e) => setEditingText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && editingText.trim()) {
                  onCreateChapter(editingText.trim(), addParentId);
                  setAddChapterOpen(false);
                  setEditingText("");
                }
              }}
            />
            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => {
                  setAddChapterOpen(false);
                  setEditingText("");
                }}
              >
                取消
              </Button>
              <Button
                onClick={() => {
                  if (editingText.trim()) {
                    onCreateChapter(editingText.trim(), addParentId);
                    setAddChapterOpen(false);
                    setEditingText("");
                  }
                }}
                disabled={!editingText.trim()}
              >
                确认
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* 编辑章节对话框 */}
      <Dialog open={editChapterOpen} onOpenChange={setEditChapterOpen}>
        <DialogContent className="max-w-[720px]">
          <DialogHeader>
            <DialogTitle>编辑章节文本</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="relative">
              <textarea
                className="min-h-[300px] w-full resize-y rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                value={editingText}
                onChange={(e) => setEditingText(e.target.value)}
              />
              <div className="absolute bottom-2 right-2 text-xs text-muted-foreground">
                {editingText.length} 字符
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => {
                  setEditChapterOpen(false);
                  setEditingChapter(null);
                  setEditingText("");
                }}
              >
                取消
              </Button>
              <Button onClick={handleSaveChapterTitle} disabled={!editingText.trim()}>
                保存
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
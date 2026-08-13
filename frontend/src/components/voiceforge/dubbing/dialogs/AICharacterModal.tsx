import { useState } from "react";
import { Bot, Loader2, UserCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { VoiceForgeSentence } from "@/api/voiceforge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface AICharacterModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sentences: VoiceForgeSentence[];
  onExtract: (
    characters: Array<{
      name: string;
      gender?: string;
      personality?: string;
    }>,
  ) => void;
  busy: boolean;
}

interface ExtractedCharacter {
  name: string;
  gender?: string;
  personality?: string;
  selected: boolean;
}

export function AICharacterModal({
  open,
  onOpenChange,
  sentences,
  onExtract,
  busy,
}: AICharacterModalProps) {
  const [results, setResults] = useState<ExtractedCharacter[]>([]);
  const [extracting, setExtracting] = useState(false);

  const projectText = sentences.map((s) => s.text).join("\n");

  const handleExtract = async () => {
    setExtracting(true);
    try {
      // Mock AI extraction — in production, call API
      await new Promise((r) => setTimeout(r, 1500));
      const names = new Set<string>();
      const found: ExtractedCharacter[] = [];
      for (const s of sentences) {
        if (s.character_name && !names.has(s.character_name)) {
          names.add(s.character_name);
          found.push({
            name: s.character_name,
            gender: undefined,
            personality: undefined,
            selected: true,
          });
        }
      }
      if (found.length === 0) {
        found.push({
          name: "旁白",
          gender: undefined,
          personality: "叙述者",
          selected: true,
        });
      }
      setResults(found);
    } finally {
      setExtracting(false);
    }
  };

  const toggleSelect = (index: number) =>
    setResults((prev) =>
      prev.map((r, i) => (i === index ? { ...r, selected: !r.selected } : r)),
    );

  const handleCreate = () => {
    const selected = results.filter((r) => r.selected);
    if (selected.length) {
      onExtract(
        selected.map(({ name, gender, personality }) => ({
          name,
          gender,
          personality,
        })),
      );
    }
  };

  const handleOpenChange = (value: boolean) => {
    if (!value) setResults([]);
    onOpenChange(value);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Bot className="h-5 w-5 text-purple-400" />
            AI 提取角色
          </DialogTitle>
          <DialogDescription>
            从项目文本中自动识别并提取角色信息。
          </DialogDescription>
        </DialogHeader>

        {/* Source text */}
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            项目文本
          </label>
          <textarea
            value={projectText}
            readOnly
            className="voice-input min-h-32 resize-none font-mono text-xs leading-relaxed opacity-80"
          />
        </div>

        {/* Extract button */}
        <Button
          onClick={handleExtract}
          disabled={extracting || busy || !sentences.length}
          className="w-full gap-2 border-purple-500/30 bg-purple-500/20 text-purple-400 hover:bg-purple-500/30"
          variant="outline"
        >
          {extracting || busy ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Bot className="h-4 w-4" />
          )}
          {extracting || busy ? "提取中…" : "AI 提取角色"}
        </Button>

        {/* Results */}
        {results.length > 0 && (
          <div className="space-y-2">
            <h4 className="text-sm font-medium">
              提取结果 <span className="text-muted-foreground">({results.length})</span>
            </h4>
            <div className="max-h-60 space-y-1.5 overflow-y-auto pr-1">
              {results.map((r, idx) => (
                <label
                  key={idx}
                  className={`flex items-start gap-3 rounded-lg border p-3 transition ${
                    r.selected
                      ? "border-primary/60 bg-primary/5"
                      : "border-border/60"
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={r.selected}
                    onChange={() => toggleSelect(idx)}
                    className="mt-0.5 h-4 w-4 shrink-0 rounded border-input"
                  />
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">{r.name}</span>
                      {r.gender && (
                        <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs text-primary">
                          {r.gender}
                        </span>
                      )}
                    </div>
                    {r.personality && (
                      <p className="mt-1 text-xs text-muted-foreground">
                        {r.personality}
                      </p>
                    )}
                  </div>
                </label>
              ))}
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)}>
            取消
          </Button>
          {results.length > 0 && (
            <Button
              onClick={handleCreate}
              disabled={!results.some((r) => r.selected)}
            >
              <UserCheck className="mr-1.5 h-4 w-4" />
              创建选中角色 ({results.filter((r) => r.selected).length})
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

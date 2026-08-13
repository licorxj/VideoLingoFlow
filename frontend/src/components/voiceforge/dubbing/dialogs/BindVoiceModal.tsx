import { useState, useMemo } from "react";
import { Search, Volume2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface BindVoiceModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  voices: Array<{ id: string; display_name: string; voice_group?: string }>;
  onBind: (voiceId: string) => void;
}

export function BindVoiceModal({
  open,
  onOpenChange,
  voices,
  onBind,
}: BindVoiceModalProps) {
  const [search, setSearch] = useState("");

  const grouped = useMemo(() => {
    const filtered = voices.filter(
      (v) =>
        v.display_name.toLowerCase().includes(search.toLowerCase()) ||
        (v.voice_group ?? "").toLowerCase().includes(search.toLowerCase()),
    );
    const map = new Map<string, typeof voices>();
    for (const v of filtered) {
      const group = v.voice_group || "未分组";
      if (!map.has(group)) map.set(group, []);
      map.get(group)!.push(v);
    }
    return map;
  }, [voices, search]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Volume2 className="h-5 w-5 text-muted-foreground" />
            绑定音色
          </DialogTitle>
          <DialogDescription>
            搜索并选择一个音色绑定到当前角色。
          </DialogDescription>
        </DialogHeader>

        {/* Search */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索音色名称或分组…"
            className="voice-input pl-9"
            autoFocus
          />
        </div>

        {/* Voice list */}
        <div className="max-h-80 space-y-4 overflow-y-auto pr-1">
          {grouped.size === 0 && (
            <p className="py-8 text-center text-sm text-muted-foreground">
              没有匹配的音色
            </p>
          )}
          {[...grouped.entries()].map(([group, items]) => (
            <div key={group}>
              <h4 className="mb-1.5 text-xs font-medium text-muted-foreground">
                {group}
              </h4>
              <div className="space-y-1">
                {items.map((voice) => (
                  <button
                    key={voice.id}
                    type="button"
                    onClick={() => {
                      onBind(voice.id);
                      onOpenChange(false);
                    }}
                    className="flex w-full items-center gap-2 rounded-lg border border-border/60 px-3 py-2 text-left text-sm transition hover:border-primary/40 hover:bg-accent"
                  >
                    <Volume2 className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <span className="flex-1 truncate">{voice.display_name}</span>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

import { useEffect, useState } from "react";
import { UserPlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

/* ── Types ─────────────────────────────────────────────────────────── */

interface AddCharacterModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAdd: (name: string, data?: { character_type?: string; note?: string }) => void;
}

/* ── Component ──────────────────────────────────────────────────────── */

const CHARACTER_TYPES = [
  { value: "narrator", label: "旁白" },
  { value: "protagonist", label: "主角" },
  { value: "supporting", label: "配角" },
  { value: "other", label: "其他" },
];

export function AddCharacterModal({
  open,
  onOpenChange,
  onAdd,
}: AddCharacterModalProps) {
  const [name, setName] = useState("");
  const [characterType, setCharacterType] = useState("");
  const [note, setNote] = useState("");

  // Reset form when dialog opens
  useEffect(() => {
    if (open) {
      setName("");
      setCharacterType("");
      setNote("");
    }
  }, [open]);

  const handleSubmit = () => {
    const trimmed = name.trim();
    if (!trimmed) return;

    const data: { character_type?: string; note?: string } = {};
    if (characterType) data.character_type = characterType;
    if (note.trim()) data.note = note.trim();

    onAdd(trimmed, Object.keys(data).length > 0 ? data : undefined);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <UserPlus className="h-4 w-4" />
            添加角色
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {/* Character name */}
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              角色名称 <span className="text-destructive">*</span>
            </label>
            <Input
              autoFocus
              placeholder="输入角色名称"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && name.trim()) handleSubmit();
              }}
            />
          </div>

          {/* Character type */}
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              角色类型
            </label>
            <Select value={characterType} onValueChange={setCharacterType}>
              <SelectTrigger>
                <SelectValue placeholder="选择角色类型" />
              </SelectTrigger>
              <SelectContent>
                {CHARACTER_TYPES.map((t) => (
                  <SelectItem key={t.value} value={t.value}>
                    {t.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Note */}
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              备注
            </label>
            <Textarea
              placeholder="角色备注信息（可选）"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              className="min-h-[80px] resize-none"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={handleSubmit} disabled={!name.trim()}>
            <UserPlus className="mr-1.5 h-4 w-4" />
            添加
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

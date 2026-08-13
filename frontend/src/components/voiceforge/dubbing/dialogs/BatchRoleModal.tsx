import { useState } from "react";
import { Users, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

/* ── Types ─────────────────────────────────────────────────────────── */

interface BatchRoleModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  characters: Array<{ id: string; name: string }>;
  selectedCount: number;
  onApply: (characterId: string) => void;
}

/* ── Component ─────────────────────────────────────────────────────── */

export function BatchRoleModal({
  open,
  onOpenChange,
  characters,
  selectedCount,
  onApply,
}: BatchRoleModalProps) {
  const [selectedCharacterId, setSelectedCharacterId] = useState<string>("");

  const handleApply = () => {
    if (selectedCharacterId) {
      onApply(selectedCharacterId);
      setSelectedCharacterId("");
    }
  };

  const handleOpenChange = (value: boolean) => {
    if (!value) {
      setSelectedCharacterId("");
    }
    onOpenChange(value);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Users className="h-5 w-5 text-primary" />
            批量分配角色
          </DialogTitle>
          <DialogDescription>
            将选中的 {selectedCount} 个句子分配给同一个角色
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              选择角色
            </label>
            <Select value={selectedCharacterId} onValueChange={setSelectedCharacterId}>
              <SelectTrigger>
                <SelectValue placeholder="请选择一个角色" />
              </SelectTrigger>
              <SelectContent>
                {characters.map((character) => (
                  <SelectItem key={character.id} value={character.id}>
                    {character.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="rounded-lg bg-muted/30 p-3 text-xs text-muted-foreground">
            <p>
              已选中 <span className="font-medium text-foreground">{selectedCount}</span> 个句子
            </p>
            {selectedCharacterId && (
              <p className="mt-1">
                将分配给: <span className="font-medium text-primary">
                  {characters.find((c) => c.id === selectedCharacterId)?.name}
                </span>
              </p>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)}>
            取消
          </Button>
          <Button
            onClick={handleApply}
            disabled={!selectedCharacterId}
          >
            <Check className="mr-1.5 h-4 w-4" />
            应用
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

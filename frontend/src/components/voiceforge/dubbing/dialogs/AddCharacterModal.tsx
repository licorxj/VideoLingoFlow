import { useState, useEffect } from "react";
import { UserPlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface AddCharacterModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAdd: (data: {
    name: string;
    gender?: string;
    age_range?: string;
    personality?: string;
    voice_design_desc?: string;
  }) => void;
  busy: boolean;
}

const GENDERS = ["男", "女", "未知"];
const AGE_RANGES = ["儿童", "少年", "青年", "中年", "老年"];

export function AddCharacterModal({
  open,
  onOpenChange,
  onAdd,
  busy,
}: AddCharacterModalProps) {
  const [name, setName] = useState("");
  const [gender, setGender] = useState("");
  const [ageRange, setAgeRange] = useState("");
  const [personality, setPersonality] = useState("");
  const [voiceDesignDesc, setVoiceDesignDesc] = useState("");

  useEffect(() => {
    if (open) {
      setName("");
      setGender("");
      setAgeRange("");
      setPersonality("");
      setVoiceDesignDesc("");
    }
  }, [open]);

  const handleAdd = () => {
    if (!name.trim()) return;
    onAdd({
      name: name.trim(),
      gender: gender || undefined,
      age_range: ageRange || undefined,
      personality: personality.trim() || undefined,
      voice_design_desc: voiceDesignDesc.trim() || undefined,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <UserPlus className="h-5 w-5 text-muted-foreground" />
            添加角色
          </DialogTitle>
          <DialogDescription>
            填写角色基本信息，用于配音分配和声音设计。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* 角色名称 */}
          <label className="grid gap-1.5 text-sm">
            <span className="font-medium">
              角色名称 <span className="text-destructive">*</span>
            </span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例如：林小雨"
              className="voice-input"
              autoFocus
            />
          </label>

          {/* 性别 */}
          <label className="grid gap-1.5 text-sm">
            <span className="font-medium">性别</span>
            <select
              value={gender}
              onChange={(e) => setGender(e.target.value)}
              className="voice-input"
            >
              <option value="">未指定</option>
              {GENDERS.map((g) => (
                <option key={g} value={g}>{g}</option>
              ))}
            </select>
          </label>

          {/* 年龄段 */}
          <label className="grid gap-1.5 text-sm">
            <span className="font-medium">年龄段</span>
            <select
              value={ageRange}
              onChange={(e) => setAgeRange(e.target.value)}
              className="voice-input"
            >
              <option value="">未指定</option>
              {AGE_RANGES.map((a) => (
                <option key={a} value={a}>{a}</option>
              ))}
            </select>
          </label>

          {/* 性格描述 */}
          <label className="grid gap-1.5 text-sm">
            <span className="font-medium">性格描述</span>
            <textarea
              value={personality}
              onChange={(e) => setPersonality(e.target.value)}
              placeholder="温柔、活泼、沉稳…"
              className="voice-input min-h-16 resize-none"
            />
          </label>

          {/* 声音设计描述 */}
          <label className="grid gap-1.5 text-sm">
            <span className="font-medium">声音设计描述</span>
            <textarea
              value={voiceDesignDesc}
              onChange={(e) => setVoiceDesignDesc(e.target.value)}
              placeholder="用于 AI 生成音色时的风格参考"
              className="voice-input min-h-16 resize-none"
            />
          </label>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            取消
          </Button>
          <Button onClick={handleAdd} disabled={busy || !name.trim()}>
            {busy ? "添加中…" : "添加角色"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

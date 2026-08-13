import { useState } from "react";
import {
  Users,
  Plus,
  Pencil,
  Trash2,
  Bot,
  X,
  Check,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
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

interface Character {
  id: string;
  name: string;
  character_type?: string;
  voice_profile_id?: string | null;
  note?: string;
}

interface Voice {
  id: string;
  display_name: string;
  voice_group?: string;
}

interface CharacterPanelProps {
  characters: Character[];
  voices: Voice[];
  onCreateCharacter: (name: string) => void;
  onDeleteCharacter: (id: string) => void;
  onUpdateCharacter: (id: string, data: Record<string, unknown>) => void;
  onClearAll: () => void;
  onAIExtract: () => void;
}

/* ── Gender / Type helpers ─────────────────────────────────────────── */

const GENDER_MAP: Record<string, string> = {
  male: "男",
  female: "女",
  narrator: "旁白",
  protagonist: "主角",
  supporting: "配角",
  other: "其他",
};

function extractGender(type?: string): string | null {
  if (!type) return null;
  if (type === "male" || type === "female") return type;
  return null;
}

function typeLabel(type?: string): string | null {
  if (!type) return null;
  return GENDER_MAP[type] || type;
}

/* ── CharacterPanel Component ──────────────────────────────────────── */

export function CharacterPanel({
  characters,
  onCreateCharacter,
  onDeleteCharacter,
  onUpdateCharacter,
  onClearAll,
  onAIExtract,
}: CharacterPanelProps) {
  const [addName, setAddName] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState({
    name: "",
    gender: "",
    age: "",
    personality: "",
    voiceDesign: "",
  });

  /* ── Inline add ────────────────────────────────────────────────── */

  const handleAdd = () => {
    const name = addName.trim();
    if (!name) return;
    onCreateCharacter(name);
    setAddName("");
  };

  /* ── Inline edit ───────────────────────────────────────────────── */

  const startEdit = (char: Character) => {
    setEditingId(char.id);
    const gender = extractGender(char.character_type);
    setEditForm({
      name: char.name,
      gender: gender || "",
      age: "",
      personality: "",
      voiceDesign: "",
    });
  };

  const cancelEdit = () => {
    setEditingId(null);
  };

  const saveEdit = (id: string) => {
    const patch: Record<string, unknown> = {};
    if (editForm.name.trim()) patch.name = editForm.name.trim();
    if (editForm.gender) patch.character_type = editForm.gender;
    onUpdateCharacter(id, patch);
    setEditingId(null);
  };

  /* ── Render ────────────────────────────────────────────────────── */

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-border/60 px-3 py-3">
        <Users className="h-4 w-4 text-muted-foreground" />
        <span className="text-sm font-semibold">项目角色</span>
        <span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
          {characters.length}
        </span>
      </div>

      {/* Action buttons */}
      <div className="flex gap-2 border-b border-border/60 px-3 py-2.5">
        <Button
          variant="outline"
          size="sm"
          className="flex-1 border-purple-500/30 text-purple-400 hover:bg-purple-500/20"
          onClick={onAIExtract}
        >
          <Sparkles className="mr-1 h-3.5 w-3.5" />
          AI提取
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="flex-1"
          onClick={() => {
            setEditingId("__new__");
            setEditForm({
              name: "",
              gender: "",
              age: "",
              personality: "",
              voiceDesign: "",
            });
          }}
        >
          <Plus className="mr-1 h-3.5 w-3.5" />
          添加
        </Button>
        {characters.length > 0 && (
          <Button
            variant="outline"
            size="sm"
            className="border-red-500/30 text-red-400 hover:bg-red-500/20"
            onClick={() => {
              if (confirm("确认清空所有角色？")) {
                onClearAll();
              }
            }}
          >
            <Trash2 className="mr-1 h-3.5 w-3.5" />
            清空
          </Button>
        )}
      </div>

      {/* Character list */}
      <div className="flex-1 overflow-y-auto px-3 py-2">
        {/* Inline new character form */}
        {editingId === "__new__" && (
          <div className="mb-2 rounded-lg border border-border/60 bg-accent/30 p-3 space-y-2">
            <Input
              autoFocus
              placeholder="角色名称"
              value={editForm.name}
              onChange={(e) =>
                setEditForm((f) => ({ ...f, name: e.target.value }))
              }
              onKeyDown={(e) => {
                if (e.key === "Enter" && editForm.name.trim()) {
                  onCreateCharacter(editForm.name.trim());
                  setEditingId(null);
                }
                if (e.key === "Escape") setEditingId(null);
              }}
              className="h-8 text-sm"
            />
            <div className="flex justify-end gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setEditingId(null)}
              >
                <X className="mr-1 h-3.5 w-3.5" />
                取消
              </Button>
              <Button
                size="sm"
                disabled={!editForm.name.trim()}
                onClick={() => {
                  if (editForm.name.trim()) {
                    onCreateCharacter(editForm.name.trim());
                    setEditingId(null);
                  }
                }}
              >
                <Check className="mr-1 h-3.5 w-3.5" />
                确认
              </Button>
            </div>
          </div>
        )}

        {/* Inline quick add row */}
        {editingId !== "__new__" && (
          <div className="mb-2 flex gap-2">
            <Input
              placeholder="输入角色名称，回车添加"
              value={addName}
              onChange={(e) => setAddName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleAdd();
              }}
              className="h-8 flex-1 text-sm"
            />
            <Button
              size="icon"
              variant="outline"
              className="h-8 w-8 shrink-0"
              onClick={handleAdd}
              disabled={!addName.trim()}
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>
        )}

        {/* Character items */}
        {characters.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
            <Users className="mb-2 h-8 w-8 opacity-40" />
            <span className="text-sm">暂无角色</span>
          </div>
        ) : (
          <div className="space-y-1">
            {characters.map((char) => {
              const isEditing = editingId === char.id;
              const gender = extractGender(char.character_type);
              const bound = !!char.voice_profile_id;

              if (isEditing) {
                return (
                  <div
                    key={char.id}
                    className="rounded-lg border border-border/60 bg-accent/30 p-3 space-y-2"
                  >
                    {/* Name */}
                    <div>
                      <label className="mb-1 block text-[10px] font-medium text-muted-foreground">
                        名称
                      </label>
                      <Input
                        value={editForm.name}
                        onChange={(e) =>
                          setEditForm((f) => ({ ...f, name: e.target.value }))
                        }
                        className="h-8 text-sm"
                      />
                    </div>

                    {/* Gender */}
                    <div>
                      <label className="mb-1 block text-[10px] font-medium text-muted-foreground">
                        性别
                      </label>
                      <Select
                        value={editForm.gender}
                        onValueChange={(v) =>
                          setEditForm((f) => ({ ...f, gender: v }))
                        }
                      >
                        <SelectTrigger className="h-8 text-sm">
                          <SelectValue placeholder="选择性别" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="male">男</SelectItem>
                          <SelectItem value="female">女</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    {/* Age */}
                    <div>
                      <label className="mb-1 block text-[10px] font-medium text-muted-foreground">
                        年龄段
                      </label>
                      <Select
                        value={editForm.age}
                        onValueChange={(v) =>
                          setEditForm((f) => ({ ...f, age: v }))
                        }
                      >
                        <SelectTrigger className="h-8 text-sm">
                          <SelectValue placeholder="选择年龄段" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="child">儿童</SelectItem>
                          <SelectItem value="teen">少年</SelectItem>
                          <SelectItem value="young">青年</SelectItem>
                          <SelectItem value="middle">中年</SelectItem>
                          <SelectItem value="elder">老年</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    {/* Personality */}
                    <div>
                      <label className="mb-1 block text-[10px] font-medium text-muted-foreground">
                        性格描述
                      </label>
                      <Textarea
                        value={editForm.personality}
                        onChange={(e) =>
                          setEditForm((f) => ({
                            ...f,
                            personality: e.target.value,
                          }))
                        }
                        placeholder="描述角色的性格特征..."
                        className="min-h-[60px] resize-none text-sm"
                      />
                    </div>

                    {/* Voice design */}
                    <div>
                      <label className="mb-1 block text-[10px] font-medium text-muted-foreground">
                        音色设计描述
                      </label>
                      <Textarea
                        value={editForm.voiceDesign}
                        onChange={(e) =>
                          setEditForm((f) => ({
                            ...f,
                            voiceDesign: e.target.value,
                          }))
                        }
                        placeholder="描述期望的音色特征..."
                        className="min-h-[60px] resize-none text-sm"
                      />
                    </div>

                    {/* Action buttons */}
                    <div className="flex justify-end gap-2 pt-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={cancelEdit}
                      >
                        取消
                      </Button>
                      <Button size="sm" onClick={() => saveEdit(char.id)}>
                        <Check className="mr-1 h-3.5 w-3.5" />
                        保存
                      </Button>
                    </div>
                  </div>
                );
              }

              return (
                <div
                  key={char.id}
                  className="group flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-accent/60"
                >
                  <span className="min-w-0 flex-1 truncate font-medium">
                    {char.name}
                  </span>

                  {/* Gender badge */}
                  {gender && (
                    <span
                      className={`shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium ${
                        gender === "male"
                          ? "bg-blue-500/15 text-blue-400"
                          : "bg-pink-500/15 text-pink-400"
                      }`}
                    >
                      {gender === "male" ? "男" : "女"}
                    </span>
                  )}

                  {/* Type badge (non-gender types) */}
                  {!gender && char.character_type && (
                    <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                      {typeLabel(char.character_type)}
                    </span>
                  )}

                  {/* Bound badge */}
                  {bound && (
                    <span className="shrink-0 rounded-full bg-green-500/15 px-1.5 py-0.5 text-[10px] font-medium text-green-400">
                      已绑定
                    </span>
                  )}

                  {/* Edit / Delete */}
                  <div className="flex shrink-0 gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-6 w-6"
                      onClick={() => startEdit(char)}
                      title="编辑"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      className="h-6 w-6 text-destructive"
                      onClick={() => {
                        if (confirm(`确认删除角色"${char.name}"？`)) {
                          onDeleteCharacter(char.id);
                        }
                      }}
                      title="删除"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

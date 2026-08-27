import { Pencil, Trash2, Link2, User } from "lucide-react";
import { Button } from "@/components/ui/button";

export interface CharacterCardData {
  id: string;
  name: string;
  character_type?: string;
  voice_profile_id?: string | null;
}

interface CharacterCardProps {
  character: CharacterCardData;
  boundVoiceName?: string;
  onEdit: (character: CharacterCardData) => void;
  onBindVoice: (character: CharacterCardData) => void;
  onDelete: (character: CharacterCardData) => void;
}

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

export function CharacterCard({
  character,
  boundVoiceName,
  onEdit,
  onBindVoice,
  onDelete,
}: CharacterCardProps) {
  const gender = extractGender(character.character_type);
  const bound = !!character.voice_profile_id;

  return (
    <div className="group flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-accent/60">
      <User className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <span className="min-w-0 flex-1 truncate font-medium">{character.name}</span>

      {gender && (
        <span
          className={`shrink-0 rounded-full border px-1.5 py-0.5 text-[10px] font-medium ${
            gender === "male" ? "gender-male" : "gender-female"
          }`}
        >
          {gender === "male" ? "男" : "女"}
        </span>
      )}

      {!gender && character.character_type && (
        <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
          {typeLabel(character.character_type)}
        </span>
      )}

      {bound && (
        <span
          className="shrink-0 max-w-[9rem] truncate rounded-full bg-success/15 px-1.5 py-0.5 text-[10px] font-medium text-success"
          title={boundVoiceName}
        >
          {boundVoiceName ?? "已绑定"}
        </span>
      )}

      <div className="flex shrink-0 gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
        <Button
          size="icon"
          variant="ghost"
          className="h-6 w-6"
          onClick={() => onBindVoice(character)}
          title="绑定音色"
        >
          <Link2 className="h-3.5 w-3.5" />
        </Button>
        <Button
          size="icon"
          variant="ghost"
          className="h-6 w-6"
          onClick={() => onEdit(character)}
          title="编辑"
        >
          <Pencil className="h-3.5 w-3.5" />
        </Button>
        <Button
          size="icon"
          variant="ghost"
          className="h-6 w-6 text-destructive"
          onClick={() => {
            if (confirm(`确认删除角色"${character.name}"？`)) {
              onDelete(character);
            }
          }}
          title="删除"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  );
}

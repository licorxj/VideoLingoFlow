export const ASSET_TYPE_ORDER = ["bgm", "sfx", "ambience"] as const;
export type AssetType = (typeof ASSET_TYPE_ORDER)[number];

export const ASSET_TYPE_LABELS: Record<string, string> = {
  bgm: "背景音乐",
  sfx: "音效",
  ambience: "环境音",
};

export const ASSET_TYPE_COLORS: Record<string, string> = {
  bgm: "#a29bfe",
  sfx: "#fdcb6e",
  ambience: "#55efc4",
};

export const AUDIO_FILETYPES: Array<[string, string]> = [["音频文件", "*.wav *.mp3 *.flac *.m4a *.ogg *.aac"]];

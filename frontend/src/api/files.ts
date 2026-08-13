import axios from "./client";

export interface FileItem {
  name: string;
  path: string;
  isDir: boolean;
  size?: number;
}

export async function browseDirectory(path: string = ""): Promise<{
  path: string;
  parent?: string;
  items: FileItem[];
}> {
  const res = await axios.post("/api/files/browse", { path });
  return res.data;
}

export async function listDrives(): Promise<{ drives: { name: string; path: string }[] }> {
  const res = await axios.get("/api/files/drive");
  return res.data;
}


export async function nativeFileDialog(
  type: "file" | "folder" = "file",
  title = "Select",
  filetypes: [string, string][] = [],
  multiple = false,
): Promise<string | string[]> {
  const res = await axios.post("/api/files/native-dialog", { type, title, filetypes, multiple });
  if (multiple) {
    return (res.data.paths || []) as string[];
  }
  return res.data.path || res.data.paths?.[0] || "";
}

export async function nativeSaveDialog(title = "Save As", defaultName = "", filetypes: [string, string][] = []): Promise<string> {
  const res = await axios.post("/api/files/native-save-dialog", { title, defaultName, filetypes });
  return res.data.path || "";
}

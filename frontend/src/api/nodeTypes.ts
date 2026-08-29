import axios from "./client";

export interface NodeTypeConfig {
  id: string;
  name: string;
  version?: string;
  category: string;
  description: string;
  icon: string;
  color: string;
  inputs: { id: string; label: string; type: string; required?: boolean }[];
  outputs: { id: string; label: string; type: string; required?: boolean }[];
  defaultConfig: Record<string, any>;
  configFields: any[];
  isBuiltIn?: boolean;
  execType?: string;
  execCode?: string;
  execFile?: string;
  execTimeout?: number;
  codeDir?: string;
  kind?: "normal" | "group";
  groupDefinition?: Record<string, any>;
}

export interface NodeSchemaOption {
  value: string;
  label: string;
  color?: string;
  icon?: string;
  supportedProperties?: string[];
  requiresOptions?: boolean;
}

export interface NodeTypesSchema {
  categories: NodeSchemaOption[];
  portTypes: NodeSchemaOption[];
  configFieldTypes: NodeSchemaOption[];
  execTypes: NodeSchemaOption[];
}

export interface NodePackageValidationResult {
  ok: boolean;
  valid: boolean;
  errors: string[];
  warnings: string[];
  packageFiles: string[];
  node?: {
    id: string;
    name: string;
    version?: string;
    category: string;
    execType?: string;
    execFile?: string;
    schemaVersion?: string;
  };
  localNode?: {
    id: string;
    name: string;
    version?: string;
    category?: string;
  } | null;
  versionComparison?: {
    status: "new" | "upgrade" | "downgrade" | "same" | "different" | "builtin";
    message: string;
    localVersion?: string;
    packageVersion?: string;
    requiresConfirmation?: boolean;
    recommendedBackup?: boolean;
  };
  shareMeta?: {
    shareName?: string;
    description?: string;
    nodeId?: string;
    version?: string;
    schemaVersion?: string;
    author?: string;
    sourceUrl?: string;
    tags?: string[];
    exportedAt?: string;
  };
}

export interface NodeTypeBackupEntry {
  id: string;
  nodeId: string;
  path: string;
  createdAt?: string;
  hasCode: boolean;
  node: {
    id: string;
    name: string;
    version?: string;
    category?: string;
  };
}

export async function listNodeTypes(): Promise<NodeTypeConfig[]> {
  const res = await axios.get("/api/node-types");
  return res.data.nodes || [];
}

export async function getNodeTypesSchema(): Promise<NodeTypesSchema> {
  const res = await axios.get("/api/node-types/schema");
  return res.data;
}

export async function createNodeType(config: NodeTypeConfig): Promise<NodeTypeConfig> {
  const res = await axios.post("/api/node-types", config);
  return res.data.node;
}

export async function updateNodeType(nodeId: string, config: NodeTypeConfig): Promise<NodeTypeConfig> {
  const res = await axios.put(`/api/node-types/${nodeId}`, config);
  return res.data.node;
}

export async function deleteNodeType(nodeId: string): Promise<void> {
  await axios.delete(`/api/node-types/${nodeId}`);
}

export async function exportNodeType(
  nodeId: string,
  shareName: string,
  shareDescription: string,
  author = "",
  sourceUrl = "",
  tags: string[] = []
): Promise<{ zipPath: string; fileName: string }> {
  const res = await axios.post("/api/node-types/export", {
    nodeId, shareName, shareDescription, author, sourceUrl, tags,
  });
  return res.data;
}

export async function importNodeType(
  file: File,
  options?: { allowOverwrite?: boolean; createBackup?: boolean; renameTo?: string }
): Promise<{
  node: NodeTypeConfig;
  extractedFiles?: string[];
  installResult?: string;
  packageWarnings?: string[];
  backupPath?: string;
  versionComparison?: NodePackageValidationResult["versionComparison"];
}> {
  const form = new FormData();
  form.append("file", file);
  form.append("allowOverwrite", String(!!options?.allowOverwrite));
  form.append("createBackup", String(!!options?.createBackup));
  if (options?.renameTo) form.append("renameTo", options.renameTo);
  const res = await axios.post("/api/node-types/import", form);
  return res.data;
}

export async function validateNodeTypePackage(file: File): Promise<NodePackageValidationResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await axios.post("/api/node-types/validate-package", form);
  return res.data;
}

export async function listNodeTypeBackups(nodeId: string): Promise<NodeTypeBackupEntry[]> {
  const res = await axios.get(`/api/node-types/${nodeId}/backups`);
  return res.data.backups || [];
}

export async function restoreNodeTypeBackup(
  nodeId: string,
  backupId: string,
  options?: { createBackup?: boolean }
): Promise<{
  node: NodeTypeConfig;
  restoredFrom: string;
  currentBackupPath?: string;
}> {
  const res = await axios.post(`/api/node-types/${nodeId}/backups/${backupId}/restore`, {
    createBackup: options?.createBackup ?? true,
  });
  return res.data;
}

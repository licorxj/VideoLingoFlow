import { useState, useEffect, useCallback } from "react";
import { backupApi, BackupOption, BackupInfo, RestoreMode } from "@/api/backup";
import {
  Database,
  FolderOpen,
  Download,
  Upload,
  CheckCircle2,
  AlertTriangle,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { cn } from "@/lib/utils";

type Status =
  | { kind: "idle" }
  | { kind: "success"; text: string }
  | { kind: "error"; text: string };

export default function DataBackupSettings() {
  const [options, setOptions] = useState<BackupOption[]>([]);
  const [backupDir, setBackupDir] = useState("");
  const [selected, setSelected] = useState<Record<string, boolean>>({});

  const [backups, setBackups] = useState<BackupInfo[]>([]);
  const [selectedBackup, setSelectedBackup] = useState<string>("");
  const [restoreSelected, setRestoreSelected] = useState<Record<string, boolean>>({});
  const [mode, setMode] = useState<RestoreMode>("overwrite");

  const [loading, setLoading] = useState(false);
  const [listLoading, setListLoading] = useState(false);
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  const refreshOptions = useCallback(async () => {
    try {
      const res = await backupApi.options();
      setOptions(res.data.options);
      setSelected(
        Object.fromEntries(res.data.options.map((o) => [o.id, true]))
      );
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    refreshOptions();
  }, [refreshOptions]);

  const selectedIds = Object.keys(selected).filter((k) => selected[k]);
  const restoreIds = Object.keys(restoreSelected).filter((k) => restoreSelected[k]);

  const setStatusMsg = (s: Status) => setStatus(s);

  const handleCreate = async () => {
    if (!backupDir.trim()) {
      setStatusMsg({ kind: "error", text: "请先设置备份存放目录（建议放在项目之外）" });
      return;
    }
    if (selectedIds.length === 0) {
      setStatusMsg({ kind: "error", text: "请至少选择一个备份项" });
      return;
    }
    setLoading(true);
    setStatusMsg({ kind: "idle" });
    try {
      const res = await backupApi.create(backupDir.trim(), selectedIds);
      setStatusMsg({
        kind: "success",
        text: `备份成功，共 ${res.data.itemCount} 个文件，已保存至：${res.data.backupPath}`,
      });
    } catch (e: any) {
      setStatusMsg({ kind: "error", text: e?.message || "备份失败" });
    } finally {
      setLoading(false);
    }
  };

  const handleList = async () => {
    if (!backupDir.trim()) {
      setStatusMsg({ kind: "error", text: "请先填写备份存放目录" });
      return;
    }
    setListLoading(true);
    try {
      const res = await backupApi.list(backupDir.trim());
      setBackups(res.data.backups);
      if (res.data.backups.length === 0) {
        setStatusMsg({ kind: "error", text: "该目录下没有找到有效的备份" });
      } else {
        setStatusMsg({ kind: "idle" });
      }
      setSelectedBackup("");
      setRestoreSelected({});
    } catch (e: any) {
      setStatusMsg({ kind: "error", text: e?.message || "列举备份失败" });
    } finally {
      setListLoading(false);
    }
  };

  // 选中某个备份后，默认勾选该备份包含的所有项
  const handlePickBackup = (path: string) => {
    setSelectedBackup(path);
    const info = backups.find((b) => b.path === path);
    if (info) {
      setRestoreSelected(Object.fromEntries(info.options.map((o) => [o, true])));
    }
  };

  const handleRestore = async () => {
    if (!selectedBackup) {
      setStatusMsg({ kind: "error", text: "请先选择要恢复的备份" });
      return;
    }
    if (restoreIds.length === 0) {
      setStatusMsg({ kind: "error", text: "请至少选择一个要恢复的项" });
      return;
    }
    setLoading(true);
    setStatusMsg({ kind: "idle" });
    try {
      const res = await backupApi.restore(selectedBackup, restoreIds, mode);
      const detail = res.data.restored
        .map((r) => `${r.label}: ${r.restored} 项`)
        .join("，");
      setStatusMsg({
        kind: "success",
        text: `恢复成功（${mode === "overwrite" ? "覆盖模式" : "增量模式"}）：${detail}`,
      });
      refreshOptions();
    } catch (e: any) {
      setStatusMsg({ kind: "error", text: e?.message || "恢复失败" });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-5 stagger-children">
      <StatusBanner status={status} />

      {/* 备份存放目录 */}
      <Section
        icon={FolderOpen}
        title="备份存放目录"
        desc="建议设置在项目目录之外（如 D:/videolingo_backups），防止项目更新时被覆盖。"
      >
        <div className="flex gap-2">
          <input
            type="text"
            value={backupDir}
            placeholder="例如：D:/videolingo_backups 或 /opt/videolingo_backups"
            onChange={(e) => setBackupDir(e.target.value)}
            className="w-full px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 outline-none"
          />
          <button
            onClick={handleList}
            disabled={listLoading}
            className="shrink-0 inline-flex items-center gap-1.5 px-3.5 py-2.5 rounded-xl border border-border/60 bg-card/60 text-sm font-medium hover:bg-accent transition-colors disabled:opacity-50"
          >
            {listLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
            列出备份
          </button>
        </div>
      </Section>

      {/* 备份 */}
      <Section
        icon={Download}
        title="执行备份"
        desc="勾选需要备份的内容，点击「执行备份」后会在上述目录生成带 manifest 的备份文件夹。"
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {options.map((o) => (
            <CheckCard
              key={o.id}
              checked={!!selected[o.id]}
              onChange={(v) => setSelected((s) => ({ ...s, [o.id]: v }))}
              title={o.label}
              desc={o.description}
              count={o.currentCount}
            />
          ))}
        </div>
        <div className="mt-4 flex items-center gap-3">
          <button
            onClick={handleCreate}
            disabled={loading}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Database className="w-4 h-4" />}
            执行备份
          </button>
        </div>
      </Section>

      {/* 恢复 */}
      <Section
        icon={Upload}
        title="恢复备份"
        desc="选择备份文件夹后，可挑选恢复项并选择恢复模式。"
      >
        <div className="space-y-4">
          {backups.length > 0 ? (
            <div>
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                选择备份
              </label>
              <select
                value={selectedBackup}
                onChange={(e) => handlePickBackup(e.target.value)}
                className="w-full mt-2 px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 outline-none"
              >
                <option value="">— 请选择 —</option>
                {backups.map((b) => (
                  <option key={b.path} value={b.path}>
                    {b.name} （{b.createdAt} · {b.itemCount} 项）
                  </option>
                ))}
              </select>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              暂无备份，请先在上方填写目录并点击「列出备份」。
            </p>
          )}

          {selectedBackup && (
            <>
              <div>
                <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  恢复模式
                </label>
                <div className="flex gap-2 mt-2">
                  <ModeChip
                    active={mode === "overwrite"}
                    onClick={() => setMode("overwrite")}
                    title="覆盖模式"
                    desc="用备份内容完全替换目标（集合类数据会先清除未在备份中的项）"
                  />
                  <ModeChip
                    active={mode === "incremental"}
                    onClick={() => setMode("incremental")}
                    title="增量恢复模式"
                    desc="仅追加 / 更新备份中的项，保留目标已有的其它数据"
                  />
                </div>
              </div>

              <div>
                <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  恢复项
                </label>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-2">
                  {options
                    .filter((o) => {
                      const info = backups.find((b) => b.path === selectedBackup);
                      return info?.options.includes(o.id);
                    })
                    .map((o) => (
                      <CheckCard
                        key={o.id}
                        checked={!!restoreSelected[o.id]}
                        onChange={(v) => setRestoreSelected((s) => ({ ...s, [o.id]: v }))}
                        title={o.label}
                        desc={o.description}
                        count={o.currentCount}
                      />
                    ))}
                </div>
              </div>

              <button
                onClick={handleRestore}
                disabled={loading}
                className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50"
              >
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
                执行恢复
              </button>
            </>
          )}
        </div>
      </Section>
    </div>
  );
}

function StatusBanner({ status }: { status: Status }) {
  if (status.kind === "idle") return null;
  const isOk = status.kind === "success";
  return (
    <div
      className={cn(
        "flex items-start gap-2 rounded-xl border p-3 text-sm",
        isOk
          ? "border-success/40 bg-success/10 text-foreground"
          : "border-destructive/40 bg-destructive/10 text-foreground"
      )}
    >
      {isOk ? (
        <CheckCircle2 className="w-4 h-4 mt-0.5 text-success shrink-0" />
      ) : (
        <AlertTriangle className="w-4 h-4 mt-0.5 text-destructive shrink-0" />
      )}
      <span className="break-all">{status.text}</span>
    </div>
  );
}

function Section({
  icon: Icon,
  title,
  desc,
  children,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  desc: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
      <div>
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Icon className="w-4 h-4 text-primary" />
          {title}
        </h3>
        <p className="mt-1 text-xs text-muted-foreground">{desc}</p>
      </div>
      {children}
    </div>
  );
}

function CheckCard({
  checked,
  onChange,
  title,
  desc,
  count,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  title: string;
  desc: string;
  count: number;
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className={cn(
        "flex items-start gap-3 rounded-xl border p-3 text-left transition-all",
        checked
          ? "border-primary/50 bg-primary/5"
          : "border-border/60 hover:bg-accent"
      )}
    >
      <div
        className={cn(
          "mt-0.5 w-4 h-4 shrink-0 rounded border flex items-center justify-center transition-colors",
          checked ? "bg-primary border-primary" : "border-border"
        )}
      >
        {checked && <CheckCircle2 className="w-3.5 h-3.5 text-primary-foreground" />}
      </div>
      <div className="min-w-0">
        <div className="text-sm font-medium flex items-center gap-2">
          {title}
          <span className="text-[11px] font-normal text-muted-foreground">
            （当前 {count} 项）
          </span>
        </div>
        <div className="text-xs text-muted-foreground mt-0.5">{desc}</div>
      </div>
    </button>
  );
}

function ModeChip({
  active,
  onClick,
  title,
  desc,
}: {
  active: boolean;
  onClick: () => void;
  title: string;
  desc: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex-1 rounded-xl border p-3 text-left transition-all",
        active ? "border-primary/50 bg-primary/5" : "border-border/60 hover:bg-accent"
      )}
    >
      <div className="text-sm font-medium">{title}</div>
      <div className="text-xs text-muted-foreground mt-0.5">{desc}</div>
    </button>
  );
}

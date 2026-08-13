import { useState, useEffect, useCallback } from "react";
import {
  Plus,
  Trash2,
  Download,
  X,
  Check,
  Search,
  Mic2,
  UserCheck,
} from "lucide-react";
import client from "@/api/client";

interface Voice {
  voice_id: string;
  voice_name: string;
  description: string;
  gender: string;
  age: string;
  language: string;
}

interface VoiceManagePanelProps {
  interfaceId: string;
  interfaceName: string;
  open: boolean;
  onClose: () => void;
}

const GENDER_OPTIONS = [
  { value: "male", label: "男" },
  { value: "female", label: "女" },
  { value: "neutral", label: "中性" },
];

const AGE_OPTIONS = [
  { value: "child", label: "儿童" },
  { value: "young", label: "青年" },
  { value: "adult", label: "成年" },
  { value: "senior", label: "老年" },
];

const GENDER_LABEL: Record<string, string> = {
  male: "男",
  female: "女",
  neutral: "中性",
};

const AGE_LABEL: Record<string, string> = {
  child: "儿童",
  young: "青年",
  adult: "成年",
  senior: "老年",
};

const EMPTY_FORM: Voice = {
  voice_id: "",
  voice_name: "",
  description: "",
  gender: "",
  age: "",
  language: "",
};

export default function VoiceManagePanel({
  interfaceId,
  interfaceName,
  open,
  onClose,
}: VoiceManagePanelProps) {
  const [voices, setVoices] = useState<Voice[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [showAddForm, setShowAddForm] = useState(false);
  const [addForm, setAddForm] = useState<Voice>({ ...EMPTY_FORM });
  const [saving, setSaving] = useState(false);
  const [showFetchDialog, setShowFetchDialog] = useState(false);
  const [fetchLoading, setFetchLoading] = useState(false);
  const [fetchedVoices, setFetchedVoices] = useState<Voice[]>([]);
  const [fetchSelected, setFetchSelected] = useState<Set<string>>(new Set());

  const loadVoices = useCallback(async () => {
    setLoading(true);
    try {
      const res = await client.get(`/api/tts-voices/${interfaceId}`);
      setVoices(res.data.voices || []);
    } catch {
      setVoices([]);
    } finally {
      setLoading(false);
    }
  }, [interfaceId]);

  useEffect(() => {
    if (open && interfaceId) loadVoices();
  }, [open, interfaceId, loadVoices]);

  useEffect(() => {
    if (!open) {
      setShowAddForm(false);
      setShowFetchDialog(false);
      setSearch("");
      setAddForm({ ...EMPTY_FORM });
    }
  }, [open]);

  const handleDelete = async (voiceId: string) => {
    if (!confirm("确定要删除该音色吗？")) return;
    try {
      await client.delete(`/api/tts-voices/${interfaceId}/${voiceId}`);
      loadVoices();
    } catch (e: any) {
      alert("删除失败: " + (e.response?.data?.detail || e.message));
    }
  };

  const handleAdd = async () => {
    if (!addForm.voice_id.trim()) {
      alert("voice_id 为必填项");
      return;
    }
    setSaving(true);
    try {
      await client.post(`/api/tts-voices/${interfaceId}`, addForm);
      setShowAddForm(false);
      setAddForm({ ...EMPTY_FORM });
      loadVoices();
    } catch (e: any) {
      alert("添加失败: " + (e.response?.data?.detail || e.message));
    } finally {
      setSaving(false);
    }
  };

  const handleFetch = async () => {
    setFetchLoading(true);
    setFetchSelected(new Set());
    try {
      const res = await client.post(`/api/tts-voices/${interfaceId}/fetch`);
      setFetchedVoices(res.data.voices || []);
      setShowFetchDialog(true);
    } catch (e: any) {
      alert("获取音色失败: " + (e.response?.data?.detail || e.message));
    } finally {
      setFetchLoading(false);
    }
  };

  const toggleFetchSelect = (voiceId: string) => {
    setFetchSelected((prev) => {
      const next = new Set(prev);
      if (next.has(voiceId)) next.delete(voiceId);
      else next.add(voiceId);
      return next;
    });
  };

  const toggleFetchSelectAll = () => {
    if (fetchSelected.size === fetchedVoices.length) {
      setFetchSelected(new Set());
    } else {
      setFetchSelected(new Set(fetchedVoices.map((v) => v.voice_id)));
    }
  };

  const handleBatchAdd = async () => {
    const selectedVoices = fetchedVoices.filter((v) =>
      fetchSelected.has(v.voice_id)
    );
    if (selectedVoices.length === 0) {
      alert("请至少选择一个音色");
      return;
    }
    setSaving(true);
    try {
      await client.post(`/api/tts-voices/${interfaceId}/batch`, {
        voices: selectedVoices,
      });
      setShowFetchDialog(false);
      setFetchedVoices([]);
      setFetchSelected(new Set());
      loadVoices();
    } catch (e: any) {
      alert("批量添加失败: " + (e.response?.data?.detail || e.message));
    } finally {
      setSaving(false);
    }
  };

  const filtered = search
    ? voices.filter((v) => {
        const q = search.toLowerCase();
        return (
          v.voice_name.toLowerCase().includes(q) ||
          v.voice_id.toLowerCase().includes(q) ||
          v.description.toLowerCase().includes(q) ||
          (GENDER_LABEL[v.gender] || "").includes(q) ||
          (AGE_LABEL[v.age] || "").includes(q) ||
          (v.language || "").toLowerCase().includes(q)
        );
      })
    : voices;

  if (!open) return null;

  const inputCls =
    "px-3 py-2 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none w-full";

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 backdrop-blur-sm animate-fade-in">
      <div className="bg-background rounded-2xl border border-border/50 shadow-2xl w-full max-w-3xl max-h-[85vh] flex flex-col animate-scale-in">
        {/* Header */}
        <div className="px-5 py-4 border-b border-border/40 flex items-center justify-between">
          <h3 className="text-lg font-bold flex items-center gap-2">
            <Mic2 className="w-5 h-5 text-primary" />
            音色管理 - {interfaceName}
          </h3>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-secondary transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Action bar */}
        <div className="px-5 py-3 border-b border-border/30 space-y-3">
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                setShowAddForm(true);
                setShowFetchDialog(false);
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-primary text-primary-foreground rounded-lg transition-all duration-200 hover:shadow-lg hover:shadow-primary/25 active:scale-[0.97]"
            >
              <Plus className="w-3.5 h-3.5" />
              手动添加
            </button>
            <button
              onClick={handleFetch}
              disabled={fetchLoading}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border border-border/60 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent/60 transition-all duration-200 active:scale-[0.97] disabled:opacity-50"
            >
              <Download className="w-3.5 h-3.5" />
              {fetchLoading ? "获取中..." : "获取支持音色"}
            </button>
          </div>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
            <input
              className="w-full pl-8 pr-3 py-2 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none"
              placeholder="搜索音色..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
        </div>

        {/* Voice table */}
        <div className="flex-1 overflow-y-auto max-h-[420px]">
          {loading ? (
            <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
              加载中...
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <Mic2 className="w-8 h-8 mb-2 opacity-40" />
              <span className="text-sm">暂无音色数据</span>
            </div>
          ) : (
            <div>
              {/* Table header */}
              <div className="flex items-center gap-3 px-5 py-2 border-b border-border/30 bg-muted/30 sticky top-0 z-10">
                <div className="flex-1 text-xs font-medium text-muted-foreground">
                  voice_name
                </div>
                <div className="w-36 text-xs font-medium text-muted-foreground">
                  voice_id
                </div>
                <div className="w-12 text-xs font-medium text-muted-foreground text-center">
                  性别
                </div>
                <div className="w-12 text-xs font-medium text-muted-foreground text-center">
                  年龄
                </div>
                <div className="w-16 text-xs font-medium text-muted-foreground text-center">
                  语言
                </div>
                <div className="w-10"></div>
              </div>
              {/* Table rows */}
              <div className="divide-y divide-border/20">
                {filtered.map((v) => (
                  <div
                    key={v.voice_id}
                    className="flex items-center gap-3 px-5 py-2.5 hover:bg-muted/20 transition-colors"
                  >
                    <div className="flex-1 min-w-0">
                      <span className="text-sm font-medium truncate block">
                        {v.voice_name || "-"}
                      </span>
                      {v.description && (
                        <p className="text-[11px] text-muted-foreground mt-0.5 truncate">
                          {v.description}
                        </p>
                      )}
                    </div>
                    <div className="w-36 text-xs text-muted-foreground font-mono truncate">
                      {v.voice_id}
                    </div>
                    <div className="w-12 text-xs text-center">
                      {GENDER_LABEL[v.gender] || ""}
                    </div>
                    <div className="w-12 text-xs text-center">
                      {AGE_LABEL[v.age] || ""}
                    </div>
                    <div className="w-16 text-xs text-center text-muted-foreground">
                      {v.language || ""}
                    </div>
                    <button
                      onClick={() => handleDelete(v.voice_id)}
                      className="w-10 flex justify-center p-1.5 rounded-lg text-muted-foreground hover:text-red-500 hover:bg-red-500/10 transition-all duration-200"
                      title="删除"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-border/40 flex items-center justify-between">
          <span className="text-xs text-muted-foreground">
            共 {voices.length} 个音色
          </span>
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium border border-border/60 rounded-xl hover:bg-secondary/70 transition-all duration-200 active:scale-[0.97]"
          >
            关闭
          </button>
        </div>
      </div>

      {/* Add voice form dialog */}
      {showAddForm && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm animate-fade-in">
          <div className="bg-background border border-border/60 rounded-2xl shadow-2xl w-[min(480px,90vw)] p-6 space-y-4 animate-scale-in">
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-semibold">手动添加音色</h4>
              <button
                onClick={() => setShowAddForm(false)}
                className="p-1.5 rounded-lg hover:bg-secondary transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                  Voice ID *
                </label>
                <input
                  className={inputCls}
                  value={addForm.voice_id}
                  onChange={(e) =>
                    setAddForm({ ...addForm, voice_id: e.target.value })
                  }
                  placeholder="必填，唯一标识"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                  音色名称
                </label>
                <input
                  className={inputCls}
                  value={addForm.voice_name}
                  onChange={(e) =>
                    setAddForm({ ...addForm, voice_name: e.target.value })
                  }
                  placeholder="显示名称"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                  描述
                </label>
                <input
                  className={inputCls}
                  value={addForm.description}
                  onChange={(e) =>
                    setAddForm({ ...addForm, description: e.target.value })
                  }
                  placeholder="音色描述"
                />
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                    性别
                  </label>
                  <select
                    className={inputCls}
                    value={addForm.gender}
                    onChange={(e) =>
                      setAddForm({ ...addForm, gender: e.target.value })
                    }
                  >
                    <option value="">-</option>
                    {GENDER_OPTIONS.map((g) => (
                      <option key={g.value} value={g.value}>
                        {g.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                    年龄
                  </label>
                  <select
                    className={inputCls}
                    value={addForm.age}
                    onChange={(e) =>
                      setAddForm({ ...addForm, age: e.target.value })
                    }
                  >
                    <option value="">-</option>
                    {AGE_OPTIONS.map((a) => (
                      <option key={a.value} value={a.value}>
                        {a.label}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1.5 block">
                    语言
                  </label>
                  <input
                    className={inputCls}
                    value={addForm.language}
                    onChange={(e) =>
                      setAddForm({ ...addForm, language: e.target.value })
                    }
                    placeholder="如 zh-CN"
                  />
                </div>
              </div>
            </div>
            <div className="flex gap-3 justify-end pt-2">
              <button
                onClick={() => setShowAddForm(false)}
                className="px-4 py-2 text-sm font-medium border border-border/60 rounded-xl hover:bg-secondary/70 transition-all duration-200 active:scale-[0.97]"
              >
                取消
              </button>
              <button
                onClick={handleAdd}
                disabled={saving}
                className="px-4 py-2 text-sm font-semibold bg-primary text-primary-foreground rounded-xl transition-all duration-200 hover:shadow-lg hover:shadow-primary/25 active:scale-[0.97] disabled:opacity-40"
              >
                {saving ? "保存中..." : "保存"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Fetch & batch select dialog */}
      {showFetchDialog && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 backdrop-blur-sm animate-fade-in">
          <div className="bg-background border border-border/60 rounded-2xl shadow-2xl w-[min(560px,90vw)] max-h-[80vh] flex flex-col animate-scale-in">
            <div className="px-5 py-4 border-b border-border/40 flex items-center justify-between">
              <h4 className="text-sm font-semibold">选择要添加的音色</h4>
              <button
                onClick={() => setShowFetchDialog(false)}
                className="p-1.5 rounded-lg hover:bg-secondary transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="px-5 py-3 border-b border-border/30">
              <button
                onClick={toggleFetchSelectAll}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border border-border/60 rounded-lg hover:bg-accent/60 transition-colors"
              >
                <UserCheck className="w-3.5 h-3.5" />
                {fetchSelected.size === fetchedVoices.length &&
                fetchedVoices.length > 0
                  ? "取消全选"
                  : "全选"}
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-5 py-3 max-h-[400px]">
              {fetchedVoices.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                  <Mic2 className="w-8 h-8 mb-2 opacity-40" />
                  <span className="text-sm">未获取到音色</span>
                </div>
              ) : (
                <div className="space-y-1.5">
                  {fetchedVoices.map((v) => (
                    <label
                      key={v.voice_id}
                      className="flex items-center gap-3 p-3 rounded-xl border border-border/30 hover:border-primary/40 cursor-pointer transition-colors"
                    >
                      <input
                        type="checkbox"
                        checked={fetchSelected.has(v.voice_id)}
                        onChange={() => toggleFetchSelect(v.voice_id)}
                        className="rounded"
                      />
                      <div className="flex-1 min-w-0">
                        <span className="text-sm font-medium">
                          {v.voice_name || v.voice_id}
                        </span>
                        {v.description && (
                          <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1">
                            {v.description}
                          </p>
                        )}
                      </div>
                      <div className="flex items-center gap-1 flex-shrink-0">
                        {v.gender && (
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-muted/50 text-muted-foreground">
                            {GENDER_LABEL[v.gender] || v.gender}
                          </span>
                        )}
                        {v.age && (
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-muted/50 text-muted-foreground">
                            {AGE_LABEL[v.age] || v.age}
                          </span>
                        )}
                        {v.language && (
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-muted/50 text-muted-foreground">
                            {v.language}
                          </span>
                        )}
                      </div>
                    </label>
                  ))}
                </div>
              )}
            </div>
            <div className="px-5 py-3 border-t border-border/40 flex items-center justify-between">
              <span className="text-xs text-muted-foreground">
                已选 {fetchSelected.size} / {fetchedVoices.length}
              </span>
              <div className="flex gap-3">
                <button
                  onClick={() => setShowFetchDialog(false)}
                  className="px-4 py-2 text-sm font-medium border border-border/60 rounded-xl hover:bg-secondary/70 transition-all duration-200 active:scale-[0.97]"
                >
                  取消
                </button>
                <button
                  onClick={handleBatchAdd}
                  disabled={saving || fetchSelected.size === 0}
                  className="flex items-center gap-1.5 px-4 py-2 text-sm font-semibold bg-primary text-primary-foreground rounded-xl transition-all duration-200 hover:shadow-lg hover:shadow-primary/25 active:scale-[0.97] disabled:opacity-40"
                >
                  <Check className="w-3.5 h-3.5" />
                  {saving ? "添加中..." : "确认添加"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

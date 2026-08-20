import { useState, useEffect, useCallback } from "react";
import {
  ocrInterfacesApi,
  OCRInterface,
  OCRInterfaceConfig,
  OCRDeps,
  OCRConfigFields,
  OCRTestResult,
} from "@/api/ocrInterfaces";
import { cn } from "@/lib/utils";
import {
  ScanText,
  Save,
  Loader2,
  ChevronDown,
  ShieldCheck,
  AlertTriangle,
  Cpu,
  Boxes,
  Languages,
  Settings,
  FlaskConical,
  CheckCircle2,
  Upload,
  Trash2,
} from "lucide-react";

const DEFAULT_CONFIG: OCRInterfaceConfig = {
  sdk_module: "backend.ocr.ocr_rapidocr",
  sdk_class: "RapidOCREngine",
  engine_type: "onnxruntime",
  ocr_version: "PP-OCRv6",
  model_type: "small",
  custom_model_name: "",
  lang_type: "ch",
  use_cuda: false,
  device_id: 0,
  use_det: true,
  use_cls: true,
  use_rec: true,
  text_score: 0.5,
  box_thresh: 0.5,
  unclip_ratio: 1.6,
  limit_side_len: 736,
  threads: -1,
  return_word_box: false,
  max_workers: 4,
  timeout: 120,
};

const DEP_LABELS: Record<keyof OCRDeps, string> = {
  rapidocr: "rapidocr",
  onnxruntime: "onnxruntime",
  torch: "PyTorch",
  paddle: "PaddlePaddle",
};

const ENGINE_TIPS: Record<string, { tip: string; warn?: boolean }> = {
  onnxruntime: {
    tip: "CPU 默认引擎，兼容性最好，无需额外配置，推荐首选。",
  },
  torch: {
    tip: "GPU 默认引擎，使用项目已安装的 PyTorch（CUDA 版）。若未安装 torch，请先运行安装脚本或在 venv 中执行 pip install torch。",
  },
  paddle: {
    tip: "GPU 备用引擎，未随项目安装。选择后需手动安装：pip install paddlepaddle-gpu（请按官方文档选择对应 CUDA 版本：https://www.paddlepaddle.org.cn/install/quick），否则运行时将报错。",
    warn: true,
  },
};

function Toggle({
  checked,
  onChange,
  label,
  desc,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  desc?: string;
}) {
  return (
    <div className="flex items-center justify-between p-3 rounded-xl border border-border/40 hover:border-border/60 transition-all duration-200">
      <div>
        <label className="text-sm font-medium">{label}</label>
        {desc && <p className="text-xs text-muted-foreground">{desc}</p>}
      </div>
      <label className="relative cursor-pointer flex items-center">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          className="peer sr-only"
        />
        <div className="w-9 h-5 bg-muted rounded-full peer-checked:bg-primary transition-colors duration-200" />
        <div className="absolute left-0.5 top-0.5 w-4 h-4 bg-background rounded-full shadow-sm peer-checked:translate-x-4 transition-transform duration-200" />
      </label>
    </div>
  );
}

export default function OCRSettings() {
  const [interfaces, setInterfaces] = useState<OCRInterface[]>([]);
  const [config, setConfig] = useState<OCRInterfaceConfig>({ ...DEFAULT_CONFIG });
  const [deps, setDeps] = useState<OCRDeps | null>(null);
  const [fields, setFields] = useState<OCRConfigFields | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  // 测试区状态
  const [testImage, setTestImage] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<OCRTestResult | null>(null);

  // 高级参数折叠
  const [showAdvanced, setShowAdvanced] = useState(false);

  const load = useCallback(async () => {
    const [ifaceRes, depsRes, fieldsRes] = await Promise.all([
      ocrInterfacesApi.list(),
      ocrInterfacesApi.checkDeps(),
      ocrInterfacesApi.configFields(),
    ]);
    const list = ifaceRes.data.interfaces || [];
    setInterfaces(list);
    const builtin = list.find((i: OCRInterface) => i.id === "rapidocr") || list[0];
    if (builtin) {
      setConfig({ ...DEFAULT_CONFIG, ...(builtin.config || {}) });
    }
    setDeps(depsRes.data.deps);
    setFields(fieldsRes.data);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const ifaceId = interfaces.find((i) => i.id === "rapidocr")?.id || interfaces[0]?.id || "rapidocr";

  const setCfg = (patch: Partial<OCRInterfaceConfig>) => {
    setSaved(false);
    setConfig((prev) => ({ ...prev, ...patch }));
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await ocrInterfacesApi.update(ifaceId, { config });
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e: any) {
      alert("保存失败：" + (e?.response?.data?.detail || e?.message || String(e)));
    } finally {
      setSaving(false);
    }
  };

  const handleEngineChange = (value: string) => {
    if (value === "paddle" && deps && !deps.paddle) {
      alert(
        "当前未安装 PaddlePaddle！\n\n这是 GPU 备用引擎，未随项目安装。请先手动安装：\n\npip install paddlepaddle-gpu\n\n（按官方文档选择对应 CUDA 版本：https://www.paddlepaddle.org.cn/install/quick）\n\n你也可以暂时选择 onnxruntime（CPU）或 torch（GPU）。"
      );
    }
    if (value === "torch" && deps && !deps.torch) {
      alert("未检测到 PyTorch。GPU 引擎依赖项目已安装的 PyTorch（CUDA 版），请先安装后再切换。");
    }
    setCfg({
      engine_type: value,
      use_cuda: value !== "onnxruntime",
    });
  };

  const sizesForVersion = fields?.sizes_by_version?.[config.ocr_version] || ["small"];

  const handleUpload = async (file: File) => {
    try {
      const res = await ocrInterfacesApi.uploadImage(file);
      setTestImage(res.data.path || "");
      setTestResult(null);
    } catch (e: any) {
      alert("上传失败：" + (e?.response?.data?.detail || e?.message || String(e)));
    }
  };

  const handleTest = async () => {
    if (!testImage) return;
    setTesting(true);
    setTestResult(null);
    try {
      const res = await ocrInterfacesApi.test(ifaceId, { image_path: testImage });
      setTestResult(res.data);
    } catch (e: any) {
      alert("测试失败：" + (e?.response?.data?.detail || e?.message || String(e)));
    } finally {
      setTesting(false);
    }
  };

  const selectCls = "w-full px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none appearance-none";
  const inputCls = "w-full px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none";
  const numCls = "w-full px-3 py-2 border border-border/60 rounded-lg bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none";
  const cardCls = "rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4";
  const sectionTitle = "text-sm font-semibold flex items-center gap-2";

  return (
    <div className="space-y-5 stagger-children">
      {/* 依赖状态卡 */}
      <div className={cardCls}>
        <h3 className={sectionTitle}>
          <ShieldCheck className="w-4 h-4 text-primary" />
          运行环境依赖
        </h3>
        <p className="text-xs text-muted-foreground">
          OCR 使用 rapidocr 本地离线推理。其中 PaddlePaddle 为 GPU 备用引擎，未随项目安装；PyTorch 已随项目安装。
        </p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {deps &&
            (Object.keys(DEP_LABELS) as (keyof OCRDeps)[]).map((key) => {
              const ok = deps[key];
              return (
                <div
                  key={key}
                  className={cn(
                    "flex flex-col gap-1 p-3 rounded-xl border transition-all duration-200",
                    ok ? "border-emerald-500/30 bg-emerald-500/5" : "border-amber-500/30 bg-amber-500/5"
                  )}
                >
                  <div className="flex items-center gap-1.5">
                    {ok ? (
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
                    ) : (
                      <AlertTriangle className="w-3.5 h-3.5 text-amber-500" />
                    )}
                    <span className="text-xs font-medium truncate">{DEP_LABELS[key]}</span>
                  </div>
                  <span className={cn("text-[11px]", ok ? "text-emerald-600" : "text-amber-600")}>
                    {ok ? "已安装" : key === "paddle" ? "未安装（可选）" : "未安装"}
                  </span>
                </div>
              );
            })}
        </div>
        {deps && !deps.paddle && (
          <div className="flex items-start gap-2 p-3 rounded-xl border border-amber-500/30 bg-amber-500/5 text-xs text-amber-700">
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
            <div>
              选择 PaddlePaddle 引擎前请先手动安装：<code className="font-mono">pip install paddlepaddle-gpu</code>
              （按官方文档选择对应 CUDA 版本：https://www.paddlepaddle.org.cn/install/quick）
            </div>
          </div>
        )}
        {deps && !deps.rapidocr && (
          <div className="flex items-start gap-2 p-3 rounded-xl border border-red-500/30 bg-red-500/5 text-xs text-red-600">
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
            <div>
              rapidocr 未安装，请先安装依赖：<code className="font-mono">pip install rapidocr onnxruntime</code>
            </div>
          </div>
        )}
      </div>

      {/* 推理引擎 */}
      <div className={cardCls}>
        <h3 className={sectionTitle}>
          <Cpu className="w-4 h-4 text-primary" />
          推理引擎
        </h3>
        <div className="space-y-3">
          <select
            className={selectCls}
            value={config.engine_type}
            onChange={(e) => handleEngineChange(e.target.value)}
          >
            {fields?.engine_options.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <div
            className={cn(
              "flex items-start gap-2 p-3 rounded-xl border text-xs",
              ENGINE_TIPS[config.engine_type]?.warn
                ? "border-amber-500/30 bg-amber-500/5 text-amber-700"
                : "border-primary/20 bg-primary/5 text-muted-foreground"
            )}
          >
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
            <span>{ENGINE_TIPS[config.engine_type]?.tip}</span>
          </div>
          {config.engine_type !== "onnxruntime" && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-muted-foreground mb-1.5 block">GPU 设备号</label>
                <input
                  type="number"
                  className={numCls}
                  value={config.device_id}
                  min={0}
                  onChange={(e) => setCfg({ device_id: parseInt(e.target.value || "0", 10) })}
                />
              </div>
              <div className="flex items-end pb-1">
                <Toggle
                  checked={config.use_cuda}
                  onChange={(v) => setCfg({ use_cuda: v })}
                  label="启用 CUDA"
                  desc="使用 GPU 加速推理"
                />
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 模型配置 */}
      <div className={cardCls}>
        <h3 className={sectionTitle}>
          <Boxes className="w-4 h-4 text-primary" />
          模型配置
        </h3>
        <p className="text-xs text-muted-foreground">
          支持 PP-OCRv6 / PP-OCRv5 / PP-OCRv4。非默认版本/尺寸首次使用时将自动从魔搭社区下载模型；尺寸越大精度越高、速度越慢。
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-muted-foreground mb-1.5 block">模型版本</label>
            <select
              className={selectCls}
              value={config.ocr_version}
              onChange={(e) => {
                const sizes = fields?.sizes_by_version?.[e.target.value] || ["small"];
                setCfg({ ocr_version: e.target.value, model_type: sizes[0] });
              }}
            >
              {fields && Object.keys(fields.sizes_by_version).map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-muted-foreground mb-1.5 block">模型尺寸</label>
            <select
              className={selectCls}
              value={config.model_type}
              disabled={!!config.custom_model_name}
              onChange={(e) => setCfg({ model_type: e.target.value })}
            >
              {sizesForVersion.map((s) => (
                <option key={s} value={s}>
                  {s}
                  {s === "small" || s === "mobile" ? "（默认，均衡）" : s === "tiny" ? "（最快）" : s === "medium" || s === "server" ? "（更高精度）" : ""}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div>
          <label className="text-xs text-muted-foreground mb-1.5 block">
            自定义模型名（高级）
          </label>
          <input
            className={inputCls}
            placeholder="留空使用上方默认选择；填写后原样透传给 rapidocr"
            value={config.custom_model_name}
            onChange={(e) => setCfg({ custom_model_name: e.target.value })}
          />
          <p className="text-[11px] text-muted-foreground mt-1.5">
            为后续新增模型版本预留的透传入口：填写后将覆盖上方「模型版本 / 模型尺寸」作为模型标识原样传给 rapidocr（需自行确保对应模型可用）。
          </p>
        </div>
      </div>

      {/* 识别语言 */}
      <div className={cardCls}>
        <h3 className={sectionTitle}>
          <Languages className="w-4 h-4 text-primary" />
          识别语言
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 items-end">
          <div>
            <select
              className={selectCls}
              value={config.lang_type}
              onChange={(e) => setCfg({ lang_type: e.target.value })}
            >
              {fields?.lang_options.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
          <p className="text-xs text-muted-foreground">
            ch 支持中英文混合识别；en 英文；multi 多语言（首次使用自动下载对应模型）。
          </p>
        </div>
      </div>

      {/* 管线开关 */}
      <div className={cardCls}>
        <h3 className={sectionTitle}>
          <Settings className="w-4 h-4 text-primary" />
          识别管线
        </h3>
        <div className="space-y-2">
          <Toggle
            checked={config.use_det}
            onChange={(v) => setCfg({ use_det: v })}
            label="文本检测（Det）"
            desc="定位图片中的文本行区域"
          />
          <Toggle
            checked={config.use_cls}
            onChange={(v) => setCfg({ use_cls: v })}
            label="方向分类（Cls）"
            desc="识别 0° / 180° 文本行方向"
          />
          <Toggle
            checked={config.use_rec}
            onChange={(v) => setCfg({ use_rec: v })}
            label="文字识别（Rec）"
            desc="输出每行文本内容"
          />
        </div>
      </div>

      {/* 高级参数 */}
      <div className={cardCls}>
        <button
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="w-full flex items-center justify-between"
        >
          <h3 className={sectionTitle}>
            <Settings className="w-4 h-4 text-primary" />
            高级参数
          </h3>
          <ChevronDown
            className={cn("w-4 h-4 text-muted-foreground transition-transform duration-200", showAdvanced && "rotate-180")}
          />
        </button>
        {showAdvanced && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            <div>
              <label className="text-xs text-muted-foreground mb-1.5 block">
                识别置信度阈值 text_score
              </label>
              <input
                type="number"
                step="0.05"
                min="0"
                max="1"
                className={numCls}
                value={config.text_score}
                onChange={(e) => setCfg({ text_score: parseFloat(e.target.value || "0.5") })}
              />
              <p className="text-[11px] text-muted-foreground mt-1">值越大把握越大（0~1），默认 0.5</p>
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1.5 block">检测框阈值 box_thresh</label>
              <input
                type="number"
                step="0.05"
                min="0"
                max="1"
                className={numCls}
                value={config.box_thresh}
                onChange={(e) => setCfg({ box_thresh: parseFloat(e.target.value || "0.5") })}
              />
              <p className="text-[11px] text-muted-foreground mt-1">值越大召回率越低（0~1），默认 0.5</p>
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1.5 block">检测框扩展 unclip_ratio</label>
              <input
                type="number"
                step="0.1"
                min="1.6"
                max="2.0"
                className={numCls}
                value={config.unclip_ratio}
                onChange={(e) => setCfg({ unclip_ratio: parseFloat(e.target.value || "1.6") })}
              />
              <p className="text-[11px] text-muted-foreground mt-1">值越大检测框整体越大（1.6~2.0），默认 1.6</p>
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1.5 block">图像边长限制 limit_side_len</label>
              <input
                type="number"
                min="32"
                className={numCls}
                value={config.limit_side_len}
                onChange={(e) => setCfg({ limit_side_len: parseInt(e.target.value || "736", 10) })}
              />
              <p className="text-[11px] text-muted-foreground mt-1">单位 px，越小处理越快，默认 736</p>
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1.5 block">推理线程数 threads</label>
              <input
                type="number"
                className={numCls}
                value={config.threads}
                onChange={(e) => setCfg({ threads: parseInt(e.target.value || "-1", 10) })}
              />
              <p className="text-[11px] text-muted-foreground mt-1">ONNX Runtime 线程数，-1 表示自动</p>
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1.5 block">批处理线程数 max_workers</label>
              <input
                type="number"
                min={1}
                className={numCls}
                value={config.max_workers}
                onChange={(e) => setCfg({ max_workers: parseInt(e.target.value || "4", 10) })}
              />
              <p className="text-[11px] text-muted-foreground mt-1">
                批量抽帧文字检测时并行推理的线程数，默认 4；建议不超过 CPU 核心数
              </p>
            </div>
            <div className="flex items-end pb-1">
              <Toggle
                checked={config.return_word_box}
                onChange={(v) => setCfg({ return_word_box: v })}
                label="返回单字坐标"
                desc="额外返回每个字/词的坐标信息"
              />
            </div>
          </div>
        )}
      </div>

      {/* 测试区 */}
      <div className={cardCls}>
        <h3 className={sectionTitle}>
          <FlaskConical className="w-4 h-4 text-primary" />
          测试识别
        </h3>
        <p className="text-xs text-muted-foreground">
          上传一张图片快速验证当前配置的 OCR 识别效果（支持 png / jpg / jpeg / bmp / webp / tif）。
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold border border-border/60 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent/60 transition-all duration-200 cursor-pointer active:scale-[0.97]">
            <Upload className="w-3.5 h-3.5" />
            上传图片
            <input
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleUpload(file);
                e.target.value = "";
              }}
            />
          </label>
          {testImage && (
            <>
              <span className="text-xs text-muted-foreground truncate max-w-[200px]">{testImage.split(/[\\/]/).pop()}</span>
              <button
                onClick={handleTest}
                disabled={testing}
                className="flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold bg-primary text-primary-foreground rounded-lg transition-all duration-200 hover:shadow-lg hover:shadow-primary/25 active:scale-[0.97] disabled:opacity-50"
              >
                {testing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ScanText className="w-3.5 h-3.5" />}
                {testing ? "识别中..." : "开始识别"}
              </button>
              <button
                onClick={() => {
                  setTestImage("");
                  setTestResult(null);
                }}
                className="p-2 rounded-lg border border-border/40 hover:bg-red-500/10 text-muted-foreground hover:text-red-500 transition-all duration-200"
                title="清除"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </>
          )}
        </div>
        {testResult && (
          <div className="space-y-2">
            <div className="flex items-center gap-3 text-xs text-muted-foreground">
              <span className="flex items-center gap-1">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
                识别 {testResult.txts.length} 行
              </span>
              <span>总耗时 {testResult.elapse.toFixed(3)}s</span>
            </div>
            <div className="rounded-xl border border-border/40 divide-y divide-border/40 max-h-80 overflow-y-auto">
              {testResult.txts.map((txt, i) => (
                <div key={i} className="flex items-center justify-between gap-3 px-3.5 py-2.5">
                  <span className="text-sm break-all">{txt}</span>
                  <span className="text-[11px] text-muted-foreground shrink-0 font-mono">
                    {testResult.scores?.[i] !== undefined
                      ? (testResult.scores[i] * 100).toFixed(1) + "%"
                      : "-"}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* 保存 */}
      <div className="flex items-center justify-end gap-3">
        <span className="text-xs text-muted-foreground">
          {saved ? "已保存到 ocr_interfaces.json，重启后端后仍生效" : "配置保存在内置接口 rapidocr 中"}
        </span>
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-1.5 px-5 py-2.5 text-sm font-semibold bg-primary text-primary-foreground rounded-xl transition-all duration-200 hover:shadow-lg hover:shadow-primary/25 active:scale-[0.97] disabled:opacity-50"
        >
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
          {saving ? "保存中..." : "保存配置"}
        </button>
      </div>
    </div>
  );
}

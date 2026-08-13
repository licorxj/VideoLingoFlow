import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { settingsApi } from "@/api/settings";
import { Brain, Link, Key, Layers, Zap, Loader2, Info, ExternalLink, Wrench } from "lucide-react";
import PromptEditor from "./PromptEditor";

const STEPS = [
  { id: "default_model", name: "默认模型" },
  { id: "s02_subtitle_check", name: "字幕查错" },
  { id: "s03_sentence_split", name: "句子分割" },
  { id: "s04_summarize", name: "内容总结" },
  { id: "s05_translate_faithful", name: "逐句翻译" },
  { id: "s05_translate_reflect", name: "反思翻译" },
  { id: "s07_subtitle_align", name: "字幕对齐" },
  { id: "s08_dub_task", name: "配音任务" },
  { id: "s09_subtitle_reduction", name: "字幕缩减" },
  { id: "agent_model", name: "Agent 模型" },
];

export default function LLMSettings() {
  const navigate = useNavigate();
  const [useRouter, setUseRouter] = useState(true);
  const [routerUrl, setRouterUrl] = useState("http://localhost:8800/v1");
  const [routerApiKey, setRouterApiKey] = useState("123");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [maxConcurrent, setMaxConcurrent] = useState("10");
  const [maxRequestChars, setMaxRequestChars] = useState("12000");
  const [timeout, setTimeoutVal] = useState("120");
  const [retryEnabled, setRetryEnabled] = useState(true);
  const [retryCount, setRetryCount] = useState("3");
  const [models, setModels] = useState<Record<string, string>>({});
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, { ok: boolean; msg: string }>>({});
  const [promptEditorOpen, setPromptEditorOpen] = useState(false);

  useEffect(() => {
    settingsApi.getAll().then((res) => {
      const cfg = res.data.config?.llm || {};
      setUseRouter(cfg.use_router ?? true);
      setRouterUrl(cfg.router_url || "http://localhost:8800/v1");
      setRouterApiKey(cfg.router_api_key || "123");
      setBaseUrl(cfg.base_url || "");
      setApiKey(cfg.api_key || "");
      setMaxConcurrent(String(cfg.max_concurrent || 10));
      setMaxRequestChars(String(cfg.max_request_chars || 12000));
      setTimeoutVal(String(cfg.timeout || 120));
      setRetryEnabled(cfg.retry_enabled ?? true);
      setRetryCount(String(cfg.retry_count ?? 3));
      setModels(cfg.step_models || {});
    });
  }, []);

  const testModel = async (stepId: string) => {
    setTesting(stepId);
    setTestResult((prev) => ({ ...prev, [stepId]: { ok: false, msg: "" } }));
    try {
      const res = await fetch("/api/llm/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ step_name: stepId, prompt: 'Respond with JSON: {"message": "connectivity_ok"}' }),
      });
      const data = await res.json();
      if (data.success) {
        setTestResult((prev) => ({ ...prev, [stepId]: { ok: true, msg: "\u8fde\u901a\u6210\u529f" } }));
      } else {
        setTestResult((prev) => ({ ...prev, [stepId]: { ok: false, msg: data.error || "\u8fde\u901a\u5931\u8d25" } }));
      }
    } catch (err: any) {
      const msg = err.message || "\u8bf7\u6c42\u5931\u8d25";
      setTestResult((prev) => ({ ...prev, [stepId]: { ok: false, msg } }));
    }
    setTesting(null);
  };

  const saveModel = (step: string, val: string) => {
    setModels({ ...models, [step]: val });
    settingsApi.update("llm.step_models." + step, val);
  };

  return (
    <div className="space-y-5 stagger-children">
      <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Link className="w-4 h-4 text-primary" />
          连接配置
        </h3>

        {/* 二选一控件 */}
        <div className="flex p-1 rounded-xl bg-muted/50 border border-border/40 w-fit">
          <button
            onClick={() => {
              setUseRouter(true);
              settingsApi.update("llm.use_router", true);
            }}
            className={"px-4 py-2 text-sm font-medium rounded-lg transition-all duration-200 " +
              (useRouter
                ? "bg-primary text-primary-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground")}
          >
            大模型路由器
          </button>
          <button
            onClick={() => {
              setUseRouter(false);
              settingsApi.update("llm.use_router", false);
            }}
            className={"px-4 py-2 text-sm font-medium rounded-lg transition-all duration-200 " +
              (!useRouter
                ? "bg-primary text-primary-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground")}
          >
            自定义大模型
          </button>
        </div>

        {/* 大模型路由器模式 */}
        {useRouter && (
          <div className="space-y-4">
            <div className="flex items-start gap-3 p-4 rounded-xl bg-muted/30 border-l-4 border-primary">
              <Info className="w-4 h-4 text-primary mt-0.5 flex-shrink-0" />
              <p className="text-sm text-muted-foreground leading-relaxed">
                推荐使用本项目自带的大模型路由器来管理各个阶段的使用模型，并可以使用路由器中的多模型多api混合路由带来的高并发和自动化切换的便利，请前往大模型路由器中配置好你的平台和api，并在策略中填入你的模型和路由规则，注意，下方的各阶段的模型名称对应的是路由器中的策略名称，如果不熟悉，请勿修改
              </p>
            </div>
            <button
              onClick={() => navigate("/llm-router")}
              className="flex items-center gap-2 px-4 py-2.5 text-sm font-medium rounded-xl border border-border/60 bg-background/50 hover:bg-primary/10 hover:border-primary/50 hover:text-primary transition-all duration-200"
            >
              <ExternalLink className="w-4 h-4" />
              前往大模型路由器
            </button>
          </div>
        )}

        {/* 自定义大模型模式 */}
        {!useRouter && (
          <div className="space-y-4">
            <div>
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                统一 API URL
              </label>
              <input
                className="w-full mt-2 px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                onBlur={() => settingsApi.update("llm.base_url", baseUrl)}
                placeholder="https://your-api-router.com/v1"
              />
              <p className="text-xs text-muted-foreground mt-1">
                自定义大模型的 API 地址，所有阶段的 LLM 请求将发送到此地址
              </p>
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                API Key
              </label>
              <div className="relative mt-2">
                <Key className="absolute left-3.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground/50" />
                <input
                  type="password"
                  className="w-full pl-10 pr-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  onBlur={() => settingsApi.update("llm.api_key", apiKey)}
                  placeholder="your-api-key"
                />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 请求参数板块 */}
      <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Zap className="w-4 h-4 text-primary" />
          请求参数
        </h3>
        <div className="grid md:grid-cols-3 gap-4">
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              模型并发请求数
            </label>
            <input
              type="number"
              min="1"
              max="50"
              className="w-full mt-2 px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none"
              value={maxConcurrent}
              onChange={(e) => setMaxConcurrent(e.target.value)}
              onBlur={() => settingsApi.update("llm.max_concurrent", parseInt(maxConcurrent) || 10)}
              placeholder="10"
            />
            <p className="text-xs text-muted-foreground mt-1.5">
              同时发起的 LLM 请求数量
            </p>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              模型请求字数上限
            </label>
            <input
              type="number"
              min="100"
              max="500000"
              className="w-full mt-2 px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none"
              value={maxRequestChars}
              onChange={(e) => setMaxRequestChars(e.target.value)}
              onBlur={() =>
                settingsApi.update(
                  "llm.max_request_chars",
                  parseInt(maxRequestChars) || 12000,
                )
              }
              placeholder="12000"
            />
            <p className="text-xs text-muted-foreground mt-1.5">
              限制单次 LLM 请求文本字数，避免超出模型上下文
            </p>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              超时时间（秒）
            </label>
            <input
              type="number"
              min="10"
              max="600"
              className="w-full mt-2 px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none"
              value={timeout}
              onChange={(e) => setTimeoutVal(e.target.value)}
              onBlur={() => settingsApi.update("llm.timeout", parseInt(timeout) || 120)}
              placeholder="120"
            />
            <p className="text-xs text-muted-foreground mt-1.5">
              单次 LLM 请求的最长等待时间
            </p>
          </div>
        </div>
        <div className="grid md:grid-cols-2 gap-4">
          <div className="flex items-end">
            <label className="flex items-center gap-3 cursor-pointer group">
              <div className="relative">
                <input
                  type="checkbox"
                  checked={retryEnabled}
                  onChange={(e) => {
                    setRetryEnabled(e.target.checked);
                    settingsApi.update("llm.retry_enabled", e.target.checked);
                  }}
                  className="peer sr-only"
                />
                <div className="w-9 h-5 bg-muted rounded-full peer-checked:bg-primary transition-colors duration-200" />
                <div className="absolute left-0.5 top-0.5 w-4 h-4 bg-background rounded-full shadow-sm peer-checked:translate-x-4 transition-transform duration-200" />
              </div>
              <span className="text-sm group-hover:text-foreground transition-colors">
                超时重试
              </span>
            </label>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              重试次数
            </label>
            <input
              type="number"
              min="1"
              max="10"
              className="w-full mt-2 px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none"
              value={retryCount}
              onChange={(e) => setRetryCount(e.target.value)}
              onBlur={() => settingsApi.update("llm.retry_count", parseInt(retryCount) || 3)}
              placeholder="3"
            />
            <p className="text-xs text-muted-foreground mt-1.5">
              超时后最多重试的次数
            </p>
          </div>
        </div>
        <div className="pt-2">
          <button
            onClick={() => setPromptEditorOpen(true)}
            className="flex items-center gap-2 px-4 py-2.5 text-sm font-medium rounded-xl border border-border/60 bg-background/50 hover:bg-primary/10 hover:border-primary/50 hover:text-primary transition-all duration-200"
          >
            <Wrench className="w-4 h-4" />
            Prompt 工程
          </button>
          <p className="text-xs text-muted-foreground mt-1.5">
            自定义各步骤的 LLM Prompt 模板，支持占位符编辑和校验
          </p>
        </div>
      </div>

      <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
        <div>
          <h3 className="text-sm font-semibold flex items-center gap-2">
            <Layers className="w-4 h-4 text-primary" />
            "各阶段模型覆盖"
          </h3>
          <p className="text-xs text-muted-foreground">
            默认模型为兜底模型，必须设置，其他模型可选设置，不设置时将调用默认模型
          </p>
        </div>
        <div className="space-y-3">
          {STEPS.map((s) => (
            <div
              key={s.id}
              className="flex items-center gap-3 p-3 rounded-xl border border-border/40 hover:border-border/60 transition-colors duration-200"
            >
              <div className="w-28 flex-shrink-0">
                <div className="text-sm font-medium">{s.name}</div>
                <div className="text-[11px] text-muted-foreground font-mono">
                  {s.id}
                </div>
              </div>
              <input
                className="flex-1 px-3 py-2 border border-border/60 rounded-lg bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none"
                value={models[s.id] || ""}
                onChange={(e) =>
                  setModels({ ...models, [s.id]: e.target.value })
                }
                onBlur={() => saveModel(s.id, models[s.id] || "")}
                placeholder={s.id}
              />
              <button
                onClick={() => testModel(s.id)}
                disabled={testing === s.id}
                className={"flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border transition-all duration-200 flex-shrink-0 " +
                  (testing === s.id
                    ? "border-muted text-muted-foreground cursor-wait"
                    : testResult[s.id]?.ok
                    ? "border-green-500/50 text-green-600 hover:bg-green-500/10"
                    : testResult[s.id]
                    ? "border-red-500/50 text-red-600 hover:bg-red-500/10"
                    : "border-border/60 text-muted-foreground hover:border-primary/50 hover:text-primary")}
              >
                {testing === s.id ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <Zap className="w-3 h-3" />
                )}
                {testing === s.id ? "\u6d4b\u8bd5\u4e2d" : testResult[s.id]?.ok ? "\u8fde\u901a" : testResult[s.id] ? "\u5931\u8d25" : "\u8fde\u901a\u6d4b\u8bd5"}
              </button>
            </div>
          ))}
        </div>
      </div>
      <PromptEditor open={promptEditorOpen} onOpenChange={setPromptEditorOpen} />
    </div>
  );
}

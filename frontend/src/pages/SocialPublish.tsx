import { useState, useRef, useEffect } from "react";
import { ExternalLink, RefreshCw, Github, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAlert } from "@/components/ui/AlertProvider";

export default function SocialPublish() {
  const [updating, setUpdating] = useState(false);
  const [statusMsg, setStatusMsg] = useState("");
  const [iframeKey, setIframeKey] = useState(Date.now());
  const { alert } = useAlert();
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = () => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  };

  useEffect(() => {
    return () => stopPolling();
  }, []);

  const startPolling = () => {
    stopPolling();
    pollTimerRef.current = setInterval(async () => {
      try {
        const res = await fetch("/api/publish/update-status");
        if (!res.ok) return;
        const data = await res.json();
        if (data.message) {
          setStatusMsg(data.message);
        }

        if (data.status === "success") {
          stopPolling();
          setUpdating(false);
          setStatusMsg("");
          alert(data.message || "第三方项目更新完成！", "success", "更新成功");
          setIframeKey(Date.now());
        } else if (data.status === "error") {
          stopPolling();
          setUpdating(false);
          setStatusMsg("");
          alert(data.message || "第三方项目更新失败", "error", "更新失败");
        }
      } catch (e) {
        // 网络抖动忽略，等待下次轮询
      }
    }, 1500);
  };

  const handleUpdate = async () => {
    setUpdating(true);
    setStatusMsg("正在启动更新任务...");
    try {
      const res = await fetch("/api/publish/update-project", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      const data = await res.json();
      if (res.ok) {
        startPolling();
      } else {
        throw new Error(data.detail || data.msg || "启动更新任务失败");
      }
    } catch (err: any) {
      setUpdating(false);
      setStatusMsg("");
      alert(err.message || "无法发起项目更新操作，请重试", "error", "更新失败");
    }
  };

  return (
    <div className="flex flex-col h-[calc(100vh-56px)] -m-2">
      {/* 顶部工具与声明信息栏 */}
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2 bg-slate-100/90 dark:bg-slate-800/90 border-b border-slate-200 dark:border-slate-700/80 backdrop-blur shrink-0 text-sm">
        {/* 1. 开源项目声明 */}
        <div className="flex items-center gap-2 text-slate-800 dark:text-slate-200 font-medium">
          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-primary/10 text-primary border border-primary/20">
            <Sparkles className="w-3.5 h-3.5" />
            开源项目
          </span>
          <span className="font-semibold tracking-wide">QianFan Sync</span>
        </div>

        {/* 2 & 3. 操作按钮与更新状态 */}
        <div className="flex items-center gap-2.5">
          {updating && statusMsg && (
            <span className="text-xs text-primary font-medium animate-pulse">
              {statusMsg}
            </span>
          )}

          {/* 访问项目地址 */}
          <Button
            variant="outline"
            size="sm"
            className="h-8 gap-1.5 text-xs font-medium text-slate-700 dark:text-slate-300 hover:text-primary dark:hover:text-primary"
            asChild
          >
            <a
              href="https://github.com/DevilJie/social-auto-upload-web-ui"
              target="_blank"
              rel="noopener noreferrer"
            >
              <Github className="w-3.5 h-3.5" />
              <span>项目地址</span>
              <ExternalLink className="w-3 h-3 opacity-60" />
            </a>
          </Button>

          {/* 更新按钮 */}
          <Button
            variant="default"
            size="sm"
            disabled={updating}
            onClick={handleUpdate}
            className="h-8 gap-1.5 text-xs font-medium shadow-sm"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${updating ? "animate-spin" : ""}`} />
            <span>{updating ? "更新中..." : "更新项目"}</span>
          </Button>
        </div>
      </div>

      {/* iframe 视图 */}
      <iframe
        key={iframeKey}
        src="http://localhost:5173/social/#"
        className="w-full flex-1 border-none"
        title="多平台发布"
      />
    </div>
  );
}

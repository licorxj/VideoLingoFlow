import { useState, useEffect } from "react";
import { settingsApi } from "@/api/settings";
import { Cpu } from "lucide-react";

/** 线程设置：并发与资源（原「通用设置」页的高级设置板块） */
export default function ThreadSettings() {
  const [maxTasks, setMaxTasks] = useState(3);
  const [modelDir, setModelDir] = useState("./_model_cache");

  useEffect(() => {
    Promise.all([
      settingsApi.get("batch.max_concurrent_tasks"),
      settingsApi.get("advanced.model_dir"),
    ]).then(([mc, md]) => {
      setMaxTasks(mc.data.value ?? 3);
      setModelDir(md.data.value || "./_model_cache");
    });
  }, []);

  const save = (k: string, v: any) => settingsApi.update(k, v);

  return (
    <div className="space-y-5 stagger-children">
      <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Cpu className="w-4 h-4 text-primary" />
          "线程设置"
        </h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              "最大并发任务数"
            </label>
            <input type="number"
              className="w-full mt-2 px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none"
              value={maxTasks}
              onChange={(e) => setMaxTasks(+e.target.value)}
              onBlur={() => save("batch.max_concurrent_tasks", maxTasks)}
            />
            <p className="mt-1.5 text-[10px] text-muted-foreground">
              批量执行器立即生效；Worker 实际并行度为启动时读取值，修改后需重启后端进程
            </p>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              "模型缓存目录"
            </label>
            <input
              className="w-full mt-2 px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm font-mono focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none"
              value={modelDir}
              onChange={(e) => setModelDir(e.target.value)}
              onBlur={() => save("advanced.model_dir", modelDir)}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

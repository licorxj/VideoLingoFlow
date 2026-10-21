import { useState, useEffect } from "react";
import { settingsApi } from "@/api/settings";
import {
  Type,
} from "lucide-react";

export default function VideoSettings() {
  const [minSubDur, setMinSubDur] = useState(0.5);
  const [minTrimDur, setMinTrimDur] = useState(2);

  useEffect(() => {
    Promise.all([
      settingsApi.get("advanced.min_subtitle_duration"),
      settingsApi.get("advanced.min_trim_duration"),
    ]).then(([ms, mt]) => {
      setMinSubDur(ms.data.value ?? 0.5);
      setMinTrimDur(mt.data.value ?? 2);
    });
  }, []);

  const save = (k: string, v: any) => settingsApi.update(k, v);

  return (
    <div className="space-y-5 stagger-children">
      <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Type className="w-4 h-4 text-primary" />
          "字幕处理"
        </h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              "最短字幕时长 (秒)"
            </label>
            <input type="number" step="0.1"
              className="w-full mt-2 px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none"
              value={minSubDur}
              onChange={(e) => setMinSubDur(+e.target.value)}
              onBlur={() => save("advanced.min_subtitle_duration", minSubDur)}
            />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              "最短裁剪时长 (秒)"
            </label>
            <input type="number" step="0.1"
              className="w-full mt-2 px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none"
              value={minTrimDur}
              onChange={(e) => setMinTrimDur(+e.target.value)}
              onBlur={() => save("advanced.min_trim_duration", minTrimDur)}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

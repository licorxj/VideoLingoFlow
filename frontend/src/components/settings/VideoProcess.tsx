import { useState, useEffect, useCallback, useRef } from "react";
import { Film, Volume2, Music, Gauge } from "lucide-react";
import client from "@/api/client";

const cn = (...classes: (string | boolean | undefined)[]) => classes.filter(Boolean).join(" ");
const inputCls = "w-full mt-2 px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none";
const labelCls = "text-xs font-medium text-muted-foreground uppercase tracking-wider";

const QUALITY_OPTIONS = [
  { label: "原始质量(copy)", value: "copy" },
  { label: "高质量(CRF18)", value: "high" },
  { label: "中等(CRF23)", value: "medium" },
  { label: "低质量(CRF28)", value: "low" },
];

export default function VideoProcess() {
  const [defaultQuality, setDefaultQuality] = useState("medium");
  const [bgmVolume, setBgmVolume] = useState(0.3);
  const [dubVolume, setDubVolume] = useState(0.8);
  const [fadeIn, setFadeIn] = useState(0.5);
  const [fadeOut, setFadeOut] = useState(0.5);
  const [targetLufs, setTargetLufs] = useState(-14);
  const [speedMin, setSpeedMin] = useState(1.0);
  const [speedMax, setSpeedMax] = useState(1.5);
  const [gapThreshold, setGapThreshold] = useState(0.5);
  const [matchVideoSpeed, setMatchVideoSpeed] = useState(false);
  const [slowLimit, setSlowLimit] = useState(0.8);
  const [fastLimit, setFastLimit] = useState(1.2);

  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  useEffect(() => {
    const keys = [
      "video.default_quality",
      "bgm.volume",
      "bgm.dub_volume",
      "bgm.fade_in",
      "bgm.fade_out",
      "video.target_lufs",
      "video.speed.min",
      "video.speed.max",
      "video.speed.gap_threshold",
      "video.speed.match_video_speed",
      "video.speed.slow_limit",
      "video.speed.fast_limit",
    ];
    Promise.all(keys.map((k) => client.get(`/api/settings/${k}`)))
      .then(([q, bv, dv, fi, fo, tl, sm, sx, gt, mv, sl, fl]) => {
        if (q.data?.value) setDefaultQuality(q.data.value);
        if (bv.data?.value !== undefined) setBgmVolume(bv.data.value);
        if (dv.data?.value !== undefined) setDubVolume(dv.data.value);
        if (fi.data?.value !== undefined) setFadeIn(fi.data.value);
        if (fo.data?.value !== undefined) setFadeOut(fo.data.value);
        if (tl.data?.value !== undefined) setTargetLufs(tl.data.value);
        if (sm.data?.value !== undefined) setSpeedMin(sm.data.value);
        if (sx.data?.value !== undefined) setSpeedMax(sx.data.value);
        if (gt.data?.value !== undefined) setGapThreshold(gt.data.value);
        if (mv.data?.value !== undefined) setMatchVideoSpeed(mv.data.value);
        if (sl.data?.value !== undefined) setSlowLimit(sl.data.value);
        if (fl.data?.value !== undefined) setFastLimit(fl.data.value);
      })
      .catch(() => {});
  }, []);

  const save = useCallback((key: string, value: any) => {
    if (timers.current[key]) clearTimeout(timers.current[key]);
    timers.current[key] = setTimeout(() => {
      client.put("/api/settings", { key, value }).catch(() => {});
    }, 400);
  }, []);

  const saveImmediate = useCallback((key: string, value: any) => {
    if (timers.current[key]) clearTimeout(timers.current[key]);
    client.put("/api/settings", { key, value }).catch(() => {});
  }, []);

  return (
    <div className="space-y-4 stagger-children">
      <div className="flex items-center gap-3 mb-2">
        <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
          <Film className="w-5 h-5 text-primary" />
        </div>
        <div>
          <h2 className="text-lg font-bold">视频处理</h2>
          <p className="text-xs text-muted-foreground">视频合成与音频混合的默认参数</p>
        </div>
      </div>

      {/* Quality & Encoding card */}
      <div className="rounded-2xl border border-border/50 bg-card/70 p-4 space-y-3">
        <h3 className="text-xs font-semibold flex items-center gap-1.5">
          <Film className="w-3.5 h-3.5 text-primary" />
          视频质量
        </h3>
        <div>
          <label className={labelCls}>默认视频质量</label>
          <select
            className={cn(inputCls, "appearance-none")}
            value={defaultQuality}
            onChange={(e) => {
              setDefaultQuality(e.target.value);
              saveImmediate("video.default_quality", e.target.value);
            }}
          >
            {QUALITY_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
      </div>

      {/* BGM settings card */}
      <div className="rounded-2xl border border-border/50 bg-card/70 p-4 space-y-3">
        <h3 className="text-xs font-semibold flex items-center gap-1.5">
          <Volume2 className="w-3.5 h-3.5 text-primary" />
          背景音乐设置
        </h3>
        <div>
          <label className={labelCls}>默认 BGM 音量</label>
          <div className="flex items-center gap-3 mt-2">
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={bgmVolume}
              onChange={(e) => {
                const v = +e.target.value;
                setBgmVolume(v);
                save("bgm.volume", v);
              }}
              className="flex-1 h-1.5 accent-primary"
            />
            <span className="text-xs text-muted-foreground w-10 text-right">{bgmVolume.toFixed(2)}</span>
          </div>
        </div>
        <div>
          <label className={labelCls}>默认配音响度</label>
          <div className="flex items-center gap-3 mt-2">
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={dubVolume}
              onChange={(e) => {
                const v = +e.target.value;
                setDubVolume(v);
                save("bgm.dub_volume", v);
              }}
              className="flex-1 h-1.5 accent-primary"
            />
            <span className="text-xs text-muted-foreground w-10 text-right">{dubVolume.toFixed(2)}</span>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>默认淡入时间 (秒)</label>
            <input
              type="number"
              min={0}
              max={10}
              step={0.1}
              className={inputCls}
              value={fadeIn}
              onChange={(e) => setFadeIn(+e.target.value)}
              onBlur={() => save("bgm.fade_in", fadeIn)}
            />
          </div>
          <div>
            <label className={labelCls}>默认淡出时间 (秒)</label>
            <input
              type="number"
              min={0}
              max={10}
              step={0.1}
              className={inputCls}
              value={fadeOut}
              onChange={(e) => setFadeOut(+e.target.value)}
              onBlur={() => save("bgm.fade_out", fadeOut)}
            />
          </div>
        </div>
      </div>

      {/* Dubbing speed range card */}
      <div className="rounded-2xl border border-border/50 bg-card/70 p-4 space-y-3">
        <h3 className="text-xs font-semibold flex items-center gap-1.5">
          <Gauge className="w-3.5 h-3.5 text-primary" />
          配音速度范围
        </h3>
        <p className="text-xs text-muted-foreground">配音时自动调整语速匹配原视频时长</p>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>最小速度</label>
            <input
              type="number"
              step={0.1}
              className={inputCls}
              value={speedMin}
              onChange={(e) => setSpeedMin(+e.target.value)}
              onBlur={() => save("video.speed.min", speedMin)}
            />
          </div>
          <div>
            <label className={labelCls}>最快速度</label>
            <input
              type="number"
              step={0.1}
              className={inputCls}
              value={speedMax}
              onChange={(e) => setSpeedMax(+e.target.value)}
              onBlur={() => save("video.speed.max", speedMax)}
            />
          </div>
        </div>
        <div>
          <label className={labelCls}>句子间隙配音占用阈值</label>
          <div className="flex items-center gap-3 mt-2">
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={gapThreshold}
              onChange={(e) => {
                const v = +e.target.value;
                setGapThreshold(v);
                save("video.speed.gap_threshold", v);
              }}
              className="flex-1 h-1.5 accent-primary"
            />
            <span className="text-xs text-muted-foreground w-10 text-right">{gapThreshold.toFixed(2)}</span>
          </div>
        </div>
        <label className="flex items-center gap-3 cursor-pointer group">
          <div className="relative">
            <input
              type="checkbox"
              checked={matchVideoSpeed}
              onChange={(e) => {
                setMatchVideoSpeed(e.target.checked);
                save("video.speed.match_video_speed", e.target.checked);
              }}
              className="peer sr-only"
            />
            <div className="w-9 h-5 bg-muted rounded-full peer-checked:bg-primary transition-colors duration-200" />
            <div className="absolute left-0.5 top-0.5 w-4 h-4 bg-background rounded-full shadow-sm peer-checked:translate-x-4 transition-transform duration-200" />
          </div>
          <span className="text-sm group-hover:text-foreground transition-colors">
            视频变速匹配配音
          </span>
        </label>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>视频减速限制倍率</label>
            <input
              type="number"
              min={0.5}
              max={1}
              step={0.05}
              className={inputCls}
              value={slowLimit}
              onChange={(e) => setSlowLimit(+e.target.value)}
              onBlur={() => save("video.speed.slow_limit", slowLimit)}
            />
          </div>
          <div>
            <label className={labelCls}>视频加速倍率限制</label>
            <input
              type="number"
              min={1}
              max={2}
              step={0.05}
              className={inputCls}
              value={fastLimit}
              onChange={(e) => setFastLimit(+e.target.value)}
              onBlur={() => save("video.speed.fast_limit", fastLimit)}
            />
          </div>
        </div>
      </div>

      {/* Loudness card */}
      <div className="rounded-2xl border border-border/50 bg-card/70 p-4 space-y-3">
        <h3 className="text-xs font-semibold flex items-center gap-1.5">
          <Music className="w-3.5 h-3.5 text-primary" />
          响度标准化
        </h3>
        <div>
          <label className={labelCls}>响度标准化目标 (LUFS)</label>
          <input
            type="number"
            min={-30}
            max={0}
            step={0.5}
            className={inputCls}
            value={targetLufs}
            onChange={(e) => setTargetLufs(+e.target.value)}
            onBlur={() => save("video.target_lufs", targetLufs)}
          />
          <p className="text-[11px] text-muted-foreground mt-1.5">
            推荐 -14 LUFS（YouTube/流媒体标准），留空则不进行响度标准化
          </p>
        </div>
      </div>
    </div>
  );
}

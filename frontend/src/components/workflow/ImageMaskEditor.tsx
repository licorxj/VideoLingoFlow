import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Pencil, Square, Undo2, Trash2, Upload, X } from "lucide-react";

export interface MaskStroke {
  points: [number, number][];
  size: number;
}
export interface MaskRect {
  x: number;
  y: number;
  w: number;
  h: number;
}
export interface MaskData {
  strokes: MaskStroke[];
  rects: MaskRect[];
  color: string;
  alpha: number;
}

function buildStableFileUrl(filePath: string, taskId?: string, refreshKey?: string | number) {
  const params = new URLSearchParams();
  params.set("path", filePath);
  if (taskId) params.set("task_id", String(taskId));
  if (refreshKey !== undefined && refreshKey !== "") params.set("refresh", String(refreshKey));
  return `/api/files/stream?${params.toString()}`;
}

function useStableFileUrl(filePath: string | null | undefined, taskId?: string | null, refreshKey?: string | number) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!filePath) {
      setUrl(null);
      return;
    }
    setUrl(buildStableFileUrl(filePath, taskId || undefined, refreshKey));
  }, [filePath, taskId, refreshKey]);
  return url;
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  imagePath: string | null;
  taskId?: string | null;
  refreshKey?: string;
  mask: MaskData;
  onChange: (mask: MaskData) => void;
}

type Tool = "brush" | "rect";

const MAX_W = 760;

export function ImageMaskEditor({ open, onOpenChange, imagePath, taskId, refreshKey, mask, onChange }: Props) {
  const upstreamSrc = useStableFileUrl(imagePath, taskId, refreshKey);
  const [localSrc, setLocalSrc] = useState<string | null>(null);
  const imgSrc = localSrc || upstreamSrc;

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const [tool, setTool] = useState<Tool>("brush");
  const [brushSize, setBrushSize] = useState<number>(0.02);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 绘制中的预览数据
  const [drawing, setDrawing] = useState<{
    stroke?: MaskStroke;
    rectStart?: [number, number];
    rect?: MaskRect;
  } | null>(null);

  const color = mask.color || "#ff3b30";
  const alpha = mask.alpha ?? 0.5;

  const displaySize = useCallback(() => {
    if (!natural) return { w: MAX_W, h: MAX_W };
    const scale = Math.min(1, MAX_W / natural.w);
    return { w: Math.round(natural.w * scale), h: Math.round(natural.h * scale) };
  }, [natural]);

  // 加载图片
  useEffect(() => {
    if (!imgSrc) {
      imgRef.current = null;
      setNatural(null);
      return;
    }
    const im = new Image();
    im.onload = () => {
      imgRef.current = im;
      setNatural({ w: im.naturalWidth, h: im.naturalHeight });
    };
    im.src = imgSrc;
  }, [imgSrc]);

  const toNorm = useCallback((e: React.PointerEvent<HTMLCanvasElement>): [number, number] => {
    const canvas = canvasRef.current!;
    const rect = canvas.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    return [Math.max(0, Math.min(1, x)), Math.max(0, Math.min(1, y))];
  }, []);

  // 渲染：原图 + 蒙版叠加
  useEffect(() => {
    const canvas = canvasRef.current;
    const im = imgRef.current;
    if (!canvas) return;
    const { w: cw, h: ch } = displaySize();
    if (canvas.width !== cw || canvas.height !== ch) {
      canvas.width = cw;
      canvas.height = ch;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, cw, ch);
    if (im && natural) {
      ctx.drawImage(im, 0, 0, cw, ch);
    } else {
      ctx.fillStyle = "#1f2937";
      ctx.fillRect(0, 0, cw, ch);
    }

    const drawOverlay = (strokes: MaskStroke[], rects: MaskRect[], a: number) => {
      if (a <= 0) return;
      ctx.globalAlpha = a;
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      const minPx = Math.min(cw, ch);
      for (const r of rects) {
        const x0 = r.x * cw;
        const y0 = r.y * ch;
        ctx.fillRect(x0, y0, r.w * cw, r.h * ch);
      }
      for (const s of strokes) {
        const width = Math.max(1, s.size * 2 * minPx);
        ctx.lineWidth = width;
        const pts = s.points.map((p) => [p[0] * cw, p[1] * ch] as [number, number]);
        if (pts.length === 1) {
          ctx.beginPath();
          ctx.arc(pts[0][0], pts[0][1], width / 2, 0, Math.PI * 2);
          ctx.fill();
        } else {
          ctx.beginPath();
          ctx.moveTo(pts[0][0], pts[0][1]);
          for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
          ctx.stroke();
          for (const p of pts) {
            ctx.beginPath();
            ctx.arc(p[0], p[1], width / 2, 0, Math.PI * 2);
            ctx.fill();
          }
        }
      }
      ctx.globalAlpha = 1;
    };

    drawOverlay(mask.strokes, mask.rects, alpha);
    if (drawing?.stroke) drawOverlay([drawing.stroke], [], alpha);
    if (drawing?.rect) drawOverlay([], [drawing.rect], alpha);
  }, [imgRef.current, natural, displaySize, mask, drawing, color, alpha]);

  const commit = useCallback(
    (next: MaskData) => onChange(next),
    [onChange]
  );

  const onPointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!natural) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    const pt = toNorm(e);
    if (tool === "brush") {
      setDrawing({ stroke: { points: [pt], size: brushSize } });
    } else {
      setDrawing({ rectStart: pt, rect: { x: pt[0], y: pt[1], w: 0, h: 0 } });
    }
  };

  const onPointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!drawing) return;
    const pt = toNorm(e);
    if (drawing.stroke) {
      const last = drawing.stroke.points[drawing.stroke.points.length - 1];
      const dx = pt[0] - last[0];
      const dy = pt[1] - last[1];
      if (dx * dx + dy * dy < 0.000006) return; // 抽稀
      setDrawing({ stroke: { points: [...drawing.stroke.points, pt], size: drawing.stroke.size } });
    } else if (drawing.rectStart) {
      const s = drawing.rectStart;
      const x = Math.min(s[0], pt[0]);
      const y = Math.min(s[1], pt[1]);
      const w = Math.abs(pt[0] - s[0]);
      const h = Math.abs(pt[1] - s[1]);
      setDrawing({ rectStart: s, rect: { x, y, w, h } });
    }
  };

  const onPointerUp = () => {
    if (!drawing) return;
    if (drawing.stroke && drawing.stroke.points.length >= 1) {
      commit({ ...mask, strokes: [...mask.strokes, drawing.stroke] });
    } else if (drawing.rect && drawing.rect.w > 0.004 && drawing.rect.h > 0.004) {
      commit({ ...mask, rects: [...mask.rects, drawing.rect] });
    }
    setDrawing(null);
  };

  const undo = () => {
    if (mask.strokes.length > 0) {
      commit({ ...mask, strokes: mask.strokes.slice(0, -1) });
    } else if (mask.rects.length > 0) {
      commit({ ...mask, rects: mask.rects.slice(0, -1) });
    }
  };

  const clearAll = () => commit({ ...mask, strokes: [], rects: [] });

  const onLocalFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (localSrc) URL.revokeObjectURL(localSrc);
    setLocalSrc(URL.createObjectURL(f));
  };

  const { w: cw, h: ch } = displaySize();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[860px] w-[92vw]">
        <DialogHeader>
          <DialogTitle>绘制图片蒙版</DialogTitle>
          <DialogDescription>
            使用画笔或矩形在图片上标注蒙版区域，绘制结果会传给后端合成蒙版。
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant={tool === "brush" ? "default" : "outline"}
              onClick={() => setTool("brush")}
            >
              <Pencil className="h-4 w-4 mr-1" /> 画笔
            </Button>
            <Button
              size="sm"
              variant={tool === "rect" ? "default" : "outline"}
              onClick={() => setTool("rect")}
            >
              <Square className="h-4 w-4 mr-1" /> 矩形
            </Button>
            <div className="flex items-center gap-2 text-xs">
              <span>笔刷</span>
              <input
                type="range"
                min={0.005}
                max={0.12}
                step={0.005}
                value={brushSize}
                onChange={(e) => setBrushSize(Number(e.target.value))}
                className="w-28"
              />
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span>颜色</span>
              <input
                type="color"
                value={color}
                onChange={(e) => commit({ ...mask, color: e.target.value })}
                className="h-7 w-9 rounded border bg-transparent"
              />
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span>透明度</span>
              <input
                type="range"
                min={0.1}
                max={1}
                step={0.05}
                value={alpha}
                onChange={(e) => commit({ ...mask, alpha: Number(e.target.value) })}
                className="w-24"
              />
            </div>
            <Button size="sm" variant="ghost" onClick={undo}>
              <Undo2 className="h-4 w-4 mr-1" /> 撤销
            </Button>
            <Button size="sm" variant="ghost" onClick={clearAll}>
              <Trash2 className="h-4 w-4 mr-1" /> 清空
            </Button>
            <Button size="sm" variant="ghost" onClick={() => fileInputRef.current?.click()}>
              <Upload className="h-4 w-4 mr-1" /> 本地图片
            </Button>
            <input ref={fileInputRef} type="file" accept="image/*" hidden onChange={onLocalFile} />
            <span className="text-xs text-muted-foreground ml-auto">
              笔 {mask.strokes.length} · 框 {mask.rects.length}
            </span>
          </div>

          <div className="rounded-md border bg-black/40 flex items-center justify-center overflow-auto" style={{ maxHeight: 520 }}>
            {imgSrc ? (
              <canvas
                ref={canvasRef}
                width={cw}
                height={ch}
                style={{ width: cw, height: ch, touchAction: "none", cursor: tool === "brush" ? "crosshair" : "cell" }}
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onPointerLeave={onPointerUp}
              />
            ) : (
              <div className="text-xs text-muted-foreground p-10 text-center">
                尚未获取图片，请先连接上游图片输入，或点击「本地图片」加载一张图片用于绘制。
              </div>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            <X className="h-4 w-4 mr-1" /> 完成
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

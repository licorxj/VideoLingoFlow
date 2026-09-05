import {
  getNodeTypeDef, CATEGORIES,
  type Workflow, type PortDef,
} from "@/lib/workflowTypes";

/**
 * 程序化 Canvas 渲染分享附图（不依赖 DOM 截图，稳定且高清）：
 *  - renderNodeCard       → 渲染「节点卡片」模样（1280x720）
 *  - renderWorkflowGraph  → 按工作流节点坐标渲染「全貌图」（尺寸按内容自适应）
 */

const RATIO = 2; // 2x 像素比，高清

function makeCanvas(w: number, h: number): { canvas: HTMLCanvasElement; ctx: CanvasRenderingContext2D } | null {
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(w * RATIO));
  canvas.height = Math.max(1, Math.round(h * RATIO));
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.scale(RATIO, RATIO);
  return { canvas, ctx };
}

export async function canvasToBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("canvas 导出 PNG 失败"))), "image/png");
  });
}

function roundedRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  const rr = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.arcTo(x + w, y, x + w, y + h, rr);
  ctx.arcTo(x + w, y + h, x, y + h, rr);
  ctx.arcTo(x, y + h, x, y, rr);
  ctx.arcTo(x, y, x + w, y, rr);
  ctx.closePath();
}

function wrapText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string[] {
  const lines: string[] = [];
  let line = "";
  for (const ch of Array.from(String(text))) {
    if (ctx.measureText(line + ch).width > maxWidth && line) {
      lines.push(line);
      line = ch;
    } else {
      line += ch;
    }
  }
  if (line) lines.push(line);
  return lines;
}

function ellipseText(text: string, max: number): string {
  const t = String(text || "");
  return t.length > max ? t.slice(0, max - 1) + "…" : t;
}

/* ================================================================ */
/* 节点卡片（1280x720 分享附图）                                       */
/* ================================================================ */
export interface NodeCardData {
  id?: string;
  name?: string;
  version?: string;
  category?: string;
  color?: string;
  description?: string;
  icon?: string;
  inputs?: unknown[];
  outputs?: unknown[];
}

export async function renderNodeCard(node?: NodeCardData): Promise<Blob | null> {
  const W = 1280, H = 720;
  const made = makeCanvas(W, H);
  if (!made) return null;
  const { canvas, ctx } = made;

  // 深色渐变背景
  const grad = ctx.createLinearGradient(0, 0, W, H);
  grad.addColorStop(0, "#1e293b");
  grad.addColorStop(1, "#0f172a");
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, W, H);

  const color = node?.color || "#6366f1";
  const category = String(node?.category || "");
  const catMeta = (CATEGORIES as Record<string, { label: string }>)[category];
  const catLabel = catMeta?.label || category || "NODE";
  const name = String(node?.name || "Node");
  const desc = String(node?.description || "");
  const version = String(node?.version || "1.0.0");
  const inputs = Array.isArray(node?.inputs) ? (node!.inputs as PortDef[]) : [];
  const outputs = Array.isArray(node?.outputs) ? (node!.outputs as PortDef[]) : [];
  const initials = (name.slice(0, 2) || "N").toUpperCase();

  /* 顶部：分类徽章（左）+ 版本徽章（右） */
  ctx.font = "700 20px system-ui, sans-serif";
  ctx.textBaseline = "middle";
  ctx.textAlign = "center";
  ctx.fillStyle = color;
  roundedRect(ctx, 64, 44, 216, 46, 14);
  ctx.fill();
  ctx.fillStyle = "#fff";
  ctx.fillText(catLabel.toUpperCase(), 64 + 108, 44 + 23);

  const versionText = "v" + version;
  ctx.textAlign = "right";
  ctx.fillStyle = "rgba(148,163,184,0.9)";
  ctx.fillText(versionText, W - 64, 67);

  /* 中央：图标圆块 + 名称 + 分类 */
  const iconCX = W / 2, iconCY = 218, iconR = 72;
  ctx.fillStyle = color + "26";
  roundedRect(ctx, iconCX - iconR, iconCY - iconR, iconR * 2, iconR * 2, 32);
  ctx.fill();
  ctx.strokeStyle = color + "66";
  ctx.lineWidth = 2;
  roundedRect(ctx, iconCX - iconR, iconCY - iconR, iconR * 2, iconR * 2, 32);
  ctx.stroke();
  ctx.fillStyle = color;
  ctx.font = "800 54px system-ui, sans-serif";
  ctx.textAlign = "center";
  ctx.fillText(initials, iconCX, iconCY + 2);

  ctx.fillStyle = "#f8fafc";
  ctx.font = "700 48px system-ui, sans-serif";
  ctx.fillText(ellipseText(name, 26), iconCX, 340);

  ctx.fillStyle = color;
  ctx.font = "600 20px system-ui, sans-serif";
  ctx.fillText(catLabel.toUpperCase(), iconCX, 386);

  /* 描述（最多两行） */
  if (desc) {
    ctx.font = "22px system-ui, sans-serif";
    ctx.fillStyle = "#94a3b8";
    ctx.textAlign = "center";
    const lines = wrapText(ctx, desc, 980).slice(0, 2);
    let y = 440;
    for (const line of lines) {
      ctx.fillText(line, iconCX, y);
      y += 30;
    }
  }

  /* 底部：输入（左） / 输出（右） */
  const listY = 540;
  const listX = 120;
  const rightX = W - 120;
  ctx.font = "600 18px system-ui, sans-serif";
  ctx.textAlign = "left";
  ctx.fillStyle = "#cbd5e1";
  ctx.fillText("输入", listX, listY - 34);
  ctx.textAlign = "right";
  ctx.fillText("输出", rightX, listY - 34);

  const drawPorts = (ports: PortDef[], x: number, align: "left" | "right") => {
    ctx.font = "18px system-ui, sans-serif";
    ctx.textAlign = align;
    const shown = ports.slice(0, 4);
    shown.forEach((p, i) => {
      const y = listY + i * 34;
      const pcolor = p.color || "#6b7280";
      const label = String(p.label || p.id || "port");
      if (align === "left") {
        ctx.fillStyle = pcolor;
        ctx.beginPath();
        ctx.arc(x + 8, y, 7, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "#cbd5e1";
        ctx.fillText(ellipseText(label, 14), x + 26, y);
      } else {
        ctx.fillStyle = pcolor;
        ctx.beginPath();
        ctx.arc(x - 8, y, 7, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "#cbd5e1";
        ctx.fillText(ellipseText(label, 14), x - 26, y);
      }
    });
    if (ports.length > 4) {
      ctx.fillStyle = "#94a3b8";
      ctx.fillText(`+${ports.length - 4}`, align === "left" ? x + 26 : x - 26, listY + 4 * 34);
    }
    if (ports.length === 0) {
      ctx.fillStyle = "#64748b";
      ctx.fillText("—", x, listY);
    }
  };

  drawPorts(inputs, listX, "left");
  drawPorts(outputs, rightX, "right");

  return canvasToBlob(canvas);
}

/* ================================================================ */
/* 工作流全貌图（按节点坐标渲染，尺寸自适应）                              */
/* ================================================================ */
const NODE_W = 224;
const NODE_H = 92;
const GAP_X = 72;
const GAP_Y = 64;
const PAD = 70;
const MAX_OUT_W = 1680;
const MAX_OUT_H = 2100;

interface LayoutNode {
  id: string;
  label: string;
  nodeType: string;
  color: string;
  x: number;
  y: number;
}

function buildLayout(workflow?: Workflow): LayoutNode[] {
  const raw = Array.isArray(workflow?.nodes) ? workflow.nodes : [];
  const nodes: LayoutNode[] = raw
    .filter((n) => n && typeof n === "object")
    .map((n, i) => {
      const def = getNodeTypeDef(String((n.data as any)?.nodeType || ""));
      const pos = ((n as any).position || {}) as { x?: number; y?: number };
      const hasPos = typeof pos.x === "number" && typeof pos.y === "number";
      return {
        id: String((n as any).id || `n${i}`),
        label: String((n.data as any)?.label || (n.data as any)?.nodeType || "节点"),
        nodeType: String((n.data as any)?.nodeType || ""),
        color: def?.color || "#6366f1",
        x: hasPos ? (pos.x as number) : NaN,
        y: hasPos ? (pos.y as number) : NaN,
      };
    });

  const anyPos = nodes.some((n) => !Number.isNaN(n.x));
  if (!anyPos) {
    // 无坐标 → 自动网格布局（每行 4 个）
    nodes.forEach((n, i) => {
      n.x = (i % 4) * (NODE_W + GAP_X);
      n.y = Math.floor(i / 4) * (NODE_H + GAP_Y);
    });
  } else {
    let maxX = 0;
    let auto = 0;
    for (const n of nodes) if (!Number.isNaN(n.x)) maxX = Math.max(maxX, n.x);
    for (const n of nodes) {
      if (Number.isNaN(n.x)) {
        n.x = maxX + NODE_W + GAP_X + (auto % 4) * (NODE_W + GAP_X);
        n.y = Math.floor(auto / 4) * (NODE_H + GAP_Y);
        auto++;
      }
    }
  }
  return nodes;
}

export async function renderWorkflowGraph(workflow?: Workflow): Promise<Blob | null> {
  const nodes = buildLayout(workflow);
  const edges = Array.isArray(workflow?.edges) ? workflow.edges : [];

  // 画布尺寸：节点包围盒 + 内边距
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  if (nodes.length === 0) {
    minX = 0; minY = 0; maxX = NODE_W; maxY = NODE_H;
  } else {
    for (const n of nodes) {
      minX = Math.min(minX, n.x);
      minY = Math.min(minY, n.y);
      maxX = Math.max(maxX, n.x + NODE_W);
      maxY = Math.max(maxY, n.y + NODE_H);
    }
  }
  const bw = maxX - minX + PAD * 2;
  const bh = maxY - minY + PAD * 2;
  const scale = Math.min(1, MAX_OUT_W / bw, MAX_OUT_H / bh);
  const W = Math.round(bw * scale);
  const H = Math.round(bh * scale);
  const offX = -minX + PAD;
  const offY = -minY + PAD;
  const S = scale;

  const made = makeCanvas(W, H);
  if (!made) return null;
  const { canvas, ctx } = made;

  // 背景
  const bg = ctx.createLinearGradient(0, 0, W, H);
  bg.addColorStop(0, "#1e293b");
  bg.addColorStop(1, "#0f172a");
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, W, H);

  const nodeMap = new Map(nodes.map((n) => [n.id, n]));
  ctx.lineCap = "round";

  /* 边：贝塞尔曲线 + 箭头 */
  for (const e of edges) {
    const src = nodeMap.get(String((e as any).source || ""));
    const tgt = nodeMap.get(String((e as any).target || ""));
    if (!src || !tgt) continue;
    const x1 = (src.x + NODE_W / 2) * S + offX * S;
    const y1 = (src.y + NODE_H) * S + offY * S;
    const x2 = (tgt.x + NODE_W / 2) * S + offX * S;
    const y2 = tgt.y * S + offY * S;
    const dy = Math.max(40, (y2 - y1) * 0.5);
    ctx.strokeStyle = "rgba(148,163,184,0.85)";
    ctx.lineWidth = 2.5 * S;
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.bezierCurveTo(x1, y1 + dy, x2, y2 - dy, x2, y2);
    ctx.stroke();
    // 箭头：指向目标节点（顶点朝下进入目标）
    const arrowR = 9 * S;
    ctx.fillStyle = "rgba(148,163,184,0.9)";
    ctx.beginPath();
    ctx.moveTo(x2, y2);
    ctx.lineTo(x2 - arrowR * 0.6, y2 - arrowR);
    ctx.lineTo(x2 + arrowR * 0.6, y2 - arrowR);
    ctx.closePath();
    ctx.fill();
  }

  /* 节点：圆角矩形 + 顶部色条 + 名称 */
  ctx.textBaseline = "middle";
  for (const n of nodes) {
    const x = n.x * S + offX * S;
    const y = n.y * S + offY * S;
    const w = NODE_W * S;
    const h = NODE_H * S;

    ctx.fillStyle = "rgba(15,23,42,0.92)";
    ctx.strokeStyle = n.color;
    ctx.lineWidth = 2 * S;
    roundedRect(ctx, x, y, w, h, 14 * S);
    ctx.fill();
    ctx.stroke();

    // 顶部色条
    ctx.fillStyle = n.color;
    roundedRect(ctx, x, y, w, 8 * S, 14 * S);
    ctx.fill();
    ctx.fillRect(x, y + 5 * S, w, 3 * S);

    // 类型色点 + 名称
    ctx.fillStyle = n.color;
    ctx.beginPath();
    ctx.arc(x + 26 * S, y + h / 2, 7 * S, 0, Math.PI * 2);
    ctx.fill();

    ctx.textAlign = "left";
    ctx.fillStyle = "#f8fafc";
    ctx.font = `700 ${Math.max(13, 17 * S)}px system-ui, sans-serif`;
    const nameMax = (w - 54 * S) / Math.max(0.4, 1);
    ctx.fillText(ellipseText(n.label, Math.max(8, Math.floor(nameMax / (8 * S)))), x + 44 * S, y + 34 * S);

    ctx.fillStyle = "#94a3b8";
    ctx.font = `${Math.max(10, 12 * S)}px system-ui, sans-serif`;
    ctx.fillText(ellipseText(n.nodeType || "node", 20), x + 44 * S, y + 62 * S);
  }

  return canvasToBlob(canvas);
}

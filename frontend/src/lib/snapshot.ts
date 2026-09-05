import { toPng } from "html-to-image";
import type { Workflow } from "@/lib/workflowTypes";
import { renderNodeCard, renderWorkflowGraph, type NodeCardData } from "@/lib/canvasPreview";

export function previewFileFromBlob(blob: Blob, name: string): File {
  return new File([blob], name, { type: blob.type || "image/png" });
}

async function blobToFileOrNull(blob: Blob | null, name: string): Promise<File | null> {
  return blob ? previewFileFromBlob(blob, name) : null;
}

/**
 * 节点卡片快照：用 Canvas 程序化渲染「节点卡片」模样（分类色/图标/名称/输入输出），
 * 高清稳定，不依赖 DOM 截图。
 */
export async function captureNodeCard(nodeType?: NodeCardData): Promise<File | null> {
  const blob = await renderNodeCard(nodeType).catch(() => null);
  return blobToFileOrNull(blob, "preview.png");
}

/**
 * 工作流全貌快照：按工作流节点坐标在 Canvas 上渲染全貌高清图（节点 + 连线），
 * 在无画布环境下（如共享社区「分析我的资源」）也能生成。
 */
export async function captureWorkflowCard(workflow?: Workflow): Promise<File | null> {
  const blob = await renderWorkflowGraph(workflow).catch(() => null);
  return blobToFileOrNull(blob, "workflow-preview.png");
}

/**
 * 工作流画布快照（工作流编辑器内）：优先用 ReactFlow 实例内置 toObjectURL 导出
 * 全画布高清 PNG；实例不可用时回退到对 .react-flow 容器做 html-to-image 截屏。
 */
export async function captureWorkflowCanvas(rfInstance: any): Promise<File | null> {
  try {
    if (rfInstance && typeof rfInstance.toObjectURL === "function") {
      const dataUrl = await rfInstance.toObjectURL({
        width: 1280,
        height: 720,
        backgroundColor: "#0f172a",
      });
      const blob = await (await fetch(dataUrl)).blob();
      return previewFileFromBlob(blob, "workflow-preview.png");
    }
  } catch {
    /* 回退 */
  }
  try {
    const el = document.querySelector<HTMLElement>(".react-flow");
    if (el) {
      const dataUrl = await toPng(el, {
        width: el.offsetWidth || 1280,
        height: el.offsetHeight || 720,
        backgroundColor: "#0f172a",
        pixelRatio: 2,
      });
      const blob = await (await fetch(dataUrl)).blob();
      return previewFileFromBlob(blob, "workflow-preview.png");
    }
  } catch {
    /* 忽略 */
  }
  return null;
}

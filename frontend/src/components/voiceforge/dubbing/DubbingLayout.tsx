import React, { useCallback, useRef, useState } from "react";

/* ── Constants ─────────────────────────────────────────────────────── */

const LEFT_DEFAULT = 260;
const LEFT_MIN = 200;
const LEFT_MAX = 400;

const RIGHT_DEFAULT = 300;
const RIGHT_MIN = 240;
const RIGHT_MAX = 450;

const CENTER_MIN = 400;

const HANDLE_WIDTH = 4;

/* ── Types ─────────────────────────────────────────────────────────── */

interface DubbingLayoutProps {
  left: React.ReactNode;
  center: React.ReactNode;
  right: React.ReactNode;
}

type DragSide = "left" | "right" | null;

/* ── Component ─────────────────────────────────────────────────────── */

export function DubbingLayout({ left, center, right }: DubbingLayoutProps) {
  const [leftWidth, setLeftWidth] = useState(LEFT_DEFAULT);
  const [rightWidth, setRightWidth] = useState(RIGHT_DEFAULT);
  const dragRef = useRef<{
    side: DragSide;
    startX: number;
    startWidth: number;
  } | null>(null);

  /* ── Drag handlers ──────────────────────────────────────────────── */

  const onMouseDown = useCallback(
    (side: DragSide) => (e: React.MouseEvent) => {
      e.preventDefault();
      const startX = e.clientX;
      const startWidth = side === "left" ? leftWidth : rightWidth;

      dragRef.current = { side, startX, startWidth };
      document.body.style.userSelect = "none";
      document.body.style.cursor = "col-resize";
    },
    [leftWidth, rightWidth],
  );

  const onMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (!dragRef.current) return;

      const { side, startX, startWidth } = dragRef.current;
      const delta = e.clientX - startX;

      if (side === "left") {
        const next = Math.min(LEFT_MAX, Math.max(LEFT_MIN, startWidth + delta));
        setLeftWidth(next);
      } else {
        const next = Math.min(RIGHT_MAX, Math.max(RIGHT_MIN, startWidth - delta));
        setRightWidth(next);
      }
    },
    [],
  );

  const onMouseUp = useCallback(() => {
    dragRef.current = null;
    document.body.style.userSelect = "";
    document.body.style.cursor = "";
  }, []);

  return (
    <div
      className="flex h-full min-h-0 w-full overflow-hidden"
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      onMouseLeave={onMouseUp}
    >
      {/* ── Left panel ──────────────────────────────────────────── */}
      <div
        className="flex-shrink-0 overflow-y-auto border-r border-border/60 bg-card"
        style={{ width: leftWidth }}
      >
        {left}
      </div>

      {/* ── Left drag handle ────────────────────────────────────── */}
      <DragHandle side="left" onMouseDown={onMouseDown} />

      {/* ── Center panel ────────────────────────────────────────── */}
      <div
        className="min-w-0 flex-1 overflow-y-auto"
        style={{ minWidth: CENTER_MIN }}
      >
        {center}
      </div>

      {/* ── Right drag handle ───────────────────────────────────── */}
      <DragHandle side="right" onMouseDown={onMouseDown} />

      {/* ── Right panel ─────────────────────────────────────────── */}
      <div
        className="flex-shrink-0 overflow-y-auto border-l border-border/60 bg-card"
        style={{ width: rightWidth }}
      >
        {right}
      </div>
    </div>
  );
}

/* ── Drag Handle ───────────────────────────────────────────────────── */

interface DragHandleProps {
  side: "left" | "right";
  onMouseDown: (side: "left" | "right") => (e: React.MouseEvent) => void;
}

function DragHandle({ side, onMouseDown }: DragHandleProps) {
  return (
    <div
      className="group relative flex-shrink-0 cursor-col-resize"
      style={{ width: HANDLE_WIDTH }}
      onMouseDown={onMouseDown(side)}
    >
      {/* Visible thin bar */}
      <div className="absolute inset-y-0 left-1/2 -translate-x-1/2 w-px bg-border/40 transition-colors group-hover:bg-[#6c5ce7]" />

      {/* Hover hit-area (wider than the visual bar for easier grabbing) */}
      <div className="absolute inset-y-0 left-0 right-0 z-10" />
    </div>
  );
}

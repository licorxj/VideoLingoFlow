# Mobile Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a full mobile editing experience to the editor page with an independent component tree, sharing EditorCore and stores with the desktop layout.

**Architecture:** Branch on `useIsMobile()` in the editor page to render either `MobileEditorLayout` or the existing desktop layout. Mobile components live in `components/editor/mobile/`. Touch gestures use native Touch API (no new dependencies). Drawers use the existing `vaul` Drawer component.

**Tech Stack:** React 19, Zustand, vaul Drawer, native Touch API, Tailwind CSS

---

## File Structure

```
apps/web/src/components/editor/mobile/
├── mobile-editor-layout.tsx         # Root mobile layout (preview + timeline + toolbar)
├── mobile-header.tsx                # Top bar (back, name, undo/redo, menu)
├── mobile-preview.tsx               # Preview canvas with touch overlay
├── mobile-timeline/
│   ├── mobile-timeline.tsx          # Timeline container (horizontal scroll, centered playhead)
│   ├── mobile-track.tsx             # Single track renderer (48px height)
│   ├── mobile-playhead.tsx          # Fixed-center playhead
│   └── mobile-timeline-gestures.tsx # Pinch-zoom + pan gesture layer
├── mobile-toolbar.tsx               # Bottom tab bar (assets, text, sticker, audio, AI)
├── mobile-drawer/
│   ├── mobile-assets-drawer.tsx     # Assets drawer (reuses desktop asset views)
│   ├── mobile-properties-drawer.tsx # Properties drawer (reuses desktop property components)
│   ├── mobile-text-drawer.tsx       # Text tool drawer
│   ├── mobile-sticker-drawer.tsx    # Sticker tool drawer
│   ├── mobile-audio-drawer.tsx      # Audio tool drawer
│   └── mobile-ai-drawer.tsx         # AI agent drawer
└── hooks/
    ├── use-touch-gestures.ts        # Generic touch gesture hook (pan, pinch, longpress, doubletap, rotate)
    ├── use-timeline-scroll.ts       # Timeline-specific scroll + zoom state
    └── use-mobile-drawer.ts         # Drawer open/close state (mutually exclusive)
```

**Modified files:**
- `apps/web/src/app/[locale]/editor/[project_id]/page.tsx` — add mobile branch
- `apps/web/src/app/layout.tsx` — add `viewport-fit=cover` meta tag

---

### Task 1: Touch Gesture Hook

**Files:**
- Create: `apps/web/src/components/editor/mobile/hooks/use-touch-gestures.ts`

This is the foundation — all mobile timeline and preview interactions depend on it.

- [ ] **Step 1: Create the touch gesture hook**

```typescript
// apps/web/src/components/editor/mobile/hooks/use-touch-gestures.ts
"use client";

import { useRef, useEffect, useCallback } from "react";

interface TouchGestureHandlers {
	onPan?: ({ deltaX, deltaY }: { deltaX: number; deltaY: number }) => void;
	onPinch?: ({ scale, centerX, centerY }: { scale: number; centerX: number; centerY: number }) => void;
	onLongPress?: ({ x, y }: { x: number; y: number }) => void;
	onDoubleTap?: ({ x, y }: { x: number; y: number }) => void;
	onTap?: ({ x, y }: { x: number; y: number }) => void;
	onRotate?: ({ angle }: { angle: number }) => void;
	longPressThreshold?: number;
	doubleTapInterval?: number;
}

interface TouchState {
	startTouches: Touch[];
	lastTapTime: number;
	longPressTimer: ReturnType<typeof setTimeout> | null;
	initialPinchDistance: number | null;
	initialAngle: number | null;
	isPanning: boolean;
	lastPanX: number;
	lastPanY: number;
}

function getDistance({ touchA, touchB }: { touchA: Touch; touchB: Touch }): number {
	const dx = touchA.clientX - touchB.clientX;
	const dy = touchA.clientY - touchB.clientY;
	return Math.sqrt(dx * dx + dy * dy);
}

function getAngle({ touchA, touchB }: { touchA: Touch; touchB: Touch }): number {
	return Math.atan2(
		touchB.clientY - touchA.clientY,
		touchB.clientX - touchA.clientX,
	);
}

export function useTouchGestures({
	ref,
	handlers,
}: {
	ref: React.RefObject<HTMLElement | null>;
	handlers: TouchGestureHandlers;
}) {
	const stateRef = useRef<TouchState>({
		startTouches: [],
		lastTapTime: 0,
		longPressTimer: null,
		initialPinchDistance: null,
		initialAngle: null,
		isPanning: false,
		lastPanX: 0,
		lastPanY: 0,
	});

	const handlersRef = useRef(handlers);
	handlersRef.current = handlers;

	const clearLongPress = useCallback(() => {
		const state = stateRef.current;
		if (state.longPressTimer) {
			clearTimeout(state.longPressTimer);
			state.longPressTimer = null;
		}
	}, []);

	useEffect(() => {
		const el = ref.current;
		if (!el) return;

		const threshold = handlersRef.current.longPressThreshold ?? 300;
		const doubleTapInterval = handlersRef.current.doubleTapInterval ?? 300;

		const onTouchStart = (e: TouchEvent) => {
			const state = stateRef.current;
			state.startTouches = Array.from(e.touches);

			if (e.touches.length === 1) {
				const touch = e.touches[0];
				state.lastPanX = touch.clientX;
				state.lastPanY = touch.clientY;
				state.isPanning = false;

				clearLongPress();
				state.longPressTimer = setTimeout(() => {
					if (!state.isPanning) {
						handlersRef.current.onLongPress?.({ x: touch.clientX, y: touch.clientY });
					}
				}, threshold);
			}

			if (e.touches.length === 2) {
				clearLongPress();
				state.initialPinchDistance = getDistance({
					touchA: e.touches[0],
					touchB: e.touches[1],
				});
				state.initialAngle = getAngle({
					touchA: e.touches[0],
					touchB: e.touches[1],
				});
			}
		};

		const onTouchMove = (e: TouchEvent) => {
			const state = stateRef.current;

			if (e.touches.length === 1 && handlersRef.current.onPan) {
				const touch = e.touches[0];
				const deltaX = touch.clientX - state.lastPanX;
				const deltaY = touch.clientY - state.lastPanY;

				if (Math.abs(deltaX) > 2 || Math.abs(deltaY) > 2) {
					state.isPanning = true;
					clearLongPress();
				}

				if (state.isPanning) {
					handlersRef.current.onPan({ deltaX, deltaY });
					state.lastPanX = touch.clientX;
					state.lastPanY = touch.clientY;
				}
			}

			if (e.touches.length === 2) {
				const currentDistance = getDistance({
					touchA: e.touches[0],
					touchB: e.touches[1],
				});

				if (state.initialPinchDistance && handlersRef.current.onPinch) {
					const scale = currentDistance / state.initialPinchDistance;
					const centerX = (e.touches[0].clientX + e.touches[1].clientX) / 2;
					const centerY = (e.touches[0].clientY + e.touches[1].clientY) / 2;
					handlersRef.current.onPinch({ scale, centerX, centerY });
				}

				if (state.initialAngle != null && handlersRef.current.onRotate) {
					const currentAngle = getAngle({
						touchA: e.touches[0],
						touchB: e.touches[1],
					});
					const angle = currentAngle - state.initialAngle;
					handlersRef.current.onRotate({ angle });
				}
			}
		};

		const onTouchEnd = (e: TouchEvent) => {
			const state = stateRef.current;
			clearLongPress();

			if (e.touches.length === 0 && !state.isPanning && state.startTouches.length === 1) {
				const touch = state.startTouches[0];
				const now = Date.now();

				if (now - state.lastTapTime < doubleTapInterval) {
					handlersRef.current.onDoubleTap?.({ x: touch.clientX, y: touch.clientY });
					state.lastTapTime = 0;
				} else {
					handlersRef.current.onTap?.({ x: touch.clientX, y: touch.clientY });
					state.lastTapTime = now;
				}
			}

			state.initialPinchDistance = null;
			state.initialAngle = null;
			state.isPanning = false;
		};

		el.addEventListener("touchstart", onTouchStart, { passive: true });
		el.addEventListener("touchmove", onTouchMove, { passive: true });
		el.addEventListener("touchend", onTouchEnd, { passive: true });

		return () => {
			clearLongPress();
			el.removeEventListener("touchstart", onTouchStart);
			el.removeEventListener("touchmove", onTouchMove);
			el.removeEventListener("touchend", onTouchEnd);
		};
	}, [ref, clearLongPress]);
}
```

- [ ] **Step 2: Commit**

```bash
git add apps/web/src/components/editor/mobile/hooks/use-touch-gestures.ts
git commit -m "feat(mobile): add touch gesture hook (pan, pinch, longpress, doubletap, rotate)"
```

---

### Task 2: Mobile Drawer State Hook

**Files:**
- Create: `apps/web/src/components/editor/mobile/hooks/use-mobile-drawer.ts`

Manages which drawer is open. Only one drawer at a time (mutually exclusive).

- [ ] **Step 1: Create the drawer state hook**

```typescript
// apps/web/src/components/editor/mobile/hooks/use-mobile-drawer.ts
"use client";

import { create } from "zustand";

type MobileDrawerType =
	| "assets"
	| "text"
	| "sticker"
	| "audio"
	| "ai"
	| "properties"
	| null;

interface MobileDrawerState {
	activeDrawer: MobileDrawerType;
	openDrawer: ({ drawer }: { drawer: MobileDrawerType }) => void;
	closeDrawer: () => void;
	toggleDrawer: ({ drawer }: { drawer: NonNullable<MobileDrawerType> }) => void;
}

export const useMobileDrawerStore = create<MobileDrawerState>((set, get) => ({
	activeDrawer: null,
	openDrawer: ({ drawer }) => set({ activeDrawer: drawer }),
	closeDrawer: () => set({ activeDrawer: null }),
	toggleDrawer: ({ drawer }) => {
		const current = get().activeDrawer;
		set({ activeDrawer: current === drawer ? null : drawer });
	},
}));
```

- [ ] **Step 2: Commit**

```bash
git add apps/web/src/components/editor/mobile/hooks/use-mobile-drawer.ts
git commit -m "feat(mobile): add mobile drawer state management"
```

---

### Task 3: Mobile Header

**Files:**
- Create: `apps/web/src/components/editor/mobile/mobile-header.tsx`

Top bar with back button, project name, undo/redo, and overflow menu.

- [ ] **Step 1: Create mobile header component**

```tsx
// apps/web/src/components/editor/mobile/mobile-header.tsx
"use client";

import { Button } from "@/components/ui/button";
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useEditor } from "@/hooks/use-editor";
import { useRouter } from "@/lib/navigation";
import { useTranslation } from "@i18next-toolkit/nextjs-approuter";
import {
	ArrowLeft02Icon,
	MoreHorizontalIcon,
	ArrowTurnBackwardIcon,
	ArrowTurnForwardIcon,
	Download04Icon,
	Settings01Icon,
	Expand01Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { toast } from "sonner";

export function MobileHeader() {
	const { t } = useTranslation();
	const editor = useEditor();
	const router = useRouter();
	const activeProject = editor.project.getActive();
	const projectName = activeProject?.metadata.name || "";

	const handleBack = async () => {
		try {
			await editor.project.prepareExit();
			editor.project.closeProject();
		} catch {
			editor.project.closeProject();
		} finally {
			router.push("/projects");
		}
	};

	const handleUndo = () => {
		editor.command.undo();
	};

	const handleRedo = () => {
		editor.command.redo();
	};

	return (
		<header
			className="bg-background flex h-11 items-center justify-between px-2 pt-[env(safe-area-inset-top)]"
		>
			<div className="flex items-center gap-1">
				<Button
					type="button"
					variant="ghost"
					size="icon"
					className="size-9"
					onClick={handleBack}
					onKeyDown={(e) => { if (e.key === "Enter") handleBack(); }}
				>
					<HugeiconsIcon icon={ArrowLeft02Icon} className="size-5" />
				</Button>
				<span className="max-w-[140px] truncate text-sm font-medium">
					{projectName}
				</span>
			</div>

			<div className="flex items-center gap-1">
				<Button
					type="button"
					variant="ghost"
					size="icon"
					className="size-9"
					onClick={handleUndo}
					onKeyDown={(e) => { if (e.key === "Enter") handleUndo(); }}
					title={t("Undo")}
				>
					<HugeiconsIcon icon={ArrowTurnBackwardIcon} className="size-4" />
				</Button>
				<Button
					type="button"
					variant="ghost"
					size="icon"
					className="size-9"
					onClick={handleRedo}
					onKeyDown={(e) => { if (e.key === "Enter") handleRedo(); }}
					title={t("Redo")}
				>
					<HugeiconsIcon icon={ArrowTurnForwardIcon} className="size-4" />
				</Button>

				<DropdownMenu>
					<DropdownMenuTrigger asChild>
						<Button type="button" variant="ghost" size="icon" className="size-9">
							<HugeiconsIcon icon={MoreHorizontalIcon} className="size-5" />
						</Button>
					</DropdownMenuTrigger>
					<DropdownMenuContent align="end" className="w-44">
						<DropdownMenuItem className="flex items-center gap-2">
							<HugeiconsIcon icon={Download04Icon} className="size-4" />
							{t("Export")}
						</DropdownMenuItem>
						<DropdownMenuItem className="flex items-center gap-2">
							<HugeiconsIcon icon={Settings01Icon} className="size-4" />
							{t("Project Settings")}
						</DropdownMenuItem>
						<DropdownMenuItem className="flex items-center gap-2">
							<HugeiconsIcon icon={Expand01Icon} className="size-4" />
							{t("Fullscreen Preview")}
						</DropdownMenuItem>
					</DropdownMenuContent>
				</DropdownMenu>
			</div>
		</header>
	);
}
```

- [ ] **Step 2: Commit**

```bash
git add apps/web/src/components/editor/mobile/mobile-header.tsx
git commit -m "feat(mobile): add mobile editor header with back, undo/redo, menu"
```

---

### Task 4: Mobile Preview

**Files:**
- Create: `apps/web/src/components/editor/mobile/mobile-preview.tsx`

Preview canvas with play/pause overlay. Reuses the existing `PreviewCanvas` rendering logic.

- [ ] **Step 1: Create mobile preview component**

```tsx
// apps/web/src/components/editor/mobile/mobile-preview.tsx
"use client";

import { useRef, useCallback } from "react";
import { useEditor } from "@/hooks/use-editor";
import { useRafLoop } from "@/hooks/use-raf-loop";
import { cn } from "@/utils/ui";
import { Play01Icon, Pause01Icon } from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";

export function MobilePreview() {
	const editor = useEditor();
	const canvasRef = useRef<HTMLCanvasElement>(null);
	const containerRef = useRef<HTMLDivElement>(null);

	useRafLoop(
		useCallback(
			({ time }: { time: number }) => {
				const canvas = canvasRef.current;
				if (!canvas) return;
				editor.renderer.renderFrame({ canvas, time });
			},
			[editor],
		),
	);

	const isPlaying = editor.playback.getIsPlaying();

	const handleTogglePlay = () => {
		if (isPlaying) {
			editor.playback.pause();
		} else {
			editor.playback.play();
		}
	};

	return (
		<div
			ref={containerRef}
			className="relative flex min-h-[30vh] flex-1 items-center justify-center overflow-hidden bg-black"
		>
			<canvas
				ref={canvasRef}
				className="max-h-full max-w-full object-contain"
			/>

			{/* Play/Pause overlay */}
			<button
				type="button"
				className={cn(
					"absolute inset-0 flex items-center justify-center",
					"bg-black/0 active:bg-black/10 transition-colors",
				)}
				onClick={handleTogglePlay}
				onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") handleTogglePlay(); }}
			>
				{!isPlaying && (
					<div className="flex size-14 items-center justify-center rounded-full bg-black/50">
						<HugeiconsIcon icon={Play01Icon} className="size-8 text-white" />
					</div>
				)}
			</button>
		</div>
	);
}
```

Note: The actual canvas rendering integration will need to match how `PreviewCanvas` in `apps/web/src/components/editor/panels/preview/index.tsx` (lines 320-432) initializes the canvas. The above is a structural scaffold — the canvas render call (`editor.renderer.renderFrame`) should be adapted to match the actual API in the existing `PreviewCanvas` component. Read that component and align the API during implementation.

- [ ] **Step 2: Commit**

```bash
git add apps/web/src/components/editor/mobile/mobile-preview.tsx
git commit -m "feat(mobile): add mobile preview canvas with play/pause overlay"
```

---

### Task 5: Timeline Scroll Hook

**Files:**
- Create: `apps/web/src/components/editor/mobile/hooks/use-timeline-scroll.ts`

Manages horizontal scroll position and zoom level for the mobile timeline. Playhead stays centered — content scrolls.

- [ ] **Step 1: Create timeline scroll hook**

```typescript
// apps/web/src/components/editor/mobile/hooks/use-timeline-scroll.ts
"use client";

import { useCallback, useRef } from "react";
import { useEditor } from "@/hooks/use-editor";
import { TIMELINE_CONSTANTS } from "@/constants/timeline-constants";

export function useTimelineScroll() {
	const editor = useEditor();
	const zoomRef = useRef(1);
	const lastPinchScaleRef = useRef(1);

	const pixelsPerSecond = TIMELINE_CONSTANTS.PIXELS_PER_SECOND;

	const timeToPixels = useCallback(
		({ time }: { time: number }) => {
			return time * pixelsPerSecond * zoomRef.current;
		},
		[pixelsPerSecond],
	);

	const pixelsToTime = useCallback(
		({ pixels }: { pixels: number }) => {
			return pixels / (pixelsPerSecond * zoomRef.current);
		},
		[pixelsPerSecond],
	);

	const handlePan = useCallback(
		({ deltaX }: { deltaX: number }) => {
			const timeDelta = pixelsToTime({ pixels: -deltaX });
			const currentTime = editor.playback.getCurrentTime();
			const newTime = Math.max(0, currentTime + timeDelta);
			editor.playback.seek({ time: newTime });
		},
		[editor, pixelsToTime],
	);

	const handlePinch = useCallback(
		({ scale }: { scale: number }) => {
			const newZoom = Math.max(
				TIMELINE_CONSTANTS.ZOOM_MIN,
				Math.min(
					TIMELINE_CONSTANTS.ZOOM_MAX,
					zoomRef.current * (scale / lastPinchScaleRef.current),
				),
			);
			zoomRef.current = newZoom;
			lastPinchScaleRef.current = scale;
		},
		[],
	);

	const handlePinchEnd = useCallback(() => {
		lastPinchScaleRef.current = 1;
	}, []);

	return {
		zoomRef,
		timeToPixels,
		pixelsToTime,
		handlePan,
		handlePinch,
		handlePinchEnd,
	};
}
```

- [ ] **Step 2: Commit**

```bash
git add apps/web/src/components/editor/mobile/hooks/use-timeline-scroll.ts
git commit -m "feat(mobile): add timeline scroll/zoom hook with centered playhead model"
```

---

### Task 6: Mobile Playhead

**Files:**
- Create: `apps/web/src/components/editor/mobile/mobile-timeline/mobile-playhead.tsx`

Fixed at horizontal center of the timeline viewport. A vertical line with a triangle indicator.

- [ ] **Step 1: Create mobile playhead component**

```tsx
// apps/web/src/components/editor/mobile/mobile-timeline/mobile-playhead.tsx
"use client";

export function MobilePlayhead() {
	return (
		<div
			className="pointer-events-none absolute top-0 bottom-0 left-1/2 z-30 w-px -translate-x-1/2"
			style={{ backgroundColor: "hsl(var(--primary))" }}
		>
			{/* Triangle indicator at top */}
			<div
				className="absolute -top-1 left-1/2 -translate-x-1/2"
				style={{
					width: 0,
					height: 0,
					borderLeft: "6px solid transparent",
					borderRight: "6px solid transparent",
					borderTop: "8px solid hsl(var(--primary))",
				}}
			/>
		</div>
	);
}
```

- [ ] **Step 2: Commit**

```bash
git add apps/web/src/components/editor/mobile/mobile-timeline/mobile-playhead.tsx
git commit -m "feat(mobile): add centered playhead indicator"
```

---

### Task 7: Mobile Track

**Files:**
- Create: `apps/web/src/components/editor/mobile/mobile-timeline/mobile-track.tsx`

Renders a single track's elements horizontally. Track height is 48px for touch-friendly targets.

- [ ] **Step 1: Create mobile track component**

```tsx
// apps/web/src/components/editor/mobile/mobile-timeline/mobile-track.tsx
"use client";

import { cn } from "@/utils/ui";
import { TRACK_COLORS } from "@/constants/timeline-constants";
import type { TimelineTrack, TimelineElement } from "@/types/timeline";
import { useEditor } from "@/hooks/use-editor";
import { useElementSelection } from "@/hooks/timeline/element/use-element-selection";

const MOBILE_TRACK_HEIGHT = 48;

export function MobileTrack({
	track,
	timeToPixels,
}: {
	track: TimelineTrack;
	timeToPixels: ({ time }: { time: number }) => number;
}) {
	const editor = useEditor();
	const { selectedElements, toggleElement } = useElementSelection();
	const colorConfig = TRACK_COLORS[track.type];

	return (
		<div
			className="relative shrink-0"
			style={{ height: MOBILE_TRACK_HEIGHT }}
		>
			{track.elements.map((element) => (
				<MobileTrackElement
					key={element.id}
					element={element}
					trackType={track.type}
					colorClass={colorConfig.background}
					isSelected={selectedElements.some((sel) => sel.id === element.id)}
					timeToPixels={timeToPixels}
					onTap={() => toggleElement({ elementId: element.id, trackId: track.id })}
				/>
			))}
		</div>
	);
}

function MobileTrackElement({
	element,
	trackType,
	colorClass,
	isSelected,
	timeToPixels,
	onTap,
}: {
	element: TimelineElement;
	trackType: string;
	colorClass: string;
	isSelected: boolean;
	timeToPixels: ({ time }: { time: number }) => number;
	onTap: () => void;
}) {
	const left = timeToPixels({ time: element.startTime });
	const width = timeToPixels({ time: element.duration });

	return (
		<button
			type="button"
			className={cn(
				"absolute top-1 bottom-1 rounded-md border text-xs overflow-hidden",
				colorClass,
				isSelected && "ring-2 ring-primary",
			)}
			style={{ left, width: Math.max(width, 20) }}
			onClick={onTap}
			onKeyDown={(e) => { if (e.key === "Enter") onTap(); }}
		>
			<span className="block truncate px-1.5 py-0.5 text-white/90">
				{trackType === "text"
					? ("content" in element ? (element as { content: string }).content : "Text")
					: element.name ?? trackType}
			</span>
		</button>
	);
}
```

Note: The `element.startTime`, `element.duration`, and `element.name` field names should be verified against the actual `TimelineElement` type in `apps/web/src/types/timeline.ts` during implementation. Also verify `useElementSelection` API from `apps/web/src/hooks/timeline/element/use-element-selection.ts`.

- [ ] **Step 2: Commit**

```bash
git add apps/web/src/components/editor/mobile/mobile-timeline/mobile-track.tsx
git commit -m "feat(mobile): add mobile track component with touch-friendly 48px height"
```

---

### Task 8: Mobile Timeline Container

**Files:**
- Create: `apps/web/src/components/editor/mobile/mobile-timeline/mobile-timeline.tsx`

The main timeline component. Horizontal scroll with centered playhead model. Integrates touch gestures for pan and pinch-zoom.

- [ ] **Step 1: Create mobile timeline component**

```tsx
// apps/web/src/components/editor/mobile/mobile-timeline/mobile-timeline.tsx
"use client";

import { useRef, useMemo } from "react";
import { useEditor } from "@/hooks/use-editor";
import { useTouchGestures } from "../hooks/use-touch-gestures";
import { useTimelineScroll } from "../hooks/use-timeline-scroll";
import { MobileTrack } from "./mobile-track";
import { MobilePlayhead } from "./mobile-playhead";
import { TRACK_GAP } from "@/constants/timeline-constants";
import { useMobileDrawerStore } from "../hooks/use-mobile-drawer";

export function MobileTimeline() {
	const editor = useEditor();
	const containerRef = useRef<HTMLDivElement>(null);
	const { zoomRef, timeToPixels, handlePan, handlePinch, handlePinchEnd } =
		useTimelineScroll();
	const { openDrawer } = useMobileDrawerStore();

	const activeScene = editor.scenes.getActive();
	const tracks = activeScene?.tracks ?? [];

	const totalDuration = useMemo(() => {
		let maxEnd = 0;
		for (const track of tracks) {
			for (const element of track.elements) {
				const end = element.startTime + element.duration;
				if (end > maxEnd) maxEnd = end;
			}
		}
		return maxEnd;
	}, [tracks]);

	useTouchGestures({
		ref: containerRef,
		handlers: {
			onPan: handlePan,
			onPinch: handlePinch,
			onTap: () => {
				// Tap on empty area: deselect
				editor.selection.clearSelection();
				useMobileDrawerStore.getState().closeDrawer();
			},
		},
	});

	const currentTime = editor.playback.getCurrentTime();
	const viewportCenterOffset = containerRef.current
		? containerRef.current.clientWidth / 2
		: 0;
	const scrollX = timeToPixels({ time: currentTime }) - viewportCenterOffset;

	return (
		<div
			ref={containerRef}
			className="relative h-[180px] overflow-hidden border-t bg-background"
		>
			{/* Scrolling content layer */}
			<div
				className="absolute top-0 left-0 h-full"
				style={{
					transform: `translateX(${-scrollX}px)`,
					willChange: "transform",
					width: timeToPixels({ time: totalDuration + 5 }),
				}}
			>
				<div
					className="flex flex-col pt-2"
					style={{ gap: TRACK_GAP }}
				>
					{tracks.map((track) => (
						<MobileTrack
							key={track.id}
							track={track}
							timeToPixels={timeToPixels}
						/>
					))}
				</div>
			</div>

			{/* Fixed-center playhead */}
			<MobilePlayhead />
		</div>
	);
}
```

Note: Verify `editor.scenes.getActive()`, `editor.playback.getCurrentTime()`, and `editor.selection.clearSelection()` APIs by reading `apps/web/src/core/index.ts` and the relevant managers during implementation. The `element.startTime` and `element.duration` fields should match the `TimelineElement` type.

- [ ] **Step 2: Commit**

```bash
git add apps/web/src/components/editor/mobile/mobile-timeline/mobile-timeline.tsx
git commit -m "feat(mobile): add mobile timeline with horizontal scroll and centered playhead"
```

---

### Task 9: Mobile Toolbar

**Files:**
- Create: `apps/web/src/components/editor/mobile/mobile-toolbar.tsx`

Bottom tab bar with 5 tabs: Assets, Text, Sticker, Audio, AI. Each tab toggles its corresponding drawer.

- [ ] **Step 1: Create mobile toolbar component**

```tsx
// apps/web/src/components/editor/mobile/mobile-toolbar.tsx
"use client";

import { cn } from "@/utils/ui";
import { useTranslation } from "@i18next-toolkit/nextjs-approuter";
import { useMobileDrawerStore } from "./hooks/use-mobile-drawer";
import {
	Folder03Icon,
	TextIcon,
	Happy01Icon,
	HeadphonesIcon,
	AiBrain01Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon, type IconSvgElement } from "@hugeicons/react";

type ToolbarTab = "assets" | "text" | "sticker" | "audio" | "ai";

const TOOLBAR_TABS: {
	id: ToolbarTab;
	labelKey: string;
	icon: IconSvgElement;
}[] = [
	{ id: "assets", labelKey: "Assets", icon: Folder03Icon },
	{ id: "text", labelKey: "Text", icon: TextIcon },
	{ id: "sticker", labelKey: "Stickers", icon: Happy01Icon },
	{ id: "audio", labelKey: "Audio", icon: HeadphonesIcon },
	{ id: "ai", labelKey: "AI", icon: AiBrain01Icon },
];

export function MobileToolbar() {
	const { t } = useTranslation();
	const { activeDrawer, toggleDrawer } = useMobileDrawerStore();

	return (
		<nav
			className="bg-background flex items-center justify-around border-t px-2 py-1.5 pb-[calc(0.375rem+env(safe-area-inset-bottom))]"
		>
			{TOOLBAR_TABS.map((tab) => {
				const isActive = activeDrawer === tab.id;
				return (
					<button
						key={tab.id}
						type="button"
						className={cn(
							"flex flex-col items-center gap-0.5 rounded-md px-3 py-1.5 text-xs",
							"active:bg-accent transition-colors",
							isActive
								? "text-primary"
								: "text-muted-foreground",
						)}
						onClick={() => toggleDrawer({ drawer: tab.id })}
						onKeyDown={(e) => {
							if (e.key === "Enter") toggleDrawer({ drawer: tab.id });
						}}
					>
						<HugeiconsIcon
							icon={tab.icon}
							className={cn("size-5", isActive && "text-primary")}
						/>
						<span>{t(tab.labelKey)}</span>
					</button>
				);
			})}
		</nav>
	);
}
```

- [ ] **Step 2: Commit**

```bash
git add apps/web/src/components/editor/mobile/mobile-toolbar.tsx
git commit -m "feat(mobile): add bottom toolbar with 5 tab buttons"
```

---

### Task 10: Mobile Drawer Components

**Files:**
- Create: `apps/web/src/components/editor/mobile/mobile-drawer/mobile-assets-drawer.tsx`
- Create: `apps/web/src/components/editor/mobile/mobile-drawer/mobile-properties-drawer.tsx`
- Create: `apps/web/src/components/editor/mobile/mobile-drawer/mobile-text-drawer.tsx`
- Create: `apps/web/src/components/editor/mobile/mobile-drawer/mobile-sticker-drawer.tsx`
- Create: `apps/web/src/components/editor/mobile/mobile-drawer/mobile-audio-drawer.tsx`
- Create: `apps/web/src/components/editor/mobile/mobile-drawer/mobile-ai-drawer.tsx`

Each drawer wraps desktop content inside a vaul Drawer. The `mobile-properties-drawer` auto-opens when a timeline element is selected.

- [ ] **Step 1: Create assets drawer**

```tsx
// apps/web/src/components/editor/mobile/mobile-drawer/mobile-assets-drawer.tsx
"use client";

import {
	Drawer,
	DrawerContent,
	DrawerHeader,
	DrawerTitle,
} from "@/components/ui/drawer";
import { useMobileDrawerStore } from "../hooks/use-mobile-drawer";
import { type Tab, useAssetsPanelStore } from "@/stores/assets-panel-store";
import { MediaView } from "@/components/editor/panels/assets/views/media";
import { SoundsView } from "@/components/editor/panels/assets/views/sounds";
import { StickersView } from "@/components/editor/panels/assets/views/stickers";
import { TransitionsView } from "@/components/editor/panels/assets/views/transitions";
import { Captions } from "@/components/editor/panels/assets/views/captions";
import { SettingsView } from "@/components/editor/panels/assets/views/settings";
import { useTranslation } from "@i18next-toolkit/nextjs-approuter";

export function MobileAssetsDrawer() {
	const { t } = useTranslation();
	const { activeDrawer, closeDrawer } = useMobileDrawerStore();
	const isOpen = activeDrawer === "assets";

	return (
		<Drawer open={isOpen} onOpenChange={(open) => { if (!open) closeDrawer(); }}>
			<DrawerContent className="max-h-[60vh]">
				<DrawerHeader>
					<DrawerTitle>{t("Assets")}</DrawerTitle>
				</DrawerHeader>
				<div className="overflow-y-auto px-4 pb-6">
					<MediaView />
				</div>
			</DrawerContent>
		</Drawer>
	);
}
```

- [ ] **Step 2: Create properties drawer (auto-opens on selection)**

```tsx
// apps/web/src/components/editor/mobile/mobile-drawer/mobile-properties-drawer.tsx
"use client";

import { useEffect } from "react";
import {
	Drawer,
	DrawerContent,
	DrawerHeader,
	DrawerTitle,
} from "@/components/ui/drawer";
import { useMobileDrawerStore } from "../hooks/use-mobile-drawer";
import { useElementSelection } from "@/hooks/timeline/element/use-element-selection";
import { PropertiesPanel } from "@/components/editor/panels/properties";
import { useTranslation } from "@i18next-toolkit/nextjs-approuter";

export function MobilePropertiesDrawer() {
	const { t } = useTranslation();
	const { activeDrawer, openDrawer, closeDrawer } = useMobileDrawerStore();
	const { selectedElements } = useElementSelection();
	const isOpen = activeDrawer === "properties";

	// Auto-open on selection, auto-close on deselection
	useEffect(() => {
		if (selectedElements.length > 0 && activeDrawer !== "properties") {
			openDrawer({ drawer: "properties" });
		}
		if (selectedElements.length === 0 && activeDrawer === "properties") {
			closeDrawer();
		}
	}, [selectedElements.length, activeDrawer, openDrawer, closeDrawer]);

	return (
		<Drawer open={isOpen} onOpenChange={(open) => { if (!open) closeDrawer(); }}>
			<DrawerContent className="max-h-[60vh]">
				<DrawerHeader>
					<DrawerTitle>{t("Properties")}</DrawerTitle>
				</DrawerHeader>
				<div className="overflow-y-auto px-4 pb-6">
					<PropertiesPanel />
				</div>
			</DrawerContent>
		</Drawer>
	);
}
```

- [ ] **Step 3: Create text drawer**

```tsx
// apps/web/src/components/editor/mobile/mobile-drawer/mobile-text-drawer.tsx
"use client";

import {
	Drawer,
	DrawerContent,
	DrawerHeader,
	DrawerTitle,
} from "@/components/ui/drawer";
import { useMobileDrawerStore } from "../hooks/use-mobile-drawer";
import { TextView } from "@/components/editor/panels/assets/views/text";
import { useTranslation } from "@i18next-toolkit/nextjs-approuter";

export function MobileTextDrawer() {
	const { t } = useTranslation();
	const { activeDrawer, closeDrawer } = useMobileDrawerStore();
	const isOpen = activeDrawer === "text";

	return (
		<Drawer open={isOpen} onOpenChange={(open) => { if (!open) closeDrawer(); }}>
			<DrawerContent className="max-h-[60vh]">
				<DrawerHeader>
					<DrawerTitle>{t("Text")}</DrawerTitle>
				</DrawerHeader>
				<div className="overflow-y-auto px-4 pb-6">
					<TextView />
				</div>
			</DrawerContent>
		</Drawer>
	);
}
```

- [ ] **Step 4: Create sticker drawer**

```tsx
// apps/web/src/components/editor/mobile/mobile-drawer/mobile-sticker-drawer.tsx
"use client";

import {
	Drawer,
	DrawerContent,
	DrawerHeader,
	DrawerTitle,
} from "@/components/ui/drawer";
import { useMobileDrawerStore } from "../hooks/use-mobile-drawer";
import { StickersView } from "@/components/editor/panels/assets/views/stickers";
import { useTranslation } from "@i18next-toolkit/nextjs-approuter";

export function MobileStickerDrawer() {
	const { t } = useTranslation();
	const { activeDrawer, closeDrawer } = useMobileDrawerStore();
	const isOpen = activeDrawer === "sticker";

	return (
		<Drawer open={isOpen} onOpenChange={(open) => { if (!open) closeDrawer(); }}>
			<DrawerContent className="max-h-[60vh]">
				<DrawerHeader>
					<DrawerTitle>{t("Stickers")}</DrawerTitle>
				</DrawerHeader>
				<div className="overflow-y-auto px-4 pb-6">
					<StickersView />
				</div>
			</DrawerContent>
		</Drawer>
	);
}
```

- [ ] **Step 5: Create audio drawer**

```tsx
// apps/web/src/components/editor/mobile/mobile-drawer/mobile-audio-drawer.tsx
"use client";

import {
	Drawer,
	DrawerContent,
	DrawerHeader,
	DrawerTitle,
} from "@/components/ui/drawer";
import { useMobileDrawerStore } from "../hooks/use-mobile-drawer";
import { SoundsView } from "@/components/editor/panels/assets/views/sounds";
import { useTranslation } from "@i18next-toolkit/nextjs-approuter";

export function MobileAudioDrawer() {
	const { t } = useTranslation();
	const { activeDrawer, closeDrawer } = useMobileDrawerStore();
	const isOpen = activeDrawer === "audio";

	return (
		<Drawer open={isOpen} onOpenChange={(open) => { if (!open) closeDrawer(); }}>
			<DrawerContent className="max-h-[60vh]">
				<DrawerHeader>
					<DrawerTitle>{t("Audio")}</DrawerTitle>
				</DrawerHeader>
				<div className="overflow-y-auto px-4 pb-6">
					<SoundsView />
				</div>
			</DrawerContent>
		</Drawer>
	);
}
```

- [ ] **Step 6: Create AI drawer**

```tsx
// apps/web/src/components/editor/mobile/mobile-drawer/mobile-ai-drawer.tsx
"use client";

import {
	Drawer,
	DrawerContent,
	DrawerHeader,
	DrawerTitle,
} from "@/components/ui/drawer";
import { useMobileDrawerStore } from "../hooks/use-mobile-drawer";
import { AIView } from "@/components/editor/panels/assets/views/ai";
import { useTranslation } from "@i18next-toolkit/nextjs-approuter";

export function MobileAIDrawer() {
	const { t } = useTranslation();
	const { activeDrawer, closeDrawer } = useMobileDrawerStore();
	const isOpen = activeDrawer === "ai";

	return (
		<Drawer open={isOpen} onOpenChange={(open) => { if (!open) closeDrawer(); }}>
			<DrawerContent className="max-h-[60vh]">
				<DrawerHeader>
					<DrawerTitle>{t("AI")}</DrawerTitle>
				</DrawerHeader>
				<div className="overflow-y-auto px-4 pb-6">
					<AIView />
				</div>
			</DrawerContent>
		</Drawer>
	);
}
```

- [ ] **Step 7: Commit all drawers**

```bash
git add apps/web/src/components/editor/mobile/mobile-drawer/
git commit -m "feat(mobile): add all 6 drawer components (assets, properties, text, sticker, audio, AI)"
```

---

### Task 11: Mobile Editor Layout

**Files:**
- Create: `apps/web/src/components/editor/mobile/mobile-editor-layout.tsx`

The root layout that assembles all mobile components: header, preview, timeline, drawers, and toolbar.

- [ ] **Step 1: Create mobile editor layout**

```tsx
// apps/web/src/components/editor/mobile/mobile-editor-layout.tsx
"use client";

import { MobileHeader } from "./mobile-header";
import { MobilePreview } from "./mobile-preview";
import { MobileTimeline } from "./mobile-timeline/mobile-timeline";
import { MobileToolbar } from "./mobile-toolbar";
import { MobileAssetsDrawer } from "./mobile-drawer/mobile-assets-drawer";
import { MobilePropertiesDrawer } from "./mobile-drawer/mobile-properties-drawer";
import { MobileTextDrawer } from "./mobile-drawer/mobile-text-drawer";
import { MobileStickerDrawer } from "./mobile-drawer/mobile-sticker-drawer";
import { MobileAudioDrawer } from "./mobile-drawer/mobile-audio-drawer";
import { MobileAIDrawer } from "./mobile-drawer/mobile-ai-drawer";

export function MobileEditorLayout() {
	return (
		<div className="flex h-full flex-col">
			<MobileHeader />
			<MobilePreview />
			<MobileTimeline />
			<MobileToolbar />

			{/* Drawer layer */}
			<MobileAssetsDrawer />
			<MobilePropertiesDrawer />
			<MobileTextDrawer />
			<MobileStickerDrawer />
			<MobileAudioDrawer />
			<MobileAIDrawer />
		</div>
	);
}
```

- [ ] **Step 2: Commit**

```bash
git add apps/web/src/components/editor/mobile/mobile-editor-layout.tsx
git commit -m "feat(mobile): add root mobile editor layout assembling all mobile components"
```

---

### Task 12: Wire Mobile Layout into Editor Page

**Files:**
- Modify: `apps/web/src/app/[locale]/editor/[project_id]/page.tsx`

Add `useIsMobile()` branch to render `MobileEditorLayout` on mobile devices.

- [ ] **Step 1: Update editor page with mobile branch**

In `apps/web/src/app/[locale]/editor/[project_id]/page.tsx`, modify the `Editor` component:

```tsx
// At the top, add imports:
import { useIsMobile } from "@/hooks/use-mobile";
import { lazy, Suspense } from "react";

const MobileEditorLayout = lazy(() =>
	import("@/components/editor/mobile/mobile-editor-layout").then((m) => ({
		default: m.MobileEditorLayout,
	})),
);
```

Replace the content inside `<EditorProvider>` (lines 27-34) with:

```tsx
<EditorProvider projectId={projectId}>
	<EditorShell />
</EditorProvider>
```

Add a new `EditorShell` component in the same file:

```tsx
function EditorShell() {
	const isMobile = useIsMobile();

	return (
		<div className="bg-background flex h-screen w-screen flex-col overflow-hidden">
			{isMobile ? (
				<Suspense fallback={<div className="flex h-screen items-center justify-center">Loading...</div>}>
					<MobileEditorLayout />
				</Suspense>
			) : (
				<>
					<EditorHeader />
					<div className="min-h-0 min-w-0 flex-1 px-3 pb-3">
						<EditorLayout />
					</div>
				</>
			)}
			<MigrationDialog />
		</div>
	);
}
```

- [ ] **Step 2: Verify desktop still works**

Run: `bun run dev:web`

Open desktop browser at `http://localhost:4100`, navigate to any project editor. Verify the desktop layout renders as before with no visual changes.

- [ ] **Step 3: Verify mobile renders**

Open browser DevTools, toggle mobile device simulation (e.g. iPhone 14, width 390px). Navigate to the same editor page. Verify:
- Mobile header appears with back button and project name
- Preview area shows
- Timeline area shows (may be empty if no tracks)
- Bottom toolbar with 5 tabs appears
- Tapping a toolbar tab opens the corresponding drawer

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/app/[locale]/editor/[project_id]/page.tsx
git commit -m "feat(mobile): wire mobile editor layout into page with lazy loading"
```

---

### Task 13: Safe Area and Viewport Meta

**Files:**
- Modify: `apps/web/src/app/layout.tsx`

Add `viewport-fit=cover` to support safe area insets on iOS.

- [ ] **Step 1: Update viewport meta**

In `apps/web/src/app/layout.tsx`, find the existing viewport configuration. If using Next.js metadata API, update:

```typescript
export const viewport: Viewport = {
	// ... existing config
	viewportFit: "cover",
};
```

If using a `<meta>` tag directly, ensure:

```html
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
```

- [ ] **Step 2: Commit**

```bash
git add apps/web/src/app/layout.tsx
git commit -m "feat(mobile): add viewport-fit=cover for safe area support"
```

---

### Task 14: Integration Testing and Polish

**Files:**
- All mobile components created in previous tasks

This is a manual verification and polish pass.

- [ ] **Step 1: Test drawer interactions**

In mobile simulation mode:
1. Tap "Assets" → assets drawer opens from bottom
2. Tap "Assets" again → drawer closes
3. Tap "Text" → text drawer opens, assets drawer was already closed
4. Tap "Audio" → audio drawer opens, text drawer closes (mutually exclusive)
5. Close all drawers

- [ ] **Step 2: Test timeline interactions**

1. Add a video clip to the timeline (via assets drawer)
2. Verify the clip appears as a colored block in the mobile timeline
3. Single-finger drag left/right → timeline scrolls (playhead stays centered)
4. Tap on a clip → clip highlights, properties drawer auto-opens
5. Tap empty area → clip deselects, properties drawer closes

- [ ] **Step 3: Test header**

1. Tap undo/redo buttons → verify they trigger undo/redo
2. Tap the overflow menu (⋮) → verify dropdown appears
3. Tap back arrow → navigates to projects page

- [ ] **Step 4: Fix any CSS overflow issues**

Common mobile issues to check:
- No horizontal scroll on the main page (only timeline should scroll)
- Drawers don't overflow the viewport
- Safe area padding visible on iPhone (simulator or real device)
- Bottom toolbar doesn't overlap with content

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat(mobile): polish mobile editor layout and fix CSS issues"
```

---

## Summary of Tasks

| Task | Component | Dependencies |
|------|-----------|-------------|
| 1 | Touch Gesture Hook | None |
| 2 | Mobile Drawer State Hook | None |
| 3 | Mobile Header | None |
| 4 | Mobile Preview | None |
| 5 | Timeline Scroll Hook | Task 1 |
| 6 | Mobile Playhead | None |
| 7 | Mobile Track | Task 5 |
| 8 | Mobile Timeline Container | Tasks 1, 5, 6, 7 |
| 9 | Mobile Toolbar | Task 2 |
| 10 | Mobile Drawer Components | Task 2 |
| 11 | Mobile Editor Layout | Tasks 3, 4, 8, 9, 10 |
| 12 | Wire into Editor Page | Task 11 |
| 13 | Safe Area / Viewport Meta | None |
| 14 | Integration Testing | Task 12 |

Tasks 1-4, 6, and 13 have no dependencies and can be implemented in parallel.

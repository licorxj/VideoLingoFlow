"use client";

import { useRef, useCallback } from "react";
import { useEditor } from "@/hooks/use-editor";
import { useRafLoop } from "@/hooks/use-raf-loop";
import { useTimelineScroll } from "../hooks/use-timeline-scroll";
import { useTouchGestures } from "../hooks/use-touch-gestures";
import { useMobileDrawerStore } from "../hooks/use-mobile-drawer";
import { MobileTrack } from "./mobile-track";
import { MobilePlayhead } from "./mobile-playhead";
import { cn } from "@/utils/ui";

const TIMELINE_HEIGHT = 180;
const CONTENT_END_PADDING_SECONDS = 2;

export function MobileTimeline() {
	const editor = useEditor();
	const containerRef = useRef<HTMLElement>(null);
	const translateXRef = useRef(0);
	const contentRef = useRef<HTMLDivElement>(null);
	const isDraggingElementRef = useRef(false);

	const { timeToPixels, pixelsToTime, handlePan, handlePinch } =
		useTimelineScroll();
	const closeDrawer = useMobileDrawerStore((s) => s.closeDrawer);

	const handleDragActiveChange = useCallback(
		({ active }: { active: boolean }) => {
			isDraggingElementRef.current = active;
		},
		[],
	);

	const getScrollX = useCallback(() => {
		const currentTime = editor.playback.getCurrentTime();
		const containerWidth = containerRef.current?.clientWidth ?? 0;
		return timeToPixels({ time: currentTime }) - containerWidth / 2;
	}, [editor, timeToPixels]);

	const getContentWidth = useCallback(() => {
		const duration = editor.timeline.getTotalDuration();
		const totalTime = duration + CONTENT_END_PADDING_SECONDS;
		return timeToPixels({ time: totalTime });
	}, [editor, timeToPixels]);

	// RAF loop keeps the translateX in sync with playback time
	useRafLoop(
		useCallback(() => {
			if (!contentRef.current) return;
			const scrollX = getScrollX();
			// Only write to DOM when value actually changed (avoid layout thrash)
			if (scrollX !== translateXRef.current) {
				translateXRef.current = scrollX;
				contentRef.current.style.transform = `translateX(${-scrollX}px)`;
			}
		}, [getScrollX]),
	);

	const guardedHandlePan = useCallback(
		({ deltaX }: { deltaX: number; deltaY: number }) => {
			if (isDraggingElementRef.current) return;
			handlePan({ deltaX });
		},
		[handlePan],
	);

	const guardedHandlePinch = useCallback(
		(params: { scale: number; centerX: number; centerY: number }) => {
			if (isDraggingElementRef.current) return;
			handlePinch(params);
		},
		[handlePinch],
	);

	useTouchGestures({
		ref: containerRef,
		handlers: {
			onPan: guardedHandlePan,
			onPinch: guardedHandlePinch,
			onTap: () => {
				if (isDraggingElementRef.current) return;
				editor.selection.clearSelection();
				closeDrawer();
			},
		},
	});

	const tracks = editor.timeline.getTracks();
	const contentWidth = getContentWidth();

	return (
		<section
			ref={containerRef}
			className={cn(
				"bg-background relative overflow-hidden border-t",
				"touch-none select-none",
			)}
			style={{ height: TIMELINE_HEIGHT }}
			aria-label="Timeline"
		>
			{/* Scrollable content layer */}
			<div
				ref={contentRef}
				className="absolute top-0 left-0 h-full overflow-y-auto overflow-x-visible"
				style={{
					width: contentWidth,
					willChange: "transform",
				}}
			>
				<div className="flex flex-col py-2">
					{tracks.map((track, index) => (
						<div key={track.id}>
							{index > 0 && <div className="bg-border mx-2 h-px" />}
							<MobileTrack
								track={track}
								timeToPixels={timeToPixels}
								pixelsToTime={pixelsToTime}
								containerRef={containerRef}
								onDragActiveChange={handleDragActiveChange}
							/>
						</div>
					))}
				</div>
			</div>

			{/* Centered playhead overlay */}
			<MobilePlayhead />
		</section>
	);
}

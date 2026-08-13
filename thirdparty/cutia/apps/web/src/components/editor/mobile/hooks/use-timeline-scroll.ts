"use client";

import { useRef, useCallback } from "react";
import { useEditor } from "@/hooks/use-editor";
import { TIMELINE_CONSTANTS } from "@/constants/timeline-constants";

interface TimelineScrollState {
	zoomLevel: number;
}

/**
 * Manages horizontal scroll position and zoom level for the mobile timeline.
 *
 * Uses a "centered playhead" model: the playhead stays fixed at screen center
 * and timeline content scrolls underneath. Panning converts pixel deltas to
 * time deltas and seeks the playhead. Pinch-zoom adjusts zoom within bounds.
 */
export function useTimelineScroll() {
	const editor = useEditor();

	const stateRef = useRef<TimelineScrollState>({
		zoomLevel: 1,
	});

	const timeToPixels = useCallback(({ time }: { time: number }): number => {
		return (
			time * TIMELINE_CONSTANTS.PIXELS_PER_SECOND * stateRef.current.zoomLevel
		);
	}, []);

	const pixelsToTime = useCallback(({ pixels }: { pixels: number }): number => {
		return (
			pixels /
			(TIMELINE_CONSTANTS.PIXELS_PER_SECOND * stateRef.current.zoomLevel)
		);
	}, []);

	const handlePan = useCallback(
		({ deltaX }: { deltaX: number }) => {
			const timeDelta = pixelsToTime({ pixels: -deltaX });
			const currentTime = editor.playback.getCurrentTime();
			const newTime = currentTime + timeDelta;
			editor.playback.seek({ time: Math.max(0, newTime) });
		},
		[editor, pixelsToTime],
	);

	const handlePinch = useCallback(({ scale }: { scale: number }) => {
		const state = stateRef.current;
		const newZoom = state.zoomLevel * scale;
		state.zoomLevel = Math.min(
			TIMELINE_CONSTANTS.ZOOM_MAX,
			Math.max(TIMELINE_CONSTANTS.ZOOM_MIN, newZoom),
		);
	}, []);

	const getZoomLevel = useCallback((): number => {
		return stateRef.current.zoomLevel;
	}, []);

	const setZoomLevel = useCallback(({ zoomLevel }: { zoomLevel: number }) => {
		stateRef.current.zoomLevel = Math.min(
			TIMELINE_CONSTANTS.ZOOM_MAX,
			Math.max(TIMELINE_CONSTANTS.ZOOM_MIN, zoomLevel),
		);
	}, []);

	return {
		timeToPixels,
		pixelsToTime,
		handlePan,
		handlePinch,
		getZoomLevel,
		setZoomLevel,
	};
}

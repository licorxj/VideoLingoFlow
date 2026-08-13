"use client";

import { useRef, useEffect, useCallback } from "react";

interface TouchGestureHandlers {
	onPan?: ({ deltaX, deltaY }: { deltaX: number; deltaY: number }) => void;
	onPinch?: ({
		scale,
		centerX,
		centerY,
	}: {
		scale: number;
		centerX: number;
		centerY: number;
	}) => void;
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

function getDistance({
	touchA,
	touchB,
}: {
	touchA: Touch;
	touchB: Touch;
}): number {
	const dx = touchA.clientX - touchB.clientX;
	const dy = touchA.clientY - touchB.clientY;
	return Math.sqrt(dx * dx + dy * dy);
}

function getAngle({
	touchA,
	touchB,
}: {
	touchA: Touch;
	touchB: Touch;
}): number {
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
						handlersRef.current.onLongPress?.({
							x: touch.clientX,
							y: touch.clientY,
						});
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
					handlersRef.current.onPinch({
						scale,
						centerX,
						centerY,
					});
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

			if (
				e.touches.length === 0 &&
				!state.isPanning &&
				state.startTouches.length === 1
			) {
				const touch = state.startTouches[0];
				const now = Date.now();

				if (now - state.lastTapTime < doubleTapInterval) {
					handlersRef.current.onDoubleTap?.({
						x: touch.clientX,
						y: touch.clientY,
					});
					state.lastTapTime = 0;
				} else {
					handlersRef.current.onTap?.({
						x: touch.clientX,
						y: touch.clientY,
					});
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

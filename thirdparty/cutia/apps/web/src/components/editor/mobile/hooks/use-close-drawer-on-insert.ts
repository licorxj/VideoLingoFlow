"use client";

import { useRef, useEffect } from "react";
import { useEditor } from "@/hooks/use-editor";
import { useMobileDrawerStore } from "./use-mobile-drawer";

/**
 * Closes the active mobile drawer when a new element is inserted into the
 * timeline. Works by tracking total element count — when it increases while
 * a content drawer (not properties) is open, the drawer is dismissed.
 */
export function useCloseDrawerOnInsert() {
	const editor = useEditor();
	const { activeDrawer, closeDrawer } = useMobileDrawerStore();
	const tracks = editor.timeline.getTracks();

	const elementCount = tracks.reduce(
		(sum, track) => sum + track.elements.length,
		0,
	);
	const prevCountRef = useRef(elementCount);

	useEffect(() => {
		const prev = prevCountRef.current;
		prevCountRef.current = elementCount;

		if (
			elementCount > prev &&
			activeDrawer !== null &&
			activeDrawer !== "properties"
		) {
			closeDrawer();
		}
	}, [elementCount, activeDrawer, closeDrawer]);
}

"use client";

export function MobilePlayhead() {
	return (
		<div
			className="bg-foreground pointer-events-none absolute top-0 bottom-0 left-1/2 z-30 -translate-x-1/2"
			style={{ width: 2 }}
		>
			{/* Circle indicator at top, matching desktop */}
			<div className="bg-foreground border-foreground/50 absolute top-1 left-1/2 size-3 -translate-x-1/2 rounded-full border-2 shadow-xs" />
		</div>
	);
}

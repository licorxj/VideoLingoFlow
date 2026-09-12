"use client";

import * as ResizablePrimitive from "react-resizable-panels";

import { cn } from "@/utils/ui";

const ResizablePanelGroup = ({
	className,
	...props
}: React.ComponentProps<typeof ResizablePrimitive.PanelGroup>) => (
	<ResizablePrimitive.PanelGroup
		className={cn(
			"flex size-full data-[panel-group-direction=vertical]:flex-col",
			className,
		)}
		{...props}
	/>
);

const ResizablePanel = ResizablePrimitive.Panel;

const ResizableHandle = ({
	withHandle,
	className,
	...props
}: React.ComponentProps<typeof ResizablePrimitive.PanelResizeHandle> & {
	withHandle?: boolean;
}) => (
	<ResizablePrimitive.PanelResizeHandle
		className={cn(
			"group relative flex w-px items-center justify-center bg-transparent",
			"after:absolute after:inset-y-0 after:left-1/2 after:w-1.5 after:-translate-x-1/2",
			"after:rounded-full after:transition-colors after:duration-150",
			"hover:after:bg-primary/20 active:after:bg-primary/30",
			"data-[panel-group-direction=vertical]:h-px data-[panel-group-direction=vertical]:w-full",
			"data-[panel-group-direction=vertical]:after:left-0 data-[panel-group-direction=vertical]:after:h-1.5",
			"data-[panel-group-direction=vertical]:after:w-full data-[panel-group-direction=vertical]:after:translate-x-0",
			"data-[panel-group-direction=vertical]:after:-translate-y-1/2",
			"[&[data-panel-group-direction=vertical]>div]:rotate-90",
			className,
		)}
		{...props}
	>
		{withHandle && (
			<div
				className={cn(
					"z-10 flex h-3 w-3 items-center justify-center rounded-full",
					"bg-border opacity-0 transition-all duration-150",
					"group-hover:opacity-100 group-hover:bg-primary group-hover:shadow-[0_0_0_4px_rgba(124,58,237,0.18)]",
					"group-data-[panel-group-direction=vertical]:rotate-90",
				)}
			/>
		)}
	</ResizablePrimitive.PanelResizeHandle>
);

export { ResizablePanelGroup, ResizablePanel, ResizableHandle };

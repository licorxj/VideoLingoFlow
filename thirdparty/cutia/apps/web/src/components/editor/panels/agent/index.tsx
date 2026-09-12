"use client";

import { AgentView } from "../assets/views/agent/agent-view";

export function AgentPanel() {
	return (
		<div
			className="panel bg-background flex h-full flex-col overflow-hidden rounded-xl border border-border/60 select-text shadow-[var(--shadow-panel)]"
			data-keybinding-free
		>
			<AgentView />
		</div>
	);
}
